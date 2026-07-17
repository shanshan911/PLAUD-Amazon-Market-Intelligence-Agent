from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from .config import load_config
from .excel_parser import parse_report
from .metrics import add_week_over_week, compute_ai_competitors, compute_brand_share
from .reporting import read_snapshot, write_csv, write_markdown_report, write_snapshot


@dataclass
class PipelineResult:
    output_dir: Path
    brand_share: pd.DataFrame
    ai_summary: pd.DataFrame
    ai_detail: pd.DataFrame
    run_log: list[dict[str, Any]]


def discover_report_file(config: dict[str, Any], week_id: str, marketplace: str, input_dir: Path | None = None) -> Path | None:
    input_cfg = config.get("input", {})
    raw_dir = input_dir or Path(input_cfg.get("raw_dir", "data/raw"))
    pattern = input_cfg.get("file_pattern", "{week_id}_{marketplace}_*.xlsx").format(
        week_id=week_id, marketplace=marketplace
    )
    candidates = sorted(raw_dir.rglob(pattern))
    return candidates[0] if candidates else None


def run_pipeline(
    config_path: str | Path,
    week_id: str | None = None,
    input_dir: str | Path | None = None,
    output_dir: str | Path | None = None,
    previous_snapshot: str | Path | None = None,
) -> PipelineResult:
    config = load_config(config_path)
    week = week_id or config.get("monitoring", {}).get("week_id")
    marketplaces = config.get("monitoring", {}).get("marketplaces", [])
    raw_dir = Path(input_dir) if input_dir else None
    base_output_dir = Path(output_dir or config.get("output", {}).get("output_dir", "outputs"))
    run_output_dir = base_output_dir / week
    run_output_dir.mkdir(parents=True, exist_ok=True)

    previous = read_snapshot(previous_snapshot)
    run_log: list[dict[str, Any]] = []
    brand_frames: list[pd.DataFrame] = []
    ai_summary_frames: list[pd.DataFrame] = []
    ai_detail_frames: list[pd.DataFrame] = []

    for marketplace in marketplaces:
        source_file = discover_report_file(config, week, marketplace, raw_dir)
        if source_file is None:
            run_log.append(
                {
                    "marketplace": marketplace,
                    "status": "missing_file",
                    "source_file": "",
                    "warnings": "",
                    "error": "未找到卖家精灵 Excel 报告",
                }
            )
            continue

        try:
            parsed = parse_report(source_file, marketplace, config)
            brand_share = compute_brand_share(parsed.brand_df, parsed.product_df, marketplace, config)
            ai_summary, ai_detail = compute_ai_competitors(parsed.product_df, marketplace, config)
            brand_frames.append(brand_share)
            ai_summary_frames.append(ai_summary)
            ai_detail_frames.append(ai_detail)
            run_log.append(
                {
                    "marketplace": marketplace,
                    "status": "ok",
                    "source_file": str(source_file),
                    "warnings": "; ".join(parsed.warnings),
                    "error": "",
                }
            )
        except Exception as exc:  # noqa: BLE001 - runtime log should capture per-site failures.
            run_log.append(
                {
                    "marketplace": marketplace,
                    "status": "error",
                    "source_file": str(source_file),
                    "warnings": "",
                    "error": str(exc),
                }
            )

    brand_share = pd.concat(brand_frames, ignore_index=True) if brand_frames else pd.DataFrame()
    ai_summary = pd.concat(ai_summary_frames, ignore_index=True) if ai_summary_frames else pd.DataFrame()
    ai_detail = pd.concat(ai_detail_frames, ignore_index=True) if ai_detail_frames else pd.DataFrame()

    prev_brand = previous.get("brand_share") if previous else None
    prev_ai = previous.get("ai_summary") if previous else None
    if not brand_share.empty:
        brand_share = add_week_over_week(
            brand_share,
            prev_brand,
            key_cols=["marketplace", "brand"],
            value_cols=["monthly_units_share", "monthly_revenue_share"],
        )
    if not ai_summary.empty:
        ai_summary = add_week_over_week(
            ai_summary,
            prev_ai,
            key_cols=["marketplace"],
            value_cols=["ai_units_share", "ai_revenue_share"],
        )

    write_csv(brand_share, run_output_dir / "brand_share.csv")
    write_csv(ai_summary, run_output_dir / "ai_competitor_summary.csv")
    write_csv(ai_detail, run_output_dir / "ai_competitor_asins.csv")
    write_csv(pd.DataFrame(run_log), run_output_dir / "run_log.csv")
    write_markdown_report(run_output_dir / "weekly_report.md", week, brand_share, ai_summary, ai_detail, run_log)
    write_snapshot(run_output_dir / "metrics_snapshot.json", brand_share, ai_summary)

    return PipelineResult(
        output_dir=run_output_dir,
        brand_share=brand_share,
        ai_summary=ai_summary,
        ai_detail=ai_detail,
        run_log=run_log,
    )
