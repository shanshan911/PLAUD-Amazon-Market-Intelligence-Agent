from __future__ import annotations

from typing import Any

from .base import EnvRequirement, missing_envs


SERVICE_REQUIREMENTS = {
    "amazon_ads": {
        "label": "Amazon Ads API",
        "use_case": "广告花费、Campaign/Search Term 报告、ACOS/TACOS 与广告驱动份额分析",
        "env": [
            EnvRequirement("client_id_env", "Client ID"),
            EnvRequirement("client_secret_env", "Client Secret"),
            EnvRequirement("refresh_token_env", "Refresh Token"),
        ],
        "config": [],
    },
    "sp_api": {
        "label": "Amazon SP-API",
        "use_case": "卖家订单、Catalog、库存、定价、Reports/Sales 等官方经营数据",
        "env": [
            EnvRequirement("lwa_client_id_env", "LWA Client ID"),
            EnvRequirement("lwa_client_secret_env", "LWA Client Secret"),
            EnvRequirement("refresh_token_env", "Refresh Token"),
            EnvRequirement("aws_access_key_env", "AWS Access Key"),
            EnvRequirement("aws_secret_key_env", "AWS Secret Key"),
        ],
        "config": ["endpoint", "aws_region", "user_agent"],
    },
    "sellersprite": {
        "label": "SellerSprite API",
        "use_case": "类目市场、竞品 ASIN、关键词、BSR 销量反推与第三方市场估算",
        "env": [
            EnvRequirement("secret_key_env", "Secret Key"),
        ],
        "config": ["base_url"],
    },
}


def integration_statuses(config: dict[str, Any]) -> list[dict[str, Any]]:
    integrations = config.get("api_integrations", {})
    statuses: list[dict[str, Any]] = []
    for key, meta in SERVICE_REQUIREMENTS.items():
        cfg = integrations.get(key, {})
        enabled = bool(cfg.get("enabled"))
        missing = missing_envs(cfg, list(meta["env"]))
        missing_config = [
            field
            for field in meta["config"]
            if not str(cfg.get(field) or "").strip()
        ]
        ready = enabled and not missing and not missing_config
        statuses.append(
            {
                "key": key,
                "label": meta["label"],
                "enabled": enabled,
                "ready": ready,
                "missing_env": missing,
                "missing_config": missing_config,
                "use_case": meta["use_case"],
                "next_step": _next_step(enabled, missing, missing_config),
            }
        )
    return statuses


def _next_step(enabled: bool, missing: list[str], missing_config: list[str]) -> str:
    if not enabled:
        return "配置中 enabled=true 后再做联调"
    if missing:
        return "补齐环境变量：" + ", ".join(missing)
    if missing_config:
        return "补齐配置项：" + ", ".join(missing_config)
    return "可执行连通性测试"
