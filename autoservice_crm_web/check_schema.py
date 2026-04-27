#!/usr/bin/env python3
import os
import sys
from dataclasses import dataclass

from sqlalchemy import create_engine, inspect, text

from config import DEFAULT_DATABASE_URL
from models import Base


@dataclass
class ColumnInfo:
    name: str
    data_type: str
    udt_name: str
    is_nullable: bool
    default: str | None


def normalize_default(value: str | None) -> str:
    if not value:
        return ""
    return value.replace("::text", "").replace("::character varying", "").replace(" ", "").lower()


def main() -> int:
    db_url = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)
    engine = create_engine(db_url, future=True)

    expected_tables = {
        t.name: t for t in Base.metadata.sorted_tables if (t.schema or "public") == "app"
    }
    failures: list[str] = []

    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT table_name, column_name, data_type, udt_name, is_nullable, column_default
                FROM information_schema.columns
                WHERE table_schema = 'app'
                ORDER BY table_name, ordinal_position
                """
            )
        ).mappings().all()

        actual: dict[str, dict[str, ColumnInfo]] = {}
        for r in rows:
            actual.setdefault(r["table_name"], {})[r["column_name"]] = ColumnInfo(
                name=r["column_name"],
                data_type=r["data_type"],
                udt_name=r["udt_name"],
                is_nullable=(r["is_nullable"] == "YES"),
                default=r["column_default"],
            )

        # Missing tables
        for table_name in expected_tables:
            if table_name not in actual:
                failures.append(f"[TABLE] Missing table in DB: app.{table_name}")

        # Extra tables
        for table_name in sorted(actual):
            if table_name not in expected_tables:
                failures.append(f"[TABLE] Table exists in DB but not in models.py: app.{table_name}")

        # Column-level checks
        for table_name, table in expected_tables.items():
            actual_cols = actual.get(table_name, {})
            expected_cols = {c.name: c for c in table.columns}

            for col_name, col in expected_cols.items():
                if col_name not in actual_cols:
                    failures.append(f"[COLUMN] Missing column in DB: app.{table_name}.{col_name}")
                    continue

                db_col = actual_cols[col_name]
                expected_type = col.type.compile(dialect=engine.dialect).lower()
                actual_type = (
                    "timestamp with time zone" if db_col.data_type == "timestamp with time zone" else db_col.udt_name
                ).lower()

                # Type compatibility for common PG aliases
                aliases = {
                    "bigint": {"int8", "bigint"},
                    "integer": {"int4", "integer"},
                    "boolean": {"bool", "boolean"},
                    "text": {"text"},
                    "date": {"date"},
                    "time without time zone": {"time"},
                    "timestamp with time zone": {"timestamptz", "timestamp with time zone"},
                    "jsonb": {"jsonb"},
                }

                compatible = False
                for key, vals in aliases.items():
                    if key in expected_type and actual_type in vals:
                        compatible = True
                        break
                if "numeric" in expected_type and actual_type == "numeric":
                    compatible = True

                if not compatible:
                    failures.append(
                        f"[TYPE] app.{table_name}.{col_name}: model={expected_type}, db={db_col.data_type}/{db_col.udt_name}"
                    )

                if bool(col.nullable) != db_col.is_nullable:
                    failures.append(
                        f"[NULLABLE] app.{table_name}.{col_name}: model={col.nullable}, db={db_col.is_nullable}"
                    )

                model_default = ""
                if col.server_default is not None:
                    model_default = normalize_default(str(col.server_default.arg))
                db_default = normalize_default(db_col.default)
                if model_default and db_default and model_default not in db_default:
                    failures.append(
                        f"[DEFAULT] app.{table_name}.{col_name}: model={model_default}, db={db_default}"
                    )

            for col_name in sorted(actual_cols):
                if col_name not in expected_cols:
                    failures.append(f"[COLUMN] Column exists in DB but not models.py: app.{table_name}.{col_name}")

        # Foreign keys
        inspector = inspect(conn)
        for table_name, table in expected_tables.items():
            model_fks = {
                (fk.parent.name, fk.column.table.schema or "public", fk.column.table.name, fk.column.name)
                for fk in table.foreign_keys
            }
            db_fks = set()
            for fk in inspector.get_foreign_keys(table_name, schema="app"):
                cols = fk.get("constrained_columns") or []
                refs = fk.get("referred_columns") or []
                ref_schema = fk.get("referred_schema") or "public"
                ref_table = fk.get("referred_table")
                for c, r in zip(cols, refs):
                    db_fks.add((c, ref_schema, ref_table, r))

            for fk_def in sorted(model_fks):
                if fk_def not in db_fks:
                    failures.append(
                        f"[FK] Missing FK in DB: app.{table_name}.{fk_def[0]} -> {fk_def[1]}.{fk_def[2]}.{fk_def[3]}"
                    )

    if failures:
        print("Schema check failed. Found mismatches:")
        for item in failures:
            print(" -", item)
        return 1

    print("Schema check passed: models.py and DB schema are aligned for app.* tables.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
