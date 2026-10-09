-- Campus Canteen Pre-Order and Queue Management System
-- Run in pgAdmin 4 Query Tool after selecting canteen_db.
-- These are read-only reports/inspection queries unless noted otherwise.

-- 1. List menu items and current availability/stock
SELECT item_id, name, category, price, prep_time_min, daily_stock,
       ready_quantity, is_available
FROM menu_items ORDER BY category, name;

-- 2. View all orders with the student who placed them
SELECT o.order_id, o.placed_at, s.roll_no, s.name AS student_name,
       o.status, o.pickup_slot, o.total_amount
FROM orders o LEFT JOIN students s ON s.student_id = o.student_id
ORDER BY o.placed_at DESC;

-- 3. View the items belonging to each order
SELECT o.order_id, o.status, mi.name AS item_name, oi.quantity,
       oi.unit_price, oi.quantity * oi.unit_price AS line_total
FROM order_items oi
JOIN orders o ON o.order_id = oi.order_id
JOIN menu_items mi ON mi.item_id = oi.item_id
ORDER BY o.order_id DESC, mi.name;

-- 4. Order status change history (automatically recorded by trigger)
SELECT log_id, order_id, old_status, new_status, changed_at
FROM order_status_log ORDER BY changed_at DESC;

-- 5. Today's order count and sales total
SELECT COUNT(*) AS orders_today,
       COALESCE(SUM(total_amount) FILTER (WHERE status = 'Collected'), 0) AS collected_sales_today
FROM orders WHERE placed_at::date = CURRENT_DATE;

-- 6. Most popular menu items (last 7 days)
SELECT mi.item_id, mi.name, SUM(oi.quantity) AS units_ordered
FROM order_items oi
JOIN orders o ON o.order_id = oi.order_id
JOIN menu_items mi ON mi.item_id = oi.item_id
WHERE o.placed_at >= NOW() - INTERVAL '7 days'
GROUP BY mi.item_id, mi.name
ORDER BY units_ordered DESC, mi.name;

-- 7. Orders grouped by hour for today
SELECT EXTRACT(HOUR FROM placed_at)::int AS order_hour, COUNT(*) AS order_count
FROM orders WHERE placed_at::date = CURRENT_DATE
GROUP BY order_hour ORDER BY order_hour;

-- 8. Average preparation duration for orders that reached Ready/Collected
-- Uses the status-log timestamps. Results may be empty until orders are processed.
SELECT AVG(ready_log.changed_at - placed_log.changed_at) AS avg_prep_duration
FROM orders o
JOIN LATERAL (
  SELECT MIN(changed_at) AS changed_at FROM order_status_log
  WHERE order_id = o.order_id AND new_status = 'Placed'
) placed_log ON TRUE
JOIN LATERAL (
  SELECT MIN(changed_at) AS changed_at FROM order_status_log
  WHERE order_id = o.order_id AND new_status = 'Ready'
) ready_log ON TRUE
WHERE ready_log.changed_at IS NOT NULL AND placed_log.changed_at IS NOT NULL;

-- 9. Current kitchen capacity
SELECT * FROM kitchen_capacity ORDER BY updated_at DESC;

-- 10. Update the stock for a menu item (replace item_id and stock)
-- UPDATE menu_items SET daily_stock = 25 WHERE item_id = 1;

-- 11. Add a menu item (edit values before running)
-- INSERT INTO menu_items(name, category, price, prep_time_min, daily_stock, ready_quantity)
-- VALUES ('Example Snack', 'Snacks', 25.00, 5, 20, 0);

-- 12. Inspect database tables
SELECT table_name FROM information_schema.tables
WHERE table_schema = 'public' ORDER BY table_name;
