from __future__ import annotations

import hashlib
import hmac
import json
import urllib.parse
from datetime import datetime, timezone
from typing import Any

from .base import ApiConfigError, build_url, env_value, form_json, http_json, require_env


SP_REGION_ENDPOINTS = {
    "NA": ("https://sellingpartnerapi-na.amazon.com", "us-east-1"),
    "EU": ("https://sellingpartnerapi-eu.amazon.com", "eu-west-1"),
    "FE": ("https://sellingpartnerapi-fe.amazon.com", "us-west-2"),
}

MARKETPLACE_SP_REGION = {
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
    "PL": "EU",
    "TR": "EU",
    "AE": "EU",
    "IN": "EU",
    "JP": "FE",
    "AU": "FE",
    "SG": "FE",
}

LWA_TOKEN_URL = "https://api.amazon.com/auth/o2/token"


def sp_region_for_marketplace(marketplace: str) -> str:
    return MARKETPLACE_SP_REGION.get(marketplace.upper(), "EU")


def _aws_quote(value: str) -> str:
    return urllib.parse.quote(value, safe="-_.~")


def _canonical_query(query: str) -> str:
    params = urllib.parse.parse_qsl(query, keep_blank_values=True)
    return "&".join(f"{_aws_quote(k)}={_aws_quote(v)}" for k, v in sorted(params))


def _canonical_headers(headers: dict[str, str]) -> tuple[str, str]:
    normalized = {
        key.lower().strip(): " ".join(str(value).strip().split())
        for key, value in headers.items()
        if value is not None
    }
    ordered = sorted(normalized.items())
    canonical = "".join(f"{key}:{value}\n" for key, value in ordered)
    signed = ";".join(key for key, _ in ordered)
    return canonical, signed


def _sign(key: bytes, message: str) -> bytes:
    return hmac.new(key, message.encode("utf-8"), hashlib.sha256).digest()


def _signature_key(secret_key: str, date_stamp: str, region_name: str, service_name: str) -> bytes:
    key_date = _sign(("AWS4" + secret_key).encode("utf-8"), date_stamp)
    key_region = _sign(key_date, region_name)
    key_service = _sign(key_region, service_name)
    return _sign(key_service, "aws4_request")


class SigV4Signer:
    def __init__(
        self,
        access_key: str,
        secret_key: str,
        region: str,
        service: str = "execute-api",
        session_token: str = "",
    ) -> None:
        self.access_key = access_key
        self.secret_key = secret_key
        self.region = region
        self.service = service
        self.session_token = session_token

    def sign(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        payload: bytes,
        request_time: datetime | None = None,
    ) -> dict[str, str]:
        now = request_time or datetime.now(timezone.utc)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = now.strftime("%Y%m%d")
        parsed = urllib.parse.urlsplit(url)
        signed_headers = dict(headers)
        signed_headers["host"] = parsed.netloc
        signed_headers["x-amz-date"] = amz_date
        if self.session_token:
            signed_headers["x-amz-security-token"] = self.session_token

        payload_hash = hashlib.sha256(payload).hexdigest()
        canonical_headers, signed_header_names = _canonical_headers(signed_headers)
        canonical_request = "\n".join(
            [
                method.upper(),
                urllib.parse.quote(parsed.path or "/", safe="/-_.~"),
                _canonical_query(parsed.query),
                canonical_headers,
                signed_header_names,
                payload_hash,
            ]
        )
        credential_scope = f"{date_stamp}/{self.region}/{self.service}/aws4_request"
        string_to_sign = "\n".join(
            [
                "AWS4-HMAC-SHA256",
                amz_date,
                credential_scope,
                hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
            ]
        )
        signature = hmac.new(
            _signature_key(self.secret_key, date_stamp, self.region, self.service),
            string_to_sign.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        signed_headers["Authorization"] = (
            "AWS4-HMAC-SHA256 "
            f"Credential={self.access_key}/{credential_scope}, "
            f"SignedHeaders={signed_header_names}, "
            f"Signature={signature}"
        )
        return signed_headers


class SellingPartnerClient:
    """SP-API client with LWA token refresh and AWS SigV4 request signing."""

    def __init__(
        self,
        lwa_client_id: str,
        lwa_client_secret: str,
        refresh_token: str,
        aws_access_key: str,
        aws_secret_key: str,
        endpoint: str,
        aws_region: str,
        user_agent: str,
        aws_session_token: str = "",
        timeout_seconds: int = 30,
    ) -> None:
        self.lwa_client_id = lwa_client_id
        self.lwa_client_secret = lwa_client_secret
        self.refresh_token = refresh_token
        self.endpoint = endpoint.rstrip("/")
        self.aws_region = aws_region
        self.user_agent = user_agent
        self.timeout_seconds = int(timeout_seconds or 30)
        self.signer = SigV4Signer(
            access_key=aws_access_key,
            secret_key=aws_secret_key,
            region=aws_region,
            session_token=aws_session_token,
        )

    @classmethod
    def from_config(cls, config: dict[str, Any], marketplace: str | None = None) -> "SellingPartnerClient":
        cfg = config.get("api_integrations", {}).get("sp_api", {})
        selling_region = sp_region_for_marketplace(marketplace) if marketplace else str(cfg.get("selling_region") or "EU").upper()
        default_endpoint, default_aws_region = SP_REGION_ENDPOINTS.get(selling_region, SP_REGION_ENDPOINTS["EU"])
        endpoint = default_endpoint if marketplace else str(cfg.get("endpoint") or default_endpoint)
        aws_region = default_aws_region if marketplace else str(cfg.get("aws_region") or default_aws_region)
        return cls(
            lwa_client_id=require_env(cfg, "lwa_client_id_env"),
            lwa_client_secret=require_env(cfg, "lwa_client_secret_env"),
            refresh_token=require_env(cfg, "refresh_token_env"),
            aws_access_key=require_env(cfg, "aws_access_key_env"),
            aws_secret_key=require_env(cfg, "aws_secret_key_env"),
            aws_session_token=env_value(cfg, "aws_session_token_env") if cfg.get("aws_session_token_env") else "",
            endpoint=endpoint,
            aws_region=aws_region,
            user_agent=str(cfg.get("user_agent") or "PLAUDMonitor/0.1 (Language=Python)"),
            timeout_seconds=int(cfg.get("timeout_seconds") or 30),
        )

    def refresh_access_token(self) -> dict[str, Any]:
        return form_json(
            LWA_TOKEN_URL,
            {
                "grant_type": "refresh_token",
                "refresh_token": self.refresh_token,
                "client_id": self.lwa_client_id,
                "client_secret": self.lwa_client_secret,
            },
            timeout=self.timeout_seconds,
        )

    def request_json(
        self,
        method: str,
        path: str,
        query: dict[str, Any] | None = None,
        body: Any | None = None,
        access_token: str | None = None,
    ) -> Any:
        token = access_token or str(self.refresh_access_token().get("access_token") or "")
        url = build_url(self.endpoint, path, query)
        payload = b""
        headers = {
            "accept": "application/json",
            "user-agent": self.user_agent,
            "x-amz-access-token": token,
        }
        if body is not None:
            payload = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            headers["content-type"] = "application/json"
        signed_headers = self.signer.sign(method, url, headers, payload)
        return http_json(method, url, signed_headers, payload if body is not None else None, self.timeout_seconds)

    def get_marketplace_participations(self, access_token: str | None = None) -> Any:
        return self.request_json("GET", "/sellers/v1/marketplaceParticipations", access_token=access_token)

    def get_catalog_item(self, asin: str, marketplace_ids: list[str], access_token: str | None = None) -> Any:
        if not marketplace_ids:
            raise ApiConfigError("marketplace_ids is required for catalog item lookup")
        return self.request_json(
            "GET",
            f"/catalog/2022-04-01/items/{asin}",
            {"marketplaceIds": marketplace_ids},
            access_token=access_token,
        )
