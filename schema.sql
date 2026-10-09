-- Run this in pgAdmin 4 Query Tool after creating the separate database canteen_db_new. Do not run it against canteen_db.
CREATE TABLE IF NOT EXISTS students (
  student_id SERIAL PRIMARY KEY,
  roll_no VARCHAR(40) NOT NULL UNIQUE,
  name VARCHAR(120) NOT NULL,
  email VARCHAR(160) NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS staff (
  staff_id SERIAL PRIMARY KEY,
  staff_code VARCHAR(40) NOT NULL UNIQUE,
  name VARCHAR(120) NOT NULL,
  role VARCHAR(20) NOT NULL CHECK (role IN ('staff','admin')),
  password_hash TEXT NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS menu_items (
  item_id SERIAL PRIMARY KEY,
  name VARCHAR(120) NOT NULL,
  category VARCHAR(40) NOT NULL,
  price NUMERIC(10,2) NOT NULL CHECK (price >= 0),
  prep_time_min INTEGER NOT NULL DEFAULT 5 CHECK (prep_time_min >= 0),
  daily_stock INTEGER NOT NULL DEFAULT 0 CHECK (daily_stock >= 0),
  ready_quantity INTEGER NOT NULL DEFAULT 0 CHECK (ready_quantity >= 0),
  is_available BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS orders (
  order_id SERIAL PRIMARY KEY,
  student_id INTEGER REFERENCES students(student_id),
  status VARCHAR(20) NOT NULL DEFAULT 'Placed' CHECK (status IN ('Placed','Preparing','Ready','Collected','Cancelled')),
  total_amount NUMERIC(10,2) NOT NULL DEFAULT 0 CHECK (total_amount >= 0),
  pickup_slot VARCHAR(80),
  order_type VARCHAR(20) NOT NULL DEFAULT 'preorder' CHECK (order_type IN ('preorder','walkin')),
  placed_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS order_items (
  order_item_id SERIAL PRIMARY KEY,
  order_id INTEGER NOT NULL REFERENCES orders(order_id) ON DELETE CASCADE,
  item_id INTEGER NOT NULL REFERENCES menu_items(item_id),
  quantity INTEGER NOT NULL CHECK (quantity > 0),
  unit_price NUMERIC(10,2) NOT NULL CHECK (unit_price >= 0)
);
CREATE TABLE IF NOT EXISTS order_status_log (
  log_id SERIAL PRIMARY KEY,
  order_id INTEGER NOT NULL REFERENCES orders(order_id) ON DELETE CASCADE,
  old_status VARCHAR(20),
  new_status VARCHAR(20) NOT NULL,
  changed_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS kitchen_capacity (
  capacity_id SERIAL PRIMARY KEY,
  active_cooks INTEGER NOT NULL DEFAULT 4 CHECK (active_cooks > 0),
  max_parallel_orders INTEGER NOT NULL DEFAULT 10 CHECK (max_parallel_orders > 0),
  updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE OR REPLACE FUNCTION log_order_status_change() RETURNS TRIGGER AS $$
BEGIN
  IF TG_OP = 'INSERT' THEN
    INSERT INTO order_status_log(order_id,old_status,new_status) VALUES(NEW.order_id,NULL,NEW.status);
  ELSIF NEW.status IS DISTINCT FROM OLD.status THEN
    INSERT INTO order_status_log(order_id,old_status,new_status) VALUES(NEW.order_id,OLD.status,NEW.status);
  END IF;
  RETURN NEW;
END; $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_order_status_log ON orders;
CREATE TRIGGER trg_order_status_log AFTER INSERT OR UPDATE OF status ON orders
FOR EACH ROW EXECUTE FUNCTION log_order_status_change();

CREATE OR REPLACE FUNCTION sync_menu_availability() RETURNS TRIGGER AS $$
BEGIN
  NEW.is_available := (NEW.daily_stock > 0);
  RETURN NEW;
END; $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_menu_availability ON menu_items;
CREATE TRIGGER trg_menu_availability BEFORE INSERT OR UPDATE OF daily_stock ON menu_items
FOR EACH ROW EXECUTE FUNCTION sync_menu_availability();

INSERT INTO kitchen_capacity(active_cooks,max_parallel_orders)
SELECT 4,10 WHERE NOT EXISTS (SELECT 1 FROM kitchen_capacity);

INSERT INTO menu_items(name,category,price,prep_time_min,daily_stock,ready_quantity)
SELECT v.name,v.category,v.price,v.prep,v.stock,v.ready
FROM (VALUES
 ('Veg Thali','Meals',80.00,12,30,5),
 ('Masala Dosa','Meals',55.00,10,25,4),
 ('Chicken Biryani','Meals',120.00,18,20,2),
 ('Bread Omelette','Snacks',35.00,6,20,3),
 ('Samosa','Snacks',15.00,4,40,8),
 ('Filter Coffee','Beverages',20.00,3,50,10),
 ('Fresh Lime','Beverages',25.00,4,25,5)
) AS v(name,category,price,prep,stock,ready)
WHERE NOT EXISTS (SELECT 1 FROM menu_items);
