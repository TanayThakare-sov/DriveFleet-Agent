"""Generate a deterministic, synthetic drive-fleet SQLite database.

Replace this with your real drive data (or load your Project 1 dataset) — the rest of the
project only depends on the schema in schema.sql.
"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from pathlib import Path

import numpy as np

AS_OF = date(2025, 7, 15)  # "today" inside the dataset => last quarter = Q2 2025

# (model_id, model_name, family, capacity_tb, interface, rpm, warranty_months)
MODELS = [
    (1, "Orion O12", "Orion", 12, "SATA", 7200, 60),
    (2, "Orion O16", "Orion", 16, "SATA", 7200, 60),
    (3, "Vega V8", "Vega", 8, "SAS", 7200, 36),
    (4, "Vega V10", "Vega", 10, "SAS", 7200, 48),
    (5, "Atlas A20", "Atlas", 20, "SATA", 7200, 60),
    (6, "Nova N4", "Nova", 4, "SATA", 5400, 24),
]
MODEL_WEIGHTS = [0.25, 0.20, 0.15, 0.15, 0.12, 0.13]
BASE_FAIL_RATE = {1: 0.07, 2: 0.08, 3: 0.16, 4: 0.11, 5: 0.09, 6: 0.18}
DATACENTERS = ["Pune-DC1", "Singapore-DC2", "Frankfurt-DC3", "Oregon-DC4", "Virginia-DC5"]
FAILURE_MODES = ["media errors", "head failure", "firmware/controller", "motor/spindle", "connector/other"]
FAILURE_MODE_WEIGHTS = [0.38, 0.27, 0.15, 0.12, 0.08]


def build_database(db_path: Path, n_drives: int = 600, seed: int = 80) -> Path:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    rng = np.random.default_rng(seed)
    schema = (Path(__file__).parent / "schema.sql").read_text()
    conn = sqlite3.connect(db_path)
    conn.executescript(schema)
    conn.executemany("INSERT INTO drive_models VALUES (?,?,?,?,?,?,?)", MODELS)
    conn.execute("INSERT INTO meta VALUES ('as_of_date', ?)", (AS_OF.isoformat(),))

    start, end = date(2020, 1, 1), date(2025, 3, 31)
    span = (end - start).days
    model_ids = [m[0] for m in MODELS]

    drives, smart, failures = [], [], []
    for i in range(1, n_drives + 1):
        serial = f"SN{i:05d}"
        model_id = int(rng.choice(model_ids, p=MODEL_WEIGHTS))
        deploy = start + timedelta(days=int(rng.integers(0, span)))
        dc = str(rng.choice(DATACENTERS, p=[0.30, 0.20, 0.20, 0.15, 0.15]))
        age_days = (AS_OF - deploy).days

        failed = rng.random() < BASE_FAIL_RATE[model_id] * (1 + age_days / 2000)
        obs = AS_OF
        if failed:
            earliest = max(deploy + timedelta(days=90), AS_OF - timedelta(days=540))
            if earliest >= AS_OF:
                failed = False
            else:
                obs = earliest + timedelta(days=int(rng.integers(0, (AS_OF - earliest).days + 1)))
                mode = str(rng.choice(FAILURE_MODES, p=FAILURE_MODE_WEIGHTS))
                failures.append((serial, obs.isoformat(), mode))

        degraded = rng.random() < (0.85 if failed else 0.08)
        hours = int((obs - deploy).days * 24 * rng.uniform(0.75, 1.0))
        if degraded:
            realloc = int(rng.lognormal(5, 1))
            pending = int(rng.poisson(12))
            uncorr = int(rng.poisson(6))
            temp = rng.normal(44, 4)
            rer = rng.gamma(2.0, 1.5)
            ser = rng.gamma(2.0, 1.0)
        else:
            realloc = int(rng.poisson(1.5))
            pending = int(rng.poisson(0.3))
            uncorr = int(rng.poisson(0.1))
            temp = rng.normal(38, 4)
            rer = rng.gamma(2.0, 0.4)
            ser = rng.gamma(2.0, 0.4)

        drives.append((serial, model_id, deploy.isoformat(), dc))
        smart.append((serial, obs.isoformat(), hours, realloc, pending, uncorr,
                      round(float(temp), 1), round(float(rer), 2), round(float(ser), 2)))

    conn.executemany("INSERT INTO drives VALUES (?,?,?,?)", drives)
    conn.executemany("INSERT INTO smart_latest VALUES (?,?,?,?,?,?,?,?,?)", smart)
    conn.executemany("INSERT INTO failures VALUES (?,?,?)", failures)
    conn.commit()
    conn.close()
    return db_path


if __name__ == "__main__":  # pragma: no cover
    from drivefleet.config import get_settings

    print("Wrote", build_database(get_settings().db_path))
