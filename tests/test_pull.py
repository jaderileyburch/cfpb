"""Tests for query building, normalization, and record transformation."""
from patternproof.pull import (
    build_query_params,
    describe_filters,
    normalize_company,
    to_record,
    _extract_hits,
    _next_cursor,
    load_aliases,
)


def test_build_query_params_repeating_fields():
    params = build_query_params({
        "company": ["NAVY FEDERAL CREDIT UNION"],
        "product": ["Vehicle loan or lease", "Debt collection"],
        "date_received_min": "2019-01-01",
        "has_narrative": True,
    })
    assert ("company", "NAVY FEDERAL CREDIT UNION") in params
    assert params.count(("product", "Vehicle loan or lease")) == 1
    assert params.count(("product", "Debt collection")) == 1
    assert ("date_received_min", "2019-01-01") in params
    assert ("has_narrative", "true") in params


def test_build_query_params_string_coerced_to_single_value():
    params = build_query_params({"company": "ADESA CORPORATION"})
    assert ("company", "ADESA CORPORATION") in params


def test_build_query_params_search_term():
    params = build_query_params({"search_term": "speedy recovery", "has_narrative": True})
    assert ("search_term", "speedy recovery") in params


def test_describe_filters_readable():
    text = describe_filters({"company": ["X"], "search_term": "y"})
    assert "company" in text and "search_term" in text


def test_normalize_company_strips_suffixes():
    assert normalize_company("Navy Federal Credit Union, Inc.") == "NAVY FEDERAL CREDIT UNION"
    assert normalize_company("Capital One, N.A.") == "CAPITAL ONE"
    assert normalize_company(None) is None


def test_normalize_company_alias_collapsing():
    reverse = load_aliases_from_dict({
        "NAVY FEDERAL CREDIT UNION": ["NFCU", "Navy Federal"],
    })
    assert normalize_company("NFCU", reverse) == "NAVY FEDERAL CREDIT UNION"
    assert normalize_company("navy federal", reverse) == "NAVY FEDERAL CREDIT UNION"
    assert normalize_company("NAVY FEDERAL CREDIT UNION", reverse) == "NAVY FEDERAL CREDIT UNION"


def test_extract_hits_handles_bare_list_and_wrapped():
    assert _extract_hits([{"a": 1}]) == [{"a": 1}]
    wrapped = {"hits": {"hits": [{"b": 2}]}}
    assert _extract_hits(wrapped) == [{"b": 2}]
    assert _extract_hits({"unexpected": True}) == []


def test_next_cursor_from_sort_array():
    assert _next_cursor({"sort": [123, "abc"]}) == "123_abc"
    assert _next_cursor({"sort": []}) is None


def test_to_record_field_renames():
    raw = {
        "_id": "555",
        "_source": {
            "complaint_id": "555",
            "complaint_what_happened": "They repossessed my car.",
            "timely": "Yes",
            "company": "Navy Federal Credit Union",
            "product": "Vehicle loan or lease",
            "date_received": "2025-01-02T00:00:00",
        },
    }
    rec = to_record(raw)
    assert rec["complaint_id"] == "555"
    assert rec["consumer_complaint_narrative"] == "They repossessed my car."
    assert rec["timely_response"] == "Yes"
    assert rec["company_normalized"] == "NAVY FEDERAL CREDIT UNION"
    assert rec["raw_json"]  # full payload preserved


# Helper: build a reverse alias map in-memory without touching disk.
def load_aliases_from_dict(data):
    reverse = {}
    for canonical, variants in data.items():
        reverse[canonical.upper()] = canonical
        for v in variants:
            reverse[v.upper()] = canonical
    return reverse


def test_load_aliases_missing_file_returns_empty(tmp_path):
    assert load_aliases(tmp_path / "nope.yaml") == {}


def test_load_aliases_reverse_lookup(tmp_path):
    p = tmp_path / "aliases.yaml"
    p.write_text("NAVY FEDERAL CREDIT UNION:\n  - NFCU\n  - Navy Federal\n", encoding="utf-8")
    reverse = load_aliases(p)
    assert reverse["NFCU"] == "NAVY FEDERAL CREDIT UNION"
    assert reverse["NAVY FEDERAL"] == "NAVY FEDERAL CREDIT UNION"
    assert reverse["NAVY FEDERAL CREDIT UNION"] == "NAVY FEDERAL CREDIT UNION"
