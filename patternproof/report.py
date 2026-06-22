"""Standalone HTML pattern report generator."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Template

from . import analyze


REPORT_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>PatternProof :: {{ company }} :: {{ case_id }}</title>
<style>
:root {
  color-scheme: light;
  --bg: #ffffff;
  --surface: #f7f7f5;
  --surface-2: #ececea;
  --border: #d9d9d4;
  --text: #1a1a1a;
  --muted: #5c5c5c;
  --accent: #2c5282;
  --accent-soft: #ebf2fa;
  --warn-bg: #fff8e7;
  --warn-border: #e6d58a;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
  background: var(--bg);
  color: var(--text);
  line-height: 1.5;
  -webkit-font-smoothing: antialiased;
}
.container { max-width: 1100px; margin: 0 auto; padding: 40px 24px 80px; }
h1 { font-size: 26px; margin: 0 0 4px; letter-spacing: -0.01em; font-weight: 700; }
h2 { font-size: 18px; margin: 36px 0 10px; padding-bottom: 6px; border-bottom: 1px solid var(--border); }
h3 { font-size: 13px; margin: 20px 0 8px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em; }
.meta { color: var(--muted); font-size: 13px; margin-bottom: 8px; }
.subtitle { color: var(--muted); font-size: 14px; margin: 0 0 24px; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin: 16px 0 24px; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 6px; padding: 14px 16px; }
.card .label { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em; }
.card .value { font-size: 22px; font-weight: 600; margin-top: 4px; font-variant-numeric: tabular-nums; }
.card .value.small { font-size: 14px; font-weight: 500; }
table { width: 100%; border-collapse: collapse; font-size: 14px; }
th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--border); vertical-align: middle; }
th { background: var(--surface); font-weight: 600; font-size: 12px; text-transform: uppercase; letter-spacing: 0.04em; color: var(--muted); }
tr:last-child td { border-bottom: none; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
td.bar-cell { width: 30%; }
.bar { background: var(--surface-2); height: 6px; border-radius: 3px; overflow: hidden; }
.bar > span { display: block; height: 100%; background: var(--accent); }
.footnote { margin-top: 36px; padding-top: 16px; border-top: 1px solid var(--border); font-size: 12px; color: var(--muted); }
.note { background: var(--warn-bg); border: 1px solid var(--warn-border); border-radius: 6px; padding: 12px 14px; margin: 20px 0; font-size: 13px; line-height: 1.55; }
.section-wrap { margin-bottom: 8px; }
.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }
@media (max-width: 800px) {
  .two-col { grid-template-columns: 1fr; }
}
.empty { color: var(--muted); font-style: italic; padding: 12px 0; }
code { font-family: ui-monospace, "SF Mono", Menlo, monospace; font-size: 12px; background: var(--surface); padding: 1px 5px; border-radius: 3px; }
</style>
</head>
<body>
<div class="container">

<h1>PatternProof</h1>
<p class="subtitle">CFPB Consumer Complaint Pattern Analysis Toolkit</p>
<p class="subtitle">{{ company }} :: case configuration <code>{{ case_id }}</code></p>
<div class="meta">Generated {{ generated_at }} from local mirror of CFPB Consumer Complaint Database</div>

<div class="cards">
  <div class="card"><div class="label">Total complaints</div><div class="value">{{ "{:,}".format(total) }}</div></div>
  <div class="card"><div class="label">Date range</div><div class="value small">{{ date_min }} to {{ date_max }}</div></div>
  <div class="card"><div class="label">Categories matched</div><div class="value">{{ category_count }}</div></div>
  <div class="card"><div class="label">States represented</div><div class="value">{{ state_count }}</div></div>
</div>

<h2>Yearly complaint volume</h2>
{% if yearly %}
<table>
<thead><tr><th>Year</th><th class="num">Count</th><th class="num">Share</th><th class="bar-cell"></th></tr></thead>
<tbody>
{% for row in yearly %}
<tr>
  <td>{{ row.year }}</td>
  <td class="num">{{ "{:,}".format(row.n) }}</td>
  <td class="num">{{ "%.1f"|format(row.n / total * 100) }}%</td>
  <td class="bar-cell"><div class="bar"><span style="width: {{ "%.1f"|format(row.n / max_yearly * 100) }}%"></span></div></td>
</tr>
{% endfor %}
</tbody>
</table>
{% else %}
<div class="empty">No yearly data available.</div>
{% endif %}

<h2>Category pattern volume</h2>
<p class="meta">Counts of complaints whose narratives match each taxonomy category. A single complaint can match multiple categories.</p>
{% if categories %}
<table>
<thead><tr><th>Category</th><th class="num">Matched</th><th class="num">Share of total</th><th class="bar-cell"></th></tr></thead>
<tbody>
{% for row in categories %}
<tr>
  <td>{{ row.category }}</td>
  <td class="num">{{ "{:,}".format(row.n) }}</td>
  <td class="num">{{ "%.1f"|format(row.n / total * 100) }}%</td>
  <td class="bar-cell"><div class="bar"><span style="width: {{ "%.1f"|format(row.n / max_category * 100) }}%"></span></div></td>
</tr>
{% endfor %}
</tbody>
</table>
{% else %}
<div class="empty">No classifications found. Run <code>classify {{ case_id }}</code> first.</div>
{% endif %}

<div class="two-col">
  <div class="section-wrap">
    <h2>Company response disposition</h2>
    {% if responses %}
    <table>
    <thead><tr><th>Disposition</th><th class="num">Count</th><th class="num">Share</th></tr></thead>
    <tbody>
    {% for row in responses %}
    <tr>
      <td>{{ row.company_response or "(none reported)" }}</td>
      <td class="num">{{ "{:,}".format(row.n) }}</td>
      <td class="num">{{ "%.1f"|format(row.n / total * 100) }}%</td>
    </tr>
    {% endfor %}
    </tbody>
    </table>
    {% else %}
    <div class="empty">No response data.</div>
    {% endif %}
  </div>

  <div class="section-wrap">
    <h2>Public response posture</h2>
    {% if public_responses %}
    <table>
    <thead><tr><th>Public response</th><th class="num">Count</th></tr></thead>
    <tbody>
    {% for row in public_responses %}
    <tr>
      <td>{{ row.company_public_response or "(none)" }}</td>
      <td class="num">{{ "{:,}".format(row.n) }}</td>
    </tr>
    {% endfor %}
    </tbody>
    </table>
    {% else %}
    <div class="empty">No public response data.</div>
    {% endif %}
  </div>
</div>

<h2>Product breakdown</h2>
{% if products %}
<table>
<thead><tr><th>Product</th><th>Sub-product</th><th class="num">Count</th><th class="num">Share</th></tr></thead>
<tbody>
{% for row in products %}
<tr>
  <td>{{ row.product }}</td>
  <td>{{ row.sub_product or "" }}</td>
  <td class="num">{{ "{:,}".format(row.n) }}</td>
  <td class="num">{{ "%.1f"|format(row.n / total * 100) }}%</td>
</tr>
{% endfor %}
</tbody>
</table>
{% else %}
<div class="empty">No product data.</div>
{% endif %}

<h2>Geographic distribution (top 15)</h2>
{% if states %}
<table>
<thead><tr><th>State</th><th class="num">Count</th><th class="num">Share</th></tr></thead>
<tbody>
{% for row in states[:15] %}
<tr>
  <td>{{ row.state or "(unknown)" }}</td>
  <td class="num">{{ "{:,}".format(row.n) }}</td>
  <td class="num">{{ "%.1f"|format(row.n / total * 100) }}%</td>
</tr>
{% endfor %}
</tbody>
</table>
{% else %}
<div class="empty">No geographic data.</div>
{% endif %}

<div class="note">
<strong>Evidentiary framing.</strong>
The CFPB Consumer Complaint Database publishes consumer-submitted complaints
that the company has had an opportunity to respond to. Narratives appear with
explicit consumer consent and are public record. The data is suitable as
evidence of complaint pattern and corporate notice
("X of [company]'s CFPB complaints in [category] over [period] involve [pattern]")
but is not adjudicated and should not be framed as proof of misconduct in any
single underlying case. Complaint volume reflects only consumers who knew how
to escalate to the CFPB, so any pattern figure is an undercount.
</div>

<div class="footnote">
Source: CFPB Consumer Complaint Database, public search API
<code>consumerfinance.gov/data-research/consumer-complaints/search/api/v1/</code>.
This report reflects records held in the local SQLite mirror as of the generation timestamp.
<br><br>
Generated by PatternProof. Designed by PinkViper Labs.
</div>

</div>
</body>
</html>
"""


def generate_report(
    conn: sqlite3.Connection,
    case_id: str,
    company_normalized: str,
    out_path: Path,
) -> None:
    total = analyze.total_volume(conn, company_normalized)
    yearly = analyze.yearly_volume(conn, company_normalized)
    products = analyze.product_breakdown(conn, company_normalized)
    categories = analyze.category_volume(conn, case_id, company_normalized)
    responses = analyze.company_response_breakdown(conn, company_normalized)
    public_responses = analyze.public_response_breakdown(conn, company_normalized)
    states = analyze.geographic_distribution(conn, company_normalized)

    date_row = conn.execute(
        "SELECT MIN(date_received) AS dmin, MAX(date_received) AS dmax "
        "FROM complaints WHERE company_normalized = ?",
        (company_normalized,),
    ).fetchone()

    max_yearly = max((r["n"] for r in yearly), default=1) or 1
    max_category = max((r["n"] for r in categories), default=1) or 1

    template = Template(REPORT_TEMPLATE)
    html = template.render(
        company=company_normalized,
        case_id=case_id,
        generated_at=datetime.now(timezone.utc).isoformat(),
        total=total or 1,
        date_min=(date_row["dmin"] or "")[:10] if date_row and date_row["dmin"] else "(none)",
        date_max=(date_row["dmax"] or "")[:10] if date_row and date_row["dmax"] else "(none)",
        category_count=len([c for c in categories if c["n"] > 0]),
        state_count=len(states),
        yearly=yearly,
        products=products[:30],
        categories=categories,
        responses=responses,
        public_responses=public_responses[:10],
        states=states,
        max_yearly=max_yearly,
        max_category=max_category,
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
