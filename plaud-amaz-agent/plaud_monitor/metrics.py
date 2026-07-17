from __future__ import annotations

from typing import Any

import pandas as pd

from .ai_classifier import classify_title
from .brand import add_standard_brand_columns
from .normalizers import safe_divide


def compute_brand_share(
    brand_df: pd.DataFrame,
    product_df: pd.DataFrame,
    marketplace: str,
    config: dict[str, Any],
) -> pd.DataFrame:
    branded = add_standard_brand_columns(brand_df, config, marketplace)
    product_branded = add_standard_brand_columns(product_df, config, marketplace)

    category_units = product_df["monthly_units"].fillna(0).sum()
    category_revenue = product_df["monthly_revenue"].fillna(0).sum()

    rows: list[dict[str, Any]] = []
    tracked = branded[branded["brand_group"].isin(["plaud", "competitor"])]
    for brand, group in tracked.groupby("standard_brand", dropna=False):
        units = group["monthly_units"].fillna(0).sum() if "monthly_units" in group else None
        revenue = group["monthly_revenue"].fillna(0).sum() if "monthly_revenue" in group else None
        unit_share = (
            group["monthly_units_share"].fillna(0).sum()
            if "monthly_units_share" in group
            else safe_divide(units, category_units)
        )
        revenue_share = (
            group["monthly_revenue_share"].fillna(0).sum()
            if "monthly_revenue_share" in group
            else safe_divide(revenue, category_revenue)
        )
        first = group.iloc[0]
        rows.append(
            {
                "marketplace": marketplace,
                "brand": brand,
                "brand_group": first.get("brand_group", ""),
                "priority": first.get("competitor_priority", ""),
                "monthly_units": units,
                "monthly_revenue": revenue,
                "monthly_units_share": unit_share,
                "monthly_revenue_share": revenue_share,
            }
        )

    competitor_source = branded[
        (branded["brand_group"] == "competitor") & (branded["include_in_competitor_total"])
    ]
    if not competitor_source.empty:
        competitor_units = (
            competitor_source["monthly_units"].fillna(0).sum() if "monthly_units" in competitor_source else None
        )
        competitor_revenue = (
            competitor_source["monthly_revenue"].fillna(0).sum() if "monthly_revenue" in competitor_source else None
        )
        rows.append(
            {
                "marketplace": marketplace,
                "brand": "COMPETITORS_TOTAL",
                "brand_group": "competitor_total",
                "priority": "",
                "monthly_units": competitor_units,
                "monthly_revenue": competitor_revenue,
                "monthly_units_share": competitor_source["monthly_units_share"].fillna(0).sum()
                if "monthly_units_share" in competitor_source
                else safe_divide(competitor_units, category_units),
                "monthly_revenue_share": competitor_source["monthly_revenue_share"].fillna(0).sum()
                if "monthly_revenue_share" in competitor_source
                else safe_divide(competitor_revenue, category_revenue),
            }
        )

    if not rows and not product_branded.empty:
        plaud_products = product_branded[product_branded["brand_group"] == "plaud"]
        if not plaud_products.empty:
            rows.append(
                {
                    "marketplace": marketplace,
                    "brand": "PLAUD",
                    "brand_group": "plaud",
                    "priority": "",
                    "monthly_units": plaud_products["monthly_units"].fillna(0).sum(),
                    "monthly_revenue": plaud_products["monthly_revenue"].fillna(0).sum(),
                    "monthly_units_share": safe_divide(
                        plaud_products["monthly_units"].fillna(0).sum(), category_units
                    ),
                    "monthly_revenue_share": safe_divide(
                        plaud_products["monthly_revenue"].fillna(0).sum(), category_revenue
                    ),
                }
            )

    return pd.DataFrame(rows)


def compute_ai_competitors(product_df: pd.DataFrame, marketplace: str, config: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    products = add_standard_brand_columns(product_df, config, marketplace)
    classified = products.copy()
    matches = classified["product_title"].map(lambda title: classify_title(title, marketplace, config))
    classified["is_ai_product"] = matches.map(lambda item: item[0])
    classified["ai_matched_keywords"] = matches.map(lambda item: ", ".join(item[1]))

    ai_competitors = classified[(classified["is_ai_product"]) & (classified["brand_group"] != "plaud")].copy()
    category_units = classified["monthly_units"].fillna(0).sum()
    category_revenue = classified["monthly_revenue"].fillna(0).sum()
    ai_units = ai_competitors["monthly_units"].fillna(0).sum()
    ai_revenue = ai_competitors["monthly_revenue"].fillna(0).sum()

    summary = pd.DataFrame(
        [
            {
                "marketplace": marketplace,
                "category_units": category_units,
                "category_revenue": category_revenue,
                "ai_competitor_asin_count": int(ai_competitors["asin"].nunique()),
                "ai_competitor_units": ai_units,
                "ai_competitor_revenue": ai_revenue,
                "ai_units_share": safe_divide(ai_units, category_units),
                "ai_revenue_share": safe_divide(ai_revenue, category_revenue),
            }
        ]
    )

    detail_cols = [
        "marketplace",
        "asin",
        "brand_name",
        "standard_brand",
        "product_title",
        "monthly_units",
        "monthly_revenue",
        "ai_matched_keywords",
    ]
    ai_competitors["marketplace"] = marketplace
    for col in detail_cols:
        if col not in ai_competitors.columns:
            ai_competitors[col] = ""
    return summary, ai_competitors[detail_cols]


def add_week_over_week(
    current: pd.DataFrame,
    previous: pd.DataFrame | None,
    key_cols: list[str],
    value_cols: list[str],
) -> pd.DataFrame:
    if previous is None or previous.empty or current.empty:
        result = current.copy()
        for col in value_cols:
            result[f"prev_{col}"] = None
            result[f"{col}_delta"] = None
            result[f"{col}_wow"] = None
        result["trend_status"] = "no_baseline"
        return result

    prev_cols = key_cols + value_cols
    previous_small = previous[prev_cols].rename(columns={col: f"prev_{col}" for col in value_cols})
    result = current.merge(previous_small, on=key_cols, how="left")
    trend_parts = []
    for col in value_cols:
        prev_col = f"prev_{col}"
        delta_col = f"{col}_delta"
        wow_col = f"{col}_wow"
        result[delta_col] = result[col] - result[prev_col]
        result[wow_col] = result[delta_col] / result[prev_col].replace({0: pd.NA})
        trend_parts.append(delta_col)
    result["trend_status"] = result[trend_parts].apply(_trend_label, axis=1)
    return result


def _trend_label(row: pd.Series) -> str:
    values = [value for value in row.tolist() if pd.notna(value)]
    if not values:
        return "no_baseline"
    max_abs = max(abs(float(value)) for value in values)
    if max_abs < 0.000001:
        return "flat"
    return "up" if sum(values) > 0 else "down"
