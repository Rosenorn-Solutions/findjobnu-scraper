from __future__ import annotations

from pathlib import Path


def read_init_sql() -> str:
    sql_path = Path(__file__).resolve().parents[3] / "sql" / "001_init.sql"
    return sql_path.read_text(encoding="utf-8")