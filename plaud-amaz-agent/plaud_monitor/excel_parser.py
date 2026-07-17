from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from .normalizers import normalize_key, normalize_text, parse_int, parse_number, parse_percent


@dataclass
class ParsedReport:
    marketplace: str
    source_file: Path
    brand_df: pd.DataFrame
    product_df: pd.DataFrame
    warnings: list[str]


def alias_lookup(field_aliases: dict[str, list[str]]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for canonical, aliases in field_aliases.items():
        lookup[normalize_key(canonical)] = canonical
        for alias in aliases:
            lookup[normalize_key(alias)] = canonical
    return lookup


def canonicalize_columns(df: pd.DataFrame, field_aliases: dict[str, list[str]]) -> pd.DataFrame:
    lookup = alias_lookup(field_aliases)
    renamed: dict[Any, str] = {}
    used: set[str] = set()
    for col in df.columns:
        canonical = lookup.get(normalize_key(col)) or infer_column_name(col, field_aliases)
        if canonical and canonical not in used:
            renamed[col] = canonical
            used.add(canonical)
        else:
            renamed[col] = normalize_text(col)
    result = df.rename(columns=renamed)
    return result.dropna(how="all")


def infer_column_name(col: Any, field_aliases: dict[str, list[str]]) -> str | None:
    col_key = normalize_key(col)
    if not col_key:
        return None
    for canonical, aliases in field_aliases.items():
        for alias in aliases:
            alias_key = normalize_key(alias)
            if alias_key and col_key.startswith(alias_key):
                return canonical
    return None


def find_sheet_name(excel: pd.ExcelFile, candidates: list[str]) -> str:
    normalized = {normalize_key(name): name for name in excel.sheet_names}
    for candidate in candidates:
        if normalize_key(candidate) in normalized:
            return normalized[normalize_key(candidate)]
    raise ValueError(f"找不到目标 Sheet，候选名称={candidates}，实际 Sheet={excel.sheet_names}")


def read_canonical_sheet(
    excel: pd.ExcelFile,
    sheet_name: str,
    field_aliases: dict[str, list[str]],
    required_fields: set[str],
    max_header_scan_rows: int = 12,
) -> pd.DataFrame:
    last_df: pd.DataFrame | None = None
    for header_row in range(max_header_scan_rows):
        df = pd.read_excel(excel, sheet_name=sheet_name, header=header_row)
        df = canonicalize_columns(df, field_aliases)
        last_df = df
        if required_fields.issubset(set(df.columns)):
            return df
    actual = list(last_df.columns) if last_df is not None else []
    raise ValueError(f"Sheet `{sheet_name}` 缺少必要字段 {sorted(required_fields)}，当前字段={actual}")


def clean_brand_df(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    result["brand_name"] = result["brand_name"].map(normalize_text)
    if "monthly_units" in result:
        result["monthly_units"] = result["monthly_units"].map(parse_int)
    if "monthly_revenue" in result:
        result["monthly_revenue"] = result["monthly_revenue"].map(parse_number)
    if "monthly_units_share" in result:
        result["monthly_units_share"] = result["monthly_units_share"].map(parse_percent)
    if "monthly_revenue_share" in result:
        result["monthly_revenue_share"] = result["monthly_revenue_share"].map(parse_percent)
    result = result[result["brand_name"] != ""]
    return result


def clean_product_df(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    result["brand_name"] = result["brand_name"].map(normalize_text)
    result["product_title"] = result["product_title"].map(normalize_text)
    result["asin"] = result["asin"].map(normalize_text)
    result["monthly_units"] = result["monthly_units"].map(parse_int)
    result["monthly_revenue"] = result["monthly_revenue"].map(parse_number)
    if "price" in result:
        result["price"] = result["price"].map(parse_number)
    if "bsr_rank" in result:
        result["bsr_rank"] = result["bsr_rank"].map(parse_int)
    # SellerSprite reports often include both a broad category BSR and a final
    # subcategory BSR. For category-size estimation, the final category rank is
    # the better signal, so prefer 小类BSR when it is present.
    if "小类BSR" in result:
        small_rank = result["小类BSR"].map(parse_int)
        result["subcategory_bsr_rank"] = small_rank
        if "bsr_rank" in result:
            result["bsr_rank"] = small_rank.where(small_rank.notna() & (small_rank > 0), result["bsr_rank"])
        else:
            result["bsr_rank"] = small_rank
    result = result[(result["asin"] != "") | (result["product_title"] != "")]
    return result


def parse_report(path: str | Path, marketplace: str, config: dict[str, Any]) -> ParsedReport:
    source = Path(path)
    warnings: list[str] = []
    excel = pd.ExcelFile(source)
    sheets = config["sheets"]
    field_aliases = config["field_aliases"]

    brand_sheet = find_sheet_name(excel, sheets["brand_concentration"])
    product_candidates = list(sheets["product_concentration"]) + [marketplace]
    product_sheet = find_sheet_name(excel, product_candidates)

    brand_df = read_canonical_sheet(
        excel,
        brand_sheet,
        field_aliases,
        required_fields={"brand_name"},
    )
    product_df = read_canonical_sheet(
        excel,
        product_sheet,
        field_aliases,
        required_fields={"asin", "brand_name", "product_title", "monthly_units", "monthly_revenue"},
    )

    brand_df = clean_brand_df(brand_df)
    product_df = clean_product_df(product_df)

    if "monthly_units_share" not in brand_df.columns:
        warnings.append("品牌集中度缺少月销量占比，将尝试用品牌销量/类目总销量计算。")
    if "monthly_revenue_share" not in brand_df.columns:
        warnings.append("品牌集中度缺少月销售额占比，将尝试用品牌销售额/类目总销售额计算。")
    if product_df["monthly_units"].fillna(0).sum() == 0:
        warnings.append("商品集中度类目总销量为 0 或未识别。")
    if product_df["monthly_revenue"].fillna(0).sum() == 0:
        warnings.append("商品集中度类目总销售额为 0 或未识别。")

    return ParsedReport(
        marketplace=marketplace,
        source_file=source,
        brand_df=brand_df,
        product_df=product_df,
        warnings=warnings,
    )
