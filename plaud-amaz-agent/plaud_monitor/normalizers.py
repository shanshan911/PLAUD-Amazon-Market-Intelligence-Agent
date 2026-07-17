from __future__ import annotations

import math
import re
import unicodedata
from typing import Any


EMPTY_VALUES = {"", "-", "--", "—", "N/A", "NA", "None", "null", "暂无"}


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value))
    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalize_key(value: Any) -> str:
    text = normalize_text(value)
    text = text.replace("＆", "&")
    text = re.sub(r"\s+", " ", text)
    return text.casefold()


def is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    return normalize_text(value) in EMPTY_VALUES


def parse_number(value: Any) -> float | None:
    if is_empty(value):
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and math.isnan(value):
            return None
        return float(value)

    text = normalize_text(value)
    multiplier = 1.0
    if "亿" in text:
        multiplier = 100_000_000.0
    elif "万" in text:
        multiplier = 10_000.0
    elif re.search(r"(?<=\d)\s*[Kk]\b", text):
        multiplier = 1_000.0
    elif re.search(r"(?<=\d)\s*[Mm]\b", text):
        multiplier = 1_000_000.0

    cleaned = (
        text.replace(",", "")
        .replace("$", "")
        .replace("£", "")
        .replace("€", "")
        .replace("¥", "")
        .replace("￥", "")
        .replace("%", "")
    )
    match = re.search(r"-?\d+(?:\.\d+)?", cleaned)
    if not match:
        return None
    return float(match.group(0)) * multiplier


def parse_int(value: Any) -> int | None:
    parsed = parse_number(value)
    if parsed is None:
        return None
    return int(round(parsed))


def parse_percent(value: Any) -> float | None:
    if is_empty(value):
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and math.isnan(value):
            return None
        numeric = float(value)
        return numeric / 100.0 if abs(numeric) > 1 else numeric

    text = normalize_text(value)
    numeric = parse_number(text)
    if numeric is None:
        return None
    return numeric / 100.0 if "%" in text or abs(numeric) > 1 else numeric


def format_percent(value: float | None, digits: int = 2) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    return f"{value * 100:.{digits}f}%"


def format_number(value: float | int | None) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    if abs(float(value)) >= 1000:
        return f"{float(value):,.0f}"
    return f"{float(value):.0f}"


def safe_divide(numerator: float | int | None, denominator: float | int | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return float(numerator) / float(denominator)
