from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from plaud_monitor.config import load_config


def marketplace_multiplier(marketplace: str) -> float:
    return {
        "US": 1.0,
        "UK": 0.72,
        "DE": 0.82,
        "FR": 0.65,
        "IT": 0.55,
        "ES": 0.5,
        "JP": 0.78,
    }.get(marketplace, 1.0)


def build_brand_rows(marketplace: str) -> list[dict[str, object]]:
    factor = marketplace_multiplier(marketplace)
    rows = [
        {"品牌名": "PLAUD", "月销量": int(4200 * factor), "月销售额": round(630000 * factor, 2), "月销量占比": "28.0%", "月销售额占比": "34.0%"},
        {"品牌名": "Sony", "月销量": int(2100 * factor), "月销售额": round(252000 * factor, 2), "月销量占比": "14.0%", "月销售额占比": "13.6%"},
        {"品牌名": "Olympus", "月销量": int(1600 * factor), "月销售额": round(176000 * factor, 2), "月销量占比": "10.7%", "月销售额占比": "9.5%"},
        {"品牌名": "iFLYTEK", "月销量": int(900 * factor), "月销售额": round(180000 * factor, 2), "月销量占比": "6.0%", "月销售额占比": "9.7%"},
        {"品牌名": "OtherBrand", "月销量": int(6200 * factor), "月销售额": round(614000 * factor, 2), "月销量占比": "41.3%", "月销售额占比": "33.2%"},
    ]
    if marketplace == "JP":
        rows.append({"品牌名": "Panasonic", "月销量": int(700 * factor), "月销售额": round(77000 * factor, 2), "月销量占比": "4.7%", "月销售额占比": "4.1%"})
    return rows


def build_product_rows(marketplace: str) -> list[dict[str, object]]:
    factor = marketplace_multiplier(marketplace)
    return [
        {"ASIN": f"{marketplace}PLAUD001", "品牌名": "PLAUD", "商品标题": "PLAUD NOTE AI Voice Recorder with Summary", "月销量": int(3000 * factor), "月销售额": round(450000 * factor, 2), "BSR排名": 1},
        {"ASIN": f"{marketplace}PLAUD002", "品牌名": "Plaud", "商品标题": "PLAUD NOTE Voice Recorder", "月销量": int(1200 * factor), "月销售额": round(180000 * factor, 2), "BSR排名": 3},
        {"ASIN": f"{marketplace}SONY001", "品牌名": "Sony", "商品标题": "Sony Digital Voice Recorder", "月销量": int(1300 * factor), "月销售额": round(156000 * factor, 2), "BSR排名": 2},
        {"ASIN": f"{marketplace}SONYAI2", "品牌名": "Sony", "商品标题": "Sony AI Voice Recorder with Noise Reduction", "月销量": int(800 * factor), "月销售额": round(96000 * factor, 2), "BSR排名": 5},
        {"ASIN": f"{marketplace}OLY001", "品牌名": "Olympus", "商品标题": "Olympus Digital Recorder", "月销量": int(1600 * factor), "月销售额": round(176000 * factor, 2), "BSR排名": 6},
        {"ASIN": f"{marketplace}IFLYAI", "品牌名": "iFLYTEK", "商品标题": "iFLYTEK AI Recorder with ChatGPT Summary", "月销量": int(900 * factor), "月销售额": round(180000 * factor, 2), "BSR排名": 8},
        {"ASIN": f"{marketplace}OTH001", "品牌名": "OtherBrand", "商品标题": "Mini Voice Recorder", "月销量": int(4200 * factor), "月销售额": round(294000 * factor, 2), "BSR排名": 10},
        {"ASIN": f"{marketplace}OTHIA2", "品牌名": "OtherBrand", "商品标题": localized_ai_title(marketplace), "月销量": int(2000 * factor), "月销售额": round(320000 * factor, 2), "BSR排名": 12},
        {"ASIN": f"{marketplace}MAIN01", "品牌名": "OtherBrand", "商品标题": "MAIN Voice Recorder Portable", "月销量": int(500 * factor), "月销售额": round(35000 * factor, 2), "BSR排名": 18},
    ]


def localized_ai_title(marketplace: str) -> str:
    return {
        "DE": "KI Diktiergerät mit Transkription",
        "FR": "Dictaphone IA avec transcription",
        "IT": "Registratore vocale IA con trascrizione",
        "ES": "Grabadora de voz IA con transcripción",
        "JP": "人工知能 ボイスレコーダー 文字起こし",
    }.get(marketplace, "AI Voice Recorder with Transcription")


def create_mock_report(output_path: Path, marketplace: str) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        pd.DataFrame(build_brand_rows(marketplace)).to_excel(writer, sheet_name="品牌集中度", index=False)
        pd.DataFrame(build_product_rows(marketplace)).to_excel(writer, sheet_name="商品集中度", index=False)


def main() -> int:
    parser = argparse.ArgumentParser(description="Create mock SellerSprite reports")
    parser.add_argument("--config", default="config/monitor_config.example.json")
    parser.add_argument("--week", default=None)
    parser.add_argument("--output-dir", default="data/mock/raw")
    args = parser.parse_args()

    config = load_config(args.config)
    week = args.week or config["monitoring"]["week_id"]
    marketplaces = config["monitoring"]["marketplaces"]
    output_dir = Path(args.output_dir)
    for marketplace in marketplaces:
        path = output_dir / week / marketplace / f"{week}_{marketplace}_VoiceRecorders.xlsx"
        create_mock_report(path, marketplace)
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
