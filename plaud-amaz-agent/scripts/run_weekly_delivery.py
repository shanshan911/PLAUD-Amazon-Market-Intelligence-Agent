from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import mimetypes
import os
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib import request
from zoneinfo import ZoneInfo

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from plaud_monitor.config import load_config
from plaud_monitor.platform import (
    connect,
    ensure_excel_report_for_run,
    get_run,
    init_db,
    latest_runs,
    read_table_for_run,
)
from plaud_monitor.reporting import style_worksheet
from plaud_monitor.sellersprite_deep_dive import import_asin_keyword_intel_for_runs
from plaud_monitor.sellersprite_importer import import_sellersprite_mcp_market


DEFAULT_MARKETPLACES = ["US", "UK", "DE", "FR", "IT", "ES", "JP"]


@dataclass
class WeeklyRunResult:
    marketplace: str
    status: str
    run_id: int | None = None
    report_path: Path | None = None
    error: str = ""
    reused: bool = False


def main() -> int:
    parser = argparse.ArgumentParser(description="Run weekly SellerSprite pull and deliver Feishu report")
    parser.add_argument("--config", default="config/monitor_config.p0.json")
    parser.add_argument("--env-file", default=".env.local")
    parser.add_argument("--week-id", default="auto", help="Use auto for current ISO week, e.g. 2026-W27")
    parser.add_argument("--marketplaces", default="", help="Comma-separated sites; default reads config")
    parser.add_argument("--top-n", type=int, default=100)
    parser.add_argument("--new-product", type=int, default=6)
    parser.add_argument("--month", default="", help="Optional SellerSprite month filter, e.g. 202606")
    parser.add_argument("--db-path", default="data/db.sqlite")
    parser.add_argument("--raw-dir", default="outputs/sellersprite_mcp")
    parser.add_argument("--report-dir", default="outputs/reports")
    parser.add_argument("--delivery-dir", default="outputs/weekly_delivery")
    parser.add_argument("--public-base-url", default=os.environ.get("PLAUD_PUBLIC_BASE_URL", "http://10.0.153.253:8501"))
    parser.add_argument("--force-refresh", action="store_true", help="Pull again even if this week already has a run")
    parser.add_argument("--skip-fetch", action="store_true", help="Do not call MCP; compose delivery from existing DB data")
    parser.add_argument("--skip-asin-deep-dive", action="store_true", help="Skip Top competitor ASIN keyword deep dive")
    parser.add_argument("--deep-dive-top-asins", type=int, default=20)
    parser.add_argument("--deep-dive-keyword-limit", type=int, default=20)
    parser.add_argument("--notify", choices=["auto", "none", "webhook", "bot", "both"], default="auto")
    args = parser.parse_args()

    root = Path(args.config).resolve().parents[1]
    load_env_file(root / args.env_file)
    config = load_config(args.config)
    week_id = current_week_id() if args.week_id == "auto" else args.week_id
    marketplaces = selected_marketplaces(args.marketplaces, config)

    init_db(args.db_path)
    results = run_or_reuse_weekly_imports(args, config, week_id, marketplaces)
    ok_run_ids = [item.run_id for item in results if item.status == "ok" and item.run_id]
    if not ok_run_ids:
        print("No successful runs; skip report delivery.")
        for item in results:
            print(f"{item.marketplace}: {item.status} {item.error}".strip())
        return 2

    deep_dive_results = []
    if not args.skip_asin_deep_dive and not args.skip_fetch:
        deep_dive_results = import_asin_keyword_intel_for_runs(
            config_path=args.config,
            run_ids=[int(run_id) for run_id in ok_run_ids],
            db_path=args.db_path,
            top_n=args.deep_dive_top_asins,
            month=args.month or None,
            keyword_limit=args.deep_dive_keyword_limit,
            raw_dir="outputs/sellersprite_mcp_asin",
            force_refresh=args.force_refresh,
        )

    workbook_path, markdown_path, message = build_delivery_assets(
        db_path=args.db_path,
        week_id=week_id,
        run_ids=[int(run_id) for run_id in ok_run_ids],
        results=results,
        delivery_dir=Path(args.delivery_dir),
        public_base_url=args.public_base_url.rstrip("/"),
    )

    print(f"Weekly delivery ready: {workbook_path}")
    print(f"Summary: {markdown_path}")
    for item in results:
        suffix = "reused" if item.reused else "imported"
        print(f"{item.marketplace}: {item.status} run_id={item.run_id or '-'} {suffix if item.status == 'ok' else item.error}")
    for item in deep_dive_results:
        print(f"ASIN deep dive {item.marketplace or item.run_id}: {item.status} rows={item.keyword_rows} asins={item.asin_count}")

    notify_mode = resolve_notify_mode(args.notify)
    if notify_mode == "none":
        print("Feishu delivery skipped.")
        return 0

    send_feishu_delivery(notify_mode, message, workbook_path, markdown_path)
    return 0


def run_or_reuse_weekly_imports(
    args: argparse.Namespace,
    config: dict[str, Any],
    week_id: str,
    marketplaces: list[str],
) -> list[WeeklyRunResult]:
    results: list[WeeklyRunResult] = []
    for marketplace in marketplaces:
        if not args.force_refresh:
            existing = latest_run_for_site_week(args.db_path, week_id, marketplace)
            if existing:
                report_path = ensure_excel_report_for_run(args.db_path, int(existing["id"]), args.report_dir)
                results.append(
                    WeeklyRunResult(
                        marketplace=marketplace,
                        status="ok",
                        run_id=int(existing["id"]),
                        report_path=report_path,
                        reused=True,
                    )
                )
                continue

        if args.skip_fetch:
            results.append(WeeklyRunResult(marketplace=marketplace, status="error", error="missing existing run"))
            continue

        result = import_sellersprite_mcp_market(
            config_path=args.config,
            marketplace=marketplace,
            week_id=week_id,
            month=args.month or None,
            top_n=args.top_n,
            new_product=args.new_product,
            db_path=args.db_path,
            raw_dir=args.raw_dir,
            report_dir=args.report_dir,
        )
        results.append(
            WeeklyRunResult(
                marketplace=marketplace,
                status=result.status,
                run_id=result.run_id or None,
                report_path=result.excel_report_path if result.excel_report_path else None,
                error=result.error,
            )
        )
    return results


def build_delivery_assets(
    db_path: str,
    week_id: str,
    run_ids: list[int],
    results: list[WeeklyRunResult],
    delivery_dir: Path,
    public_base_url: str,
) -> tuple[Path, Path, str]:
    delivery_dir = delivery_dir / week_id
    delivery_dir.mkdir(parents=True, exist_ok=True)
    brand_frames: list[pd.DataFrame] = []
    ai_frames: list[pd.DataFrame] = []
    ai_detail_frames: list[pd.DataFrame] = []
    product_frames: list[pd.DataFrame] = []
    asin_keyword_frames: list[pd.DataFrame] = []
    summary_rows: list[dict[str, Any]] = []
    action_rows: list[dict[str, Any]] = []

    for run_id in run_ids:
        run = get_run(db_path, run_id)
        if not run:
            continue
        brand = read_table_for_run(db_path, "brand_metrics", run_id)
        ai_summary = read_table_for_run(db_path, "ai_summary", run_id)
        ai_detail = read_table_for_run(db_path, "ai_detail", run_id)
        product = read_table_for_run(db_path, "product_metrics", run_id)
        asin_keywords = read_table_for_run(db_path, "mcp_asin_keyword_intel", run_id)
        brand_frames.append(brand)
        ai_frames.append(ai_summary)
        ai_detail_frames.append(ai_detail)
        product_frames.append(product)
        asin_keyword_frames.append(asin_keywords)

        prev_run = previous_site_run(db_path, str(run.get("marketplace", "")), str(run.get("week_id", "")))
        prev_brand = read_table_for_run(db_path, "brand_metrics", int(prev_run["id"])) if prev_run else pd.DataFrame()
        prev_ai = read_table_for_run(db_path, "ai_summary", int(prev_run["id"])) if prev_run else pd.DataFrame()
        metrics = site_metrics(run, brand, ai_summary, prev_brand, prev_ai)
        report_path = ensure_excel_report_for_run(db_path, run_id)
        summary_rows.append(
            {
                "周次": run.get("week_id"),
                "站点": run.get("marketplace"),
                "Run": run_id,
                "PLAUD销量份额": metrics["plaud_units_share"],
                "PLAUD销量份额环比pp": metrics["plaud_units_delta_pp"],
                "竞品合计销量份额": metrics["competitor_units_share"],
                "AI竞品销量渗透": metrics["ai_units_share"],
                "AI竞品销量渗透环比pp": metrics["ai_units_delta_pp"],
                "类目月销量": metrics["category_units"],
                "AI竞品ASIN数": metrics["ai_asin_count"],
                "周报文件": str(report_path or ""),
                "分析链接": f"{public_base_url}/analysis?id={run_id}",
                "行动建议链接": f"{public_base_url}/actions?id={run_id}",
            }
        )
        action_rows.extend(build_action_rows(run, metrics, ai_detail, product))

    summary_df = pd.DataFrame(summary_rows)
    actions_df = pd.DataFrame(action_rows)
    run_log_df = pd.DataFrame(
        [
            {
                "站点": item.marketplace,
                "状态": item.status,
                "Run": item.run_id,
                "是否复用已有数据": "是" if item.reused else "否",
                "错误": item.error,
            }
            for item in results
        ]
    )
    brand_df = pd.concat(brand_frames, ignore_index=True) if brand_frames else pd.DataFrame()
    ai_df = pd.concat(ai_frames, ignore_index=True) if ai_frames else pd.DataFrame()
    ai_detail_df = pd.concat(ai_detail_frames, ignore_index=True) if ai_detail_frames else pd.DataFrame()
    product_df = pd.concat(product_frames, ignore_index=True) if product_frames else pd.DataFrame()
    asin_keyword_df = pd.concat(asin_keyword_frames, ignore_index=True) if asin_keyword_frames else pd.DataFrame()

    workbook_path = delivery_dir / f"PLAUD_亚马逊监控周报_{week_id}.xlsx"
    with pd.ExcelWriter(workbook_path, engine="openpyxl") as writer:
        summary_df.to_excel(writer, sheet_name="七站点汇总", index=False)
        actions_df.to_excel(writer, sheet_name="行动建议", index=False)
        brand_df.to_excel(writer, sheet_name="品牌市占", index=False)
        ai_df.to_excel(writer, sheet_name="AI竞品汇总", index=False)
        ai_detail_df.to_excel(writer, sheet_name="AI竞品明细", index=False)
        product_df.to_excel(writer, sheet_name="商品明细", index=False)
        asin_keyword_df.to_excel(writer, sheet_name="Top ASIN关键词深挖", index=False)
        run_log_df.to_excel(writer, sheet_name="运行日志", index=False)
        for sheet in writer.book.worksheets:
            style_worksheet(sheet)

    message = build_feishu_message(week_id, summary_df, actions_df, results, public_base_url)
    markdown_path = delivery_dir / f"PLAUD_亚马逊监控周报_{week_id}_摘要.md"
    markdown_path.write_text(message, encoding="utf-8")
    return workbook_path, markdown_path, message


def build_action_rows(
    run: dict[str, Any],
    metrics: dict[str, float],
    ai_detail: pd.DataFrame,
    product: pd.DataFrame,
) -> list[dict[str, Any]]:
    site = str(run.get("marketplace", ""))
    rows: list[dict[str, Any]] = []
    if metrics["plaud_units_delta_pp"] <= -3:
        rows.append(
            action_row(
                "P0",
                site,
                "排查 PLAUD 份额下滑来源",
                f"PLAUD 销量份额环比 {metrics['plaud_units_delta_pp']:.2f}pp。",
                "站点运营",
                "PLAUD 销量份额 / Top ASIN 排名 / 价格与优惠",
            )
        )
    if metrics["ai_units_delta_pp"] >= 2:
        rows.append(
            action_row(
                "P1",
                site,
                "复盘 AI 竞品渗透上升",
                f"AI 竞品销量渗透环比 +{metrics['ai_units_delta_pp']:.2f}pp。",
                "市场分析",
                "AI ASIN 销量 / 标题命中词 / 新增 ASIN",
            )
        )
    if not ai_detail.empty and "monthly_revenue" in ai_detail:
        top_ai = ai_detail.sort_values("monthly_revenue", ascending=False).head(1).iloc[0]
        rows.append(
            action_row(
                "P1",
                site,
                f"复盘 AI 标杆 ASIN {top_ai.get('asin', '')}",
                f"品牌 {top_ai.get('standard_brand', '')}，月销售额 {num(top_ai.get('monthly_revenue'))}。",
                "市场分析",
                "AI ASIN 销售额 / 标题卖点 / 评论和主图",
            )
        )
    if product.empty:
        rows.append(
            action_row(
                "P2",
                site,
                "补齐商品明细",
                "本周缺少商品明细，价格带、ASIN 变化和类目销量反推不可复核。",
                "数据分析",
                "商品集中度明细 / BSR 排名 / 价格",
            )
        )
    if not rows:
        rows.append(
            action_row(
                "P2",
                site,
                "维持监控并复核 Top ASIN 变化",
                "未触发 P0/P1 异常，保留本周作为趋势基线。",
                "站点运营",
                "PLAUD 份额 / AI 竞品渗透 / Top ASIN 排名",
            )
        )
    return rows


def action_row(priority: str, site: str, title: str, detail: str, owner: str, metric: str) -> dict[str, str]:
    return {
        "优先级": priority,
        "站点": site,
        "行动建议": title,
        "判断依据": detail,
        "负责人": owner,
        "复核指标": metric,
    }


def build_feishu_message(
    week_id: str,
    summary_df: pd.DataFrame,
    actions_df: pd.DataFrame,
    results: list[WeeklyRunResult],
    public_base_url: str,
) -> str:
    ok_count = sum(1 for item in results if item.status == "ok")
    total_count = len(results)
    lines = [
        f"PLAUD 亚马逊监控周报｜{week_id}",
        "",
        f"覆盖站点：{ok_count}/{total_count}",
        f"看板链接：{public_base_url}/?week_id={week_id}",
        f"行动建议：{public_base_url}/actions?week_id={week_id}",
        "",
        "七站点核心指标：",
    ]
    for _, row in summary_df.sort_values("站点").iterrows():
        lines.append(
            f"- {row.get('站点')}: PLAUD {pct(row.get('PLAUD销量份额'))}"
            f"（{format_pp(row.get('PLAUD销量份额环比pp'))}），"
            f"AI {pct(row.get('AI竞品销量渗透'))}，类目月销量 {num(row.get('类目月销量'))}"
        )
    lines.append("")
    lines.append("行动建议 Top：")
    for _, row in actions_df.head(8).iterrows():
        lines.append(f"- [{row.get('优先级')}] {row.get('站点')}｜{row.get('行动建议')}：{row.get('判断依据')}")
    failed = [item for item in results if item.status != "ok"]
    if failed:
        lines.append("")
        lines.append("拉取失败：")
        for item in failed:
            lines.append(f"- {item.marketplace}: {item.error}")
    return "\n".join(lines)


def site_metrics(
    run: dict[str, Any],
    brand: pd.DataFrame,
    ai_summary: pd.DataFrame,
    prev_brand: pd.DataFrame,
    prev_ai: pd.DataFrame,
) -> dict[str, float]:
    plaud = first_row(brand[brand["brand"] == "PLAUD"]) if not brand.empty and "brand" in brand else {}
    competitors = first_row(brand[brand["brand"] == "COMPETITORS_TOTAL"]) if not brand.empty and "brand" in brand else {}
    ai = first_row(ai_summary) if not ai_summary.empty else {}
    prev_plaud = first_row(prev_brand[prev_brand["brand"] == "PLAUD"]) if not prev_brand.empty and "brand" in prev_brand else {}
    prev_ai_row = first_row(prev_ai) if not prev_ai.empty else {}
    plaud_share = as_float(plaud.get("monthly_units_share"))
    ai_share = as_float(ai.get("ai_units_share"))
    return {
        "plaud_units_share": plaud_share,
        "plaud_units_delta_pp": (plaud_share - as_float(prev_plaud.get("monthly_units_share"))) * 100 if prev_plaud else 0.0,
        "competitor_units_share": as_float(competitors.get("monthly_units_share")),
        "ai_units_share": ai_share,
        "ai_units_delta_pp": (ai_share - as_float(prev_ai_row.get("ai_units_share"))) * 100 if prev_ai_row else 0.0,
        "category_units": as_float(ai.get("category_units")),
        "ai_asin_count": as_float(ai.get("ai_competitor_asin_count")),
    }


def send_feishu_delivery(mode: str, message: str, workbook_path: Path, markdown_path: Path) -> None:
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
        for path in (workbook_path, markdown_path):
            file_key = feishu_upload_file(token, path)
            send_feishu_bot_file(token, receive_id_type, receive_id, file_key)
        print("Feishu bot message and files sent.")


def send_feishu_webhook(webhook: str, message: str) -> None:
    payload: dict[str, Any] = {"msg_type": "text", "content": {"text": message}}
    secret = os.environ.get("FEISHU_WEBHOOK_SECRET", "").strip()
    if secret:
        timestamp = str(int(time.time()))
        sign = base64.b64encode(hmac.new(f"{timestamp}\n{secret}".encode("utf-8"), digestmod=hashlib.sha256).digest()).decode("utf-8")
        payload["timestamp"] = timestamp
        payload["sign"] = sign
    post_json(webhook, payload)


def feishu_tenant_token(app_id: str, app_secret: str) -> str:
    payload = {"app_id": app_id, "app_secret": app_secret}
    data = post_json("https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal", payload)
    token = data.get("tenant_access_token")
    if not token:
        raise RuntimeError(f"Feishu tenant token failed: {data}")
    return str(token)


def send_feishu_bot_text(token: str, receive_id_type: str, receive_id: str, message: str) -> None:
    url = f"https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type={receive_id_type}"
    payload = {"receive_id": receive_id, "msg_type": "text", "content": json.dumps({"text": message}, ensure_ascii=False)}
    post_json(url, payload, token=token)


def send_feishu_bot_file(token: str, receive_id_type: str, receive_id: str, file_key: str) -> None:
    url = f"https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type={receive_id_type}"
    payload = {"receive_id": receive_id, "msg_type": "file", "content": json.dumps({"file_key": file_key}, ensure_ascii=False)}
    post_json(url, payload, token=token)


def feishu_upload_file(token: str, path: Path) -> str:
    file_type = "xls" if path.suffix.lower() in {".xls", ".xlsx"} else "stream"
    fields = {"file_type": file_type, "file_name": path.name}
    files = {"file": path}
    data, content_type = encode_multipart(fields, files)
    req = request.Request(
        "https://open.feishu.cn/open-apis/im/v1/files",
        data=data,
        headers={"Authorization": f"Bearer {token}", "Content-Type": content_type},
        method="POST",
    )
    with request.urlopen(req, timeout=60) as response:
        payload = json.loads(response.read().decode("utf-8"))
    file_key = payload.get("data", {}).get("file_key")
    if not file_key:
        raise RuntimeError(f"Feishu file upload failed: {payload}")
    return str(file_key)


def post_json(url: str, payload: dict[str, Any], token: str | None = None) -> dict[str, Any]:
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = request.Request(url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), headers=headers, method="POST")
    with request.urlopen(req, timeout=60) as response:
        raw = response.read().decode("utf-8")
    return json.loads(raw) if raw else {}


def encode_multipart(fields: dict[str, str], files: dict[str, Path]) -> tuple[bytes, str]:
    boundary = f"----plaud-{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.append(f"--{boundary}\r\n".encode("utf-8"))
        chunks.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
        chunks.append(str(value).encode("utf-8") + b"\r\n")
    for name, path in files.items():
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        chunks.append(f"--{boundary}\r\n".encode("utf-8"))
        chunks.append(f'Content-Disposition: form-data; name="{name}"; filename="{path.name}"\r\n'.encode("utf-8"))
        chunks.append(f"Content-Type: {mime}\r\n\r\n".encode("utf-8"))
        chunks.append(path.read_bytes())
        chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def latest_run_for_site_week(db_path: str, week_id: str, marketplace: str) -> dict[str, Any] | None:
    with connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT *
            FROM uploaded_reports
            WHERE status = 'ok' AND week_id = ? AND marketplace = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (week_id, marketplace),
        ).fetchone()
    return dict(row) if row else None


def previous_site_run(db_path: str, marketplace: str, week_id: str) -> dict[str, Any] | None:
    candidates = [
        run
        for run in latest_runs(db_path, limit=2000)
        if run.get("status") == "ok" and run.get("marketplace") == marketplace and week_sort_key(run.get("week_id")) < week_sort_key(week_id)
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda item: (*week_sort_key(item.get("week_id")), int(item.get("id") or 0)))


def selected_marketplaces(raw: str, config: dict[str, Any]) -> list[str]:
    if raw:
        values = raw.split(",")
    else:
        values = config.get("monitoring", {}).get("marketplaces", DEFAULT_MARKETPLACES)
    return [str(value).strip().upper() for value in values if str(value).strip()]


def current_week_id() -> str:
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    iso = now.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def week_sort_key(value: object) -> tuple[int, int, str]:
    text = str(value or "")
    if "-W" in text:
        year, week = text.split("-W", 1)
        try:
            return int(year), int(week), text
        except ValueError:
            pass
    return (0, 0, text)


def first_row(df: pd.DataFrame) -> dict[str, Any]:
    return df.iloc[0].to_dict() if not df.empty else {}


def as_float(value: object, default: float = 0.0) -> float:
    try:
        if pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def pct(value: object) -> str:
    return f"{as_float(value) * 100:.2f}%"


def num(value: object) -> str:
    return f"{as_float(value):,.0f}"


def format_pp(value: object) -> str:
    number = as_float(value)
    sign = "+" if number > 0 else ""
    return f"{sign}{number:.2f}pp"


def resolve_notify_mode(mode: str) -> str:
    if mode != "auto":
        return mode
    has_webhook = bool(os.environ.get("FEISHU_WEBHOOK_URL", "").strip())
    has_bot = bool(
        os.environ.get("FEISHU_APP_ID", "").strip()
        and os.environ.get("FEISHU_APP_SECRET", "").strip()
        and os.environ.get("FEISHU_RECEIVE_ID", "").strip()
    )
    if has_webhook and has_bot:
        return "both"
    if has_bot:
        return "bot"
    if has_webhook:
        return "webhook"
    return "none"


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


if __name__ == "__main__":
    raise SystemExit(main())
