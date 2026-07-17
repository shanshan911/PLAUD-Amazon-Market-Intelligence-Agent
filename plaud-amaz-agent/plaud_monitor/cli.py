from __future__ import annotations

import argparse
from pathlib import Path

from .config import write_example_config
from .pipeline import run_pipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PLAUD Amazon monitoring data pipeline")
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="Run the data pipeline")
    run_parser.add_argument("--config", required=True, help="Path to JSON config")
    run_parser.add_argument("--week", help="Week id, for example 2026-W20")
    run_parser.add_argument("--input-dir", help="Folder that contains raw SellerSprite Excel reports")
    run_parser.add_argument("--output-dir", help="Output folder")
    run_parser.add_argument("--previous-snapshot", help="Previous metrics_snapshot.json for WoW comparison")

    init_parser = subparsers.add_parser("init-config", help="Create an example config")
    init_parser.add_argument("--path", default="config/monitor_config.example.json")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "init-config":
        write_example_config(Path(args.path))
        print(f"Example config written to {args.path}")
        return 0

    if args.command == "run":
        result = run_pipeline(
            config_path=args.config,
            week_id=args.week,
            input_dir=args.input_dir,
            output_dir=args.output_dir,
            previous_snapshot=args.previous_snapshot,
        )
        ok_count = sum(1 for item in result.run_log if item["status"] == "ok")
        print(f"Processed {ok_count}/{len(result.run_log)} marketplaces")
        print(f"Output: {result.output_dir}")
        return 0

    parser.print_help()
    return 1
