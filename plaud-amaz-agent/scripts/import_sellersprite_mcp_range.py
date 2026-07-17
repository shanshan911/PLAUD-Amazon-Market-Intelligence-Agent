from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from plaud_monitor.config import load_config
from plaud_monitor.metrics import compute_ai_competitors, compute_brand_share
from plaud_monitor.platform import (
    connect,
    create_upload_record,
    init_db,
    insert_dataframe,
    prepare_product_metrics,
    update_run_status,
)
from plaud_monitor.reporting import write_excel_report, write_markdown_report
from plaud_monitor.sellersprite_importer import (
    category_path_from_payload,
    fetch_mcp_market_payload,
    import_warnings,
    normalize_brand_payload,
    normalize_goods_payload,
    resolve_mcp_market_node_id,
    safe_node_name,
)
from plaud_monitor.integrations.sellersprite_mcp import SellerSpriteMcpClient


DEFAULT_SITES = ["US", "UK", "DE", "FR", "IT", "ES", "JP"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Batch import SellerSprite MCP data for a week range")
    parser.add_argument("--config", default="config/monitor_config.p0.json")
    parser.add_argument("--env-file", default=".env.local")
    parser.add_argument("--start-week", required=True, help="Example: 2026-W01")
    parser.add_argument("--end-week", required=True, help="Example: 2026-W20")
    parser.add_argument("--marketplaces", default="", help="Comma-separated sites; default reads config")
    parser.add_argument("--top-n", type=int, default=100)
    parser.add_argument("--new-product", type=int, default=6)
    parser.add_argument("--db-path", default="data/db.sqlite")
    parser.add_argument("--raw-dir", default="outputs/sellersprite_mcp")
    parser.add_argument("--report-dir", default="outputs/reports")
    parser.add_argument("--force-refresh", action="store_true", help="Import even if an ok run already exists")
    parser.add_argument("--no-resolve-node", action="store_true")
    args = parser.parse_args()

    root = Path(args.config).resolve().parents[1]
    load_env_file(root / args.env_file)
    config = load_config(args.config)
    sites = selected_marketplaces(args.marketplaces, config)
    weeks = week_range(args.start_week, args.end_week)
    week_months = {week: week_to_month(week) for week in weeks}
    month_weeks = group_weeks_by_month(weeks, week_months)

    init_db(args.db_path)
    existing = existing_ok_pairs(args.db_path, weeks, sites)
    client = SellerSpriteMcpClient.from_config(config)
    client.initialize()

    imported = 0
    skipped = 0
    failed = 0
    fetched_month_sites = 0

    for site in sites:
        for month, month_week_list in month_weeks.items():
            pending_weeks = [
                week
                for week in month_week_list
                if args.force_refresh or (week, site) not in existing
            ]
            if not pending_weeks:
                skipped += len(month_week_list)
                print(f"{site} {month}: skip {len(month_week_list)} week(s), already ok")
                continue

            print(f"{site} {month}: fetching MCP once for {', '.join(pending_weeks)}")
            try:
                node_id, node_meta = resolve_mcp_market_node_id(
                    client,
                    config,
                    site,
                    None,
                    month,
                    not args.no_resolve_node,
                )
                payload = fetch_mcp_market_payload(
                    client=client,
                    marketplace=site,
                    node_id_path=node_id,
                    node_meta=node_meta,
                    month=month,
                    top_n=args.top_n,
                    new_product=args.new_product,
                    week_id=f"{month[:4]}-M{month[4:]}",
                    raw_dir=args.raw_dir,
                )
                fetched_month_sites += 1
                imported += import_payload_for_weeks(
                    config=config,
                    db_path=args.db_path,
                    report_dir=args.report_dir,
                    payload=payload,
                    marketplace=site,
                    node_id_path=node_id,
                    month=month,
                    weeks=pending_weeks,
                )
            except Exception as exc:  # noqa: BLE001 - batch run should continue across sites.
                failed += len(pending_weeks)
                for week in pending_weeks:
                    print(f"{week} {site}: failed {exc}")

    print(
        "Batch done: "
        f"weeks={len(weeks)}, sites={len(sites)}, "
        f"month_site_fetches={fetched_month_sites}, imported={imported}, skipped={skipped}, failed={failed}"
    )
    return 1 if failed else 0


def import_payload_for_weeks(
    config: dict[str, Any],
    db_path: str,
    report_dir: str,
    payload: Any,
    marketplace: str,
    node_id_path: str,
    month: str,
    weeks: list[str],
) -> int:
    brand_df = normalize_brand_payload(payload.brands)
    product_df = normalize_goods_payload(payload.goods, payload.marketplace, category_path_from_payload(config, payload))
    brand_share = compute_brand_share(brand_df, product_df, marketplace, config)
    ai_summary, ai_detail = compute_ai_competitors(product_df, marketplace, config)
    product_metrics = prepare_product_metrics(product_df, marketplace, config)
    base_warnings = import_warnings(payload, brand_df, product_df)
    base_warnings.append(f"SellerSprite MCP month={month}; 月度数据映射到周次，非精确周快照")

    imported = 0
    with connect(db_path) as conn:
        for week in weeks:
            run_id = create_upload_record(
                conn,
                week,
                marketplace,
                f"SellerSprite_MCP_{marketplace}_{month}_{safe_node_name(node_id_path)}.json",
                payload.raw_path,
                "SellerSprite MCP monthly history mapped to week",
            )
            try:
                insert_dataframe(conn, "brand_metrics", run_id, brand_share)
                insert_dataframe(conn, "ai_summary", run_id, ai_summary)
                insert_dataframe(conn, "ai_detail", run_id, ai_detail)
                insert_dataframe(conn, "product_metrics", run_id, product_metrics)

                report_path = Path(report_dir) / week / marketplace / f"report_run_{run_id}.md"
                excel_report_path = Path(report_dir) / week / marketplace / f"report_run_{run_id}.xlsx"
                run_log = [
                    {
                        "marketplace": marketplace,
                        "status": "ok",
                        "source_file": str(payload.raw_path),
                        "warnings": "; ".join(base_warnings),
                        "error": "",
                    }
                ]
                write_markdown_report(report_path, week, brand_share, ai_summary, ai_detail, run_log)
                write_excel_report(excel_report_path, week, brand_share, ai_summary, ai_detail, run_log)
                update_run_status(
                    conn,
                    run_id,
                    "ok",
                    "; ".join(base_warnings),
                    "",
                    str(report_path),
                    str(excel_report_path),
                )
                imported += 1
                print(f"{week} {marketplace}: imported run_id={run_id}, month={month}")
            except Exception as exc:  # noqa: BLE001
                update_run_status(conn, run_id, "error", "", str(exc), "", "")
                print(f"{week} {marketplace}: failed run_id={run_id}, error={exc}")
    return imported


def selected_marketplaces(raw: str, config: dict[str, Any]) -> list[str]:
    if raw.strip():
        values = raw.split(",")
    else:
        values = config.get("monitoring", {}).get("marketplaces", DEFAULT_SITES)
    return [str(value).strip().upper() for value in values if str(value).strip()]


def parse_week_id(value: str) -> tuple[int, int]:
    clean = value.strip().upper().replace(" ", "")
    if "-W" not in clean:
        raise ValueError(f"Invalid week id: {value}")
    year_raw, week_raw = clean.split("-W", 1)
    return int(year_raw), int(week_raw)


def format_week_id(year: int, week: int) -> str:
    return f"{year}-W{week:02d}"


def week_range(start_week: str, end_week: str) -> list[str]:
    start_year, start = parse_week_id(start_week)
    end_year, end = parse_week_id(end_week)
    if start_year != end_year:
        raise ValueError("Only same-year week ranges are supported")
    if end < start:
        raise ValueError("end-week must be after start-week")
    return [format_week_id(start_year, week) for week in range(start, end + 1)]


def week_to_month(week_id: str) -> str:
    year, week = parse_week_id(week_id)
    # ISO Thursday anchors the week to the calendar month for reporting.
    anchor = date.fromisocalendar(year, week, 4)
    return f"{anchor.year}{anchor.month:02d}"


def group_weeks_by_month(weeks: list[str], week_months: dict[str, str]) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = defaultdict(list)
    for week in weeks:
        groups[week_months[week]].append(week)
    return dict(groups)


def existing_ok_pairs(db_path: str, weeks: list[str], sites: list[str]) -> set[tuple[str, str]]:
    placeholders = ",".join("?" for _ in weeks)
    with connect(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT week_id, marketplace
            FROM uploaded_reports
            WHERE status = 'ok'
              AND week_id IN ({placeholders})
            """,
            weeks,
        ).fetchall()
    site_set = set(sites)
    return {(str(row["week_id"]), str(row["marketplace"]).upper()) for row in rows if str(row["marketplace"]).upper() in site_set}


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


if __name__ == "__main__":
    raise SystemExit(main())
