import sqlite3

import pytest

from drivefleet.tools.sql_tool import (
    SQLSafetyError,
    describe_schema,
    run_readonly_query,
    validate_sql,
)


def test_select_works():
    out = run_readonly_query("SELECT COUNT(*) AS n FROM drives")
    assert out["columns"] == ["n"] and out["rows"][0][0] == 600


def test_cte_works():
    out = run_readonly_query("WITH x AS (SELECT model_id FROM drives) SELECT COUNT(*) FROM x")
    assert out["rows"][0][0] == 600


def test_view_and_trailing_semicolon():
    out = run_readonly_query("SELECT COUNT(*) FROM drive_status WHERE status='failed';")
    assert out["rows"][0][0] > 0


@pytest.mark.parametrize("sql", [
    "DELETE FROM drives",
    "DROP TABLE drives",
    "UPDATE drives SET datacenter='x'",
    "INSERT INTO meta VALUES ('a','b')",
    "CREATE TABLE t(x)",
    "ATTACH DATABASE 'x.db' AS x",
    "PRAGMA writable_schema=1",
    "SELECT 1; DROP TABLE drives",
    "SELECT * FROM drives; SELECT 1",
    "/* hi */ DELETE FROM drives",
    "",
    "   ",
    "REPLACE INTO meta VALUES ('a','b')",
    "WITH x AS (SELECT 1) DELETE FROM drives",
])
def test_rejects_unsafe(sql):
    with pytest.raises(SQLSafetyError):
        run_readonly_query(sql)


def test_keywords_inside_string_literals_are_fine():
    out = run_readonly_query("SELECT 'drop table; delete' AS s")
    assert out["rows"][0][0] == "drop table; delete"


def test_data_unchanged_after_attack_attempts(fleet_env):
    for sql in ["DELETE FROM drives", "UPDATE drives SET datacenter='x'"]:
        with pytest.raises(SQLSafetyError):
            run_readonly_query(sql)
    conn = sqlite3.connect(fleet_env.db_path)
    assert conn.execute("SELECT COUNT(*) FROM drives").fetchone()[0] == 600
    conn.close()


def test_authorizer_and_readonly_block_writes_even_if_validation_bypassed(fleet_env):
    """Layers 2 and 3 must hold on their own."""
    from drivefleet.tools.sql_tool import connect_readonly

    conn = connect_readonly()
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("DELETE FROM drives")
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("CREATE TABLE evil(x)")
    conn.close()


def test_row_cap():
    out = run_readonly_query("SELECT serial FROM drives", max_rows=10)
    assert out["row_count"] == 10 and out["truncated"] is True


def test_timeout(monkeypatch):
    monkeypatch.setenv("DRIVEFLEET_QUERY_TIMEOUT_S", "0.2")
    heavy = ("WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM c WHERE x < 500000000) "
             "SELECT COUNT(*) FROM c")
    with pytest.raises(SQLSafetyError, match="timed out"):
        run_readonly_query(heavy)


def test_sql_error_is_reported_cleanly():
    with pytest.raises(SQLSafetyError, match="SQL error"):
        run_readonly_query("SELECT nope FROM drives")


def test_schema_description():
    s = describe_schema()
    assert s["as_of_date"] == "2025-07-15"
    assert {"drives", "drive_models", "smart_latest", "failures", "drive_status"} <= set(s["objects"])


def test_validate_returns_clean_sql():
    assert validate_sql("SELECT 1;") == "SELECT 1"
