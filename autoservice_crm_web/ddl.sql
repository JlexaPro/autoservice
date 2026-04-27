CREATE SCHEMA IF NOT EXISTS app;

CREATE TABLE IF NOT EXISTS app.users (
    user_id bigserial PRIMARY KEY,
    username text NOT NULL UNIQUE,
    password_hash text NULL,
    full_name text NOT NULL,
    role text NOT NULL DEFAULT 'manager',
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS app.employees (
    employee_id bigserial PRIMARY KEY,
    employee_number text NOT NULL UNIQUE,
    full_name text NOT NULL,
    role text NOT NULL,
    phone text NULL,
    birth_date date NULL,
    hourly_rate numeric(12,2) NULL,
    comments text NULL,
    specialization text NULL,
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS app.clients (
    client_id bigserial PRIMARY KEY,
    full_name text NOT NULL,
    phone_raw text NOT NULL,
    phone_normalized text NOT NULL,
    email text NULL,
    client_tone text NOT NULL DEFAULT 'Нейтральный',
    client_tags text NULL,
    manager_comment text NULL,
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_clients_phone_normalized ON app.clients(phone_normalized);
CREATE INDEX IF NOT EXISTS idx_clients_full_name_lower ON app.clients((lower(full_name)));

CREATE TABLE IF NOT EXISTS app.client_comment_history (
    history_id bigserial PRIMARY KEY,
    client_id bigint NOT NULL REFERENCES app.clients(client_id),
    old_comment text NULL,
    new_comment text NULL,
    old_tone text NULL,
    new_tone text NULL,
    old_tags text NULL,
    new_tags text NULL,
    changed_at timestamptz NOT NULL DEFAULT now(),
    changed_by text NULL
);

CREATE TABLE IF NOT EXISTS app.cars (
    car_id bigserial PRIMARY KEY,
    client_id bigint NOT NULL REFERENCES app.clients(client_id),
    brand text NOT NULL,
    model text NOT NULL,
    car_year integer NULL,
    plate_number text NOT NULL,
    plate_number_normalized text NULL,
    vin text NULL,
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_cars_client_id ON app.cars(client_id);
CREATE INDEX IF NOT EXISTS idx_cars_plate_number_normalized ON app.cars(plate_number_normalized);

CREATE TABLE IF NOT EXISTS app.car_work_history (
    history_id bigserial PRIMARY KEY,
    car_id bigint NOT NULL REFERENCES app.cars(car_id),
    work_date date NOT NULL,
    employee_id bigint NULL REFERENCES app.employees(employee_id),
    employee_number text NULL,
    work_summary text NOT NULL,
    comment text NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    created_by text NULL
);

CREATE TABLE IF NOT EXISTS app.service_requests (
    request_id bigserial PRIMARY KEY,
    external_request_id text NULL UNIQUE,
    source_system text NOT NULL DEFAULT 'manual',
    source_file_name text NULL,
    source_created_at timestamptz NOT NULL DEFAULT now(),
    import_dttm timestamptz NOT NULL DEFAULT now(),

    client_id bigint NULL REFERENCES app.clients(client_id),
    car_id bigint NULL REFERENCES app.cars(car_id),

    full_name text NOT NULL,
    phone_raw text NOT NULL,
    phone_normalized text NOT NULL,
    email text NULL,
    car_brand text NOT NULL,
    car_model text NOT NULL,
    car_year integer NULL,
    car_plate text NOT NULL,

    parts_mode text NULL,
    problem_description text NOT NULL,
    urgency text NULL,
    desired_visit_date date NULL,
    preferred_contact_slot text NULL,
    client_comment text NULL,
    personal_data_consent boolean NOT NULL DEFAULT false,
    request_status text NOT NULL DEFAULT 'Новая',
    raw_payload jsonb NULL
);
CREATE INDEX IF NOT EXISTS idx_service_requests_phone_normalized ON app.service_requests(phone_normalized);
CREATE INDEX IF NOT EXISTS idx_service_requests_source_created_at ON app.service_requests(source_created_at);
CREATE INDEX IF NOT EXISTS idx_service_requests_request_status ON app.service_requests(request_status);
CREATE INDEX IF NOT EXISTS idx_service_requests_client_id ON app.service_requests(client_id);
CREATE INDEX IF NOT EXISTS idx_service_requests_car_id ON app.service_requests(car_id);

CREATE TABLE IF NOT EXISTS app.request_status_history (
    history_id bigserial PRIMARY KEY,
    request_id bigint NOT NULL REFERENCES app.service_requests(request_id),
    old_status text NULL,
    new_status text NOT NULL,
    changed_at timestamptz NOT NULL DEFAULT now(),
    changed_by text NULL,
    comment text NULL
);

CREATE TABLE IF NOT EXISTS app.service_bays (
    service_bay_id bigserial PRIMARY KEY,
    bay_name text NOT NULL,
    bay_type text NULL,
    is_active boolean NOT NULL DEFAULT true,
    comment text NULL
);

CREATE TABLE IF NOT EXISTS app.app_settings (
    setting_key text PRIMARY KEY,
    setting_value text NOT NULL,
    description text NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS app.service_visits (
    visit_id bigserial PRIMARY KEY,
    request_id bigint NULL REFERENCES app.service_requests(request_id),
    client_id bigint NOT NULL REFERENCES app.clients(client_id),
    car_id bigint NOT NULL REFERENCES app.cars(car_id),

    visit_source text NOT NULL DEFAULT 'request',
    visit_status text NOT NULL DEFAULT 'Создан',
    work_type text NOT NULL DEFAULT 'Общее',

    problem_description text NOT NULL,
    parts_mode text NULL,
    urgency text NULL,
    desired_visit_date date NULL,
    preferred_contact_slot text NULL,

    client_comment text NULL,
    service_comment text NULL,
    work_cost numeric(12,2) NULL,
    master_profit numeric(12,2) NULL,

    created_at timestamptz NOT NULL DEFAULT now(),
    planned_start_at timestamptz NULL,
    planned_end_at timestamptz NULL,
    completed_at timestamptz NULL,

    assigned_employee_id bigint NULL REFERENCES app.employees(employee_id),
    assigned_employee_number text NULL,
    service_bay_id bigint NULL REFERENCES app.service_bays(service_bay_id),
    CONSTRAINT chk_service_visits_time_range CHECK (
        planned_end_at IS NULL OR planned_start_at IS NULL OR planned_end_at > planned_start_at
    )
);
CREATE INDEX IF NOT EXISTS idx_service_visits_client_id ON app.service_visits(client_id);
CREATE INDEX IF NOT EXISTS idx_service_visits_car_id ON app.service_visits(car_id);
CREATE INDEX IF NOT EXISTS idx_service_visits_planned_start_at ON app.service_visits(planned_start_at);
CREATE INDEX IF NOT EXISTS idx_service_visits_visit_status ON app.service_visits(visit_status);
CREATE INDEX IF NOT EXISTS idx_service_visits_assigned_employee_id ON app.service_visits(assigned_employee_id);
CREATE INDEX IF NOT EXISTS idx_service_visits_service_bay_id ON app.service_visits(service_bay_id);

CREATE TABLE IF NOT EXISTS app.service_visit_history (
    history_id bigserial PRIMARY KEY,
    visit_id bigint NOT NULL REFERENCES app.service_visits(visit_id),
    old_visit_status text NULL,
    new_visit_status text NOT NULL,
    changed_at timestamptz NOT NULL DEFAULT now(),
    changed_by text NULL,
    service_comment text NULL,
    planned_start_at timestamptz NULL,
    planned_end_at timestamptz NULL,
    assigned_employee_number text NULL,
    service_bay_id bigint NULL
);

CREATE TABLE IF NOT EXISTS app.followups (
    followup_id bigserial PRIMARY KEY,
    request_id bigint NULL REFERENCES app.service_requests(request_id),
    client_id bigint NOT NULL REFERENCES app.clients(client_id),
    car_id bigint NULL REFERENCES app.cars(car_id),
    visit_id bigint NULL REFERENCES app.service_visits(visit_id),

    task_type text NOT NULL,
    task_status text NOT NULL DEFAULT 'Открыто',
    due_date date NOT NULL,
    preferred_contact_slot text NULL,

    title text NOT NULL,
    description text NULL,

    created_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz NULL
);
CREATE INDEX IF NOT EXISTS idx_followups_due_date ON app.followups(due_date);
CREATE INDEX IF NOT EXISTS idx_followups_task_status ON app.followups(task_status);
CREATE INDEX IF NOT EXISTS idx_followups_client_id ON app.followups(client_id);
CREATE INDEX IF NOT EXISTS idx_followups_request_id ON app.followups(request_id);

CREATE TABLE IF NOT EXISTS app.followup_history (
    history_id bigserial PRIMARY KEY,
    followup_id bigint NOT NULL REFERENCES app.followups(followup_id),
    old_task_status text NULL,
    new_task_status text NOT NULL,
    changed_at timestamptz NOT NULL DEFAULT now(),
    changed_by text NULL,
    description text NULL,
    due_date date NULL
);

CREATE TABLE IF NOT EXISTS app.service_slots (
    slot_id bigserial PRIMARY KEY,
    slot_date date NOT NULL,
    start_time time NOT NULL,
    end_time time NOT NULL,
    service_bay_id bigint NULL REFERENCES app.service_bays(service_bay_id),
    employee_id bigint NULL REFERENCES app.employees(employee_id),
    slot_status text NOT NULL DEFAULT 'Свободен',
    visit_id bigint NULL REFERENCES app.service_visits(visit_id),
    comment text NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT chk_service_slots_time_range CHECK (end_time > start_time)
);
CREATE INDEX IF NOT EXISTS idx_service_slots_date_bay ON app.service_slots(slot_date, service_bay_id);
CREATE INDEX IF NOT EXISTS idx_service_slots_date_employee ON app.service_slots(slot_date, employee_id);
CREATE INDEX IF NOT EXISTS idx_service_slots_visit_id ON app.service_slots(visit_id);

CREATE TABLE IF NOT EXISTS app.promotions (
    promotion_id bigserial PRIMARY KEY,
    title text NOT NULL,
    description text NULL,
    starts_at date NULL,
    ends_at date NULL,
    is_active boolean NOT NULL DEFAULT true,
    target_tags text NULL,
    target_car_brands text NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS app.promotion_contacts (
    contact_id bigserial PRIMARY KEY,
    promotion_id bigint NOT NULL REFERENCES app.promotions(promotion_id),
    client_id bigint NOT NULL REFERENCES app.clients(client_id),
    car_id bigint NULL REFERENCES app.cars(car_id),
    contact_status text NOT NULL DEFAULT 'Запланировано',
    planned_date date NULL,
    contacted_at timestamptz NULL,
    result_comment text NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_promotion_contacts_promotion_id ON app.promotion_contacts(promotion_id);
CREATE INDEX IF NOT EXISTS idx_promotion_contacts_client_id ON app.promotion_contacts(client_id);

CREATE TABLE IF NOT EXISTS app.sms_templates (
    template_id bigserial PRIMARY KEY,
    template_key text NOT NULL UNIQUE,
    title text NOT NULL,
    body text NOT NULL,
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS app.work_orders (
    work_order_id bigserial PRIMARY KEY,
    order_number text NOT NULL UNIQUE,
    request_id bigint NULL REFERENCES app.service_requests(request_id),
    visit_id bigint NULL REFERENCES app.service_visits(visit_id),
    client_id bigint NOT NULL REFERENCES app.clients(client_id),
    car_id bigint NOT NULL REFERENCES app.cars(car_id),
    assigned_employee_id bigint NULL REFERENCES app.employees(employee_id),
    service_bay_id bigint NULL REFERENCES app.service_bays(service_bay_id),
    status text NOT NULL DEFAULT 'Создан',
    created_at timestamptz NOT NULL DEFAULT now(),
    opened_at timestamptz NOT NULL DEFAULT now(),
    closed_at timestamptz NULL,
    work_total numeric(12,2) NOT NULL DEFAULT 0,
    parts_total numeric(12,2) NOT NULL DEFAULT 0,
    parts_cost_total numeric(12,2) NOT NULL DEFAULT 0,
    total_amount numeric(12,2) NOT NULL DEFAULT 0,
    total_cost numeric(12,2) NOT NULL DEFAULT 0,
    total_profit numeric(12,2) NOT NULL DEFAULT 0,
    comment text NULL,
    created_by text NULL
);
CREATE INDEX IF NOT EXISTS idx_work_orders_opened_at ON app.work_orders(opened_at);
CREATE INDEX IF NOT EXISTS idx_work_orders_status ON app.work_orders(status);
CREATE INDEX IF NOT EXISTS idx_work_orders_client_id ON app.work_orders(client_id);
CREATE INDEX IF NOT EXISTS idx_work_orders_visit_id ON app.work_orders(visit_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_work_orders_open_visit
    ON app.work_orders(visit_id)
    WHERE visit_id IS NOT NULL AND status <> 'Закрыт';

CREATE TABLE IF NOT EXISTS app.work_order_items (
    item_id bigserial PRIMARY KEY,
    work_order_id bigint NOT NULL REFERENCES app.work_orders(work_order_id) ON DELETE CASCADE,
    work_type text NOT NULL,
    description text NULL,
    comment text NULL,
    employee_id bigint NULL REFERENCES app.employees(employee_id),
    employee_number text NULL,
    qty numeric(10,2) NOT NULL DEFAULT 1,
    unit_price numeric(12,2) NOT NULL DEFAULT 0,
    unit_cost numeric(12,2) NOT NULL DEFAULT 0,
    line_total numeric(12,2) NOT NULL DEFAULT 0,
    line_cost numeric(12,2) NOT NULL DEFAULT 0,
    line_profit numeric(12,2) NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS app.work_order_parts (
    part_id bigserial PRIMARY KEY,
    work_order_id bigint NOT NULL REFERENCES app.work_orders(work_order_id) ON DELETE CASCADE,
    part_name text NOT NULL,
    part_number text NULL,
    part_brand text NULL,
    comment text NULL,
    qty numeric(10,2) NOT NULL DEFAULT 1,
    sale_price numeric(12,2) NOT NULL DEFAULT 0,
    cost_price numeric(12,2) NOT NULL DEFAULT 0,
    line_total numeric(12,2) NOT NULL DEFAULT 0,
    line_cost numeric(12,2) NOT NULL DEFAULT 0,
    line_profit numeric(12,2) NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS app.work_order_status_history (
    history_id bigserial PRIMARY KEY,
    work_order_id bigint NOT NULL REFERENCES app.work_orders(work_order_id) ON DELETE CASCADE,
    old_status text NULL,
    new_status text NOT NULL,
    changed_at timestamptz NOT NULL DEFAULT now(),
    changed_by text NULL,
    comment text NULL
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
CREATE INDEX IF NOT EXISTS idx_payments_work_order_id ON app.payments(work_order_id);
