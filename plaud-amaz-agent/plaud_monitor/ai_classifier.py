from __future__ import annotations

import re
import unicodedata
from typing import Any

from .config import ai_keywords_for_marketplace
from .normalizers import normalize_text


def normalize_title(title: Any) -> str:
    return unicodedata.normalize("NFKC", normalize_text(title))


def keyword_pattern(keyword: str) -> re.Pattern[str]:
    keyword_norm = normalize_title(keyword)
    compact = keyword_norm.replace(".", "")
    if re.fullmatch(r"[A-Za-z]{1,3}", compact):
        return re.compile(rf"(?<![A-Za-z0-9]){re.escape(keyword_norm)}(?![A-Za-z0-9])", re.IGNORECASE)
    return re.compile(re.escape(keyword_norm), re.IGNORECASE)


def match_keywords(title: str, keywords: list[str]) -> list[str]:
    normalized = normalize_title(title)
    matches: list[str] = []
    for keyword in keywords:
        if keyword_pattern(keyword).search(normalized):
            matches.append(keyword)
    return matches


def should_exclude(title: str, exclude_terms: list[str]) -> bool:
    normalized = normalize_title(title)
    return any(keyword_pattern(term).search(normalized) for term in exclude_terms)


def classify_title(title: Any, marketplace: str, config: dict[str, Any]) -> tuple[bool, list[str]]:
    rules = config.get("ai_rules", {})
    keywords = ai_keywords_for_marketplace(config, marketplace)
    exclude_terms = list(rules.get("exclude_terms", []))
    normalized = normalize_title(title)
    if should_exclude(normalized, exclude_terms):
        return False, []
    matches = match_keywords(normalized, keywords)
    return bool(matches), matches
