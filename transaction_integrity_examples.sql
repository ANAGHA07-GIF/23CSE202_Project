-- CAMPUS CANTEEN: TRANSACTION & DATA INTEGRITY DEMONSTRATIONS
-- Run examples individually in pgAdmin connected to canteen_db_new.
-- These are coursework examples; ROLLBACK examples deliberately do not save changes.

-- 1) Atomic transaction demonstration (safe read-only rollback example)
BEGIN;
SELECT order_id, status, total_amount
FROM public.orders
ORDER BY placed_at DESC
LIMIT 5;
ROLLBACK;

-- 2) Demonstrate a transaction with a deliberate rollback without changing data.
BEGIN;
UPDATE public.menu_items SET daily_stock = daily_stock WHERE item_id = -1;
ROLLBACK;

-- 3) Inspect database integrity constraints.
SELECT conrelid::regclass AS table_name,
       conname AS constraint_name,
       pg_get_constraintdef(oid) AS definition
FROM pg_constraint
WHERE connamespace = 'public'::regnamespace
ORDER BY table_name::text, constraint_name;

-- 4) Inspect order status audit history (trigger writes to this table).
SELECT order_id, old_status, new_status, changed_at
FROM public.order_status_log
ORDER BY changed_at DESC
LIMIT 25;

-- 5) Check stock values and availability consistency.
SELECT item_id, name, daily_stock, ready_quantity, is_available,
       (daily_stock > 0) AS expected_availability
FROM public.menu_items
ORDER BY name;

-- 6) Report active orders and queue load.
SELECT status, COUNT(*) AS order_count
FROM public.orders
WHERE status IN ('Placed','Preparing','Ready')
GROUP BY status
ORDER BY status;

-- TRANSACTION DESIGN NOTES
-- Order placement: one transaction locks menu rows, validates stock, inserts order and lines,
-- and decrements stock. If any operation fails, the entire transaction is rolled back.
-- Cancellation: one transaction locks the order, verifies status='Placed', restores stock,
-- and sets status='Cancelled'. If any step fails, both stock and status changes are rolled back.
-- Status transitions: Flask only permits Placed -> Preparing -> Ready -> Collected.
-- Audit: trg_order_status_log records insert/status changes in the same database transaction.
-- Integrity: CHECK constraints protect non-negative stock/prices, positive quantities and allowed statuses.
