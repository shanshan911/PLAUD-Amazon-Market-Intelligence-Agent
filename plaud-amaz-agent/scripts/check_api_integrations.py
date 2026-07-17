from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from plaud_monitor.config import load_config
from plaud_monitor.integrations import AmazonAdsClient, SellerSpriteClient, SellingPartnerClient, integration_statuses
from plaud_monitor.integrations.base import ApiConfigError, ApiRequestError, redact
from plaud_monitor.normalizers import normalize_text


def main() -> int:
    parser = argparse.ArgumentParser(description="Check official API integration readiness")
    parser.add_argument("--config", default="config/monitor_config.p0.json", help="Path to monitor config")
    parser.add_argument("--env-file", default=".env.local", help="Optional local env file for API secrets")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Attempt non-mutating live checks for enabled integrations",
    )
    parser.add_argument("--sellersprite-marketplace", default="US", help="Marketplace for optional SellerSprite ASIN check")
    parser.add_argument("--sellersprite-asin", default="", help="Optional ASIN for SellerSprite live detail check")
    args = parser.parse_args()

    load_env_file(Path(args.config).resolve().parents[1] / args.env_file)
    config = load_config(args.config)
    statuses = integration_statuses(config)
    if args.live:
        append_live_checks(config, statuses, args.sellersprite_marketplace, args.sellersprite_asin)

    if args.json:
        print(json.dumps(statuses, ensure_ascii=False, indent=2))
    else:
        print("PLAUD official API integration readiness")
        print(f"Config: {Path(args.config).resolve()}")
        for item in statuses:
            enabled = "enabled" if item["enabled"] else "disabled"
            ready = "ready" if item["ready"] else "not ready"
            print(f"- {item['label']}: {enabled}, {ready}")
            print(f"  Use case: {item['use_case']}")
            print(f"  Next: {item['next_step']}")
            if item.get("live_check"):
                print(f"  Live: {item['live_check']}")
    return 0


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def append_live_checks(config: dict, statuses: list[dict], sellersprite_marketplace: str, sellersprite_asin: str) -> None:
    by_key = {item["key"]: item for item in statuses}
    if by_key.get("amazon_ads", {}).get("ready"):
        try:
            profiles = AmazonAdsClient.from_config(config).list_profiles()
            by_key["amazon_ads"]["live_check"] = f"profiles={len(profiles)}"
        except (ApiConfigError, ApiRequestError) as exc:
            by_key["amazon_ads"]["live_check"] = f"failed: {exc}"
    if by_key.get("sp_api", {}).get("ready"):
        try:
            token = SellingPartnerClient.from_config(config).refresh_access_token()
            expires = token.get("expires_in", "")
            by_key["sp_api"]["live_check"] = f"LWA token ok, expires_in={expires}"
        except (ApiConfigError, ApiRequestError) as exc:
            by_key["sp_api"]["live_check"] = f"failed: {exc}"
    if by_key.get("sellersprite", {}).get("ready"):
        try:
            client = SellerSpriteClient.from_config(config)
            if sellersprite_asin:
                payload = client.asin_detail(sellersprite_marketplace, sellersprite_asin)
                validate_sellersprite_response(payload, "ASIN detail")
                data = payload.get("data") if isinstance(payload, dict) else None
                if isinstance(data, dict):
                    keys = ", ".join(list(data.keys())[:8])
                    by_key["sellersprite"]["live_check"] = f"ASIN detail ok, data_keys={keys}"
                else:
                    by_key["sellersprite"]["live_check"] = f"ASIN detail ok, data_type={type(data).__name__}"
            else:
                payload = client.visits()
                validate_sellersprite_response(payload, "visits")
                data = payload.get("data") if isinstance(payload, dict) else None
                by_key["sellersprite"]["live_check"] = (
                    f"visits ok, secret={redact(client.secret_key)}, data_type={type(data).__name__}"
                )
        except (ApiConfigError, ApiRequestError) as exc:
            by_key["sellersprite"]["live_check"] = f"failed: {exc}"


def validate_sellersprite_response(payload: object, label: str) -> None:
    if not isinstance(payload, dict):
        raise ApiRequestError(f"{label} returned non-object response")
    code = normalize_text(payload.get("code"))
    message = normalize_text(payload.get("message"))
    if code and code.upper() != "OK":
        raise ApiRequestError(f"{label} failed: code={code}, message={message}")
    if "data" not in payload:
        raise ApiRequestError(f"{label} response missing data: code={code}, message={message}")


if __name__ == "__main__":
    raise SystemExit(main())
