-- Safe, repeatable migration for an EXISTING canteen_db_new database.
-- BACK UP the database before running. Do NOT run against the old canteen_db.
BEGIN;

-- Account deletion preserves order history by setting student_id to NULL.
ALTER TABLE public.orders ALTER COLUMN student_id DROP NOT NULL;

-- Add Cancelled to the allowed statuses without changing existing order records.
DO $$
DECLARE c RECORD;
BEGIN
  FOR c IN
    SELECT conname FROM pg_constraint
    WHERE conrelid = 'public.orders'::regclass
      AND contype = 'c'
      AND pg_get_constraintdef(oid) ILIKE '%status%'
  LOOP
    EXECUTE format('ALTER TABLE public.orders DROP CONSTRAINT %I', c.conname);
  END LOOP;
  ALTER TABLE public.orders ADD CONSTRAINT orders_status_check
    CHECK (status IN ('Placed','Preparing','Ready','Collected','Cancelled'));
END $$;

-- Useful indexes for order history, queue and reports.
CREATE INDEX IF NOT EXISTS idx_orders_student_placed ON public.orders(student_id, placed_at DESC);
CREATE INDEX IF NOT EXISTS idx_orders_status_placed ON public.orders(status, placed_at);
CREATE INDEX IF NOT EXISTS idx_orders_pickup_slot_status ON public.orders(pickup_slot, status);
CREATE INDEX IF NOT EXISTS idx_order_items_order ON public.order_items(order_id);
CREATE INDEX IF NOT EXISTS idx_order_items_item ON public.order_items(item_id);
CREATE INDEX IF NOT EXISTS idx_status_log_order_changed ON public.order_status_log(order_id, changed_at);

COMMIT;

-- Verify after running:
-- SELECT DISTINCT status FROM public.orders ORDER BY status;
-- SELECT column_name, is_nullable FROM information_schema.columns
-- WHERE table_schema='public' AND table_name='orders' AND column_name='student_id';
