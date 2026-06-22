"""SQLite schema and helpers for PatternProof."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS complaints (
    complaint_id TEXT PRIMARY KEY,
    date_received TEXT,
    product TEXT,
    sub_product TEXT,
    issue TEXT,
    sub_issue TEXT,
    consumer_complaint_narrative TEXT,
    company TEXT,
    company_normalized TEXT,
    state TEXT,
    zip_code TEXT,
    tags TEXT,
    consumer_consent_provided TEXT,
    submitted_via TEXT,
    date_sent_to_company TEXT,
    company_response TEXT,
    company_public_response TEXT,
    timely_response TEXT,
    consumer_disputed TEXT,
    raw_json TEXT,
    pulled_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_company_norm ON complaints(company_normalized);
CREATE INDEX IF NOT EXISTS idx_date_received ON complaints(date_received);
CREATE INDEX IF NOT EXISTS idx_product ON complaints(product);
CREATE INDEX IF NOT EXISTS idx_sub_product ON complaints(sub_product);
CREATE INDEX IF NOT EXISTS idx_state ON complaints(state);
CREATE INDEX IF NOT EXISTS idx_company_response ON complaints(company_response);

CREATE VIRTUAL TABLE IF NOT EXISTS complaints_fts USING fts5(
    complaint_id UNINDEXED,
    narrative,
    tokenize='porter unicode61'
);

CREATE TABLE IF NOT EXISTS classifications (
    complaint_id TEXT,
    case_id TEXT,
    category TEXT,
    matched INTEGER,
    match_terms TEXT,
    score REAL,
    classified_at TEXT,
    PRIMARY KEY (complaint_id, case_id, category)
);

CREATE INDEX IF NOT EXISTS idx_class_case ON classifications(case_id);
CREATE INDEX IF NOT EXISTS idx_class_category ON classifications(case_id, category, matched);

CREATE TABLE IF NOT EXISTS pull_log (
    pull_id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT,
    filter_json TEXT,
    started_at TEXT,
    completed_at TEXT,
    records_fetched INTEGER,
    records_new INTEGER,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS cases (
    case_id TEXT PRIMARY KEY,
    name TEXT,
    config_json TEXT,
    created_at TEXT,
    updated_at TEXT
);
"""


def open_db(path: str | Path) -> sqlite3.Connection:
    """Open a connection with sensible pragmas."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_db(path: str | Path) -> None:
    """Create the schema if it does not already exist."""
    conn = open_db(path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


COLUMNS = [
    "complaint_id", "date_received", "product", "sub_product",
    "issue", "sub_issue", "consumer_complaint_narrative",
    "company", "company_normalized", "state", "zip_code", "tags",
    "consumer_consent_provided", "submitted_via", "date_sent_to_company",
    "company_response", "company_public_response", "timely_response",
    "consumer_disputed", "raw_json", "pulled_at",
]


def upsert_complaint(conn: sqlite3.Connection, record: dict[str, Any]) -> bool:
    """Insert or replace one complaint row. Returns True if the row was new."""
    existing = conn.execute(
        "SELECT 1 FROM complaints WHERE complaint_id = ?",
        (record["complaint_id"],),
    ).fetchone()

    placeholders = ", ".join(["?"] * len(COLUMNS))
    values = [record.get(c) for c in COLUMNS]
    conn.execute(
        f"INSERT OR REPLACE INTO complaints ({', '.join(COLUMNS)}) VALUES ({placeholders})",
        values,
    )

    narrative = record.get("consumer_complaint_narrative")
    if narrative:
        conn.execute("DELETE FROM complaints_fts WHERE complaint_id = ?", (record["complaint_id"],))
        conn.execute(
            "INSERT INTO complaints_fts (complaint_id, narrative) VALUES (?, ?)",
            (record["complaint_id"], narrative),
        )

    return existing is None


def count_complaints(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) AS n FROM complaints").fetchone()["n"]
