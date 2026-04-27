#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, text

from check_app import main as check_app_main
from config import get_settings
from logging_setup import setup_logging


def apply_sql_file(engine, file_path: Path) -> None:
    sql_text = file_path.read_text(encoding="utf-8")
    with engine.raw_connection() as raw_conn:
        with raw_conn.cursor() as cursor:
            cursor.execute(sql_text)
        raw_conn.commit()


def main() -> int:
    logger = setup_logging()
    settings = get_settings()

    ddl_file = settings.base_dir / "ddl.sql"
    patch_file = settings.base_dir / "migration_patch_current.sql"

    if not ddl_file.exists() or not patch_file.exists():
        print("ERROR: Не найдены ddl.sql или migration_patch_current.sql")
        return 1

    try:
        engine = create_engine(settings.database_url, future=True, pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("OK: Подключение к БД успешно")

        apply_sql_file(engine, ddl_file)
        print("OK: ddl.sql применён")

        apply_sql_file(engine, patch_file)
        print("OK: migration_patch_current.sql применён")

        logger.info("Локальная инициализация БД выполнена успешно")
    except Exception as exc:
        logger.exception("Ошибка локальной инициализации БД: %s", exc)
        print(f"ERROR: Не удалось подготовить БД: {exc}")
        return 1

    return check_app_main()


if __name__ == "__main__":
    raise SystemExit(main())
