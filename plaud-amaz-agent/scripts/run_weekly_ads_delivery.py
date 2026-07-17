from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app
from plaud_monitor.config import load_config
from plaud_monitor.integrations.amazon_ads import AmazonAdsClient, download_ads_report, profile_id_from_config
from plaud_monitor.integrations.base import ApiConfigError, ApiRequestError
from plaud_monitor.reporting import style_worksheet
from scripts.import_amazon_ads_api import (
    REPORT_PRESETS,
    build_report_request,
    decode_report_bytes,
    import_csv_to_db,
    normalize_record,
    records_from_payload,
    report_download_url,
    report_id_from_response,
    wait_for_report,
    write_csv,
)
from scripts.run_weekly_delivery import (
    feishu_tenant_token,
    feishu_upload_file,
    load_env_file,
    resolve_notify_mode,
    send_feishu_bot_file,
    send_feishu_bot_text,
    send_feishu_webhook,
)


DEFAULT_MARKETPLACES = ["US", "UK", "DE", "FR", "IT", "ES", "JP"]
DEFAULT_REPORT_TYPES = ["search_term", "campaign", "targeting", "asin"]


@dataclass
class AdsRunResult:
    marketplace: str
    report_type: str
    status: str
    report_id: str = ""
    rows_imported: int = 0
    records: int = 0
    csv_path: Path | None = None
    error: str = ""
    reused: bool = False


def previous_full_week(today: date | None = None) -> tuple[str, str, str]:
    today = today or date.today()
    this_week_monday = today - timedelta(days=today.weekday())
    start = this_week_monday - timedelta(days=7)
    end = this_week_monday - timedelta(days=1)
    iso = end.isocalendar()
    return f"{iso.year}-W{iso.week:02d}", start.isoformat(), end.isoformat()


def split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def selected_marketplaces(raw: str, config: dict[str, Any]) -> list[str]:
    if raw:
        values = split_csv(raw)
    else:
        values = config.get("monitoring", {}).get("marketplaces", DEFAULT_MARKETPLACES)
    return [str(value).strip().upper() for value in values if str(value).strip()]


def selected_report_types(raw: str) -> list[str]:
    values = split_csv(raw) if raw else DEFAULT_REPORT_TYPES
    result = [value for value in values if value in REPORT_PRESETS]
    return result or DEFAULT_REPORT_TYPES


def profile_id_for_marketplace(
    config: dict[str, Any],
    marketplace: str,
    override_map: dict[str, str],
    allow_placeholder: bool = False,
) -> str:
    if override_map.get(marketplace):
        return override_map[marketplace]
    env_specific = os.environ.get(f"AMAZON_ADS_PROFILE_ID_{marketplace}", "").strip()
    if env_specific:
        return env_specific
    if allow_placeholder:
        ads_cfg = config.get("api_integrations", {}).get("amazon_ads", {})
        profile_env = str(ads_cfg.get("profile_id_env") or "AMAZON_ADS_PROFILE_ID")
        return f"<{profile_env}_{marketplace} or {profile_env}>"
    return profile_id_from_config(config)


def parse_profile_map(raw: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in split_csv(raw):
        if ":" not in item:
            continue
        site, profile_id = item.split(":", 1)
        site = site.strip().upper()
        profile_id = profile_id.strip()
        if site and profile_id:
            result[site] = profile_id
    return result


def ads_upload_exists(db_path: str, week_id: str, marketplace: str, report_type: str) -> bool:
    app.init_ads_db()
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT id
            FROM ad_report_uploads
            WHERE week_id = ? AND marketplace = ? AND report_type = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (week_id, marketplace.upper(), report_type),
        ).fetchone()
    return bool(row)


def delete_ads_uploads(db_path: str, week_id: str, marketplace: str, report_type: str) -> None:
    app.init_ads_db()
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT id
            FROM ad_report_uploads
            WHERE week_id = ? AND marketplace = ? AND report_type = ?
            """,
            (week_id, marketplace.upper(), report_type),
        ).fetchall()
        upload_ids = [int(row[0]) for row in rows]
        for upload_id in upload_ids:
            conn.execute("DELETE FROM ad_metrics WHERE upload_id = ?", (upload_id,))
            conn.execute("DELETE FROM ad_report_uploads WHERE id = ?", (upload_id,))
        conn.commit()


def report_request_namespace(args: argparse.Namespace, marketplace: str, report_type: str) -> argparse.Namespace:
    return argparse.Namespace(
        marketplace=marketplace,
        report_type=report_type,
        report_type_id="",
        columns="",
        group_by="",
        start_date=args.start_date,
        end_date=args.end_date,
        ad_product=args.ad_product,
        time_unit=args.time_unit,
        format=args.format,
    )


def pull_one_report(
    args: argparse.Namespace,
    config: dict[str, Any],
    marketplace: str,
    report_type: str,
    profile_id: str,
) -> AdsRunResult:
    if ads_upload_exists(args.db_path, args.week_id, marketplace, report_type) and not args.force_refresh:
        return AdsRunResult(marketplace=marketplace, report_type=report_type, status="ok", reused=True)
    if args.force_refresh:
        delete_ads_uploads(args.db_path, args.week_id, marketplace, report_type)

    request_args = report_request_namespace(args, marketplace, report_type)
    request_body = build_report_request(request_args)
    if args.dry_run:
        output_dir = Path(args.output_dir) / args.week_id / marketplace
        output_dir.mkdir(parents=True, exist_ok=True)
        dry_path = output_dir / f"dry_run_{report_type}.json"
        dry_path.write_text(json.dumps({"profile_id": profile_id, "request": request_body}, ensure_ascii=False, indent=2), encoding="utf-8")
        return AdsRunResult(marketplace=marketplace, report_type=report_type, status="dry_run", csv_path=dry_path)

    client = AmazonAdsClient.from_config(config, marketplace)
    created = client.create_report(profile_id, request_body)
    report_id = report_id_from_response(created)
    report = wait_for_report(client, profile_id, report_id, args.poll_seconds, args.max_wait_seconds)
    url = report_download_url(report)
    if not url:
        raise ApiRequestError(f"Amazon Ads report completed without download URL: {report}")

    raw = download_ads_report(url)
    payload = decode_report_bytes(raw)
    records = [normalize_record(item) for item in records_from_payload(payload)]

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(args.output_dir) / args.week_id / marketplace
    raw_path = output_dir / f"{stamp}_{report_type}_{report_id}.raw"
    json_path = output_dir / f"{stamp}_{report_type}_{report_id}.json"
    csv_path = output_dir / f"{stamp}_{report_type}_{report_id}.csv"
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_path.write_bytes(raw)
    json_path.write_text(json.dumps({"request": request_body, "report": report, "records": records}, ensure_ascii=False, indent=2), encoding="utf-8")
    write_csv(csv_path, records)

    imported = import_csv_to_db(
        csv_path,
        args.week_id,
        marketplace,
        report_type,
        f"Amazon Ads API weekly sync; report_id={report_id}; {args.start_date}..{args.end_date}",
    )
    return AdsRunResult(
        marketplace=marketplace,
        report_type=report_type,
        status="ok",
        report_id=report_id,
        rows_imported=imported,
        records=len(records),
        csv_path=csv_path,
    )


def pull_ads_reports(args: argparse.Namespace, config: dict[str, Any], marketplaces: list[str], report_types: list[str]) -> list[AdsRunResult]:
    profile_map = parse_profile_map(args.profile_id_map)
    results: list[AdsRunResult] = []
    for marketplace in marketplaces:
        try:
            profile_id = profile_id_for_marketplace(config, marketplace, profile_map, allow_placeholder=args.dry_run)
        except ApiConfigError as exc:
            for report_type in report_types:
                results.append(AdsRunResult(marketplace, report_type, "error", error=str(exc)))
            continue
        for report_type in report_types:
            try:
                result = pull_one_report(args, config, marketplace, report_type, profile_id)
            except (ApiConfigError, ApiRequestError, RuntimeError, OSError, ValueError) as exc:
                result = AdsRunResult(marketplace, report_type, "error", error=str(exc)[:300])
            results.append(result)
    return results


def read_ads_summary(db_path: str, week_id: str) -> pd.DataFrame:
    app.init_ads_db()
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT
                week_id,
                marketplace,
                report_type,
                COUNT(*) AS row_count,
                SUM(impressions) AS impressions,
                SUM(clicks) AS clicks,
                SUM(spend) AS spend,
                SUM(sales) AS sales,
                SUM(orders) AS orders,
                SUM(units) AS units
            FROM ad_metrics
            WHERE week_id = ?
            GROUP BY week_id, marketplace, report_type
            ORDER BY marketplace, report_type
            """,
            (week_id,),
        ).fetchall()
    df = pd.DataFrame(rows, columns=["week_id", "marketplace", "report_type", "row_count", "impressions", "clicks", "spend", "sales", "orders", "units"])
    if df.empty:
        return df
    df["ctr"] = df.apply(lambda row: row["clicks"] / row["impressions"] if row["impressions"] else 0.0, axis=1)
    df["acos"] = df.apply(lambda row: row["spend"] / row["sales"] if row["sales"] else 0.0, axis=1)
    df["roas"] = df.apply(lambda row: row["sales"] / row["spend"] if row["spend"] else 0.0, axis=1)
    return df


def read_top_terms(db_path: str, week_id: str, limit: int = 40) -> pd.DataFrame:
    app.init_ads_db()
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT
                COALESCE(NULLIF(search_term, ''), NULLIF(targeting, ''), NULLIF(campaign, ''), '(未命名)') AS term,
                marketplace,
                report_type,
                campaign,
                SUM(impressions) AS impressions,
                SUM(clicks) AS clicks,
                SUM(spend) AS spend,
                SUM(sales) AS sales,
                SUM(orders) AS orders,
                SUM(units) AS units
            FROM ad_metrics
            WHERE week_id = ?
            GROUP BY term, marketplace, report_type, campaign
            ORDER BY spend DESC, sales DESC
            LIMIT ?
            """,
            (week_id, limit),
        ).fetchall()
    df = pd.DataFrame(rows, columns=["term", "marketplace", "report_type", "campaign", "impressions", "clicks", "spend", "sales", "orders", "units"])
    if df.empty:
        return df
    df["acos"] = df.apply(lambda row: row["spend"] / row["sales"] if row["sales"] else 0.0, axis=1)
    df["roas"] = df.apply(lambda row: row["sales"] / row["spend"] if row["spend"] else 0.0, axis=1)
    return df


def read_market_share(db_path: str, week_id: str) -> pd.DataFrame:
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            """
            WITH latest AS (
                SELECT week_id, marketplace, MAX(id) AS run_id
                FROM uploaded_reports
                WHERE status = 'ok' AND week_id = ?
                GROUP BY week_id, marketplace
            )
            SELECT
                l.week_id,
                l.marketplace,
                MAX(CASE WHEN b.brand = 'PLAUD' THEN b.monthly_units_share ELSE NULL END) AS plaud_units_share,
                MAX(CASE WHEN b.brand = 'PLAUD' THEN b.monthly_revenue_share ELSE NULL END) AS plaud_revenue_share
            FROM latest l
            LEFT JOIN brand_metrics b ON b.run_id = l.run_id
            GROUP BY l.week_id, l.marketplace
            """,
            (week_id,),
        ).fetchall()
    return pd.DataFrame(rows, columns=["week_id", "marketplace", "plaud_units_share", "plaud_revenue_share"])


def format_number(value: object) -> str:
    try:
        return f"{float(value or 0):,.0f}"
    except (TypeError, ValueError):
        return "0"


def format_percent(value: object) -> str:
    try:
        return f"{float(value or 0) * 100:.2f}%"
    except (TypeError, ValueError):
        return "0.00%"


def build_attribution_rows(summary: pd.DataFrame, top_terms: pd.DataFrame, market_share: pd.DataFrame) -> pd.DataFrame:
    if summary.empty:
        return pd.DataFrame()
    site_summary = summary.groupby("marketplace", as_index=False).agg(
        spend=("spend", "sum"),
        sales=("sales", "sum"),
        impressions=("impressions", "sum"),
        clicks=("clicks", "sum"),
        orders=("orders", "sum"),
        units=("units", "sum"),
    )
    site_summary["acos"] = site_summary.apply(lambda row: row["spend"] / row["sales"] if row["sales"] else 0.0, axis=1)
    site_summary["ctr"] = site_summary.apply(lambda row: row["clicks"] / row["impressions"] if row["impressions"] else 0.0, axis=1)
    if not market_share.empty:
        site_summary = site_summary.merge(market_share[["marketplace", "plaud_units_share", "plaud_revenue_share"]], on="marketplace", how="left")
    else:
        site_summary["plaud_units_share"] = 0.0
        site_summary["plaud_revenue_share"] = 0.0

    top_by_site: dict[str, dict[str, Any]] = {}
    if not top_terms.empty:
        for site, group in top_terms.groupby("marketplace"):
            top_by_site[str(site)] = group.sort_values(["spend", "sales"], ascending=False).head(1).iloc[0].to_dict()

    rows: list[dict[str, Any]] = []
    for _, row in site_summary.sort_values("spend", ascending=False).iterrows():
        site = str(row.get("marketplace"))
        top = top_by_site.get(site, {})
        acos = float(row.get("acos") or 0)
        ctr = float(row.get("ctr") or 0)
        spend = float(row.get("spend") or 0)
        sales = float(row.get("sales") or 0)
        if spend <= 0:
            action = "本周广告数据为空，确认报表授权或广告投放状态。"
        elif sales <= 0:
            action = "广告有花费但无销售，优先排查关键词、落地 ASIN、预算和转化链路。"
        elif acos >= 0.35:
            action = "ACOS 偏高，复盘高花费词与低转化 ASIN，收紧无效投放。"
        elif ctr < 0.003:
            action = "CTR 偏低，检查主图、标题与广告位相关性。"
        else:
            action = "广告效率可接受，结合市占变化判断是否加预算或扩词。"
        rows.append(
            {
                "站点": site,
                "广告花费": spend,
                "广告销售额": sales,
                "ACOS": acos,
                "CTR": ctr,
                "订单": row.get("orders", 0),
                "销量": row.get("units", 0),
                "PLAUD销量份额": row.get("plaud_units_share", 0),
                "Top投放词/对象": top.get("term", ""),
                "Top投放花费": top.get("spend", 0),
                "归因判断": action,
            }
        )
    return pd.DataFrame(rows)


def build_delivery_assets(args: argparse.Namespace, results: list[AdsRunResult]) -> tuple[Path, Path, str]:
    delivery_dir = Path(args.delivery_dir) / args.week_id
    delivery_dir.mkdir(parents=True, exist_ok=True)
    summary = read_ads_summary(args.db_path, args.week_id)
    top_terms = read_top_terms(args.db_path, args.week_id)
    market_share = read_market_share(args.db_path, args.week_id)
    attribution = build_attribution_rows(summary, top_terms, market_share)
    run_log = pd.DataFrame(
        [
            {
                "站点": item.marketplace,
                "报表类型": item.report_type,
                "状态": item.status,
                "Report ID": item.report_id,
                "记录数": item.records,
                "入库行数": item.rows_imported,
                "是否复用": "是" if item.reused else "否",
                "文件": str(item.csv_path or ""),
                "错误": item.error,
            }
            for item in results
        ]
    )

    workbook_path = delivery_dir / f"PLAUD_广告归因周报_{args.week_id}.xlsx"
    with pd.ExcelWriter(workbook_path, engine="openpyxl") as writer:
        attribution.to_excel(writer, sheet_name="广告归因摘要", index=False)
        summary.to_excel(writer, sheet_name="广告站点汇总", index=False)
        top_terms.to_excel(writer, sheet_name="Top投放词", index=False)
        market_share.to_excel(writer, sheet_name="市占关联", index=False)
        run_log.to_excel(writer, sheet_name="运行日志", index=False)
        for sheet in writer.book.worksheets:
            style_worksheet(sheet)

    message = build_feishu_message(args, results, attribution, top_terms)
    markdown_path = delivery_dir / f"PLAUD_广告归因周报_{args.week_id}_摘要.md"
    markdown_path.write_text(message, encoding="utf-8")
    return workbook_path, markdown_path, message


def build_feishu_message(args: argparse.Namespace, results: list[AdsRunResult], attribution: pd.DataFrame, top_terms: pd.DataFrame) -> str:
    ok = sum(1 for item in results if item.status in {"ok", "dry_run"})
    reused = sum(1 for item in results if item.reused)
    failed = [item for item in results if item.status == "error"]
    lines = [
        f"PLAUD 广告归因摘要｜{args.week_id}",
        "",
        f"数据区间：{args.start_date} 至 {args.end_date}",
        f"拉取结果：{ok}/{len(results)} 成功或已生成，复用 {reused} 项",
        f"广告页：{args.public_base_url.rstrip('/')}/ads?week_id={args.week_id}",
        "",
        "站点归因摘要：",
    ]
    if attribution.empty:
        lines.append("- 暂无广告数据入库；请检查 Amazon Ads API 授权、profileId 或报表是否为空。")
    else:
        for _, row in attribution.head(7).iterrows():
            lines.append(
                f"- {row.get('站点')}: Spend {format_number(row.get('广告花费'))}, "
                f"Sales {format_number(row.get('广告销售额'))}, ACOS {format_percent(row.get('ACOS'))}, "
                f"CTR {format_percent(row.get('CTR'))}; {row.get('归因判断')}"
            )
    if not top_terms.empty:
        lines.append("")
        lines.append("Top 投放词/对象：")
        for _, row in top_terms.head(6).iterrows():
            lines.append(
                f"- {row.get('marketplace')}｜{row.get('term')}: Spend {format_number(row.get('spend'))}, "
                f"Sales {format_number(row.get('sales'))}, ACOS {format_percent(row.get('acos'))}"
            )
    if failed:
        lines.append("")
        lines.append("失败项：")
        for item in failed[:10]:
            lines.append(f"- {item.marketplace} {item.report_type}: {item.error}")
    return "\n".join(lines)


def send_delivery(mode: str, message: str, workbook_path: Path, markdown_path: Path) -> None:
    if mode in {"webhook", "both"}:
        webhook = os.environ.get("FEISHU_WEBHOOK_URL", "").strip()
        if webhook:
            send_feishu_webhook(webhook, message)
            print("Feishu webhook message sent.")
        else:
            print("FEISHU_WEBHOOK_URL missing; webhook delivery skipped.")
    if mode in {"bot", "both"}:
        app_id = os.environ.get("FEISHU_APP_ID", "").strip()
        app_secret = os.environ.get("FEISHU_APP_SECRET", "").strip()
        receive_id = os.environ.get("FEISHU_RECEIVE_ID", "").strip()
        receive_id_type = os.environ.get("FEISHU_RECEIVE_ID_TYPE", "chat_id").strip()
        if not (app_id and app_secret and receive_id):
            print("FEISHU_APP_ID/FEISHU_APP_SECRET/FEISHU_RECEIVE_ID missing; bot delivery skipped.")
            return
        token = feishu_tenant_token(app_id, app_secret)
        send_feishu_bot_text(token, receive_id_type, receive_id, message)
        for path in [workbook_path, markdown_path]:
            file_key = feishu_upload_file(token, path)
            send_feishu_bot_file(token, receive_id_type, receive_id, file_key)
        print("Feishu bot message and files sent.")


def main() -> int:
    default_week, default_start, default_end = previous_full_week()
    parser = argparse.ArgumentParser(description="Weekly Amazon Ads API sync and Feishu attribution delivery")
    parser.add_argument("--config", default="config/monitor_config.p0.json")
    parser.add_argument("--env-file", default=".env.local")
    parser.add_argument("--db-path", default="data/db.sqlite")
    parser.add_argument("--marketplaces", default="")
    parser.add_argument("--report-types", default=",".join(DEFAULT_REPORT_TYPES))
    parser.add_argument("--profile-id-map", default="", help="Comma map, e.g. US:123,JP:456; fallback AMAZON_ADS_PROFILE_ID_{SITE} or AMAZON_ADS_PROFILE_ID")
    parser.add_argument("--week-id", default=default_week)
    parser.add_argument("--start-date", default=default_start)
    parser.add_argument("--end-date", default=default_end)
    parser.add_argument("--ad-product", default="SPONSORED_PRODUCTS")
    parser.add_argument("--time-unit", choices=["SUMMARY", "DAILY"], default="SUMMARY")
    parser.add_argument("--format", default="GZIP_JSON")
    parser.add_argument("--poll-seconds", type=int, default=10)
    parser.add_argument("--max-wait-seconds", type=int, default=600)
    parser.add_argument("--output-dir", default="outputs/amazon_ads_api")
    parser.add_argument("--delivery-dir", default="outputs/weekly_ads_delivery")
    parser.add_argument("--public-base-url", default=os.environ.get("PLAUD_PUBLIC_BASE_URL", "http://10.0.153.253:8501"))
    parser.add_argument("--notify", choices=["auto", "none", "webhook", "bot", "both"], default="auto")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force-refresh", action="store_true")
    args = parser.parse_args()

    app.DB_PATH = Path(args.db_path)
    root = Path(args.config).resolve().parents[1]
    load_env_file(root / args.env_file)
    config = load_config(args.config)
    marketplaces = selected_marketplaces(args.marketplaces, config)
    report_types = selected_report_types(args.report_types)

    results = pull_ads_reports(args, config, marketplaces, report_types)
    workbook_path, markdown_path, message = build_delivery_assets(args, results)
    print(f"Ads delivery ready: {workbook_path}")
    print(f"Summary: {markdown_path}")
    for item in results:
        suffix = "reused" if item.reused else item.status
        print(f"{item.marketplace} {item.report_type}: {suffix} rows={item.rows_imported} {item.error}".strip())

    notify_mode = resolve_notify_mode(args.notify)
    if notify_mode == "none":
        print("Feishu delivery skipped.")
        return 0 if not any(item.status == "error" for item in results) else 2
    send_delivery(notify_mode, message, workbook_path, markdown_path)
    return 0 if not any(item.status == "error" for item in results) else 2


if __name__ == "__main__":
    raise SystemExit(main())
