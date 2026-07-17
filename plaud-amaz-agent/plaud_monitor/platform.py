from __future__ import annotations

import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from .config import load_config
from .excel_parser import parse_report
from .brand import add_standard_brand_columns
from .metrics import compute_ai_competitors, compute_brand_share
from .reporting import write_excel_report, write_markdown_report


DEFAULT_DB_PATH = Path("data/db.sqlite")
DEFAULT_UPLOAD_DIR = Path("data/uploads")
DEFAULT_REPORT_DIR = Path("outputs/reports")


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> bool:
        result = super().__exit__(exc_type, exc_value, traceback)
        self.close()
        return result


@dataclass
class ProcessedRun:
    run_id: int
    week_id: str
    marketplace: str
    upload_path: Path
    report_path: Path
    excel_report_path: Path
    status: str
    error: str = ""


def utcnow_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def connect(db_path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, factory=ClosingConnection)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str | Path = DEFAULT_DB_PATH) -> None:
    with connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS uploaded_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                week_id TEXT NOT NULL,
                marketplace TEXT NOT NULL,
                original_filename TEXT NOT NULL,
                stored_path TEXT NOT NULL,
                uploaded_at TEXT NOT NULL,
                status TEXT NOT NULL,
                warnings TEXT,
                error TEXT,
                note TEXT,
                report_path TEXT,
                excel_report_path TEXT
            )
            """
        )
        ensure_column(conn, "uploaded_reports", "excel_report_path", "TEXT")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS brand_metrics (
                run_id INTEGER NOT NULL,
                marketplace TEXT,
                brand TEXT,
                brand_group TEXT,
                priority TEXT,
                monthly_units REAL,
                monthly_revenue REAL,
                monthly_units_share REAL,
                monthly_revenue_share REAL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ai_summary (
                run_id INTEGER NOT NULL,
                marketplace TEXT,
                category_units REAL,
                category_revenue REAL,
                ai_competitor_asin_count INTEGER,
                ai_competitor_units REAL,
                ai_competitor_revenue REAL,
                ai_units_share REAL,
                ai_revenue_share REAL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ai_detail (
                run_id INTEGER NOT NULL,
                marketplace TEXT,
                asin TEXT,
                brand_name TEXT,
                standard_brand TEXT,
                product_title TEXT,
                monthly_units REAL,
                monthly_revenue REAL,
                ai_matched_keywords TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS product_metrics (
                run_id INTEGER NOT NULL,
                marketplace TEXT,
                asin TEXT,
                brand_name TEXT,
                standard_brand TEXT,
                product_title TEXT,
                bsr_rank REAL,
                monthly_units REAL,
                monthly_revenue REAL,
                price REAL,
                category_path TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS mcp_asin_keyword_intel (
                run_id INTEGER NOT NULL,
                week_id TEXT,
                marketplace TEXT,
                asin TEXT,
                brand TEXT,
                product_title TEXT,
                source_type TEXT,
                keyword TEXT,
                related_keyword TEXT,
                keyword_type TEXT,
                conversion_type TEXT,
                searches REAL,
                purchases REAL,
                purchase_rate REAL,
                traffic_percentage REAL,
                rank_position REAL,
                ad_position REAL,
                bid REAL,
                products REAL,
                supply_demand_ratio REAL,
                source_status TEXT,
                source_error TEXT,
                raw_json TEXT,
                fetched_at TEXT NOT NULL
            )
            """
        )
        conn.commit()


def create_upload_record(
    conn: sqlite3.Connection,
    week_id: str,
    marketplace: str,
    original_filename: str,
    stored_path: Path,
    note: str = "",
) -> int:
    cur = conn.execute(
        """
        INSERT INTO uploaded_reports
            (week_id, marketplace, original_filename, stored_path, uploaded_at, status, warnings, error, note, report_path, excel_report_path)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            week_id,
            marketplace,
            original_filename,
            str(stored_path),
            utcnow_iso(),
            "uploaded",
            "",
            "",
            note,
            "",
            "",
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def update_run_status(
    conn: sqlite3.Connection,
    run_id: int,
    status: str,
    warnings: str = "",
    error: str = "",
    report_path: str = "",
    excel_report_path: str = "",
) -> None:
    conn.execute(
        """
        UPDATE uploaded_reports
        SET status = ?, warnings = ?, error = ?, report_path = ?, excel_report_path = ?
        WHERE id = ?
        """,
        (status, warnings, error, report_path, excel_report_path, run_id),
    )
    conn.commit()


def ensure_column(conn: sqlite3.Connection, table: str, column: str, column_type: str) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")
        conn.commit()


def save_uploaded_file(
    source_path: str | Path,
    week_id: str,
    marketplace: str,
    original_filename: str | None = None,
    upload_dir: str | Path = DEFAULT_UPLOAD_DIR,
) -> Path:
    source = Path(source_path)
    filename = safe_filename(original_filename or source.name)
    target_dir = Path(upload_dir) / week_id / marketplace
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / filename
    if target.exists():
        stem = target.stem
        suffix = target.suffix
        target = target_dir / f"{stem}_{datetime.now().strftime('%Y%m%d%H%M%S')}{suffix}"
    shutil.copy2(source, target)
    return target


def safe_filename(name: str) -> str:
    keep = []
    for char in name:
        if char.isalnum() or char in {".", "-", "_", " ", "(", ")", "来源", "插件"}:
            keep.append(char)
        else:
            keep.append("_")
    filename = "".join(keep).strip()
    return filename or "uploaded_report.xlsx"


def insert_dataframe(conn: sqlite3.Connection, table: str, run_id: int, df: pd.DataFrame) -> None:
    if df.empty:
        return
    prepared = df.copy()
    prepared.insert(0, "run_id", run_id)
    prepared.to_sql(table, conn, if_exists="append", index=False)
    conn.commit()


def prepare_product_metrics(product_df: pd.DataFrame, marketplace: str, config: dict[str, Any]) -> pd.DataFrame:
    if product_df.empty:
        return pd.DataFrame()
    products = add_standard_brand_columns(product_df, config, marketplace).copy()
    products["marketplace"] = marketplace
    column_map = {
        "类目路径": "category_path",
    }
    products = products.rename(columns=column_map)
    required = [
        "marketplace",
        "asin",
        "brand_name",
        "standard_brand",
        "product_title",
        "bsr_rank",
        "monthly_units",
        "monthly_revenue",
        "price",
        "category_path",
    ]
    for col in required:
        if col not in products.columns:
            products[col] = None
    return products[required]


def process_report_file(
    config_path: str | Path,
    source_file: str | Path,
    week_id: str,
    marketplace: str,
    db_path: str | Path = DEFAULT_DB_PATH,
    upload_dir: str | Path = DEFAULT_UPLOAD_DIR,
    report_dir: str | Path = DEFAULT_REPORT_DIR,
    original_filename: str | None = None,
    note: str = "",
) -> ProcessedRun:
    init_db(db_path)
    config = load_config(config_path)
    marketplace = marketplace.upper()
    upload_path = save_uploaded_file(source_file, week_id, marketplace, original_filename, upload_dir)

    with connect(db_path) as conn:
        run_id = create_upload_record(conn, week_id, marketplace, original_filename or Path(source_file).name, upload_path, note)
        try:
            parsed = parse_report(upload_path, marketplace, config)
            brand_share = compute_brand_share(parsed.brand_df, parsed.product_df, marketplace, config)
            ai_summary, ai_detail = compute_ai_competitors(parsed.product_df, marketplace, config)
            product_metrics = prepare_product_metrics(parsed.product_df, marketplace, config)

            insert_dataframe(conn, "brand_metrics", run_id, brand_share)
            insert_dataframe(conn, "ai_summary", run_id, ai_summary)
            insert_dataframe(conn, "ai_detail", run_id, ai_detail)
            insert_dataframe(conn, "product_metrics", run_id, product_metrics)

            report_path = Path(report_dir) / week_id / marketplace / f"report_run_{run_id}.md"
            excel_report_path = Path(report_dir) / week_id / marketplace / f"report_run_{run_id}.xlsx"
            run_log = [
                {
                    "marketplace": marketplace,
                    "status": "ok",
                    "source_file": str(upload_path),
                    "warnings": "; ".join(parsed.warnings),
                    "error": "",
                }
            ]
            write_markdown_report(report_path, week_id, brand_share, ai_summary, ai_detail, run_log)
            write_excel_report(excel_report_path, week_id, brand_share, ai_summary, ai_detail, run_log)
            update_run_status(
                conn,
                run_id,
                "ok",
                "; ".join(parsed.warnings),
                "",
                str(report_path),
                str(excel_report_path),
            )
            return ProcessedRun(run_id, week_id, marketplace, upload_path, report_path, excel_report_path, "ok")
        except Exception as exc:  # noqa: BLE001 - operators need the failure in the UI.
            update_run_status(conn, run_id, "error", "", str(exc), "")
            return ProcessedRun(run_id, week_id, marketplace, upload_path, Path(), Path(), "error", str(exc))


def latest_runs(db_path: str | Path = DEFAULT_DB_PATH, limit: int = 20) -> list[dict[str, Any]]:
    init_db(db_path)
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT * FROM uploaded_reports
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_run(db_path: str | Path, run_id: int) -> dict[str, Any] | None:
    init_db(db_path)
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM uploaded_reports WHERE id = ?", (run_id,)).fetchone()
    return dict(row) if row else None


def read_table_for_run(db_path: str | Path, table: str, run_id: int) -> pd.DataFrame:
    init_db(db_path)
    with connect(db_path) as conn:
        return pd.read_sql_query(f"SELECT * FROM {table} WHERE run_id = ?", conn, params=(run_id,))


def ensure_excel_report_for_run(
    db_path: str | Path,
    run_id: int,
    report_dir: str | Path = DEFAULT_REPORT_DIR,
) -> Path | None:
    init_db(db_path)
    run = get_run(db_path, run_id)
    if not run or run.get("status") != "ok":
        return None
    existing = run.get("excel_report_path")
    if existing and Path(existing).exists():
        return Path(existing)

    brand = read_table_for_run(db_path, "brand_metrics", run_id)
    ai_summary = read_table_for_run(db_path, "ai_summary", run_id)
    ai_detail = read_table_for_run(db_path, "ai_detail", run_id)
    run_log = [
        {
            "marketplace": run.get("marketplace", ""),
            "status": run.get("status", ""),
            "source_file": run.get("stored_path", ""),
            "warnings": run.get("warnings", ""),
            "error": run.get("error", ""),
        }
    ]
    path = Path(report_dir) / run["week_id"] / run["marketplace"] / f"report_run_{run_id}.xlsx"
    write_excel_report(path, run["week_id"], brand, ai_summary, ai_detail, run_log)
    with connect(db_path) as conn:
        conn.execute("UPDATE uploaded_reports SET excel_report_path = ? WHERE id = ?", (str(path), run_id))
        conn.commit()
    return path


def latest_successful_run_id(db_path: str | Path = DEFAULT_DB_PATH) -> int | None:
    init_db(db_path)
    with connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT id
            FROM uploaded_reports
            WHERE status = 'ok'
            ORDER BY
                CAST(substr(week_id, 1, 4) AS INTEGER) DESC,
                CAST(substr(week_id, instr(week_id, 'W') + 1) AS INTEGER) DESC,
                id DESC
            LIMIT 1
            """
        ).fetchone()
    return int(row["id"]) if row else None


def aggregate_counts(db_path: str | Path = DEFAULT_DB_PATH) -> dict[str, int]:
    init_db(db_path)
    with connect(db_path) as conn:
        reports = conn.execute("SELECT COUNT(*) AS c FROM uploaded_reports").fetchone()["c"]
        ok = conn.execute("SELECT COUNT(*) AS c FROM uploaded_reports WHERE status = 'ok'").fetchone()["c"]
        errors = conn.execute("SELECT COUNT(*) AS c FROM uploaded_reports WHERE status = 'error'").fetchone()["c"]
    return {"reports": int(reports), "ok": int(ok), "errors": int(errors)}
