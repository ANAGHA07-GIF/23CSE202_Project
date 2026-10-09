import os

from datetime import datetime, date

from functools import wraps

from flask import Flask, jsonify, request, session, send_from_directory

import psycopg2

from psycopg2.extras import RealDictCursor

from werkzeug.security import generate_password_hash, check_password_hash



app = Flask(__name__, static_folder="static")

app.secret_key = os.getenv("FLASK_SECRET_KEY", "change-this-secret-key-before-deployment")

app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")



DATABASE_URL = os.getenv("DATABASE_URL")

DB_CONFIG = {

    "host": os.getenv("PGHOST", "localhost"),

    "port": os.getenv("PGPORT", "5432"),

    "dbname": os.getenv("PGDATABASE", "canteen_db_new"),

    "user": os.getenv("PGUSER", "postgres"),

    "password": os.getenv("PGPASSWORD", ""),

}



def get_conn():

    if DATABASE_URL:

        return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

    return psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)



def query(sql, params=(), one=False, commit=False):

    conn = get_conn()

    try:

        with conn.cursor() as cur:

            cur.execute(sql, params)

            result = cur.fetchone() if one else (cur.fetchall() if cur.description else None)

        if commit: conn.commit()

        return result

    except Exception:

        conn.rollback()

        raise

    finally:

        conn.close()



def api_error(message, status=400):

    return jsonify(error=message), status



def current_user():

    return session.get("user")



def require_roles(*roles):

    def decorator(fn):

        @wraps(fn)

        def wrapped(*args, **kwargs):

            user = current_user()

            if not user:

                return api_error("Please log in first.", 401)

            if roles and user["role"] not in roles:

                return api_error("You do not have permission to do that.", 403)

            return fn(*args, **kwargs)

        return wrapped

    return decorator



def rowdict(row):

    if not row: return None

    return dict(row)



@app.get("/")

def home():

    return send_from_directory("static", "index.html")



@app.get("/<path:page>")

def pages(page):

    allowed = {"index.html", "login.html", "register.html", "student.html", "staff.html", "admin.html", "style.css"}

    if page in allowed:

        return send_from_directory("static", page)

    return ("Not found", 404)



@app.get("/api/health")

def health():

    try:

        query("SELECT 1", one=True)

        return jsonify(status="ok", database="connected")

    except Exception as exc:

        app.logger.exception("Database health check failed")

        return api_error("Database connection failed. Check PostgreSQL settings.", 503)



@app.post("/api/auth/register")

def register():

    data = request.get_json(silent=True) or {}

    name, roll, email, password = (str(data.get(k, "")).strip() for k in ("name","roll_no","email","password"))

    if not all([name, roll, email, password]): return api_error("Fill in all fields.")

    if len(password) < 6: return api_error("Password must be at least 6 characters.")

    try:

        row = query("""INSERT INTO students(roll_no,name,email,password_hash)

                       VALUES(%s,%s,%s,%s) RETURNING student_id,roll_no,name,email""",

                    (roll, name, email.lower(), generate_password_hash(password)), one=True, commit=True)

        session["user"] = {"id": row["student_id"], "identifier": row["roll_no"], "name": row["name"], "role": "student"}

        return jsonify(message="Account created", user=session["user"]), 201

    except psycopg2.errors.UniqueViolation:

        return api_error("That roll number or email is already registered.", 409)

    except Exception:

        app.logger.exception("Registration failed")

        return api_error("Could not create account. Check the database setup.", 500)



@app.post("/api/auth/login")

def login():

    data = request.get_json(silent=True) or {}

    role = str(data.get("userType","")).lower()

    identifier, password = str(data.get("identifier","")).strip(), str(data.get("password",""))

    if role not in ("student","staff","admin"): return api_error("Choose a valid role.")

    if not identifier or not password: return api_error("Enter both fields to continue.")

    try:

        if role == "student":

            row = query("SELECT student_id AS id, roll_no AS identifier, name, password_hash FROM students WHERE lower(roll_no)=lower(%s)", (identifier,), one=True)

        else:

            row = query("SELECT staff_id AS id, staff_code AS identifier, name, password_hash, role AS account_role FROM staff WHERE lower(staff_code)=lower(%s)", (identifier,), one=True)

            if row and row.get("account_role") != role: row = None

        if not row or not check_password_hash(row["password_hash"], password):

            return api_error("Invalid ID/password or role.", 401)

        session.clear()

        session["user"] = {"id": row["id"], "identifier": row["identifier"], "name": row["name"], "role": role}

        return jsonify(message="Logged in", user=session["user"])

    except Exception:

        app.logger.exception("Login failed")

        return api_error("Login failed. Check the database setup.", 500)



@app.get("/api/auth/me")

def me():

    user = current_user()

    return (jsonify(user), 200) if user else api_error("Not logged in.", 401)



@app.post("/api/auth/logout")

def logout():

    session.clear()

    return jsonify(message="Logged out")



@app.get("/api/menu")

def menu():

    rows = query("""SELECT item_id,name,category,price::float AS price,prep_time_min,daily_stock,

                    ready_quantity,is_available FROM menu_items ORDER BY category,name""")

    return jsonify(rows)



@app.get("/api/menu/wait-time")
def wait_time():
    """Estimate queue wait from active order item preparation work and active kitchen capacity."""
    row = query("""SELECT COALESCE(CEIL(
                       COALESCE(SUM(oi.quantity * mi.prep_time_min), 0)::numeric /
                       GREATEST(COALESCE((SELECT active_cooks FROM kitchen_capacity ORDER BY capacity_id LIMIT 1), 1), 1)
                   ), 0)::int AS minutes,
                   COUNT(DISTINCT o.order_id)::int AS active_orders
                FROM orders o
                JOIN order_items oi ON oi.order_id=o.order_id
                JOIN menu_items mi ON mi.item_id=oi.item_id
                WHERE o.status IN ('Placed','Preparing')""", one=True)
    return jsonify(minutes=(row or {}).get("minutes", 0), active_orders=(row or {}).get("active_orders", 0))


@app.post("/api/orders")
@require_roles("student")
def create_order():
    """Create an order atomically: validate slot, lock stock, write order/items, decrement stock."""
    data = request.get_json(silent=True) or {}
    items = data.get("items")
    if not isinstance(items, list) or not items:
        return api_error("Add at least one menu item.")
    try:
        # Merge duplicate item IDs and validate input before opening the transaction.
        quantities = {}
        for item in items:
            item_id = int(item.get("item_id", 0))
            qty = int(item.get("quantity", 0))
            if item_id <= 0 or qty <= 0:
                raise ValueError("Each item must have a valid ID and quantity of at least one.")
            quantities[item_id] = quantities.get(item_id, 0) + qty
        if len(quantities) > 30:
            raise ValueError("An order can contain at most 30 distinct menu items.")
        order_type = str(data.get("order_type", "preorder")).strip().lower()
        if order_type not in ("preorder", "walkin"):
            raise ValueError("Invalid order type.")
        pickup_slot = str(data.get("pickup_slot", "")).strip()[:80]
        if order_type == "preorder" and not pickup_slot:
            raise ValueError("Choose a pickup time slot.")
    except (TypeError, ValueError, AttributeError) as exc:
        return api_error(str(exc) or "Invalid order details.")

    user = current_user()
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            # Serialize slot capacity checks so two simultaneous requests cannot overbook a slot.
            cur.execute("SELECT max_parallel_orders FROM kitchen_capacity ORDER BY capacity_id LIMIT 1 FOR UPDATE")
            capacity = cur.fetchone()
            slot_capacity = int(capacity["max_parallel_orders"]) if capacity else 10
            if order_type == "preorder":
                cur.execute("""SELECT COUNT(*) AS n FROM orders
                               WHERE pickup_slot=%s AND status IN ('Placed','Preparing','Ready')""", (pickup_slot,))
                # PostgreSQL aggregate row locking is not supported; the kitchen_capacity row lock
                # above serializes this check and order creation.
                slot_count = cur.fetchone()["n"]
                if slot_count >= slot_capacity:
                    raise ValueError("That pickup slot is full. Please choose another slot.")

            normalized = []
            total = 0
            # Lock menu rows in ascending ID order to reduce deadlock risk.
            for item_id in sorted(quantities):
                qty = quantities[item_id]
                cur.execute("""SELECT item_id,name,price,daily_stock,is_available,prep_time_min
                               FROM menu_items WHERE item_id=%s FOR UPDATE""", (item_id,))
                menu_item = cur.fetchone()
                if not menu_item or not menu_item["is_available"] or menu_item["daily_stock"] < qty:
                    raise ValueError("An item is unavailable or has insufficient stock. Refresh the menu and try again.")
                normalized.append((menu_item, qty))
                total += menu_item["price"] * qty

            cur.execute("""INSERT INTO orders(student_id,status,total_amount,pickup_slot,order_type,placed_at)
                           VALUES(%s,'Placed',%s,%s,%s,NOW())
                           RETURNING order_id,status,total_amount,placed_at""",
                        (user["id"], total, pickup_slot or None, order_type))
            order = cur.fetchone()
            for menu_item, qty in normalized:
                cur.execute("""INSERT INTO order_items(order_id,item_id,quantity,unit_price)
                               VALUES(%s,%s,%s,%s)""",
                            (order["order_id"], menu_item["item_id"], qty, menu_item["price"]))
                cur.execute("UPDATE menu_items SET daily_stock=daily_stock-%s WHERE item_id=%s",
                            (qty, menu_item["item_id"]))
            # Transaction commits only after order and all lines/stock updates succeed.
        conn.commit()
        return jsonify({**dict(order), "total_amount": float(order["total_amount"])}), 201
    except ValueError as exc:
        conn.rollback()
        return api_error(str(exc))
    except Exception:
        conn.rollback()
        app.logger.exception("Order creation failed; transaction rolled back")
        return api_error("Could not place order. No partial order or stock update was saved.", 500)
    finally:
        conn.close()


@app.get("/api/student/orders")

@require_roles("student")

def student_orders():

    rows = query("""SELECT o.order_id,o.placed_at,o.status,o.total_amount::float AS total_amount,

                    COALESCE(string_agg(oi.quantity::text || '× ' || mi.name, ', ' ORDER BY mi.name),'') AS items_summary

                    FROM orders o LEFT JOIN order_items oi ON oi.order_id=o.order_id

                    LEFT JOIN menu_items mi ON mi.item_id=oi.item_id

                    WHERE o.student_id=%s GROUP BY o.order_id ORDER BY o.placed_at DESC""",(current_user()["id"],))

    return jsonify(rows)




@app.delete("/api/student/account")
@require_roles("student")
def delete_student_account():
    user = current_user()
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE orders SET student_id=NULL WHERE student_id=%s", (user["id"],))
            cur.execute("DELETE FROM students WHERE student_id=%s", (user["id"],))
            if cur.rowcount != 1:
                conn.rollback()
                return api_error("Student account not found.", 404)
        conn.commit()
        session.clear()
        return jsonify(message="Account deleted. Order history is retained without personal account details.")
    except Exception:
        conn.rollback()
        app.logger.exception("Student account deletion failed")
        return api_error("Could not delete the account. Check the database migration and try again.", 500)
    finally:
        conn.close()


@app.patch("/api/student/orders/<int:order_id>/cancel")
@require_roles("student")
def cancel_student_order(order_id):
    """Cancel only an unstarted order and restore its stock in the same transaction."""
    user = current_user()
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT status FROM orders WHERE order_id=%s AND student_id=%s FOR UPDATE",
                        (order_id, user["id"]))
            order = cur.fetchone()
            if not order:
                conn.rollback()
                return api_error("Order not found for your account.", 404)
            if order["status"] != "Placed":
                conn.rollback()
                return api_error("Only orders with status Placed can be cancelled. Cancellation is unavailable after preparation starts.", 409)
            cur.execute("SELECT item_id,quantity FROM order_items WHERE order_id=%s ORDER BY item_id", (order_id,))
            lines = cur.fetchall()
            # Lock and restore inventory, then update status. Any failure rolls back both operations.
            for line in lines:
                cur.execute("UPDATE menu_items SET daily_stock=daily_stock+%s WHERE item_id=%s",
                            (line["quantity"], line["item_id"]))
                if cur.rowcount != 1:
                    raise RuntimeError("A menu item referenced by this order no longer exists.")
            cur.execute("UPDATE orders SET status='Cancelled' WHERE order_id=%s AND status='Placed'",
                        (order_id,))
            if cur.rowcount != 1:
                raise RuntimeError("Order status changed while cancelling.")
        conn.commit()
        return jsonify(message="Order cancelled and stock restored.", status="Cancelled")
    except Exception:
        conn.rollback()
        app.logger.exception("Order cancellation failed; transaction rolled back")
        return api_error("Could not cancel the order. No partial stock or status changes were saved.", 500)
    finally:
        conn.close()


@app.get("/api/staff/queue")

@require_roles("staff","admin")

def staff_queue():

    rows = query("""SELECT o.order_id,o.status,o.pickup_slot,o.order_type,o.placed_at,

                    COALESCE(string_agg(oi.quantity::text || '× ' || mi.name, ', ' ORDER BY mi.name),'') AS items_summary

                    FROM orders o LEFT JOIN order_items oi ON oi.order_id=o.order_id

                    LEFT JOIN menu_items mi ON mi.item_id=oi.item_id

                    WHERE o.placed_at::date=CURRENT_DATE AND o.status <> 'Cancelled'

                    GROUP BY o.order_id ORDER BY CASE WHEN o.order_type='preorder' THEN 0 ELSE 1 END,o.placed_at""")

    return jsonify(rows)



@app.patch("/api/staff/orders/<int:order_id>/status")

@require_roles("staff","admin")

def update_status(order_id):

    data = request.get_json(silent=True) or {}

    status = data.get("status")

    allowed = {"Placed":"Preparing","Preparing":"Ready","Ready":"Collected"}

    try:

        with get_conn() as conn:

            with conn.cursor() as cur:

                cur.execute("SELECT status FROM orders WHERE order_id=%s FOR UPDATE",(order_id,))

                row=cur.fetchone()

                if not row: return api_error("Order not found.",404)

                if allowed.get(row["status"]) != status: return api_error("Invalid status transition.")

                cur.execute("UPDATE orders SET status=%s WHERE order_id=%s",(status,order_id))

        return jsonify(message="Status updated",status=status)

    except Exception:

        app.logger.exception("Status update failed")

        return api_error("Could not update order status.",500)



@app.post("/api/admin/menu")

@require_roles("admin")

def add_menu_item():

    d=request.get_json(silent=True) or {}

    try:

        row=query("""INSERT INTO menu_items(name,category,price,prep_time_min,daily_stock,ready_quantity,is_available)

                     VALUES(%s,%s,%s,%s,%s,%s,%s)

                     RETURNING item_id,name,category,price::float AS price,prep_time_min,daily_stock,ready_quantity,is_available""",

                  (d["name"].strip(),d["category"],float(d["price"]),int(d["prep_time_min"]),max(0,int(d.get("daily_stock",0))),max(0,int(d.get("ready_quantity",0))),int(d.get("daily_stock",0))>0),one=True,commit=True)

        return jsonify(row),201

    except (KeyError,ValueError,TypeError): return api_error("Enter valid menu item details.")

    except Exception:

        app.logger.exception("Add item failed")

        return api_error("Could not add menu item.",500)



@app.put("/api/admin/menu/<int:item_id>")

@require_roles("admin")

def update_menu_item(item_id):

    d=request.get_json(silent=True) or {}

    if "daily_stock" not in d: return api_error("daily_stock is required.")

    try:

        row=query("""UPDATE menu_items SET daily_stock=%s,is_available=(%s>0)

                     WHERE item_id=%s RETURNING item_id,daily_stock,is_available""",

                  (max(0,int(d["daily_stock"])),max(0,int(d["daily_stock"])),item_id),one=True,commit=True)

        return (jsonify(row),200) if row else api_error("Menu item not found.",404)

    except Exception:

        app.logger.exception("Stock update failed")

        return api_error("Could not update stock.",500)



@app.post("/api/admin/accounts")

@require_roles("admin")

def create_staff_account():

    """Allow an authenticated admin to create staff or additional admin accounts."""

    data = request.get_json(silent=True) or {}

    name = str(data.get("name", "")).strip()

    staff_code = str(data.get("staff_code", "")).strip()

    role = str(data.get("role", "")).strip().lower()

    password = str(data.get("password", ""))



    if not all([name, staff_code, role, password]):

        return api_error("Fill in all fields.")

    if role not in ("staff", "admin"):

        return api_error("Role must be staff or admin.")

    if len(password) < 6:

        return api_error("Password must be at least 6 characters.")



    try:

        row = query(

            """INSERT INTO staff(staff_code, name, role, password_hash)

               VALUES(%s, %s, %s, %s)

               RETURNING staff_id, staff_code, name, role, created_at""",

            (staff_code, name, role, generate_password_hash(password)),

            one=True, commit=True

        )

        return jsonify(message="Account created successfully.", account=row), 201

    except psycopg2.errors.UniqueViolation:

        return api_error("That staff/admin ID already exists. Choose another ID.", 409)

    except Exception:

        app.logger.exception("Staff/admin account creation failed")

        return api_error("Could not create the account. Check the server logs.", 500)




@app.get("/api/admin/accounts")
@require_roles("admin")
def list_staff_accounts():
    return jsonify(query("SELECT staff_id, staff_code, name, role, created_at FROM staff ORDER BY role, name"))


@app.delete("/api/admin/accounts/<int:staff_id>")
@require_roles("admin")
def delete_staff_account(staff_id):
    user = current_user()
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT staff_id, role FROM staff WHERE staff_id=%s FOR UPDATE", (staff_id,))
            target = cur.fetchone()
            if not target:
                conn.rollback()
                return api_error("Account not found.", 404)
            if target["staff_id"] == user["id"]:
                conn.rollback()
                return api_error("You cannot delete the account you are currently using.", 409)
            if target["role"] == "admin":
                cur.execute("SELECT COUNT(*) AS n FROM staff WHERE role='admin'")
                if cur.fetchone()["n"] <= 1:
                    conn.rollback()
                    return api_error("The last administrator account cannot be deleted.", 409)
            cur.execute("DELETE FROM staff WHERE staff_id=%s", (staff_id,))
        conn.commit()
        return jsonify(message="Account deleted.")
    except Exception:
        conn.rollback()
        app.logger.exception("Staff/admin account deletion failed")
        return api_error("Could not delete the account.", 500)
    finally:
        conn.close()


@app.delete("/api/admin/menu/<int:item_id>")
@require_roles("admin")
def delete_menu_item(item_id):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT item_id FROM menu_items WHERE item_id=%s FOR UPDATE", (item_id,))
            if not cur.fetchone():
                conn.rollback()
                return api_error("Menu item not found.", 404)
            cur.execute("SELECT EXISTS(SELECT 1 FROM order_items WHERE item_id=%s) AS used", (item_id,))
            if cur.fetchone()["used"]:
                conn.rollback()
                return api_error("This item is in order history and cannot be permanently deleted. Set stock to 0 to make it unavailable.", 409)
            cur.execute("DELETE FROM menu_items WHERE item_id=%s", (item_id,))
        conn.commit()
        return jsonify(message="Menu item deleted.")
    except Exception:
        conn.rollback()
        app.logger.exception("Menu item deletion failed")
        return api_error("Could not delete menu item.", 500)
    finally:
        conn.close()

@app.get("/api/admin/reports/popular-items")

@require_roles("admin")

def popular_items():

    rows=query("""SELECT mi.name,
                         COALESCE(SUM(CASE WHEN o.order_id IS NOT NULL AND o.status <> 'Cancelled'
                                           THEN oi.quantity ELSE 0 END),0)::int AS times_ordered
                  FROM menu_items mi
                  LEFT JOIN order_items oi ON oi.item_id=mi.item_id
                  LEFT JOIN orders o ON o.order_id=oi.order_id
                                      AND o.placed_at >= NOW()-INTERVAL '7 days'
                  GROUP BY mi.item_id ORDER BY times_ordered DESC,mi.name LIMIT 10""")

    return jsonify(rows)



@app.get("/api/admin/reports/summary")

@require_roles("admin")

def report_summary():

    row=query("""SELECT COALESCE(SUM(total_amount),0)::float AS sales_today,

                 COUNT(*)::int AS orders_today,

                 (SELECT EXTRACT(HOUR FROM placed_at)::int FROM orders WHERE placed_at::date=CURRENT_DATE AND status <> 'Cancelled'

                  GROUP BY EXTRACT(HOUR FROM placed_at) ORDER BY COUNT(*) DESC LIMIT 1) AS peak_hour,

                 (SELECT ROUND(AVG(EXTRACT(EPOCH FROM (l.changed_at-o.placed_at))/60)::numeric,1)::float

                  FROM orders o JOIN order_status_log l ON l.order_id=o.order_id

                  WHERE o.status IN ('Ready','Collected') AND l.new_status='Ready') AS avg_prep

                 FROM orders WHERE placed_at::date=CURRENT_DATE AND status <> 'Cancelled'""",one=True)

    return jsonify(salesToday=row["sales_today"],ordersToday=row["orders_today"],peakHour=row["peak_hour"],avgPrepMinutes=row["avg_prep"])



@app.get("/api/admin/reports/orders-by-hour")

@require_roles("admin")

def orders_by_hour():

    return jsonify(query("""SELECT EXTRACT(HOUR FROM placed_at)::int AS hour,COUNT(*)::int AS count

                            FROM orders WHERE placed_at::date=CURRENT_DATE AND status <> 'Cancelled'

                            GROUP BY hour ORDER BY hour"""))



if __name__ == "__main__":

    app.run(debug=True, port=int(os.getenv("PORT", "5000")))
