"""Aggregation queries for pattern analysis."""
from __future__ import annotations

import sqlite3
from typing import Any


def total_volume(conn: sqlite3.Connection, company_normalized: str | None) -> int:
    if company_normalized is None:
        row = conn.execute("SELECT COUNT(*) AS n FROM complaints").fetchone()
    else:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM complaints WHERE company_normalized = ?",
            (company_normalized,),
        ).fetchone()
    return int(row["n"])


def yearly_volume(conn: sqlite3.Connection, company_normalized: str | None) -> list[dict[str, Any]]:
    if company_normalized is None:
        rows = conn.execute(
            """
            SELECT substr(date_received, 1, 4) AS year, COUNT(*) AS n
            FROM complaints
            WHERE date_received IS NOT NULL
            GROUP BY year
            ORDER BY year
            """
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT substr(date_received, 1, 4) AS year, COUNT(*) AS n
            FROM complaints
            WHERE company_normalized = ?
              AND date_received IS NOT NULL
            GROUP BY year
            ORDER BY year
            """,
            (company_normalized,),
        ).fetchall()
    return [dict(r) for r in rows]


def product_breakdown(conn: sqlite3.Connection, company_normalized: str | None) -> list[dict[str, Any]]:
    if company_normalized is None:
        rows = conn.execute(
            """
            SELECT product, sub_product, COUNT(*) AS n
            FROM complaints
            GROUP BY product, sub_product
            ORDER BY n DESC
            LIMIT 15
            """
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT product, sub_product, COUNT(*) AS n
            FROM complaints
            WHERE company_normalized = ?
            GROUP BY product, sub_product
            ORDER BY n DESC
            """,
            (company_normalized,),
        ).fetchall()
    return [dict(r) for r in rows]


def issue_breakdown(conn: sqlite3.Connection, company_normalized: str | None) -> list[dict[str, Any]]:
    if company_normalized is None:
        rows = conn.execute(
            """
            SELECT issue, sub_issue, COUNT(*) AS n
            FROM complaints
            GROUP BY issue, sub_issue
            ORDER BY n DESC
            LIMIT 15
            """
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT issue, sub_issue, COUNT(*) AS n
            FROM complaints
            WHERE company_normalized = ?
            GROUP BY issue, sub_issue
            ORDER BY n DESC
            """,
            (company_normalized,),
        ).fetchall()
    return [dict(r) for r in rows]


def category_volume(
    conn: sqlite3.Connection,
    case_id: str,
    company_normalized: str | None = None,
) -> list[dict[str, Any]]:
    sql = """
        SELECT cl.category, COUNT(*) AS n
        FROM classifications cl
        JOIN complaints c ON c.complaint_id = cl.complaint_id
        WHERE cl.case_id = ? AND cl.matched = 1
    """
    params: list[Any] = [case_id]
    if company_normalized:
        sql += " AND c.company_normalized = ?"
        params.append(company_normalized)
    sql += " GROUP BY cl.category ORDER BY n DESC"
    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def category_overlap(
    conn: sqlite3.Connection,
    case_id: str,
    categories: list[str],
    company_normalized: str | None = None,
) -> int:
    """Count complaints that match ALL of the listed categories simultaneously."""
    if not categories:
        return 0
    sql_parts = [
        "SELECT COUNT(*) AS n FROM complaints c WHERE 1=1"
    ]
    params: list[Any] = []
    if company_normalized:
        sql_parts.append("AND c.company_normalized = ?")
        params.append(company_normalized)
    for cat in categories:
        sql_parts.append(
            "AND EXISTS (SELECT 1 FROM classifications cl "
            "WHERE cl.complaint_id = c.complaint_id "
            "AND cl.case_id = ? AND cl.category = ? AND cl.matched = 1)"
        )
        params.extend([case_id, cat])
    sql = " ".join(sql_parts)
    row = conn.execute(sql, params).fetchone()
    return int(row["n"])


def company_response_breakdown(
    conn: sqlite3.Connection,
    company_normalized: str,
    case_id: str | None = None,
    category: str | None = None,
) -> list[dict[str, Any]]:
    sql = "SELECT c.company_response, COUNT(*) AS n FROM complaints c"
    params: list[Any] = []
    if case_id and category:
        sql += (
            " JOIN classifications cl ON cl.complaint_id = c.complaint_id"
            " WHERE c.company_normalized = ?"
            " AND cl.case_id = ? AND cl.category = ? AND cl.matched = 1"
        )
        params = [company_normalized, case_id, category]
    else:
        sql += " WHERE c.company_normalized = ?"
        params = [company_normalized]
    sql += " GROUP BY c.company_response ORDER BY n DESC"
    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def public_response_breakdown(
    conn: sqlite3.Connection,
    company_normalized: str,
) -> list[dict[str, Any]]:
    """Distribution of the company_public_response field (their canned posture)."""
    rows = conn.execute(
        """
        SELECT company_public_response, COUNT(*) AS n
        FROM complaints
        WHERE company_normalized = ?
        GROUP BY company_public_response
        ORDER BY n DESC
        """,
        (company_normalized,),
    ).fetchall()
    return [dict(r) for r in rows]


def geographic_distribution(
    conn: sqlite3.Connection,
    company_normalized: str,
    case_id: str | None = None,
    category: str | None = None,
) -> list[dict[str, Any]]:
    sql = "SELECT c.state, COUNT(*) AS n FROM complaints c"
    params: list[Any] = []
    if case_id and category:
        sql += (
            " JOIN classifications cl ON cl.complaint_id = c.complaint_id"
            " WHERE c.company_normalized = ?"
            " AND cl.case_id = ? AND cl.category = ? AND cl.matched = 1"
        )
        params = [company_normalized, case_id, category]
    else:
        sql += " WHERE c.company_normalized = ?"
        params = [company_normalized]
    sql += " GROUP BY c.state ORDER BY n DESC"
    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def yearly_category_trend(
    conn: sqlite3.Connection,
    case_id: str,
    category: str,
    company_normalized: str | None = None,
) -> list[dict[str, Any]]:
    sql = """
        SELECT substr(c.date_received, 1, 4) AS year, COUNT(*) AS n
        FROM complaints c
        JOIN classifications cl ON cl.complaint_id = c.complaint_id
        WHERE cl.case_id = ? AND cl.category = ? AND cl.matched = 1
          AND c.date_received IS NOT NULL
    """
    params: list[Any] = [case_id, category]
    if company_normalized:
        sql += " AND c.company_normalized = ?"
        params.append(company_normalized)
    sql += " GROUP BY year ORDER BY year"
    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def sample_complaint_ids(
    conn: sqlite3.Connection,
    case_id: str,
    category: str,
    company_normalized: str | None = None,
    limit: int = 50,
) -> list[str]:
    sql = """
        SELECT c.complaint_id
        FROM complaints c
        JOIN classifications cl ON cl.complaint_id = c.complaint_id
        WHERE cl.case_id = ? AND cl.category = ? AND cl.matched = 1
    """
    params: list[Any] = [case_id, category]
    if company_normalized:
        sql += " AND c.company_normalized = ?"
        params.append(company_normalized)
    sql += " ORDER BY c.date_received DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    return [r["complaint_id"] for r in rows]
