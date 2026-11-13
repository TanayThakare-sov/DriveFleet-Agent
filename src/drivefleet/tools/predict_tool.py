"""Failure-prediction tools (wrap your Project 1 model).

Expected artifacts in the model directory:
  failure_model.joblib  any estimator exposing predict_proba(DataFrame[features]) -> P(fail)
  model_card.json       {"features": [...], "thresholds": {"medium": x, "high": y},
                         "feature_p90": {feature: value}}  (feature_p90 is optional)
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import joblib
import pandas as pd

from drivefleet.config import get_settings

TIER_ORDER = {"low": 0, "medium": 1, "high": 2}
_CACHE: dict[str, tuple] = {}


def _load(model_dir: Path | None = None):
    model_dir = Path(model_dir or get_settings().model_dir)
    key = str(model_dir.resolve())
    if key not in _CACHE:
        model_path, card_path = model_dir / "failure_model.joblib", model_dir / "model_card.json"
        if not model_path.exists() or not card_path.exists():
            raise FileNotFoundError(f"Model not found in {model_dir}. Run `drivefleet setup` first.")
        _CACHE[key] = (joblib.load(model_path), json.loads(card_path.read_text()))
    return _CACHE[key]


def risk_tier(prob: float, thresholds: dict) -> str:
    if prob >= thresholds["high"]:
        return "high"
    if prob >= thresholds["medium"]:
        return "medium"
    return "low"


def _fetch_frame(where: str, params: tuple, db_path: Path | None) -> pd.DataFrame:
    path = Path(db_path or get_settings().db_path)
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        return pd.read_sql_query(
            f"""SELECT s.*, ds.model_name, ds.status, ds.failure_date
                FROM smart_latest s JOIN drive_status ds ON ds.serial = s.serial {where}""",
            conn, params=params,
        )
    finally:
        conn.close()


def _score(df: pd.DataFrame, model, card) -> pd.DataFrame:
    out = df.copy()
    out["failure_probability"] = model.predict_proba(out[card["features"]])[:, 1]
    out["risk_tier"] = out["failure_probability"].map(lambda p: risk_tier(p, card["thresholds"]))
    return out


def predict_drive_risk(serial: str, db_path: Path | None = None, model_dir: Path | None = None) -> dict:
    """Failure risk for one drive, with the SMART signals that look abnormal."""
    model, card = _load(model_dir)
    df = _fetch_frame("WHERE s.serial = ?", (serial.strip().upper(),), db_path)
    if df.empty:
        return {"error": f"Unknown drive serial: {serial}"}
    row = _score(df, model, card).iloc[0]
    p90 = card.get("feature_p90", {})
    signals = [
        f"{f} = {row[f]:g} (above fleet 90th percentile {p90[f]:g})"
        for f in card["features"] if f in p90 and row[f] > p90[f]
    ]
    result = {
        "serial": row["serial"],
        "model_name": row["model_name"],
        "status": row["status"],
        "failure_probability": round(float(row["failure_probability"]), 4),
        "risk_tier": row["risk_tier"],
        "tier_thresholds": card["thresholds"],
        "abnormal_signals": signals,
    }
    if row["status"] == "failed":
        result["note"] = f"This drive already failed on {row['failure_date']}; the score reflects its last SMART snapshot."
    return result


def list_high_risk_drives(min_tier: str = "high", limit: int = 50, db_path: Path | None = None,
                          model_dir: Path | None = None) -> dict:
    """Score all ACTIVE drives and return those at or above min_tier, highest risk first."""
    if min_tier not in TIER_ORDER:
        return {"error": "min_tier must be one of: low, medium, high"}
    limit = max(1, min(int(limit), 500))
    model, card = _load(model_dir)
    df = _fetch_frame("WHERE ds.status = 'active'", (), db_path)
    scored = _score(df, model, card)
    keep = scored[scored["risk_tier"].map(TIER_ORDER) >= TIER_ORDER[min_tier]]
    keep = keep.sort_values(["failure_probability", "serial"], ascending=[False, True])
    drives = [
        {"serial": r.serial, "model_name": r.model_name,
         "failure_probability": round(float(r.failure_probability), 4), "risk_tier": r.risk_tier}
        for r in keep.head(limit).itertuples()
    ]
    return {"min_tier": min_tier, "total_matching": len(keep), "returned": len(drives), "drives": drives}
