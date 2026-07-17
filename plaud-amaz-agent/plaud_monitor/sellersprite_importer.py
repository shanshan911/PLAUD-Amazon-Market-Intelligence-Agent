from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from .config import load_config
from .integrations.base import ApiRequestError
from .integrations.sellersprite import SellerSpriteClient
from .integrations.sellersprite_mcp import SellerSpriteMcpClient, parse_tool_content
from .metrics import compute_ai_competitors, compute_brand_share
from .normalizers import normalize_text, parse_int, parse_number, parse_percent
from .platform import (
    DEFAULT_DB_PATH,
    DEFAULT_REPORT_DIR,
    ProcessedRun,
    connect,
    create_upload_record,
    init_db,
    insert_dataframe,
    prepare_product_metrics,
    update_run_status,
)
from .reporting import write_excel_report, write_markdown_report


@dataclass(frozen=True)
class SellerSpriteMarketPayload:
    marketplace: str
    node_id_path: str
    statistics: dict[str, Any]
    goods: list[dict[str, Any]]
    brands: list[dict[str, Any]]
    raw_path: Path


def import_sellersprite_market(
    config_path: str | Path,
    marketplace: str,
    week_id: str | None = None,
    node_id_path: str | None = None,
    month: str | None = None,
    top_n: int = 100,
    new_product: int = 6,
    resolve_node: bool = True,
    db_path: str | Path = DEFAULT_DB_PATH,
    raw_dir: str | Path = "outputs/sellersprite",
    report_dir: str | Path = DEFAULT_REPORT_DIR,
    dry_run: bool = False,
) -> ProcessedRun:
    config = load_config(config_path)
    marketplace = marketplace.upper()
    week_id = week_id or str(config.get("monitoring", {}).get("week_id") or "")
    if not week_id:
        raise ValueError("week_id is required")

    client = SellerSpriteClient.from_config(config)
    resolved_node = resolve_market_node_id(client, config, marketplace, node_id_path, month, resolve_node)
    payload = fetch_market_payload(
        client=client,
        marketplace=marketplace,
        node_id_path=resolved_node,
        month=month,
        top_n=top_n,
        new_product=new_product,
        week_id=week_id,
        raw_dir=raw_dir,
    )
    brand_df = normalize_brand_payload(payload.brands)
    product_df = normalize_goods_payload(payload.goods, payload.marketplace, category_path_from_payload(config, payload))

    if dry_run:
        return ProcessedRun(
            run_id=0,
            week_id=week_id,
            marketplace=marketplace,
            upload_path=payload.raw_path,
            report_path=Path(),
            excel_report_path=Path(),
            status="dry_run",
        )

    init_db(db_path)
    with connect(db_path) as conn:
        run_id = create_upload_record(
            conn,
            week_id,
            marketplace,
            f"SellerSprite_API_{marketplace}_{safe_node_name(resolved_node)}.json",
            payload.raw_path,
            "SellerSprite API market import",
        )
        try:
            brand_share = compute_brand_share(brand_df, product_df, marketplace, config)
            ai_summary, ai_detail = compute_ai_competitors(product_df, marketplace, config)
            product_metrics = prepare_product_metrics(product_df, marketplace, config)

            insert_dataframe(conn, "brand_metrics", run_id, brand_share)
            insert_dataframe(conn, "ai_summary", run_id, ai_summary)
            insert_dataframe(conn, "ai_detail", run_id, ai_detail)
            insert_dataframe(conn, "product_metrics", run_id, product_metrics)

            report_path = Path(report_dir) / week_id / marketplace / f"report_run_{run_id}.md"
            excel_report_path = Path(report_dir) / week_id / marketplace / f"report_run_{run_id}.xlsx"
            warnings = import_warnings(payload, brand_df, product_df)
            run_log = [
                {
                    "marketplace": marketplace,
                    "status": "ok",
                    "source_file": str(payload.raw_path),
                    "warnings": "; ".join(warnings),
                    "error": "",
                }
            ]
            write_markdown_report(report_path, week_id, brand_share, ai_summary, ai_detail, run_log)
            write_excel_report(excel_report_path, week_id, brand_share, ai_summary, ai_detail, run_log)
            update_run_status(
                conn,
                run_id,
                "ok",
                "; ".join(warnings),
                "",
                str(report_path),
                str(excel_report_path),
            )
            return ProcessedRun(
                run_id=run_id,
                week_id=week_id,
                marketplace=marketplace,
                upload_path=payload.raw_path,
                report_path=report_path,
                excel_report_path=excel_report_path,
                status="ok",
            )
        except Exception as exc:  # noqa: BLE001 - surface import failures to the dashboard.
            update_run_status(conn, run_id, "error", "", str(exc), "", "")
            return ProcessedRun(run_id, week_id, marketplace, payload.raw_path, Path(), Path(), "error", str(exc))


def import_sellersprite_mcp_market(
    config_path: str | Path,
    marketplace: str,
    week_id: str | None = None,
    node_id_path: str | None = None,
    month: str | None = None,
    top_n: int = 100,
    new_product: int = 6,
    resolve_node: bool = True,
    db_path: str | Path = DEFAULT_DB_PATH,
    raw_dir: str | Path = "outputs/sellersprite_mcp",
    report_dir: str | Path = DEFAULT_REPORT_DIR,
    dry_run: bool = False,
) -> ProcessedRun:
    config = load_config(config_path)
    marketplace = marketplace.upper()
    week_id = week_id or str(config.get("monitoring", {}).get("week_id") or "")
    if not week_id:
        raise ValueError("week_id is required")

    client = SellerSpriteMcpClient.from_config(config)
    client.initialize()
    resolved_node, node_meta = resolve_mcp_market_node_id(client, config, marketplace, node_id_path, month, resolve_node)
    payload = fetch_mcp_market_payload(
        client=client,
        marketplace=marketplace,
        node_id_path=resolved_node,
        node_meta=node_meta,
        month=month,
        top_n=top_n,
        new_product=new_product,
        week_id=week_id,
        raw_dir=raw_dir,
    )
    brand_df = normalize_brand_payload(payload.brands)
    product_df = normalize_goods_payload(payload.goods, payload.marketplace, category_path_from_payload(config, payload))

    if dry_run:
        return ProcessedRun(
            run_id=0,
            week_id=week_id,
            marketplace=marketplace,
            upload_path=payload.raw_path,
            report_path=Path(),
            excel_report_path=Path(),
            status="dry_run",
        )

    init_db(db_path)
    with connect(db_path) as conn:
        run_id = create_upload_record(
            conn,
            week_id,
            marketplace,
            f"SellerSprite_MCP_{marketplace}_{safe_node_name(resolved_node)}.json",
            payload.raw_path,
            "SellerSprite MCP market import",
        )
        try:
            brand_share = compute_brand_share(brand_df, product_df, marketplace, config)
            ai_summary, ai_detail = compute_ai_competitors(product_df, marketplace, config)
            product_metrics = prepare_product_metrics(product_df, marketplace, config)

            insert_dataframe(conn, "brand_metrics", run_id, brand_share)
            insert_dataframe(conn, "ai_summary", run_id, ai_summary)
            insert_dataframe(conn, "ai_detail", run_id, ai_detail)
            insert_dataframe(conn, "product_metrics", run_id, product_metrics)

            report_path = Path(report_dir) / week_id / marketplace / f"report_run_{run_id}.md"
            excel_report_path = Path(report_dir) / week_id / marketplace / f"report_run_{run_id}.xlsx"
            warnings = import_warnings(payload, brand_df, product_df)
            run_log = [
                {
                    "marketplace": marketplace,
                    "status": "ok",
                    "source_file": str(payload.raw_path),
                    "warnings": "; ".join(warnings),
                    "error": "",
                }
            ]
            write_markdown_report(report_path, week_id, brand_share, ai_summary, ai_detail, run_log)
            write_excel_report(excel_report_path, week_id, brand_share, ai_summary, ai_detail, run_log)
            update_run_status(
                conn,
                run_id,
                "ok",
                "; ".join(warnings),
                "",
                str(report_path),
                str(excel_report_path),
            )
            return ProcessedRun(
                run_id=run_id,
                week_id=week_id,
                marketplace=marketplace,
                upload_path=payload.raw_path,
                report_path=report_path,
                excel_report_path=excel_report_path,
                status="ok",
            )
        except Exception as exc:  # noqa: BLE001 - surface import failures to the dashboard.
            update_run_status(conn, run_id, "error", "", str(exc), "", "")
            return ProcessedRun(run_id, week_id, marketplace, payload.raw_path, Path(), Path(), "error", str(exc))


def fetch_mcp_market_payload(
    client: SellerSpriteMcpClient,
    marketplace: str,
    node_id_path: str,
    node_meta: dict[str, Any],
    month: str | None,
    top_n: int,
    new_product: int,
    week_id: str,
    raw_dir: str | Path,
) -> SellerSpriteMarketPayload:
    request: dict[str, Any] = {
        "marketplace": marketplace,
        "nodeIdPath": node_id_path,
        "topN": top_n,
        "newProduct": new_product,
    }
    if month:
        request["month"] = month
    product_raw = mcp_call_data(client, "market_product_concentration", request)
    brand_raw = mcp_call_data(client, "market_brand_concentration", request)
    goods = unwrap_sellersprite_data(product_raw, "mcp_market_product_concentration")
    brands = unwrap_sellersprite_data(brand_raw, "mcp_market_brand_concentration")
    if not isinstance(goods, list):
        raise ApiRequestError("SellerSprite MCP product concentration response data is not a list")
    if not isinstance(brands, list):
        raise ApiRequestError("SellerSprite MCP brand concentration response data is not a list")

    statistics = {
        "nodeIdPath": node_id_path,
        "nodeLabelPath": node_meta.get("nodeLabelPath") or node_id_path,
        "nodeLabelPathLocale": node_meta.get("nodeLabelPathLocale") or "",
        "products": node_meta.get("products"),
        "source": "SellerSprite MCP",
    }
    raw_path = write_raw_payload(
        raw_dir,
        week_id,
        marketplace,
        node_id_path,
        {
            "request": request,
            "node": node_meta,
            "goods": product_raw,
            "brand": brand_raw,
        },
    )
    return SellerSpriteMarketPayload(marketplace, node_id_path, statistics, goods, brands, raw_path)


def resolve_mcp_market_node_id(
    client: SellerSpriteMcpClient,
    config: dict[str, Any],
    marketplace: str,
    explicit_node_id_path: str | None,
    month: str | None,
    resolve_node: bool,
) -> tuple[str, dict[str, Any]]:
    marketplace_cfg = config.get("marketplaces", {}).get(marketplace, {})
    configured = normalize_text(explicit_node_id_path or marketplace_cfg.get("sellersprite_node_id_path"))
    if configured:
        return configured, {"nodeIdPath": configured}

    category_url = normalize_text(marketplace_cfg.get("category_url"))
    fallback_node = extract_amazon_node_id(category_url)
    if not fallback_node:
        raise ValueError(f"{marketplace} missing nodeIdPath and no Amazon category id could be extracted")
    if not resolve_node:
        return fallback_node, {"nodeIdPath": fallback_node}

    for request in ({"marketplace": marketplace, "keyword": fallback_node}, {"marketplace": marketplace, "nodeIdPath": fallback_node}):
        if month:
            request["month"] = month
        try:
            raw = mcp_call_data(client, "product_node", request)
            data = unwrap_sellersprite_data(raw, "mcp_product_node")
        except ApiRequestError:
            continue
        if isinstance(data, list) and data:
            row = choose_mcp_node(data, fallback_node)
            node_id_path = normalize_text(row.get("nodeIdPath"))
            if node_id_path:
                return node_id_path, row
    return fallback_node, {"nodeIdPath": fallback_node}


def choose_mcp_node(rows: list[dict[str, Any]], fallback_node: str) -> dict[str, Any]:
    for row in rows:
        node_id_path = normalize_text(row.get("nodeIdPath"))
        if node_id_path and node_id_path.split(":")[-1] == fallback_node:
            return row
    for row in rows:
        if normalize_text(row.get("nodeIdPath")):
            return row
    return rows[0]


def mcp_call_data(client: SellerSpriteMcpClient, tool_name: str, request: dict[str, Any]) -> Any:
    result = client.tools_call(tool_name, {"request": request})
    return parse_tool_content(result)


def fetch_market_payload(
    client: SellerSpriteClient,
    marketplace: str,
    node_id_path: str,
    month: str | None,
    top_n: int,
    new_product: int,
    week_id: str,
    raw_dir: str | Path,
) -> SellerSpriteMarketPayload:
    statistics_raw = client.market_statistics(
        marketplace=marketplace,
        node_id_path=node_id_path,
        month=month,
        top_n=top_n,
        new_product=new_product,
    )
    goods_raw = client.market_goods(
        marketplace=marketplace,
        node_id_path=node_id_path,
        month=month,
        top_n=top_n,
        new_product=new_product,
    )
    brand_raw = client.market_brand(
        marketplace=marketplace,
        node_id_path=node_id_path,
        month=month,
        top_n=top_n,
        new_product=new_product,
    )

    statistics = unwrap_sellersprite_data(statistics_raw, "market_statistics")
    goods = unwrap_sellersprite_data(goods_raw, "market_goods")
    brands = unwrap_sellersprite_data(brand_raw, "market_brand")
    if not isinstance(statistics, dict):
        raise ApiRequestError("SellerSprite statistics response data is not an object")
    if not isinstance(goods, list):
        raise ApiRequestError("SellerSprite goods response data is not a list")
    if not isinstance(brands, list):
        raise ApiRequestError("SellerSprite brand response data is not a list")

    raw_path = write_raw_payload(
        raw_dir,
        week_id,
        marketplace,
        node_id_path,
        {
            "request": {
                "marketplace": marketplace,
                "nodeIdPath": node_id_path,
                "month": month,
                "topN": top_n,
                "newProduct": new_product,
            },
            "statistics": statistics_raw,
            "goods": goods_raw,
            "brand": brand_raw,
        },
    )
    return SellerSpriteMarketPayload(marketplace, node_id_path, statistics, goods, brands, raw_path)


def unwrap_sellersprite_data(payload: Any, label: str) -> Any:
    if not isinstance(payload, dict):
        raise ApiRequestError(f"SellerSprite {label} returned non-object response")
    code = normalize_text(payload.get("code"))
    message = normalize_text(payload.get("message"))
    if code and code.upper() != "OK":
        raise ApiRequestError(f"SellerSprite {label} failed: code={code}, message={message}")
    if "data" not in payload:
        raise ApiRequestError(f"SellerSprite {label} response missing data: code={code}, message={message}")
    return payload.get("data")


def resolve_market_node_id(
    client: SellerSpriteClient,
    config: dict[str, Any],
    marketplace: str,
    explicit_node_id_path: str | None,
    month: str | None,
    resolve_node: bool,
) -> str:
    marketplace_cfg = config.get("marketplaces", {}).get(marketplace, {})
    configured = normalize_text(explicit_node_id_path or marketplace_cfg.get("sellersprite_node_id_path"))
    if configured:
        return configured

    category_url = normalize_text(marketplace_cfg.get("category_url"))
    fallback_node = extract_amazon_node_id(category_url)
    if not fallback_node:
        raise ValueError(f"{marketplace} missing nodeIdPath and no Amazon category id could be extracted")
    if not resolve_node:
        return fallback_node

    for query in ({"node_id_path": fallback_node}, {"keyword": fallback_node}):
        try:
            raw = client.product_node(marketplace, month=month, **query)
            data = unwrap_sellersprite_data(raw, "product_node")
        except ApiRequestError:
            continue
        if isinstance(data, list) and data:
            exact = choose_node_id_path(data, fallback_node)
            if exact:
                return exact
    return fallback_node


def choose_node_id_path(rows: list[dict[str, Any]], fallback_node: str) -> str:
    for row in rows:
        node_id_path = normalize_text(row.get("nodeIdPath"))
        if node_id_path and node_id_path.split(":")[-1] == fallback_node:
            return node_id_path
    for row in rows:
        node_id_path = normalize_text(row.get("nodeIdPath"))
        if node_id_path:
            return node_id_path
    return fallback_node


def extract_amazon_node_id(url: str) -> str:
    matches = re.findall(r"/(\d{4,})(?:[/?#]|$)", url)
    return matches[-1] if matches else ""


def normalize_goods_payload(rows: list[dict[str, Any]], marketplace: str, category_path: str) -> pd.DataFrame:
    normalized: list[dict[str, Any]] = []
    for row in rows:
        normalized.append(
            {
                "asin": normalize_text(row.get("asin")),
                "brand_name": normalize_text(row.get("brand")),
                "product_title": normalize_text(row.get("title")),
                "monthly_units": parse_int(row.get("totalUnits")),
                "monthly_revenue": parse_number(row.get("totalRevenue")),
                "price": parse_number(row.get("price")),
                "bsr_rank": parse_int(row.get("ranking")),
                "category_path": category_path,
                "asin_url": normalize_text(row.get("asinUrl")),
                "image_url": normalize_text(row.get("imageUrl")),
                "seller_name": normalize_text(row.get("sellerName")),
                "seller_type": normalize_text(row.get("sellerType")),
                "ratings": parse_int(row.get("ratings")),
                "reviews": parse_int(row.get("reviews")),
                "rating": parse_number(row.get("rating")),
                "marketplace": marketplace,
            }
        )
    columns = [
        "asin",
        "brand_name",
        "product_title",
        "monthly_units",
        "monthly_revenue",
        "price",
        "bsr_rank",
        "category_path",
        "asin_url",
        "image_url",
        "seller_name",
        "seller_type",
        "ratings",
        "reviews",
        "rating",
        "marketplace",
    ]
    return pd.DataFrame(normalized, columns=columns)


def normalize_brand_payload(rows: list[dict[str, Any]]) -> pd.DataFrame:
    normalized: list[dict[str, Any]] = []
    for row in rows:
        normalized.append(
            {
                "brand_name": normalize_text(row.get("brand")),
                "ranking": parse_int(row.get("ranking")),
                "monthly_units": parse_int(row.get("totalUnits")),
                "monthly_revenue": parse_number(row.get("totalRevenue")),
                "monthly_units_share": parse_percent(row.get("totalUnitsRatio")),
                "monthly_revenue_share": parse_percent(row.get("totalRevenueRatio")),
                "products": parse_int(row.get("products")),
                "new_products": parse_int(row.get("newProducts")),
                "avg_price": parse_number(row.get("avgPrice")),
                "ratings": parse_int(row.get("ratings")),
                "reviews": parse_int(row.get("reviews")),
                "rating": parse_number(row.get("rating")),
            }
        )
    columns = [
        "brand_name",
        "ranking",
        "monthly_units",
        "monthly_revenue",
        "monthly_units_share",
        "monthly_revenue_share",
        "products",
        "new_products",
        "avg_price",
        "ratings",
        "reviews",
        "rating",
    ]
    return pd.DataFrame(normalized, columns=columns)


def category_path_from_payload(config: dict[str, Any], payload: SellerSpriteMarketPayload) -> str:
    if payload.statistics:
        return normalize_text(
            payload.statistics.get("nodeLabelPath")
            or payload.statistics.get("nodeLabelPathLocale")
            or payload.node_id_path
        )
    return normalize_text(config.get("marketplaces", {}).get(payload.marketplace, {}).get("category_path")) or payload.node_id_path


def import_warnings(
    payload: SellerSpriteMarketPayload,
    brand_df: pd.DataFrame,
    product_df: pd.DataFrame,
) -> list[str]:
    warnings: list[str] = [f"SellerSprite nodeIdPath={payload.node_id_path}"]
    if product_df.empty:
        warnings.append("商品集中度 API 未返回商品明细")
    if brand_df.empty:
        warnings.append("品牌集中度 API 未返回品牌明细")
    if product_df.get("monthly_units", pd.Series(dtype=float)).fillna(0).sum() == 0:
        warnings.append("商品集中度总销量为 0 或未返回")
    return warnings


def write_raw_payload(
    raw_dir: str | Path,
    week_id: str,
    marketplace: str,
    node_id_path: str,
    payload: dict[str, Any],
) -> Path:
    target = Path(raw_dir) / week_id / marketplace / f"market_{safe_node_name(node_id_path)}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return target


def safe_node_name(node_id_path: str) -> str:
    return re.sub(r"[^0-9A-Za-z_-]+", "_", node_id_path).strip("_") or "node"
