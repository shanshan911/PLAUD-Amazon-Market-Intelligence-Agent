from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from plaud_monitor.config import load_config
from plaud_monitor.excel_parser import parse_report


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse one SellerSprite Excel report and export normalized previews")
    parser.add_argument("--config", default="config/monitor_config.example.json", help="Path to JSON config")
    parser.add_argument("--file", required=True, help="SellerSprite Excel report path")
    parser.add_argument("--marketplace", required=True, help="Marketplace code, for example US")
    parser.add_argument("--output-dir", default="outputs/parse_preview", help="Preview output folder")
    args = parser.parse_args()

    config = load_config(args.config)
    parsed = parse_report(args.file, args.marketplace, config)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    brand_path = output_dir / f"{args.marketplace}_brand_concentration_normalized.csv"
    product_path = output_dir / f"{args.marketplace}_product_concentration_normalized.csv"

    parsed.brand_df.to_csv(brand_path, index=False, encoding="utf-8-sig")
    parsed.product_df.to_csv(product_path, index=False, encoding="utf-8-sig")

    print(f"Parsed: {parsed.source_file}")
    print(f"Brand rows: {len(parsed.brand_df)} -> {brand_path}")
    print(f"Product rows: {len(parsed.product_df)} -> {product_path}")
    if parsed.warnings:
        print("Warnings:")
        for warning in parsed.warnings:
            print(f"- {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
