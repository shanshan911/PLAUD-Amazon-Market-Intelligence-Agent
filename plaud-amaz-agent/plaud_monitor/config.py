from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any


DEFAULT_FIELD_ALIASES: dict[str, list[str]] = {
    "brand_name": ["品牌名", "品牌", "Brand", "brand"],
    "asin": ["ASIN", "asin"],
    "product_title": ["商品标题", "标题", "Product Title", "Title"],
    "product_type": ["类型", "商品类型", "Type"],
    "monthly_units": ["月销量", "求和项:月销量", "销量", "Monthly Sales", "Monthly Units"],
    "monthly_revenue": ["月销售额", "求和项:月销售额", "销售额", "Monthly Revenue", "Revenue"],
    "monthly_units_share": ["月销量占比", "销量占比", "市场份额", "Monthly Sales Share", "Unit Share", "Market Share"],
    "monthly_revenue_share": ["月销售额占比", "销售额占比", "Revenue Share"],
    "price": ["价格", "售价", "Price"],
    "bsr_rank": ["BSR排名", "BSR", "排名", "Rank", "小类BSR", "大类BSR"],
    "product_url": ["商品链接", "商品详情页链接", "链接", "URL", "Product URL"],
}


DEFAULT_SHEETS: dict[str, list[str]] = {
    "brand_concentration": ["品牌集中度", "Brands", "Brand Concentration"],
    "product_concentration": ["商品集中度", "Product Concentration"],
}


DEFAULT_CONFIG: dict[str, Any] = {
    "monitoring": {
        "week_id": "2026-W20",
        "marketplaces": ["US", "UK", "DE", "FR", "IT", "ES", "JP"],
    },
    "marketplaces": {},
    "plaud": {"aliases": ["PLAUD", "Plaud", "PLAUD AI", "PLAUD NOTE", "PLAUD-AI"]},
    "competitors": {"default": []},
    "ai_rules": {
        "default_keywords": ["AI", "A.I.", "Artificial Intelligence"],
        "marketplace_keywords": {},
        "exclude_terms": ["MAIN"],
    },
    "input": {
        "raw_dir": "data/raw",
        "file_pattern": "{week_id}_{marketplace}_*.xlsx",
    },
    "output": {
        "output_dir": "outputs",
        "report_formats": ["csv", "markdown"],
        "thresholds": {
            "plaud_share_pp": 3,
            "competitor_jump_pp": 5,
            "ai_share_pp": 5,
        },
    },
    "api_integrations": {
        "amazon_ads": {
            "enabled": False,
            "region": "EU",
            "client_id_env": "AMAZON_ADS_CLIENT_ID",
            "client_secret_env": "AMAZON_ADS_CLIENT_SECRET",
            "refresh_token_env": "AMAZON_ADS_REFRESH_TOKEN",
            "profile_id_env": "AMAZON_ADS_PROFILE_ID",
            "timeout_seconds": 30,
        },
        "sp_api": {
            "enabled": False,
            "selling_region": "EU",
            "endpoint": "https://sellingpartnerapi-eu.amazon.com",
            "aws_region": "eu-west-1",
            "lwa_client_id_env": "SP_API_LWA_CLIENT_ID",
            "lwa_client_secret_env": "SP_API_LWA_CLIENT_SECRET",
            "refresh_token_env": "SP_API_REFRESH_TOKEN",
            "aws_access_key_env": "SP_API_AWS_ACCESS_KEY_ID",
            "aws_secret_key_env": "SP_API_AWS_SECRET_ACCESS_KEY",
            "aws_session_token_env": "SP_API_AWS_SESSION_TOKEN",
            "user_agent": "PLAUDMonitor/0.1 (Language=Python)",
            "timeout_seconds": 30,
        },
        "sellersprite": {
            "enabled": False,
            "base_url": "https://api.sellersprite.com",
            "secret_key_env": "SELLERSPRITE_SECRET_KEY",
            "timeout_seconds": 30,
        },
    },
    "sheets": DEFAULT_SHEETS,
    "field_aliases": DEFAULT_FIELD_ALIASES,
}


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as f:
        user_config = json.load(f)
    config = deep_merge(DEFAULT_CONFIG, user_config)
    config["_config_path"] = str(config_path.resolve())
    return config


def write_example_config(path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as f:
        json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)


def marketplace_config(config: dict[str, Any], marketplace: str) -> dict[str, Any]:
    return config.get("marketplaces", {}).get(marketplace, {})


def competitors_for_marketplace(config: dict[str, Any], marketplace: str) -> list[dict[str, Any]]:
    competitors = config.get("competitors", {})
    return list(competitors.get("default", [])) + list(competitors.get(marketplace, []))


def ai_keywords_for_marketplace(config: dict[str, Any], marketplace: str) -> list[str]:
    rules = config.get("ai_rules", {})
    keywords = list(rules.get("default_keywords", []))
    keywords.extend(rules.get("marketplace_keywords", {}).get(marketplace, []))
    seen: set[str] = set()
    unique = []
    for keyword in keywords:
        key = keyword.casefold()
        if key not in seen:
            seen.add(key)
            unique.append(keyword)
    return unique
