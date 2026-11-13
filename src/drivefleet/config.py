"""Central configuration. Values are read from environment variables at call time."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:  # optional: load .env if python-dotenv is installed
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = ROOT / "src"

if load_dotenv is not None:
    load_dotenv(ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    db_path: Path
    model_dir: Path
    datasheet_dir: Path
    max_rows: int
    query_timeout_s: float
    anthropic_model: str
    max_agent_steps: int


def _path(env: str, default: Path) -> Path:
    value = os.getenv(env)
    if not value:
        return default
    p = Path(value)
    return p if p.is_absolute() else ROOT / p


def get_settings() -> Settings:
    return Settings(
        db_path=_path("DRIVEFLEET_DB", ROOT / "data" / "fleet.db"),
        model_dir=_path("DRIVEFLEET_MODEL_DIR", ROOT / "models"),
        datasheet_dir=_path("DRIVEFLEET_DATASHEET_DIR", ROOT / "data" / "datasheets"),
        max_rows=int(os.getenv("DRIVEFLEET_MAX_ROWS", "200")),
        query_timeout_s=float(os.getenv("DRIVEFLEET_QUERY_TIMEOUT_S", "5")),
        anthropic_model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5"),
        max_agent_steps=int(os.getenv("DRIVEFLEET_MAX_AGENT_STEPS", "8")),
    )
