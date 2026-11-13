"""Train the failure-prediction model (stand-in for Project 1).

To use your real Project 1 model instead, save any scikit-learn-compatible estimator
(with predict_proba) to models/failure_model.joblib and write models/model_card.json with
the same keys this script writes (features, thresholds, feature_p90). See README.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer, StandardScaler

FEATURES = [
    "power_on_hours",
    "reallocated_sectors",
    "pending_sectors",
    "uncorrectable_errors",
    "temperature_c",
    "read_error_rate",
    "seek_error_rate",
]
THRESHOLDS = {"medium": 0.15, "high": 0.50}


def load_training_frame(db_path: Path) -> pd.DataFrame:
    conn = sqlite3.connect(db_path)
    try:
        return pd.read_sql_query(
            """SELECT s.*, CASE WHEN f.serial IS NULL THEN 0 ELSE 1 END AS failed
               FROM smart_latest s LEFT JOIN failures f ON f.serial = s.serial""",
            conn,
        )
    finally:
        conn.close()


def make_pipeline() -> Pipeline:
    return Pipeline([
        ("log1p", FunctionTransformer(np.log1p)),
        ("scale", StandardScaler()),
        ("clf", LogisticRegression(C=1.0, max_iter=1000)),
    ])


def train(db_path: Path, model_dir: Path) -> dict:
    df = load_training_frame(db_path)
    X, y = df[FEATURES], df["failed"]

    X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.25, stratify=y, random_state=42)
    auc = roc_auc_score(y_te, make_pipeline().fit(X_tr, y_tr).predict_proba(X_te)[:, 1])

    model = make_pipeline().fit(X, y)  # final model uses all data
    active = df[df["failed"] == 0]
    card = {
        "model": "log1p -> StandardScaler -> LogisticRegression",
        "features": FEATURES,
        "thresholds": THRESHOLDS,
        "metrics": {
            "roc_auc_holdout": round(float(auc), 4),
            "n_drives": len(df),
            "failure_rate": round(float(y.mean()), 4),
        },
        "feature_p90": {f: float(active[f].quantile(0.9)) for f in FEATURES},
    }
    model_dir = Path(model_dir)
    model_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, model_dir / "failure_model.joblib")
    (model_dir / "model_card.json").write_text(json.dumps(card, indent=2))
    return card


if __name__ == "__main__":  # pragma: no cover
    from drivefleet.config import get_settings

    s = get_settings()
    print(json.dumps(train(s.db_path, s.model_dir), indent=2))
