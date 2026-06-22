"""CFPB Consumer Complaint Database API v1 client and pull pipeline.

The CFPB retired the Socrata platform. The current public endpoint is the
ccdb5-api search service at consumerfinance.gov. It uses repeating query
parameters (no SoQL) and cursor-based pagination via search_after, because
the documented frm/offset pagination is broken.

Reference: https://cfpb.github.io/ccdb5-api/
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import requests
import yaml

API_ENDPOINT = "https://www.consumerfinance.gov/data-research/consumer-complaints/search/api/v1/"
PAGE_LIMIT = 1000
REQUEST_TIMEOUT = 120
PAGE_SLEEP_SECONDS = 0.5


def build_query_params(filters: dict[str, Any]) -> list[tuple[str, str]]:
    """Convert a case-config filters dict to a list of (key, value) tuples.

    Returns a list (not dict) because company, product, sub_product, and state
    are repeating parameters in the API.
    """
    params: list[tuple[str, str]] = []

    def _add_multi(key: str, value: Any) -> None:
        if not value:
            return
        if isinstance(value, str):
            value = [value]
        for v in value:
            params.append((key, str(v)))

    _add_multi("company", filters.get("company"))
    _add_multi("product", filters.get("product"))
    _add_multi("sub_product", filters.get("sub_product"))
    _add_multi("issue", filters.get("issue"))
    _add_multi("state", filters.get("state"))
    _add_multi("tags", filters.get("tags"))

    if filters.get("date_received_min"):
        params.append(("date_received_min", str(filters["date_received_min"])))
    if filters.get("date_received_max"):
        params.append(("date_received_max", str(filters["date_received_max"])))
    if filters.get("has_narrative"):
        params.append(("has_narrative", "true"))
    if filters.get("search_term"):
        params.append(("search_term", str(filters["search_term"])))
    if filters.get("field"):
        params.append(("field", str(filters["field"])))

    return params


def describe_filters(filters: dict[str, Any]) -> str:
    """Human-readable filter summary for logging."""
    parts: list[str] = []
    for key in ("company", "product", "sub_product", "issue", "state", "tags"):
        val = filters.get(key)
        if not val:
            continue
        if isinstance(val, str):
            val = [val]
        parts.append(f"{key}={val}")
    if filters.get("date_received_min"):
        parts.append(f"date_received_min={filters['date_received_min']}")
    if filters.get("date_received_max"):
        parts.append(f"date_received_max={filters['date_received_max']}")
    if filters.get("has_narrative"):
        parts.append("has_narrative=true")
    if filters.get("search_term"):
        parts.append(f"search_term='{filters['search_term']}'")
    if filters.get("field"):
        parts.append(f"field={filters['field']}")
    return "; ".join(parts) if parts else "(no filters)"


def _extract_hits(data: Any) -> list[dict[str, Any]]:
    """The API can return a bare array or a wrapped Elasticsearch-style object.

    Handle both shapes defensively.
    """
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        hits = data.get("hits")
        if isinstance(hits, dict):
            inner = hits.get("hits")
            if isinstance(inner, list):
                return inner
        if isinstance(hits, list):
            return hits
    return []


def fetch_page(
    base_params: list[tuple[str, str]],
    size: int = PAGE_LIMIT,
    search_after: str | None = None,
) -> list[dict[str, Any]]:
    """Fetch one page from the CFPB API."""
    params = list(base_params)
    params.append(("size", str(size)))
    params.append(("format", "json"))
    params.append(("no_aggs", "true"))
    if search_after is not None:
        params.append(("search_after", search_after))

    resp = requests.get(
        API_ENDPOINT,
        params=params,
        headers={"Accept": "application/json"},
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    return _extract_hits(resp.json())


def _next_cursor(last_hit: dict[str, Any]) -> str | None:
    """Build the search_after value from the last hit on a page.

    CFPB's pagination expects 'k_id' where k is the sort score and id is the
    document id. Some responses include both in the sort array; some only one.
    """
    sort_vals = last_hit.get("sort") or []
    if not sort_vals:
        return None
    if len(sort_vals) >= 2:
        return f"{sort_vals[0]}_{sort_vals[1]}"
    doc_id = last_hit.get("_id") or last_hit.get("_source", {}).get("complaint_id", "")
    if not doc_id:
        return None
    return f"{sort_vals[0]}_{doc_id}"


def iter_complaints(
    filters: dict[str, Any],
    max_pages: int | None = None,
) -> Iterator[tuple[int, dict[str, Any]]]:
    """Yield (page_number, complaint_record) tuples until exhausted or max_pages hit.

    Uses cursor-based pagination because the API's offset-style pagination is
    broken. The CFPB complaint search API requires no authentication.
    """
    base_params = build_query_params(filters)
    page = 0
    cursor: str | None = None
    while True:
        if max_pages is not None and page >= max_pages:
            return
        batch = fetch_page(base_params, PAGE_LIMIT, cursor)
        if not batch:
            return
        for record in batch:
            yield page, record
        if len(batch) < PAGE_LIMIT:
            return
        next_cursor = _next_cursor(batch[-1])
        if next_cursor is None:
            return
        cursor = next_cursor
        page += 1
        time.sleep(PAGE_SLEEP_SECONDS)


def load_aliases(path: str | Path) -> dict[str, str]:
    """Load a company alias map and return a reverse lookup of VARIANT -> canonical.

    The file maps each canonical company name to a list of variants that should
    collapse into it, for example:

        NAVY FEDERAL CREDIT UNION:
          - NFCU
          - NAVY FED
          - NAVY FEDERAL

    Matching is case-insensitive. If the file is absent or empty, an empty map
    is returned and normalization falls back to suffix and case handling only.
    """
    p = Path(path)
    if not p.exists():
        return {}
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    reverse: dict[str, str] = {}
    for canonical, variants in data.items():
        can = str(canonical).strip()
        if not can:
            continue
        reverse[can.upper()] = can
        for variant in (variants or []):
            v = str(variant).strip()
            if v:
                reverse[v.upper()] = can
    return reverse


def normalize_company(name: str | None, aliases: dict[str, str] | None = None) -> str | None:
    """Canonicalize a company name.

    First strips common corporate suffixes and uppercases. Then, if an alias
    map is supplied, maps known variants (matched on either the raw uppercased
    name or the suffix-stripped form) to their canonical name. This lets
    "Navy Federal", "NFCU", and "NAVY FEDERAL CREDIT UNION" all collapse to a
    single canonical company.
    """
    if not name:
        return None
    raw_upper = name.strip().upper()
    n = raw_upper
    suffixes = [
        ", LLC", " LLC", ", INC", " INC", ", INC.", " INC.",
        ", N.A.", " N.A.", ", NA", " NA",
        ", L.P.", " L.P.", ", LP", " LP",
        ", L.L.C.", " L.L.C.",
        ", CORP", " CORP", ", CORP.", " CORP.",
    ]
    for suffix in suffixes:
        if n.endswith(suffix):
            n = n[: -len(suffix)].strip()
    if aliases:
        if raw_upper in aliases:
            return aliases[raw_upper]
        if n in aliases:
            return aliases[n]
    return n


def to_record(raw: dict[str, Any], aliases: dict[str, str] | None = None) -> dict[str, Any]:
    """Convert a ccdb5-api hit to a DB record.

    Hit shape: {_index, _id, _score, _source: {...}, sort: [...]}.
    Fields live under _source. Two field renames from the old Socrata schema:
        consumer_complaint_narrative -> complaint_what_happened
        timely_response              -> timely
    consumer_disputed is deprecated (2017) and may be absent.
    """
    src = raw.get("_source") if isinstance(raw.get("_source"), dict) else raw

    narrative = src.get("complaint_what_happened") or src.get("consumer_complaint_narrative")
    timely = src.get("timely") if "timely" in src else src.get("timely_response")

    return {
        "complaint_id": str(src.get("complaint_id") or raw.get("_id") or ""),
        "date_received": src.get("date_received"),
        "product": src.get("product"),
        "sub_product": src.get("sub_product"),
        "issue": src.get("issue"),
        "sub_issue": src.get("sub_issue"),
        "consumer_complaint_narrative": narrative,
        "company": src.get("company"),
        "company_normalized": normalize_company(src.get("company"), aliases),
        "state": src.get("state"),
        "zip_code": src.get("zip_code"),
        "tags": src.get("tags"),
        "consumer_consent_provided": src.get("consumer_consent_provided"),
        "submitted_via": src.get("submitted_via"),
        "date_sent_to_company": src.get("date_sent_to_company"),
        "company_response": src.get("company_response"),
        "company_public_response": src.get("company_public_response"),
        "timely_response": timely,
        "consumer_disputed": src.get("consumer_disputed"),
        "raw_json": json.dumps(raw, separators=(",", ":")),
        "pulled_at": datetime.now(timezone.utc).isoformat(),
    }
