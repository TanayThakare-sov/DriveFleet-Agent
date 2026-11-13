"""Read-only SQL tool.

Safety is layered (defence in depth) so the agent can look at data but never change it:
  1. Static validation: a single SELECT/WITH statement, no write/DDL/PRAGMA/ATTACH keywords.
  2. The SQLite connection is opened in read-only mode (mode=ro) with PRAGMA query_only=ON.
  3. A SQLite authorizer denies every action except SELECT / READ / FUNCTION.
  4. Row cap and wall-clock timeout so a bad query cannot flood the model or hang the server.
"""
from __future__ import annotations

import re
import sqlite3
import time
from pathlib import Path

from drivefleet.config import get_settings

__all__ = ["SQLSafetyError", "describe_schema", "run_readonly_query", "validate_sql"]


class SQLSafetyError(ValueError):
    """Raised when a query is rejected by the safety checks."""


_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|attach|detach|pragma|vacuum|reindex|"
    r"truncate|begin|commit|rollback|savepoint|release|load_extension)\b",
    re.IGNORECASE,
)
_ALLOWED_ACTIONS = {
    sqlite3.SQLITE_SELECT,
    sqlite3.SQLITE_READ,
    sqlite3.SQLITE_FUNCTION,
    getattr(sqlite3, "SQLITE_RECURSIVE", 33),
}


def _strip_literals_and_comments(sql: str) -> str:
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    sql = re.sub(r"--[^\n]*", " ", sql)
    sql = re.sub(r"'(?:[^']|'')*'", "''", sql)
    sql = re.sub(r'"(?:[^"]|"")*"', '""', sql)
    return sql


def validate_sql(sql: str) -> str:
    """Return the cleaned statement or raise SQLSafetyError."""
    if not isinstance(sql, str) or not sql.strip():
        raise SQLSafetyError("Empty query.")
    stripped = _strip_literals_and_comments(sql).strip().rstrip(";").strip()
    if ";" in stripped:
        raise SQLSafetyError("Only a single statement is allowed.")
    if not re.match(r"^(select|with)\b", stripped, re.IGNORECASE):
        raise SQLSafetyError("Only SELECT queries (optionally starting with WITH) are allowed.")
    bad = _FORBIDDEN.search(stripped)
    if bad:
        raise SQLSafetyError(f"Forbidden keyword in query: {bad.group(0).upper()}. This tool is read-only.")
    return sql.strip().rstrip(";")


def _authorizer(action, *_args):
    return sqlite3.SQLITE_OK if action in _ALLOWED_ACTIONS else sqlite3.SQLITE_DENY


def connect_readonly(db_path: Path | None = None, timeout_s: float | None = None,
                     strict: bool = True) -> sqlite3.Connection:
    """Open the DB read-only. strict=True (default, used for model-written SQL) also installs the
    authorizer + timeout. strict=False is only for our own fixed introspection queries."""
    s = get_settings()
    db_path = Path(db_path or s.db_path)
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found at {db_path}. Run `drivefleet setup` first.")
    conn = sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)
    conn.execute("PRAGMA query_only = ON")  # run before the authorizer is installed
    if not strict:
        return conn
    conn.set_authorizer(_authorizer)
    deadline = time.monotonic() + (timeout_s if timeout_s is not None else s.query_timeout_s)
    conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 10_000)
    return conn


def run_readonly_query(sql: str, max_rows: int | None = None, db_path: Path | None = None) -> dict:
    """Validate and run a read-only query. Returns columns, rows, row_count, truncated."""
    cleaned = validate_sql(sql)
    limit = max_rows or get_settings().max_rows
    conn = connect_readonly(db_path)
    try:
        try:
            cur = conn.execute(cleaned)
            fetched = cur.fetchmany(limit + 1)
            columns = [c[0] for c in cur.description] if cur.description else []
        except sqlite3.DatabaseError as exc:
            msg = str(exc)
            if "interrupted" in msg:
                msg = "Query timed out. Simplify it or add filters."
            elif "not authorized" in msg:
                msg = "Query attempted a non-read operation and was blocked."
            raise SQLSafetyError(f"SQL error: {msg}") from exc
    finally:
        conn.close()
    truncated = len(fetched) > limit
    rows = [list(r) for r in fetched[:limit]]
    return {"columns": columns, "rows": rows, "row_count": len(rows), "truncated": truncated}


def describe_schema(db_path: Path | None = None) -> dict:
    """Tables/views with their columns, the as-of date, and a few usage hints."""
    conn = connect_readonly(db_path, strict=False)  # fixed queries; still mode=ro + query_only
    try:
        objs = conn.execute(
            "SELECT name, type FROM sqlite_master WHERE type IN ('table','view') "
            "AND name NOT LIKE 'sqlite_%' ORDER BY type, name"
        ).fetchall()
        schema = {}
        for name, kind in objs:
            cols = conn.execute(f'SELECT name, type FROM pragma_table_info("{name}")').fetchall()
            schema[name] = {"type": kind, "columns": [f"{c} {t}".strip() for c, t in cols]}
        as_of = conn.execute("SELECT value FROM meta WHERE key='as_of_date'").fetchone()
    finally:
        conn.close()
    return {
        "as_of_date": as_of[0] if as_of else None,
        "objects": schema,
        "hints": [
            "Dates are TEXT in YYYY-MM-DD format; compare them as strings.",
            "View drive_status has one row per drive: status (active/failed), warranty_end, "
            "under_warranty (1/0 as of as_of_date), failure_date, failure_mode.",
            "SQLite dialect. Use date()/strftime(); there is no DATEADD or INTERVAL.",
        ],
    }
