from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from plaud_monitor.config import load_config
from plaud_monitor.sellersprite_importer import import_sellersprite_market


def main() -> int:
    parser = argparse.ArgumentParser(description="Import SellerSprite market data into PLAUD monitor")
    parser.add_argument("--config", default="config/monitor_config.p0.json", help="Path to monitor config")
    parser.add_argument("--env-file", default=".env.local", help="Optional local env file for API secrets")
    parser.add_argument("--marketplace", help="Single marketplace code, e.g. IT")
    parser.add_argument("--marketplaces", help="Comma-separated marketplace codes, e.g. US,UK,DE,FR,IT,ES,JP")
    parser.add_argument("--week-id", default="", help="Week id for the imported run")
    parser.add_argument("--node-id-path", default="", help="SellerSprite nodeIdPath; omit to use config/category URL")
    parser.add_argument("--month", default="", help="SellerSprite month filter, e.g. 202605")
    parser.add_argument("--top-n", type=int, default=100, help="Top listing count for concentration APIs")
    parser.add_argument("--new-product", type=int, default=6, help="New product window in months")
    parser.add_argument("--no-resolve-node", action="store_true", help="Use extracted Amazon node id directly")
    parser.add_argument("--db-path", default="data/db.sqlite", help="SQLite database path")
    parser.add_argument("--raw-dir", default="outputs/sellersprite", help="Directory for raw API JSON payloads")
    parser.add_argument("--report-dir", default="outputs/reports", help="Directory for generated reports")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and save raw JSON without inserting into DB")
    args = parser.parse_args()

    root = Path(args.config).resolve().parents[1]
    load_env_file(root / args.env_file)
    config = load_config(args.config)
    marketplaces = selected_marketplaces(args, config)
    if not marketplaces:
        raise SystemExit("Provide --marketplace, --marketplaces, or monitoring.marketplaces in config")

    for marketplace in marketplaces:
        result = import_sellersprite_market(
            config_path=args.config,
            marketplace=marketplace,
            week_id=args.week_id or None,
            node_id_path=args.node_id_path or None,
            month=args.month or None,
            top_n=args.top_n,
            new_product=args.new_product,
            resolve_node=not args.no_resolve_node,
            db_path=args.db_path,
            raw_dir=args.raw_dir,
            report_dir=args.report_dir,
            dry_run=args.dry_run,
        )
        if result.status == "ok":
            print(
                f"{marketplace}: imported run_id={result.run_id}, "
                f"raw={result.upload_path}, report={result.excel_report_path}"
            )
        elif result.status == "dry_run":
            print(f"{marketplace}: dry run ok, raw={result.upload_path}")
        else:
            print(f"{marketplace}: failed run_id={result.run_id}, error={result.error}")
    return 0


def selected_marketplaces(args: argparse.Namespace, config: dict) -> list[str]:
    if args.marketplaces:
        values = args.marketplaces.split(",")
    elif args.marketplace:
        values = [args.marketplace]
    else:
        values = config.get("monitoring", {}).get("marketplaces", [])
    return [str(value).strip().upper() for value in values if str(value).strip()]


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
