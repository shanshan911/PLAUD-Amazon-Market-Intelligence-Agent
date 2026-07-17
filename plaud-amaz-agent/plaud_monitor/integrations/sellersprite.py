from __future__ import annotations

from typing import Any

from .base import build_url, http_json, require_env


class SellerSpriteClient:
    """SellerSprite external API client using the official secret-key header."""

    def __init__(
        self,
        secret_key: str,
        base_url: str = "https://api.sellersprite.com",
        timeout_seconds: int = 30,
    ) -> None:
        self.secret_key = secret_key
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = int(timeout_seconds or 30)

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "SellerSpriteClient":
        cfg = config.get("api_integrations", {}).get("sellersprite", {})
        return cls(
            secret_key=require_env(cfg, "secret_key_env"),
            base_url=str(cfg.get("base_url") or "https://api.sellersprite.com"),
            timeout_seconds=int(cfg.get("timeout_seconds") or 30),
        )

    def headers(self) -> dict[str, str]:
        return {
            "secret-key": self.secret_key,
            "Content-Type": "application/json;charset=UTF-8",
        }

    def request_json(
        self,
        method: str,
        path: str,
        query: dict[str, Any] | None = None,
        body: Any | None = None,
    ) -> Any:
        url = build_url(self.base_url, path, query)
        return http_json(method, url, self.headers(), body, self.timeout_seconds)

    def visits(self) -> Any:
        return self.request_json("GET", "/v1/visits")

    def product_node(
        self,
        marketplace: str,
        node_id_path: str | None = None,
        keyword: str | None = None,
        month: str | None = None,
    ) -> Any:
        query = {
            "marketplace": marketplace.upper(),
            "nodeIdPath": node_id_path,
            "keyword": keyword,
            "month": month,
        }
        return self.request_json(
            "GET",
            "/v1/product/node",
            query,
        )

    def market_statistics(
        self,
        marketplace: str,
        node_id_path: str,
        month: str | None = None,
        top_n: int | None = None,
        new_product: int | None = None,
        return_fields: list[str] | None = None,
    ) -> Any:
        return self._market_post(
            "/v1/market/statistics",
            marketplace,
            node_id_path,
            month,
            top_n,
            new_product,
            return_fields,
        )

    def market_goods(
        self,
        marketplace: str,
        node_id_path: str,
        month: str | None = None,
        top_n: int | None = None,
        new_product: int | None = None,
        asins: list[str] | None = None,
        return_fields: list[str] | None = None,
    ) -> Any:
        body_extra = {"asins": asins} if asins else None
        return self._market_post(
            "/v1/market/goods",
            marketplace,
            node_id_path,
            month,
            top_n,
            new_product,
            return_fields,
            body_extra,
        )

    def market_brand(
        self,
        marketplace: str,
        node_id_path: str,
        month: str | None = None,
        top_n: int | None = None,
        new_product: int | None = None,
        return_fields: list[str] | None = None,
    ) -> Any:
        return self._market_post(
            "/v1/market/brand",
            marketplace,
            node_id_path,
            month,
            top_n,
            new_product,
            return_fields,
        )

    def market_price_distribution(
        self,
        marketplace: str,
        node_id_path: str,
        month: str | None = None,
        top_n: int | None = None,
        new_product: int | None = None,
        return_fields: list[str] | None = None,
    ) -> Any:
        return self._market_post(
            "/v1/market/price",
            marketplace,
            node_id_path,
            month,
            top_n,
            new_product,
            return_fields,
        )

    def _market_post(
        self,
        path: str,
        marketplace: str,
        node_id_path: str,
        month: str | None = None,
        top_n: int | None = None,
        new_product: int | None = None,
        return_fields: list[str] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> Any:
        body: dict[str, Any] = {
            "marketplace": marketplace.upper(),
            "nodeIdPath": node_id_path,
        }
        if month:
            body["month"] = month
        if top_n is not None:
            body["topN"] = top_n
        if new_product is not None:
            body["newProduct"] = new_product
        if return_fields:
            body["returnFields"] = return_fields
        if extra:
            body.update(extra)
        return self.request_json("POST", path, body=body)

    def bsr_sales_estimate(self, marketplace: str, bsr: int, category_id: str) -> Any:
        return self.request_json(
            "GET",
            "/v1/sales/prediction/bsr",
            {"marketplace": marketplace.upper(), "bsr": bsr, "categoryId": category_id},
        )

    def asin_sales_estimate(self, marketplace: str, asin: str) -> Any:
        return self.request_json(
            "GET",
            "/v1/sales/prediction/asin",
            {"marketplace": marketplace.upper(), "asin": asin},
        )

    def asin_detail(self, marketplace: str, asin: str) -> Any:
        return self.request_json("GET", f"/v1/asin/{marketplace.upper()}/{asin}")
