#!/usr/bin/env python3
from __future__ import annotations

import sys

from sqlalchemy import create_engine, inspect, text

from config import get_settings
from logging_setup import setup_logging

REQUIRED_TABLES = {
    "clients",
    "cars",
    "service_requests",
    "service_visits",
    "followups",
    "work_orders",
    "employees",
    "service_bays",
    "service_slots",
}

REQUIRED_COLUMNS = {
    "clients": {"client_id", "full_name", "phone_raw", "phone_normalized", "is_active"},
    "cars": {"car_id", "client_id", "brand", "model", "plate_number", "is_active"},
    "service_requests": {"request_id", "client_id", "car_id", "request_status", "source_system"},
    "service_visits": {"visit_id", "request_id", "client_id", "car_id", "visit_status", "service_bay_id"},
    "followups": {"followup_id", "request_id", "task_type", "task_status", "due_date"},
    "work_orders": {"work_order_id", "order_number", "client_id", "car_id", "status", "total_amount"},
    "employees": {"employee_id", "employee_number", "full_name", "role", "is_active"},
    "service_bays": {"service_bay_id", "bay_name", "is_active"},
    "service_slots": {"slot_id", "visit_id", "slot_date", "start_time", "end_time", "slot_status"},
}


def ok(message: str) -> None:
    print(f"OK: {message}")


def error(message: str) -> None:
    print(f"ERROR: {message}")


def main() -> int:
    setup_logging()
    settings = get_settings()
    failures: list[str] = []

    try:
        engine = create_engine(settings.database_url, future=True, pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            ok("Подключение к БД успешно")

            table_count = conn.execute(
                text("SELECT count(*) FROM information_schema.tables WHERE table_schema='app'")
            ).scalar_one()
            ok(f"Таблиц в схеме app: {table_count}")

            inspector = inspect(conn)
            actual_tables = set(inspector.get_table_names(schema="app"))

            missing_tables = sorted(REQUIRED_TABLES - actual_tables)
            if missing_tables:
                failures.append("Отсутствуют ключевые таблицы: " + ", ".join(missing_tables))
            else:
                ok("Все ключевые таблицы присутствуют")

            for table_name, columns in REQUIRED_COLUMNS.items():
                if table_name not in actual_tables:
                    continue
                actual_columns = {col["name"] for col in inspector.get_columns(table_name, schema="app")}
                missing_columns = sorted(columns - actual_columns)
                if missing_columns:
                    failures.append(f"Таблица app.{table_name}: нет колонок: {', '.join(missing_columns)}")
                else:
                    ok(f"Таблица app.{table_name}: ключевые колонки на месте")
    except Exception as exc:
        failures.append(f"Ошибка проверки БД: {exc}")

    if failures:
        for item in failures:
            error(item)
        return 1

    ok("Проверка приложения завершена успешно")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
