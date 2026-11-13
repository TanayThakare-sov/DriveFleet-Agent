-- DriveFleet schema. The agent only ever sees this through a READ-ONLY connection.

CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);  -- as_of_date = the "today" of this dataset (YYYY-MM-DD)

CREATE TABLE drive_models (
    model_id        INTEGER PRIMARY KEY,
    model_name      TEXT NOT NULL UNIQUE,
    family          TEXT NOT NULL,
    capacity_tb     INTEGER NOT NULL,
    interface       TEXT NOT NULL,       -- SATA / SAS
    rpm             INTEGER NOT NULL,
    warranty_months INTEGER NOT NULL
);

CREATE TABLE drives (
    serial      TEXT PRIMARY KEY,        -- e.g. SN00157
    model_id    INTEGER NOT NULL REFERENCES drive_models(model_id),
    deploy_date TEXT NOT NULL,           -- YYYY-MM-DD
    datacenter  TEXT NOT NULL
);

-- Latest SMART snapshot per drive (for failed drives: the last snapshot before failure)
CREATE TABLE smart_latest (
    serial               TEXT PRIMARY KEY REFERENCES drives(serial),
    snapshot_date        TEXT NOT NULL,
    power_on_hours       INTEGER NOT NULL,
    reallocated_sectors  INTEGER NOT NULL,
    pending_sectors      INTEGER NOT NULL,
    uncorrectable_errors INTEGER NOT NULL,
    temperature_c        REAL NOT NULL,
    read_error_rate      REAL NOT NULL,
    seek_error_rate      REAL NOT NULL
);

CREATE TABLE failures (
    serial       TEXT PRIMARY KEY REFERENCES drives(serial),
    failure_date TEXT NOT NULL,          -- YYYY-MM-DD
    failure_mode TEXT NOT NULL
);

-- Convenience view: one row per drive with status and warranty info.
CREATE VIEW drive_status AS
SELECT
    d.serial,
    m.model_name,
    m.family,
    m.capacity_tb,
    d.datacenter,
    d.deploy_date,
    m.warranty_months,
    date(d.deploy_date, '+' || m.warranty_months || ' months') AS warranty_end,
    CASE WHEN date(d.deploy_date, '+' || m.warranty_months || ' months')
              >= (SELECT value FROM meta WHERE key = 'as_of_date')
         THEN 1 ELSE 0 END AS under_warranty,   -- 1 = still under warranty as of as_of_date
    CASE WHEN f.serial IS NULL THEN 'active' ELSE 'failed' END AS status,
    f.failure_date,
    f.failure_mode
FROM drives d
JOIN drive_models m ON m.model_id = d.model_id
LEFT JOIN failures f ON f.serial = d.serial;
