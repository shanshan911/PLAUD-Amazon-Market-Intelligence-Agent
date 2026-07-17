#!/usr/bin/env python3
"""Fetch or parse public Amazon frontend pages for lightweight monitoring.

This script intentionally avoids login, captcha solving, proxy rotation, or any
other anti-bot bypass. It is designed for small validation samples and for
parsing HTML that an operator has manually saved from a browser.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


MARKETPLACES = {
    "US": {"domain": "www.amazon.com", "lang": "en-US,en;q=0.8"},
    "UK": {"domain": "www.amazon.co.uk", "lang": "en-GB,en;q=0.8"},
    "DE": {"domain": "www.amazon.de", "lang": "de-DE,de;q=0.8,en;q=0.5"},
    "FR": {"domain": "www.amazon.fr", "lang": "fr-FR,fr;q=0.8,en;q=0.5"},
    "IT": {"domain": "www.amazon.it", "lang": "it-IT,it;q=0.8,en;q=0.5"},
    "ES": {"domain": "www.amazon.es", "lang": "es-ES,es;q=0.8,en;q=0.5"},
    "JP": {"domain": "www.amazon.co.jp", "lang": "ja-JP,ja;q=0.8,en;q=0.5"},
}


@dataclass
class FetchResult:
    url: str
    marketplace: str
    status_code: int | None
    fetched_at: str
    source: str
    blocked: bool
    error: str = ""
    html_path: str = ""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def compact_text(value: str) -> str:
    value = html.unescape(value)
    value = re.sub(r"<script\b.*?</script>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<style\b.*?</style>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def strip_tags(value: str) -> str:
    return compact_text(value)


def get_attr(tag: str, attr: str) -> str:
    match = re.search(rf"\b{re.escape(attr)}=[\"']([^\"']+)[\"']", tag, flags=re.I)
    return html.unescape(match.group(1)).strip() if match else ""


def first_match(patterns: list[str], text: str, flags: int = re.I | re.S) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, flags=flags)
        if match:
            return html.unescape(match.group(1)).strip()
    return ""


def normalize_number(value: str) -> float | None:
    raw = re.sub(r"[^\d,.\-]", "", value or "")
    if not raw:
        return None
    if "," in raw and "." in raw:
        if raw.rfind(",") > raw.rfind("."):
            raw = raw.replace(".", "").replace(",", ".")
        else:
            raw = raw.replace(",", "")
    elif "," in raw and "." not in raw:
        parts = raw.split(",")
        if len(parts[-1]) in {1, 2}:
            raw = raw.replace(".", "").replace(",", ".")
        else:
            raw = raw.replace(",", "")
    try:
        return float(raw)
    except ValueError:
        return None


def normalize_int(value: str) -> int | None:
    number = normalize_number(value)
    return int(number) if number is not None else None


def build_product_url(marketplace: str, asin: str) -> str:
    site = MARKETPLACES[marketplace.upper()]
    return f"https://{site['domain']}/dp/{asin.strip()}"


def infer_marketplace(url: str, fallback: str) -> str:
    for code, item in MARKETPLACES.items():
        if item["domain"] in url:
            return code
    return fallback.upper()


def looks_blocked(status_code: int | None, page: str) -> bool:
    page_lower = page.lower()
    if status_code in {403, 429, 503}:
        return True
    block_markers = [
        "robot check",
        "enter the characters you see below",
        "captcha",
        "/errors/validatecaptcha",
        "api-services-support@amazon.com",
        "sorry, we just need to make sure you're not a robot",
    ]
    return any(marker in page_lower for marker in block_markers)


def fetch_html(url: str, marketplace: str, timeout: int) -> tuple[int | None, str, str]:
    site = MARKETPLACES.get(marketplace.upper(), MARKETPLACES["US"])
    headers = {
        "User-Agent": "PLAUDMarketMonitor/0.1 (+public-page-validation; no-login)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": site["lang"],
        "Connection": "close",
    }
    request = Request(url, headers=headers, method="GET")
    try:
        with urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            body = response.read().decode(charset, "replace")
            return response.status, body, ""
    except HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        return exc.code, body, str(exc)
    except URLError as exc:
        return None, "", str(exc)
    except TimeoutError as exc:
        return None, "", str(exc)


def parse_title(page: str) -> str:
    return strip_tags(
        first_match(
            [
                r"<span[^>]+id=[\"']productTitle[\"'][^>]*>(.*?)</span>",
                r"<meta[^>]+property=[\"']og:title[\"'][^>]+content=[\"']([^\"']+)[\"']",
                r"<title[^>]*>(.*?)</title>",
            ],
            page,
        )
    )


def parse_brand(page: str) -> str:
    byline = strip_tags(first_match([r"<a[^>]+id=[\"']bylineInfo[\"'][^>]*>(.*?)</a>"], page))
    if byline:
        byline = re.sub(r"^(Visit the|Brand:|Marke:|Marca:|Visita lo|Visitez la)\s+", "", byline, flags=re.I)
        byline = re.sub(r"\s+(Store|Shop|ストア)$", "", byline, flags=re.I)
        byline = re.sub(r"(の)?ストアを表示$", "", byline)
        return byline.strip()
    label_patterns = [
        r"(?:Brand|Marke|Marque|Marca|ブランド)\s*[:：]\s*([A-Za-z0-9][^|,;]{1,80})",
    ]
    text = compact_text(page)
    return first_match(label_patterns, text, flags=re.I)


def price_currency(raw: str) -> str:
    raw = raw.strip()
    match = re.match(r"([^\d\s.,]+)", raw)
    return match.group(1) if match else ""


def parse_price(page: str) -> dict[str, Any]:
    price_area = first_match(
        [
            r"<div[^>]+id=[\"']corePrice[^\"']*[\"'][^>]*>(.*?)</div>\s*</div>",
            r"<span[^>]+id=[\"']priceblock_[^\"']+[\"'][^>]*>(.*?)</span>",
        ],
        page,
    )
    source = price_area or page
    raw = strip_tags(
        first_match(
            [
                r"<span[^>]+class=[\"'][^\"']*a-offscreen[^\"']*[\"'][^>]*>(.*?)</span>",
                r"<span[^>]+id=[\"']priceblock_[^\"']+[\"'][^>]*>(.*?)</span>",
            ],
            source,
        )
    )
    if not raw:
        whole = strip_tags(first_match([r"<span[^>]+class=[\"'][^\"']*a-price-whole[^\"']*[\"'][^>]*>(.*?)</span>"], source))
        fraction = strip_tags(first_match([r"<span[^>]+class=[\"'][^\"']*a-price-fraction[^\"']*[\"'][^>]*>(.*?)</span>"], source))
        symbol = strip_tags(first_match([r"<span[^>]+class=[\"'][^\"']*a-price-symbol[^\"']*[\"'][^>]*>(.*?)</span>"], source))
        if whole:
            raw = f"{symbol}{whole}{'.' + fraction if fraction else ''}"
    return {"raw": raw, "value": normalize_number(raw), "currency": price_currency(raw)}


def parse_rating(page: str) -> dict[str, Any]:
    raw = strip_tags(
        first_match(
            [
                r"<span[^>]+id=[\"']acrPopover[\"'][^>]+title=[\"']([^\"']+)[\"']",
                r"([0-5](?:[.,]\d)?\s*(?:out of|von|sur|su|de)\s*5\s*stars?)",
                r"(5つ星のうち\s*[0-5](?:[.,]\d)?)",
            ],
            page,
        )
    )
    value = None
    if raw:
        jp = re.search(r"5つ星のうち\s*([0-5](?:[.,]\d)?)", raw)
        value = normalize_number(jp.group(1) if jp else raw)
    return {"raw": raw, "value": value}


def parse_review_count(page: str) -> dict[str, Any]:
    raw = strip_tags(
        first_match(
            [
                r"<span[^>]+id=[\"']acrCustomerReviewText[\"'][^>]*>(.*?)</span>",
                r"([0-9][0-9.,\s]*\s+(?:ratings?|reviews?|Bewertungen|évaluations|valutazioni|valoraciones|個の評価))",
            ],
            page,
        )
    )
    return {"raw": raw, "value": normalize_int(raw)}


def parse_bsr_rank_list(segment: str) -> list[dict[str, Any]]:
    ranks: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    patterns = [
        r"([A-Za-z0-9＆&/・\-\s\u3040-\u30ff\u3400-\u9fff]+?)\s*[-–]\s*([0-9][0-9.,\s]*)\s*位",
        r"#\s*([0-9][0-9.,\s]*)\s+in\s+([^>#|;,.]+)",
        r"(?:Nr\.?|n[.º°]*)\s*([0-9][0-9.,\s]*)\s+(?:in|en|dans|nella categoria)\s+([^>#|;,.]+)",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, segment, flags=re.I):
            if pattern.startswith("([A-Za-z"):
                category = match.group(1).strip(" :·-")
                rank = normalize_int(match.group(2))
            else:
                rank = normalize_int(match.group(1))
                category = match.group(2).strip(" :·-")
            if not rank or not category:
                continue
            category = re.sub(r"^(Amazon 売れ筋ランキング|Best Sellers Rank)\s*", "", category).strip()
            key = (category, rank)
            if key not in seen:
                seen.add(key)
                ranks.append({"category": category, "rank": rank})
    return ranks


def parse_bsr(page: str) -> dict[str, Any]:
    text = compact_text(page)
    keywords = [
        "Best Sellers Rank",
        "Bestseller-Rang",
        "Classement des meilleures ventes",
        "Classifica Bestseller",
        "Clasificación en los más vendidos",
        "Clasificación de los más vendidos",
        "Amazon 売れ筋ランキング",
        "売れ筋ランキング",
    ]
    segment = ""
    for keyword in keywords:
        idx = text.lower().find(keyword.lower())
        if idx >= 0:
            segment = text[idx : idx + 450]
            break
    rank = None
    category = ""
    ranks: list[dict[str, Any]] = []
    if segment:
        ranks = parse_bsr_rank_list(segment)
        if ranks:
            final_rank = ranks[-1]
            rank = final_rank["rank"]
            category = final_rank["category"]
        else:
            rank_match = re.search(r"(?:#|Nr\.?|n[.º°]*|第)?\s*([0-9][0-9.,\s]*)\s*(?:位)?", segment, flags=re.I)
            rank = normalize_int(rank_match.group(1)) if rank_match else None
            category_match = re.search(
                r"(?:in|en|dans|in der|nella categoria|em|位\s*)([^>#|]+?)(?:\s*(?:See Top|Voir|Siehe|Visualizza|Ver|$))",
                segment,
                flags=re.I,
            )
            category = category_match.group(1).strip(" :·") if category_match else ""
    return {"raw": segment, "rank": rank, "category": category, "ranks": ranks}


def parse_availability(page: str) -> str:
    return strip_tags(first_match([r"<div[^>]+id=[\"']availability[\"'][^>]*>(.*?)</div>"], page))


def parse_coupon(page: str) -> str:
    rendered = compact_text(page)
    label_coupon = strip_tags(first_match([r"<label[^>]+id=[\"']couponText[^\"']*[\"'][^>]*>(.*?)</label>"], page))
    if label_coupon:
        return label_coupon
    return first_match(
        [
            r"\b((?:Save|Coupon|Rabatt|Économisez|Risparmia|Ahorra|クーポン)\s+(?:[¥$€£]?\s*\d|[0-9０-９]|[^<]{0,60}%)[^。.;]{0,80})",
        ],
        rendered,
    )


def parse_image(page: str) -> str:
    tag = first_match([r"(<img[^>]+id=[\"']landingImage[\"'][^>]*>)"], page)
    if tag:
        return get_attr(tag, "data-old-hires") or get_attr(tag, "src")
    return first_match([r"<meta[^>]+property=[\"']og:image[\"'][^>]+content=[\"']([^\"']+)[\"']"], page)


def parse_asins(page: str) -> list[str]:
    asins: list[str] = []
    seen: set[str] = set()
    for asin in re.findall(r"/(?:dp|gp/product)/([A-Z0-9]{10})(?:[/?\"'#]|$)", page):
        if asin not in seen:
            seen.add(asin)
            asins.append(asin)
    for asin in re.findall(r"\bdata-asin=[\"']([A-Z0-9]{10})[\"']", page):
        if asin not in seen:
            seen.add(asin)
            asins.append(asin)
    return asins


def parse_product_page(page: str, url: str, marketplace: str) -> dict[str, Any]:
    title = parse_title(page)
    price = parse_price(page)
    rating = parse_rating(page)
    reviews = parse_review_count(page)
    bsr = parse_bsr(page)
    asin_from_url = first_match([r"/(?:dp|gp/product)/([A-Z0-9]{10})"], url)
    return {
        "page_type": "product",
        "marketplace": marketplace,
        "url": url,
        "asin": asin_from_url or first_match([r"\bASIN[:：]?\s*([A-Z0-9]{10})"], compact_text(page)),
        "title": title,
        "brand": parse_brand(page),
        "price_raw": price["raw"],
        "price_value": price["value"],
        "price_currency": price["currency"],
        "rating_raw": rating["raw"],
        "rating_value": rating["value"],
        "review_count_raw": reviews["raw"],
        "review_count": reviews["value"],
        "bsr_raw": bsr["raw"],
        "bsr_rank": bsr["rank"],
        "bsr_category": bsr["category"],
        "bsr_ranks": bsr["ranks"],
        "availability": parse_availability(page),
        "coupon": parse_coupon(page),
        "image_url": parse_image(page),
    }


def parse_listing_page(page: str, url: str, marketplace: str) -> dict[str, Any]:
    asins = parse_asins(page)
    return {
        "page_type": "listing",
        "marketplace": marketplace,
        "url": url,
        "asins_found": len(asins),
        "asins": asins[:100],
        "title": parse_title(page),
    }


def parse_page(page: str, url: str, marketplace: str) -> dict[str, Any]:
    if re.search(r"/(?:dp|gp/product)/[A-Z0-9]{10}", url):
        return parse_product_page(page, url, marketplace)
    result = parse_listing_page(page, url, marketplace)
    if result["asins_found"] == 1:
        product = parse_product_page(page, url, marketplace)
        product["page_type"] = "product_like"
        return product
    return result


def write_outputs(output_dir: Path, prefix: str, fetch: FetchResult, parsed: dict[str, Any], page: str) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{prefix}.json"
    csv_path = output_dir / f"{prefix}.csv"
    payload = {"fetch": asdict(fetch), "parsed": parsed}
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if parsed.get("page_type") == "listing":
        rows = [{"marketplace": parsed.get("marketplace"), "url": parsed.get("url"), "position": i + 1, "asin": asin} for i, asin in enumerate(parsed.get("asins", []))]
    else:
        rows = [parsed]
    if rows:
        fieldnames = sorted({key for row in rows for key in row.keys()})
        with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
    return json_path, csv_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch or parse public Amazon frontend pages")
    parser.add_argument("--marketplace", default="US", choices=sorted(MARKETPLACES), help="Amazon marketplace")
    parser.add_argument("--asin", default="", help="ASIN to fetch, e.g. B0FQ5J7HFQ")
    parser.add_argument("--url", default="", help="Full Amazon URL to fetch")
    parser.add_argument("--html-file", default="", help="Parse a manually saved Amazon HTML file instead of fetching")
    parser.add_argument("--output-dir", default="outputs/amazon_frontend", help="Output directory")
    parser.add_argument("--timeout", type=int, default=20, help="Network timeout in seconds")
    args = parser.parse_args()

    marketplace = args.marketplace.upper()
    if args.url:
        url = args.url
    elif args.asin:
        url = build_product_url(marketplace, args.asin)
    else:
        parser.error("Provide --asin, --url, or --html-file")

    marketplace = infer_marketplace(url, marketplace)
    source = "html_file" if args.html_file else "network"
    status_code: int | None = None
    error = ""
    page = ""
    html_path = ""

    if args.html_file:
        html_path = args.html_file
        page = Path(args.html_file).read_text(encoding="utf-8", errors="replace")
    else:
        status_code, page, error = fetch_html(url, marketplace, args.timeout)
        if page:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            raw_dir = Path(args.output_dir) / "raw"
            raw_dir.mkdir(parents=True, exist_ok=True)
            html_file = raw_dir / f"{timestamp}_{marketplace}_{args.asin or 'url'}.html"
            html_file.write_text(page, encoding="utf-8")
            html_path = str(html_file)
        time.sleep(0.2)

    blocked = looks_blocked(status_code, page)
    fetch = FetchResult(
        url=url,
        marketplace=marketplace,
        status_code=status_code,
        fetched_at=utc_now(),
        source=source,
        blocked=blocked,
        error=error,
        html_path=html_path,
    )
    parsed = parse_page(page, url, marketplace) if page and not blocked else {}
    prefix = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{marketplace}_{args.asin or 'amazon'}"
    json_path, csv_path = write_outputs(Path(args.output_dir), prefix, fetch, parsed, page)

    print(json.dumps({"fetch": asdict(fetch), "parsed": parsed, "json_path": str(json_path), "csv_path": str(csv_path)}, ensure_ascii=False, indent=2))
    if blocked:
        print("Amazon returned a blocked/captcha/robot-check page. Use manual HTML save or an authorized API for reliable production collection.", file=sys.stderr)
        return 2
    if error:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
