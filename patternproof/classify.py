"""Configurable keyword and regex classification engine."""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from typing import Any


def compile_taxonomy(taxonomy: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Pre-compile keyword and regex patterns for each category."""
    compiled: dict[str, dict[str, Any]] = {}
    for cat_id, cat_def in taxonomy.items():
        patterns: list[tuple[str, re.Pattern[str]]] = []
        for kw in cat_def.get("keywords") or []:
            pattern = re.compile(r"\b" + re.escape(kw) + r"\b", re.IGNORECASE)
            patterns.append((kw, pattern))
        for rx in cat_def.get("regex") or []:
            patterns.append((rx, re.compile(rx, re.IGNORECASE)))
        compiled[cat_id] = {
            "description": cat_def.get("description", ""),
            "patterns": patterns,
            "min_matches": int(cat_def.get("min_matches", 1)),
        }
    return compiled


def classify_text(
    text: str | None,
    compiled_taxonomy: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Return per-category match results for a single narrative."""
    results: dict[str, dict[str, Any]] = {}
    if not text:
        for cat_id in compiled_taxonomy:
            results[cat_id] = {"matched": False, "match_terms": [], "score": 0.0}
        return results

    for cat_id, cat in compiled_taxonomy.items():
        hits: list[str] = []
        for term, pat in cat["patterns"]:
            if pat.search(text):
                hits.append(term)
        results[cat_id] = {
            "matched": len(hits) >= cat["min_matches"],
            "match_terms": hits,
            "score": float(len(hits)),
        }
    return results


def classify_case(
    conn: sqlite3.Connection,
    case_id: str,
    taxonomy: dict[str, dict[str, Any]],
    company_normalized: str | None = None,
) -> dict[str, int]:
    """Run classification across all stored complaints with narratives.

    If company_normalized is provided, only complaints from that company are
    classified. Otherwise the entire database is processed (cheap; useful for
    multi-defendant cases).

    Returns a dict of category -> match count.
    """
    compiled = compile_taxonomy(taxonomy)

    sql = (
        "SELECT complaint_id, consumer_complaint_narrative "
        "FROM complaints "
        "WHERE consumer_complaint_narrative IS NOT NULL "
        "  AND consumer_complaint_narrative != ''"
    )
    params: list[Any] = []
    if company_normalized:
        sql += " AND company_normalized = ?"
        params.append(company_normalized)

    rows = conn.execute(sql, params).fetchall()

    counts: dict[str, int] = {cat: 0 for cat in compiled}
    now = datetime.now(timezone.utc).isoformat()

    for row in rows:
        results = classify_text(row["consumer_complaint_narrative"], compiled)
        for cat_id, result in results.items():
            conn.execute(
                "INSERT OR REPLACE INTO classifications "
                "(complaint_id, case_id, category, matched, match_terms, score, classified_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    row["complaint_id"],
                    case_id,
                    cat_id,
                    1 if result["matched"] else 0,
                    ", ".join(result["match_terms"]),
                    result["score"],
                    now,
                ),
            )
            if result["matched"]:
                counts[cat_id] += 1

    conn.commit()
    return counts
