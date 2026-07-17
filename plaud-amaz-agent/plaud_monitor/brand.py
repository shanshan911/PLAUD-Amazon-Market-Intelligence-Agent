from __future__ import annotations

from typing import Any

import pandas as pd

from .config import competitors_for_marketplace
from .normalizers import normalize_key, normalize_text


def build_brand_mapping(config: dict[str, Any], marketplace: str) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for alias in config.get("plaud", {}).get("aliases", []):
        mapping[normalize_key(alias)] = "PLAUD"

    for competitor in competitors_for_marketplace(config, marketplace):
        brand = normalize_text(competitor.get("brand", ""))
        if not brand:
            continue
        aliases = [brand] + list(competitor.get("aliases", []))
        for alias in aliases:
            mapping[normalize_key(alias)] = brand
    return mapping


def competitor_meta(config: dict[str, Any], marketplace: str) -> dict[str, dict[str, Any]]:
    meta: dict[str, dict[str, Any]] = {}
    for competitor in competitors_for_marketplace(config, marketplace):
        brand = normalize_text(competitor.get("brand", ""))
        if brand:
            meta[brand] = competitor
    return meta


def standardize_brand_name(value: Any, mapping: dict[str, str]) -> str:
    text = normalize_text(value)
    return mapping.get(normalize_key(text), text)


def add_standard_brand_columns(df: pd.DataFrame, config: dict[str, Any], marketplace: str) -> pd.DataFrame:
    mapping = build_brand_mapping(config, marketplace)
    meta = competitor_meta(config, marketplace)
    result = df.copy()
    result["standard_brand"] = result["brand_name"].map(lambda value: standardize_brand_name(value, mapping))
    result["brand_group"] = "other"
    result.loc[result["standard_brand"] == "PLAUD", "brand_group"] = "plaud"
    result.loc[result["standard_brand"].isin(meta.keys()), "brand_group"] = "competitor"
    result["include_in_competitor_total"] = result["standard_brand"].map(
        lambda brand: bool(meta.get(brand, {}).get("include_in_total", True))
    )
    result["competitor_priority"] = result["standard_brand"].map(lambda brand: meta.get(brand, {}).get("priority", ""))
    return result
