from __future__ import annotations

from typing import Any
from urllib.request import Request, urlopen

from .base import ApiConfigError, build_url, form_json, http_json, require_env


ADS_REGION_ENDPOINTS = {
    "NA": "https://advertising-api.amazon.com",
    "EU": "https://advertising-api-eu.amazon.com",
    "FE": "https://advertising-api-fe.amazon.com",
}

MARKETPLACE_ADS_REGION = {
    "US": "NA",
    "CA": "NA",
    "MX": "NA",
    "BR": "NA",
    "UK": "EU",
    "DE": "EU",
    "FR": "EU",
    "IT": "EU",
    "ES": "EU",
    "NL": "EU",
    "SE": "EU",
    "TR": "EU",
    "JP": "FE",
    "AU": "FE",
    "SG": "FE",
}

LWA_TOKEN_URL = "https://api.amazon.com/auth/o2/token"


def ads_region_for_marketplace(marketplace: str) -> str:
    return MARKETPLACE_ADS_REGION.get(marketplace.upper(), "EU")


class AmazonAdsClient:
    """Small Amazon Ads API client for OAuth, profiles, and report endpoints."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        region: str = "EU",
        timeout_seconds: int = 30,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.region = region.upper()
        self.timeout_seconds = int(timeout_seconds or 30)
        if self.region not in ADS_REGION_ENDPOINTS:
            raise ApiConfigError(f"Unsupported Amazon Ads region: {region}")
        self.base_url = ADS_REGION_ENDPOINTS[self.region]

    @classmethod
    def from_config(cls, config: dict[str, Any], marketplace: str | None = None) -> "AmazonAdsClient":
        cfg = config.get("api_integrations", {}).get("amazon_ads", {})
        region = ads_region_for_marketplace(marketplace) if marketplace else str(cfg.get("region") or "EU")
        return cls(
            client_id=require_env(cfg, "client_id_env"),
            client_secret=require_env(cfg, "client_secret_env"),
            refresh_token=require_env(cfg, "refresh_token_env"),
            region=region,
            timeout_seconds=int(cfg.get("timeout_seconds") or 30),
        )

    def refresh_access_token(self) -> dict[str, Any]:
        return form_json(
            LWA_TOKEN_URL,
            {
                "grant_type": "refresh_token",
                "refresh_token": self.refresh_token,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
            timeout=self.timeout_seconds,
        )

    def auth_headers(self, access_token: str, profile_id: str | int | None = None) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Amazon-Advertising-API-ClientId": self.client_id,
            "Content-Type": "application/json",
        }
        if profile_id:
            headers["Amazon-Advertising-API-Scope"] = str(profile_id)
        return headers

    def list_profiles(
        self,
        access_token: str | None = None,
        access_level: str | None = None,
        api_program: str | None = None,
    ) -> list[dict[str, Any]]:
        token = access_token or str(self.refresh_access_token().get("access_token") or "")
        url = build_url(
            self.base_url,
            "/v2/profiles",
            {"accessLevel": access_level, "apiProgram": api_program},
        )
        result = http_json("GET", url, self.auth_headers(token), timeout=self.timeout_seconds)
        return result if isinstance(result, list) else []

    def request_json(
        self,
        method: str,
        path: str,
        profile_id: str | int,
        query: dict[str, Any] | None = None,
        body: Any | None = None,
        access_token: str | None = None,
    ) -> Any:
        token = access_token or str(self.refresh_access_token().get("access_token") or "")
        url = build_url(self.base_url, path, query)
        return http_json(method, url, self.auth_headers(token, profile_id), body, self.timeout_seconds)

    def create_report(self, profile_id: str | int, report_request: dict[str, Any], access_token: str | None = None) -> dict[str, Any]:
        result = self.request_json("POST", "/reporting/reports", profile_id, body=report_request, access_token=access_token)
        return result if isinstance(result, dict) else {}

    def get_report(self, profile_id: str | int, report_id: str, access_token: str | None = None) -> dict[str, Any]:
        result = self.request_json("GET", f"/reporting/reports/{report_id}", profile_id, access_token=access_token)
        return result if isinstance(result, dict) else {}


def download_ads_report(download_url: str, timeout_seconds: int = 60) -> bytes:
    request = Request(download_url, headers={"Accept": "*/*"}, method="GET")
    with urlopen(request, timeout=timeout_seconds) as response:
        return response.read()


def profile_id_from_config(config: dict[str, Any]) -> str:
    cfg = config.get("api_integrations", {}).get("amazon_ads", {})
    return require_env(cfg, "profile_id_env")
