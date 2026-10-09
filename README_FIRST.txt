CAMPUS CANTEEN — FINAL FLASK + POSTGRESQL PROJECT

This package includes the Flask backend, existing frontend styling, student ordering and cancellation, estimated queue wait, pickup-slot capacity checks, staff queue/status updates, admin menu management, admin/staff account management, reports, schema/migration files, and transaction-integrity examples.

IMPORTANT DATABASE SAFETY
- This project defaults to the separate database named canteen_db_new.
- It is intended to leave your old canteen_db database untouched.
- In pgAdmin, create canteen_db_new if you have not already created it.
- Do not change PGDATABASE to canteen_db unless you intentionally want to use that database.
- Back up canteen_db_new before running a migration against an existing database.

SETUP — WINDOWS / VS CODE
1. Extract this ZIP and open the Campus_Canteen_Final folder in VS Code.
2. In pgAdmin 4, create a PostgreSQL database named canteen_db_new (only if it does not already exist).
3. For a NEW/EMPTY canteen_db_new database: open schema.sql in pgAdmin Query Tool connected to canteen_db_new and execute it once. It creates the tables, triggers, kitchen capacity row and sample menu items. Do not run the schema on your old canteen_db database.
4. If canteen_db_new already contains the project tables/data, do NOT rerun schema.sql. Back up the database first. The status constraint may already include Cancelled; only run migration_cancel_delete.sql if you need to align the existing database with the current schema. It enables Cancelled orders, nullable student_id, and useful indexes while retaining order history. The migration is designed to be repeatable, but always back up first.
5. In the project folder, open PowerShell and run:
     python -m venv .venv
     .\.venv\Scripts\Activate.ps1
     pip install -r requirements.txt
6. Set PostgreSQL environment variables in the same PowerShell window (use your actual PostgreSQL password):
     $env:PGHOST="localhost"
     $env:PGPORT="5432"
     $env:PGDATABASE="canteen_db_new"
     $env:PGUSER="postgres"
     $env:PGPASSWORD="YOUR_POSTGRES_PASSWORD"
     $env:FLASK_SECRET_KEY="replace-with-a-long-random-secret"
7. Only if you need demo accounts, run setup_db.py (it creates missing demo accounts and does not delete existing accounts):
     python setup_db.py
8. Start the app:
     python app.py
9. Open http://127.0.0.1:5000 in your browser. Do not open HTML files directly using file://; Flask is needed for API requests and login sessions.

DEMO ACCOUNTS
Staff ID: STAFF001   Password: staff123
Admin ID: ADMIN001   Password: admin123
Student: create an account using Sign Up.

FEATURES / NOTES
- Students can browse/search the menu, see estimated wait time, place orders in pickup slots, view order history/status and cancel an order only while its status is Placed. Pickup slots are capped by kitchen_capacity.max_parallel_orders.
- Student account deletion retains order history by clearing the student_id reference. It requires the migration when upgrading an existing database.
- Staff/admin can move an order through Placed → Preparing → Ready → Collected.
- Admins can create staff and additional admin accounts, view/delete accounts (cannot delete their own account or the last admin), add menu items, update stock, and delete menu items only when no order history references them.
- A menu item referenced by order history cannot be permanently deleted; set its stock to 0 to make it unavailable.
- Transaction integrity: order creation locks and validates stock, inserts order and order lines, and decrements stock in one transaction. If any step fails, all changes roll back. Cancelling a Placed order restores stock and marks the order Cancelled in the same transaction.
- The order-status trigger writes audit records to order_status_log. The backend allows only Placed → Preparing → Ready → Collected; Cancelled is only allowed through the student cancellation route.
- transaction_integrity_examples.sql contains safe coursework queries and notes for demonstrating constraints, audit history, transactions, and rollback.
- The existing static/style.css and overall frontend design are retained.

TROUBLESHOOTING
- If /api/health returns a database error, check PostgreSQL is running, the password is correct, and PGDATABASE is canteen_db_new.
- If Cancel reports a database constraint error, ensure migration_cancel_delete.sql was run against canteen_db_new.
- Change demo passwords and FLASK_SECRET_KEY before deployment. Keep .env out of GitHub and use environment variables for production secrets. This project is intended for coursework/demo use; debug mode should be disabled before deployment. The app has been syntax-checked, but test it against a backup/test database before relying on all database-dependent features.
