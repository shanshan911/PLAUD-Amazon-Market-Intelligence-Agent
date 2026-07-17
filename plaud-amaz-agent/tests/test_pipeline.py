from __future__ import annotations

from pathlib import Path

from plaud_monitor.pipeline import run_pipeline
from scripts.create_mock_reports import create_mock_report


def test_pipeline_with_mock_reports(tmp_path: Path) -> None:
    week = "2026-W20"
    raw_dir = tmp_path / "raw"
    out_dir = tmp_path / "outputs"
    for marketplace in ["US", "ES"]:
        create_mock_report(raw_dir / week / marketplace / f"{week}_{marketplace}_VoiceRecorders.xlsx", marketplace)

    config_path = tmp_path / "config.json"
    config_path.write_text(
        """
{
  "monitoring": {"week_id": "2026-W20", "marketplaces": ["US", "ES"]},
  "plaud": {"aliases": ["PLAUD", "Plaud", "PLAUD NOTE"]},
  "competitors": {
    "default": [
      {"brand": "Sony", "aliases": ["SONY"], "priority": "高", "include_in_total": true},
      {"brand": "iFLYTEK", "aliases": ["IFLYTEK"], "priority": "高", "include_in_total": true}
    ]
  },
  "ai_rules": {
    "default_keywords": ["AI", "A.I.", "Artificial Intelligence"],
    "marketplace_keywords": {"ES": ["IA", "Inteligencia Artificial"]},
    "exclude_terms": ["MAIN"]
  },
  "input": {"raw_dir": "unused", "file_pattern": "{week_id}_{marketplace}_*.xlsx"},
  "output": {"output_dir": "unused"}
}
""",
        encoding="utf-8",
    )

    result = run_pipeline(config_path, input_dir=raw_dir, output_dir=out_dir)

    assert (result.output_dir / "brand_share.csv").exists()
    assert (result.output_dir / "ai_competitor_summary.csv").exists()
    assert (result.output_dir / "weekly_report.md").exists()
    assert result.ai_summary["ai_competitor_asin_count"].sum() > 0
    assert "PLAUD" in set(result.brand_share["brand"])
