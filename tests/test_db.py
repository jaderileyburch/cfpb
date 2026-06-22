"""Tests for schema creation, upsert behavior, and FTS indexing."""
from patternproof import db as db_mod


def _record(cid, narrative="They repossessed my car.", company="NAVY FEDERAL CREDIT UNION"):
    return {
        "complaint_id": cid,
        "date_received": "2025-01-02",
        "product": "Vehicle loan or lease",
        "sub_product": "Loan",
        "issue": "Managing the loan or lease",
        "sub_issue": None,
        "consumer_complaint_narrative": narrative,
        "company": company,
        "company_normalized": company,
        "state": "NV",
        "zip_code": "891XX",
        "tags": None,
        "consumer_consent_provided": "Consent provided",
        "submitted_via": "Web",
        "date_sent_to_company": "2025-01-03",
        "company_response": "Closed with explanation",
        "company_public_response": None,
        "timely_response": "Yes",
        "consumer_disputed": None,
        "raw_json": "{}",
        "pulled_at": "2025-01-04T00:00:00+00:00",
    }


def test_init_creates_all_tables(tmp_path):
    path = tmp_path / "t.db"
    db_mod.init_db(path)
    conn = db_mod.open_db(path)
    names = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
    )}
    for expected in ("complaints", "classifications", "pull_log", "cases", "complaints_fts"):
        assert expected in names
    conn.close()


def test_upsert_reports_new_then_not_new(tmp_path):
    path = tmp_path / "t.db"
    db_mod.init_db(path)
    conn = db_mod.open_db(path)
    assert db_mod.upsert_complaint(conn, _record("1")) is True
    assert db_mod.upsert_complaint(conn, _record("1")) is False  # replace, not new
    assert db_mod.count_complaints(conn) == 1
    conn.close()


def test_fts_search_finds_narrative(tmp_path):
    path = tmp_path / "t.db"
    db_mod.init_db(path)
    conn = db_mod.open_db(path)
    db_mod.upsert_complaint(conn, _record("1", narrative="vehicle was repossessed without notice"))
    db_mod.upsert_complaint(conn, _record("2", narrative="billing dispute on statement"))
    hits = conn.execute(
        "SELECT complaint_id FROM complaints_fts WHERE complaints_fts MATCH ?",
        ("repossessed",),
    ).fetchall()
    assert [h["complaint_id"] for h in hits] == ["1"]
    conn.close()


def test_count_complaints_empty(tmp_path):
    path = tmp_path / "t.db"
    db_mod.init_db(path)
    conn = db_mod.open_db(path)
    assert db_mod.count_complaints(conn) == 0
    conn.close()
