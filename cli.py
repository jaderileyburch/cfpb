"""Command line interface for PatternProof."""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import click
import yaml

from patternproof import analyze as analyze_mod
from patternproof import classify as classify_mod
from patternproof import db as db_mod
from patternproof import export as export_mod
from patternproof import pull as pull_mod
from patternproof import report as report_mod


DEFAULT_DB = "data/cfpb.db"
DEFAULT_CASES_DIR = "config/cases"
DEFAULT_EXPORT_DIR = "exports"
DEFAULT_ALIASES = "config/aliases.yaml"


def load_case(case_id: str, cases_dir: str = DEFAULT_CASES_DIR) -> dict:
    path = Path(cases_dir) / f"{case_id}.yaml"
    if not path.exists():
        raise click.ClickException(f"Case config not found: {path}")
    with path.open() as f:
        return yaml.safe_load(f)


def canon_company(company: str | None, ctx: click.Context) -> str | None:
    """Canonicalize a user-supplied --company value through the alias map.

    Lets a user type any known variant (for example 'NFCU') and have it resolve
    to the same canonical name stored in company_normalized.
    """
    if not company:
        return company
    aliases = pull_mod.load_aliases(ctx.obj["aliases"])
    return pull_mod.normalize_company(company, aliases)


@click.group()
@click.option("--db", default=DEFAULT_DB, show_default=True, help="SQLite database path.")
@click.option("--cases-dir", default=DEFAULT_CASES_DIR, show_default=True, help="Directory of case YAML configs.")
@click.option("--aliases", default=DEFAULT_ALIASES, show_default=True, help="Company alias map (YAML).")
@click.pass_context
def cli(ctx: click.Context, db: str, cases_dir: str, aliases: str) -> None:
    """PatternProof: CFPB Consumer Complaint Pattern Analysis Toolkit.

    Designed by PinkViper Labs.
    """
    ctx.ensure_object(dict)
    ctx.obj["db"] = db
    ctx.obj["cases_dir"] = cases_dir
    ctx.obj["aliases"] = aliases


@cli.command()
@click.pass_context
def init(ctx: click.Context) -> None:
    """Initialize or upgrade the SQLite schema."""
    db_mod.init_db(ctx.obj["db"])
    click.echo(f"Database initialized: {ctx.obj['db']}")


@cli.command()
@click.pass_context
def cases(ctx: click.Context) -> None:
    """List available case configurations."""
    cases_dir = Path(ctx.obj["cases_dir"])
    if not cases_dir.exists():
        click.echo(f"No cases directory at {cases_dir}")
        return
    files = sorted(p for p in cases_dir.glob("*.yaml") if not p.stem.startswith("_"))
    if not files:
        click.echo("No case configurations found.")
        return
    for path in files:
        try:
            with path.open() as f:
                cfg = yaml.safe_load(f) or {}
            click.echo(f"  {path.stem:<24} {cfg.get('name', '(unnamed)')}")
        except Exception as e:
            click.echo(f"  {path.stem:<24} ERROR: {e}")


@cli.command()
@click.argument("case_id")
@click.option("--since", default=None, help="Override date_received_min from case config (YYYY-MM-DD).")
@click.option("--max-pages", default=None, type=int, help="Cap number of pages (for testing).")
@click.pass_context
def pull(ctx: click.Context, case_id: str, since: str | None, max_pages: int | None) -> None:
    """Pull complaints from the CFPB API matching a case configuration."""
    case = load_case(case_id, ctx.obj["cases_dir"])
    filters = dict(case.get("filters", {}) or {})
    if since:
        filters["date_received_min"] = since

    db_mod.init_db(ctx.obj["db"])
    conn = db_mod.open_db(ctx.obj["db"])
    aliases = pull_mod.load_aliases(ctx.obj["aliases"])

    started = datetime.now(timezone.utc).isoformat()
    click.echo(f"Filters: {pull_mod.describe_filters(filters)}")

    fetched = 0
    new = 0
    current_page = -1
    page_count_in_batch = 0
    note = "ok"

    try:
        for page_idx, raw in pull_mod.iter_complaints(filters, max_pages=max_pages):
            if page_idx != current_page:
                if current_page >= 0:
                    conn.commit()
                    click.echo(f"  page {current_page + 1}: batch of {page_count_in_batch} (running: {fetched} total, {new} new)")
                current_page = page_idx
                page_count_in_batch = 0
            record = pull_mod.to_record(raw, aliases)
            if not record["complaint_id"]:
                continue
            is_new = db_mod.upsert_complaint(conn, record)
            fetched += 1
            page_count_in_batch += 1
            if is_new:
                new += 1
        if current_page >= 0:
            conn.commit()
            click.echo(f"  page {current_page + 1}: batch of {page_count_in_batch} (running: {fetched} total, {new} new)")
        if max_pages is not None and current_page + 1 >= max_pages:
            click.echo(f"Hit max-pages cap of {max_pages}.")
    except Exception as e:
        note = f"error: {e}"
        conn.commit()
        click.echo(f"Pull aborted: {e}", err=True)

    completed = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO pull_log (case_id, filter_json, started_at, completed_at, records_fetched, records_new, notes) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (case_id, json.dumps(filters), started, completed, fetched, new, note),
    )
    conn.execute(
        "INSERT OR REPLACE INTO cases (case_id, name, config_json, created_at, updated_at) "
        "VALUES (?, ?, ?, COALESCE((SELECT created_at FROM cases WHERE case_id = ?), ?), ?)",
        (case_id, case.get("name", case_id), json.dumps(case), case_id, started, completed),
    )
    conn.commit()
    conn.close()

    click.echo(f"Done. Fetched {fetched} records, {new} new.")


@cli.command()
@click.argument("case_id")
@click.option("--company", default=None, help="Limit classification to one normalized company.")
@click.pass_context
def classify(ctx: click.Context, case_id: str, company: str | None) -> None:
    """Run the case taxonomy across pulled complaint narratives."""
    company = canon_company(company, ctx)
    case = load_case(case_id, ctx.obj["cases_dir"])
    taxonomy = case.get("taxonomy") or {}
    if not taxonomy:
        raise click.ClickException(f"Case '{case_id}' has no taxonomy defined.")

    conn = db_mod.open_db(ctx.obj["db"])
    counts = classify_mod.classify_case(conn, case_id, taxonomy, company)
    conn.close()

    click.echo(f"Classification complete for case '{case_id}':")
    for cat, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        click.echo(f"  {cat:<28} {n}")


@cli.command()
@click.argument("case_id")
@click.option("--company", default=None, help="Normalized company name (e.g. 'NAVY FEDERAL CREDIT UNION').")
@click.pass_context
def stats(ctx: click.Context, case_id: str, company: str) -> None:
    """Print key statistics for a company under a case configuration."""
    company = canon_company(company, ctx)
    conn = db_mod.open_db(ctx.obj["db"])

    total = analyze_mod.total_volume(conn, company)
    click.echo(f"\nTotal complaints for {company}: {total}\n")

    click.echo("Yearly volume:")
    for row in analyze_mod.yearly_volume(conn, company):
        share = (row["n"] / total * 100) if total else 0
        click.echo(f"  {row['year']:<6} {row['n']:>6}  ({share:5.1f}%)")

    click.echo("\nProduct breakdown:")
    for row in analyze_mod.product_breakdown(conn, company)[:10]:
        sub = row["sub_product"] or ""
        label = f"{row['product']}{' / ' + sub if sub else ''}"
        click.echo(f"  {row['n']:>6}  {label}")

    click.echo("\nCategory matches:")
    for row in analyze_mod.category_volume(conn, case_id, company):
        share = (row["n"] / total * 100) if total else 0
        click.echo(f"  {row['category']:<28} {row['n']:>6}  ({share:5.1f}%)")

    click.echo("\nCompany response disposition:")
    for row in analyze_mod.company_response_breakdown(conn, company):
        share = (row["n"] / total * 100) if total else 0
        disp = row["company_response"] or "(none)"
        click.echo(f"  {disp:<40} {row['n']:>6}  ({share:5.1f}%)")

    click.echo("\nTop states:")
    for row in analyze_mod.geographic_distribution(conn, company)[:10]:
        st = row["state"] or "(unknown)"
        click.echo(f"  {st:<4} {row['n']:>6}")

    conn.close()


@cli.command()
@click.argument("case_id")
@click.argument("categories", nargs=-1, required=True)
@click.option("--company", default=None)
@click.pass_context
def overlap(ctx: click.Context, case_id: str, categories: tuple[str, ...], company: str) -> None:
    """Count complaints matching ALL listed categories simultaneously.

    Example: overlap nfcu-auto repossession payment_acceptance notice_failure --company "NAVY FEDERAL CREDIT UNION"
    """
    company = canon_company(company, ctx)
    conn = db_mod.open_db(ctx.obj["db"])
    n = analyze_mod.category_overlap(conn, case_id, list(categories), company)
    total = analyze_mod.total_volume(conn, company)
    share = (n / total * 100) if total else 0
    click.echo(f"Overlap of [{', '.join(categories)}]: {n} complaints ({share:.1f}% of total {total})")
    conn.close()


@cli.command()
@click.argument("case_id")
@click.option("--company", default=None)
@click.option("--out-dir", default=DEFAULT_EXPORT_DIR, show_default=True)
@click.option("--include-narrative/--no-narrative", default=False)
@click.pass_context
def export(ctx: click.Context, case_id: str, company: str, out_dir: str, include_narrative: bool) -> None:
    """Export summary CSV and tagged complaint list."""
    company = canon_company(company, ctx)
    conn = db_mod.open_db(ctx.obj["db"])
    out = Path(out_dir) / case_id

    summary_path = out / "summary.csv"
    tagged_path = out / "tagged_complaints.csv"
    export_mod.write_summary_csv(conn, case_id, company, summary_path)
    export_mod.write_tagged_complaints_csv(conn, case_id, company, tagged_path, include_narrative)

    click.echo(f"Wrote: {summary_path}")
    click.echo(f"Wrote: {tagged_path}")
    conn.close()


@cli.command()
@click.argument("case_id")
@click.argument("category")
@click.option("--company", default=None)
@click.option("--out-dir", default=DEFAULT_EXPORT_DIR, show_default=True)
@click.option("--limit", default=25, type=int, show_default=True)
@click.option("--excerpt-chars", default=600, type=int, show_default=True)
@click.pass_context
def excerpts(
    ctx: click.Context,
    case_id: str,
    category: str,
    company: str,
    out_dir: str,
    limit: int,
    excerpt_chars: int,
) -> None:
    """Export anonymized narrative excerpts and a citation ID list for a category."""
    company = canon_company(company, ctx)
    conn = db_mod.open_db(ctx.obj["db"])
    out = Path(out_dir) / case_id

    excerpts_path = out / f"excerpts_{category}.txt"
    ids_path = out / f"citation_ids_{category}.txt"
    export_mod.write_narrative_excerpts(
        conn, case_id, category, company, excerpts_path, limit, excerpt_chars,
    )
    export_mod.write_citation_list(conn, case_id, category, company, ids_path, limit)

    click.echo(f"Wrote: {excerpts_path}")
    click.echo(f"Wrote: {ids_path}")
    conn.close()


@cli.command()
@click.argument("case_id")
@click.option("--company", default=None)
@click.option("--out", default=None, help="Output HTML path (default: exports/<case_id>/report.html).")
@click.pass_context
def report(ctx: click.Context, case_id: str, company: str, out: str | None) -> None:
    """Generate a standalone HTML pattern report."""
    company = canon_company(company, ctx)
    conn = db_mod.open_db(ctx.obj["db"])
    out_path = Path(out) if out else Path(DEFAULT_EXPORT_DIR) / case_id / "report.html"
    report_mod.generate_report(conn, case_id, company, out_path)
    click.echo(f"Wrote: {out_path}")
    conn.close()


@cli.command()
@click.pass_context
def renormalize(ctx: click.Context) -> None:
    """Recompute company_normalized for every stored complaint using the current alias map.

    Run this after editing the alias file so existing rows pick up new aliases
    without re-pulling from the API.
    """
    aliases = pull_mod.load_aliases(ctx.obj["aliases"])
    conn = db_mod.open_db(ctx.obj["db"])
    rows = conn.execute("SELECT complaint_id, company FROM complaints").fetchall()
    changed = 0
    for row in rows:
        new_norm = pull_mod.normalize_company(row["company"], aliases)
        conn.execute(
            "UPDATE complaints SET company_normalized = ? WHERE complaint_id = ?",
            (new_norm, row["complaint_id"]),
        )
        changed += 1
    conn.commit()
    distinct = conn.execute(
        "SELECT COUNT(DISTINCT company_normalized) AS n FROM complaints"
    ).fetchone()["n"]
    conn.close()
    click.echo(f"Renormalized {changed} rows into {distinct} distinct canonical companies.")


@cli.command()
@click.pass_context
def status(ctx: click.Context) -> None:
    """Show database row counts and last pull info."""
    conn = db_mod.open_db(ctx.obj["db"])
    total = db_mod.count_complaints(conn)
    click.echo(f"Total complaints in database: {total}")

    last_pulls = conn.execute(
        "SELECT case_id, started_at, completed_at, records_fetched, records_new, notes "
        "FROM pull_log ORDER BY pull_id DESC LIMIT 5"
    ).fetchall()
    if last_pulls:
        click.echo("\nRecent pulls:")
        for row in last_pulls:
            click.echo(
                f"  {row['started_at']}  case={row['case_id']:<20}  "
                f"fetched={row['records_fetched']:<6} new={row['records_new']:<6} note={row['notes']}"
            )

    cases_rows = conn.execute("SELECT case_id, name, updated_at FROM cases ORDER BY updated_at DESC").fetchall()
    if cases_rows:
        click.echo("\nCases on record:")
        for row in cases_rows:
            click.echo(f"  {row['case_id']:<20} {row['name']} (updated {row['updated_at']})")

    conn.close()


if __name__ == "__main__":
    cli(obj={})
