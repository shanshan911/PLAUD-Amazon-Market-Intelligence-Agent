from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from plaud_monitor.config import load_config
from plaud_monitor.platform import init_db, latest_runs
from plaud_monitor.sellersprite_deep_dive import import_asin_keyword_intel_for_runs


DEFAULT_MARKETPLACES = ["US", "UK", "DE", "FR", "IT", "ES", "JP"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run SellerSprite MCP second-pass ASIN keyword deep dive")
    parser.add_argument("--config", default="config/monitor_config.p0.json")
    parser.add_argument("--env-file", default=".env.local")
    parser.add_argument("--db-path", default="data/db.sqlite")
    parser.add_argument("--week-id", default="", help="Week to process, e.g. 2026-W27; default latest successful week")
    parser.add_argument("--marketplaces", default="", help="Comma-separated sites; default reads config")
    parser.add_argument("--run-ids", default="", help="Comma-separated run IDs; overrides week/site selection")
    parser.add_argument("--top-asins", type=int, default=20)
    parser.add_argument("--keyword-limit", type=int, default=20)
    parser.add_argument("--month", default="", help="Optional SellerSprite month filter, e.g. 202606")
    parser.add_argument("--raw-dir", default="outputs/sellersprite_mcp_asin")
    parser.add_argument("--force-refresh", action="store_true")
    parser.add_argument("--throttle-seconds", type=float, default=1.55)
    args = parser.parse_args()

    root = Path(args.config).resolve().parents[1]
    load_env_file(root / args.env_file)
    config = load_config(args.config)
    init_db(args.db_path)
    run_ids = selected_run_ids(args, config)
    if not run_ids:
        print("No successful runs found for ASIN keyword deep dive.")
        return 2

    results = import_asin_keyword_intel_for_runs(
        config_path=args.config,
        run_ids=run_ids,
        db_path=args.db_path,
        top_n=args.top_asins,
        month=args.month or None,
        keyword_limit=args.keyword_limit,
        raw_dir=args.raw_dir,
        force_refresh=args.force_refresh,
        throttle_seconds=args.throttle_seconds,
    )
    ok_count = sum(1 for item in results if item.status in {"ok", "reused"})
    for item in results:
        suffix = f"rows={item.keyword_rows} asins={item.asin_count}"
        if item.error:
            suffix = f"{suffix} error={item.error}"
        print(f"{item.marketplace or item.run_id}: {item.status} {suffix}")
    return 0 if ok_count else 2


def selected_run_ids(args: argparse.Namespace, config: dict[str, Any]) -> list[int]:
    if args.run_ids:
        return [int(value.strip()) for value in args.run_ids.split(",") if value.strip()]

    marketplaces = selected_marketplaces(args.marketplaces, config)
    runs = [run for run in latest_runs(args.db_path, limit=4000) if run.get("status") == "ok"]
    if args.week_id:
        week_id = current_week_id() if args.week_id == "auto" else args.week_id
    else:
        week_id = latest_week_id(runs)
    selected: list[int] = []
    for marketplace in marketplaces:
        candidates = [
            run
            for run in runs
            if str(run.get("week_id")) == week_id and str(run.get("marketplace")).upper() == marketplace
        ]
        if not candidates:
            continue
        selected.append(int(max(candidates, key=lambda run: int(run.get("id") or 0))["id"]))
    return selected


def selected_marketplaces(raw: str, config: dict[str, Any]) -> list[str]:
    if raw:
        values = raw.split(",")
    else:
        values = config.get("monitoring", {}).get("marketplaces", DEFAULT_MARKETPLACES)
    return [str(value).strip().upper() for value in values if str(value).strip()]


def latest_week_id(runs: list[dict[str, Any]]) -> str:
    if not runs:
        return ""
    return str(max(runs, key=lambda run: (*week_sort_key(run.get("week_id")), int(run.get("id") or 0))).get("week_id") or "")


def current_week_id() -> str:
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    iso = now.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def week_sort_key(value: object) -> tuple[int, int, str]:
    text = str(value or "")
    if "-W" in text:
        year, week = text.split("-W", 1)
        try:
            return int(year), int(week), text
        except ValueError:
            pass
    return 0, 0, text


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
