-- Safe idempotent patch for existing installations.
-- Apply after ddl.sql (or on already-running DB) to align schema with current app/models.

CREATE SCHEMA IF NOT EXISTS app;

CREATE TABLE IF NOT EXISTS app.sms_templates (
    template_id bigserial PRIMARY KEY,
    template_key text NOT NULL UNIQUE,
    title text NOT NULL,
    body text NOT NULL,
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS app.payments (
    payment_id bigserial PRIMARY KEY,
    work_order_id bigint NOT NULL REFERENCES app.work_orders(work_order_id),
    payment_date timestamptz NOT NULL DEFAULT now(),
    amount numeric(12,2) NOT NULL,
    payment_method text NOT NULL DEFAULT 'Наличные',
    comment text NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    created_by text NULL
);

ALTER TABLE IF EXISTS app.employees
    ADD COLUMN IF NOT EXISTS birth_date date,
    ADD COLUMN IF NOT EXISTS hourly_rate numeric(12,2),
    ADD COLUMN IF NOT EXISTS comments text;

ALTER TABLE IF EXISTS app.clients
    ADD COLUMN IF NOT EXISTS phone_normalized text,
    ADD COLUMN IF NOT EXISTS client_tone text,
    ADD COLUMN IF NOT EXISTS client_tags text,
    ADD COLUMN IF NOT EXISTS manager_comment text,
    ADD COLUMN IF NOT EXISTS is_active boolean,
    ADD COLUMN IF NOT EXISTS created_at timestamptz,
    ADD COLUMN IF NOT EXISTS updated_at timestamptz;

ALTER TABLE IF EXISTS app.clients
    ALTER COLUMN client_tone SET DEFAULT 'Нейтральный',
    ALTER COLUMN is_active SET DEFAULT true,
    ALTER COLUMN created_at SET DEFAULT now(),
    ALTER COLUMN updated_at SET DEFAULT now();

ALTER TABLE IF EXISTS app.service_requests
    ADD COLUMN IF NOT EXISTS phone_normalized text,
    ADD COLUMN IF NOT EXISTS personal_data_consent boolean,
    ADD COLUMN IF NOT EXISTS raw_payload jsonb;

ALTER TABLE IF EXISTS app.service_requests
    ALTER COLUMN source_system SET DEFAULT 'manual',
    ALTER COLUMN source_created_at SET DEFAULT now(),
    ALTER COLUMN import_dttm SET DEFAULT now(),
    ALTER COLUMN personal_data_consent SET DEFAULT false,
    ALTER COLUMN request_status SET DEFAULT 'Новая';

ALTER TABLE IF EXISTS app.service_visits
    ALTER COLUMN visit_source SET DEFAULT 'request',
    ALTER COLUMN visit_status SET DEFAULT 'Создан',
    ALTER COLUMN work_type SET DEFAULT 'Общее',
    ALTER COLUMN created_at SET DEFAULT now();

ALTER TABLE IF EXISTS app.followups
    ALTER COLUMN task_status SET DEFAULT 'Открыто',
    ALTER COLUMN created_at SET DEFAULT now();

ALTER TABLE IF EXISTS app.service_slots
    ALTER COLUMN slot_status SET DEFAULT 'Свободен',
    ALTER COLUMN created_at SET DEFAULT now(),
    ALTER COLUMN updated_at SET DEFAULT now();

ALTER TABLE IF EXISTS app.promotions
    ALTER COLUMN is_active SET DEFAULT true,
    ALTER COLUMN created_at SET DEFAULT now();

ALTER TABLE IF EXISTS app.promotion_contacts
    ALTER COLUMN contact_status SET DEFAULT 'Запланировано',
    ALTER COLUMN created_at SET DEFAULT now();

ALTER TABLE IF EXISTS app.work_orders
    ADD COLUMN IF NOT EXISTS created_at timestamptz,
    ADD COLUMN IF NOT EXISTS created_by text;

ALTER TABLE IF EXISTS app.work_orders
    ALTER COLUMN status SET DEFAULT 'Создан',
    ALTER COLUMN created_at SET DEFAULT now(),
    ALTER COLUMN opened_at SET DEFAULT now(),
    ALTER COLUMN work_total SET DEFAULT 0,
    ALTER COLUMN parts_total SET DEFAULT 0,
    ALTER COLUMN parts_cost_total SET DEFAULT 0,
    ALTER COLUMN total_amount SET DEFAULT 0,
    ALTER COLUMN total_cost SET DEFAULT 0,
    ALTER COLUMN total_profit SET DEFAULT 0;

ALTER TABLE IF EXISTS app.work_order_items
    ADD COLUMN IF NOT EXISTS employee_id bigint,
    ADD COLUMN IF NOT EXISTS employee_number text;

ALTER TABLE IF EXISTS app.work_order_items
    ALTER COLUMN qty SET DEFAULT 1,
    ALTER COLUMN unit_price SET DEFAULT 0,
    ALTER COLUMN unit_cost SET DEFAULT 0,
    ALTER COLUMN line_total SET DEFAULT 0,
    ALTER COLUMN line_cost SET DEFAULT 0,
    ALTER COLUMN line_profit SET DEFAULT 0;

ALTER TABLE IF EXISTS app.work_order_parts
    ADD COLUMN IF NOT EXISTS part_number text;

ALTER TABLE IF EXISTS app.work_order_parts
    ALTER COLUMN qty SET DEFAULT 1,
    ALTER COLUMN sale_price SET DEFAULT 0,
    ALTER COLUMN cost_price SET DEFAULT 0,
    ALTER COLUMN line_total SET DEFAULT 0,
    ALTER COLUMN line_cost SET DEFAULT 0,
    ALTER COLUMN line_profit SET DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_clients_phone_normalized ON app.clients(phone_normalized);
CREATE INDEX IF NOT EXISTS idx_clients_full_name_lower ON app.clients((lower(full_name)));
CREATE INDEX IF NOT EXISTS idx_cars_client_id ON app.cars(client_id);
CREATE INDEX IF NOT EXISTS idx_cars_plate_number_normalized ON app.cars(plate_number_normalized);
CREATE INDEX IF NOT EXISTS idx_service_requests_phone_normalized ON app.service_requests(phone_normalized);
CREATE INDEX IF NOT EXISTS idx_service_requests_source_created_at ON app.service_requests(source_created_at);
CREATE INDEX IF NOT EXISTS idx_service_requests_request_status ON app.service_requests(request_status);
CREATE INDEX IF NOT EXISTS idx_service_requests_client_id ON app.service_requests(client_id);
CREATE INDEX IF NOT EXISTS idx_service_requests_car_id ON app.service_requests(car_id);
CREATE INDEX IF NOT EXISTS idx_service_visits_client_id ON app.service_visits(client_id);
CREATE INDEX IF NOT EXISTS idx_service_visits_car_id ON app.service_visits(car_id);
CREATE INDEX IF NOT EXISTS idx_service_visits_planned_start_at ON app.service_visits(planned_start_at);
CREATE INDEX IF NOT EXISTS idx_service_visits_visit_status ON app.service_visits(visit_status);
CREATE INDEX IF NOT EXISTS idx_service_visits_assigned_employee_id ON app.service_visits(assigned_employee_id);
CREATE INDEX IF NOT EXISTS idx_service_visits_service_bay_id ON app.service_visits(service_bay_id);
CREATE INDEX IF NOT EXISTS idx_followups_due_date ON app.followups(due_date);
CREATE INDEX IF NOT EXISTS idx_followups_task_status ON app.followups(task_status);
CREATE INDEX IF NOT EXISTS idx_followups_client_id ON app.followups(client_id);
CREATE INDEX IF NOT EXISTS idx_followups_request_id ON app.followups(request_id);
CREATE INDEX IF NOT EXISTS idx_service_slots_date_bay ON app.service_slots(slot_date, service_bay_id);
CREATE INDEX IF NOT EXISTS idx_service_slots_date_employee ON app.service_slots(slot_date, employee_id);
CREATE INDEX IF NOT EXISTS idx_service_slots_visit_id ON app.service_slots(visit_id);
CREATE INDEX IF NOT EXISTS idx_promotion_contacts_promotion_id ON app.promotion_contacts(promotion_id);
CREATE INDEX IF NOT EXISTS idx_promotion_contacts_client_id ON app.promotion_contacts(client_id);
CREATE INDEX IF NOT EXISTS idx_work_orders_opened_at ON app.work_orders(opened_at);
CREATE INDEX IF NOT EXISTS idx_work_orders_status ON app.work_orders(status);
CREATE INDEX IF NOT EXISTS idx_work_orders_client_id ON app.work_orders(client_id);
CREATE INDEX IF NOT EXISTS idx_work_orders_visit_id ON app.work_orders(visit_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_work_orders_open_visit ON app.work_orders(visit_id) WHERE visit_id IS NOT NULL AND status <> 'Закрыт';
CREATE INDEX IF NOT EXISTS idx_payments_work_order_id ON app.payments(work_order_id);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint c
        JOIN pg_class t ON t.oid = c.conrelid
        JOIN pg_namespace n ON n.oid = t.relnamespace
        WHERE n.nspname = 'app' AND t.relname = 'work_order_items' AND c.conname = 'work_order_items_employee_id_fkey'
    ) THEN
        ALTER TABLE app.work_order_items
            ADD CONSTRAINT work_order_items_employee_id_fkey
            FOREIGN KEY (employee_id) REFERENCES app.employees(employee_id);
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint c
        JOIN pg_class t ON t.oid = c.conrelid
        JOIN pg_namespace n ON n.oid = t.relnamespace
        WHERE n.nspname = 'app' AND t.relname = 'service_visits' AND c.conname = 'chk_service_visits_time_range'
    ) THEN
        ALTER TABLE app.service_visits
            ADD CONSTRAINT chk_service_visits_time_range
            CHECK (planned_end_at IS NULL OR planned_start_at IS NULL OR planned_end_at > planned_start_at);
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint c
        JOIN pg_class t ON t.oid = c.conrelid
        JOIN pg_namespace n ON n.oid = t.relnamespace
        WHERE n.nspname = 'app' AND t.relname = 'service_slots' AND c.conname = 'chk_service_slots_time_range'
    ) THEN
        ALTER TABLE app.service_slots
            ADD CONSTRAINT chk_service_slots_time_range
            CHECK (end_time > start_time);
    END IF;
END $$;
