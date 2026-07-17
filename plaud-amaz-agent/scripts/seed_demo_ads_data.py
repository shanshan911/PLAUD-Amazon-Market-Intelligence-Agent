#!/usr/bin/env python3
"""Seed demo Amazon Ads data for the local MVP dashboard.

The generated rows are explicitly marked as DEMO_ADS_SEED in upload notes and
stored under data/ads_demo/. The script only deletes previous DEMO_ADS_SEED
rows, so real manual uploads or Amazon Ads API imports are preserved.
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app
from scripts.import_amazon_ads_api import import_csv_to_db


MARKETPLACES = ["US", "UK", "DE", "FR", "IT", "ES", "JP"]
REPORT_TYPES = ["search_term", "campaign", "targeting", "asin"]
SITE_SCALE = {
    "US": 1.28,
    "UK": 0.78,
    "DE": 0.72,
    "FR": 0.55,
    "IT": 0.48,
    "ES": 0.44,
    "JP": 0.86,
}
TERMS = [
    ("PLAUD Brand Defense", "Brand", "plaud note", "exact", "B0FQ5J7HFQ", 1.18),
    ("Voice Recorder Category", "Category", "voice recorder", "phrase", "B0FXL8WZQN", 1.00),
    ("AI Recorder Expansion", "AI", "ai voice recorder", "broad", "B0G4M5QMNG", 0.86),
    ("Meeting Notes", "Scenario", "meeting recorder", "phrase", "B0D35MNVRT", 0.74),
    ("Competitor Capture", "Competitor", "notta recorder", "exact", "B0G3GH1H1K", 0.68),
    ("Long Tail Discovery", "Long Tail", "record meetings transcript", "broad", "B0FKN8FYV1", 0.52),
]


def week_range(start: int, end: int, year: int) -> list[str]:
    return [f"{year}-W{week:02d}" for week in range(start, end + 1)]


def clean_demo_rows(db_path: str, weeks: list[str], marketplaces: list[str]) -> int:
    app.init_ads_db()
    placeholders_weeks = ",".join("?" for _ in weeks)
    placeholders_sites = ",".join("?" for _ in marketplaces)
    params = [*weeks, *marketplaces]
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT id
            FROM ad_report_uploads
            WHERE note LIKE 'DEMO_ADS_SEED%'
              AND week_id IN ({placeholders_weeks})
              AND marketplace IN ({placeholders_sites})
            """,
            params,
        ).fetchall()
        upload_ids = [int(row[0]) for row in rows]
        for upload_id in upload_ids:
            conn.execute("DELETE FROM ad_metrics WHERE upload_id = ?", (upload_id,))
            conn.execute("DELETE FROM ad_report_uploads WHERE id = ?", (upload_id,))
        conn.commit()
    return len(upload_ids)


def row_for(site: str, week_index: int, term_index: int, report_type: str) -> dict[str, object]:
    scale = SITE_SCALE.get(site, 0.5)
    campaign, ad_group, term, match_type, asin, term_weight = TERMS[term_index]
    week_growth = 1 + week_index * 0.055
    site_wave = 1 + ((term_index + len(site)) % 3 - 1) * 0.045
    type_factor = {
        "search_term": 1.00,
        "campaign": 1.08,
        "targeting": 0.92,
        "asin": 0.84,
    }.get(report_type, 1.0)
    spend = round(420 * scale * week_growth * site_wave * term_weight * type_factor, 2)
    roas = 3.15 + (term_index % 4) * 0.34 + week_index * 0.08 + (0.18 if site in {"US", "JP"} else 0)
    sales = round(spend * roas, 2)
    clicks = int(86 * scale * week_growth * term_weight * type_factor + 18 + term_index * 4)
    ctr = 0.0105 + (term_index % 3) * 0.002 + week_index * 0.00025
    impressions = int(clicks / ctr)
    orders = max(1, int(sales / (168 + term_index * 18)))
    units = max(1, int(orders * (1.05 + (term_index % 2) * 0.18)))
    target = term if report_type in {"targeting", "campaign"} else ""
    search_term = term if report_type in {"search_term", "asin"} else ""
    return {
        "date": "",
        "campaign": campaign,
        "ad group": ad_group,
        "search term": search_term,
        "targeting": target,
        "match type": match_type,
        "asin": asin,
        "sku": f"PLAUD-{site}-{term_index + 1:02d}",
        "impressions": impressions,
        "clicks": clicks,
        "spend": spend,
        "sales": sales,
        "orders": orders,
        "units": units,
        "acos": round(spend / sales if sales else 0, 4),
        "roas": round(sales / spend if spend else 0, 4),
    }


def write_demo_csv(path: Path, site: str, week_index: int, report_type: str) -> None:
    fieldnames = [
        "date",
        "campaign",
        "ad group",
        "search term",
        "targeting",
        "match type",
        "asin",
        "sku",
        "impressions",
        "clicks",
        "spend",
        "sales",
        "orders",
        "units",
        "acos",
        "roas",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for term_index in range(len(TERMS)):
            writer.writerow(row_for(site, week_index, term_index, report_type))


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed demo Amazon Ads data for the dashboard")
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--start-week", type=int, default=21)
    parser.add_argument("--end-week", type=int, default=27)
    parser.add_argument("--marketplaces", default=",".join(MARKETPLACES))
    parser.add_argument("--db-path", default=str(app.DB_PATH))
    parser.add_argument("--output-dir", default="data/ads_demo")
    parser.add_argument("--keep-existing-demo", action="store_true")
    args = parser.parse_args()

    weeks = week_range(args.start_week, args.end_week, args.year)
    marketplaces = [item.strip().upper() for item in args.marketplaces.split(",") if item.strip()]
    if not args.keep_existing_demo:
        removed = clean_demo_rows(args.db_path, weeks, marketplaces)
        print(f"Removed demo uploads: {removed}")

    imported_total = 0
    upload_total = 0
    output_dir = Path(args.output_dir)
    for week_index, week_id in enumerate(weeks):
        for site in marketplaces:
            for report_type in REPORT_TYPES:
                csv_path = output_dir / week_id / site / f"DEMO_ADS_SEED_{week_id}_{site}_{report_type}.csv"
                write_demo_csv(csv_path, site, week_index, report_type)
                imported = import_csv_to_db(
                    csv_path,
                    week_id,
                    site,
                    report_type,
                    f"DEMO_ADS_SEED; sample dashboard data; replace with Amazon Ads API or official export",
                )
                imported_total += imported
                upload_total += 1
    print(f"Seeded demo uploads: {upload_total}")
    print(f"Seeded demo rows: {imported_total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
