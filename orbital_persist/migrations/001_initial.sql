CREATE TABLE IF NOT EXISTS conjunction_events (
    event_id TEXT PRIMARY KEY,
    obj1_norad_id INTEGER NOT NULL,
    obj1_name TEXT NOT NULL,
    obj2_norad_id INTEGER NOT NULL,
    obj2_name TEXT NOT NULL,
    first_detected_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    tca TEXT NOT NULL,
    initial_miss_distance_km REAL NOT NULL,
    initial_pc REAL NOT NULL,
    relative_velocity_km_s REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'monitoring',
    space_weather_at_detection TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_obj1 ON conjunction_events(obj1_norad_id);
CREATE INDEX IF NOT EXISTS idx_events_obj2 ON conjunction_events(obj2_norad_id);
CREATE INDEX IF NOT EXISTS idx_events_status ON conjunction_events(status);
CREATE INDEX IF NOT EXISTS idx_events_tca ON conjunction_events(tca);

CREATE TABLE IF NOT EXISTS pc_snapshots (
    snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL,
    snapshot_at TEXT NOT NULL,
    pc REAL NOT NULL,
    miss_distance_km REAL NOT NULL,
    covariance_inflation REAL NOT NULL DEFAULT 1.0,
    kp_index REAL,
    space_weather_snapshot TEXT,
    FOREIGN KEY (event_id) REFERENCES conjunction_events(event_id)
);

CREATE INDEX IF NOT EXISTS idx_snapshots_event_time
ON pc_snapshots(event_id, snapshot_at);

CREATE TABLE IF NOT EXISTS verdicts (
    verdict_id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    issued_at TEXT NOT NULL,
    verdict_type TEXT NOT NULL,
    reasoning TEXT NOT NULL,
    plan_json TEXT,
    operator_decision TEXT,
    operator_decided_at TEXT,
    operator_notes TEXT,
    FOREIGN KEY (event_id) REFERENCES conjunction_events(event_id)
);

CREATE INDEX IF NOT EXISTS idx_verdicts_event ON verdicts(event_id);
CREATE INDEX IF NOT EXISTS idx_verdicts_decision ON verdicts(operator_decision);
