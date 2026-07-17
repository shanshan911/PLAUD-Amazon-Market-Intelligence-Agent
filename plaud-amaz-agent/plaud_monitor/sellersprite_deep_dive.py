from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from .config import load_config
from .integrations.base import ApiRequestError
from .integrations.sellersprite_mcp import SellerSpriteMcpClient, parse_tool_content
from .normalizers import normalize_text, parse_number, parse_percent
from .platform import DEFAULT_DB_PATH, connect, init_db, read_table_for_run, utcnow_iso


@dataclass(frozen=True)
class DeepDiveResult:
    run_id: int
    marketplace: str
    asin_count: int
    keyword_rows: int
    status: str
    error: str = ""


KEYWORD_KEYS = [
    "keyword",
    "keywords",
    "searchTerm",
    "searchTerms",
    "trafficKeyword",
    "word",
    "query",
    "term",
]
KEYWORD_TYPE_KEYS = ["badge", "badges", "trafficKeywordType", "trafficKeywordTypes", "type", "relation"]
CONVERSION_TYPE_KEYS = ["conversionType", "conversionKeywordType", "conversionKeywordTypes", "conversion", "tag"]


def import_asin_keyword_intel_for_runs(
    config_path: str | Path,
    run_ids: list[int],
    db_path: str | Path = DEFAULT_DB_PATH,
    top_n: int = 20,
    month: str | None = None,
    keyword_limit: int = 20,
    raw_dir: str | Path = "outputs/sellersprite_mcp_asin",
    force_refresh: bool = False,
    throttle_seconds: float = 1.55,
) -> list[DeepDiveResult]:
    if not run_ids:
        return []
    config = load_config(config_path)
    init_db(db_path)
    client = SellerSpriteMcpClient.from_config(config)
    client.initialize()

    results: list[DeepDiveResult] = []
    for run_id in run_ids:
        try:
            result = import_asin_keyword_intel_for_run(
                client=client,
                run_id=run_id,
                db_path=db_path,
                top_n=top_n,
                month=month,
                keyword_limit=keyword_limit,
                raw_dir=raw_dir,
                force_refresh=force_refresh,
                throttle_seconds=throttle_seconds,
            )
        except Exception as exc:  # noqa: BLE001 - keep weekly delivery moving across sites.
            result = DeepDiveResult(
                run_id=run_id,
                marketplace="",
                asin_count=0,
                keyword_rows=0,
                status="error",
                error=str(exc),
            )
        results.append(result)
    return results


def import_asin_keyword_intel_for_run(
    client: SellerSpriteMcpClient,
    run_id: int,
    db_path: str | Path = DEFAULT_DB_PATH,
    top_n: int = 20,
    month: str | None = None,
    keyword_limit: int = 20,
    raw_dir: str | Path = "outputs/sellersprite_mcp_asin",
    force_refresh: bool = False,
    throttle_seconds: float = 1.55,
) -> DeepDiveResult:
    run = run_row(db_path, run_id)
    if not run:
        return DeepDiveResult(run_id, "", 0, 0, "error", f"Run {run_id} not found")
    marketplace = str(run.get("marketplace") or "").upper()
    week_id = str(run.get("week_id") or "")

    if not force_refresh and existing_success_rows(db_path, run_id) > 0:
        return DeepDiveResult(run_id, marketplace, 0, existing_success_rows(db_path, run_id), "reused")

    if force_refresh:
        clear_run_intel(db_path, run_id)

    competitors = top_competitor_asins(db_path, run_id, top_n)
    if competitors.empty:
        insert_status_row(
            db_path,
            run,
            source_type="traffic_keyword",
            source_status="error",
            source_error="No competitor ASIN found for deep dive",
        )
        return DeepDiveResult(run_id, marketplace, 0, 0, "error", "No competitor ASIN found")

    rows: list[dict[str, Any]] = []
    for _, item in competitors.iterrows():
        asin = normalize_asin(item.get("asin"))
        if not asin:
            continue
        request = {
            "marketplace": marketplace,
            "asin": asin,
            "size": max(1, int(keyword_limit)),
            "page": 1,
            "includeTop10AsinData": False,
            "order": {"field": "searches", "desc": True},
        }
        if month:
            request["month"] = month
        try:
            payload = mcp_tool_request(client, "traffic_keyword", request)
            write_raw_payload(raw_dir, week_id, marketplace, asin, "traffic_keyword", payload)
            rows.extend(normalize_keyword_payload(payload, run, item.to_dict(), "traffic_keyword"))
        except Exception as exc:  # noqa: BLE001 - store per-ASIN failure and continue.
            rows.append(status_row(run, item.to_dict(), "traffic_keyword", "error", str(exc)))
        time.sleep(max(0.0, throttle_seconds))

    batch_asins = [normalize_asin(value) for value in competitors["asin"].tolist()]
    batch_asins = [value for value in batch_asins if value]
    if batch_asins:
        order_request = {
            "marketplace": marketplace,
            "asins": batch_asins,
            "reverseType": "W",
            "date": week_end_saturday(week_id),
            "size": max(20, min(200, int(keyword_limit) * len(batch_asins))),
            "page": 1,
            "variation": "N",
            "order": {"field": "searchRank", "desc": True},
        }
        try:
            payload = mcp_tool_request(client, "keyword_order", order_request)
            write_raw_payload(raw_dir, week_id, marketplace, "batch_top_asins", "keyword_order", payload)
            rows.extend(normalize_keyword_payload(payload, run, {}, "keyword_order"))
        except Exception as exc:  # noqa: BLE001 - keyword_order is additive, not blocking.
            rows.append(status_row(run, {}, "keyword_order", "error", str(exc)))

    rows.extend(related_term_rows(run, rows, limit=max(12, keyword_limit)))
    inserted = replace_run_intel(db_path, run_id, rows)
    status = "ok" if inserted else "empty"
    return DeepDiveResult(run_id, marketplace, len(batch_asins), inserted, status)


def mcp_tool_request(client: SellerSpriteMcpClient, tool_name: str, request: dict[str, Any]) -> Any:
    result = client.tools_call(tool_name, {"request": request})
    return parse_tool_content(result)


def run_row(db_path: str | Path, run_id: int) -> dict[str, Any] | None:
    init_db(db_path)
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM uploaded_reports WHERE id = ?", (run_id,)).fetchone()
    return dict(row) if row else None


def top_competitor_asins(db_path: str | Path, run_id: int, top_n: int) -> pd.DataFrame:
    product = read_table_for_run(db_path, "product_metrics", run_id)
    if product.empty or "asin" not in product:
        return pd.DataFrame()
    view = product.copy()
    view["_asin_key"] = view["asin"].map(normalize_asin)
    view = view[view["_asin_key"] != ""].copy()
    if "standard_brand" in view:
        view = view[view["standard_brand"].fillna("").str.upper() != "PLAUD"].copy()
    for col in ["monthly_revenue", "monthly_units", "bsr_rank"]:
        if col not in view:
            view[col] = 0
        view[col] = view[col].map(float_value)
    if view.empty:
        return view
    view = view.sort_values(["monthly_revenue", "monthly_units", "bsr_rank"], ascending=[False, False, True])
    return view.drop_duplicates("_asin_key").head(max(1, int(top_n))).copy()


def normalize_keyword_payload(payload: Any, run: dict[str, Any], product_row: dict[str, Any], source_type: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    records = extract_records(payload)
    if not records:
        rows.append(status_row(run, product_row, source_type, "empty", "MCP returned no keyword records", payload))
        return rows
    for record in records:
        if not isinstance(record, dict):
            continue
        keyword = first_text(record, KEYWORD_KEYS)
        asin = normalize_asin(first_text(record, ["asin", "parentAsin", "sourceAsin"])) or normalize_asin(product_row.get("asin"))
        if not keyword:
            continue
        rows.append(
            {
                "run_id": int(run["id"]),
                "week_id": run.get("week_id", ""),
                "marketplace": str(run.get("marketplace") or "").upper(),
                "asin": asin,
                "brand": first_text(record, ["brand", "brandName", "standardBrand"]) or product_row.get("standard_brand") or product_row.get("brand_name") or "",
                "product_title": first_text(record, ["title", "productTitle", "product_name"]) or product_row.get("product_title") or "",
                "source_type": source_type,
                "keyword": keyword,
                "related_keyword": first_text(record, ["relatedKeyword", "related_keyword", "recommendedKeyword"]),
                "keyword_type": compact_value(first_value(record, KEYWORD_TYPE_KEYS)),
                "conversion_type": compact_value(first_value(record, CONVERSION_TYPE_KEYS)),
                "searches": numeric_value(first_value(record, ["searches", "searchVolume", "searchRank", "searchesRank"])),
                "purchases": numeric_value(first_value(record, ["purchases", "purchase", "keywordsIsHide"])),
                "purchase_rate": percent_value(first_value(record, ["purchaseRate", "conversionRate", "cvr"])),
                "traffic_percentage": percent_value(first_value(record, ["trafficPercentage", "trafficPercent", "trafficRate"])),
                "rank_position": numeric_value(first_value(record, ["rankPosition", "naturalRank", "organicRank"])),
                "ad_position": numeric_value(first_value(record, ["adPosition", "sponsoredRank", "adsRank"])),
                "bid": numeric_value(first_value(record, ["bid", "ppcBid", "suggestedBid"])),
                "products": numeric_value(first_value(record, ["products", "productCount", "goods"])),
                "supply_demand_ratio": numeric_value(first_value(record, ["supplyDemandRatio", "sdr"])),
                "source_status": "ok",
                "source_error": "",
                "raw_json": raw_json(record),
                "fetched_at": utcnow_iso(),
            }
        )
    if not rows:
        rows.append(status_row(run, product_row, source_type, "empty", "MCP returned no concrete keyword records", payload))
    return rows


def related_term_rows(run: dict[str, Any], keyword_rows: list[dict[str, Any]], limit: int = 20) -> list[dict[str, Any]]:
    stopwords = {
        "with", "for", "and", "the", "this", "that", "from", "into", "your", "you", "our", "per", "con", "para", "pour",
        "von", "und", "der", "die", "das", "les", "des", "del", "una", "uno", "plus", "voice", "recorder", "recording",
        "audio", "device", "digital", "amazon", "usb",
    }
    weights: dict[str, dict[str, float]] = {}
    for row in keyword_rows:
        if row.get("source_status") != "ok":
            continue
        keyword = str(row.get("keyword") or "")
        score = max(float_value(row.get("searches")), float_value(row.get("purchases")), 1.0)
        for token in re.findall(r"[a-z0-9][a-z0-9+.-]{2,}", keyword.lower()):
            token = token.strip(".,-+")
            if not token or token in stopwords or token.isdigit():
                continue
            item = weights.setdefault(token, {"count": 0.0, "score": 0.0})
            item["count"] += 1
            item["score"] += score
    ranked = sorted(weights.items(), key=lambda item: (item[1]["score"], item[1]["count"]), reverse=True)[:limit]
    rows: list[dict[str, Any]] = []
    for term, stats in ranked:
        rows.append(
            {
                "run_id": int(run["id"]),
                "week_id": run.get("week_id", ""),
                "marketplace": str(run.get("marketplace") or "").upper(),
                "asin": "",
                "brand": "",
                "product_title": "",
                "source_type": "related_term",
                "keyword": term,
                "related_keyword": term,
                "keyword_type": "derived",
                "conversion_type": "",
                "searches": float(stats["score"]),
                "purchases": float(stats["count"]),
                "purchase_rate": None,
                "traffic_percentage": None,
                "rank_position": None,
                "ad_position": None,
                "bid": None,
                "products": None,
                "supply_demand_ratio": None,
                "source_status": "derived_from_mcp",
                "source_error": "",
                "raw_json": raw_json({"term": term, **stats}),
                "fetched_at": utcnow_iso(),
            }
        )
    return rows


def extract_records(payload: Any) -> list[Any]:
    data = unwrap_data(payload)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("records", "list", "items", "rows", "data", "keywords", "result"):
            value = data.get(key)
            if isinstance(value, list):
                return value
        return [data]
    return []


def unwrap_data(payload: Any) -> Any:
    if isinstance(payload, dict):
        if "code" in payload and normalize_text(payload.get("code")).upper() not in {"", "OK", "0"}:
            raise ApiRequestError(f"SellerSprite MCP response failed: {payload.get('code')} {payload.get('message')}")
        if "data" in payload:
            return payload.get("data")
    return payload


def replace_run_intel(db_path: str | Path, run_id: int, rows: list[dict[str, Any]]) -> int:
    init_db(db_path)
    columns = [
        "run_id",
        "week_id",
        "marketplace",
        "asin",
        "brand",
        "product_title",
        "source_type",
        "keyword",
        "related_keyword",
        "keyword_type",
        "conversion_type",
        "searches",
        "purchases",
        "purchase_rate",
        "traffic_percentage",
        "rank_position",
        "ad_position",
        "bid",
        "products",
        "supply_demand_ratio",
        "source_status",
        "source_error",
        "raw_json",
        "fetched_at",
    ]
    prepared = [{column: row.get(column) for column in columns} for row in rows]
    with connect(db_path) as conn:
        conn.execute("DELETE FROM mcp_asin_keyword_intel WHERE run_id = ?", (run_id,))
        if prepared:
            placeholders = ",".join(["?"] * len(columns))
            conn.executemany(
                f"INSERT INTO mcp_asin_keyword_intel ({','.join(columns)}) VALUES ({placeholders})",
                [[row.get(column) for column in columns] for row in prepared],
            )
        conn.commit()
    return len(prepared)


def clear_run_intel(db_path: str | Path, run_id: int) -> None:
    init_db(db_path)
    with connect(db_path) as conn:
        conn.execute("DELETE FROM mcp_asin_keyword_intel WHERE run_id = ?", (run_id,))
        conn.commit()


def existing_success_rows(db_path: str | Path, run_id: int) -> int:
    init_db(db_path)
    with connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS c
            FROM mcp_asin_keyword_intel
            WHERE run_id = ? AND source_status IN ('ok', 'derived_from_mcp')
            """,
            (run_id,),
        ).fetchone()
    return int(row["c"] if row else 0)


def insert_status_row(
    db_path: str | Path,
    run: dict[str, Any],
    source_type: str,
    source_status: str,
    source_error: str,
) -> None:
    replace_run_intel(db_path, int(run["id"]), [status_row(run, {}, source_type, source_status, source_error)])


def status_row(
    run: dict[str, Any],
    product_row: dict[str, Any],
    source_type: str,
    source_status: str,
    source_error: str,
    raw: Any | None = None,
) -> dict[str, Any]:
    return {
        "run_id": int(run["id"]),
        "week_id": run.get("week_id", ""),
        "marketplace": str(run.get("marketplace") or "").upper(),
        "asin": normalize_asin(product_row.get("asin")),
        "brand": product_row.get("standard_brand") or product_row.get("brand_name") or "",
        "product_title": product_row.get("product_title") or "",
        "source_type": source_type,
        "keyword": "",
        "related_keyword": "",
        "keyword_type": "",
        "conversion_type": "",
        "searches": None,
        "purchases": None,
        "purchase_rate": None,
        "traffic_percentage": None,
        "rank_position": None,
        "ad_position": None,
        "bid": None,
        "products": None,
        "supply_demand_ratio": None,
        "source_status": source_status,
        "source_error": source_error[:500],
        "raw_json": raw_json(raw or {}),
        "fetched_at": utcnow_iso(),
    }


def write_raw_payload(raw_dir: str | Path, week_id: str, marketplace: str, asin: str, tool_name: str, payload: Any) -> Path:
    safe_asin = re.sub(r"[^0-9A-Za-z_-]+", "_", asin).strip("_") or "batch"
    path = Path(raw_dir) / week_id / marketplace / f"{safe_asin}_{tool_name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return path


def week_end_saturday(week_id: str) -> str:
    match = re.match(r"^(\d{4})-W(\d{1,2})$", str(week_id or ""))
    if not match:
        return date.today().strftime("%Y%m%d")
    year = int(match.group(1))
    week = int(match.group(2))
    return date.fromisocalendar(year, week, 6).strftime("%Y%m%d")


def normalize_asin(value: Any) -> str:
    text = normalize_text(value).upper()
    match = re.search(r"\bB0[A-Z0-9]{8}\b", text)
    if match:
        return match.group(0)
    text = re.sub(r"[^A-Z0-9]", "", text)
    return text if len(text) == 10 else ""


def first_value(row: dict[str, Any], keys: list[str]) -> Any:
    lowered = {str(key).casefold(): value for key, value in row.items()}
    for key in keys:
        if key in row and row.get(key) not in (None, ""):
            return row.get(key)
        value = lowered.get(key.casefold())
        if value not in (None, ""):
            return value
    return None


def first_text(row: dict[str, Any], keys: list[str]) -> str:
    return normalize_text(first_value(row, keys))


def compact_value(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(normalize_text(item) for item in value if normalize_text(item))
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))[:300]
    return normalize_text(value)


def numeric_value(value: Any) -> float | None:
    return parse_number(value)


def percent_value(value: Any) -> float | None:
    return parse_percent(value)


def float_value(value: Any) -> float:
    parsed = parse_number(value)
    return float(parsed or 0.0)


def raw_json(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str)
    return text[:12000]
