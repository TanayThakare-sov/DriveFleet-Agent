"""MCP server exposing the DriveFleet tools over stdio.

Run:   python -m drivefleet.mcp_server.server
Any MCP-compatible client (Claude Desktop, Claude Code, this repo's agent, ...) can use it.

NOTE: with the stdio transport, never print() to stdout — it is the protocol channel.
"""
from __future__ import annotations

import json
import logging
import sys

from mcp.server.fastmcp import FastMCP

from drivefleet import tools

logging.basicConfig(stream=sys.stderr, level=logging.INFO)
log = logging.getLogger("drivefleet.mcp")

mcp = FastMCP("drivefleet")


def _dump(obj) -> str:
    return json.dumps(obj, default=str)


def _safe(fn, *args, **kwargs) -> str:
    """Return tool output as JSON; return errors as JSON so the model can correct itself."""
    try:
        return _dump(fn(*args, **kwargs))
    except tools.SQLSafetyError as exc:
        return _dump({"error": str(exc)})
    except FileNotFoundError as exc:
        return _dump({"error": str(exc)})
    except Exception as exc:
        log.exception("tool failed")
        return _dump({"error": f"{type(exc).__name__}: {exc}"})


@mcp.tool()
def describe_schema() -> str:
    """Show the fleet database schema (tables, views, columns), the dataset's as-of date
    ("today" for this data), and SQL hints. Call this before writing SQL if unsure of columns."""
    return _safe(tools.describe_schema)


@mcp.tool()
def query_fleet_db(sql: str) -> str:
    """Run ONE read-only SQLite SELECT query on the drive fleet database and return rows.
    Use for counts, rankings, failures by model/date/datacenter, SMART statistics, and warranty
    dates (view drive_status has status, warranty_end, under_warranty). Cannot modify data.
    Results are capped; use aggregates and LIMIT rather than selecting everything."""
    return _safe(tools.run_readonly_query, sql)


@mcp.tool()
def predict_drive_risk(serial: str) -> str:
    """Predict failure risk for ONE drive by serial number (e.g. 'SN00157'). Returns failure
    probability, risk tier (low/medium/high) and which SMART signals look abnormal. Use for
    'is drive X at risk?' questions."""
    return _safe(tools.predict_drive_risk, serial)


@mcp.tool()
def list_high_risk_drives(min_tier: str = "high", limit: int = 50) -> str:
    """Score all ACTIVE drives with the failure model and list those at or above min_tier
    ('low' | 'medium' | 'high'), highest risk first. Returns total_matching plus up to `limit`
    drives (serial, model, probability). It does NOT include warranty info; combine with
    query_fleet_db (view drive_status) for warranty questions."""
    return _safe(tools.list_high_risk_drives, min_tier, limit)


@mcp.tool()
def search_datasheets(query: str, top_k: int = 3) -> str:
    """Search product datasheets for specifications of drive models: warranty terms, interface,
    capacity, MTBF, AFR, workload rating, power, temperature limits, construction. Include the
    model name in the query (e.g. 'Orion O12 warranty'). Use this for product facts that are
    NOT in the fleet database."""
    return _safe(tools.search_datasheets, query, top_k)


def main() -> None:
    mcp.run()  # stdio transport


if __name__ == "__main__":
    main()
