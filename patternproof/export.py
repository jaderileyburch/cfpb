"""Export utilities for litigation deliverables."""
from __future__ import annotations

import csv
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from . import analyze


def write_summary_csv(
    conn: sqlite3.Connection,
    case_id: str,
    company_normalized: str,
    out_path: Path,
) -> None:
    """Write a single-file summary CSV with all the headline numbers."""
    total = analyze.total_volume(conn, company_normalized)
    yearly = analyze.yearly_volume(conn, company_normalized)
    cats = analyze.category_volume(conn, case_id, company_normalized)
    responses = analyze.company_response_breakdown(conn, company_normalized)
    public_responses = analyze.public_response_breakdown(conn, company_normalized)
    states = analyze.geographic_distribution(conn, company_normalized)
    products = analyze.product_breakdown(conn, company_normalized)

    out_path.parent.mkdir(parents=True, exist_ok=True)

    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Section", "Key", "Value", "Share"])

        w.writerow(["Header", "Company", company_normalized, ""])
        w.writerow(["Header", "Case ID", case_id, ""])
        w.writerow(["Header", "Generated", datetime.now(timezone.utc).isoformat(), ""])
        w.writerow(["Header", "Total complaints", total, ""])
        w.writerow([])

        w.writerow(["Yearly volume", "Year", "Count", "Share"])
        for row in yearly:
            share = f"{(row['n'] / total * 100):.1f}%" if total else ""
            w.writerow(["", row["year"], row["n"], share])
        w.writerow([])

        w.writerow(["Category matches", "Category", "Count", "Share of total"])
        for row in cats:
            share = f"{(row['n'] / total * 100):.1f}%" if total else ""
            w.writerow(["", row["category"], row["n"], share])
        w.writerow([])

        w.writerow(["Company response", "Disposition", "Count", "Share"])
        for row in responses:
            share = f"{(row['n'] / total * 100):.1f}%" if total else ""
            w.writerow(["", row["company_response"] or "(none)", row["n"], share])
        w.writerow([])

        w.writerow(["Public response", "Response", "Count", "Share"])
        for row in public_responses:
            share = f"{(row['n'] / total * 100):.1f}%" if total else ""
            w.writerow(["", row["company_public_response"] or "(none)", row["n"], share])
        w.writerow([])

        w.writerow(["Geographic distribution", "State", "Count", "Share"])
        for row in states:
            share = f"{(row['n'] / total * 100):.1f}%" if total else ""
            w.writerow(["", row["state"] or "(unknown)", row["n"], share])
        w.writerow([])

        w.writerow(["Product breakdown", "Product / Sub-product", "Count", "Share"])
        for row in products:
            share = f"{(row['n'] / total * 100):.1f}%" if total else ""
            label = f"{row['product']} / {row['sub_product']}" if row['sub_product'] else row['product']
            w.writerow(["", label, row["n"], share])


def write_tagged_complaints_csv(
    conn: sqlite3.Connection,
    case_id: str,
    company_normalized: str,
    out_path: Path,
    include_narrative: bool = False,
) -> None:
    """One row per complaint with all matched categories concatenated."""
    sql = """
        SELECT
            c.complaint_id,
            c.date_received,
            c.product,
            c.sub_product,
            c.issue,
            c.sub_issue,
            c.state,
            c.zip_code,
            c.tags,
            c.submitted_via,
            c.company_response,
            c.company_public_response,
            c.timely_response,
            c.consumer_disputed,
            GROUP_CONCAT(CASE WHEN cl.matched = 1 THEN cl.category END, '; ') AS matched_categories,
            c.consumer_complaint_narrative
        FROM complaints c
        LEFT JOIN classifications cl
          ON cl.complaint_id = c.complaint_id AND cl.case_id = ?
        WHERE c.company_normalized = ?
        GROUP BY c.complaint_id
        ORDER BY c.date_received DESC
    """
    rows = conn.execute(sql, (case_id, company_normalized)).fetchall()

    out_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "complaint_id", "date_received", "product", "sub_product",
        "issue", "sub_issue", "state", "zip_code", "tags", "submitted_via",
        "company_response", "company_public_response",
        "timely_response", "consumer_disputed", "matched_categories",
    ]
    if include_narrative:
        fieldnames.append("consumer_complaint_narrative")

    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            d = dict(row)
            if not include_narrative:
                d.pop("consumer_complaint_narrative", None)
            w.writerow(d)


def write_citation_list(
    conn: sqlite3.Connection,
    case_id: str,
    category: str,
    company_normalized: str,
    out_path: Path,
    limit: int = 100,
) -> None:
    """Plain text list of complaint IDs suitable for in camera review or appendix."""
    ids = analyze.sample_complaint_ids(conn, case_id, category, company_normalized, limit)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(ids) + ("\n" if ids else ""), encoding="utf-8")


def write_narrative_excerpts(
    conn: sqlite3.Connection,
    case_id: str,
    category: str,
    company_normalized: str,
    out_path: Path,
    limit: int = 25,
    excerpt_chars: int = 600,
) -> None:
    """Anonymized narrative excerpts for a category, formatted for brief use."""
    sql = """
        SELECT c.complaint_id, c.date_received, c.state,
               c.product, c.sub_product, c.issue, c.sub_issue,
               c.company_response, c.consumer_complaint_narrative
        FROM complaints c
        JOIN classifications cl ON cl.complaint_id = c.complaint_id
        WHERE cl.case_id = ? AND cl.category = ? AND cl.matched = 1
          AND c.company_normalized = ?
          AND c.consumer_complaint_narrative IS NOT NULL
        ORDER BY c.date_received DESC
        LIMIT ?
    """
    rows = conn.execute(sql, (case_id, category, company_normalized, limit)).fetchall()

    out_path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = [
        "CFPB Consumer Complaint Narrative Excerpts",
        f"Case configuration: {case_id}",
        f"Category: {category}",
        f"Company: {company_normalized}",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "Source: CFPB Consumer Complaint Database (consumer-consented narratives, public record)",
        "",
        "=" * 72,
        "",
    ]

    for row in rows:
        narrative = (row["consumer_complaint_narrative"] or "").strip()
        excerpt = narrative[:excerpt_chars]
        if len(narrative) > excerpt_chars:
            excerpt += " [...]"
        date = (row["date_received"] or "")[:10]
        sub = row["sub_product"] or ""
        product_line = f"{row['product']}{' / ' + sub if sub else ''}"
        sub_issue = row["sub_issue"] or ""
        issue_line = f"{row['issue']}{' / ' + sub_issue if sub_issue else ''}"

        lines.extend([
            f"Complaint ID: {row['complaint_id']}",
            f"Date received: {date}",
            f"State: {row['state']}",
            f"Product: {product_line}",
            f"Issue: {issue_line}",
            f"Company response: {row['company_response'] or '(none)'}",
            "",
            excerpt,
            "",
            "-" * 72,
            "",
        ])

    out_path.write_text("\n".join(lines), encoding="utf-8")
