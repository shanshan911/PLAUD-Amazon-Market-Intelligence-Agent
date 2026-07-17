from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from plaud_monitor.config import load_config
from plaud_monitor.integrations.amazon_ads import AmazonAdsClient, download_ads_report, profile_id_from_config
from plaud_monitor.integrations.base import ApiConfigError, ApiRequestError


REPORT_PRESETS: dict[str, dict[str, Any]] = {
    "search_term": {
        "label": "Sponsored Products Search Term",
        "report_type_id": "spSearchTerm",
        "group_by": ["searchTerm"],
        "columns": [
            "date",
            "campaignName",
            "adGroupName",
            "targeting",
            "matchType",
            "searchTerm",
            "impressions",
            "clicks",
            "cost",
            "sales7d",
            "purchases7d",
            "unitsSoldClicks7d",
            "acosClicks7d",
            "roasClicks7d",
        ],
    },
    "campaign": {
        "label": "Sponsored Products Campaign",
        "report_type_id": "spCampaigns",
        "group_by": ["campaign"],
        "columns": [
            "date",
            "campaignName",
            "campaignId",
            "campaignStatus",
            "impressions",
            "clicks",
            "cost",
            "sales7d",
            "purchases7d",
            "unitsSoldClicks7d",
            "acosClicks7d",
            "roasClicks7d",
        ],
    },
    "targeting": {
        "label": "Sponsored Products Targeting",
        "report_type_id": "spTargeting",
        "group_by": ["targeting"],
        "columns": [
            "date",
            "campaignName",
            "adGroupName",
            "targeting",
            "matchType",
            "impressions",
            "clicks",
            "cost",
            "sales7d",
            "purchases7d",
            "unitsSoldClicks7d",
            "acosClicks7d",
            "roasClicks7d",
        ],
    },
    "asin": {
        "label": "Sponsored Products Advertised Product",
        "report_type_id": "spAdvertisedProduct",
        "group_by": ["advertiser"],
        "columns": [
            "date",
            "campaignName",
            "adGroupName",
            "advertisedAsin",
            "advertisedSku",
            "impressions",
            "clicks",
            "cost",
            "sales7d",
            "purchases7d",
            "unitsSoldClicks7d",
            "acosClicks7d",
            "roasClicks7d",
        ],
    },
}


@dataclass
class LocalFileItem:
    path: Path
    filename: str

    def __post_init__(self) -> None:
        self.file = self.path.open("rb")


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def iso_week_id(day: date) -> str:
    year, week, _ = day.isocalendar()
    return f"{year}-W{week:02d}"


def default_date_range() -> tuple[str, str, str]:
    today = date.today()
    end = today - timedelta(days=1)
    start = end - timedelta(days=6)
    return start.isoformat(), end.isoformat(), iso_week_id(end)


def split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def build_report_request(args: argparse.Namespace) -> dict[str, Any]:
    preset = REPORT_PRESETS[args.report_type]
    columns = split_csv(args.columns) if args.columns else list(preset["columns"])
    group_by = split_csv(args.group_by) if args.group_by else list(preset["group_by"])
    return {
        "name": f"PLAUD_{args.marketplace}_{args.report_type}_{args.start_date}_{args.end_date}_{int(time.time())}",
        "startDate": args.start_date,
        "endDate": args.end_date,
        "configuration": {
            "adProduct": args.ad_product,
            "groupBy": group_by,
            "columns": columns,
            "reportTypeId": args.report_type_id or preset["report_type_id"],
            "timeUnit": args.time_unit,
            "format": args.format,
        },
    }


def report_id_from_response(response: dict[str, Any]) -> str:
    for key in ["reportId", "report_id", "id"]:
        value = str(response.get(key) or "").strip()
        if value:
            return value
    raise ApiRequestError(f"Amazon Ads API did not return a reportId: {response}")


def report_status(payload: dict[str, Any]) -> str:
    return str(payload.get("status") or payload.get("statusDetails") or "").upper()


def report_download_url(payload: dict[str, Any]) -> str:
    for key in ["url", "downloadUrl", "location"]:
        value = str(payload.get(key) or "").strip()
        if value:
            return value
    details = payload.get("locationDetails") or {}
    if isinstance(details, dict):
        for key in ["url", "downloadUrl", "location"]:
            value = str(details.get(key) or "").strip()
            if value:
                return value
    return ""


def wait_for_report(client: AmazonAdsClient, profile_id: str, report_id: str, poll_seconds: int, max_wait_seconds: int) -> dict[str, Any]:
    deadline = time.time() + max_wait_seconds
    last_payload: dict[str, Any] = {}
    while time.time() <= deadline:
        payload = client.get_report(profile_id, report_id)
        last_payload = payload
        status = report_status(payload)
        if status in {"COMPLETED", "SUCCESS", "DONE"} and report_download_url(payload):
            return payload
        if status in {"FAILURE", "FAILED", "CANCELLED"}:
            raise ApiRequestError(f"Amazon Ads report failed: {payload}")
        print(f"Report {report_id} status={status or 'UNKNOWN'}; waiting {poll_seconds}s...")
        time.sleep(poll_seconds)
    raise ApiRequestError(f"Timed out waiting for Amazon Ads report {report_id}: {last_payload}")


def decode_report_bytes(raw: bytes) -> Any:
    payload = raw
    if raw[:2] == b"\x1f\x8b":
        payload = gzip.decompress(raw)
    text = payload.decode("utf-8-sig", errors="replace")
    stripped = text.lstrip()
    if stripped.startswith("[") or stripped.startswith("{"):
        return json.loads(text)
    return list(csv.DictReader(io.StringIO(text)))


def records_from_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ["records", "reports", "data", "rows"]:
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return [payload]
    return []


def first_present(row: dict[str, Any], keys: list[str]) -> Any:
    lower = {str(key).lower(): key for key in row}
    for key in keys:
        if key in row and row.get(key) not in {None, ""}:
            return row.get(key)
        actual = lower.get(key.lower())
        if actual and row.get(actual) not in {None, ""}:
            return row.get(actual)
    return ""


def normalize_record(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "date": first_present(row, ["date", "startDate"]),
        "campaign": first_present(row, ["campaignName", "campaign", "campaignId"]),
        "ad group": first_present(row, ["adGroupName", "adGroup", "adGroupId"]),
        "search term": first_present(row, ["searchTerm", "customerSearchTerm", "query"]),
        "targeting": first_present(row, ["targeting", "keyword", "keywordText", "targetingText"]),
        "match type": first_present(row, ["matchType"]),
        "asin": first_present(row, ["advertisedAsin", "purchasedAsin", "asin"]),
        "sku": first_present(row, ["advertisedSku", "sku"]),
        "impressions": first_present(row, ["impressions"]),
        "clicks": first_present(row, ["clicks"]),
        "spend": first_present(row, ["cost", "spend"]),
        "sales": first_present(row, ["sales", "sales7d", "sales14d", "attributedSales14d"]),
        "orders": first_present(row, ["orders", "purchases", "purchases7d", "purchases14d"]),
        "units": first_present(row, ["units", "unitsSoldClicks7d", "unitsSoldClicks14d"]),
        "acos": first_present(row, ["acos", "acosClicks7d", "acosClicks14d"]),
        "roas": first_present(row, ["roas", "roasClicks7d", "roasClicks14d"]),
    }


def write_csv(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "date",
        "campaign",
        "ad group",
        "search term",
        "targeting",
        "match type",
        "asin",
        "sku",
        "impressions",
        "clicks",
        "spend",
        "sales",
        "orders",
        "units",
        "acos",
        "roas",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            writer.writerow({key: record.get(key, "") for key in fieldnames})


def import_csv_to_db(csv_path: Path, week_id: str, marketplace: str, report_type: str, note: str) -> int:
    import app

    file_item = LocalFileItem(csv_path, csv_path.name)
    try:
        return app.import_ads_report(week_id, marketplace, report_type, file_item, note)
    finally:
        try:
            file_item.file.close()
        except Exception:
            pass


def main() -> int:
    default_start, default_end, default_week = default_date_range()
    parser = argparse.ArgumentParser(description="Pull Amazon Ads API reports into PLAUD monitor")
    parser.add_argument("--config", default="config/monitor_config.p0.json")
    parser.add_argument("--env-file", default=".env.local")
    parser.add_argument("--marketplace", default="US", choices=["US", "UK", "DE", "FR", "IT", "ES", "JP"])
    parser.add_argument("--profile-id", default="", help="Override AMAZON_ADS_PROFILE_ID")
    parser.add_argument("--week-id", default=default_week)
    parser.add_argument("--start-date", default=default_start)
    parser.add_argument("--end-date", default=default_end)
    parser.add_argument("--report-type", choices=sorted(REPORT_PRESETS), default="search_term")
    parser.add_argument("--report-type-id", default="", help="Override Amazon Ads reportTypeId")
    parser.add_argument("--columns", default="", help="Comma-separated Amazon Ads columns override")
    parser.add_argument("--group-by", default="", help="Comma-separated Amazon Ads groupBy override")
    parser.add_argument("--ad-product", default="SPONSORED_PRODUCTS")
    parser.add_argument("--time-unit", choices=["SUMMARY", "DAILY"], default="SUMMARY")
    parser.add_argument("--format", default="GZIP_JSON")
    parser.add_argument("--poll-seconds", type=int, default=10)
    parser.add_argument("--max-wait-seconds", type=int, default=600)
    parser.add_argument("--output-dir", default="outputs/amazon_ads_api")
    parser.add_argument("--list-profiles", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-db-import", action="store_true")
    args = parser.parse_args()

    root = Path(args.config).resolve().parents[1]
    load_env_file(root / args.env_file)
    config = load_config(args.config)

    if args.dry_run:
        ads_cfg = config.get("api_integrations", {}).get("amazon_ads", {})
        profile_env = str(ads_cfg.get("profile_id_env") or "AMAZON_ADS_PROFILE_ID")
        profile_id = args.profile_id or os.environ.get(profile_env, "").strip() or f"<{profile_env}>"
        print(json.dumps({"profile_id": profile_id, "request": build_report_request(args)}, ensure_ascii=False, indent=2))
        return 0

    client = AmazonAdsClient.from_config(config, args.marketplace)

    if args.list_profiles:
        profiles = client.list_profiles()
        print(json.dumps(profiles, ensure_ascii=False, indent=2))
        return 0

    profile_id = args.profile_id or profile_id_from_config(config)
    request_body = build_report_request(args)
    created = client.create_report(profile_id, request_body)
    report_id = report_id_from_response(created)
    print(f"Created Amazon Ads report: {report_id}")

    report = wait_for_report(client, profile_id, report_id, args.poll_seconds, args.max_wait_seconds)
    url = report_download_url(report)
    if not url:
        raise ApiRequestError(f"Amazon Ads report completed without download URL: {report}")
    raw = download_ads_report(url)
    payload = decode_report_bytes(raw)
    records = [normalize_record(item) for item in records_from_payload(payload)]

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(args.output_dir) / args.week_id / args.marketplace
    raw_path = output_dir / f"{stamp}_{args.report_type}_{report_id}.raw"
    json_path = output_dir / f"{stamp}_{args.report_type}_{report_id}.json"
    csv_path = output_dir / f"{stamp}_{args.report_type}_{report_id}.csv"
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_path.write_bytes(raw)
    json_path.write_text(json.dumps({"request": request_body, "report": report, "records": records}, ensure_ascii=False, indent=2), encoding="utf-8")
    write_csv(csv_path, records)

    imported = 0
    if not args.skip_db_import:
        imported = import_csv_to_db(
            csv_path,
            args.week_id,
            args.marketplace,
            args.report_type,
            f"Amazon Ads API report_id={report_id}; {args.start_date}..{args.end_date}",
        )

    print(
        json.dumps(
            {
                "status": "ok",
                "report_id": report_id,
                "records": len(records),
                "rows_imported": imported,
                "csv_path": str(csv_path),
                "json_path": str(json_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ApiConfigError, ApiRequestError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
