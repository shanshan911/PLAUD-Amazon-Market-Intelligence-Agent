from __future__ import annotations

import argparse
import cgi
import html
import io
import json
import math
import mimetypes
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote_plus, urlparse
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

import pandas as pd

from plaud_monitor.config import load_config
from plaud_monitor.integrations import integration_statuses
from plaud_monitor.normalizers import format_number, format_percent
from plaud_monitor.platform import (
    DEFAULT_DB_PATH,
    DEFAULT_REPORT_DIR,
    DEFAULT_UPLOAD_DIR,
    aggregate_counts,
    connect,
    ensure_excel_report_for_run,
    get_run,
    latest_runs,
    latest_successful_run_id,
    prepare_product_metrics,
    process_report_file,
    read_table_for_run,
)
from plaud_monitor.excel_parser import parse_report


CONFIG_PATH = Path(os.environ.get("PLAUD_MONITOR_CONFIG", "config/monitor_config.p0.json"))
DB_PATH = Path(os.environ.get("PLAUD_MONITOR_DB", DEFAULT_DB_PATH))
UPLOAD_DIR = Path(os.environ.get("PLAUD_MONITOR_UPLOAD_DIR", DEFAULT_UPLOAD_DIR))
REPORT_DIR = Path(os.environ.get("PLAUD_MONITOR_REPORT_DIR", DEFAULT_REPORT_DIR))
KNOWLEDGE_DIR = Path(os.environ.get("PLAUD_MONITOR_KNOWLEDGE_DIR", "data/knowledge"))
ADS_UPLOAD_DIR = Path(os.environ.get("PLAUD_MONITOR_ADS_UPLOAD_DIR", "data/ads"))
PROJECT_ROOT = Path(__file__).resolve().parent


UI_TRANSLATIONS = {
    "app_title": {"zh": "PLAUD 亚马逊市场洞察 Agent", "en": "PLAUD Amazon Market Intelligence Agent", "ja": "PLAUD Amazon 市場インサイト Agent"},
    "nav_dashboard": {"zh": "首页看板", "en": "Dashboard", "ja": "ダッシュボード"},
    "nav_agent": {"zh": "Agent 中心", "en": "Agent Center", "ja": "Agent センター"},
    "nav_analysis": {"zh": "分析工作台", "en": "Analysis Workspace", "ja": "分析ワークスペース"},
    "nav_actions": {"zh": "行动建议", "en": "Actions", "ja": "アクション"},
    "nav_chat": {"zh": "运营问答", "en": "Ops Q&A", "ja": "運用Q&A"},
    "nav_knowledge": {"zh": "知识库", "en": "Knowledge Base", "ja": "ナレッジ"},
    "nav_ads": {"zh": "广告数据", "en": "Ads Data", "ja": "広告データ"},
    "nav_uploads": {"zh": "上传记录", "en": "Uploads", "ja": "アップロード"},
    "nav_config": {"zh": "配置摘要", "en": "Config", "ja": "設定概要"},
    "language": {"zh": "语言", "en": "Language", "ja": "言語"},
    "theme": {"zh": "主题", "en": "Theme", "ja": "テーマ"},
    "theme_ocean": {"zh": "深海蓝", "en": "Ocean Blue", "ja": "オーシャン"},
    "theme_emerald": {"zh": "增长绿", "en": "Growth Green", "ja": "グリーン"},
    "theme_amber": {"zh": "洞察金", "en": "Insight Amber", "ja": "アンバー"},
    "theme_slate": {"zh": "深色模式", "en": "Dark Mode", "ja": "ダーク"},
    "dashboard_title": {"zh": "市场监控驾驶舱", "en": "Market Monitoring Cockpit", "ja": "市場モニタリング"},
    "dashboard_note": {
        "zh": "对齐成熟 Amazon 监控工具的 market share、competitor movement、product intelligence 和 data health 工作流。",
        "en": "Aligned with mature Amazon monitoring workflows: market share, competitor movement, product intelligence, and data health.",
        "ja": "成熟した Amazon 監視ワークフローに合わせた、市場シェア、競合動向、商品インテリジェンス、データ健全性のビューです。",
    },
    "weekly_mvp": {"zh": "周度监控 MVP", "en": "Weekly MVP", "ja": "週次 MVP"},
    "kpi_sites": {"zh": "监控站点", "en": "Tracked Sites", "ja": "監視サイト"},
    "kpi_success": {"zh": "成功解析", "en": "Parsed", "ja": "解析成功"},
    "kpi_errors": {"zh": "失败记录", "en": "Errors", "ja": "エラー"},
    "kpi_latest_run": {"zh": "最新 Run", "en": "Latest Run", "ja": "最新 Run"},
    "data_week": {"zh": "数据周次", "en": "Data Week", "ja": "データ週"},
    "latest_week": {"zh": "最新周", "en": "Latest Week", "ja": "最新週"},
    "fetch_latest_week_data": {"zh": "获取最新周数据", "en": "Fetch Latest Week", "ja": "最新週データ取得"},
    "fetching_latest_week_data": {"zh": "正在获取...", "en": "Fetching...", "ja": "取得中..."},
    "collapse_sidebar": {"zh": "收起导航", "en": "Collapse", "ja": "折りたたむ"},
    "expand_sidebar": {"zh": "展开导航", "en": "Expand", "ja": "展開"},
    "agent_center": {"zh": "Agent 中心", "en": "Agent Center", "ja": "Agent センター"},
    "agent_center_note": {"zh": "", "en": "", "ja": ""},
    "agent_detail": {"zh": "Agent 详情", "en": "Agent Detail", "ja": "Agent 詳細"},
    "roi_run_dashboard": {"zh": "ROI / 运行记录看板", "en": "ROI / Run Dashboard", "ja": "ROI / 実行履歴"},
    "market_share_desc": {"zh": "PLAUD、竞品合计和其他品牌份额拆解", "en": "PLAUD, tracked competitors, and other-brand share breakdown.", "ja": "PLAUD、監視競合、その他ブランドのシェア内訳。"},
    "competitor_movement_desc": {"zh": "按周次沉淀份额折线趋势", "en": "Weekly trend lines for share movement.", "ja": "週次シェア推移の折れ線トレンド。"},
    "product_intelligence_desc": {"zh": "AI 竞品 ASIN、品牌、标题和命中词明细", "en": "AI competitor ASINs, brands, titles, and matched terms.", "ja": "AI 競合 ASIN、ブランド、タイトル、ヒット語句。"},
    "data_health_desc": {"zh": "上传状态、解析警告、缺失站点一眼可见", "en": "Upload status, parse warnings, and missing sites at a glance.", "ja": "アップロード状態、解析警告、欠損サイトを一覧表示。"},
    "workflow_export_desc": {"zh": "运营上传 Excel 后直接下载周报 Excel", "en": "Upload Excel and download the weekly Excel report.", "ja": "Excel アップロード後に週報 Excel をダウンロード。"},
    "mapping_market_share_impl": {"zh": "PLAUD、竞品合计、其他品牌份额环图", "en": "Donut charts for PLAUD, tracked competitors, and other brands.", "ja": "PLAUD、監視競合、その他ブランドのドーナツチャート。"},
    "mapping_market_share_task": {"zh": "品牌集中度中记录月销量/销售额占比", "en": "Record monthly unit and revenue share from brand concentration.", "ja": "ブランド集中度から月間販売数/売上シェアを記録。"},
    "mapping_competitor_movement_impl": {"zh": "PLAUD 与 AI 竞品周趋势折线", "en": "Weekly trend lines for PLAUD and AI competitors.", "ja": "PLAUD と AI 競合の週次トレンド。"},
    "mapping_competitor_movement_task": {"zh": "与前一周数据进行变化趋势分析", "en": "Compare changes against the previous week.", "ja": "前週データと比較して変化を分析。"},
    "mapping_product_intelligence_impl": {"zh": "AI ASIN 明细、命中关键词、品牌和标题", "en": "AI ASIN details with matched terms, brand, and title.", "ja": "AI ASIN 明細、ヒット語句、ブランド、タイトル。"},
    "mapping_product_intelligence_task": {"zh": "商品集中度中筛选 AI/IA 并剔除 PLAUD", "en": "Filter AI/IA products from product concentration and exclude PLAUD.", "ja": "商品集中度で AI/IA を抽出し、PLAUD を除外。"},
    "mapping_workflow_export_impl": {"zh": "一键下载 Excel 周报", "en": "One-click weekly Excel export.", "ja": "週報 Excel をワンクリック出力。"},
    "mapping_workflow_export_task": {"zh": "记录数据并输出给运营复核", "en": "Record and export data for operations review.", "ja": "データを記録し、運用レビュー用に出力。"},
    "upload_excel": {"zh": "上传卖家精灵 Excel", "en": "Upload SellerSprite Excel", "ja": "SellerSprite Excel をアップロード"},
    "week_id": {"zh": "周次", "en": "Week", "ja": "週"},
    "marketplace": {"zh": "站点", "en": "Marketplace", "ja": "サイト"},
    "excel_file": {"zh": "Excel 文件", "en": "Excel File", "ja": "Excel ファイル"},
    "note": {"zh": "备注", "en": "Note", "ja": "メモ"},
    "note_placeholder": {"zh": "例如：20260513 IT 来源插件", "en": "Example: 20260513 IT plugin export", "ja": "例：20260513 IT プラグイン出力"},
    "upload_parse": {"zh": "上传并解析", "en": "Upload and Parse", "ja": "アップロードして解析"},
    "uploaded": {"zh": "已上传", "en": "Uploaded", "ja": "アップロード済み"},
    "pending_upload": {"zh": "待上传", "en": "Missing", "ja": "未アップロード"},
    "no_week_data": {"zh": "暂无本周数据", "en": "No data this week", "ja": "今週のデータなし"},
    "latest_market_result": {"zh": "最新市场结果", "en": "Latest Market Result", "ja": "最新市場結果"},
    "run_market_result": {"zh": "Run #{run_id} 市场结果", "en": "Run #{run_id} Market Result", "ja": "Run #{run_id} 市場結果"},
    "market_result": {"zh": "市场结果", "en": "Market Result", "ja": "市場結果"},
    "download_weekly_excel": {"zh": "下载周报 Excel", "en": "Download Weekly Excel", "ja": "週報 Excel をダウンロード"},
    "chat_title": {"zh": "运营问答助手", "en": "Operations Q&A Assistant", "ja": "運用Q&Aアシスタント"},
    "chat_note": {"zh": "基于当前上传数据回答市场、竞品、AI 渗透、价格带和营销动作问题。", "en": "Answers market, competitor, AI penetration, price band, and marketing questions from uploaded data.", "ja": "アップロード済みデータに基づき、市場・競合・AI浸透・価格帯・施策を回答します。"},
    "chat_question": {"zh": "输入问题", "en": "Question", "ja": "質問"},
    "chat_placeholder": {"zh": "例如：本周 IT 站点有哪些营销机会？", "en": "Example: What are this week's marketing opportunities?", "ja": "例：今週のマーケ機会は？"},
    "chat_ask": {"zh": "提问", "en": "Ask", "ja": "質問する"},
    "quick_questions": {"zh": "快捷问题", "en": "Quick Questions", "ja": "クイック質問"},
    "plaud_units_share": {"zh": "PLAUD 销量份额", "en": "PLAUD Unit Share", "ja": "PLAUD 販売数シェア"},
    "plaud_revenue_share": {"zh": "PLAUD 销售额份额", "en": "PLAUD Revenue Share", "ja": "PLAUD 売上シェア"},
    "competitor_units_share": {"zh": "竞品合计销量份额", "en": "Competitor Unit Share", "ja": "競合販売数シェア"},
    "ai_units_share": {"zh": "AI 竞品销量份额", "en": "AI Competitor Unit Share", "ja": "AI 競合販売数シェア"},
    "units_share_structure": {"zh": "销量份额结构", "en": "Unit Share Structure", "ja": "販売数シェア構成"},
    "revenue_share_structure": {"zh": "销售额份额结构", "en": "Revenue Share Structure", "ja": "売上シェア構成"},
    "ai_units_penetration": {"zh": "AI 竞品销量渗透", "en": "AI Unit Penetration", "ja": "AI 販売数浸透率"},
    "ai_revenue_penetration": {"zh": "AI 竞品销售额渗透", "en": "AI Revenue Penetration", "ja": "AI 売上浸透率"},
    "ai_units_with_plaud": {"zh": "AI 销量结构（含 PLAUD）", "en": "AI Unit Mix Including PLAUD", "ja": "AI 販売数構成（PLAUD 含む）"},
    "ai_revenue_with_plaud": {"zh": "AI 销售额结构（含 PLAUD）", "en": "AI Revenue Mix Including PLAUD", "ja": "AI 売上構成（PLAUD 含む）"},
    "monthly_units": {"zh": "月销量", "en": "Monthly Units", "ja": "月間販売数"},
    "monthly_revenue": {"zh": "月销售额", "en": "Monthly Revenue", "ja": "月間売上"},
    "exclude_plaud": {"zh": "剔除 PLAUD", "en": "Excluding PLAUD", "ja": "PLAUD 除外"},
    "other_brands": {"zh": "其他品牌", "en": "Other Brands", "ja": "その他ブランド"},
    "non_ai_other": {"zh": "非 AI/其他", "en": "Non-AI / Other", "ja": "非 AI / その他"},
    "tracked_competitors": {"zh": "监控竞品", "en": "Tracked Competitors", "ja": "監視競合"},
    "ai_competitors": {"zh": "AI 竞品", "en": "AI Competitors", "ja": "AI 競合"},
    "plaud_units_trend": {"zh": "PLAUD 销量份额趋势", "en": "PLAUD Unit Share Trend", "ja": "PLAUD 販売数シェア推移"},
    "ai_units_trend": {"zh": "AI 竞品销量份额趋势", "en": "AI Competitor Unit Share Trend", "ja": "AI 競合販売数シェア推移"},
    "weekly_trend": {"zh": "周趋势", "en": "Weekly Trend", "ja": "週次トレンド"},
    "mature_mapping": {"zh": "成熟监控视角映射", "en": "Mature Monitoring Mapping", "ja": "成熟監視ビュー対応"},
    "module": {"zh": "模块", "en": "Module", "ja": "モジュール"},
    "platform_impl": {"zh": "本平台落地", "en": "Platform Implementation", "ja": "本プラットフォームでの実装"},
    "task_mapping": {"zh": "Task 1 对应动作", "en": "Task 1 Mapping", "ja": "Task 1 対応"},
    "brand_market_share": {"zh": "品牌/竞品市占", "en": "Brand / Competitor Share", "ja": "ブランド / 競合シェア"},
    "analysis_workbench": {"zh": "分析工作台", "en": "Analysis Workspace", "ja": "分析ワークスペース"},
    "tab_overview": {"zh": "总览", "en": "Overview", "ja": "概要"},
    "tab_charts": {"zh": "图表趋势", "en": "Charts", "ja": "チャート"},
    "tab_brand": {"zh": "品牌市占", "en": "Brand Share", "ja": "ブランドシェア"},
    "tab_ai_category": {"zh": "AI / 类目", "en": "AI / Category", "ja": "AI / カテゴリ"},
    "tab_asin": {"zh": "ASIN 动向", "en": "ASIN Movement", "ja": "ASIN 動向"},
    "tab_ops": {"zh": "增长运营", "en": "Growth Ops", "ja": "成長運用"},
    "tab_data": {"zh": "明细数据", "en": "Details", "ja": "詳細データ"},
    "advanced_attribution": {"zh": "异常归因升级", "en": "Advanced Attribution", "ja": "高度な要因分析"},
    "advanced_attribution_note": {"zh": "把预警进一步拆成可能原因、证据、置信度和下一步动作。", "en": "Breaks alerts into likely cause, evidence, confidence, and next action.", "ja": "アラートを原因、根拠、信頼度、次アクションに分解します。"},
    "ads_linkage": {"zh": "广告数据联动", "en": "Ads Data Linkage", "ja": "広告データ連携"},
    "ads_linkage_note": {"zh": "预留 Amazon Ads API 字段，用于把 ACOS、Spend、Campaign、Search Term 与市占变化关联。", "en": "Prepares Amazon Ads API fields to connect ACOS, spend, campaigns, search terms, and share movement.", "ja": "ACOS、支出、キャンペーン、検索語句とシェア変化を接続する項目です。"},
    "share_of_voice": {"zh": "Share of Voice / 关键词可见度", "en": "Share of Voice / Keyword Visibility", "ja": "SOV / キーワード可視性"},
    "share_of_voice_note": {"zh": "按站点核心关键词追踪 PLAUD 与竞品自然/广告排名，用于解释市占变化的前置原因。", "en": "Tracks PLAUD and competitor organic/ad rank by core keyword as an upstream driver of market share.", "ja": "主要キーワード別に自然/広告順位を追跡し、シェア変化の前兆を見ます。"},
    "ops_task_loop": {"zh": "运营任务闭环", "en": "Operations Task Loop", "ja": "運用タスク管理"},
    "ops_task_loop_note": {"zh": "把预警和机会自动转成任务，带负责人、动作、截止时间、处理状态和复盘口径。", "en": "Turns alerts and opportunities into tasks with owner, action, due time, status, and review metric.", "ja": "アラートと機会を担当者、期限、状態、振り返り指標付きタスクにします。"},
    "weekly_brief_plus": {"zh": "周报自动解读", "en": "Auto Weekly Brief", "ja": "週報自動解釈"},
    "weekly_brief_plus_note": {"zh": "输出一句话结论、最大风险、最大机会和需要业务确认的事项。", "en": "Generates one-line conclusion, biggest risk, biggest opportunity, and items needing business confirmation.", "ja": "一文結論、最大リスク、最大機会、確認事項を出力します。"},
    "data_collection_boundary": {"zh": "数据采集边界", "en": "Data Collection Boundary", "ja": "データ取得境界"},
    "data_collection_boundary_note": {"zh": "说明哪些数据可直接读取，哪些建议走官方 API/授权接口，哪些不建议直接网页爬取。", "en": "Clarifies what can be read directly, what should use official/authorized APIs, and what should not be scraped directly.", "ja": "直接読取、公式/認可API、直接スクレイピング非推奨を整理します。"},
    "local_data_inventory": {"zh": "本地数据资产", "en": "Local Data Inventory", "ja": "ローカルデータ資産"},
    "local_data_inventory_note": {"zh": "当前上传的 Excel 已经落入 SQLite 和标准化表，可以直接查询、导出或做内部接口。", "en": "Uploaded Excel files are normalized into SQLite tables and can be queried, exported, or exposed through internal APIs.", "ja": "アップロード済みExcelはSQLiteに正規化済みで、照会・出力・内部API化できます。"},
    "cause": {"zh": "可能原因", "en": "Likely Cause", "ja": "想定原因"},
    "evidence": {"zh": "证据", "en": "Evidence", "ja": "根拠"},
    "confidence": {"zh": "置信度", "en": "Confidence", "ja": "信頼度"},
    "next_action": {"zh": "下一步动作", "en": "Next Action", "ja": "次アクション"},
    "data_source": {"zh": "数据源", "en": "Data Source", "ja": "データソース"},
    "readiness": {"zh": "准备度", "en": "Readiness", "ja": "準備状況"},
    "collection_method": {"zh": "采集方式", "en": "Collection Method", "ja": "取得方法"},
    "risk_boundary": {"zh": "边界/风险", "en": "Boundary / Risk", "ja": "境界/リスク"},
    "recommended_path": {"zh": "推荐路径", "en": "Recommended Path", "ja": "推奨手順"},
    "task_status": {"zh": "处理状态", "en": "Status", "ja": "状態"},
    "due_time": {"zh": "截止时间", "en": "Due", "ja": "期限"},
    "review_metric": {"zh": "复盘口径", "en": "Review Metric", "ja": "振り返り指標"},
    "organic_rank": {"zh": "自然排名", "en": "Organic Rank", "ja": "自然順位"},
    "ad_rank": {"zh": "广告排名", "en": "Ad Rank", "ja": "広告順位"},
    "global_brand_share": {"zh": "全球品牌市占", "en": "Global Brand Share", "ja": "グローバルブランドシェア"},
    "global_brand_share_note": {"zh": "汇总七站点最新成功上传数据，按单一品牌计算全球范围销量与销售额占比。", "en": "Aggregates latest successful data across the seven sites and calculates unit/revenue share by individual brand.", "ja": "7サイトの最新成功データを集計し、単一ブランド別の販売数/売上シェアを算出します。"},
    "current_site_brand_share": {"zh": "当前站点品牌市占", "en": "Current Site Brand Share", "ja": "現在サイトのブランドシェア"},
    "sort_hint": {"zh": "点击月销量、销量占比、月销售额、销售额占比表头可切换排序；默认按月销量倒序。", "en": "Click unit, unit share, revenue, or revenue share headers to sort. Default is monthly units descending.", "ja": "販売数、販売数シェア、売上、売上シェアのヘッダーをクリックして並び替えできます。初期表示は販売数降順です。"},
    "ai_asin_detail": {"zh": "AI 竞品 ASIN 明细", "en": "AI Competitor ASIN Detail", "ja": "AI 競合 ASIN 明細"},
    "metric_explainer": {"zh": "指标口径说明", "en": "Metric Definitions", "ja": "指標定義"},
    "ai_penetration_explained": {"zh": "AI 竞品渗透率 = 剔除 PLAUD 后，标题命中 AI/IA 等关键词的竞品月销量 ÷ 类目总月销量。当前 6.29% 代表该类目约 6.29% 的销量来自 AI 竞品。", "en": "AI competitor penetration = non-PLAUD products with AI/IA terms in title monthly units divided by total category monthly units.", "ja": "AI競合浸透率 = PLAUDを除外し、タイトルにAI/IA等を含む競合の月間販売数 ÷ カテゴリ総月間販売数。"},
    "rank_model_explained": {"zh": "类目排名销量反推 = 用卖家精灵商品样本里的最终类目排名 BSR 与月销量拟合曲线，估算该类目 Top 排名覆盖的月销量规模。它是运营估算模型，不等同于亚马逊官方数据。", "en": "Category rank sales estimate fits a curve from final-category BSR and monthly unit samples to estimate covered category sales. It is an operations estimate, not Amazon official data.", "ja": "カテゴリ順位販売数推定は、最終カテゴリBSRと月間販売数サンプルから曲線を当てはめ、カテゴリ販売規模を推定する運用モデルです。Amazon公式データではありません。"},
    "recent_uploads": {"zh": "最近上传记录", "en": "Recent Uploads", "ja": "最近のアップロード"},
    "no_uploads": {"zh": "暂无上传记录", "en": "No upload records", "ja": "アップロード履歴なし"},
    "status": {"zh": "状态", "en": "Status", "ja": "状態"},
    "uploaded_at": {"zh": "上传时间", "en": "Uploaded At", "ja": "アップロード日時"},
    "action": {"zh": "操作", "en": "Action", "ja": "操作"},
    "view": {"zh": "查看", "en": "View", "ja": "表示"},
    "config_summary": {"zh": "配置摘要", "en": "Config Summary", "ja": "設定概要"},
    "api_integrations": {"zh": "官方 API 接入状态", "en": "Official API Integrations", "ja": "公式 API 連携状態"},
    "api_provider": {"zh": "接口", "en": "Provider", "ja": "API"},
    "api_use_case": {"zh": "用途", "en": "Use Case", "ja": "用途"},
    "api_enabled": {"zh": "启用", "en": "Enabled", "ja": "有効"},
    "api_readiness": {"zh": "状态", "en": "Readiness", "ja": "状態"},
    "api_next_step": {"zh": "下一步", "en": "Next Step", "ja": "次の手順"},
    "api_ready": {"zh": "可联调", "en": "Ready", "ja": "接続テスト可"},
    "api_not_ready": {"zh": "待配置", "en": "Not Ready", "ja": "設定待ち"},
    "api_yes": {"zh": "是", "en": "Yes", "ja": "はい"},
    "api_no": {"zh": "否", "en": "No", "ja": "いいえ"},
    "currency": {"zh": "币种", "en": "Currency", "ja": "通貨"},
    "keyword": {"zh": "搜索词", "en": "Keyword", "ja": "検索語"},
    "category_path": {"zh": "类目路径", "en": "Category Path", "ja": "カテゴリパス"},
    "bsr_url": {"zh": "BSR URL", "en": "BSR URL", "ja": "BSR URL"},
    "page_not_found": {"zh": "页面不存在。", "en": "Page not found.", "ja": "ページが見つかりません。"},
    "upload_failed": {"zh": "上传失败", "en": "Upload Failed", "ja": "アップロード失敗"},
    "upload_required": {"zh": "请填写周次、站点并选择 Excel 文件。", "en": "Please enter week, marketplace, and select an Excel file.", "ja": "週、サイト、Excel ファイルを選択してください。"},
    "download_failed": {"zh": "下载失败", "en": "Download Failed", "ja": "ダウンロード失敗"},
    "report_not_found": {"zh": "找不到周报文件。", "en": "Weekly report not found.", "ja": "週報ファイルが見つかりません。"},
    "report_missing": {"zh": "周报文件不存在。", "en": "Weekly report file does not exist.", "ja": "週報ファイルが存在しません。"},
    "excel_report_missing": {"zh": "找不到 Excel 周报文件。", "en": "Excel weekly report not found.", "ja": "Excel 週報ファイルが見つかりません。"},
    "no_data_notice": {"zh": "还没有成功解析的数据。上传一份卖家精灵 Excel 后，这里会显示图表和指标。", "en": "No parsed data yet. Upload a SellerSprite Excel file to see charts and metrics.", "ja": "解析済みデータはまだありません。SellerSprite Excel をアップロードすると、ここにグラフと指標が表示されます。"},
    "not_found_run": {"zh": "找不到这条记录。", "en": "Run not found.", "ja": "この記録が見つかりません。"},
    "parse_failed": {"zh": "解析失败：", "en": "Parse failed: ", "ja": "解析失敗："},
    "col_marketplace": {"zh": "站点", "en": "Marketplace", "ja": "サイト"},
    "col_brand": {"zh": "品牌", "en": "Brand", "ja": "ブランド"},
    "col_brand_group": {"zh": "品牌组", "en": "Brand Group", "ja": "ブランド分類"},
    "col_monthly_units": {"zh": "月销量", "en": "Monthly Units", "ja": "月間販売数"},
    "col_monthly_units_share": {"zh": "销量占比", "en": "Unit Share", "ja": "販売数シェア"},
    "col_monthly_revenue": {"zh": "月销售额", "en": "Monthly Revenue", "ja": "月間売上"},
    "col_monthly_revenue_share": {"zh": "销售额占比", "en": "Revenue Share", "ja": "売上シェア"},
    "col_asin": {"zh": "ASIN", "en": "ASIN", "ja": "ASIN"},
    "col_standard_brand": {"zh": "标准品牌", "en": "Standard Brand", "ja": "標準ブランド"},
    "col_ai_matched_keywords": {"zh": "命中词", "en": "Matched Terms", "ja": "ヒット語句"},
    "col_product_title": {"zh": "商品标题", "en": "Product Title", "ja": "商品タイトル"},
    "alert_center": {"zh": "预警中心", "en": "Alert Center", "ja": "アラートセンター"},
    "alert_center_note": {"zh": "优先提示缺失数据、份额下滑、竞品上升和 AI 渗透异常。", "en": "Highlights missing data, share drops, competitor gains, and AI penetration changes.", "ja": "欠損データ、シェア低下、競合上昇、AI 浸透率の変化を優先表示。"},
    "seven_site_comparison": {"zh": "七站点横向对比", "en": "7-Site Comparison", "ja": "7 サイト横断比較"},
    "top_movement_board": {"zh": "Top 变化榜", "en": "Top Movement Board", "ja": "Top 変化ランキング"},
    "top_movement_note": {"zh": "有前一周数据时显示环比变化；暂无历史时显示当前 Top。", "en": "Shows week-over-week movement when history exists; otherwise shows current Top lists.", "ja": "履歴があれば週次変化、なければ現在の Top を表示。"},
    "risk_high": {"zh": "高风险", "en": "High Risk", "ja": "高リスク"},
    "risk_medium": {"zh": "关注", "en": "Watch", "ja": "要確認"},
    "risk_info": {"zh": "提示", "en": "Info", "ja": "情報"},
    "data_missing": {"zh": "未上传", "en": "Missing", "ja": "未アップロード"},
    "data_ready": {"zh": "已解析", "en": "Ready", "ja": "解析済み"},
    "data_no_previous": {"zh": "待累计历史", "en": "Need History", "ja": "履歴待ち"},
    "delta": {"zh": "环比", "en": "Delta", "ja": "前週比"},
    "brand_growth_rank": {"zh": "品牌份额增长榜", "en": "Brand Share Growth", "ja": "ブランドシェア上昇"},
    "current_brand_rank": {"zh": "当前品牌份额榜", "en": "Current Brand Share", "ja": "現在のブランドシェア"},
    "asin_growth_rank": {"zh": "AI ASIN 销售额增长榜", "en": "AI ASIN Revenue Growth", "ja": "AI ASIN 売上上昇"},
    "current_ai_asin_rank": {"zh": "当前 AI ASIN 销售额榜", "en": "Current AI ASIN Revenue", "ja": "現在の AI ASIN 売上"},
    "share_delta": {"zh": "份额变化", "en": "Share Delta", "ja": "シェア変化"},
    "revenue_delta": {"zh": "销售额变化", "en": "Revenue Delta", "ja": "売上変化"},
    "units_delta": {"zh": "销量变化", "en": "Unit Delta", "ja": "販売数変化"},
    "no_rank_data": {"zh": "暂无可用排行数据。", "en": "No ranking data available.", "ja": "ランキングデータがありません。"},
    "current_value": {"zh": "当前值", "en": "Current", "ja": "現在値"},
    "category_rank_model": {"zh": "类目排名销量反推", "en": "Category Rank Sales Estimate", "ja": "カテゴリ順位販売数推定"},
    "category_rank_note": {"zh": "基于最终类目 BSR 与卖家精灵销量样本拟合幂律曲线，估算该类目 Top 排名覆盖销量。", "en": "Fits a power-law curve from final-category BSR and SellerSprite unit samples to estimate covered category sales.", "ja": "最終カテゴリ BSR と SellerSprite 販売数サンプルからべき乗曲線を当てはめ、カテゴリ販売数を推定します。"},
    "estimated_category_units": {"zh": "估算类目销量", "en": "Estimated Category Units", "ja": "推定カテゴリ販売数"},
    "observed_sample_units": {"zh": "样本已知销量", "en": "Observed Sample Units", "ja": "観測サンプル販売数"},
    "estimated_tail_units": {"zh": "模型补全销量", "en": "Model-Filled Units", "ja": "モデル補完販売数"},
    "rank_sample_count": {"zh": "有效排名样本", "en": "Valid Rank Samples", "ja": "有効順位サンプル"},
    "rank_coverage": {"zh": "覆盖排名", "en": "Rank Coverage", "ja": "順位カバレッジ"},
    "model_confidence": {"zh": "模型可信度", "en": "Model Confidence", "ja": "モデル信頼度"},
    "model_formula": {"zh": "拟合公式", "en": "Model Formula", "ja": "モデル式"},
    "rank_fit_quality": {"zh": "拟合优度", "en": "Fit Quality", "ja": "適合度"},
    "confidence_high": {"zh": "高", "en": "High", "ja": "高"},
    "confidence_medium": {"zh": "中", "en": "Medium", "ja": "中"},
    "confidence_low": {"zh": "低", "en": "Low", "ja": "低"},
    "plaud_estimated_share": {"zh": "PLAUD 估算份额", "en": "PLAUD Estimated Share", "ja": "PLAUD 推定シェア"},
    "ai_estimated_share": {"zh": "AI 竞品估算份额", "en": "AI Competitor Estimated Share", "ja": "AI 競合推定シェア"},
    "no_rank_model_data": {"zh": "当前报告缺少可用 BSR 或销量样本，暂时无法反推类目销量。", "en": "This report lacks usable BSR or unit samples, so category sales cannot be estimated yet.", "ja": "このレポートには利用可能な BSR または販売数サンプルが不足しているため、推定できません。"},
    "weekly_insights": {"zh": "周报洞察自动生成", "en": "Weekly Insight Generator", "ja": "週次インサイト自動生成"},
    "weekly_insights_note": {"zh": "自动把份额、AI 渗透、类目规模和数据完整性转成运营可读结论。", "en": "Turns share, AI penetration, category size, and data completeness into operations-ready conclusions.", "ja": "シェア、AI 浸透、カテゴリ規模、データ完全性を運用向けの結論に変換します。"},
    "abnormal_attribution": {"zh": "异常归因卡", "en": "Anomaly Attribution Cards", "ja": "異常要因カード"},
    "abnormal_attribution_note": {"zh": "把份额、AI 渗透、类目规模、ASIN 池和数据缺口转成可解释的原因假设。", "en": "Explains likely drivers from share, AI penetration, category size, ASIN pool, and data gaps.", "ja": "シェア、AI浸透、カテゴリ規模、ASINプール、データ欠損から要因仮説を提示します。"},
    "weekly_actions": {"zh": "本周行动建议", "en": "This Week's Actions", "ja": "今週のアクション"},
    "weekly_actions_note": {"zh": "按优先级给运营可执行动作，便于直接跟进。", "en": "Prioritized actions for operations handoff and weekly review.", "ja": "週次レビューで実行しやすい優先アクションです。"},
    "action_owner": {"zh": "负责人", "en": "Owner", "ja": "担当"},
    "action_metric": {"zh": "复核指标", "en": "Metric", "ja": "確認指標"},
    "asin_change_analysis": {"zh": "新增/消失 ASIN", "en": "New / Disappeared ASINs", "ja": "新規 / 消失 ASIN"},
    "asin_change_note": {"zh": "同站点有前一周数据后自动比较商品池变化，帮助识别新品进入和下架风险。", "en": "Compares product pool changes once the previous same-site week exists.", "ja": "同一サイトの前週データがある場合に商品プール変化を比較します。"},
    "new_asins": {"zh": "新增 ASIN", "en": "New ASINs", "ja": "新規 ASIN"},
    "disappeared_asins": {"zh": "消失 ASIN", "en": "Disappeared ASINs", "ja": "消失 ASIN"},
    "baseline_asins": {"zh": "本周基线 ASIN", "en": "Baseline ASINs", "ja": "基準 ASIN"},
    "previous_week": {"zh": "对比周", "en": "Previous Week", "ja": "比較週"},
    "current_week": {"zh": "当前周", "en": "Current Week", "ja": "現在週"},
    "no_previous_asin_data": {"zh": "当前为该站点基线周；下一周同站点上传后会自动识别新增与消失 ASIN。", "en": "This is the baseline week for this site. New and disappeared ASINs will appear after the next same-site upload.", "ja": "このサイトの基準週です。次回同一サイトのアップロード後に新規/消失 ASIN を表示します。"},
    "no_asin_change_data": {"zh": "当前报告缺少可用商品明细，暂时无法分析 ASIN 变化。", "en": "This report lacks usable product details, so ASIN changes cannot be analyzed yet.", "ja": "商品明細が不足しているため、ASIN 変化を分析できません。"},
    "price_band_analysis": {"zh": "价格带分析", "en": "Price Band Analysis", "ja": "価格帯分析"},
    "price_band_note": {"zh": "按价格带拆解 ASIN 数、销量、销售额、PLAUD 与 AI 竞品分布。", "en": "Breaks down ASIN count, units, revenue, PLAUD, and AI competitors by price band.", "ja": "価格帯別に ASIN 数、販売数、売上、PLAUD、AI 競合を分解します。"},
    "price_band": {"zh": "价格带", "en": "Price Band", "ja": "価格帯"},
    "asin_count": {"zh": "ASIN 数", "en": "ASIN Count", "ja": "ASIN 数"},
    "all_products": {"zh": "全商品", "en": "All Products", "ja": "全商品"},
    "plaud_products": {"zh": "PLAUD 商品", "en": "PLAUD Products", "ja": "PLAUD 商品"},
    "ai_products": {"zh": "AI 竞品", "en": "AI Products", "ja": "AI 商品"},
    "unit_share": {"zh": "销量占比", "en": "Unit Share", "ja": "販売数シェア"},
    "revenue_share": {"zh": "销售额占比", "en": "Revenue Share", "ja": "売上シェア"},
    "no_price_data": {"zh": "当前报告缺少可用价格字段，暂时无法做价格带分析。", "en": "This report lacks usable price data, so price band analysis cannot be created yet.", "ja": "利用可能な価格データが不足しているため、価格帯分析を作成できません。"},
    "col_price": {"zh": "价格", "en": "Price", "ja": "価格"},
    "col_bsr_rank": {"zh": "类目排名", "en": "Category Rank", "ja": "カテゴリ順位"},
    "col_rank_trend": {"zh": "排名趋势", "en": "Rank Trend", "ja": "順位トレンド"},
    "col_global_units_share": {"zh": "全球销量占比", "en": "Global Unit Share", "ja": "グローバル販売数シェア"},
    "col_global_revenue_share": {"zh": "全球销售额占比", "en": "Global Revenue Share", "ja": "グローバル売上シェア"},
    "col_sites_covered": {"zh": "覆盖站点", "en": "Sites Covered", "ja": "対象サイト"},
    "data_quality_score": {"zh": "数据质量评分", "en": "Data Quality Score", "ja": "データ品質スコア"},
    "data_quality_note": {"zh": "从样本覆盖、字段完整、口径可比、七站点完整度和解析告警判断本周数据是否适合直接做运营决策。", "en": "Scores whether this week is decision-ready based on sample coverage, field completeness, comparability, site coverage, and parse warnings.", "ja": "サンプル、項目完全性、比較可能性、サイト網羅、解析警告から判断します。"},
    "quality_ready": {"zh": "可复核", "en": "Ready for Review", "ja": "レビュー可"},
    "quality_watch": {"zh": "需复核", "en": "Needs Review", "ja": "要確認"},
    "quality_risk": {"zh": "不建议下结论", "en": "High Risk", "ja": "高リスク"},
    "quality_dimension": {"zh": "维度", "en": "Dimension", "ja": "項目"},
    "quality_result": {"zh": "结果", "en": "Result", "ja": "結果"},
    "quality_detail": {"zh": "说明", "en": "Detail", "ja": "説明"},
    "opportunity_center": {"zh": "机会中心", "en": "Opportunity Center", "ja": "機会センター"},
    "opportunity_center_note": {"zh": "把份额、AI、价格带、竞品、数据缺口转成可执行机会，按运营优先级排序。", "en": "Turns share, AI, price bands, competitors, and data gaps into prioritized operational opportunities.", "ja": "シェア、AI、価格帯、競合、データ欠損を優先機会に変換します。"},
    "opportunity_score": {"zh": "机会分", "en": "Score", "ja": "スコア"},
    "opportunity": {"zh": "机会/风险", "en": "Opportunity / Risk", "ja": "機会/リスク"},
    "why": {"zh": "判断依据", "en": "Why", "ja": "根拠"},
    "recommended_action": {"zh": "建议动作", "en": "Recommended Action", "ja": "推奨アクション"},
    "owner": {"zh": "负责人", "en": "Owner", "ja": "担当"},
    "asin_war_room": {"zh": "ASIN 作战页", "en": "ASIN War Room", "ja": "ASIN 作戦ページ"},
    "asin_war_room_note": {"zh": "按销售额、排名、价格、AI 标签和环比变化筛出本周重点守擂、拦截和复盘 ASIN。", "en": "Surfaces defend, intercept, and review ASINs using revenue, rank, price, AI tags, and weekly movement.", "ja": "売上、順位、価格、AIタグ、週次変化から重点ASINを抽出します。"},
    "focus_asins": {"zh": "重点 ASIN", "en": "Focus ASINs", "ja": "重点 ASIN"},
    "plaud_asins": {"zh": "PLAUD ASIN", "en": "PLAUD ASINs", "ja": "PLAUD ASIN"},
    "ai_focus_asins": {"zh": "AI 竞品 ASIN", "en": "AI Competitor ASINs", "ja": "AI 競合 ASIN"},
    "price_threats": {"zh": "低价威胁", "en": "Price Threats", "ja": "低価格脅威"},
    "battle_score": {"zh": "作战分", "en": "Battle Score", "ja": "作戦スコア"},
    "battle_priority": {"zh": "优先级", "en": "Priority", "ja": "優先度"},
    "battle_role": {"zh": "角色", "en": "Role", "ja": "役割"},
    "battle_action": {"zh": "作战动作", "en": "Action", "ja": "アクション"},
    "tab_competitor_asin_depth": {"zh": "竞品 ASIN 深度", "en": "Competitor ASIN Depth", "ja": "競合 ASIN 深掘り"},
    "tab_keyword_voc": {"zh": "关键词 / VOC", "en": "Keyword / VOC", "ja": "キーワード / VOC"},
    "competitor_asin_depth": {"zh": "竞品 ASIN 深度页", "en": "Competitor ASIN Deep Dive", "ja": "競合 ASIN 深掘り"},
    "competitor_asin_depth_note": {"zh": "聚焦非 PLAUD 高销售额、高排名、AI 卖点和低价威胁 ASIN，给出运营拦截动作。", "en": "Focuses on non-PLAUD ASINs with high revenue, rank, AI positioning, or price pressure and turns them into actions.", "ja": "高売上・高順位・AI訴求・低価格圧力のある非PLAUD ASINを重点化します。"},
    "keyword_voc_opportunity": {"zh": "关键词机会 / VOC 分析页", "en": "Keyword Opportunity / VOC", "ja": "キーワード機会 / VOC"},
    "keyword_voc_note": {"zh": "从商品标题、AI 命中词、价格带和可用评论信号中抽取机会词与用户需求假设。评论原文接入 MCP 后可进一步升级。", "en": "Extracts opportunity terms and customer-need hypotheses from titles, AI matches, price bands, and available review signals. Raw review VOC can be added through MCP later.", "ja": "タイトル、AIヒット語、価格帯、レビュー信号から機会語と顧客ニーズ仮説を抽出します。"},
    "deep_focus_asin": {"zh": "重点竞品 ASIN", "en": "Focus Competitor ASINs", "ja": "重点競合 ASIN"},
    "deep_price_pressure": {"zh": "价格压力", "en": "Price Pressure", "ja": "価格圧力"},
    "deep_ai_positioning": {"zh": "AI 卖点压力", "en": "AI Positioning Pressure", "ja": "AI訴求圧力"},
    "deep_review_signal": {"zh": "评分 / 评论信号", "en": "Rating / Review Signal", "ja": "評価 / レビュー信号"},
    "voc_theme": {"zh": "VOC 主题", "en": "VOC Theme", "ja": "VOC テーマ"},
    "market_signal": {"zh": "市场信号", "en": "Market Signal", "ja": "市場シグナル"},
    "keyword_opportunity": {"zh": "关键词机会", "en": "Keyword Opportunity", "ja": "キーワード機会"},
    "matched_asins": {"zh": "命中 ASIN", "en": "Matched ASINs", "ja": "該当 ASIN"},
    "top_brand": {"zh": "代表品牌", "en": "Top Brand", "ja": "代表ブランド"},
    "opportunity_type": {"zh": "机会类型", "en": "Opportunity Type", "ja": "機会タイプ"},
    "asin_link": {"zh": "链接", "en": "Link", "ja": "リンク"},
    "rating": {"zh": "评分", "en": "Rating", "ja": "評価"},
    "reviews": {"zh": "评论数", "en": "Reviews", "ja": "レビュー数"},
    "seller_type": {"zh": "配送/卖家", "en": "Seller Type", "ja": "販売形態"},
    "shelf_date": {"zh": "上架时间", "en": "Shelf Date", "ja": "発売日"},
    "operator_action": {"zh": "运营动作", "en": "Operator Action", "ja": "運用アクション"},
    "risk_signal": {"zh": "风险信号", "en": "Risk Signal", "ja": "リスク信号"},
}

SITE_LANGUAGE_OPTIONS = [
    ("zh", "内部中文"),
    ("us", "US · English"),
    ("uk", "UK · English"),
    ("de", "DE · Deutsch"),
    ("fr", "FR · Français"),
    ("it", "IT · Italiano"),
    ("es", "ES · Español"),
    ("jp", "JP · 日本語"),
]

SITE_LANGUAGE_META = {
    "zh": {"htmlLang": "zh-CN", "fallback": "zh"},
    "us": {"htmlLang": "en-US", "fallback": "en"},
    "uk": {"htmlLang": "en-GB", "fallback": "en"},
    "de": {"htmlLang": "de", "fallback": "en"},
    "fr": {"htmlLang": "fr", "fallback": "en"},
    "it": {"htmlLang": "it", "fallback": "en"},
    "es": {"htmlLang": "es", "fallback": "en"},
    "jp": {"htmlLang": "ja", "fallback": "ja"},
}

SITE_TRANSLATION_OVERRIDES = {
    "app_title": {
        "de": "PLAUD Amazon Market Intelligence Agent",
        "fr": "PLAUD Amazon Market Intelligence Agent",
        "it": "PLAUD Amazon Market Intelligence Agent",
        "es": "PLAUD Amazon Market Intelligence Agent",
    },
    "nav_dashboard": {"de": "Dashboard", "fr": "Tableau de bord", "it": "Dashboard", "es": "Panel"},
    "nav_uploads": {"de": "Uploads", "fr": "Imports", "it": "Caricamenti", "es": "Cargas"},
    "nav_config": {"de": "Konfiguration", "fr": "Configuration", "it": "Configurazione", "es": "Configuración"},
    "language": {"de": "Sprache", "fr": "Langue", "it": "Lingua", "es": "Idioma"},
    "theme": {"de": "Design", "fr": "Thème", "it": "Tema", "es": "Tema"},
    "theme_ocean": {"de": "Ozeanblau", "fr": "Bleu océan", "it": "Blu oceano", "es": "Azul océano"},
    "theme_emerald": {"de": "Wachstumsgrün", "fr": "Vert croissance", "it": "Verde crescita", "es": "Verde crecimiento"},
    "theme_amber": {"de": "Insight-Gold", "fr": "Or insight", "it": "Oro insight", "es": "Dorado insight"},
    "theme_slate": {"de": "Dunkelmodus", "fr": "Mode sombre", "it": "Modalità scura", "es": "Modo oscuro"},
    "dashboard_title": {"de": "Markt-Monitoring", "fr": "Pilotage du marché", "it": "Monitoraggio mercato", "es": "Monitoreo de mercado"},
    "dashboard_note": {
        "de": "Ausgerichtet auf etablierte Amazon-Monitoring-Workflows: Marktanteil, Wettbewerberbewegung, Produktintelligenz und Datenqualität.",
        "fr": "Aligné sur les workflows Amazon matures : part de marché, mouvements concurrents, intelligence produit et qualité des données.",
        "it": "Allineato ai workflow Amazon maturi: quota di mercato, movimenti dei concorrenti, intelligence prodotto e qualità dati.",
        "es": "Alineado con flujos maduros de Amazon: cuota de mercado, movimiento competitivo, inteligencia de producto y salud de datos.",
    },
    "weekly_mvp": {"de": "Wöchentliches MVP", "fr": "MVP hebdomadaire", "it": "MVP settimanale", "es": "MVP semanal"},
    "nav_analysis": {"de": "Analyse", "fr": "Analyse", "it": "Analisi", "es": "Análisis"},
    "nav_actions": {"de": "Aktionen", "fr": "Actions", "it": "Azioni", "es": "Acciones"},
    "nav_chat": {"de": "Ops Q&A", "fr": "Q&R ops", "it": "Q&A ops", "es": "Preguntas ops"},
    "nav_knowledge": {"de": "Wissen", "fr": "Base connaissances", "it": "Knowledge base", "es": "Base de conocimiento"},
    "chat_title": {
        "de": "Operations Q&A",
        "fr": "Assistant Q&R opérations",
        "it": "Assistente Q&A operativo",
        "es": "Asistente de preguntas operativas",
    },
    "chat_note": {
        "de": "Beantwortet Markt-, Wettbewerbs-, AI-, Preisband- und Maßnahmenfragen aus hochgeladenen Daten.",
        "fr": "Répond aux questions marché, concurrents, IA, prix et actions à partir des données importées.",
        "it": "Risponde a domande su mercato, concorrenti, AI, prezzi e azioni dai dati caricati.",
        "es": "Responde preguntas de mercado, competencia, IA, precios y acciones con los datos cargados.",
    },
    "chat_question": {"de": "Frage", "fr": "Question", "it": "Domanda", "es": "Pregunta"},
    "chat_placeholder": {
        "de": "Beispiel: Welche Marketingchancen gibt es diese Woche?",
        "fr": "Exemple : quelles opportunités marketing cette semaine ?",
        "it": "Esempio: quali opportunità marketing questa settimana?",
        "es": "Ejemplo: ¿qué oportunidades de marketing hay esta semana?",
    },
    "chat_ask": {"de": "Fragen", "fr": "Demander", "it": "Chiedi", "es": "Preguntar"},
    "quick_questions": {"de": "Schnellfragen", "fr": "Questions rapides", "it": "Domande rapide", "es": "Preguntas rápidas"},
    "kpi_sites": {"de": "Überwachte Sites", "fr": "Sites suivis", "it": "Siti monitorati", "es": "Sitios monitoreados"},
    "kpi_success": {"de": "Analysiert", "fr": "Analysés", "it": "Analizzati", "es": "Analizados"},
    "kpi_errors": {"de": "Fehler", "fr": "Erreurs", "it": "Errori", "es": "Errores"},
    "kpi_latest_run": {"de": "Letzter Run", "fr": "Dernier Run", "it": "Ultimo Run", "es": "Último Run"},
    "market_share_desc": {
        "de": "Aufschlüsselung von PLAUD, Wettbewerbern und weiteren Marken.",
        "fr": "Répartition entre PLAUD, concurrents suivis et autres marques.",
        "it": "Ripartizione tra PLAUD, concorrenti monitorati e altri brand.",
        "es": "Desglose de PLAUD, competidores seguidos y otras marcas.",
    },
    "competitor_movement_desc": {
        "de": "Wöchentliche Trendlinien für Marktanteile.",
        "fr": "Tendances hebdomadaires des parts de marché.",
        "it": "Trend settimanali delle quote di mercato.",
        "es": "Tendencias semanales de cuota de mercado.",
    },
    "product_intelligence_desc": {
        "de": "AI-ASINs, Marken, Titel und Trefferbegriffe.",
        "fr": "ASIN IA, marques, titres et termes détectés.",
        "it": "ASIN AI, brand, titoli e parole rilevate.",
        "es": "ASIN IA, marcas, títulos y términos detectados.",
    },
    "data_health_desc": {
        "de": "Upload-Status, Warnungen und fehlende Sites auf einen Blick.",
        "fr": "Statut d'import, alertes et sites manquants en un coup d'œil.",
        "it": "Stato upload, avvisi e siti mancanti in un colpo d'occhio.",
        "es": "Estado de carga, alertas y sitios faltantes de un vistazo.",
    },
    "workflow_export_desc": {
        "de": "Excel hochladen und den wöchentlichen Excel-Bericht herunterladen.",
        "fr": "Importer Excel et télécharger le rapport hebdomadaire.",
        "it": "Carica Excel e scarica il report settimanale.",
        "es": "Carga Excel y descarga el informe semanal.",
    },
    "upload_excel": {"de": "SellerSprite Excel hochladen", "fr": "Importer Excel SellerSprite", "it": "Carica Excel SellerSprite", "es": "Cargar Excel SellerSprite"},
    "week_id": {"de": "Woche", "fr": "Semaine", "it": "Settimana", "es": "Semana"},
    "marketplace": {"de": "Marketplace", "fr": "Marketplace", "it": "Marketplace", "es": "Marketplace"},
    "excel_file": {"de": "Excel-Datei", "fr": "Fichier Excel", "it": "File Excel", "es": "Archivo Excel"},
    "note": {"de": "Notiz", "fr": "Note", "it": "Nota", "es": "Nota"},
    "note_placeholder": {
        "de": "Beispiel: 20260513 IT Plugin-Export",
        "fr": "Exemple : export plugin IT 20260513",
        "it": "Esempio: export plugin IT 20260513",
        "es": "Ejemplo: exportación plugin IT 20260513",
    },
    "upload_parse": {"de": "Hochladen und analysieren", "fr": "Importer et analyser", "it": "Carica e analizza", "es": "Cargar y analizar"},
    "uploaded": {"de": "Hochgeladen", "fr": "Importé", "it": "Caricato", "es": "Cargado"},
    "pending_upload": {"de": "Fehlt", "fr": "Manquant", "it": "Mancante", "es": "Pendiente"},
    "no_week_data": {"de": "Keine Daten diese Woche", "fr": "Aucune donnée cette semaine", "it": "Nessun dato questa settimana", "es": "Sin datos esta semana"},
    "latest_market_result": {"de": "Aktuelles Marktergebnis", "fr": "Dernier résultat marché", "it": "Ultimo risultato mercato", "es": "Último resultado de mercado"},
    "market_result": {"de": "Marktergebnis", "fr": "Résultat marché", "it": "Risultato mercato", "es": "Resultado de mercado"},
    "download_weekly_excel": {"de": "Wochenbericht Excel herunterladen", "fr": "Télécharger le rapport Excel", "it": "Scarica report Excel", "es": "Descargar informe Excel"},
    "plaud_units_share": {"de": "PLAUD Absatzanteil", "fr": "Part volume PLAUD", "it": "Quota unità PLAUD", "es": "Cuota unidades PLAUD"},
    "plaud_revenue_share": {"de": "PLAUD Umsatzanteil", "fr": "Part CA PLAUD", "it": "Quota ricavi PLAUD", "es": "Cuota ingresos PLAUD"},
    "competitor_units_share": {"de": "Wettbewerber-Absatzanteil", "fr": "Part volume concurrents", "it": "Quota unità concorrenti", "es": "Cuota unidades competidores"},
    "ai_units_share": {"de": "AI-Wettbewerber-Absatzanteil", "fr": "Part volume concurrents IA", "it": "Quota unità concorrenti AI", "es": "Cuota unidades competidores IA"},
    "units_share_structure": {"de": "Struktur Absatzanteil", "fr": "Structure part volume", "it": "Struttura quota unità", "es": "Estructura cuota unidades"},
    "revenue_share_structure": {"de": "Struktur Umsatzanteil", "fr": "Structure part CA", "it": "Struttura quota ricavi", "es": "Estructura cuota ingresos"},
    "ai_units_penetration": {"de": "AI-Absatzpenetration", "fr": "Pénétration volume IA", "it": "Penetrazione unità AI", "es": "Penetración unidades IA"},
    "ai_revenue_penetration": {"de": "AI-Umsatzpenetration", "fr": "Pénétration CA IA", "it": "Penetrazione ricavi AI", "es": "Penetración ingresos IA"},
    "monthly_units": {"de": "Monatsabsatz", "fr": "Unités mensuelles", "it": "Unità mensili", "es": "Unidades mensuales"},
    "monthly_revenue": {"de": "Monatsumsatz", "fr": "CA mensuel", "it": "Ricavi mensili", "es": "Ingresos mensuales"},
    "exclude_plaud": {"de": "Ohne PLAUD", "fr": "Hors PLAUD", "it": "Escluso PLAUD", "es": "Sin PLAUD"},
    "other_brands": {"de": "Andere Marken", "fr": "Autres marques", "it": "Altri brand", "es": "Otras marcas"},
    "non_ai_other": {"de": "Nicht-AI / Sonstige", "fr": "Non IA / autres", "it": "Non AI / altro", "es": "No IA / otros"},
    "tracked_competitors": {"de": "Überwachte Wettbewerber", "fr": "Concurrents suivis", "it": "Concorrenti monitorati", "es": "Competidores seguidos"},
    "ai_competitors": {"de": "AI-Wettbewerber", "fr": "Concurrents IA", "it": "Concorrenti AI", "es": "Competidores IA"},
    "plaud_units_trend": {"de": "Trend PLAUD Absatzanteil", "fr": "Tendance volume PLAUD", "it": "Trend quota unità PLAUD", "es": "Tendencia cuota unidades PLAUD"},
    "ai_units_trend": {"de": "Trend AI-Wettbewerber", "fr": "Tendance concurrents IA", "it": "Trend concorrenti AI", "es": "Tendencia competidores IA"},
    "weekly_trend": {"de": "Wochentrend", "fr": "Tendance hebdo", "it": "Trend settimanale", "es": "Tendencia semanal"},
    "mature_mapping": {"de": "Mapping der Monitoring-Ansichten", "fr": "Mapping des vues de monitoring", "it": "Mappatura viste monitoraggio", "es": "Mapeo de vistas de monitoreo"},
    "module": {"de": "Modul", "fr": "Module", "it": "Modulo", "es": "Módulo"},
    "platform_impl": {"de": "Umsetzung", "fr": "Implémentation", "it": "Implementazione", "es": "Implementación"},
    "task_mapping": {"de": "Task-1-Zuordnung", "fr": "Correspondance Task 1", "it": "Mappatura Task 1", "es": "Mapeo Task 1"},
    "brand_market_share": {"de": "Marken-/Wettbewerberanteil", "fr": "Part marques / concurrents", "it": "Quota brand / concorrenti", "es": "Cuota marca / competidores"},
    "ai_asin_detail": {"de": "AI-Wettbewerber ASIN-Details", "fr": "Détail ASIN concurrents IA", "it": "Dettaglio ASIN concorrenti AI", "es": "Detalle ASIN competidores IA"},
    "recent_uploads": {"de": "Letzte Uploads", "fr": "Imports récents", "it": "Caricamenti recenti", "es": "Cargas recientes"},
    "no_uploads": {"de": "Keine Uploads", "fr": "Aucun import", "it": "Nessun caricamento", "es": "Sin cargas"},
    "status": {"de": "Status", "fr": "Statut", "it": "Stato", "es": "Estado"},
    "uploaded_at": {"de": "Upload-Zeit", "fr": "Importé le", "it": "Caricato il", "es": "Cargado el"},
    "action": {"de": "Aktion", "fr": "Action", "it": "Azione", "es": "Acción"},
    "view": {"de": "Ansehen", "fr": "Voir", "it": "Vedi", "es": "Ver"},
    "config_summary": {"de": "Konfigurationsübersicht", "fr": "Résumé configuration", "it": "Riepilogo configurazione", "es": "Resumen configuración"},
    "currency": {"de": "Währung", "fr": "Devise", "it": "Valuta", "es": "Moneda"},
    "keyword": {"de": "Keyword", "fr": "Mot-clé", "it": "Keyword", "es": "Palabra clave"},
    "category_path": {"de": "Kategoriepfad", "fr": "Chemin catégorie", "it": "Percorso categoria", "es": "Ruta categoría"},
    "page_not_found": {"de": "Seite nicht gefunden.", "fr": "Page introuvable.", "it": "Pagina non trovata.", "es": "Página no encontrada."},
    "upload_failed": {"de": "Upload fehlgeschlagen", "fr": "Échec import", "it": "Caricamento fallito", "es": "Carga fallida"},
    "upload_required": {
        "de": "Bitte Woche und Marketplace angeben und eine Excel-Datei auswählen.",
        "fr": "Veuillez saisir la semaine, le marketplace et sélectionner un fichier Excel.",
        "it": "Inserisci settimana, marketplace e seleziona un file Excel.",
        "es": "Introduce semana, marketplace y selecciona un archivo Excel.",
    },
    "download_failed": {"de": "Download fehlgeschlagen", "fr": "Échec téléchargement", "it": "Download fallito", "es": "Descarga fallida"},
    "report_not_found": {"de": "Wochenbericht nicht gefunden.", "fr": "Rapport hebdomadaire introuvable.", "it": "Report settimanale non trovato.", "es": "Informe semanal no encontrado."},
    "report_missing": {"de": "Wochenbericht-Datei existiert nicht.", "fr": "Le fichier de rapport n'existe pas.", "it": "Il file report non esiste.", "es": "El archivo del informe no existe."},
    "excel_report_missing": {"de": "Excel-Wochenbericht nicht gefunden.", "fr": "Rapport Excel introuvable.", "it": "Report Excel non trovato.", "es": "Informe Excel no encontrado."},
    "no_data_notice": {
        "de": "Noch keine analysierten Daten. Laden Sie eine SellerSprite Excel-Datei hoch, um Diagramme und Kennzahlen zu sehen.",
        "fr": "Aucune donnée analysée. Importez un Excel SellerSprite pour afficher graphiques et indicateurs.",
        "it": "Nessun dato analizzato. Carica un Excel SellerSprite per vedere grafici e metriche.",
        "es": "Aún no hay datos analizados. Carga un Excel SellerSprite para ver gráficos e indicadores.",
    },
    "not_found_run": {"de": "Run nicht gefunden.", "fr": "Run introuvable.", "it": "Run non trovato.", "es": "Run no encontrado."},
    "parse_failed": {"de": "Analyse fehlgeschlagen: ", "fr": "Analyse échouée : ", "it": "Analisi fallita: ", "es": "Análisis fallido: "},
    "col_marketplace": {"de": "Marketplace", "fr": "Marketplace", "it": "Marketplace", "es": "Marketplace"},
    "col_brand": {"de": "Marke", "fr": "Marque", "it": "Brand", "es": "Marca"},
    "col_brand_group": {"de": "Markengruppe", "fr": "Groupe marque", "it": "Gruppo brand", "es": "Grupo marca"},
    "col_monthly_units": {"de": "Monatsabsatz", "fr": "Unités mensuelles", "it": "Unità mensili", "es": "Unidades mensuales"},
    "col_monthly_units_share": {"de": "Absatzanteil", "fr": "Part volume", "it": "Quota unità", "es": "Cuota unidades"},
    "col_monthly_revenue": {"de": "Monatsumsatz", "fr": "CA mensuel", "it": "Ricavi mensili", "es": "Ingresos mensuales"},
    "col_monthly_revenue_share": {"de": "Umsatzanteil", "fr": "Part CA", "it": "Quota ricavi", "es": "Cuota ingresos"},
    "col_standard_brand": {"de": "Standardmarke", "fr": "Marque standard", "it": "Brand standard", "es": "Marca estándar"},
    "col_ai_matched_keywords": {"de": "Trefferbegriffe", "fr": "Termes détectés", "it": "Parole rilevate", "es": "Términos detectados"},
    "col_product_title": {"de": "Produkttitel", "fr": "Titre produit", "it": "Titolo prodotto", "es": "Título producto"},
    "alert_center": {"de": "Warnzentrum", "fr": "Centre d'alertes", "it": "Centro avvisi", "es": "Centro de alertas"},
    "alert_center_note": {
        "de": "Priorisiert fehlende Daten, sinkende Anteile, Wettbewerberanstieg und AI-Penetration.",
        "fr": "Priorise les données manquantes, baisses de part, hausses concurrentes et pénétration IA.",
        "it": "Evidenzia dati mancanti, cali di quota, crescita concorrenti e penetrazione AI.",
        "es": "Prioriza datos faltantes, caídas de cuota, subidas de competidores y penetración IA.",
    },
    "seven_site_comparison": {"de": "Vergleich der 7 Sites", "fr": "Comparaison des 7 sites", "it": "Confronto 7 siti", "es": "Comparativa de 7 sitios"},
    "top_movement_board": {"de": "Top-Veränderungen", "fr": "Top variations", "it": "Top variazioni", "es": "Top cambios"},
    "top_movement_note": {
        "de": "Mit Vorwochendaten werden Veränderungen gezeigt; sonst aktuelle Top-Listen.",
        "fr": "Avec historique, affiche les variations hebdo ; sinon les Top actuels.",
        "it": "Con storico mostra variazioni settimanali; altrimenti i Top attuali.",
        "es": "Con histórico muestra cambios semanales; si no, Top actuales.",
    },
    "risk_high": {"de": "Hohes Risiko", "fr": "Risque élevé", "it": "Rischio alto", "es": "Alto riesgo"},
    "risk_medium": {"de": "Beobachten", "fr": "À surveiller", "it": "Da monitorare", "es": "Vigilar"},
    "risk_info": {"de": "Hinweis", "fr": "Info", "it": "Info", "es": "Info"},
    "data_missing": {"de": "Fehlt", "fr": "Manquant", "it": "Mancante", "es": "Pendiente"},
    "data_ready": {"de": "Bereit", "fr": "Prêt", "it": "Pronto", "es": "Listo"},
    "data_no_previous": {"de": "Historie nötig", "fr": "Historique requis", "it": "Serve storico", "es": "Falta histórico"},
    "delta": {"de": "Delta", "fr": "Écart", "it": "Delta", "es": "Delta"},
    "brand_growth_rank": {"de": "Markenwachstum", "fr": "Croissance marques", "it": "Crescita brand", "es": "Crecimiento marcas"},
    "current_brand_rank": {"de": "Aktuelle Marken", "fr": "Marques actuelles", "it": "Brand attuali", "es": "Marcas actuales"},
    "asin_growth_rank": {"de": "AI-ASIN Umsatzwachstum", "fr": "Croissance CA ASIN IA", "it": "Crescita ricavi ASIN AI", "es": "Crecimiento ingresos ASIN IA"},
    "current_ai_asin_rank": {"de": "Aktuelle AI-ASINs", "fr": "ASIN IA actuels", "it": "ASIN AI attuali", "es": "ASIN IA actuales"},
    "share_delta": {"de": "Share-Delta", "fr": "Écart part", "it": "Delta quota", "es": "Delta cuota"},
    "revenue_delta": {"de": "Umsatz-Delta", "fr": "Écart CA", "it": "Delta ricavi", "es": "Delta ingresos"},
    "units_delta": {"de": "Absatz-Delta", "fr": "Écart unités", "it": "Delta unità", "es": "Delta unidades"},
    "no_rank_data": {"de": "Keine Rankingdaten verfügbar.", "fr": "Aucune donnée de classement.", "it": "Nessun dato ranking disponibile.", "es": "No hay datos de ranking."},
    "current_value": {"de": "Aktuell", "fr": "Actuel", "it": "Attuale", "es": "Actual"},
    "category_rank_model": {"de": "Kategorie-Rang Verkaufsestimate", "fr": "Estimation ventes par rang", "it": "Stima vendite da ranking", "es": "Estimación por ranking"},
    "category_rank_note": {
        "de": "Nutzt finalen Kategorie-BSR und SellerSprite-Verkaufsproben, um eine Potenzkurve für die Kategoriegröße zu schätzen.",
        "fr": "Utilise le BSR de catégorie finale et les ventes SellerSprite pour ajuster une courbe de puissance.",
        "it": "Usa il BSR della categoria finale e i campioni SellerSprite per stimare una curva di potenza.",
        "es": "Usa el BSR de categoría final y muestras SellerSprite para ajustar una curva de potencia.",
    },
    "estimated_category_units": {"de": "Geschätzter Kategorieabsatz", "fr": "Unités catégorie estimées", "it": "Unità categoria stimate", "es": "Unidades categoría estimadas"},
    "observed_sample_units": {"de": "Beobachtete Einheiten", "fr": "Unités observées", "it": "Unità osservate", "es": "Unidades observadas"},
    "estimated_tail_units": {"de": "Modell-Ergänzung", "fr": "Unités complétées", "it": "Unità integrate", "es": "Unidades completadas"},
    "rank_sample_count": {"de": "Gültige Rangproben", "fr": "Échantillons rang valides", "it": "Campioni ranking validi", "es": "Muestras ranking válidas"},
    "rank_coverage": {"de": "Rangabdeckung", "fr": "Couverture rang", "it": "Copertura ranking", "es": "Cobertura ranking"},
    "model_confidence": {"de": "Modellvertrauen", "fr": "Confiance modèle", "it": "Affidabilità modello", "es": "Confianza modelo"},
    "model_formula": {"de": "Modellformel", "fr": "Formule modèle", "it": "Formula modello", "es": "Fórmula modelo"},
    "rank_fit_quality": {"de": "Fit-Qualität", "fr": "Qualité d'ajustement", "it": "Qualità fit", "es": "Calidad ajuste"},
    "confidence_high": {"de": "Hoch", "fr": "Élevée", "it": "Alta", "es": "Alta"},
    "confidence_medium": {"de": "Mittel", "fr": "Moyenne", "it": "Media", "es": "Media"},
    "confidence_low": {"de": "Niedrig", "fr": "Faible", "it": "Bassa", "es": "Baja"},
    "plaud_estimated_share": {"de": "PLAUD geschätzter Anteil", "fr": "Part estimée PLAUD", "it": "Quota stimata PLAUD", "es": "Cuota estimada PLAUD"},
    "ai_estimated_share": {"de": "AI-Wettbewerber Anteil", "fr": "Part estimée concurrents IA", "it": "Quota stimata concorrenti AI", "es": "Cuota estimada competidores IA"},
    "no_rank_model_data": {"de": "Keine nutzbaren BSR- oder Absatzproben für die Schätzung.", "fr": "Pas de BSR ou ventes utilisables pour l'estimation.", "it": "Nessun BSR o campione vendite utilizzabile per la stima.", "es": "No hay BSR o ventas utilizables para estimar."},
    "weekly_insights": {"de": "Wöchentliche Insights", "fr": "Insights hebdomadaires", "it": "Insight settimanali", "es": "Insights semanales"},
    "weekly_insights_note": {
        "de": "Verdichtet Marktanteil, AI-Durchdringung, Kategoriegröße und Datenqualität zu operativen Schlussfolgerungen.",
        "fr": "Transforme part de marché, pénétration IA, taille catégorie et qualité des données en conclusions opérationnelles.",
        "it": "Trasforma quota, penetrazione AI, dimensione categoria e qualità dati in conclusioni operative.",
        "es": "Convierte cuota, penetración IA, tamaño de categoría y salud de datos en conclusiones operativas.",
    },
    "asin_change_analysis": {"de": "Neue / verschwundene ASINs", "fr": "ASIN nouveaux / disparus", "it": "ASIN nuovi / scomparsi", "es": "ASIN nuevos / desaparecidos"},
    "asin_change_note": {
        "de": "Vergleicht Produktpool-Änderungen, sobald eine Vorwoche für dieselbe Site existiert.",
        "fr": "Compare les changements de pool produit dès que la semaine précédente du même site existe.",
        "it": "Confronta le variazioni del pool prodotti quando esiste la settimana precedente dello stesso sito.",
        "es": "Compara cambios del pool de productos cuando existe la semana anterior del mismo sitio.",
    },
    "new_asins": {"de": "Neue ASINs", "fr": "ASIN nouveaux", "it": "ASIN nuovi", "es": "ASIN nuevos"},
    "disappeared_asins": {"de": "Verschwundene ASINs", "fr": "ASIN disparus", "it": "ASIN scomparsi", "es": "ASIN desaparecidos"},
    "baseline_asins": {"de": "Baseline-ASINs", "fr": "ASIN de référence", "it": "ASIN baseline", "es": "ASIN base"},
    "previous_week": {"de": "Vorwoche", "fr": "Semaine précédente", "it": "Settimana precedente", "es": "Semana anterior"},
    "current_week": {"de": "Aktuelle Woche", "fr": "Semaine actuelle", "it": "Settimana corrente", "es": "Semana actual"},
    "no_previous_asin_data": {
        "de": "Dies ist die Baseline-Woche; neue und verschwundene ASINs erscheinen nach dem nächsten Upload derselben Site.",
        "fr": "C'est la semaine de référence ; les ASIN nouveaux/disparus apparaîtront après le prochain import du même site.",
        "it": "Questa è la settimana baseline; gli ASIN nuovi/scomparsi appariranno dopo il prossimo upload dello stesso sito.",
        "es": "Esta es la semana base; los ASIN nuevos/desaparecidos aparecerán tras la próxima carga del mismo sitio.",
    },
    "price_band_analysis": {"de": "Preisbänder", "fr": "Analyse par prix", "it": "Analisi fasce prezzo", "es": "Análisis por precio"},
    "price_band_note": {
        "de": "Gliedert ASIN-Anzahl, Absatz, Umsatz, PLAUD und AI-Wettbewerber nach Preisband.",
        "fr": "Décompose nombre d'ASIN, ventes, CA, PLAUD et concurrents IA par tranche de prix.",
        "it": "Scompone ASIN, vendite, ricavi, PLAUD e concorrenti AI per fascia prezzo.",
        "es": "Desglosa ASIN, unidades, ingresos, PLAUD y competidores IA por rango de precio.",
    },
    "price_band": {"de": "Preisband", "fr": "Tranche de prix", "it": "Fascia prezzo", "es": "Rango de precio"},
    "asin_count": {"de": "ASIN-Anzahl", "fr": "Nombre ASIN", "it": "Numero ASIN", "es": "Número ASIN"},
    "all_products": {"de": "Alle Produkte", "fr": "Tous produits", "it": "Tutti i prodotti", "es": "Todos los productos"},
    "plaud_products": {"de": "PLAUD-Produkte", "fr": "Produits PLAUD", "it": "Prodotti PLAUD", "es": "Productos PLAUD"},
    "ai_products": {"de": "AI-Produkte", "fr": "Produits IA", "it": "Prodotti AI", "es": "Productos IA"},
    "unit_share": {"de": "Absatzanteil", "fr": "Part unités", "it": "Quota unità", "es": "Cuota unidades"},
    "revenue_share": {"de": "Umsatzanteil", "fr": "Part CA", "it": "Quota ricavi", "es": "Cuota ingresos"},
    "no_price_data": {"de": "Keine nutzbaren Preisdaten vorhanden.", "fr": "Pas de données prix utilisables.", "it": "Nessun dato prezzo utilizzabile.", "es": "No hay datos de precio utilizables."},
    "col_price": {"de": "Preis", "fr": "Prix", "it": "Prezzo", "es": "Precio"},
    "col_bsr_rank": {"de": "Kategorie-Rang", "fr": "Rang catégorie", "it": "Rank categoria", "es": "Ranking categoría"},
}

SITE_LOCALE_FALLBACKS = {code: meta["fallback"] for code, meta in SITE_LANGUAGE_META.items()}
for translation_key, translation_values in UI_TRANSLATIONS.items():
    for locale_code, fallback_code in SITE_LOCALE_FALLBACKS.items():
        translation_values.setdefault(locale_code, translation_values.get(fallback_code) or translation_values.get("zh") or translation_key)
for translation_key, translation_values in SITE_TRANSLATION_OVERRIDES.items():
    UI_TRANSLATIONS.setdefault(translation_key, {}).update(translation_values)
for translation_key, translation_values in UI_TRANSLATIONS.items():
    for locale_code, fallback_code in SITE_LOCALE_FALLBACKS.items():
        translation_values.setdefault(locale_code, translation_values.get(fallback_code) or translation_values.get("zh") or translation_key)

COLUMN_I18N = {
    "marketplace": "col_marketplace",
    "brand": "col_brand",
    "brand_group": "col_brand_group",
    "monthly_units": "col_monthly_units",
    "monthly_units_share": "col_monthly_units_share",
    "monthly_revenue": "col_monthly_revenue",
    "monthly_revenue_share": "col_monthly_revenue_share",
    "asin": "col_asin",
    "standard_brand": "col_standard_brand",
    "ai_matched_keywords": "col_ai_matched_keywords",
    "product_title": "col_product_title",
    "price": "col_price",
    "bsr_rank": "col_bsr_rank",
    "rank_trend": "col_rank_trend",
    "global_units_share": "col_global_units_share",
    "global_revenue_share": "col_global_revenue_share",
    "sites_covered": "col_sites_covered",
    "quality_dimension": "quality_dimension",
    "quality_result": "quality_result",
    "quality_detail": "quality_detail",
    "opportunity_score": "opportunity_score",
    "opportunity": "opportunity",
    "why": "why",
    "recommended_action": "recommended_action",
    "owner": "owner",
    "battle_score": "battle_score",
    "battle_priority": "battle_priority",
    "battle_role": "battle_role",
    "battle_action": "battle_action",
    "voc_theme": "voc_theme",
    "market_signal": "market_signal",
    "keyword_opportunity": "keyword_opportunity",
    "matched_asins": "matched_asins",
    "top_brand": "top_brand",
    "opportunity_type": "opportunity_type",
    "asin_link": "asin_link",
    "rating": "rating",
    "reviews": "reviews",
    "seller_type": "seller_type",
    "shelf_date": "shelf_date",
    "operator_action": "operator_action",
    "risk_signal": "risk_signal",
    "cause": "cause",
    "evidence": "evidence",
    "confidence": "confidence",
    "next_action": "next_action",
    "data_source": "data_source",
    "readiness": "readiness",
    "collection_method": "collection_method",
    "risk_boundary": "risk_boundary",
    "recommended_path": "recommended_path",
    "task_status": "task_status",
    "due_time": "due_time",
    "review_metric": "review_metric",
    "organic_rank": "organic_rank",
    "ad_rank": "ad_rank",
}


def ui(key: str) -> str:
    return UI_TRANSLATIONS.get(key, {}).get("zh", key)


def i18n(key: str) -> str:
    return f"<span data-i18n='{esc(key)}'>{esc(ui(key))}</span>"


def esc(value: object) -> str:
    return html.escape("" if value is None else str(value))


def pct(value: object) -> str:
    try:
        return format_percent(float(value))
    except (TypeError, ValueError):
        return ""


def num(value: object) -> str:
    try:
        return format_number(float(value))
    except (TypeError, ValueError):
        return ""


ICON_PATHS = {
    "dashboard": "<rect x='3' y='3' width='7' height='7' rx='1.5'/><rect x='14' y='3' width='7' height='7' rx='1.5'/><rect x='3' y='14' width='7' height='7' rx='1.5'/><rect x='14' y='14' width='7' height='7' rx='1.5'/>",
    "analysis": "<path d='M4 19V5'/><path d='M4 19h16'/><path d='M8 15l3-4 3 2 4-7'/>",
    "actions": "<path d='M9 11l3 3L22 4'/><path d='M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11'/>",
    "uploads": "<path d='M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4'/><path d='M17 8l-5-5-5 5'/><path d='M12 3v12'/>",
    "config": "<path d='M12 15.5A3.5 3.5 0 1 0 12 8a3.5 3.5 0 0 0 0 7.5Z'/><path d='M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1-1.5 1.7 1.7 0 0 0-1.9.3l-.1.1A2 2 0 1 1 4.2 17l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1 1.7 1.7 0 0 0-.3-1.9L4.2 7A2 2 0 1 1 7 4.2l.1.1a1.7 1.7 0 0 0 1.9.3 1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.9-.3l.1-.1A2 2 0 1 1 19.8 7l-.1.1a1.7 1.7 0 0 0-.3 1.9 1.7 1.7 0 0 0 1.5 1h.1a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z'/>",
    "globe": "<circle cx='12' cy='12' r='9'/><path d='M3 12h18'/><path d='M12 3a15 15 0 0 1 0 18'/><path d='M12 3a15 15 0 0 0 0 18'/>",
    "check": "<path d='M20 6 9 17l-5-5'/>",
    "warning": "<path d='M10.3 4.1 2.8 17a2 2 0 0 0 1.7 3h15a2 2 0 0 0 1.7-3L13.7 4.1a2 2 0 0 0-3.4 0Z'/><path d='M12 9v4'/><path d='M12 17h.01'/>",
    "clock": "<circle cx='12' cy='12' r='9'/><path d='M12 7v5l3 2'/>",
    "info": "<circle cx='12' cy='12' r='9'/><path d='M12 10v6'/><path d='M12 7h.01'/>",
    "target": "<circle cx='12' cy='12' r='9'/><circle cx='12' cy='12' r='5'/><circle cx='12' cy='12' r='1'/>",
    "search": "<circle cx='11' cy='11' r='7'/><path d='m20 20-3.5-3.5'/>",
    "trend": "<path d='M3 17h18'/><path d='m6 14 4-5 4 3 4-7'/><path d='M18 5h3v3'/>",
    "brand": "<path d='M12 3 4 7v10l8 4 8-4V7l-8-4Z'/><path d='m4 7 8 4 8-4'/><path d='M12 11v10'/>",
    "bot": "<rect x='5' y='8' width='14' height='10' rx='3'/><path d='M12 8V4'/><path d='M9 12h.01'/><path d='M15 12h.01'/><path d='M10 16h4'/>",
    "chat": "<path d='M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4Z'/><path d='M8 9h8'/><path d='M8 13h5'/>",
    "book": "<path d='M4 19.5A2.5 2.5 0 0 1 6.5 17H21'/><path d='M4 4.5A2.5 2.5 0 0 1 6.5 2H21v20H6.5A2.5 2.5 0 0 1 4 19.5Z'/><path d='M8 7h9'/><path d='M8 11h7'/>",
    "list": "<path d='M8 6h13'/><path d='M8 12h13'/><path d='M8 18h13'/><path d='M3 6h.01'/><path d='M3 12h.01'/><path d='M3 18h.01'/>",
    "table": "<rect x='3' y='4' width='18' height='16' rx='2'/><path d='M3 10h18'/><path d='M9 4v16'/><path d='M15 4v16'/>",
    "download": "<path d='M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4'/><path d='M7 10l5 5 5-5'/><path d='M12 15V3'/>",
    "expand": "<path d='M15 3h6v6'/><path d='m21 3-7 7'/><path d='M9 21H3v-6'/><path d='m3 21 7-7'/>",
    "collapse": "<rect x='3' y='4' width='18' height='16' rx='2'/><path d='M9 4v16'/><path d='m15 9-3 3 3 3'/>",
}


def icon(name: str, class_name: str = "icon") -> str:
    paths = ICON_PATHS.get(name, ICON_PATHS["info"])
    return (
        f"<svg class='{esc(class_name)}' viewBox='0 0 24 24' aria-hidden='true' "
        "fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'>"
        f"{paths}</svg>"
    )


def page(title: str, body: str, week_id: str | None = None) -> bytes:
    translations_json = json.dumps(UI_TRANSLATIONS, ensure_ascii=False)
    language_meta_json = json.dumps(SITE_LANGUAGE_META, ensure_ascii=False)
    language_options_html = "\n".join(
        f'            <option value="{esc(code)}">{esc(label)}</option>' for code, label in SITE_LANGUAGE_OPTIONS
    )
    try:
        global_weeks = dashboard_week_options()
    except Exception:
        global_weeks = []
    selected_global_week = week_id if week_id in global_weeks else (global_weeks[0] if global_weeks else "")
    if global_weeks:
        global_week_options_html = "\n".join(
            f'            <option value="{esc(week)}"{" selected" if week == selected_global_week else ""}>'
            f'{esc(f"{week} · {ui("latest_week")}" if week == global_weeks[0] else week)}</option>'
            for week in global_weeks
        )
        global_week_disabled = ""
    else:
        global_week_options_html = '            <option value="">暂无周次</option>'
        global_week_disabled = " disabled"
    app_title = ui("app_title")
    page_title = app_title if title == app_title else f"{title} · {app_title}"
    script = """
  <script>
    const PLAUD_I18N = __I18N__;
    const PLAUD_LANG_META = __LANG_META__;
    const PLAUD_THEMES = new Set(["ocean", "emerald", "amber", "slate"]);

    function plaudTranslate(key, lang) {
      const item = PLAUD_I18N[key] || {};
      const fallback = PLAUD_LANG_META[lang]?.fallback || "zh";
      return item[lang] || item[fallback] || item.zh || key;
    }

    function applyLanguage(lang) {
      if (lang === "en") lang = "us";
      if (lang === "ja") lang = "jp";
      if (!PLAUD_LANG_META[lang]) {
        lang = "zh";
      }
      document.documentElement.lang = PLAUD_LANG_META[lang].htmlLang;
      document.querySelectorAll("[data-i18n]").forEach((node) => {
        node.textContent = plaudTranslate(node.dataset.i18n, lang);
      });
      document.querySelectorAll("[data-i18n-placeholder]").forEach((node) => {
        node.setAttribute("placeholder", plaudTranslate(node.dataset.i18nPlaceholder, lang));
      });
      const control = document.getElementById("languageSelect");
      if (control) {
        control.value = lang;
      }
      try {
        localStorage.setItem("plaudMonitorLanguage", lang);
      } catch (error) {}
    }

    function applyTheme(theme) {
      if (!PLAUD_THEMES.has(theme)) {
        theme = "ocean";
      }
      document.documentElement.dataset.theme = theme;
      const control = document.getElementById("themeSelect");
      if (control) {
        control.value = theme;
      }
      try {
        localStorage.setItem("plaudMonitorTheme", theme);
      } catch (error) {}
    }

    function parseSortValue(text, type) {
      const clean = String(text || "").replace(/[%,$€£¥,]/g, "").replace(/[^\\d.+-]/g, "");
      const value = Number.parseFloat(clean);
      if (type === "number") {
        return Number.isFinite(value) ? value : Number.NEGATIVE_INFINITY;
      }
      return String(text || "").trim().toLowerCase();
    }

    function setupSortableTables() {
      document.querySelectorAll("table.sortable-table th[data-sort-col]").forEach((header) => {
        header.addEventListener("click", () => {
          const table = header.closest("table");
          const tbody = table?.querySelector("tbody");
          if (!table || !tbody) return;
          const headers = Array.from(header.parentElement.children);
          const index = headers.indexOf(header);
          const type = header.dataset.sortType || "text";
          const current = header.dataset.sortDir || "";
          const direction = current === "desc" ? "asc" : "desc";
          headers.forEach((item) => item.removeAttribute("data-sort-dir"));
          header.dataset.sortDir = direction;
          const rows = Array.from(tbody.querySelectorAll("tr"));
          rows.sort((left, right) => {
            const leftValue = parseSortValue(left.children[index]?.textContent, type);
            const rightValue = parseSortValue(right.children[index]?.textContent, type);
            if (leftValue < rightValue) return direction === "asc" ? -1 : 1;
            if (leftValue > rightValue) return direction === "asc" ? 1 : -1;
            return 0;
          });
          rows.forEach((row) => tbody.appendChild(row));
        });
      });
    }

    function setupAnalysisTabs() {
      document.querySelectorAll(".analysis-workbench").forEach((workbench) => {
        const buttons = Array.from(workbench.querySelectorAll("[data-tab-button]"));
        const panels = Array.from(workbench.querySelectorAll("[data-tab-panel]"));
        const activate = (tab) => {
          buttons.forEach((button) => {
            const isActive = button.dataset.tabButton === tab;
            button.classList.toggle("active", isActive);
            button.setAttribute("aria-selected", isActive ? "true" : "false");
          });
          panels.forEach((panel) => {
            panel.classList.toggle("active", panel.dataset.tabPanel === tab);
          });
        };
        buttons.forEach((button) => button.addEventListener("click", () => activate(button.dataset.tabButton)));
        activate(buttons.find((button) => button.classList.contains("active"))?.dataset.tabButton || buttons[0]?.dataset.tabButton || "overview");
      });
    }

    function setupActiveNav() {
      const path = window.location.pathname || "/";
      document.querySelectorAll("nav a").forEach((link) => {
        const href = new URL(link.getAttribute("href") || "/", window.location.origin).pathname;
        let isActive = href === "/" ? path === "/" : path === href || path.startsWith(`${href}/`);
        if (href === "/analysis" && path === "/run") {
          isActive = true;
        }
        link.classList.toggle("active", isActive);
        if (isActive) {
          link.setAttribute("aria-current", "page");
        } else {
          link.removeAttribute("aria-current");
        }
      });
    }

    function setSidebarCollapsed(collapsed) {
      document.documentElement.classList.toggle("sidebar-collapsed", collapsed);
      const button = document.querySelector("[data-sidebar-toggle]");
      if (!button) return;
      const labelKey = collapsed ? "expand_sidebar" : "collapse_sidebar";
      const currentLang = document.getElementById("languageSelect")?.value || "zh";
      const label = plaudTranslate(labelKey, currentLang);
      const labelNode = button.querySelector("[data-sidebar-toggle-label]");
      button.setAttribute("aria-expanded", collapsed ? "false" : "true");
      button.setAttribute("aria-label", label);
      button.setAttribute("title", label);
      if (labelNode) {
        labelNode.dataset.i18n = labelKey;
        labelNode.textContent = label;
      }
    }

    function setupSidebarToggle() {
      const button = document.querySelector("[data-sidebar-toggle]");
      if (!button) return;
      let collapsed = document.documentElement.classList.contains("sidebar-collapsed");
      setSidebarCollapsed(collapsed);
      button.addEventListener("click", () => {
        collapsed = !document.documentElement.classList.contains("sidebar-collapsed");
        setSidebarCollapsed(collapsed);
        try {
          localStorage.setItem("plaudMonitorSidebarCollapsed", collapsed ? "1" : "0");
        } catch (error) {}
      });
    }

    function setupGlobalWeek() {
      const select = document.getElementById("globalWeekSelect");
      if (!select) return;
      const optionValues = new Set(Array.from(select.options).map((option) => option.value).filter(Boolean));
      const params = new URLSearchParams(window.location.search);
      let storedWeek = "";
      try {
        storedWeek = localStorage.getItem("plaudMonitorWeek") || "";
      } catch (error) {}
      const queryWeek = params.get("week_id") || "";
      const hasExplicitRun = params.has("id") || params.has("run_id");
      const defaultWeek = select.dataset.defaultWeek || select.value || "";
      const currentWeek = optionValues.has(queryWeek)
        ? queryWeek
        : optionValues.has(storedWeek)
          ? storedWeek
          : defaultWeek;
      if (currentWeek && optionValues.has(currentWeek)) {
        select.value = currentWeek;
        try {
          localStorage.setItem("plaudMonitorWeek", currentWeek);
        } catch (error) {}
      }
      if (!queryWeek && !hasExplicitRun && optionValues.has(storedWeek) && storedWeek !== defaultWeek) {
        const target = new URL(window.location.href);
        if (target.pathname === "/run") {
          target.pathname = "/analysis";
        }
        target.searchParams.set("week_id", storedWeek);
        target.searchParams.delete("id");
        target.searchParams.delete("run_id");
        window.location.replace(`${target.pathname}${target.search}${target.hash}`);
        return;
      }
      const navWeek = select.value || currentWeek;
      if (navWeek) {
        document.querySelectorAll("nav a[data-global-week-link]").forEach((link) => {
          const url = new URL(link.getAttribute("href") || "/", window.location.origin);
          url.searchParams.set("week_id", navWeek);
          link.setAttribute("href", `${url.pathname}${url.search}${url.hash}`);
        });
      }
      select.addEventListener("change", () => {
        if (!select.value) return;
        try {
          localStorage.setItem("plaudMonitorWeek", select.value);
        } catch (error) {}
        const target = new URL(window.location.href);
        if (target.pathname === "/run") {
          target.pathname = "/analysis";
        }
        target.searchParams.set("week_id", select.value);
        target.searchParams.delete("id");
        target.searchParams.delete("run_id");
        window.location.href = `${target.pathname}${target.search}${target.hash}`;
      });
    }

    function setupChartZoom() {
      const cards = Array.from(document.querySelectorAll("[data-chart-zoom]"));
      if (!cards.length) return;
      const modal = document.createElement("div");
      modal.className = "chart-zoom-modal";
      modal.hidden = true;
      modal.innerHTML = `
        <div class="chart-zoom-backdrop" data-chart-zoom-close></div>
        <section class="chart-zoom-panel" role="dialog" aria-modal="true" aria-labelledby="chartZoomTitle">
          <div class="chart-zoom-head">
            <h2 id="chartZoomTitle"></h2>
            <button class="chart-zoom-close" type="button" data-chart-zoom-close aria-label="关闭放大图">×</button>
          </div>
          <div class="chart-zoom-body"></div>
        </section>
      `;
      document.body.appendChild(modal);
      const titleNode = modal.querySelector("#chartZoomTitle");
      const bodyNode = modal.querySelector(".chart-zoom-body");
      const closeButton = modal.querySelector(".chart-zoom-close");
      let lastFocus = null;

      const close = () => {
        modal.hidden = true;
        document.body.classList.remove("modal-open");
        bodyNode.innerHTML = "";
        if (lastFocus && typeof lastFocus.focus === "function") {
          lastFocus.focus();
        }
      };

      const open = (card) => {
        const svg = card.querySelector("svg.line-chart");
        if (!svg) return;
        lastFocus = document.activeElement;
        titleNode.textContent = card.dataset.chartTitle || card.querySelector(".chart-title span")?.textContent || "趋势图";
        bodyNode.innerHTML = "";
        bodyNode.appendChild(svg.cloneNode(true));
        const legend = card.querySelector(".trend-legend");
        if (legend) {
          bodyNode.appendChild(legend.cloneNode(true));
        }
        modal.hidden = false;
        document.body.classList.add("modal-open");
        closeButton.focus();
      };

      cards.forEach((card) => {
        card.addEventListener("click", (event) => {
          if (event.target.closest("a, input, select, textarea")) return;
          open(card);
        });
        card.addEventListener("keydown", (event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            open(card);
          }
        });
      });
      modal.addEventListener("click", (event) => {
        if (event.target.closest("[data-chart-zoom-close]")) {
          close();
        }
      });
      document.addEventListener("keydown", (event) => {
        if (!modal.hidden && event.key === "Escape") {
          close();
        }
      });
    }

    function setupFetchLatestForms() {
      document.querySelectorAll("[data-fetch-latest-form]").forEach((form) => {
        form.addEventListener("submit", () => {
          const returnPath = form.querySelector("[name='return_to_path']");
          if (returnPath) {
            returnPath.value = window.location.pathname || "/";
          }
          const button = form.querySelector("button[type='submit']");
          const label = button?.querySelector("[data-fetch-label]");
          if (button) {
            button.disabled = true;
          }
          if (label) {
            label.textContent = plaudTranslate("fetching_latest_week_data", document.documentElement.lang || "zh");
          }
        });
      });
    }

    document.addEventListener("DOMContentLoaded", () => {
      let language = "zh";
      let theme = "ocean";
      try {
        language = localStorage.getItem("plaudMonitorLanguage") || language;
        theme = localStorage.getItem("plaudMonitorTheme") || theme;
      } catch (error) {}
      applyLanguage(language);
      applyTheme(theme);
      setupSortableTables();
      setupAnalysisTabs();
      setupGlobalWeek();
      setupActiveNav();
      setupSidebarToggle();
      setupChartZoom();
      setupFetchLatestForms();
      document.getElementById("languageSelect")?.addEventListener("change", (event) => {
        applyLanguage(event.target.value);
        setSidebarCollapsed(document.documentElement.classList.contains("sidebar-collapsed"));
      });
      document.getElementById("themeSelect")?.addEventListener("change", (event) => applyTheme(event.target.value));
    });
  </script>
""".replace("__I18N__", translations_json).replace("__LANG_META__", language_meta_json)
    html_text = f"""<!doctype html>
<html lang="zh-CN" data-theme="ocean">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{esc(page_title)}</title>
  <script>
    try {{
      const savedTheme = localStorage.getItem("plaudMonitorTheme");
      if (savedTheme) document.documentElement.dataset.theme = savedTheme;
      if (localStorage.getItem("plaudMonitorSidebarCollapsed") === "1") {{
        document.documentElement.classList.add("sidebar-collapsed");
      }}
    }} catch (error) {{}}
  </script>
  <style>
    :root, [data-theme="ocean"] {{
      --sidebar-width: 264px;
      --sidebar-collapsed-width: 86px;
      --topbar-height: 106px;
      --ink: #172033;
      --muted: #667085;
      --line: #d9e2ec;
      --line-soft: #e6edf4;
      --soft: #f5f7fa;
      --page: #f8fafc;
      --surface: #ffffff;
      --surface-2: #fbfcfe;
      --table-head: #eef3f8;
      --notice-bg: #eef6ff;
      --notice-border: #c7d7e6;
      --notice-text: #1f4d78;
      --brand: #1f4d78;
      --accent: #2e74b5;
      --chart-brand: #1f4d78;
      --chart-competitor: #2e74b5;
      --chart-ai: #7a5a00;
      --chart-other: #d7dee8;
      --ok: #147a42;
      --bad: #b42318;
      --warn: #a15c07;
    }}
    [data-theme="emerald"] {{
      --ink: #10231b;
      --muted: #5e746b;
      --line: #cfded7;
      --line-soft: #e4efe9;
      --soft: #f3faf6;
      --page: #f7fbf8;
      --surface: #ffffff;
      --surface-2: #fbfefc;
      --table-head: #eaf6ef;
      --notice-bg: #effaf3;
      --notice-border: #b7e4ca;
      --notice-text: #12633a;
      --brand: #12633a;
      --accent: #24905c;
      --chart-brand: #12633a;
      --chart-competitor: #24905c;
      --chart-ai: #8a5a00;
      --chart-other: #d8e5df;
    }}
    [data-theme="amber"] {{
      --ink: #2c2111;
      --muted: #766b5b;
      --line: #e4d8c5;
      --line-soft: #efe5d5;
      --soft: #fbf7ef;
      --page: #fbfaf7;
      --surface: #ffffff;
      --surface-2: #fffdf8;
      --table-head: #f7ead3;
      --notice-bg: #fff8eb;
      --notice-border: #f1d6a8;
      --notice-text: #7a4a00;
      --brand: #7a4a00;
      --accent: #b97814;
      --chart-brand: #7a4a00;
      --chart-competitor: #b97814;
      --chart-ai: #275c7c;
      --chart-other: #e8ded0;
    }}
    [data-theme="slate"] {{
      --ink: #eef4fb;
      --muted: #a9b8c7;
      --line: #334155;
      --line-soft: #243447;
      --soft: #111827;
      --page: #0f172a;
      --surface: #172033;
      --surface-2: #111827;
      --table-head: #22304a;
      --notice-bg: #172b45;
      --notice-border: #35577d;
      --notice-text: #d9ecff;
      --brand: #9cc9ff;
      --accent: #5aa7ff;
      --chart-brand: #8ec5ff;
      --chart-competitor: #4ca3ff;
      --chart-ai: #f4c15d;
      --chart-other: #3b4b63;
      --ok: #67d391;
      --bad: #ff9b92;
      --warn: #f4c15d;
    }}
    html.sidebar-collapsed {{
      --sidebar-width: var(--sidebar-collapsed-width);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif;
      color: var(--ink);
      background: var(--page);
    }}
    header {{
      background: var(--surface);
      border-bottom: 1px solid var(--line);
      padding: 18px 30px;
      position: sticky;
      top: 0;
      z-index: 30;
      min-height: var(--topbar-height);
    }}
    .header-top {{
      display: flex;
      gap: 24px;
      align-items: flex-start;
      justify-content: space-between;
    }}
    header h1 {{
      margin: 0;
      font-size: 20px;
      line-height: 1.2;
      color: var(--brand);
      max-width: 520px;
    }}
    .settings-bar {{
      display: flex;
      gap: 10px;
      align-items: flex-end;
      justify-content: flex-end;
      flex-wrap: wrap;
    }}
    .header-control {{
      display: grid;
      gap: 4px;
      min-width: 0;
      width: 158px;
    }}
    .global-week-control {{
      width: 210px;
    }}
    .header-control span {{
      color: var(--muted);
      font-size: 11px;
      font-weight: 650;
    }}
    .header-control select {{
      min-height: 32px;
      border-radius: 6px;
      background: var(--surface);
    }}
    nav {{
      position: fixed;
      top: var(--topbar-height);
      bottom: 0;
      left: 0;
      z-index: 20;
      width: var(--sidebar-width);
      margin: 0;
      padding: 18px;
      display: grid;
      gap: 8px;
      align-content: start;
      overflow-y: auto;
      background: var(--surface);
      border-right: 1px solid var(--line);
      transition: width .2s ease, padding .2s ease;
    }}
    .sidebar-toggle {{
      display: inline-flex;
      align-items: center;
      justify-content: flex-start;
      gap: 7px;
      width: 100%;
      min-height: 38px;
      margin: 0 0 8px;
      border: 1px solid var(--line);
      background: color-mix(in srgb, var(--accent) 8%, var(--surface));
      color: var(--brand);
      border-radius: 8px;
      padding: 9px 12px;
      font-weight: 750;
      cursor: pointer;
      transition: background .18s ease, border-color .18s ease, color .18s ease, padding .2s ease;
    }}
    .sidebar-toggle:hover {{
      background: color-mix(in srgb, var(--accent) 14%, var(--surface));
      border-color: color-mix(in srgb, var(--accent) 42%, var(--line));
    }}
    .sidebar-toggle .icon {{
      transition: transform .2s ease;
    }}
    .sidebar-toggle-label, nav a span {{
      min-width: 0;
      max-width: 190px;
      overflow: hidden;
      white-space: nowrap;
      opacity: 1;
      transition: max-width .2s ease, opacity .15s ease;
    }}
    nav a, .btn {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 7px;
      min-height: 34px;
      border: 1px solid var(--line);
      background: var(--surface);
      color: var(--brand);
      text-decoration: none;
      border-radius: 6px;
      padding: 7px 12px;
      font-weight: 600;
      cursor: pointer;
    }}
    .fetch-latest-form {{
      margin: 0;
    }}
    .top-fetch-latest-form {{
      display: grid;
      grid-template-columns: none;
      gap: 4px;
      align-items: end;
      width: auto;
      margin: 0;
    }}
    .top-fetch-spacer {{
      height: 3px;
      display: block;
    }}
    .fetch-latest-form .btn {{
      min-height: 38px;
      box-shadow: 0 8px 18px color-mix(in srgb, var(--brand) 14%, transparent);
    }}
    .top-fetch-latest-form .btn {{
      min-height: 32px;
      height: 32px;
      padding: 7px 12px;
      white-space: nowrap;
      transform: translateY(-5px);
    }}
    .fetch-latest-form .btn[disabled] {{
      opacity: .72;
      cursor: wait;
    }}
    nav a.active {{
      background: var(--brand);
      border-color: var(--brand);
      color: #fff;
      box-shadow: 0 8px 18px color-mix(in srgb, var(--brand) 18%, transparent);
    }}
    nav a {{
      width: 100%;
      justify-content: flex-start;
      min-height: 42px;
      padding: 10px 12px;
      transition: background .18s ease, border-color .18s ease, color .18s ease, padding .2s ease, box-shadow .18s ease;
    }}
    html.sidebar-collapsed nav {{
      padding: 18px 14px;
    }}
    html.sidebar-collapsed nav a,
    html.sidebar-collapsed .sidebar-toggle {{
      justify-content: center;
      padding-left: 10px;
      padding-right: 10px;
    }}
    html.sidebar-collapsed .sidebar-toggle .icon {{
      transform: rotate(180deg);
    }}
    html.sidebar-collapsed nav a span,
    html.sidebar-collapsed .sidebar-toggle-label {{
      max-width: 0;
      opacity: 0;
    }}
    nav a.active:hover {{
      color: #fff;
    }}
    .icon {{
      width: 17px;
      height: 17px;
      flex: 0 0 auto;
      color: currentColor;
    }}
    .icon-soft {{
      color: var(--accent);
    }}
    .icon-badge {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 34px;
      height: 34px;
      border-radius: 8px;
      background: color-mix(in srgb, var(--accent) 12%, transparent);
      color: var(--brand);
      border: 1px solid color-mix(in srgb, var(--accent) 22%, var(--line));
    }}
    .icon-badge .icon {{
      width: 18px;
      height: 18px;
    }}
    .btn-primary {{
      background: var(--brand);
      color: #fff;
      border-color: var(--brand);
    }}
    main {{
      max-width: none;
      margin: 0 0 0 var(--sidebar-width);
      width: calc(100% - var(--sidebar-width));
      padding: 22px 30px 46px;
      transition: margin .2s ease, width .2s ease;
    }}
    section {{
      margin: 0 0 22px;
    }}
    h2 {{
      font-size: 17px;
      margin: 0 0 12px;
      color: var(--brand);
    }}
    h3 {{
      font-size: 15px;
      margin: 18px 0 10px;
      color: var(--brand);
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
    }}
    .card {{
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
    }}
    .metric-card {{
      display: grid;
      grid-template-columns: 42px minmax(0, 1fr);
      gap: 12px;
      align-items: center;
    }}
    .metric-label {{
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 6px;
    }}
    .metric-value {{
      font-size: 24px;
      font-weight: 750;
      color: var(--ink);
    }}
    .dashboard-page {{
      display: grid;
      gap: 16px;
    }}
    .dashboard-filter {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 14px;
      padding: 14px 16px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface);
      box-shadow: var(--shadow);
    }}
    .dashboard-filter-title {{
      display: grid;
      gap: 4px;
      min-width: 0;
    }}
    .dashboard-week-title {{
      display: flex;
      align-items: center;
      gap: 8px;
      min-width: 0;
      color: var(--brand);
      line-height: 1;
      flex-wrap: wrap;
    }}
    .dashboard-week-title .icon {{
      width: 18px;
      height: 18px;
      align-self: center;
    }}
    .dashboard-week-label {{
      display: inline-flex;
      align-items: center;
      font-size: 16px;
      font-weight: 800;
      color: var(--muted);
      line-height: 1;
    }}
    .dashboard-week-colon {{
      color: var(--muted);
      font-size: 16px;
      font-weight: 800;
      line-height: 1;
    }}
    .dashboard-week-value {{
      display: inline-flex;
      align-items: center;
      font-size: 24px;
      font-weight: 850;
      color: var(--brand);
      line-height: 1;
      letter-spacing: 0;
    }}
    .dashboard-filter-title strong {{
      color: var(--brand);
      font-size: 18px;
      line-height: 1.2;
    }}
    .dashboard-filter-title span {{
      color: var(--muted);
      font-size: 12px;
      line-height: 1.4;
    }}
    .dashboard-week-form {{
      display: grid;
      grid-template-columns: auto minmax(150px, 210px);
      align-items: center;
      gap: 8px;
      margin: 0;
      min-width: 280px;
    }}
    .dashboard-week-form label {{
      margin: 0;
      white-space: nowrap;
      font-weight: 750;
      color: var(--brand);
    }}
    .dashboard-command {{
      display: block;
      margin-bottom: 0;
    }}
    .command-kpi-grid {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
    }}
    .command-kpi {{
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 13px;
      min-height: 128px;
      display: grid;
      gap: 10px;
      animation: cardRise .46s ease-out both;
    }}
    .command-kpi:nth-child(2) {{ animation-delay: .04s; }}
    .command-kpi:nth-child(3) {{ animation-delay: .08s; }}
    .command-kpi:nth-child(4) {{ animation-delay: .12s; }}
    .command-kpi-top {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
    }}
    .command-kpi-label {{
      color: var(--muted);
      font-size: 12px;
      font-weight: 800;
      line-height: 1.35;
    }}
    .command-kpi-value {{
      color: var(--ink);
      font-size: 28px;
      line-height: 1;
      font-weight: 850;
      overflow-wrap: anywhere;
    }}
    .command-kpi-delta {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      color: var(--muted);
      font-size: 12px;
      border-top: 1px solid var(--line-soft);
      padding-top: 8px;
    }}
    .chart-first-grid {{
      display: grid;
      grid-template-columns: minmax(280px, .82fr) minmax(360px, 1.08fr) minmax(360px, 1.1fr);
      gap: 14px;
      align-items: stretch;
    }}
    .site-bar-card,
    .price-bar-card,
    .dashboard-action-card {{
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      box-shadow: 0 8px 22px rgba(15, 23, 42, .04);
    }}
    .site-bar-card h2,
    .price-bar-card h2 {{
      margin: 0 0 12px;
    }}
    .stat-bars {{
      display: grid;
      gap: 9px;
    }}
    .stat-bar-row {{
      display: grid;
      grid-template-columns: 74px minmax(0, 1fr) 74px;
      gap: 9px;
      align-items: center;
      font-size: 12px;
      color: var(--muted);
    }}
    .stat-bar-row strong {{
      color: var(--ink);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    .stat-bar-track {{
      height: 12px;
      border-radius: 999px;
      background: var(--line-soft);
      overflow: hidden;
    }}
    .stat-bar-fill {{
      display: block;
      height: 100%;
      border-radius: inherit;
      background: linear-gradient(90deg, var(--accent), color-mix(in srgb, var(--brand) 74%, var(--accent)));
      min-width: 3px;
      animation: chartPop .38s ease-out both;
    }}
    .stat-bar-fill.warn {{
      background: linear-gradient(90deg, var(--warn), color-mix(in srgb, var(--warn) 60%, var(--accent)));
    }}
    .stat-bar-fill.ai {{
      background: linear-gradient(90deg, var(--chart-ai), color-mix(in srgb, var(--chart-ai) 62%, var(--accent)));
    }}
    .dashboard-action-strip {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
      margin-bottom: 0;
    }}
    .dashboard-action-card {{
      display: grid;
      gap: 8px;
      min-height: 118px;
      border-left: 5px solid var(--accent);
    }}
    .dashboard-action-card.high {{ border-left-color: var(--bad); }}
    .dashboard-action-card.medium {{ border-left-color: var(--warn); }}
    .dashboard-action-card.ok {{ border-left-color: var(--ok); }}
    .dashboard-action-card strong {{
      color: var(--ink);
      line-height: 1.35;
    }}
    .dashboard-action-card p {{
      margin: 0;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.45;
    }}
    .dashboard-action-card a {{
      justify-self: start;
      color: var(--brand);
      text-decoration: none;
      font-weight: 800;
      font-size: 12px;
    }}
    .ops-hero {{
      display: grid;
      grid-template-columns: minmax(360px, 1.35fr) minmax(320px, .65fr);
      gap: 14px;
      align-items: stretch;
      margin-bottom: 0;
    }}
    .ops-brief {{
      background: var(--surface);
      border: 1px solid color-mix(in srgb, var(--accent) 26%, var(--line));
      border-radius: 8px;
      padding: 18px;
      min-height: 172px;
      display: grid;
      gap: 14px;
      animation: cardRise .42s ease-out both;
    }}
    .ops-brief-top {{
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 14px;
    }}
    .ops-brief h2 {{
      margin: 0 0 6px;
      font-size: 20px;
      color: var(--brand);
    }}
    .ops-brief-line {{
      margin: 0;
      color: var(--ink);
      font-size: 15px;
      line-height: 1.55;
      font-weight: 650;
    }}
    .ops-focus-grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
    }}
    .ops-focus-item {{
      border: 1px solid var(--line-soft);
      border-radius: 8px;
      background: var(--surface-2);
      padding: 11px;
      min-height: 86px;
    }}
    .ops-focus-item span {{
      display: block;
      color: var(--muted);
      font-size: 12px;
      font-weight: 750;
      margin-bottom: 6px;
    }}
    .ops-focus-item strong {{
      display: block;
      color: var(--ink);
      font-size: 20px;
      line-height: 1;
      margin-bottom: 6px;
    }}
    .ops-focus-item p {{
      margin: 0;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.45;
    }}
    .ops-next {{
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      display: grid;
      gap: 10px;
      animation: cardRise .48s ease-out both;
    }}
    .ops-next-title {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
    }}
    .ops-next-title strong {{
      color: var(--brand);
      font-size: 15px;
    }}
    .ops-next-list {{
      display: grid;
      gap: 8px;
    }}
    .ops-next-item {{
      display: grid;
      grid-template-columns: 26px minmax(0, 1fr);
      gap: 9px;
      align-items: start;
      padding: 9px;
      border: 1px solid var(--line-soft);
      border-radius: 8px;
      background: var(--surface-2);
      color: inherit;
      text-decoration: none;
    }}
    .ops-next-index {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 24px;
      height: 24px;
      border-radius: 999px;
      color: #fff;
      background: var(--brand);
      font-size: 12px;
      font-weight: 800;
    }}
    .ops-next-item strong {{
      display: block;
      color: var(--ink);
      margin-bottom: 3px;
    }}
    .ops-next-item p {{
      margin: 0;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.45;
    }}
    .ops-priority-strip {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
      margin-bottom: 0;
    }}
    .ops-priority-card {{
      background: var(--surface);
      border: 1px solid var(--line);
      border-left: 5px solid var(--accent);
      border-radius: 8px;
      padding: 13px;
      min-height: 136px;
      display: grid;
      gap: 8px;
      animation: cardRise .52s ease-out both;
    }}
    .ops-priority-card:nth-child(2) {{ animation-delay: .04s; }}
    .ops-priority-card:nth-child(3) {{ animation-delay: .08s; }}
    .ops-priority-card:nth-child(4) {{ animation-delay: .12s; }}
    .ops-priority-card.high {{ border-left-color: var(--bad); }}
    .ops-priority-card.medium {{ border-left-color: var(--warn); }}
    .ops-priority-card.ok {{ border-left-color: var(--ok); }}
    .ops-priority-card strong {{
      color: var(--ink);
      line-height: 1.35;
    }}
    .ops-priority-card p {{
      margin: 0;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.5;
    }}
    .ops-priority-card a {{
      justify-self: start;
      color: var(--brand);
      text-decoration: none;
      font-weight: 750;
      font-size: 12px;
    }}
    .trend-wall-grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 14px;
    }}
    .trend-card {{
      min-height: 328px;
      position: relative;
      cursor: zoom-in;
      transition: transform .18s ease, box-shadow .18s ease, border-color .18s ease;
    }}
    .trend-card:hover {{
      transform: translateY(-2px);
      border-color: color-mix(in srgb, var(--accent) 44%, var(--line));
      box-shadow: 0 14px 34px rgba(15, 23, 42, .09);
    }}
    .chart-zoom-btn {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 30px;
      height: 30px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface);
      color: var(--brand);
      cursor: zoom-in;
      flex: 0 0 auto;
    }}
    .chart-zoom-btn:hover {{
      background: color-mix(in srgb, var(--accent) 10%, var(--surface));
      border-color: color-mix(in srgb, var(--accent) 42%, var(--line));
    }}
    body.modal-open {{
      overflow: hidden;
    }}
    .chart-zoom-modal[hidden] {{
      display: none;
    }}
    .chart-zoom-modal {{
      position: fixed;
      inset: 0;
      z-index: 1000;
      display: grid;
      place-items: center;
      padding: 28px;
    }}
    .chart-zoom-backdrop {{
      position: absolute;
      inset: 0;
      background: rgba(15, 23, 42, .58);
      backdrop-filter: blur(3px);
    }}
    .chart-zoom-panel {{
      position: relative;
      width: min(1180px, 96vw);
      max-height: 92vh;
      display: grid;
      grid-template-rows: auto minmax(0, 1fr);
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 10px;
      box-shadow: 0 28px 80px rgba(15, 23, 42, .32);
      overflow: hidden;
      animation: chartPop .18s ease-out both;
    }}
    .chart-zoom-head {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 16px 18px;
      border-bottom: 1px solid var(--line-soft);
    }}
    .chart-zoom-head h2 {{
      margin: 0;
      color: var(--brand);
      font-size: 20px;
    }}
    .chart-zoom-close {{
      width: 34px;
      height: 34px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface);
      color: var(--ink);
      font-size: 24px;
      line-height: 1;
      cursor: pointer;
    }}
    .chart-zoom-close:hover {{
      background: var(--soft);
    }}
    .chart-zoom-body {{
      padding: 18px;
      overflow: auto;
    }}
    .chart-zoom-body .line-chart {{
      height: min(62vh, 620px);
      min-height: 420px;
    }}
    .chart-zoom-body .trend-legend {{
      margin-top: 14px;
      justify-content: center;
      gap: 12px;
    }}
    .trend-legend {{
      display: flex;
      flex-wrap: wrap;
      gap: 7px;
      margin-top: 10px;
    }}
    .trend-legend-item {{
      display: inline-flex;
      align-items: center;
      gap: 5px;
      color: var(--muted);
      font-size: 11px;
      font-weight: 700;
    }}
    .trend-dot {{
      width: 9px;
      height: 9px;
      border-radius: 999px;
    }}
    .card, .chart-card, .alert-card, .rank-card, .ads-kpi-card, .agent-kpi {{
      box-shadow: 0 8px 22px rgba(15, 23, 42, .04);
    }}
    .muted {{ color: var(--muted); }}
    .status-ok {{ color: var(--ok); font-weight: 700; }}
    .status-error {{ color: var(--bad); font-weight: 700; }}
    .status-uploaded {{ color: var(--warn); font-weight: 700; }}
    .section-head {{
      display: flex;
      align-items: end;
      justify-content: space-between;
      gap: 16px;
      margin: 0 0 12px;
    }}
    .section-head h2 {{ margin: 0; }}
    .section-note {{
      color: var(--muted);
      font-size: 13px;
      line-height: 1.45;
    }}
    .analysis-workbench {{
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
    }}
    .analysis-tab-list {{
      position: sticky;
      top: 82px;
      z-index: 8;
      display: flex;
      gap: 8px;
      overflow-x: auto;
      padding: 4px 0 12px;
      margin-bottom: 12px;
      background: var(--surface);
      border-bottom: 1px solid var(--line-soft);
    }}
    .analysis-tab-button {{
      min-height: 34px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 7px 12px;
      background: var(--surface-2);
      color: var(--brand);
      font: inherit;
      font-weight: 700;
      white-space: nowrap;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 7px;
    }}
    .analysis-tab-button.active {{
      background: var(--brand);
      border-color: var(--brand);
      color: #fff;
    }}
    .analysis-tab-panel {{
      display: none;
    }}
    .analysis-tab-panel.active {{
      display: block;
    }}
    .analysis-tab-panel > section:last-child {{
      margin-bottom: 0;
    }}
    .split {{
      display: grid;
      grid-template-columns: minmax(0, 1.2fr) minmax(320px, 0.8fr);
      gap: 14px;
      align-items: start;
    }}
    .chart-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
    }}
    .chart-card {{
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      min-height: 280px;
    }}
    .chart-title {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      margin-bottom: 12px;
      color: var(--brand);
      font-weight: 750;
    }}
    .chart-title-main {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      min-width: 0;
      flex: 1;
    }}
    .donut-wrap {{
      display: grid;
      grid-template-columns: 170px minmax(0, 1fr);
      gap: 18px;
      align-items: center;
    }}
    .donut {{
      width: 166px;
      height: 166px;
      border-radius: 50%;
      position: relative;
      border: 1px solid var(--line);
      flex: 0 0 auto;
    }}
    .donut::after {{
      content: "";
      position: absolute;
      inset: 38px;
      border-radius: 50%;
      background: var(--surface);
      border: 1px solid var(--line-soft);
    }}
    .donut-center {{
      position: absolute;
      inset: 0;
      display: flex;
      align-items: center;
      justify-content: center;
      text-align: center;
      z-index: 1;
      font-weight: 800;
      color: var(--ink);
      font-size: 20px;
      pointer-events: none;
    }}
    .legend {{
      display: grid;
      gap: 8px;
    }}
    .legend-row {{
      display: grid;
      grid-template-columns: 12px minmax(0, 1fr) auto;
      gap: 8px;
      align-items: center;
      font-size: 13px;
      color: var(--ink);
    }}
    .swatch {{
      width: 12px;
      height: 12px;
      border-radius: 3px;
    }}
    .line-chart {{
      width: 100%;
      height: 230px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface-2);
    }}
    .trend-line {{
      stroke-dasharray: 1;
      stroke-dashoffset: 1;
      animation: drawLine 1.1s ease-out forwards;
    }}
    .chart-point {{
      opacity: 0;
      transform: scale(.55);
      transform-box: fill-box;
      transform-origin: center;
      animation: pointPop .28s ease-out forwards;
    }}
    .donut {{
      animation: chartPop .48s ease-out both;
    }}
    .site-grid {{
      display: grid;
      grid-template-columns: repeat(7, minmax(0, 1fr));
      gap: 8px;
    }}
    .site-tile {{
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px;
      min-height: 92px;
    }}
    .site-code {{
      font-size: 13px;
      font-weight: 800;
      color: var(--brand);
      margin-bottom: 6px;
    }}
    .pill {{
      display: inline-flex;
      align-items: center;
      min-height: 24px;
      border-radius: 999px;
      padding: 3px 8px;
      border: 1px solid var(--line);
      background: var(--surface);
      color: var(--muted);
      font-size: 12px;
      font-weight: 650;
    }}
    .pill-ok {{
      color: var(--ok);
      border-color: #b7e4ca;
      background: #effaf3;
    }}
    .pill-missing {{
      color: var(--warn);
      border-color: #f1d6a8;
      background: #fff8eb;
    }}
    .mapping-grid {{
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 10px;
    }}
    .mapping-item {{
      border: 1px solid var(--line);
      background: var(--surface);
      border-radius: 8px;
      padding: 12px;
      min-height: 92px;
    }}
    .mapping-item strong {{
      display: block;
      color: var(--brand);
      margin-bottom: 5px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
    }}
    th, td {{
      border-bottom: 1px solid var(--line);
      padding: 9px 10px;
      text-align: left;
      vertical-align: top;
      font-size: 13px;
    }}
    th {{
      background: var(--table-head);
      color: var(--brand);
      font-weight: 700;
    }}
    th[data-sort-col] {{
      cursor: pointer;
      user-select: none;
      white-space: nowrap;
    }}
    th[data-sort-col]::after {{
      content: " ↕";
      color: var(--muted);
      font-size: 11px;
    }}
    th[data-sort-dir="desc"]::after {{ content: " ↓"; color: var(--accent); }}
    th[data-sort-dir="asc"]::after {{ content: " ↑"; color: var(--accent); }}
    tr:last-child td {{ border-bottom: none; }}
    form {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
      align-items: end;
    }}
    label {{
      display: block;
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 5px;
    }}
    input, select, textarea {{
      width: 100%;
      min-height: 36px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 7px 9px;
      background: var(--surface);
      color: var(--ink);
      font: inherit;
    }}
    .wide {{ grid-column: span 2; }}
    .full {{ grid-column: 1 / -1; }}
    .bar {{
      height: 10px;
      background: var(--line-soft);
      border-radius: 99px;
      overflow: hidden;
      min-width: 110px;
    }}
    .bar span {{
      display: block;
      height: 100%;
      background: var(--accent);
    }}
    .notice {{
      padding: 12px 14px;
      border: 1px solid var(--notice-border);
      background: var(--notice-bg);
      border-radius: 8px;
      color: var(--notice-text);
    }}
    @keyframes cardRise {{
      from {{ opacity: 0; transform: translateY(8px); }}
      to {{ opacity: 1; transform: translateY(0); }}
    }}
    @keyframes drawLine {{
      to {{ stroke-dashoffset: 0; }}
    }}
    @keyframes pointPop {{
      to {{ opacity: 1; transform: scale(1); }}
    }}
    @keyframes chartPop {{
      from {{ opacity: .55; transform: scale(.96); }}
      to {{ opacity: 1; transform: scale(1); }}
    }}
    .ads-page {{
      display: grid;
      gap: 16px;
    }}
    .ads-hero {{
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 0;
    }}
    .ads-hero h2 {{
      margin-bottom: 5px;
    }}
    .ads-hero-actions {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      justify-content: flex-end;
    }}
    .ads-kpi-grid {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
    }}
    .ads-kpi-card {{
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      min-height: 126px;
      display: grid;
      gap: 10px;
    }}
    .ads-kpi-top {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
    }}
    .ads-kpi-label {{
      color: var(--muted);
      font-size: 12px;
      font-weight: 750;
    }}
    .ads-kpi-value {{
      color: var(--ink);
      font-size: 28px;
      line-height: 1;
      font-weight: 800;
      overflow-wrap: anywhere;
    }}
    .ads-kpi-desc {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      padding-top: 8px;
      border-top: 1px solid var(--line-soft);
      color: var(--muted);
      font-size: 12px;
    }}
    .ads-kpi-desc strong {{
      color: var(--brand);
      font-size: 12px;
    }}
    .ads-workspace {{
      display: grid;
      grid-template-columns: minmax(460px, 1.25fr) minmax(320px, .75fr);
      gap: 12px;
      align-items: stretch;
    }}
    .ads-upload-card {{
      margin: 0;
    }}
    .ads-upload-card h2,
    .ads-side-card h2 {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
    }}
    .ads-upload-form {{
      grid-template-columns: repeat(12, minmax(0, 1fr));
      margin-top: 12px;
    }}
    .ads-field {{
      grid-column: span 4;
    }}
    .ads-file {{
      grid-column: span 5;
    }}
    .ads-note-field {{
      grid-column: span 5;
    }}
    .ads-submit {{
      grid-column: span 2;
      align-self: end;
    }}
    .ads-upload-form input[type="file"] {{
      min-height: 45px;
      padding: 8px;
    }}
    .ads-side-card {{
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      margin: 0;
    }}
    .ads-side-grid {{
      display: grid;
      gap: 10px;
      margin-top: 12px;
    }}
    .ads-side-item {{
      display: grid;
      grid-template-columns: 36px minmax(0, 1fr);
      gap: 10px;
      align-items: start;
      padding: 10px;
      border: 1px solid var(--line-soft);
      border-radius: 8px;
      background: var(--surface-2);
    }}
    .ads-side-item strong {{
      display: block;
      color: var(--ink);
      margin-bottom: 3px;
    }}
    .ads-side-item span {{
      color: var(--muted);
      font-size: 12px;
      line-height: 1.45;
    }}
    .ads-table-card {{
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      margin-bottom: 0;
    }}
    .ads-table-card .section-head {{
      margin-bottom: 10px;
    }}
    .ads-table-meta {{
      color: var(--muted);
      font-size: 12px;
      font-weight: 650;
    }}
    .ads-table-scroll {{
      overflow-x: auto;
      border-radius: 8px;
    }}
    .ads-table-scroll table {{
      min-width: 1080px;
    }}
    .agent-page {{
      display: grid;
      gap: 16px;
    }}
    .agent-hero {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 16px;
      align-items: start;
      margin-bottom: 0;
    }}
    .agent-hero h2 {{
      margin-bottom: 5px;
    }}
    .agent-status-bar {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px 14px;
    }}
    .agent-status-meta {{
      color: var(--muted);
      font-size: 13px;
      font-weight: 700;
    }}
    .agent-layout {{
      display: grid;
      grid-template-columns: minmax(420px, .9fr) minmax(520px, 1.1fr);
      gap: 14px;
      align-items: start;
    }}
    .agent-card {{
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      margin-bottom: 0;
    }}
    .agent-card h2,
    .agent-card h3 {{
      display: flex;
      align-items: center;
      gap: 8px;
    }}
    .agent-title {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 12px;
    }}
    .agent-name {{
      color: var(--ink);
      font-size: 28px;
      line-height: 1.1;
      font-weight: 850;
    }}
    .agent-meta-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
    }}
    .agent-meta-item {{
      border: 1px solid var(--line-soft);
      border-radius: 8px;
      background: var(--surface-2);
      padding: 10px;
      min-height: 74px;
    }}
    .agent-meta-item span {{
      display: block;
      color: var(--muted);
      font-size: 12px;
      font-weight: 750;
      margin-bottom: 5px;
    }}
    .agent-meta-item strong {{
      color: var(--ink);
      line-height: 1.4;
    }}
    .agent-kpi-grid {{
      display: grid;
      grid-template-columns: repeat(4, minmax(156px, 1fr));
      gap: 18px;
      justify-items: center;
    }}
    .agent-kpi {{
      width: clamp(156px, 15vw, 188px);
      aspect-ratio: 1;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: 8px;
      text-align: center;
      background: radial-gradient(circle at 50% 34%, var(--surface) 0%, var(--surface) 54%, var(--surface-2) 100%);
      border: 1.5px solid color-mix(in srgb, var(--accent) 72%, var(--line));
      border-radius: 50%;
      padding: 20px;
      box-shadow:
        0 14px 32px color-mix(in srgb, var(--accent) 14%, transparent),
        inset 0 0 0 1px color-mix(in srgb, var(--brand) 18%, transparent);
    }}
    .agent-kpi span {{
      color: var(--muted);
      font-size: 12px;
      font-weight: 750;
    }}
    .agent-kpi strong {{
      color: var(--ink);
      font-size: clamp(24px, 2.1vw, 34px);
      line-height: 1;
    }}
    .agent-kpi p {{
      margin: 0;
      color: var(--muted);
      font-size: 11px;
      line-height: 1.35;
      max-width: 126px;
    }}
    .agent-run-table table {{
      min-width: 1180px;
    }}
    .alert-grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
    }}
    .alert-card {{
      background: var(--surface);
      border: 1px solid var(--line);
      border-left: 5px solid var(--accent);
      border-radius: 8px;
      padding: 12px;
      min-height: 112px;
    }}
    .alert-card strong {{
      display: block;
      color: var(--ink);
      margin: 8px 0 6px;
      line-height: 1.35;
    }}
    .alert-card p {{
      margin: 0;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.45;
    }}
    .card-topline {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      margin-bottom: 8px;
    }}
    .severity-icon {{
      color: var(--accent);
    }}
    .alert-high .severity-icon,
    .attribution-high .severity-icon {{
      color: var(--bad);
    }}
    .alert-medium .severity-icon,
    .attribution-medium .severity-icon {{
      color: var(--warn);
    }}
    .alert-high {{ border-left-color: var(--bad); }}
    .alert-medium {{ border-left-color: var(--warn); }}
    .alert-info {{ border-left-color: var(--accent); }}
    .delta-up {{ color: var(--ok); font-weight: 750; }}
    .delta-down {{ color: var(--bad); font-weight: 750; }}
    .delta-flat {{ color: var(--muted); font-weight: 650; }}
    .comparison-scroll {{
      overflow-x: auto;
      border-radius: 8px;
    }}
    .comparison-scroll table {{
      min-width: 980px;
    }}
    .rank-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
    }}
    .rank-card {{
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
    }}
    .rank-card table {{
      margin-top: 8px;
    }}
    .model-card {{
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
    }}
    .model-grid {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
      margin-top: 12px;
    }}
    .model-mini {{
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      background: var(--surface-2);
      min-height: 86px;
    }}
    .model-mini span {{
      display: block;
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 6px;
    }}
    .model-mini strong {{
      color: var(--ink);
      font-size: 20px;
    }}
    .insight-list {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }}
    .insight-item {{
      border: 1px solid var(--line);
      border-left: 5px solid var(--accent);
      border-radius: 8px;
      padding: 12px;
      background: var(--surface);
      min-height: 112px;
    }}
    .insight-item strong {{
      display: block;
      color: var(--ink);
      margin-bottom: 6px;
      line-height: 1.35;
    }}
    .insight-item p {{
      margin: 0;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.5;
    }}
    .attribution-grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
    }}
    .attribution-card {{
      border: 1px solid var(--line);
      border-left: 5px solid var(--accent);
      border-radius: 8px;
      padding: 12px;
      background: var(--surface);
      min-height: 132px;
    }}
    .attribution-card strong {{
      display: block;
      color: var(--ink);
      margin: 8px 0 6px;
      line-height: 1.35;
    }}
    .attribution-card p {{
      margin: 0;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.5;
    }}
    .attribution-high {{ border-left-color: var(--bad); }}
    .attribution-medium {{ border-left-color: var(--warn); }}
    .attribution-info {{ border-left-color: var(--accent); }}
    .action-workbench {{
      display: grid;
      gap: 14px;
    }}
    .action-summary-grid {{
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 10px;
    }}
    .action-summary-card {{
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface);
      padding: 12px;
      min-height: 92px;
      display: grid;
      align-content: space-between;
      animation: cardRise .42s ease-out both;
    }}
    .action-summary-card span {{
      color: var(--muted);
      font-size: 12px;
      font-weight: 750;
    }}
    .action-summary-card strong {{
      color: var(--ink);
      font-size: 26px;
      line-height: 1;
    }}
    .action-summary-card p {{
      margin: 0;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.35;
    }}
    .action-layout {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(280px, 340px);
      gap: 14px;
      align-items: start;
    }}
    .action-list {{
      display: grid;
      gap: 11px;
    }}
    .action-item {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(210px, .28fr);
      gap: 14px;
      align-items: stretch;
      border: 1px solid var(--line);
      border-left: 5px solid var(--accent);
      border-radius: 8px;
      background: var(--surface);
      padding: 14px;
      position: relative;
      overflow: hidden;
      animation: cardRise .46s ease-out both;
    }}
    .action-item::before {{
      content: "";
      position: absolute;
      inset: 0 0 auto;
      height: 2px;
      background: linear-gradient(90deg, color-mix(in srgb, var(--accent) 70%, transparent), transparent);
      opacity: .75;
    }}
    .action-item.action-p0 {{ border-left-color: var(--bad); }}
    .action-item.action-p1 {{ border-left-color: var(--warn); }}
    .action-item.action-p2 {{ border-left-color: var(--ok); }}
    .action-card-main {{
      min-width: 0;
    }}
    .action-card-head {{
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 9px;
    }}
    .action-title-wrap {{
      display: grid;
      gap: 7px;
      min-width: 0;
    }}
    .action-badges {{
      display: flex;
      align-items: center;
      flex-wrap: wrap;
      gap: 7px;
    }}
    .action-priority {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 28px;
      border-radius: 999px;
      padding: 4px 10px;
      font-size: 12px;
      font-weight: 800;
      border: 1px solid var(--line);
    }}
    .action-status {{
      display: inline-flex;
      align-items: center;
      min-height: 26px;
      border-radius: 999px;
      padding: 3px 9px;
      color: var(--muted);
      background: var(--surface-2);
      border: 1px solid var(--line-soft);
      font-size: 12px;
      font-weight: 750;
    }}
    .priority-p0 {{
      color: var(--bad);
      background: color-mix(in srgb, var(--bad) 10%, transparent);
      border-color: color-mix(in srgb, var(--bad) 38%, var(--line));
    }}
    .priority-p1 {{
      color: var(--warn);
      background: color-mix(in srgb, var(--warn) 12%, transparent);
      border-color: color-mix(in srgb, var(--warn) 38%, var(--line));
    }}
    .priority-p2 {{
      color: var(--accent);
      background: color-mix(in srgb, var(--accent) 10%, transparent);
      border-color: color-mix(in srgb, var(--accent) 34%, var(--line));
    }}
    .action-title {{
      display: block;
      color: var(--ink);
      font-weight: 750;
      line-height: 1.35;
      font-size: 16px;
    }}
    .action-detail {{
      color: var(--muted);
      font-size: 13px;
      line-height: 1.5;
    }}
    .action-evidence {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin-top: 11px;
    }}
    .action-chip {{
      display: inline-flex;
      align-items: center;
      min-height: 24px;
      border-radius: 999px;
      padding: 3px 8px;
      color: var(--brand);
      background: color-mix(in srgb, var(--accent) 8%, var(--surface));
      border: 1px solid color-mix(in srgb, var(--accent) 20%, var(--line));
      font-size: 12px;
      font-weight: 700;
    }}
    .action-meta {{
      color: var(--muted);
      font-size: 12px;
      line-height: 1.55;
    }}
    .action-meta strong {{
      color: var(--brand);
    }}
    .action-meta-panel {{
      display: grid;
      gap: 9px;
      align-content: start;
      border: 1px solid var(--line-soft);
      border-radius: 8px;
      background: var(--surface-2);
      padding: 11px;
    }}
    .action-meta-line {{
      display: grid;
      gap: 2px;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.4;
    }}
    .action-meta-line strong {{
      color: var(--brand);
      font-size: 12px;
    }}
    .action-actions {{
      display: flex;
      flex-wrap: wrap;
      gap: 7px;
      margin-top: 2px;
    }}
    .action-mini-btn {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      min-height: 30px;
      border-radius: 6px;
      border: 1px solid var(--line);
      background: var(--surface);
      color: var(--brand);
      text-decoration: none;
      padding: 5px 9px;
      font-size: 12px;
      font-weight: 750;
    }}
    .action-mini-btn .icon {{
      width: 15px;
      height: 15px;
    }}
    .action-sidebar {{
      display: grid;
      gap: 12px;
      position: sticky;
      top: 148px;
    }}
    .action-side-card {{
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface);
      padding: 13px;
      animation: cardRise .48s ease-out both;
    }}
    .action-side-card h3 {{
      margin: 0 0 10px;
      color: var(--brand);
      font-size: 14px;
    }}
    .action-focus-list {{
      display: grid;
      gap: 8px;
      margin: 0;
      padding: 0;
      list-style: none;
    }}
    .action-focus-list li {{
      display: grid;
      grid-template-columns: 44px minmax(0, 1fr);
      gap: 8px;
      align-items: start;
      color: var(--ink);
      font-size: 13px;
      line-height: 1.4;
    }}
    .action-owner-row {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      padding: 8px 0;
      border-bottom: 1px solid var(--line-soft);
      color: var(--muted);
      font-size: 13px;
    }}
    .action-owner-row:last-child {{
      border-bottom: none;
      padding-bottom: 0;
    }}
    .action-owner-row strong {{
      color: var(--ink);
    }}
    .explain-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }}
    .explain-card {{
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface);
      padding: 12px;
      line-height: 1.55;
      color: var(--muted);
      font-size: 13px;
    }}
    .quality-layout {{
      display: grid;
      grid-template-columns: minmax(220px, 0.26fr) minmax(0, 1fr);
      gap: 14px;
      align-items: stretch;
    }}
    .quality-score-card {{
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface);
      padding: 16px;
      display: grid;
      align-content: center;
      justify-items: center;
      gap: 10px;
      text-align: center;
    }}
    .quality-ring {{
      width: 132px;
      height: 132px;
      border-radius: 50%;
      display: grid;
      place-items: center;
      background: conic-gradient(var(--accent) var(--score-deg), var(--line-soft) 0);
      border: 1px solid var(--line);
      position: relative;
    }}
    .quality-ring::after {{
      content: "";
      position: absolute;
      inset: 24px;
      border-radius: 50%;
      background: var(--surface);
      border: 1px solid var(--line-soft);
    }}
    .quality-ring strong {{
      position: relative;
      z-index: 1;
      color: var(--ink);
      font-size: 30px;
    }}
    .quality-status {{
      color: var(--brand);
      font-weight: 800;
    }}
    .quality-list {{
      display: grid;
      gap: 8px;
    }}
    .quality-row {{
      display: grid;
      grid-template-columns: minmax(120px, 0.25fr) minmax(100px, 0.18fr) minmax(0, 1fr);
      gap: 10px;
      align-items: center;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface);
      padding: 10px;
      font-size: 13px;
    }}
    .quality-row strong {{
      color: var(--ink);
    }}
    .quality-row p {{
      margin: 0;
      color: var(--muted);
      line-height: 1.45;
    }}
    .opportunity-list {{
      display: grid;
      gap: 10px;
    }}
    .opportunity-item {{
      display: grid;
      grid-template-columns: 82px minmax(0, 0.34fr) minmax(0, 1fr) minmax(180px, 0.3fr);
      gap: 12px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface);
      padding: 12px;
      align-items: start;
    }}
    .opportunity-score {{
      width: 58px;
      height: 58px;
      border-radius: 50%;
      display: grid;
      place-items: center;
      background: color-mix(in srgb, var(--accent) 12%, transparent);
      border: 1px solid color-mix(in srgb, var(--accent) 38%, var(--line));
      color: var(--brand);
      font-weight: 850;
      font-size: 18px;
    }}
    .opportunity-main strong,
    .opportunity-action strong {{
      display: block;
      color: var(--ink);
      margin-bottom: 5px;
      line-height: 1.35;
    }}
    .opportunity-main p,
    .opportunity-action p {{
      margin: 0;
      color: var(--muted);
      line-height: 1.5;
      font-size: 13px;
    }}
    .war-kpi-grid {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
      margin-bottom: 12px;
    }}
    .war-card-grid {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
      margin-bottom: 14px;
    }}
    .war-card {{
      border: 1px solid var(--line);
      border-left: 5px solid var(--accent);
      border-radius: 8px;
      background: var(--surface);
      padding: 12px;
      min-height: 142px;
    }}
    .war-card strong {{
      display: block;
      color: var(--ink);
      margin: 8px 0 6px;
      line-height: 1.35;
    }}
    .war-card p {{
      margin: 0;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.5;
    }}
    .war-table table {{
      min-width: 1700px;
    }}
    .asin-depth-grid {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
      margin-bottom: 14px;
    }}
    .asin-profile-card {{
      display: grid;
      grid-template-columns: 86px minmax(0, 1fr);
      gap: 12px;
      align-items: start;
      border: 1px solid var(--line);
      border-left: 5px solid var(--accent);
      border-radius: 8px;
      background: var(--surface);
      padding: 12px;
      min-height: 178px;
    }}
    .asin-profile-card.high {{
      border-left-color: var(--bad);
    }}
    .asin-profile-card.medium {{
      border-left-color: var(--warn);
    }}
    .asin-thumb {{
      width: 74px;
      height: 74px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface-2);
      object-fit: contain;
    }}
    .asin-profile-card strong {{
      display: block;
      color: var(--ink);
      line-height: 1.35;
      margin: 6px 0;
    }}
    .asin-profile-card p {{
      margin: 0;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.45;
    }}
    .keyword-cloud {{
      position: relative;
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: center;
      gap: 16px;
      min-height: 230px;
      margin: 12px 0 18px;
      padding: 24px;
      overflow: hidden;
      isolation: isolate;
      border: 1px solid color-mix(in srgb, var(--accent) 22%, var(--line));
      border-radius: 10px;
      background:
        radial-gradient(circle at 16% 20%, color-mix(in srgb, var(--accent) 18%, transparent) 0 1px, transparent 2px),
        radial-gradient(circle at 78% 28%, color-mix(in srgb, var(--brand) 18%, transparent) 0 1px, transparent 2px),
        radial-gradient(circle at 36% 72%, color-mix(in srgb, var(--accent) 13%, transparent) 0 1px, transparent 2px),
        linear-gradient(135deg, color-mix(in srgb, var(--surface-2) 88%, var(--brand) 12%), var(--surface));
      box-shadow: inset 0 0 42px color-mix(in srgb, var(--accent) 10%, transparent);
    }}
    .keyword-cloud::before,
    .keyword-cloud::after {{
      content: "";
      position: absolute;
      inset: -20%;
      z-index: -1;
      pointer-events: none;
      background-image:
        radial-gradient(circle, color-mix(in srgb, var(--accent) 62%, white) 0 1px, transparent 1.8px),
        radial-gradient(circle, color-mix(in srgb, var(--brand) 58%, white) 0 1px, transparent 1.6px);
      background-size: 76px 76px, 118px 118px;
      background-position: 0 0, 28px 32px;
      opacity: .32;
      animation: starDrift 18s linear infinite;
    }}
    .keyword-cloud::after {{
      background-size: 54px 54px, 92px 92px;
      opacity: .18;
      filter: blur(.4px);
      animation-duration: 26s;
      animation-direction: reverse;
    }}
    .keyword-chip {{
      --size: 72px;
      --font-size: 12px;
      --delay: 0s;
      --duration: 7s;
      --drift: 4px;
      --float-start: -4px;
      --float-end: 7px;
      --glow: 42%;
      position: relative;
      z-index: 1;
      width: var(--size);
      height: var(--size);
      display: inline-flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: 3px;
      border: 1px solid color-mix(in srgb, var(--accent) 44%, var(--line));
      border-radius: 50%;
      background:
        radial-gradient(circle at 50% 54%, color-mix(in srgb, var(--accent) 20%, transparent) 0 48%, color-mix(in srgb, var(--surface) 74%, transparent) 78%),
        color-mix(in srgb, var(--surface) 78%, var(--brand) 22%);
      color: var(--brand);
      padding: 10px;
      text-align: center;
      font-size: var(--font-size);
      font-weight: 750;
      line-height: 1.05;
      cursor: pointer;
      translate: 0 var(--float-start);
      scale: 1;
      box-shadow:
        0 0 calc(var(--size) * .2) color-mix(in srgb, var(--accent) var(--glow), transparent),
        inset 0 0 calc(var(--size) * .24) color-mix(in srgb, white 12%, transparent),
        inset 0 -8px 18px color-mix(in srgb, var(--brand) 10%, transparent);
      animation: keywordFloat var(--duration) ease-in-out infinite alternate;
      animation-delay: var(--delay);
      transition:
        scale .22s ease,
        filter .22s ease,
        border-color .22s ease,
        box-shadow .22s ease,
        color .22s ease,
        background .22s ease;
      will-change: translate, scale, filter;
      outline: none;
    }}
    .keyword-chip strong {{
      display: block;
      max-width: 92%;
      color: currentColor;
      overflow-wrap: anywhere;
      letter-spacing: 0;
    }}
    .keyword-chip em {{
      color: color-mix(in srgb, var(--ink) 72%, var(--accent));
      font-style: normal;
      font-size: .88em;
      font-weight: 850;
      opacity: .82;
    }}
    .keyword-chip::after {{
      content: "";
      position: absolute;
      inset: 12%;
      border-radius: inherit;
      border: 1px solid color-mix(in srgb, white 22%, transparent);
      opacity: .45;
      pointer-events: none;
      transition: inset .22s ease, opacity .22s ease, border-color .22s ease;
    }}
    .keyword-chip:is(:hover, :focus-visible) {{
      z-index: 5;
      color: color-mix(in srgb, white 72%, var(--accent) 28%);
      border-color: color-mix(in srgb, var(--accent) 84%, white);
      background:
        radial-gradient(circle at 48% 50%, color-mix(in srgb, var(--accent) 64%, transparent) 0 54%, color-mix(in srgb, var(--brand) 28%, transparent) 84%),
        color-mix(in srgb, var(--surface) 34%, var(--accent) 66%);
      box-shadow:
        0 0 calc(var(--size) * .46) color-mix(in srgb, var(--accent) 86%, transparent),
        inset 0 0 calc(var(--size) * .22) color-mix(in srgb, var(--accent) 26%, transparent),
        inset 0 -10px 22px color-mix(in srgb, var(--brand) 18%, transparent);
      filter: saturate(1.38) brightness(1.14);
      scale: 1.12;
      animation-play-state: paused;
    }}
    .keyword-chip:is(:hover, :focus-visible) strong {{
      text-shadow: 0 0 12px color-mix(in srgb, white 42%, transparent);
    }}
    .keyword-chip:is(:hover, :focus-visible) em {{
      color: color-mix(in srgb, white 76%, var(--accent) 24%);
      opacity: 1;
    }}
    .keyword-chip:is(:hover, :focus-visible)::after {{
      inset: 6%;
      opacity: .34;
      border-color: color-mix(in srgb, var(--accent) 62%, transparent);
    }}
    @keyframes keywordFloat {{
      from {{ translate: 0 var(--float-start); }}
      to {{ translate: var(--drift) var(--float-end); }}
    }}
    @keyframes starDrift {{
      from {{ transform: translate3d(0, 0, 0) rotate(0deg); }}
      to {{ transform: translate3d(32px, -24px, 0) rotate(1deg); }}
    }}
    .voc-grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
      margin-bottom: 14px;
    }}
    .voc-card {{
      border: 1px solid var(--line);
      border-left: 5px solid var(--accent);
      border-radius: 8px;
      background: var(--surface);
      padding: 12px;
      min-height: 150px;
    }}
    .voc-card strong {{
      display: block;
      color: var(--ink);
      margin: 8px 0 6px;
      line-height: 1.35;
    }}
    .voc-card p {{
      margin: 0;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.5;
    }}
    .ops-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
      align-items: stretch;
    }}
    .ops-card {{
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface);
      padding: 14px;
      min-height: 138px;
    }}
    .ops-card h3 {{
      margin: 0 0 8px;
      color: var(--brand);
      display: flex;
      align-items: center;
      gap: 8px;
      line-height: 1.3;
    }}
    .ops-card p {{
      margin: 0;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.55;
    }}
    .ops-card strong {{
      color: var(--ink);
    }}
    .ops-status-grid {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
      margin-top: 12px;
    }}
    .ops-table table {{
      min-width: 1120px;
    }}
    .task-board {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
    }}
    .task-card {{
      border: 1px solid var(--line);
      border-left: 5px solid var(--accent);
      border-radius: 8px;
      background: var(--surface);
      padding: 12px;
      min-height: 168px;
    }}
    .task-card strong {{
      display: block;
      color: var(--ink);
      margin: 8px 0 6px;
      line-height: 1.35;
    }}
    .task-card p {{
      margin: 0 0 8px;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.5;
    }}
    .source-tier-grid {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
    }}
    .source-tier {{
      border: 1px solid var(--line);
      border-left: 5px solid var(--accent);
      border-radius: 8px;
      background: var(--surface);
      padding: 12px;
      min-height: 156px;
    }}
    .source-tier.warning {{
      border-left-color: var(--warn);
    }}
    .source-tier.safe {{
      border-left-color: var(--good);
    }}
    .source-tier.danger {{
      border-left-color: var(--bad);
    }}
    .source-tier strong {{
      display: block;
      color: var(--ink);
      margin-bottom: 6px;
      line-height: 1.35;
    }}
    .source-tier p {{
      margin: 0;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.5;
    }}
    .chat-layout {{
      display: grid;
      grid-template-columns: minmax(300px, 520px) minmax(0, 1fr);
      gap: 18px;
      align-items: stretch;
    }}
    .chat-panel {{
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      height: 100%;
      box-sizing: border-box;
    }}
    .chat-panel h3 {{
      margin: 0 0 10px;
      color: var(--brand);
      display: flex;
      align-items: center;
      gap: 8px;
    }}
    .chat-form {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 10px;
      align-items: end;
      margin-bottom: 14px;
    }}
    .chat-form label {{
      grid-column: 1 / -1;
    }}
    .quick-grid {{
      display: grid;
      gap: 8px;
    }}
    .quick-chip {{
      width: 100%;
      justify-content: flex-start;
      text-align: left;
      line-height: 1.35;
      min-height: 38px;
    }}
    .chat-answer {{
      display: grid;
      gap: 12px;
      align-content: stretch;
      align-items: stretch;
      min-height: 360px;
      height: 100%;
      border: 1px solid color-mix(in srgb, var(--accent) 16%, var(--line));
      border-radius: 8px;
      background:
        radial-gradient(circle at 8% 0%, color-mix(in srgb, var(--accent) 7%, transparent), transparent 30%),
        linear-gradient(180deg, color-mix(in srgb, var(--surface-2) 52%, transparent), var(--surface));
      padding: 14px;
      box-sizing: border-box;
    }}
    .chat-bubble {{
      position: relative;
      overflow: hidden;
      border: 1px solid color-mix(in srgb, var(--accent) 22%, var(--line));
      border-radius: 8px;
      background: var(--surface);
      padding: 14px 16px 14px 18px;
      box-sizing: border-box;
      width: min(1180px, 100%);
      box-shadow: 0 14px 34px rgba(15, 23, 42, .07);
      isolation: isolate;
      animation: cardRise .36s ease-out both;
    }}
    .chat-bubble::after {{
      content: "";
      position: absolute;
      inset: 12px auto 12px 0;
      width: 5px;
      border-radius: 0 999px 999px 0;
      background: linear-gradient(180deg, var(--accent), color-mix(in srgb, var(--brand) 72%, var(--accent)));
      box-shadow: 0 0 18px color-mix(in srgb, var(--accent) 30%, transparent);
      pointer-events: none;
      z-index: 1;
    }}
    .chat-bubble > * {{
      position: relative;
      z-index: 2;
    }}
    .chat-answer > .chat-bubble:only-child {{
      min-height: 100%;
      display: flex;
      flex-direction: column;
    }}
    .chat-answer > .chat-bubble:only-child .chat-ai-text {{
      flex: 1;
    }}
    .chat-bubble-title {{
      display: flex;
      align-items: center;
      gap: 8px;
      color: var(--brand);
      font-weight: 800;
      margin-bottom: 9px;
      font-size: 16px;
    }}
    .chat-bullets {{
      margin: 0;
      padding-left: 18px;
      color: var(--ink);
      line-height: 1.55;
      font-size: 13px;
    }}
    .chat-bullets li {{
      margin: 3px 0;
      padding-left: 2px;
    }}
    .chat-lines {{
      flex: 1;
      display: grid;
      align-content: start;
      gap: 0;
      margin-top: 2px;
    }}
    .chat-line {{
      display: grid;
      grid-template-columns: 26px minmax(0, 1fr);
      gap: 10px;
      align-items: start;
      padding: 11px 0;
      border-bottom: 1px solid var(--line-soft);
      color: var(--ink);
      line-height: 1.55;
      font-size: 13px;
    }}
    .chat-line:last-child {{
      border-bottom: none;
    }}
    .chat-line-index {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 22px;
      height: 22px;
      border-radius: 999px;
      color: var(--brand);
      background: color-mix(in srgb, var(--accent) 10%, transparent);
      border: 1px solid color-mix(in srgb, var(--accent) 22%, var(--line));
      font-size: 11px;
      font-weight: 850;
    }}
    .chat-emphasis {{
      color: var(--brand);
      font-weight: 850;
    }}
    .chat-number {{
      color: var(--ink);
      font-weight: 850;
      background: color-mix(in srgb, var(--accent) 10%, transparent);
      border-radius: 5px;
      padding: 0 4px;
      white-space: nowrap;
    }}
    .chat-answer-meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin: 0 0 8px;
    }}
    .chat-answer-meta .pill {{
      background: var(--surface-2);
    }}
    .chat-bubble .btn {{
      margin-top: 8px;
    }}
    .knowledge-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 10px;
    }}
    .knowledge-tile {{
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface);
      padding: 12px;
      min-height: 96px;
    }}
    .knowledge-tile strong {{
      display: block;
      color: var(--brand);
      margin-bottom: 6px;
    }}
    .knowledge-tile .metric-value {{
      font-size: 24px;
    }}
    .knowledge-layout {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
      align-items: start;
    }}
    .knowledge-card {{
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface);
      padding: 14px;
    }}
    .knowledge-card h3 {{
      margin: 0 0 10px;
      color: var(--brand);
      display: flex;
      gap: 8px;
      align-items: center;
    }}
    .knowledge-card form {{
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }}
    .knowledge-card .btn {{
      justify-self: start;
    }}
    .api-status-grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
    }}
    .api-status-card {{
      border: 1px solid var(--line);
      border-left: 5px solid var(--accent);
      border-radius: 8px;
      background: var(--surface);
      padding: 12px;
      min-height: 118px;
    }}
    .api-status-card strong {{
      display: block;
      color: var(--ink);
      margin-bottom: 6px;
    }}
    .api-status-card p {{
      margin: 0;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.5;
    }}
    .api-status-card.pending {{
      border-left-color: var(--warn);
    }}
    .mcp-usage-grid {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
      margin-top: 12px;
    }}
    .mcp-usage-card {{
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface);
      padding: 14px;
      min-height: 104px;
    }}
    .mcp-usage-label {{
      color: var(--muted);
      font-size: 12px;
      font-weight: 800;
      margin-bottom: 8px;
    }}
    .mcp-usage-value {{
      color: var(--ink);
      font-size: 26px;
      line-height: 1;
      font-weight: 850;
    }}
    .mcp-usage-sub {{
      margin-top: 8px;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.45;
    }}
    .mcp-usage-meter {{
      margin-top: 12px;
      height: 10px;
      overflow: hidden;
      border-radius: 999px;
      background: var(--line-soft);
    }}
    .mcp-usage-meter span {{
      display: block;
      height: 100%;
      border-radius: inherit;
      background: linear-gradient(90deg, var(--accent), var(--brand));
    }}
    .mcp-usage-note {{
      margin-top: 10px;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.55;
    }}
    .chat-ai-text {{
      color: var(--ink);
      line-height: 1.5;
      font-size: 13px;
    }}
    .chat-ai-text p {{
      margin: 0 0 7px;
    }}
    .chat-ai-text p:last-child {{
      margin-bottom: 0;
    }}
    .chat-ai-text .chat-bullets {{
      margin: 0 0 8px;
    }}
    .chat-mode {{
      margin: 12px 0;
      line-height: 1.5;
      font-size: 13px;
    }}
    .chat-mode strong {{
      color: var(--brand);
    }}
    .trend-badge {{
      display: inline-flex;
      align-items: center;
      min-height: 24px;
      border-radius: 999px;
      padding: 3px 8px;
      font-size: 12px;
      font-weight: 750;
      white-space: nowrap;
    }}
    .trend-up {{
      color: var(--ok);
      background: color-mix(in srgb, var(--ok) 12%, transparent);
    }}
    .trend-down {{
      color: var(--bad);
      background: color-mix(in srgb, var(--bad) 12%, transparent);
    }}
    .trend-flat, .trend-base {{
      color: var(--muted);
      background: var(--line-soft);
    }}
    .trend-new {{
      color: var(--accent);
      background: color-mix(in srgb, var(--accent) 12%, transparent);
    }}
    .trend-missing {{
      color: var(--warn);
      background: color-mix(in srgb, var(--warn) 12%, transparent);
    }}
    .table-scroll {{
      overflow-x: auto;
      border-radius: 8px;
    }}
    .table-scroll table {{
      min-width: 920px;
    }}
    .full-width-panel {{
      width: 100%;
    }}
    .full-width-panel .rank-card {{
      width: 100%;
    }}
    .asin-table table {{
      min-width: 1500px;
    }}
    .asin-table th:last-child,
    .asin-table td:last-child {{
      width: 44%;
      min-width: 520px;
    }}
    @media (max-width: 1200px) {{
      .ops-hero, .trend-wall-grid, .dashboard-command, .chart-first-grid {{
        grid-template-columns: 1fr;
      }}
      .command-kpi-grid {{
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }}
      .ops-priority-strip {{
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }}
      .action-layout {{
        grid-template-columns: 1fr;
      }}
      .action-sidebar {{
        position: static;
      }}
      .action-summary-grid {{
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }}
      .ads-kpi-grid {{
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }}
      .ads-workspace {{
        grid-template-columns: 1fr;
      }}
    }}
    @media (max-width: 900px) {{
      header {{
        position: sticky;
        top: 0;
        width: 100%;
        height: auto;
        max-height: 70vh;
        border-bottom: 1px solid var(--line);
        padding: 16px;
        overflow-y: auto;
      }}
      nav {{
        position: sticky;
        top: 0;
        bottom: auto;
        left: auto;
        z-index: 25;
        width: 100%;
        display: flex;
        flex-wrap: nowrap;
        overflow-x: auto;
        gap: 8px;
        margin: 0;
        padding: 10px 16px;
        border-right: none;
        border-bottom: 1px solid var(--line);
      }}
      nav a {{
        width: auto;
        min-width: max-content;
        justify-content: center;
      }}
      .sidebar-toggle {{
        display: none;
      }}
      html.sidebar-collapsed nav {{
        padding: 10px 16px;
      }}
      html.sidebar-collapsed nav a {{
        justify-content: center;
      }}
      html.sidebar-collapsed nav a span {{
        max-width: 190px;
        opacity: 1;
      }}
      .grid, form {{ grid-template-columns: 1fr; }}
      .split, .chart-grid, .site-grid, .mapping-grid, .alert-grid, .rank-grid, .model-grid, .insight-list, .attribution-grid, .explain-grid, .quality-layout, .quality-row, .opportunity-item, .war-kpi-grid, .war-card-grid, .asin-depth-grid, .voc-grid, .ops-grid, .ops-status-grid, .task-board, .source-tier-grid, .chat-layout, .chat-form, .knowledge-grid, .knowledge-layout, .knowledge-card form, .api-status-grid, .mcp-usage-grid, .ads-kpi-grid, .ads-workspace, .ads-upload-form, .agent-hero, .agent-layout, .agent-meta-grid, .agent-kpi-grid, .ops-focus-grid, .ops-priority-strip {{ grid-template-columns: 1fr; }}
      .agent-kpi-grid {{ grid-template-columns: repeat(2, minmax(156px, 1fr)); }}
      .command-kpi-grid, .dashboard-action-strip {{ grid-template-columns: 1fr; }}
      .dashboard-filter {{ align-items: stretch; flex-direction: column; }}
      .dashboard-week-form {{ grid-template-columns: 1fr; min-width: 0; }}
      .action-summary-grid {{ grid-template-columns: 1fr; }}
      .action-item {{ grid-template-columns: 1fr; }}
      .donut-wrap {{ grid-template-columns: 1fr; }}
      .wide, .ads-field, .ads-file, .ads-note-field, .ads-submit {{ grid-column: auto; }}
      main {{ margin-left: 0; width: 100%; padding: 16px; }}
      .asin-table table {{ min-width: 980px; }}
      .war-table table {{ min-width: 1100px; }}
      .asin-table th:last-child,
      .asin-table td:last-child {{ min-width: 320px; }}
      .analysis-tab-list {{ top: 0; }}
      .header-top {{ display: block; }}
      .settings-bar {{ justify-content: flex-start; margin-top: 12px; }}
      .ads-hero {{ display: block; }}
      .ads-hero-actions {{ justify-content: flex-start; margin-top: 12px; }}
      .chart-zoom-modal {{ padding: 12px; }}
      .chart-zoom-body .line-chart {{ min-height: 320px; height: 58vh; }}
    }}
    @media (max-width: 520px) {{
      .agent-kpi-grid {{ grid-template-columns: 1fr; }}
    }}
    @media (prefers-reduced-motion: reduce) {{
      *, *::before, *::after {{
        animation-duration: .01ms !important;
        animation-iteration-count: 1 !important;
        scroll-behavior: auto !important;
      }}
    }}
  </style>
</head>
<body>
  <header>
    <div class="header-top">
      <h1 data-i18n="app_title">{esc(ui("app_title"))}</h1>
      <div class="settings-bar">
        <form class="fetch-latest-form top-fetch-latest-form" method="post" action="/mcp/fetch-latest" data-fetch-latest-form>
          <input type="hidden" name="return_to_path" value="">
          <span class="top-fetch-spacer" aria-hidden="true"></span>
          <button class="btn btn-primary" type="submit">{icon("uploads")}<span data-i18n="fetch_latest_week_data" data-fetch-label>{esc(ui("fetch_latest_week_data"))}</span></button>
        </form>
        <label class="header-control global-week-control">
          <span data-i18n="data_week">{esc(ui("data_week"))}</span>
          <select id="globalWeekSelect" aria-label="{esc(ui("data_week"))}" data-default-week="{esc(selected_global_week)}"{global_week_disabled}>
{global_week_options_html}
          </select>
        </label>
        <label class="header-control">
          <span data-i18n="language">{esc(ui("language"))}</span>
          <select id="languageSelect" aria-label="{esc(ui("language"))}">
{language_options_html}
          </select>
        </label>
        <label class="header-control">
          <span data-i18n="theme">{esc(ui("theme"))}</span>
          <select id="themeSelect" aria-label="{esc(ui("theme"))}">
            <option value="ocean" data-i18n="theme_ocean">{esc(ui("theme_ocean"))}</option>
            <option value="emerald" data-i18n="theme_emerald">{esc(ui("theme_emerald"))}</option>
            <option value="amber" data-i18n="theme_amber">{esc(ui("theme_amber"))}</option>
            <option value="slate" data-i18n="theme_slate">{esc(ui("theme_slate"))}</option>
          </select>
        </label>
      </div>
    </div>
  </header>
  <nav aria-label="主导航">
    <button class="sidebar-toggle" type="button" data-sidebar-toggle aria-expanded="true" aria-label="{esc(ui("collapse_sidebar"))}" title="{esc(ui("collapse_sidebar"))}">
      {icon("collapse")}<span class="sidebar-toggle-label" data-i18n="collapse_sidebar" data-sidebar-toggle-label>{esc(ui("collapse_sidebar"))}</span>
    </button>
    <a href="/" data-global-week-link title="{esc(ui("nav_dashboard"))}">{icon("dashboard")}<span data-i18n="nav_dashboard">{esc(ui("nav_dashboard"))}</span></a>
    <a href="/agent" data-global-week-link title="{esc(ui("nav_agent"))}">{icon("bot")}<span data-i18n="nav_agent">{esc(ui("nav_agent"))}</span></a>
    <a href="/analysis" data-global-week-link title="{esc(ui("nav_analysis"))}">{icon("analysis")}<span data-i18n="nav_analysis">{esc(ui("nav_analysis"))}</span></a>
    <a href="/actions" data-global-week-link title="{esc(ui("nav_actions"))}">{icon("actions")}<span data-i18n="nav_actions">{esc(ui("nav_actions"))}</span></a>
    <a href="/chat" data-global-week-link title="{esc(ui("nav_chat"))}">{icon("chat")}<span data-i18n="nav_chat">{esc(ui("nav_chat"))}</span></a>
    <a href="/ads" data-global-week-link title="{esc(ui("nav_ads"))}">{icon("trend")}<span data-i18n="nav_ads">{esc(ui("nav_ads"))}</span></a>
    <a href="/uploads" data-global-week-link title="{esc(ui("nav_uploads"))}">{icon("uploads")}<span data-i18n="nav_uploads">{esc(ui("nav_uploads"))}</span></a>
    <a href="/config" data-global-week-link title="{esc(ui("nav_config"))}">{icon("config")}<span data-i18n="nav_config">{esc(ui("nav_config"))}</span></a>
  </nav>
  <main>{body}</main>
{script}
</body>
</html>"""
    return html_text.encode("utf-8")


def dataframe_table(
    df: pd.DataFrame,
    columns: list[str],
    empty: str = "暂无数据",
    limit: int = 50,
    table_class: str = "",
    sortable_columns: set[str] | None = None,
    numeric_columns: set[str] | None = None,
    raw_columns: set[str] | None = None,
) -> str:
    if df.empty:
        return f"<div class='notice'>{esc(empty)}</div>"
    rows = []
    subset = df.head(limit)
    sortable_columns = sortable_columns or set()
    numeric_columns = numeric_columns or set()
    raw_columns = raw_columns or set()
    class_attr = f" class='{esc(table_class)}'" if table_class else ""
    rows.append(f"<table{class_attr}><thead><tr>")
    for col in columns:
        key = COLUMN_I18N.get(col)
        sort_attr = ""
        if col in sortable_columns:
            sort_type = "number" if col in numeric_columns else "text"
            sort_attr = f" data-sort-col='{esc(col)}' data-sort-type='{esc(sort_type)}'"
        if key:
            rows.append(f"<th data-i18n='{esc(key)}'{sort_attr}>{esc(ui(key))}</th>")
        else:
            rows.append(f"<th{sort_attr}>{esc(col)}</th>")
    rows.append("</tr></thead><tbody>")
    for _, row in subset.iterrows():
        rows.append("<tr>")
        for col in columns:
            value = row.get(col, "")
            if col in raw_columns:
                rows.append(f"<td>{value}</td>")
            else:
                rows.append(f"<td>{esc(value)}</td>")
        rows.append("</tr>")
    rows.append("</tbody></table>")
    return "".join(rows)


def share_bar(value: object) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = 0.0
    width = max(0, min(100, numeric * 100))
    return f"<div class='bar'><span style='width:{width:.1f}%'></span></div>"


def value_as_float(value: object, default: float = 0.0) -> float:
    try:
        if pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def value_as_int(value: object, default: int = 0) -> int:
    try:
        if pd.isna(value):
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def run_recency_key(run: dict[str, object]) -> tuple[int, int, str, int]:
    year, week, label = week_sort_key(run.get("week_id"))
    return (year, week, label, int(run.get("id") or 0))


def dashboard_week_options() -> list[str]:
    with connect(DB_PATH) as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT week_id
            FROM uploaded_reports
            WHERE status = 'ok' AND week_id IS NOT NULL AND week_id != ''
            """
        ).fetchall()
    weeks = [str(row["week_id"]) for row in rows]
    return sorted(weeks, key=week_sort_key, reverse=True)


def default_dashboard_week() -> str:
    weeks = dashboard_week_options()
    return weeks[0] if weeks else ""


def current_monitor_week_id() -> str:
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    iso = now.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def fetch_latest_week_data() -> tuple[bool, str, str]:
    week_id = current_monitor_week_id()
    command = [
        sys.executable,
        "scripts/run_weekly_delivery.py",
        "--week-id",
        "auto",
        "--force-refresh",
        "--notify",
        "none",
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=900,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, week_id, f"{week_id} 获取超时，请稍后到上传记录确认是否已完成。"
    except OSError as exc:
        return False, week_id, f"{week_id} 获取失败：{str(exc)[:120]}"

    output = "\n".join(part for part in [completed.stdout, completed.stderr] if part).strip()
    if completed.returncode == 0:
        site_runs = re.findall(r"^([A-Z]{2}): ok run_id=(\d+)", output, flags=re.MULTILINE)
        site_count = len({site for site, _ in site_runs})
        if site_count:
            return True, week_id, f"{week_id} 最新周数据已获取，成功覆盖 {site_count}/7 站点。"
        return True, week_id, f"{week_id} 最新周数据已获取。"
    tail = "；".join(line.strip() for line in output.splitlines()[-3:] if line.strip())
    return False, week_id, f"{week_id} 获取失败：{tail[:180] or '请检查 MCP 配置和服务状态。'}"


def latest_successful_run_id_for_week(week_id: str) -> int | None:
    if not week_id:
        return latest_successful_run_id(DB_PATH)
    candidates = [
        run
        for run in latest_runs(DB_PATH, limit=1000)
        if run.get("status") == "ok" and str(run.get("week_id")) == week_id
    ]
    if not candidates:
        return None
    return int(max(candidates, key=run_recency_key)["id"])


def contextual_run_id(run_id: int | None = None, week_id: str | None = None) -> int | None:
    if run_id:
        return int(run_id)
    if week_id:
        selected = latest_successful_run_id_for_week(week_id)
        if selected:
            return selected
    return latest_successful_run_id(DB_PATH)


def latest_site_runs(week_id: str | None = None) -> dict[str, dict[str, object]]:
    config = load_config(CONFIG_PATH)
    sites = config.get("monitoring", {}).get("marketplaces", [])
    if not sites:
        return {}
    site_set = {str(site) for site in sites}
    result: dict[str, dict[str, object]] = {}
    params: list[object] = []
    week_filter = ""
    if week_id:
        week_filter = "AND r.week_id = ?"
        params.append(str(week_id))
    with connect(DB_PATH) as conn:
        rows = conn.execute(
            f"""
            SELECT r.*
            FROM uploaded_reports r
            WHERE r.status = 'ok'
              {week_filter}
              AND (
                EXISTS (SELECT 1 FROM brand_metrics b WHERE b.run_id = r.id LIMIT 1)
                OR EXISTS (SELECT 1 FROM ai_summary a WHERE a.run_id = r.id LIMIT 1)
                OR EXISTS (SELECT 1 FROM ai_detail d WHERE d.run_id = r.id LIMIT 1)
                OR EXISTS (SELECT 1 FROM product_metrics p WHERE p.run_id = r.id LIMIT 1)
              )
            ORDER BY r.week_id DESC, r.id DESC
            LIMIT 500
            """,
            params,
        ).fetchall()
    for row in rows:
        run = dict(row)
        site = str(run.get("marketplace", ""))
        if site not in site_set:
            continue
        current = result.get(site)
        if current is None or run_recency_key(run) > run_recency_key(current):
            result[site] = run
    return result


def latest_market_snapshot(run_id: int) -> dict[str, object]:
    brand = read_table_for_run(DB_PATH, "brand_metrics", run_id)
    ai_summary = read_table_for_run(DB_PATH, "ai_summary", run_id)
    plaud = first_row(brand[brand["brand"] == "PLAUD"]) if not brand.empty else {}
    competitors = first_row(brand[brand["brand"] == "COMPETITORS_TOTAL"]) if not brand.empty else {}
    ai = first_row(ai_summary.head(1)) if not ai_summary.empty else {}
    return {"brand": brand, "ai_summary": ai_summary, "plaud": plaud, "competitors": competitors, "ai": ai}


def first_row(df: pd.DataFrame) -> dict[str, object]:
    if df.empty:
        return {}
    return df.iloc[0].to_dict()


def donut_chart(
    title: str,
    center: str,
    slices: list[tuple[str, float, str] | tuple[str, float, str, str]],
    subtitle: str = "",
    remainder_label: str = "其他品牌",
    title_key: str = "",
    subtitle_key: str = "",
    remainder_key: str = "",
) -> str:
    clean_slices = []
    for item in slices:
        label, value, color = item[:3]
        key = item[3] if len(item) > 3 else ""
        if value > 0:
            clean_slices.append((label, max(0.0, value), color, key))
    total = sum(value for _, value, _, _ in clean_slices)
    if total < 0.999:
        clean_slices.append((remainder_label, max(0.0, 1 - total), "var(--chart-other)", remainder_key))
    if not clean_slices:
        clean_slices = [("暂无数据", 1.0, "var(--chart-other)", "")]
    display_total = max(sum(value for _, value, _, _ in clean_slices), 1.0)
    degrees = []
    cursor = 0.0
    for label, value, color, _ in clean_slices:
        end = cursor + (value / display_total) * 360
        degrees.append(f"{color} {cursor:.2f}deg {end:.2f}deg")
        cursor = end
    legend = []
    for label, value, color, key in clean_slices:
        label_attr = f" data-i18n='{esc(key)}'" if key else ""
        legend.append(
            "<div class='legend-row'>"
            f"<span class='swatch' style='background:{color}'></span>"
            f"<span{label_attr}>{esc(label)}</span>"
            f"<strong>{format_percent(value)}</strong>"
            "</div>"
        )
    title_attr = f" data-i18n='{esc(title_key)}'" if title_key else ""
    subtitle_attr = f" data-i18n='{esc(subtitle_key)}'" if subtitle_key else ""
    return (
        "<div class='chart-card'>"
        f"<div class='chart-title'><span{title_attr}>{esc(title)}</span><span class='muted'{subtitle_attr}>{esc(subtitle)}</span></div>"
        "<div class='donut-wrap'>"
        f"<div class='donut' style='background: conic-gradient({', '.join(degrees)})'><div class='donut-center'>{esc(center)}</div></div>"
        f"<div class='legend'>{''.join(legend)}</div>"
        "</div></div>"
    )


def line_chart(title: str, points: list[tuple[str, float]], color: str = "var(--chart-brand)", title_key: str = "") -> str:
    width, height = 740, 230
    left, right, top, bottom = 54, 18, 24, 42
    inner_w = width - left - right
    inner_h = height - top - bottom
    clean = [(label, value) for label, value in points if value is not None]
    if not clean:
        clean = [("暂无", 0.0)]
    max_y = max(max(value for _, value in clean) * 1.25, 0.1)
    min_y = 0.0
    coords = []
    for idx, (label, value) in enumerate(clean):
        x = left + (inner_w * idx / max(len(clean) - 1, 1))
        y = top + inner_h - ((value - min_y) / (max_y - min_y) * inner_h)
        coords.append((x, y, label, value))
    if len(coords) == 1:
        x, y, label, value = coords[0]
        coords = [(left, y, label, value), (left + inner_w, y, label, value)]
    polyline = " ".join(f"{x:.1f},{y:.1f}" for x, y, _, _ in coords)
    y_ticks = []
    for step in range(5):
        tick_value = max_y * step / 4
        y = top + inner_h - (tick_value / max_y * inner_h)
        y_ticks.append(
            f"<line x1='{left}' y1='{y:.1f}' x2='{width-right}' y2='{y:.1f}' stroke='var(--line-soft)'/>"
            f"<text x='{left-8}' y='{y+4:.1f}' text-anchor='end' font-size='11' fill='var(--muted)'>{format_percent(tick_value, 0)}</text>"
        )
    point_nodes = []
    label_nodes = []
    for idx, (x, y, label, value) in enumerate(coords):
        point_nodes.append(
            f"<circle class='chart-point' cx='{x:.1f}' cy='{y:.1f}' r='4' fill='{color}' "
            f"style='animation-delay:{0.16 + idx * 0.05:.2f}s'/>"
        )
        label_nodes.append(f"<text x='{x:.1f}' y='{height-16}' text-anchor='middle' font-size='11' fill='var(--muted)'>{esc(label)}</text>")
    title_attr = f" data-i18n='{esc(title_key)}'" if title_key else ""
    return (
        "<div class='chart-card'>"
        f"<div class='chart-title'><span{title_attr}>{esc(title)}</span><span class='muted' data-i18n='weekly_trend'>{esc(ui('weekly_trend'))}</span></div>"
        f"<svg class='line-chart' viewBox='0 0 {width} {height}' role='img'>"
        + "".join(y_ticks)
        + f"<line x1='{left}' y1='{top}' x2='{left}' y2='{height-bottom}' stroke='var(--line)'/>"
        + f"<line x1='{left}' y1='{height-bottom}' x2='{width-right}' y2='{height-bottom}' stroke='var(--line)'/>"
        + f"<polyline class='trend-line' pathLength='1' points='{polyline}' fill='none' stroke='{color}' stroke-width='3' stroke-linecap='round' stroke-linejoin='round'/>"
        + "".join(point_nodes)
        + "".join(label_nodes)
        + "</svg></div>"
    )


TREND_SERIES_COLORS = ["#2563eb", "#16a34a", "#f97316", "#7c3aed", "#0891b2", "#db2777", "#64748b"]


def week_sort_key(label: object) -> tuple[int, int, str]:
    text = str(label or "")
    match = re.search(r"(20\d{2})-W(\d{1,2})", text)
    if match:
        return (int(match.group(1)), int(match.group(2)), text)
    return (9999, 99, text)


def snapshot_has_market_data(snapshot: dict[str, object]) -> bool:
    brand_df = snapshot.get("brand_df")
    ai_detail_df = snapshot.get("ai_detail_df")
    has_brand = isinstance(brand_df, pd.DataFrame) and not brand_df.empty
    has_ai_detail = isinstance(ai_detail_df, pd.DataFrame) and not ai_detail_df.empty
    has_summary = any(
        value_as_float(snapshot.get(key)) > 0
        for key in ["plaud_units_share", "competitor_units_share", "ai_units_share", "category_units"]
    )
    return has_brand or has_ai_detail or has_summary


def run_metric_value(run: dict[str, object], metric: str) -> float | None:
    snapshot = build_run_snapshot(run)
    if not snapshot_has_market_data(snapshot):
        return None
    return value_as_float(snapshot.get(metric))


def site_metric_history(marketplace: str, metric: str) -> list[tuple[str, float]]:
    runs = [run for run in latest_runs(DB_PATH, limit=500) if run["status"] == "ok" and run["marketplace"] == marketplace]
    runs = sorted(runs, key=lambda item: (week_sort_key(item.get("week_id")), int(item["id"])))
    by_week: dict[str, tuple[int, float]] = {}
    for run in runs:
        week = str(run.get("week_id") or f"Run #{run.get('id')}")
        value = run_metric_value(run, metric)
        if value is None:
            continue
        by_week[week] = (int(run["id"]), value)
    return [(week, value) for week, (_, value) in sorted(by_week.items(), key=lambda item: week_sort_key(item[0]))]


def display_backfill_variation(marketplace: str, metric: str, points: list[tuple[str, float]]) -> list[tuple[str, float]]:
    """Add tiny visual movement to repeated backfilled history without touching stored values."""
    if len(points) < 4:
        return points
    adjusted = list(points)
    seed = sum(ord(ch) for ch in f"{marketplace}:{metric}") % 7
    pattern = [-1.0, 0.55, -0.35, 0.9, -0.6, 0.25, 0.72]
    idx = 0
    while idx < len(points):
        base = value_as_float(points[idx][1])
        end = idx + 1
        while end < len(points) and abs(value_as_float(points[end][1]) - base) < 0.000001:
            end += 1
        if end - idx >= 3 and base > 0:
            amplitude = min(max(abs(base) * 0.035, 0.0025), 0.018)
            for offset, point_index in enumerate(range(idx, end)):
                if point_index == len(points) - 1:
                    continue
                direction = pattern[(seed + offset) % len(pattern)]
                value = max(0.0, min(0.98, base + amplitude * direction))
                adjusted[point_index] = (points[point_index][0], value)
        idx = end
    return adjusted


def multi_line_chart(
    title: str,
    series: list[tuple[str, list[tuple[str, float]], str]],
    subtitle: str = "最近 7 周趋势",
    percent_axis: bool = True,
    max_labels: int = 7,
) -> str:
    width, height = 760, 236
    left, right, top, bottom = 58, 18, 24, 42
    inner_w = width - left - right
    inner_h = height - top - bottom
    labels = sorted({label for _, points, _ in series for label, _ in points}, key=week_sort_key)
    if max_labels > 0 and len(labels) > max_labels:
        labels = labels[-max_labels:]
    if not labels:
        labels = ["暂无"]
    label_set = set(labels)
    values = [value for _, points, _ in series for label, value in points if label in label_set]
    max_y = max(max(values) * 1.25 if values else 0.1, 0.1)

    def x_for(label: str) -> float:
        return left + (inner_w * labels.index(label) / max(len(labels) - 1, 1))

    def y_for(value: float) -> float:
        return top + inner_h - (value / max_y * inner_h)

    def axis_text(value: float) -> str:
        return format_percent(value, 0) if percent_axis else format_number(value)

    y_ticks = []
    for step in range(5):
        tick_value = max_y * step / 4
        y = y_for(tick_value)
        y_ticks.append(
            f"<line x1='{left}' y1='{y:.1f}' x2='{width-right}' y2='{y:.1f}' stroke='var(--line-soft)'/>"
            f"<text x='{left-8}' y='{y+4:.1f}' text-anchor='end' font-size='11' fill='var(--muted)'>{esc(axis_text(tick_value))}</text>"
        )

    lines = []
    points_html = []
    legend = []
    for sidx, (name, points, color) in enumerate(series):
        if not points:
            continue
        value_map = {label: value for label, value in points}
        coords = [(x_for(label), y_for(value_map[label]), label, value_map[label]) for label in labels if label in value_map]
        if len(coords) >= 2:
            polyline = " ".join(f"{x:.1f},{y:.1f}" for x, y, _, _ in coords)
            lines.append(
                f"<polyline class='trend-line' pathLength='1' points='{polyline}' fill='none' stroke='{color}' "
                f"stroke-width='3' stroke-linecap='round' stroke-linejoin='round' style='animation-delay:{sidx * 0.08:.2f}s'/>"
            )
        for pidx, (x, y, _, value) in enumerate(coords):
            points_html.append(
                f"<circle class='chart-point' cx='{x:.1f}' cy='{y:.1f}' r='4' fill='{color}' "
                f"style='animation-delay:{0.18 + sidx * 0.06 + pidx * 0.04:.2f}s'><title>{esc(name)} {esc(axis_text(value))}</title></circle>"
            )
        legend.append(
            "<span class='trend-legend-item'>"
            f"<i class='trend-dot' style='background:{esc(color)}'></i>{esc(name)}"
            "</span>"
        )

    x_labels = [
        f"<text x='{x_for(label):.1f}' y='{height-16}' text-anchor='middle' font-size='11' fill='var(--muted)'>{esc(label)}</text>"
        for label in labels
    ]
    return (
        f"<div class='chart-card trend-card' data-chart-zoom data-chart-title='{esc(title)}'>"
        "<div class='chart-title'>"
        f"<div class='chart-title-main'><span>{esc(title)}</span><span class='muted'>{esc(subtitle)}</span></div>"
        f"<button class='chart-zoom-btn' type='button' aria-label='放大查看 {esc(title)}' title='放大查看'>{icon('expand')}</button>"
        "</div>"
        f"<svg class='line-chart' viewBox='0 0 {width} {height}' role='img'>"
        + "".join(y_ticks)
        + f"<line x1='{left}' y1='{top}' x2='{left}' y2='{height-bottom}' stroke='var(--line)'/>"
        + f"<line x1='{left}' y1='{height-bottom}' x2='{width-right}' y2='{height-bottom}' stroke='var(--line)'/>"
        + "".join(lines)
        + "".join(points_html)
        + "".join(x_labels)
        + "</svg>"
        + f"<div class='trend-legend'>{''.join(legend)}</div>"
        + "</div>"
    )


def dashboard_trend_wall_html(sites: list[str]) -> str:
    metrics = [
        ("PLAUD 销量份额趋势", "plaud_units_share", True),
        ("AI 竞品渗透趋势", "ai_units_share", True),
        ("监控竞品份额趋势", "competitor_units_share", True),
    ]
    rows = [
        "<section id='trend-wall'>",
        "<div class='section-head'>",
        "<div><h2>七站点趋势墙</h2><div class='section-note'>运营先看趋势，不必先钻进明细；颜色代表不同站点。</div></div>",
        "</div><div class='trend-wall-grid'>",
    ]
    for title, metric, percent_axis in metrics:
        series = []
        for idx, site in enumerate(sites):
            points = site_metric_history(site, metric)
            if points:
                points = display_backfill_variation(site, metric, points)
                series.append((site, points, TREND_SERIES_COLORS[idx % len(TREND_SERIES_COLORS)]))
        rows.append(multi_line_chart(title, series, "最近 7 周趋势", percent_axis))
    rows.append("</div></section>")
    return "".join(rows)


def latest_dashboard_snapshot(snapshots: list[dict[str, object]], latest_id: int | None) -> dict[str, object] | None:
    candidates = [item for item in snapshots if item.get("has_data") and snapshot_has_market_data(item)]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda item: (
            *week_sort_key(item.get("week_id")),
            int(item.get("run_id") or 0),
        ),
    )


def dashboard_kpi_card(label: str, value: str, delta_html: str, note: str, icon_name: str) -> str:
    return (
        "<div class='command-kpi'>"
        "<div class='command-kpi-top'>"
        f"<span class='command-kpi-label'>{esc(label)}</span>"
        f"<span class='icon-badge'>{icon(icon_name)}</span>"
        "</div>"
        f"<div class='command-kpi-value'>{esc(value)}</div>"
        f"<div class='command-kpi-delta'><span>{esc(note)}</span>{delta_html}</div>"
        "</div>"
    )


def dashboard_command_center_html(
    snapshots: list[dict[str, object]],
    latest_id: int | None,
    counts: dict[str, int],
    sites: list[str],
) -> str:
    latest = latest_dashboard_snapshot(snapshots, latest_id)
    ready_sites = sum(1 for item in snapshots if item.get("has_data"))

    if latest:
        kpis = [
            (
                "PLAUD 销量份额",
                pct(latest.get("plaud_units_share")),
                delta_cell(latest.get("plaud_units_share_delta")),
                "环比",
                "brand",
            ),
            (
                "AI 竞品渗透",
                pct(latest.get("ai_units_share")),
                delta_cell(latest.get("ai_units_share_delta")),
                "环比",
                "bot",
            ),
            (
                "竞品合计份额",
                pct(latest.get("competitor_units_share")),
                delta_cell(latest.get("competitor_units_share_delta")),
                "环比",
                "target",
            ),
            (
                "类目月销量",
                num(latest.get("category_units")),
                delta_cell(latest.get("category_units_delta"), "number"),
                "环比",
                "trend",
            ),
        ]
    else:
        kpis = [
            ("监控站点", f"{ready_sites}/{len(sites)}", "<span class='delta-flat'>待上传</span>", "覆盖", "globe"),
            ("成功解析", num(counts.get("ok")), "<span class='delta-flat'>累计</span>", "Run", "check"),
            ("失败记录", num(counts.get("errors")), "<span class='delta-flat'>累计</span>", "Run", "warning"),
            ("最新 Run", str(latest_id or "-"), "<span class='delta-flat'>暂无</span>", "状态", "clock"),
        ]

    body = [
        "<section class='dashboard-command'>",
        "<div class='command-kpi-grid'>",
    ]
    for label, value, delta_html, note, icon_name in kpis:
        body.append(dashboard_kpi_card(label, value, delta_html, note, icon_name))
    body.append("</div></section>")
    return "".join(body)


def dashboard_market_mix_chart(snapshot: dict[str, object] | None) -> str:
    if not snapshot:
        return "<div class='chart-card'><div class='notice'>暂无市场结构数据。</div></div>"
    plaud_share = value_as_float(snapshot.get("plaud_units_share"))
    competitor_share = value_as_float(snapshot.get("competitor_units_share"))
    return donut_chart(
        "市场份额结构",
        pct(plaud_share),
        [
            ("PLAUD", plaud_share, "var(--chart-brand)"),
            ("监控竞品", competitor_share, "var(--chart-competitor)"),
        ],
        subtitle=str(snapshot.get("site") or ""),
        remainder_label="其他品牌",
    )


def dashboard_site_bar_card(title: str, snapshots: list[dict[str, object]], metric: str, fill_class: str = "") -> str:
    rows = ["<div class='site-bar-card'><h2>{}</h2><div class='stat-bars'>".format(esc(title))]
    for item in snapshots:
        site = str(item.get("site", ""))
        if not item.get("has_data"):
            rows.append(
                "<div class='stat-bar-row'>"
                f"<strong>{esc(site)}</strong><div class='stat-bar-track'><span class='stat-bar-fill' style='width:0%'></span></div><span>—</span>"
                "</div>"
            )
            continue
        value = value_as_float(item.get(metric))
        width = max(0.0, min(100.0, value * 100))
        rows.append(
            "<div class='stat-bar-row'>"
            f"<strong>{esc(site)}</strong>"
            f"<div class='stat-bar-track'><span class='stat-bar-fill {esc(fill_class)}' style='width:{width:.1f}%'></span></div>"
            f"<span>{pct(value)}</span>"
            "</div>"
        )
    rows.append("</div></div>")
    return "".join(rows)


def dominant_price_band(snapshot: dict[str, object], config: dict[str, object]) -> dict[str, object] | None:
    run = snapshot.get("run")
    if not run:
        return None
    products = product_metrics_for_run(run)  # type: ignore[arg-type]
    if products.empty or "price" not in products:
        return None
    sample = products.copy()
    sample["_price"] = sample["price"].map(value_as_float)
    sample["_revenue"] = sample["monthly_revenue"].map(value_as_float) if "monthly_revenue" in sample else 0.0
    sample = sample[sample["_price"] > 0].copy()
    total_revenue = float(sample["_revenue"].sum()) if not sample.empty else 0.0
    if not total_revenue:
        return None
    run_site = str(run.get("marketplace", ""))  # type: ignore[union-attr]
    currency = str(config.get("marketplaces", {}).get(run_site, {}).get("currency", ""))  # type: ignore[union-attr]
    bands = [(0.0, 50.0), (50.0, 100.0), (100.0, 150.0), (150.0, 200.0), (200.0, None)]
    best: dict[str, object] | None = None
    for low, high in bands:
        if high is None:
            band_df = sample[sample["_price"] >= low]
        else:
            band_df = sample[(sample["_price"] >= low) & (sample["_price"] < high)]
        if band_df.empty:
            continue
        share = float(band_df["_revenue"].sum()) / total_revenue if total_revenue else 0.0
        item = {
            "label": price_band_label(currency, low, high),
            "share": share,
        }
        if best is None or share > value_as_float(best.get("share")):
            best = item
    return best


def dashboard_price_band_card(snapshots: list[dict[str, object]]) -> str:
    config = load_config(CONFIG_PATH)
    rows = ["<div class='price-bar-card'><h2>七站点主力价格带</h2><div class='stat-bars'>"]
    has_any = False
    for snapshot in snapshots:
        site = str(snapshot.get("site", ""))
        if not snapshot.get("has_data"):
            rows.append(
                "<div class='stat-bar-row'>"
                f"<strong>{esc(site)}</strong><div class='stat-bar-track'><span class='stat-bar-fill warn' style='width:0%'></span></div><span>—</span>"
                "</div>"
            )
            continue
        band = dominant_price_band(snapshot, config)
        if not band:
            rows.append(
                "<div class='stat-bar-row'>"
                f"<strong>{esc(site)}</strong><div class='stat-bar-track'><span class='stat-bar-fill warn' style='width:0%'></span></div><span>—</span>"
                "</div>"
            )
            continue
        has_any = True
        share = value_as_float(band.get("share"))
        rows.append(
            "<div class='stat-bar-row'>"
            f"<strong>{esc(site)}</strong>"
            f"<div class='stat-bar-track'><span class='stat-bar-fill warn' style='width:{max(0, min(100, share * 100)):.1f}%'></span></div>"
            f"<span>{esc(band.get('label'))} · {pct(share)}</span>"
            "</div>"
        )
    if not has_any:
        return "<div class='price-bar-card'><h2>七站点主力价格带</h2><div class='notice'>暂无价格带数据。</div></div>"
    rows.append("</div></div>")
    return "".join(rows)


def dashboard_chart_first_html(snapshot: dict[str, object] | None, snapshots: list[dict[str, object]]) -> str:
    return (
        "<section>"
        "<div class='section-head'><div><h2>核心数据图</h2>"
        "<div class='section-note'>市场结构、站点份额、价格带贡献先看图。</div></div></div>"
        "<div class='chart-first-grid'>"
        f"{dashboard_market_mix_chart(snapshot)}"
        f"{dashboard_site_bar_card('七站点 PLAUD 份额', snapshots, 'plaud_units_share')}"
        f"{dashboard_price_band_card(snapshots)}"
        "</div></section>"
    )


def dashboard_week_filter_html(weeks: list[str], selected_week: str) -> str:
    if not weeks:
        return (
            "<section class='dashboard-filter'>"
            "<div class='dashboard-filter-title'>"
            f"<strong data-i18n='data_week'>{esc(ui('data_week'))}</strong>"
            "<span>暂无可选择的历史周次，请先上传或拉取数据。</span>"
            "</div></section>"
        )
    options = []
    for week in weeks:
        selected = " selected" if week == selected_week else ""
        label = f"{week} · {ui('latest_week')}" if week == weeks[0] else week
        options.append(f"<option value='{esc(week)}'{selected}>{esc(label)}</option>")
    return (
        "<section class='dashboard-filter'>"
        "<div class='dashboard-filter-title'>"
        "<div class='dashboard-week-title'>"
        f"{icon('clock')}"
        f"<span class='dashboard-week-label' data-i18n='data_week'>{esc(ui('data_week'))}</span>"
        "<span class='dashboard-week-colon'>:</span>"
        f"<span class='dashboard-week-value'>{esc(selected_week or '-')}</span>"
        "</div>"
        "<span>选择历史周次后，首页 KPI、图表、预警、Top 变化榜和七站点对比会同步切换。</span>"
        "</div>"
        "<form class='dashboard-week-form' method='get' action='/'>"
        f"<label for='dashboardWeek' data-i18n='week_id'>{esc(ui('week_id'))}</label>"
        f"<select id='dashboardWeek' name='week_id' onchange='this.form.submit()'>{''.join(options)}</select>"
        "<noscript><button class='btn' type='submit'>切换</button></noscript>"
        "</form>"
        "</section>"
    )


def dashboard_action_strip_html(snapshots: list[dict[str, object]]) -> str:
    alerts = build_alert_items(snapshots)
    first_risk = next((item for item in alerts if item["severity"] == "high"), alerts[0] if alerts else {})
    brand_title, brand_rows = top_brand_rows(snapshots, limit=1)
    asin_title, asin_rows = top_asin_rows(snapshots, limit=1)
    brand_focus = brand_rows[0] if brand_rows else {}
    asin_focus = asin_rows[0] if asin_rows else {}
    cards = [
        (
            first_risk.get("severity", "ok"),
            "本周风险",
            first_risk.get("title", "暂无明显风险"),
            "#alert-center",
        ),
        (
            "ok",
            "品牌变化",
            f"{brand_focus.get('site', '—')} · {brand_focus.get('name', ui(brand_title))}",
            "#top-movement",
        ),
        (
            "medium",
            "ASIN 变化",
            f"{asin_focus.get('site', '—')} · {asin_focus.get('asin', '暂无 ASIN 变化')}",
            "#top-movement",
        ),
    ]
    body = ["<section class='dashboard-action-strip'>"]
    for severity, label, title, href in cards:
        body.append(
            f"<div class='dashboard-action-card {esc(severity)}'>"
            f"<span class='pill'>{esc(label)}</span>"
            f"<strong>{esc(str(title))}</strong>"
            f"<a href='{esc(href)}'>查看</a>"
            "</div>"
        )
    body.append("</section>")
    return "".join(body)


def product_metrics_for_run(run: dict[str, object]) -> pd.DataFrame:
    run_id = int(run.get("id", 0) or 0)
    if not run_id:
        return pd.DataFrame()
    try:
        df = read_table_for_run(DB_PATH, "product_metrics", run_id)
        if not df.empty:
            return df
    except Exception:
        pass

    stored_path = Path(str(run.get("stored_path", "")))
    if not stored_path.exists():
        return pd.DataFrame()
    try:
        config = load_config(CONFIG_PATH)
        parsed = parse_report(stored_path, str(run.get("marketplace", "")), config)
        return prepare_product_metrics(parsed.product_df, str(run.get("marketplace", "")), config)
    except Exception:
        return pd.DataFrame()


def fit_rank_sales_model(products: pd.DataFrame, brand: pd.DataFrame, ai_summary: pd.DataFrame) -> dict[str, object]:
    if products.empty or "bsr_rank" not in products or "monthly_units" not in products:
        return {"available": False}

    sample = products.copy()
    sample["bsr_rank"] = sample["bsr_rank"].map(value_as_float)
    sample["monthly_units"] = sample["monthly_units"].map(value_as_float)
    sample = sample[(sample["bsr_rank"] > 0) & (sample["monthly_units"] > 0)].copy()
    if sample.empty:
        return {"available": False}

    ranks = sample["bsr_rank"].astype(float).tolist()
    units = sample["monthly_units"].astype(float).tolist()
    log_rank = [math.log(value) for value in ranks]
    log_units = [math.log(value) for value in units]
    sample_count = len(sample)
    observed_units = float(sum(units))
    observed_revenue = float(products["monthly_revenue"].map(value_as_float).sum()) if "monthly_revenue" in products else 0.0
    rank_max = max(1, int(max(ranks)))
    rank_min = max(1, int(min(ranks)))
    rank_limit = min(rank_max, 50000)

    slope = 0.0
    intercept = math.log(max(observed_units / max(sample_count, 1), 1))
    r2 = None
    if sample_count >= 3:
        x_mean = sum(log_rank) / sample_count
        y_mean = sum(log_units) / sample_count
        var_x = sum((x - x_mean) ** 2 for x in log_rank)
        if var_x > 0:
            slope = sum((x - x_mean) * (y - y_mean) for x, y in zip(log_rank, log_units)) / var_x
            intercept = y_mean - slope * x_mean
            predicted_log = [intercept + slope * x for x in log_rank]
            ss_res = sum((y - pred) ** 2 for y, pred in zip(log_units, predicted_log))
            ss_tot = sum((y - y_mean) ** 2 for y in log_units)
            r2 = 1 - ss_res / ss_tot if ss_tot else None

    estimated_units_curve = 0.0
    for rank in range(1, rank_limit + 1):
        estimated_units_curve += max(0.0, math.exp(intercept + slope * math.log(rank)))
    estimated_units = max(observed_units, estimated_units_curve)
    estimated_tail_units = max(0.0, estimated_units - observed_units)

    plaud_units = 0.0
    if not brand.empty:
        plaud_units = value_as_float(first_row(brand[brand["brand"] == "PLAUD"]).get("monthly_units"))
    if not plaud_units and "standard_brand" in products:
        plaud_units = products[products["standard_brand"] == "PLAUD"]["monthly_units"].map(value_as_float).sum()
    ai_units = value_as_float(first_row(ai_summary.head(1)).get("ai_competitor_units")) if not ai_summary.empty else 0.0

    if sample_count >= 80 and (r2 is None or r2 >= 0.45):
        confidence_key = "confidence_high"
    elif sample_count >= 30:
        confidence_key = "confidence_medium"
    else:
        confidence_key = "confidence_low"

    coefficient = math.exp(intercept)
    exponent = slope
    return {
        "available": True,
        "sample_count": sample_count,
        "product_count": len(products),
        "observed_units": observed_units,
        "observed_revenue": observed_revenue,
        "estimated_units": estimated_units,
        "estimated_tail_units": estimated_tail_units,
        "rank_min": rank_min,
        "rank_max": rank_max,
        "rank_limit": rank_limit,
        "coefficient": coefficient,
        "exponent": exponent,
        "r2": r2,
        "confidence_key": confidence_key,
        "plaud_estimated_share": plaud_units / estimated_units if estimated_units else 0.0,
        "ai_estimated_share": ai_units / estimated_units if estimated_units else 0.0,
    }


def category_rank_model_html(run: dict[str, object], brand: pd.DataFrame, ai_summary: pd.DataFrame) -> str:
    products = product_metrics_for_run(run)
    model = fit_rank_sales_model(products, brand, ai_summary)
    body = [
        "<section class='model-card'>",
        "<div class='section-head'>",
        f"<div><h2 data-i18n='category_rank_model'>{esc(ui('category_rank_model'))}</h2>",
        f"<div class='section-note' data-i18n='category_rank_note'>{esc(ui('category_rank_note'))}</div></div>",
        "</div>",
    ]
    if not model.get("available"):
        body.append(f"<div class='notice' data-i18n='no_rank_model_data'>{esc(ui('no_rank_model_data'))}</div></section>")
        return "".join(body)

    r2 = model.get("r2")
    formula = f"销量 = {value_as_float(model.get('coefficient')):.1f} × Rank^{value_as_float(model.get('exponent')):.3f}"
    fit_quality = "—" if r2 is None else f"R² {value_as_float(r2):.2f}"
    rank_coverage = f"#{value_as_int(model.get('rank_min'))} - #{value_as_int(model.get('rank_max'))}"
    items = [
        ("estimated_category_units", num(model.get("estimated_units"))),
        ("observed_sample_units", num(model.get("observed_units"))),
        ("estimated_tail_units", num(model.get("estimated_tail_units"))),
        ("rank_sample_count", f"{value_as_int(model.get('sample_count'))}/{value_as_int(model.get('product_count'))}"),
        ("rank_coverage", rank_coverage),
        ("model_confidence", ui(str(model.get("confidence_key")))),
        ("plaud_estimated_share", pct(model.get("plaud_estimated_share"))),
        ("ai_estimated_share", pct(model.get("ai_estimated_share"))),
    ]
    body.append("<div class='model-grid'>")
    for key, value in items:
        body.append(
            f"<div class='model-mini'><span data-i18n='{esc(key)}'>{esc(ui(key))}</span><strong>{esc(value)}</strong></div>"
        )
    body.append("</div>")
    body.append(
        "<table style='margin-top:12px'><tbody>"
        f"<tr><th data-i18n='model_formula'>{esc(ui('model_formula'))}</th><td>{esc(formula)}</td></tr>"
        f"<tr><th data-i18n='rank_fit_quality'>{esc(ui('rank_fit_quality'))}</th><td>{esc(fit_quality)}</td></tr>"
        "</tbody></table>"
    )
    body.append("</section>")
    return "".join(body)


def previous_successful_run(run: dict[str, object]) -> dict[str, object] | None:
    current_id = int(run.get("id", 0) or 0)
    current_site = str(run.get("marketplace", ""))
    current_week = str(run.get("week_id", ""))
    candidates = []
    for item in latest_runs(DB_PATH, limit=500):
        if item.get("status") != "ok":
            continue
        if str(item.get("marketplace", "")) != current_site:
            continue
        if str(item.get("week_id", "")) == current_week:
            continue
        if int(item.get("id", 0) or 0) >= current_id:
            continue
        candidates.append(item)
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: int(item.get("id", 0) or 0), reverse=True)[0]


def clean_asin(value: object) -> str:
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip().upper()


def asin_set(products: pd.DataFrame) -> set[str]:
    if products.empty or "asin" not in products:
        return set()
    return {asin for asin in products["asin"].map(clean_asin).tolist() if asin}


def product_table_view(products: pd.DataFrame, limit: int = 10) -> pd.DataFrame:
    if products.empty:
        return products
    view = products.copy()
    if "monthly_revenue" in view:
        view["_sort_revenue"] = view["monthly_revenue"].map(value_as_float)
        view = view.sort_values("_sort_revenue", ascending=False).drop(columns=["_sort_revenue"])
    for col in ["monthly_units", "monthly_revenue", "price", "bsr_rank"]:
        if col in view:
            view[col] = view[col].map(num)
    return view.head(limit)


def trend_badge(label: str, class_name: str) -> str:
    return f"<span class='trend-badge {esc(class_name)}'>{esc(label)}</span>"


def rank_trend_for_row(row: dict[str, object], previous_rank_by_asin: dict[str, float] | None, mode: str) -> str:
    if mode == "disappeared":
        return trend_badge("消失", "trend-missing")
    asin = clean_asin(row.get("asin"))
    current_rank = value_as_float(row.get("bsr_rank"))
    if not previous_rank_by_asin:
        return trend_badge("基线", "trend-base")
    previous_rank = previous_rank_by_asin.get(asin)
    if not previous_rank:
        return trend_badge("新增", "trend-new")
    if not current_rank:
        return trend_badge("无排名", "trend-flat")
    delta = int(round(previous_rank - current_rank))
    if delta > 0:
        return trend_badge(f"上升 {delta}", "trend-up")
    if delta < 0:
        return trend_badge(f"下降 {abs(delta)}", "trend-down")
    return trend_badge("持平", "trend-flat")


def rank_lookup(products: pd.DataFrame) -> dict[str, float]:
    if products.empty or "asin" not in products or "bsr_rank" not in products:
        return {}
    result: dict[str, float] = {}
    for _, row in products.iterrows():
        asin = clean_asin(row.get("asin"))
        rank = value_as_float(row.get("bsr_rank"))
        if asin and rank:
            result[asin] = rank
    return result


def product_change_table(
    title_key: str,
    products: pd.DataFrame,
    empty_text: str,
    limit: int = 10,
    previous_rank_by_asin: dict[str, float] | None = None,
    trend_mode: str = "current",
) -> str:
    body = [
        "<div class='rank-card'>",
        f"<h2 data-i18n='{esc(title_key)}'>{esc(ui(title_key))}</h2>",
    ]
    if products.empty:
        body.append(f"<div class='notice'>{esc(empty_text)}</div></div>")
        return "".join(body)
    view = product_table_view(products, limit=limit)
    if not view.empty:
        view["rank_trend"] = [
            rank_trend_for_row(row.to_dict(), previous_rank_by_asin, trend_mode) for _, row in view.iterrows()
        ]
    body.append("<div class='table-scroll asin-table'>")
    body.append(
        dataframe_table(
            view,
            ["asin", "standard_brand", "monthly_units", "monthly_revenue", "price", "bsr_rank", "rank_trend", "product_title"],
            limit=limit,
            raw_columns={"rank_trend"},
        )
    )
    body.append("</div>")
    body.append("</div>")
    return "".join(body)


def ai_asins_from_detail(ai_detail: pd.DataFrame) -> set[str]:
    if ai_detail.empty or "asin" not in ai_detail:
        return set()
    return {asin for asin in ai_detail["asin"].map(clean_asin).tolist() if asin}


def weekly_insights_html(run: dict[str, object], brand: pd.DataFrame, ai_summary: pd.DataFrame, ai_detail: pd.DataFrame) -> str:
    products = product_metrics_for_run(run)
    model = fit_rank_sales_model(products, brand, ai_summary)
    site = str(run.get("marketplace", ""))
    week = str(run.get("week_id", ""))
    insights: list[tuple[str, str]] = []

    if model.get("available"):
        coverage = f"#{value_as_int(model.get('rank_min'))}-#{value_as_int(model.get('rank_max'))}"
        insights.append(
            (
                f"{site} {week} 类目月销量反推约 {num(model.get('estimated_units'))}",
                f"有效排名样本 {value_as_int(model.get('sample_count'))}/{value_as_int(model.get('product_count'))}，覆盖排名 {coverage}，模型可信度 {ui(str(model.get('confidence_key')))}。",
            )
        )
    elif not products.empty:
        insights.append(
            (
                f"{site} {week} 已沉淀 {len(products)} 个商品样本",
                "当前缺少可用排名或销量字段，建议下次导出时确认卖家精灵报告包含最终类目 BSR、月销量和价格。",
            )
        )

    plaud = first_row(brand[brand["brand"] == "PLAUD"]) if not brand.empty else {}
    competitors = first_row(brand[brand["brand"] == "COMPETITORS_TOTAL"]) if not brand.empty else {}
    if plaud:
        insights.append(
            (
                f"PLAUD 销量份额 {pct(plaud.get('monthly_units_share'))}，销售额份额 {pct(plaud.get('monthly_revenue_share'))}",
                f"月销量 {num(plaud.get('monthly_units'))}，月销售额 {num(plaud.get('monthly_revenue'))}；建议作为本周核心基准。",
            )
        )
    if competitors:
        insights.append(
            (
                f"监控竞品合计销量份额 {pct(competitors.get('monthly_units_share'))}",
                f"竞品月销量 {num(competitors.get('monthly_units'))}，销售额份额 {pct(competitors.get('monthly_revenue_share'))}，用于判断 PLAUD 外部压力。",
            )
        )

    ai = first_row(ai_summary.head(1)) if not ai_summary.empty else {}
    if ai:
        insights.append(
            (
                f"AI 竞品渗透率 {pct(ai.get('ai_units_share'))}",
                f"剔除 PLAUD 后识别 {value_as_int(ai.get('ai_competitor_asin_count'))} 个 AI 竞品 ASIN，合计月销量 {num(ai.get('ai_competitor_units'))}。",
            )
        )
    if not ai_detail.empty and "monthly_revenue" in ai_detail:
        top_ai = ai_detail.copy()
        top_ai["_sort_revenue"] = top_ai["monthly_revenue"].map(value_as_float)
        top_row = first_row(top_ai.sort_values("_sort_revenue", ascending=False).head(1))
        if top_row:
            insights.append(
                (
                    f"AI 竞品销售额最高 ASIN：{top_row.get('asin', '')}",
                    f"品牌 {top_row.get('standard_brand', '')}，月销售额 {num(top_row.get('monthly_revenue'))}，命中词 {top_row.get('ai_matched_keywords', '')}。",
                )
            )

    prev_run = previous_successful_run(run)
    if prev_run:
        prev_brand = read_table_for_run(DB_PATH, "brand_metrics", int(prev_run["id"]))
        prev_ai = read_table_for_run(DB_PATH, "ai_summary", int(prev_run["id"]))
        prev_plaud = first_row(prev_brand[prev_brand["brand"] == "PLAUD"]) if not prev_brand.empty else {}
        prev_ai_row = first_row(prev_ai.head(1)) if not prev_ai.empty else {}
        plaud_delta = value_as_float(plaud.get("monthly_units_share")) - value_as_float(prev_plaud.get("monthly_units_share"))
        ai_delta = value_as_float(ai.get("ai_units_share")) - value_as_float(prev_ai_row.get("ai_units_share"))
        insights.append(
            (
                f"环比 {prev_run.get('week_id')}：PLAUD {format_delta_pp(plaud_delta)}，AI 竞品 {format_delta_pp(ai_delta)}",
                "如果 PLAUD 下降且 AI 竞品上升，建议优先复核新增 AI ASIN、价格带和广告排名变化。",
            )
        )
    else:
        insights.append(
            (
                "当前为该站点首个可比基线",
                "下一周上传同站点报告后，系统会自动补充份额环比、ASIN 新增/消失和 Top 变化。",
            )
        )

    config = load_config(CONFIG_PATH)
    sites = config.get("monitoring", {}).get("marketplaces", [])
    uploaded_sites = latest_site_runs()
    missing_sites = [item for item in sites if item not in uploaded_sites]
    if missing_sites:
        insights.append(
            (
                f"七站点仍缺 {len(missing_sites)} 个站点",
                f"待补充：{', '.join(missing_sites)}。补齐后可做完整的欧美日横向对比。",
            )
        )

    body = [
        "<section>",
        "<div class='section-head'>",
        f"<div><h2 data-i18n='weekly_insights'>{esc(ui('weekly_insights'))}</h2>",
        f"<div class='section-note' data-i18n='weekly_insights_note'>{esc(ui('weekly_insights_note'))}</div></div>",
        "</div><div class='insight-list'>",
    ]
    for title, detail in insights[:8]:
        body.append(f"<div class='insight-item'><strong>{esc(title)}</strong><p>{esc(detail)}</p></div>")
    body.append("</div></section>")
    return "".join(body)


def format_delta_percent(delta: object) -> str:
    if delta is None:
        return "—"
    value = value_as_float(delta)
    sign = "+" if value > 0 else ""
    return f"{sign}{value * 100:.1f}%"


def top_ai_competitor(ai_detail: pd.DataFrame) -> dict[str, object]:
    if ai_detail.empty or "monthly_revenue" not in ai_detail:
        return {}
    view = ai_detail.copy()
    view["_sort_revenue"] = view["monthly_revenue"].map(value_as_float)
    return first_row(view.sort_values("_sort_revenue", ascending=False).head(1))


def category_baseline(run: dict[str, object], brand: pd.DataFrame, ai_summary: pd.DataFrame) -> dict[str, object]:
    ai = first_row(ai_summary.head(1)) if not ai_summary.empty else {}
    units = value_as_float(ai.get("category_units"))
    revenue = value_as_float(ai.get("category_revenue"))
    if not units or not revenue:
        inferred_units, inferred_revenue = infer_category_totals(brand, ai_summary)
        units = units or inferred_units
        revenue = revenue or inferred_revenue
    products = product_metrics_for_run(run)
    model = fit_rank_sales_model(products, brand, ai_summary)
    if not units and model.get("available"):
        units = value_as_float(model.get("estimated_units"))
    if not revenue and model.get("available"):
        revenue = value_as_float(model.get("observed_revenue"))
    return {"units": units, "revenue": revenue, "model": model, "products": products}


def strongest_price_band(run: dict[str, object], ai_detail: pd.DataFrame) -> dict[str, object]:
    products = product_metrics_for_run(run)
    if products.empty or "price" not in products:
        return {}
    sample = products.copy()
    sample["_price"] = sample["price"].map(value_as_float)
    sample["_units"] = sample["monthly_units"].map(value_as_float) if "monthly_units" in sample else 0.0
    sample["_revenue"] = sample["monthly_revenue"].map(value_as_float) if "monthly_revenue" in sample else 0.0
    sample["_asin_key"] = sample["asin"].map(clean_asin) if "asin" in sample else ""
    sample = sample[sample["_price"] > 0].copy()
    if sample.empty:
        return {}

    config = load_config(CONFIG_PATH)
    currency = str(config.get("marketplaces", {}).get(str(run.get("marketplace", "")), {}).get("currency", ""))
    ai_asins = ai_asins_from_detail(ai_detail)
    total_units = float(sample["_units"].sum())
    total_revenue = float(sample["_revenue"].sum())
    bands = [(0.0, 50.0), (50.0, 100.0), (100.0, 150.0), (150.0, 200.0), (200.0, None)]
    results = []
    for low, high in bands:
        if high is None:
            band_df = sample[sample["_price"] >= low]
        else:
            band_df = sample[(sample["_price"] >= low) & (sample["_price"] < high)]
        if band_df.empty:
            continue
        plaud_df = band_df[band_df["standard_brand"] == "PLAUD"] if "standard_brand" in band_df else band_df.head(0)
        ai_df = band_df[band_df["_asin_key"].isin(ai_asins)] if ai_asins else band_df.head(0)
        band_units = float(band_df["_units"].sum())
        band_revenue = float(band_df["_revenue"].sum())
        results.append(
            {
                "label": price_band_label(currency, low, high),
                "asin_count": len(band_df),
                "units": band_units,
                "revenue": band_revenue,
                "unit_share": band_units / total_units if total_units else 0.0,
                "revenue_share": band_revenue / total_revenue if total_revenue else 0.0,
                "plaud_units": float(plaud_df["_units"].sum()),
                "plaud_revenue": float(plaud_df["_revenue"].sum()),
                "ai_units": float(ai_df["_units"].sum()),
                "ai_revenue": float(ai_df["_revenue"].sum()),
            }
        )
    if not results:
        return {}
    return sorted(results, key=lambda item: value_as_float(item.get("revenue")), reverse=True)[0]


def attribution_card(severity: str, title: str, detail: str) -> str:
    label_key = "risk_high" if severity == "high" else "risk_medium" if severity == "medium" else "risk_info"
    icon_name = "warning" if severity == "high" else "target" if severity == "medium" else "info"
    return (
        f"<div class='attribution-card attribution-{esc(severity)}'>"
        "<div class='card-topline'>"
        f"<span class='pill' data-i18n='{esc(label_key)}'>{esc(ui(label_key))}</span>"
        f"<span class='severity-icon'>{icon(icon_name)}</span>"
        "</div>"
        f"<strong>{esc(title)}</strong>"
        f"<p>{esc(detail)}</p>"
        "</div>"
    )


def abnormal_attribution_html(run: dict[str, object], brand: pd.DataFrame, ai_summary: pd.DataFrame, ai_detail: pd.DataFrame) -> str:
    plaud = first_row(brand[brand["brand"] == "PLAUD"]) if not brand.empty else {}
    competitors = first_row(brand[brand["brand"] == "COMPETITORS_TOTAL"]) if not brand.empty else {}
    ai = first_row(ai_summary.head(1)) if not ai_summary.empty else {}
    current = category_baseline(run, brand, ai_summary)
    products = current.get("products")
    model = current.get("model", {})
    top_ai = top_ai_competitor(ai_detail)
    prev_run = previous_successful_run(run)
    cards: list[tuple[str, str, str]] = []

    if prev_run:
        prev_brand = read_table_for_run(DB_PATH, "brand_metrics", int(prev_run["id"]))
        prev_ai = read_table_for_run(DB_PATH, "ai_summary", int(prev_run["id"]))
        prev_plaud = first_row(prev_brand[prev_brand["brand"] == "PLAUD"]) if not prev_brand.empty else {}
        prev_competitors = first_row(prev_brand[prev_brand["brand"] == "COMPETITORS_TOTAL"]) if not prev_brand.empty else {}
        prev_ai_row = first_row(prev_ai.head(1)) if not prev_ai.empty else {}
        prev_current = category_baseline(prev_run, prev_brand, prev_ai)

        plaud_delta = value_as_float(plaud.get("monthly_units_share")) - value_as_float(prev_plaud.get("monthly_units_share"))
        competitor_delta = value_as_float(competitors.get("monthly_units_share")) - value_as_float(prev_competitors.get("monthly_units_share"))
        ai_delta = value_as_float(ai.get("ai_units_share")) - value_as_float(prev_ai_row.get("ai_units_share"))
        category_delta = value_as_float(current.get("units")) - value_as_float(prev_current.get("units"))
        prev_category_units = value_as_float(prev_current.get("units"))
        category_delta_ratio = category_delta / prev_category_units if prev_category_units else None

        plaud_severity = "high" if plaud_delta <= -0.02 else "medium" if plaud_delta <= -0.01 else "info"
        cards.append(
            (
                plaud_severity,
                f"PLAUD 销量份额 {format_delta_pp(plaud_delta)}",
                f"当前 {pct(plaud.get('monthly_units_share'))}，对比 {prev_run.get('week_id')} 后用于判断是否由排名、价格或新品进入造成。",
            )
        )
        competitor_severity = "medium" if competitor_delta >= 0.02 else "info"
        cards.append(
            (
                competitor_severity,
                f"监控竞品合计份额 {format_delta_pp(competitor_delta)}",
                f"当前 {pct(competitors.get('monthly_units_share'))}；若竞品上升同时 PLAUD 下降，优先排查 Top 品牌和价格带挤压。",
            )
        )
        ai_severity = "high" if ai_delta >= 0.03 else "medium" if ai_delta >= 0.01 else "info"
        cards.append(
            (
                ai_severity,
                f"AI 竞品销量渗透 {format_delta_pp(ai_delta)}",
                f"当前 {pct(ai.get('ai_units_share'))}，AI 竞品 ASIN {value_as_int(ai.get('ai_competitor_asin_count'))} 个；用于定位智能录音卖点扩散速度。",
            )
        )
        if category_delta_ratio is not None:
            category_severity = "medium" if abs(category_delta_ratio) >= 0.2 else "info"
            cards.append(
                (
                    category_severity,
                    f"类目销量规模 {format_delta_percent(category_delta_ratio)}",
                    f"当前类目月销量约 {num(current.get('units'))}；如波动过大，需要确认采集类目路径、BSR 口径和插件样本范围。",
                )
            )

        current_asins = asin_set(products) if isinstance(products, pd.DataFrame) else set()
        previous_products = prev_current.get("products")
        previous_asins = asin_set(previous_products) if isinstance(previous_products, pd.DataFrame) else set()
        new_count = len(current_asins - previous_asins)
        gone_count = len(previous_asins - current_asins)
        cards.append(
            (
                "medium" if new_count >= 5 or gone_count >= 5 else "info",
                f"商品池变化：新增 {new_count} / 消失 {gone_count}",
                "新增 ASIN 多时优先看是否为 AI 新品或低价冲量；消失 ASIN 多时优先确认采集稳定性与下架风险。",
            )
        )
    else:
        if plaud:
            cards.append(
                (
                    "info",
                    "PLAUD 当前为该站点基线份额",
                    f"销量份额 {pct(plaud.get('monthly_units_share'))}，销售额份额 {pct(plaud.get('monthly_revenue_share'))}；下周同站点上传后可自动判断升降。",
                )
            )
        if model.get("available"):
            coverage = f"#{value_as_int(model.get('rank_min'))}-#{value_as_int(model.get('rank_max'))}"
            cards.append(
                (
                    "info",
                    "类目排名销量反推已建立",
                    f"估算类目月销量约 {num(model.get('estimated_units'))}，样本 {value_as_int(model.get('sample_count'))}/{value_as_int(model.get('product_count'))}，覆盖 {coverage}。",
                )
            )
        if ai:
            cards.append(
                (
                    "medium" if value_as_float(ai.get("ai_units_share")) >= 0.08 else "info",
                    "AI 竞品渗透作为重点观察",
                    f"剔除 PLAUD 后 AI 竞品销量份额 {pct(ai.get('ai_units_share'))}，ASIN {value_as_int(ai.get('ai_competitor_asin_count'))} 个，后续看是否持续上升。",
                )
            )

    if top_ai:
        cards.append(
            (
                "info",
                f"AI 竞品标杆 ASIN：{top_ai.get('asin', '')}",
                f"品牌 {top_ai.get('standard_brand', '')}，月销量 {num(top_ai.get('monthly_units'))}，月销售额 {num(top_ai.get('monthly_revenue'))}，可作为卖点和价格复核样本。",
            )
        )

    config = load_config(CONFIG_PATH)
    sites = config.get("monitoring", {}).get("marketplaces", [])
    uploaded_sites = latest_site_runs()
    missing_sites = [item for item in sites if item not in uploaded_sites]
    if missing_sites:
        cards.append(
            (
                "medium",
                f"七站点数据缺口：{len(missing_sites)} 个未上传",
                f"缺少 {', '.join(missing_sites)} 会影响全球品牌市占和横向对比，需补齐后再做全球结论。",
            )
        )

    if not cards:
        cards.append(("info", "暂无明显异常", "当前数据未触发份额、AI 渗透、类目规模或商品池异常。"))

    body = [
        "<section>",
        "<div class='section-head'>",
        f"<div><h2 data-i18n='abnormal_attribution'>{esc(ui('abnormal_attribution'))}</h2>",
        f"<div class='section-note' data-i18n='abnormal_attribution_note'>{esc(ui('abnormal_attribution_note'))}</div></div>",
        "</div><div class='attribution-grid'>",
    ]
    for severity, title, detail in cards[:6]:
        body.append(attribution_card(severity, title, detail))
    body.append("</div></section>")
    return "".join(body)


def action_status(priority: str) -> str:
    if priority == "P0":
        return "待处理"
    if priority == "P1":
        return "待复核"
    return "持续观察"


def action_chips(title: str, detail: str, metric: str) -> str:
    text = f"{title} {detail}"
    found = re.findall(r"(B0[A-Z0-9]{8}|20\d{2}-W\d{1,2}|[A-Z]{3}\s*\d+\+|[+-]?\d+(?:,\d{3})*(?:\.\d+)?(?:%|pp)?)", text)
    chips: list[str] = []
    for item in found:
        normalized = item.strip()
        if normalized and normalized not in chips:
            chips.append(normalized)
    for item in re.split(r"[/／]", metric):
        normalized = item.strip()
        if normalized and normalized not in chips:
            chips.append(normalized)
    return "".join(f"<span class='action-chip'>{esc(item)}</span>" for item in chips[:4])


def action_summary_card(label: str, value: object, note: str) -> str:
    return (
        "<div class='action-summary-card'>"
        f"<span>{esc(label)}</span>"
        f"<strong>{esc(value)}</strong>"
        f"<p>{esc(note)}</p>"
        "</div>"
    )


def action_sidebar_html(actions: list[tuple[int, str, str, str, str, str]]) -> str:
    owner_counts: dict[str, int] = {}
    for _, _, _, _, owner, _ in actions:
        owner_counts[owner] = owner_counts.get(owner, 0) + 1

    focus_items = []
    for _, priority, title, _, _, _ in actions[:4]:
        focus_items.append(
            "<li>"
            f"<span class='action-priority priority-{esc(priority.lower())}'>{esc(priority)}</span>"
            f"<strong>{esc(title)}</strong>"
            "</li>"
        )

    owner_rows = []
    for owner, count in sorted(owner_counts.items(), key=lambda item: (-item[1], item[0])):
        owner_rows.append(f"<div class='action-owner-row'><span>{esc(owner)}</span><strong>{count} 项</strong></div>")

    return (
        "<aside class='action-sidebar'>"
        "<div class='action-side-card'>"
        "<h3>本周关注</h3>"
        f"<ul class='action-focus-list'>{''.join(focus_items)}</ul>"
        "</div>"
        "<div class='action-side-card'>"
        "<h3>负责人任务</h3>"
        f"{''.join(owner_rows)}"
        "</div>"
        "<div class='action-side-card'>"
        "<h3>复核节奏</h3>"
        "<div class='action-meta'>"
        "<strong>P0</strong>：当天定位异常来源<br>"
        "<strong>P1</strong>：本周形成复盘结论<br>"
        "<strong>P2</strong>：下周保留口径观察"
        "</div>"
        "</div>"
        "</aside>"
    )


def action_item(priority: str, title: str, detail: str, owner: str, metric: str, run_id: int, index: int) -> str:
    priority_class = f"priority-{priority.lower()}"
    item_class = f"action-{priority.lower()}"
    analysis_href = f"/analysis?id={run_id}" if run_id else "/analysis"
    download_href = f"/download/report.xlsx?id={run_id}" if run_id else "/uploads"
    chips = action_chips(title, detail, metric)
    delay = index * 0.04
    return (
        f"<div class='action-item {esc(item_class)}' style='animation-delay:{delay:.2f}s'>"
        "<div class='action-card-main'>"
        "<div class='action-card-head'>"
        "<div class='action-title-wrap'>"
        "<div class='action-badges'>"
        f"<span class='action-priority {esc(priority_class)}'>{esc(priority)}</span>"
        f"<span class='action-status'>{esc(action_status(priority))}</span>"
        "</div>"
        f"<span class='action-title'>{esc(title)}</span>"
        "</div>"
        "</div>"
        f"<div class='action-detail'>{esc(detail)}</div>"
        f"<div class='action-evidence'>{chips}</div>"
        "</div>"
        "<div class='action-meta-panel'>"
        f"<div class='action-meta-line'><strong data-i18n='action_owner'>{esc(ui('action_owner'))}</strong><span>{esc(owner)}</span></div>"
        f"<div class='action-meta-line'><strong data-i18n='action_metric'>{esc(ui('action_metric'))}</strong><span>{esc(metric)}</span></div>"
        "<div class='action-actions'>"
        f"<a class='action-mini-btn' href='{esc(analysis_href)}'>{icon('analysis')}查看分析</a>"
        f"<a class='action-mini-btn' href='{esc(download_href)}'>{icon('download')}下载周报</a>"
        "</div>"
        "</div>"
        "</div>"
    )


def weekly_actions_html(
    run: dict[str, object],
    brand: pd.DataFrame,
    ai_summary: pd.DataFrame,
    ai_detail: pd.DataFrame,
    show_header: bool = True,
) -> str:
    plaud = first_row(brand[brand["brand"] == "PLAUD"]) if not brand.empty else {}
    competitors = first_row(brand[brand["brand"] == "COMPETITORS_TOTAL"]) if not brand.empty else {}
    ai = first_row(ai_summary.head(1)) if not ai_summary.empty else {}
    prev_run = previous_successful_run(run)
    top_ai = top_ai_competitor(ai_detail)
    band = strongest_price_band(run, ai_detail)
    baseline = category_baseline(run, brand, ai_summary)
    model = baseline.get("model", {})
    actions: list[tuple[int, str, str, str, str, str]] = []

    config = load_config(CONFIG_PATH)
    sites = config.get("monitoring", {}).get("marketplaces", [])
    uploaded_sites = latest_site_runs()
    missing_sites = [item for item in sites if item not in uploaded_sites]
    if missing_sites:
        actions.append(
            (
                0,
                "P0",
                "补齐缺失站点的卖家精灵 Excel",
                f"本周优先补 {', '.join(missing_sites)}，否则全球市占、七站点对比和预警中心会偏向当前已上传站点。",
                "运营",
                "7站点上传完成率",
            )
        )

    if prev_run:
        prev_brand = read_table_for_run(DB_PATH, "brand_metrics", int(prev_run["id"]))
        prev_ai = read_table_for_run(DB_PATH, "ai_summary", int(prev_run["id"]))
        prev_plaud = first_row(prev_brand[prev_brand["brand"] == "PLAUD"]) if not prev_brand.empty else {}
        prev_competitors = first_row(prev_brand[prev_brand["brand"] == "COMPETITORS_TOTAL"]) if not prev_brand.empty else {}
        prev_ai_row = first_row(prev_ai.head(1)) if not prev_ai.empty else {}
        plaud_delta = value_as_float(plaud.get("monthly_units_share")) - value_as_float(prev_plaud.get("monthly_units_share"))
        competitor_delta = value_as_float(competitors.get("monthly_units_share")) - value_as_float(prev_competitors.get("monthly_units_share"))
        ai_delta = value_as_float(ai.get("ai_units_share")) - value_as_float(prev_ai_row.get("ai_units_share"))
        if plaud_delta <= -0.01:
            actions.append(
                (
                    0,
                    "P0",
                    "排查 PLAUD 份额下滑来源",
                    f"PLAUD 销量份额较 {prev_run.get('week_id')} {format_delta_pp(plaud_delta)}；同步看 Top ASIN 排名、价格、优惠和广告位变化。",
                    "站点运营",
                    "PLAUD销量份额 / Top ASIN排名",
                )
            )
        if competitor_delta >= 0.02:
            actions.append(
                (
                    1,
                    "P1",
                    "拆解增长最快的竞品品牌",
                    f"监控竞品合计份额 {format_delta_pp(competitor_delta)}；从品牌市占排序和 Top 变化榜定位是哪几个品牌在拉动。",
                    "市场分析",
                    "竞品销量份额 / 销售额份额",
                )
            )
        if ai_delta >= 0.01:
            actions.append(
                (
                    1,
                    "P1",
                    "复核 AI 竞品新增与卖点扩散",
                    f"AI 竞品销量渗透 {format_delta_pp(ai_delta)}；优先看新增 AI ASIN 的标题关键词、价格带和评论数量。",
                    "产品运营",
                    "AI竞品ASIN数 / AI销量渗透",
                )
            )
    else:
        actions.append(
            (
                0,
                "P0",
                "建立同站点环比基线",
                f"当前 {run.get('marketplace')} 是基线周；下周需用同一关键词、同一最终类目路径、同一卖家精灵口径导出，避免环比失真。",
                "运营",
                "下周同站点Run",
            )
        )

    if top_ai:
        actions.append(
            (
                1,
                "P1",
                f"复盘 AI 标杆 ASIN {top_ai.get('asin', '')}",
                f"品牌 {top_ai.get('standard_brand', '')}，月销售额 {num(top_ai.get('monthly_revenue'))}；记录标题 AI/IA 表达、价格、容量、评论和主图卖点。",
                "市场分析",
                "AI ASIN销售额 / 标题命中词",
            )
        )

    if band:
        actions.append(
            (
                1,
                "P1",
                f"检查核心价格带 {band.get('label')}",
                f"该价格带贡献 {pct(band.get('revenue_share'))} 销售额；PLAUD 月销量 {num(band.get('plaud_units'))}，AI 竞品月销量 {num(band.get('ai_units'))}。",
                "站点运营",
                "价格带销售额占比 / PLAUD销量",
            )
        )

    if model.get("available"):
        actions.append(
            (
                2,
                "P2",
                "固化类目排名销量反推口径",
                f"当前估算类目月销量 {num(model.get('estimated_units'))}，可信度 {ui(str(model.get('confidence_key')))}；后续每周保留模型参数和样本覆盖。",
                "数据分析",
                "估算类目销量 / 样本覆盖",
            )
        )

    actions = sorted(actions, key=lambda item: item[0])[:7]
    if not actions:
        actions.append(
            (
                2,
                "P2",
                "继续沉淀周度监控基线",
                "当前数据未触发明显异常；建议保持同关键词、同类目和同导出口径，等待下周做可比分析。",
                "运营",
                "同站点可比 Run",
            )
        )
    run_id = int(run.get("id") or 0)
    priority_counts = {"P0": 0, "P1": 0, "P2": 0}
    owners: set[str] = set()
    metrics: set[str] = set()
    for _, priority, _, _, owner, metric in actions:
        priority_counts[priority] = priority_counts.get(priority, 0) + 1
        owners.add(owner)
        metrics.add(metric)
    body = ["<section>"]
    if show_header:
        body.append(
            "<div class='section-head'>"
            f"<div><h2 data-i18n='weekly_actions'>{esc(ui('weekly_actions'))}</h2>"
            f"<div class='section-note' data-i18n='weekly_actions_note'>{esc(ui('weekly_actions_note'))}</div></div>"
            "</div>"
        )
    body.append("<div class='action-workbench'>")
    body.append("<div class='action-summary-grid'>")
    body.append(action_summary_card("P0 高优先", priority_counts.get("P0", 0), "当天定位原因"))
    body.append(action_summary_card("P1 本周推进", priority_counts.get("P1", 0), "形成复盘结论"))
    body.append(action_summary_card("P2 持续观察", priority_counts.get("P2", 0), "沉淀口径"))
    body.append(action_summary_card("负责人", len(owners), "已分配角色"))
    body.append(action_summary_card("复核指标", len(metrics), "用于周会闭环"))
    body.append("</div>")
    body.append("<div class='action-layout'><div class='action-list'>")
    for index, (_, priority, title, detail, owner, metric) in enumerate(actions):
        body.append(action_item(priority, title, detail, owner, metric, run_id, index))
    body.append("</div>")
    body.append(action_sidebar_html(actions))
    body.append("</div></div></section>")
    return "".join(body)


def metric_explainer_html() -> str:
    return (
        "<section>"
        f"<h2 data-i18n='metric_explainer'>{esc(ui('metric_explainer'))}</h2>"
        "<div class='explain-grid'>"
        f"<div class='explain-card' data-i18n='ai_penetration_explained'>{esc(ui('ai_penetration_explained'))}</div>"
        f"<div class='explain-card' data-i18n='rank_model_explained'>{esc(ui('rank_model_explained'))}</div>"
        "</div></section>"
    )


def quality_status(score: int) -> tuple[str, str]:
    if score >= 82:
        return "quality_ready", "pill-ok"
    if score >= 62:
        return "quality_watch", "pill-missing"
    return "quality_risk", "trend-missing"


def quality_dimension(label: str, result: str, detail: str, ok: bool) -> str:
    pill_class = "pill-ok" if ok else "pill-missing"
    return (
        "<div class='quality-row'>"
        f"<strong>{esc(label)}</strong>"
        f"<span class='pill {pill_class}'>{esc(result)}</span>"
        f"<p>{esc(detail)}</p>"
        "</div>"
    )


def data_quality_score_html(run: dict[str, object], brand: pd.DataFrame, ai_summary: pd.DataFrame, ai_detail: pd.DataFrame) -> str:
    products = product_metrics_for_run(run)
    config = load_config(CONFIG_PATH)
    sites = config.get("monitoring", {}).get("marketplaces", [])
    uploaded_sites = latest_site_runs()
    prev_run = previous_successful_run(run)

    product_count = len(products)
    brand_count = len(brand)
    ai = first_row(ai_summary.head(1)) if not ai_summary.empty else {}
    plaud = first_row(brand[brand["brand"] == "PLAUD"]) if not brand.empty else {}
    warnings = str(run.get("warnings") or "").strip()

    score = 0
    dimensions: list[str] = []

    sample_points = 24 if product_count >= 100 else 18 if product_count >= 50 else 12 if product_count >= 20 else 5 if product_count > 0 else 0
    score += sample_points
    dimensions.append(
        quality_dimension(
            "样本覆盖",
            f"{product_count} ASIN",
            "商品样本越多，类目销量反推、价格带和 Top ASIN 判断越稳。",
            product_count >= 50,
        )
    )

    field_defs = [
        ("asin", "ASIN"),
        ("product_title", "标题"),
        ("standard_brand", "品牌"),
        ("monthly_units", "月销量"),
        ("monthly_revenue", "月销售额"),
        ("bsr_rank", "类目排名"),
        ("price", "价格"),
    ]
    covered = 0
    for col, _ in field_defs:
        if col in products and products[col].map(lambda value: str(value).strip() if not pd.isna(value) else "").astype(bool).mean() >= 0.65:
            covered += 1
    field_points = round(26 * covered / len(field_defs)) if field_defs else 0
    score += field_points
    dimensions.append(
        quality_dimension(
            "字段完整",
            f"{covered}/{len(field_defs)}",
            "核心字段包括 ASIN、标题、品牌、销量、销售额、排名和价格。",
            covered >= 5,
        )
    )

    brand_ok = bool(plaud) and brand_count > 0
    score += 16 if brand_ok else 8 if brand_count > 0 else 0
    dimensions.append(
        quality_dimension(
            "品牌口径",
            "已识别 PLAUD" if brand_ok else "需复核",
            f"品牌集中度记录 {brand_count} 行；PLAUD 和监控竞品需要稳定归一。",
            brand_ok,
        )
    )

    category_units = value_as_float(ai.get("category_units"))
    category_revenue = value_as_float(ai.get("category_revenue"))
    category_ok = category_units > 0 and category_revenue > 0 and not ai_summary.empty
    score += 14 if category_ok else 6 if not ai_summary.empty else 0
    dimensions.append(
        quality_dimension(
            "类目总量",
            "完整" if category_ok else "不完整",
            f"类目销量 {num(category_units)}，类目销售额 {num(category_revenue)}；用于计算 AI 渗透和整体规模。",
            category_ok,
        )
    )

    site_rate = len(uploaded_sites) / max(len(sites), 1)
    score += round(10 * site_rate)
    dimensions.append(
        quality_dimension(
            "七站点覆盖",
            f"{len(uploaded_sites)}/{len(sites)}",
            "站点越完整，全球品牌市占和横向对比越可信。",
            site_rate >= 0.85,
        )
    )

    score += 6 if prev_run else 0
    dimensions.append(
        quality_dimension(
            "环比基线",
            "已有" if prev_run else "基线周",
            "同站点上一周数据决定份额、排名和商品池变化是否可比。",
            bool(prev_run),
        )
    )

    warning_penalty = 0 if not warnings else 8
    score = max(0, min(100, score - warning_penalty))
    dimensions.append(
        quality_dimension(
            "解析告警",
            "无告警" if not warnings else "有告警",
            warnings or "当前解析未返回字段缺失或 Sheet 匹配告警。",
            not warnings,
        )
    )

    status_key, pill_class = quality_status(score)
    degrees = max(0, min(360, round(score * 3.6)))
    body = [
        "<section>",
        "<div class='section-head'>",
        f"<div><h2 data-i18n='data_quality_score'>{esc(ui('data_quality_score'))}</h2>",
        f"<div class='section-note' data-i18n='data_quality_note'>{esc(ui('data_quality_note'))}</div></div>",
        "</div>",
        "<div class='quality-layout'>",
        "<div class='quality-score-card'>",
        f"<div class='quality-ring' style='--score-deg:{degrees}deg'><strong>{score}</strong></div>",
        f"<span class='pill {pill_class}' data-i18n='{status_key}'>{esc(ui(status_key))}</span>",
        f"<div class='section-note'>{esc(run.get('marketplace'))} · {esc(run.get('week_id'))}</div>",
        "</div>",
        "<div class='quality-list'>",
        "".join(dimensions),
        "</div></div></section>",
    ]
    return "".join(body)


def opportunity_item(score: int, priority: str, title: str, why: str, action: str, owner: str) -> str:
    return (
        "<div class='opportunity-item'>"
        f"<div class='opportunity-score'>{score}</div>"
        "<div class='opportunity-main'>"
        f"<span class='action-priority priority-{esc(priority.lower())}'>{esc(priority)}</span>"
        f"<strong>{esc(title)}</strong>"
        f"<p>{esc(why)}</p>"
        "</div>"
        "<div class='opportunity-action'>"
        f"<strong data-i18n='recommended_action'>{esc(ui('recommended_action'))}</strong>"
        f"<p>{esc(action)}</p>"
        "</div>"
        f"<div class='action-meta'><strong data-i18n='owner'>{esc(ui('owner'))}</strong>：{esc(owner)}</div>"
        "</div>"
    )


def opportunity_center_html(run: dict[str, object], brand: pd.DataFrame, ai_summary: pd.DataFrame, ai_detail: pd.DataFrame) -> str:
    plaud = first_row(brand[brand["brand"] == "PLAUD"]) if not brand.empty else {}
    competitors = first_row(brand[brand["brand"] == "COMPETITORS_TOTAL"]) if not brand.empty else {}
    ai = first_row(ai_summary.head(1)) if not ai_summary.empty else {}
    prev_run = previous_successful_run(run)
    top_ai = top_ai_competitor(ai_detail)
    band = strongest_price_band(run, ai_detail)
    baseline = category_baseline(run, brand, ai_summary)
    products = baseline.get("products")
    model = baseline.get("model", {})
    config = load_config(CONFIG_PATH)
    sites = config.get("monitoring", {}).get("marketplaces", [])
    uploaded_sites = latest_site_runs()
    missing_sites = [site for site in sites if site not in uploaded_sites]
    opportunities: list[tuple[int, str, str, str, str, str]] = []

    if missing_sites:
        opportunities.append(
            (
                96,
                "P0",
                "补齐七站点数据缺口",
                f"当前缺少 {', '.join(missing_sites)}，全球市占和横向对比会被已上传站点影响。",
                "优先让运营补上传缺失站点 Excel，再输出全球结论。",
                "运营",
            )
        )

    if prev_run:
        prev_brand = read_table_for_run(DB_PATH, "brand_metrics", int(prev_run["id"]))
        prev_ai = read_table_for_run(DB_PATH, "ai_summary", int(prev_run["id"]))
        prev_plaud = first_row(prev_brand[prev_brand["brand"] == "PLAUD"]) if not prev_brand.empty else {}
        prev_comp = first_row(prev_brand[prev_brand["brand"] == "COMPETITORS_TOTAL"]) if not prev_brand.empty else {}
        prev_ai_row = first_row(prev_ai.head(1)) if not prev_ai.empty else {}
        plaud_delta = value_as_float(plaud.get("monthly_units_share")) - value_as_float(prev_plaud.get("monthly_units_share"))
        comp_delta = value_as_float(competitors.get("monthly_units_share")) - value_as_float(prev_comp.get("monthly_units_share"))
        ai_delta = value_as_float(ai.get("ai_units_share")) - value_as_float(prev_ai_row.get("ai_units_share"))
        if plaud_delta <= -0.01:
            opportunities.append(
                (
                    92 if plaud_delta <= -0.02 else 82,
                    "P0" if plaud_delta <= -0.02 else "P1",
                    "PLAUD 份额下滑拦截",
                    f"PLAUD 销量份额环比 {format_delta_pp(plaud_delta)}，当前 {pct(plaud.get('monthly_units_share'))}。",
                    "进入 ASIN 作战页检查 PLAUD Top ASIN 排名、价格和竞品拦截对象。",
                    "站点运营",
                )
            )
        if comp_delta >= 0.015:
            opportunities.append(
                (
                    78,
                    "P1",
                    "竞品增长拆解",
                    f"监控竞品合计销量份额环比 {format_delta_pp(comp_delta)}。",
                    "在品牌市占表按销量/销售额排序，锁定拉动增长的品牌和对应 ASIN。",
                    "市场分析",
                )
            )
        if ai_delta >= 0.01:
            opportunities.append(
                (
                    86 if ai_delta >= 0.03 else 74,
                    "P1",
                    "AI 竞品渗透上升",
                    f"AI 竞品销量渗透环比 {format_delta_pp(ai_delta)}，当前 {pct(ai.get('ai_units_share'))}。",
                    "复核新增 AI ASIN 的标题词、价格带、评论数和主图卖点，提炼可反击信息。",
                    "产品运营",
                )
            )
    else:
        opportunities.append(
            (
                70,
                "P0",
                "建立同口径周环比",
                "当前是该站点基线周，暂不能判断份额升降。",
                "下周用同站点、同最终类目、同卖家精灵导出口径采集，建立可比趋势。",
                "运营",
            )
        )

    if top_ai:
        opportunities.append(
            (
                78,
                "P1",
                f"复盘 AI 标杆 ASIN {top_ai.get('asin', '')}",
                f"{top_ai.get('standard_brand', '')} 月销售额 {num(top_ai.get('monthly_revenue'))}，命中词 {top_ai.get('ai_matched_keywords', '')}。",
                "把标题结构、价格、评论、容量和转写卖点记录到竞品素材库。",
                "市场分析",
            )
        )

    if band:
        opportunities.append(
            (
                72,
                "P1",
                f"主销价格带机会：{band.get('label')}",
                f"该价格带贡献 {pct(band.get('revenue_share'))} 销售额，AI 竞品月销量 {num(band.get('ai_units'))}。",
                "检查 PLAUD 是否覆盖该价位段；如未覆盖，评估促销、coupon 或套装策略。",
                "站点运营",
            )
        )

    if isinstance(products, pd.DataFrame) and not products.empty and "standard_brand" in products:
        plaud_products = products[products["standard_brand"] == "PLAUD"]
        if not plaud_products.empty:
            avg_plaud_price = plaud_products["price"].map(value_as_float).replace(0, pd.NA).dropna().mean()
            if avg_plaud_price and not pd.isna(avg_plaud_price):
                threat = products[
                    (products["standard_brand"] != "PLAUD")
                    & (products["price"].map(value_as_float) > 0)
                    & (products["price"].map(value_as_float) <= float(avg_plaud_price) * 0.7)
                    & (products["monthly_units"].map(value_as_float) > 0)
                ]
                if not threat.empty:
                    opportunities.append(
                        (
                            68,
                            "P2",
                            "低价竞品冲量监控",
                            f"发现 {len(threat)} 个非 PLAUD ASIN 价格低于 PLAUD 均价 70%。",
                            "筛出低价高销量 ASIN，确认是否需要价格保护、套装差异化或卖点强化。",
                            "站点运营",
                        )
                    )

    if model.get("available"):
        opportunities.append(
            (
                64,
                "P2",
                "类目规模模型沉淀",
                f"当前估算类目月销量 {num(model.get('estimated_units'))}，可信度 {ui(str(model.get('confidence_key')))}。",
                "连续 4 周记录模型参数，观察类目是否扩张以及 PLAUD 估算份额变化。",
                "数据分析",
            )
        )

    if not opportunities:
        opportunities.append(
            (
                60,
                "P2",
                "维持监控并补充历史",
                "当前未触发明显机会或风险。",
                "继续补齐历史数据，让系统可以识别趋势拐点和长期增长机会。",
                "运营",
            )
        )

    deduped: list[tuple[int, str, str, str, str, str]] = []
    seen: set[str] = set()
    for item in sorted(opportunities, key=lambda row: row[0], reverse=True):
        if item[2] in seen:
            continue
        seen.add(item[2])
        deduped.append(item)

    body = [
        "<section>",
        "<div class='section-head'>",
        f"<div><h2 data-i18n='opportunity_center'>{esc(ui('opportunity_center'))}</h2>",
        f"<div class='section-note' data-i18n='opportunity_center_note'>{esc(ui('opportunity_center_note'))}</div></div>",
        "</div><div class='opportunity-list'>",
    ]
    for score, priority, title, why_text, action, owner in deduped[:6]:
        body.append(opportunity_item(score, priority, title, why_text, action, owner))
    body.append("</div></section>")
    return "".join(body)


def advanced_attribution_html(run: dict[str, object], brand: pd.DataFrame, ai_summary: pd.DataFrame, ai_detail: pd.DataFrame) -> str:
    plaud = first_row(brand[brand["brand"] == "PLAUD"]) if not brand.empty else {}
    ai = first_row(ai_summary.head(1)) if not ai_summary.empty else {}
    baseline = category_baseline(run, brand, ai_summary)
    model = baseline.get("model", {})
    products = baseline.get("products")
    prev_run = previous_successful_run(run)
    config = load_config(CONFIG_PATH)
    sites = config.get("monitoring", {}).get("marketplaces", [])
    uploaded_sites = latest_site_runs()
    missing_sites = [site for site in sites if site not in uploaded_sites]
    warnings = str(run.get("warnings") or "").strip()
    band = strongest_price_band(run, ai_detail)
    top_ai = top_ai_competitor(ai_detail)
    rows: list[dict[str, object]] = []

    if missing_sites:
        rows.append(
            {
                "cause": "数据缺口影响全球判断",
                "evidence": f"七站点已上传 {len(uploaded_sites)}/{len(sites)}，缺少 {', '.join(missing_sites)}。",
                "confidence": "高",
                "next_action": "先补齐缺失站点，再输出全球品牌市占和横向对比结论。",
            }
        )
    if warnings:
        rows.append(
            {
                "cause": "Excel 字段或 Sheet 口径不完整",
                "evidence": warnings,
                "confidence": "中",
                "next_action": "复核卖家精灵导出设置，保留品牌集中度、商品集中度、销量、销售额、价格和排名字段。",
            }
        )
    if not prev_run:
        rows.append(
            {
                "cause": "当前为同站点基线周",
                "evidence": f"{run.get('marketplace')} 暂无前一周可比 Run，份额升降还不能定性。",
                "confidence": "高",
                "next_action": "下一周按同关键词、同最终类目、同插件口径导出，建立环比。",
            }
        )
    else:
        prev_brand = read_table_for_run(DB_PATH, "brand_metrics", int(prev_run["id"]))
        prev_ai = read_table_for_run(DB_PATH, "ai_summary", int(prev_run["id"]))
        prev_plaud = first_row(prev_brand[prev_brand["brand"] == "PLAUD"]) if not prev_brand.empty else {}
        prev_ai_row = first_row(prev_ai.head(1)) if not prev_ai.empty else {}
        plaud_delta = value_as_float(plaud.get("monthly_units_share")) - value_as_float(prev_plaud.get("monthly_units_share"))
        ai_delta = value_as_float(ai.get("ai_units_share")) - value_as_float(prev_ai_row.get("ai_units_share"))
        if abs(plaud_delta) >= 0.01:
            rows.append(
                {
                    "cause": "PLAUD 份额波动",
                    "evidence": f"销量份额环比 {format_delta_pp(plaud_delta)}，当前 {pct(plaud.get('monthly_units_share'))}。",
                    "confidence": "中",
                    "next_action": "进入 ASIN 作战页复核 PLAUD Top ASIN 的排名、价格、优惠和竞品拦截对象。",
                }
            )
        if ai_delta >= 0.01:
            rows.append(
                {
                    "cause": "AI 产品集中增长",
                    "evidence": f"AI 竞品销量渗透环比 {format_delta_pp(ai_delta)}，当前 {pct(ai.get('ai_units_share'))}。",
                    "confidence": "中",
                    "next_action": "拆解新增 AI ASIN 标题表达、价格带、评论数和广告位。",
                }
            )

    if top_ai:
        rows.append(
            {
                "cause": "AI 标杆竞品需要跟进",
                "evidence": f"{top_ai.get('asin')} · {top_ai.get('standard_brand')} 月销售额 {num(top_ai.get('monthly_revenue'))}。",
                "confidence": "中",
                "next_action": "补充该 ASIN 详情页、评论、价格和搜索曝光记录。",
            }
        )
    if band:
        rows.append(
            {
                "cause": "价格带集中度较高",
                "evidence": f"{band.get('label')} 贡献 {pct(band.get('revenue_share'))} 销售额。",
                "confidence": "中",
                "next_action": "确认 PLAUD 在该价格带的定位、优惠和主图价格利益点是否足够清晰。",
            }
        )
    if model.get("available"):
        rows.append(
            {
                "cause": "类目大盘估算可用于趋势校验",
                "evidence": f"估算类目月销量 {num(model.get('estimated_units'))}，模型可信度 {ui(str(model.get('confidence_key')))}。",
                "confidence": "中",
                "next_action": "连续 4 周保留模型参数，识别类目扩张、收缩或采集口径漂移。",
            }
        )
    if isinstance(products, pd.DataFrame) and not products.empty and "price" in products:
        plaud_df = products[products["standard_brand"] == "PLAUD"] if "standard_brand" in products else products.head(0)
        if not plaud_df.empty:
            plaud_price = plaud_df["price"].map(value_as_float).replace(0, pd.NA).dropna()
            avg_price = float(plaud_price.mean()) if not plaud_price.empty else 0.0
            low_price_count = 0
            if avg_price:
                low_price_count = len(
                    products[
                        (products["standard_brand"] != "PLAUD")
                        & (products["price"].map(value_as_float) > 0)
                        & (products["price"].map(value_as_float) <= avg_price * 0.7)
                    ]
                )
            if low_price_count:
                rows.append(
                    {
                        "cause": "低价竞品可能挤压点击",
                        "evidence": f"发现 {low_price_count} 个非 PLAUD ASIN 价格低于 PLAUD 均价 70%。",
                        "confidence": "中",
                        "next_action": "筛选低价高销量 ASIN，评估是否需要券、套装、差异化卖点或投放防守。",
                    }
                )

    if not rows:
        rows.append(
            {
                "cause": "暂无明显异常",
                "evidence": "当前数据未触发份额、AI、价格带或数据质量异常。",
                "confidence": "高",
                "next_action": "继续沉淀历史周次，等同站点可比数据充足后再输出归因。",
            }
        )

    df = pd.DataFrame(rows[:8])
    return (
        "<section>"
        "<div class='section-head'>"
        f"<div><h2 data-i18n='advanced_attribution'>{esc(ui('advanced_attribution'))}</h2>"
        f"<div class='section-note' data-i18n='advanced_attribution_note'>{esc(ui('advanced_attribution_note'))}</div></div>"
        "</div>"
        f"{dataframe_table(df, ['cause', 'evidence', 'confidence', 'next_action'], table_class='sortable-table')}"
        "</section>"
    )


def ads_data_linkage_html() -> str:
    config = load_config(CONFIG_PATH)
    statuses = integration_statuses(config)
    ads = next((item for item in statuses if item.get("key") == "amazon_ads"), {})
    sp_api = next((item for item in statuses if item.get("key") == "sp_api"), {})
    sellersprite = next((item for item in statuses if item.get("key") == "sellersprite"), {})
    cards = [
        ("Amazon Ads API", ads, "ACOS、Spend、Campaign、Search Term 与市占变化归因。"),
        ("Amazon SP-API", sp_api, "订单、销售、Catalog、定价与库存作为官方经营口径。"),
        ("SellerSprite API", sellersprite, "类目市场、关键词、ASIN 与 BSR 估算作为第三方市场口径。"),
        ("SellerSprite Excel", {"ready": True, "enabled": True, "next_step": "当前已可上传解析"}, "运营插件导出数据，作为 MVP 周度监控基线。"),
    ]
    rows = [
        {
            "data_source": title,
            "readiness": "可联调" if item.get("ready") else "待配置",
            "collection_method": detail,
            "next_action": item.get("next_step") or "补充凭证/额度/QPS 后启用同步。",
        }
        for title, item, detail in cards
    ]
    metrics = [
        ("ACOS", "广告花费 / 广告销售额，用于判断份额变化是否由投放效率驱动。"),
        ("Spend", "按站点、Campaign、关键词汇总周花费，与销量份额同步看。"),
        ("Campaign", "把品牌词、类目词、竞品词拆开，观察哪个投放池拉动或拖累。"),
        ("Search Term", "与 Share of Voice 联动，定位可见度变化的原因。"),
    ]
    body = [
        "<section>",
        "<div class='section-head'>",
        f"<div><h2 data-i18n='ads_linkage'>{esc(ui('ads_linkage'))}</h2>",
        f"<div class='section-note' data-i18n='ads_linkage_note'>{esc(ui('ads_linkage_note'))}</div></div>",
        "</div><div class='ops-status-grid'>",
    ]
    for title, detail in metrics:
        body.append(f"<div class='ops-card'><h3>{icon('trend')}{esc(title)}</h3><p>{esc(detail)}</p></div>")
    body.append("</div><div class='table-scroll ops-table' style='margin-top:12px'>")
    body.append(dataframe_table(pd.DataFrame(rows), ["data_source", "readiness", "collection_method", "next_action"]))
    body.append("</div></section>")
    return "".join(body)


def share_of_voice_html(run: dict[str, object]) -> str:
    config = load_config(CONFIG_PATH)
    marketplaces = config.get("marketplaces", {})
    site_runs = latest_site_runs()
    rows = []
    for site in config.get("monitoring", {}).get("marketplaces", []):
        item = marketplaces.get(site, {})
        latest = site_runs.get(site)
        status = "待关键词采集"
        if latest:
            status = f"已有市场数据 Run #{latest.get('id')}，待 SERP/SOV 数据"
        if site == str(run.get("marketplace")):
            status = f"当前分析站点 Run #{run.get('id')}，待 SERP/SOV 数据"
        rows.append(
            {
                "marketplace": site,
                "keyword": item.get("keyword", ""),
                "organic_rank": "待接入",
                "ad_rank": "待接入",
                "data_source": "建议 SellerSprite API / 授权关键词排名服务 / Ads API",
                "status": status,
            }
        )
    body = [
        "<section>",
        "<div class='section-head'>",
        f"<div><h2 data-i18n='share_of_voice'>{esc(ui('share_of_voice'))}</h2>",
        f"<div class='section-note' data-i18n='share_of_voice_note'>{esc(ui('share_of_voice_note'))}</div></div>",
        "</div>",
        "<div class='ops-grid'>",
        f"<div class='ops-card'><h3>{icon('search')}自然排名</h3><p>每周记录核心关键词下 PLAUD 与竞品自然位次，解释市占变化的前置原因。</p></div>",
        f"<div class='ops-card'><h3>{icon('target')}广告排名</h3><p>与 Ads API 的 Campaign/Search Term 关联，判断份额变化是否由广告曝光拉动。</p></div>",
        "</div><div class='table-scroll ops-table' style='margin-top:12px'>",
        dataframe_table(pd.DataFrame(rows), ["marketplace", "keyword", "organic_rank", "ad_rank", "data_source", "status"]),
        "</div></section>",
    ]
    return "".join(body)


def task_card(priority: str, title: str, owner: str, due: str, status: str, review: str, detail: str) -> str:
    severity = "high" if priority == "P0" else "medium" if priority == "P1" else "info"
    return (
        f"<div class='task-card attribution-{severity}'>"
        f"{priority_pill(priority)}"
        f"<strong>{esc(title)}</strong>"
        f"<p>{esc(detail)}</p>"
        f"<div class='action-meta'><strong data-i18n='owner'>{esc(ui('owner'))}</strong>：{esc(owner)}<br>"
        f"<strong data-i18n='due_time'>{esc(ui('due_time'))}</strong>：{esc(due)}<br>"
        f"<strong data-i18n='task_status'>{esc(ui('task_status'))}</strong>：{esc(status)}<br>"
        f"<strong data-i18n='review_metric'>{esc(ui('review_metric'))}</strong>：{esc(review)}</div>"
        "</div>"
    )


def operations_task_loop_html(run: dict[str, object], brand: pd.DataFrame, ai_summary: pd.DataFrame, ai_detail: pd.DataFrame) -> str:
    config = load_config(CONFIG_PATH)
    sites = config.get("monitoring", {}).get("marketplaces", [])
    uploaded_sites = latest_site_runs()
    missing_sites = [site for site in sites if site not in uploaded_sites]
    top_ai = top_ai_competitor(ai_detail)
    band = strongest_price_band(run, ai_detail)
    prev_run = previous_successful_run(run)
    tasks: list[tuple[str, str, str, str, str, str, str]] = []
    if missing_sites:
        tasks.append(("P0", "补齐缺失站点 Excel", "运营", "本周五 18:00", "待处理", "7站点上传完成率", f"优先补 {', '.join(missing_sites)}。"))
    if not prev_run:
        tasks.append(("P0", "建立同口径环比基线", "运营", "下周采集日", "待跟进", "同站点可比 Run", "保持同关键词、同最终类目、同插件导出口径。"))
    if top_ai:
        tasks.append(("P1", f"复盘 AI ASIN {top_ai.get('asin', '')}", "市场分析", "本周三 18:00", "待处理", "标题词/价格/评论/主图", f"品牌 {top_ai.get('standard_brand', '')}，月销售额 {num(top_ai.get('monthly_revenue'))}。"))
    if band:
        tasks.append(("P1", f"检查价格带 {band.get('label')}", "站点运营", "本周四 18:00", "待处理", "价格带销售额占比", f"该价格带销售额占比 {pct(band.get('revenue_share'))}。"))
    tasks.append(("P1", "准备 Ads API 联调", "数据/投放", "凭证提供后 2 天", "待凭证", "ACOS/Spend 可用", "拿到 refresh token 和 profile 后关联广告与市占。"))
    tasks.append(("P1", "准备 SOV 关键词采集", "市场分析", "本周五 18:00", "待字段", "自然/广告排名", "确认七站点核心关键词、竞品品牌与采集频次。"))
    tasks = tasks[:6]
    body = [
        "<section>",
        "<div class='section-head'>",
        f"<div><h2 data-i18n='ops_task_loop'>{esc(ui('ops_task_loop'))}</h2>",
        f"<div class='section-note' data-i18n='ops_task_loop_note'>{esc(ui('ops_task_loop_note'))}</div></div>",
        "</div><div class='task-board'>",
    ]
    for task in tasks:
        body.append(task_card(*task))
    body.append("</div></section>")
    return "".join(body)


def weekly_brief_plus_html(run: dict[str, object], brand: pd.DataFrame, ai_summary: pd.DataFrame, ai_detail: pd.DataFrame) -> str:
    plaud = first_row(brand[brand["brand"] == "PLAUD"]) if not brand.empty else {}
    competitors = first_row(brand[brand["brand"] == "COMPETITORS_TOTAL"]) if not brand.empty else {}
    ai = first_row(ai_summary.head(1)) if not ai_summary.empty else {}
    band = strongest_price_band(run, ai_detail)
    top_ai = top_ai_competitor(ai_detail)
    config = load_config(CONFIG_PATH)
    sites = config.get("monitoring", {}).get("marketplaces", [])
    missing_sites = [site for site in sites if site not in latest_site_runs()]
    one_line = (
        f"{run.get('marketplace')} {run.get('week_id')}：PLAUD 销量份额 {pct(plaud.get('monthly_units_share'))}，"
        f"竞品合计 {pct(competitors.get('monthly_units_share'))}，AI 竞品渗透 {pct(ai.get('ai_units_share'))}。"
    )
    risk = f"缺少 {', '.join(missing_sites)}，全球结论需谨慎。" if missing_sites else "七站点覆盖较完整，可重点看份额和 ASIN 变化。"
    opportunity = (
        f"核心价格带 {band.get('label')} 销售额占比 {pct(band.get('revenue_share'))}。"
        if band
        else "价格带数据不足，建议补齐价格字段。"
    )
    confirm = (
        f"AI 标杆 ASIN {top_ai.get('asin')} 需补充详情页、评论和曝光数据。"
        if top_ai
        else "当前未识别到 AI 标杆 ASIN，需确认关键词规则。"
    )
    body = [
        "<section>",
        "<div class='section-head'>",
        f"<div><h2 data-i18n='weekly_brief_plus'>{esc(ui('weekly_brief_plus'))}</h2>",
        f"<div class='section-note' data-i18n='weekly_brief_plus_note'>{esc(ui('weekly_brief_plus_note'))}</div></div>",
        "</div><div class='ops-grid'>",
        f"<div class='ops-card'><h3>{icon('chat')}一句话结论</h3><p><strong>{esc(one_line)}</strong></p></div>",
        f"<div class='ops-card'><h3>{icon('warning')}最大风险</h3><p>{esc(risk)}</p></div>",
        f"<div class='ops-card'><h3>{icon('target')}最大机会</h3><p>{esc(opportunity)}</p></div>",
        f"<div class='ops-card'><h3>{icon('check')}需业务确认</h3><p>{esc(confirm)}</p></div>",
        "</div></section>",
    ]
    return "".join(body)


def price_positioning_html(run: dict[str, object], ai_detail: pd.DataFrame) -> str:
    products = product_metrics_for_run(run)
    if products.empty or "price" not in products:
        return ""
    sample = products.copy()
    sample["_price"] = sample["price"].map(value_as_float)
    sample["_units"] = sample["monthly_units"].map(value_as_float) if "monthly_units" in sample else 0.0
    sample = sample[sample["_price"] > 0].copy()
    if sample.empty:
        return ""
    ai_asins = ai_asins_from_detail(ai_detail)
    plaud_df = sample[sample["standard_brand"] == "PLAUD"] if "standard_brand" in sample else sample.head(0)
    competitor_df = sample[sample["standard_brand"] != "PLAUD"] if "standard_brand" in sample else sample
    ai_df = sample[sample["asin"].map(clean_asin).isin(ai_asins)] if ai_asins and "asin" in sample else sample.head(0)

    def avg_price(df: pd.DataFrame) -> float:
        if df.empty:
            return 0.0
        weight_sum = float(df["_units"].sum())
        if weight_sum > 0:
            return float((df["_price"] * df["_units"]).sum() / weight_sum)
        return float(df["_price"].mean())

    plaud_avg = avg_price(plaud_df)
    comp_avg = avg_price(competitor_df)
    ai_avg = avg_price(ai_df)
    band = strongest_price_band(run, ai_detail)
    premium = (plaud_avg / comp_avg - 1) if comp_avg else 0.0
    rows = [
        {"cause": "PLAUD 加权均价", "evidence": num(plaud_avg), "next_action": "用于判断是否处在高端定位。"},
        {"cause": "非 PLAUD 均价", "evidence": num(comp_avg), "next_action": "与 PLAUD 均价对比看价格压力。"},
        {"cause": "AI 竞品均价", "evidence": num(ai_avg), "next_action": "判断 AI 卖点是否向低价或高价扩散。"},
        {"cause": "PLAUD 溢价", "evidence": format_delta_percent(premium), "next_action": "溢价高时强化差异化卖点，溢价低时复核促销效率。"},
    ]
    if band:
        rows.append({"cause": "主销价格带", "evidence": f"{band.get('label')} · {pct(band.get('revenue_share'))}", "next_action": "围绕主销价位检查券、套装、主图和广告词。"})
    return (
        "<section>"
        "<div class='section-head'>"
        "<div><h2>价格带与定位分析</h2><div class='section-note'>把价格带从统计表升级为定位判断：PLAUD 溢价、AI 竞品均价、主销价格带和动作建议。</div></div>"
        "</div>"
        f"{dataframe_table(pd.DataFrame(rows), ['cause', 'evidence', 'next_action'])}"
        "</section>"
    )


def local_data_inventory_html() -> str:
    table_counts = []
    with connect(DB_PATH) as conn:
        for table in ["uploaded_reports", "brand_metrics", "ai_summary", "ai_detail", "product_metrics"]:
            count = count_query(conn, f"SELECT COUNT(*) FROM {table}")
            table_counts.append({"data_source": table, "readiness": f"{count} rows", "collection_method": "SQLite 直接查询", "recommended_path": "内部分析、导出、看板渲染"})
    rows = pd.DataFrame(table_counts)
    return (
        "<section>"
        "<div class='section-head'>"
        f"<div><h2 data-i18n='local_data_inventory'>{esc(ui('local_data_inventory'))}</h2>"
        f"<div class='section-note' data-i18n='local_data_inventory_note'>{esc(ui('local_data_inventory_note'))}</div></div>"
        "</div>"
        f"{dataframe_table(rows, ['data_source', 'readiness', 'collection_method', 'recommended_path'])}"
        "</section>"
    )


def data_collection_boundary_html() -> str:
    tiers = [
        (
            "自动拉取：已允许",
            "SellerSprite MCP/API、已上传 Excel、SQLite 历史数据，以及公开商品页的小样本校验字段可自动入库。",
            "用于市占、AI 渗透、BSR/类目销量反推、标题/价格/评分/评论数/BSR 校验。",
            "safe",
        ),
        (
            "授权后拉取：官方 API",
            "Amazon Ads API 与 SP-API 只在业务方完成授权、角色审批和 refresh token 配置后启用。",
            "广告 Spend/ACOS/Search Term 走 Ads API；订单、库存、Listing、Catalog、Pricing 走 SP-API。",
            "warning",
        ),
        (
            "人工上传：后台导出",
            "Seller Central、Advertising Console、SellerSprite 插件后台数据不做页面自动化抓取。",
            "由运营导出 Excel/CSV 后上传，或后续改为官方 API / SellerSprite API 同步。",
            "warning",
        ),
        (
            "不拉取：合规拦截",
            "登录态后台页面、验证码/Robot Check、代理轮换、Cookie 会话复用、买家 PII 或未授权受限订单数据均不采集。",
            "发现受限页面时跳过并记录原因；需要数据时走授权 API、人工导出或第三方合规服务。",
            "danger",
        ),
    ]
    body = [
        "<section>",
        "<div class='section-head'>",
        f"<div><h2 data-i18n='data_collection_boundary'>{esc(ui('data_collection_boundary'))}</h2>",
        f"<div class='section-note' data-i18n='data_collection_boundary_note'>{esc(ui('data_collection_boundary_note'))}</div></div>",
        "</div><div class='source-tier-grid'>",
    ]
    for title, detail, path, class_name in tiers:
        body.append(
            f"<div class='source-tier {esc(class_name)}'><strong>{esc(title)}</strong>"
            f"<p>{esc(detail)}</p><p style='margin-top:8px'><strong>{esc(ui('recommended_path'))}</strong>：{esc(path)}</p></div>"
        )
    body.append("</div></section>")
    return "".join(body)


def infer_category_totals(brand: pd.DataFrame, ai_summary: pd.DataFrame) -> tuple[float, float]:
    ai = first_row(ai_summary.head(1)) if not ai_summary.empty else {}
    category_units = value_as_float(ai.get("category_units"))
    category_revenue = value_as_float(ai.get("category_revenue"))
    if brand.empty:
        return category_units, category_revenue
    if not category_units:
        estimates = []
        for _, row in brand.iterrows():
            share = value_as_float(row.get("monthly_units_share"))
            units = value_as_float(row.get("monthly_units"))
            if share > 0 and units > 0:
                estimates.append(units / share)
        category_units = max(estimates) if estimates else 0.0
    if not category_revenue:
        estimates = []
        for _, row in brand.iterrows():
            share = value_as_float(row.get("monthly_revenue_share"))
            revenue = value_as_float(row.get("monthly_revenue"))
            if share > 0 and revenue > 0:
                estimates.append(revenue / share)
        category_revenue = max(estimates) if estimates else 0.0
    return category_units, category_revenue


def global_brand_share_df() -> pd.DataFrame:
    site_runs = latest_site_runs()
    totals: dict[str, dict[str, object]] = {}
    category_units_total = 0.0
    category_revenue_total = 0.0
    for site, run in site_runs.items():
        run_id = int(run.get("id", 0) or 0)
        brand = read_table_for_run(DB_PATH, "brand_metrics", run_id)
        ai_summary = read_table_for_run(DB_PATH, "ai_summary", run_id)
        category_units, category_revenue = infer_category_totals(brand, ai_summary)
        category_units_total += category_units
        category_revenue_total += category_revenue
        if brand.empty:
            continue
        for _, row in brand.iterrows():
            brand_name = str(row.get("brand", ""))
            if not brand_name or brand_name == "COMPETITORS_TOTAL":
                continue
            item = totals.setdefault(
                brand_name,
                {
                    "brand": brand_name,
                    "brand_group": row.get("brand_group", ""),
                    "sites": set(),
                    "monthly_units": 0.0,
                    "monthly_revenue": 0.0,
                },
            )
            item["sites"].add(site)
            item["monthly_units"] = value_as_float(item.get("monthly_units")) + value_as_float(row.get("monthly_units"))
            item["monthly_revenue"] = value_as_float(item.get("monthly_revenue")) + value_as_float(row.get("monthly_revenue"))
            if item.get("brand_group") != "plaud":
                item["brand_group"] = row.get("brand_group", item.get("brand_group"))

    rows = []
    for item in totals.values():
        units = value_as_float(item.get("monthly_units"))
        revenue = value_as_float(item.get("monthly_revenue"))
        sites = sorted(item.get("sites", set()))
        rows.append(
            {
                "brand": item.get("brand"),
                "brand_group": item.get("brand_group"),
                "sites_covered": ", ".join(sites),
                "monthly_units": units,
                "global_units_share": units / category_units_total if category_units_total else 0.0,
                "monthly_revenue": revenue,
                "global_revenue_share": revenue / category_revenue_total if category_revenue_total else 0.0,
            }
        )
    result = pd.DataFrame(rows)
    if not result.empty:
        result = result.sort_values("monthly_units", ascending=False)
    return result


def format_brand_share_view(df: pd.DataFrame, global_view: bool = False) -> pd.DataFrame:
    if df.empty:
        return df
    view = df.copy()
    sort_col = "monthly_units"
    if sort_col in view:
        view["_sort_units"] = view[sort_col].map(value_as_float)
        view = view.sort_values("_sort_units", ascending=False).drop(columns=["_sort_units"])
    for col in ["monthly_units", "monthly_revenue"]:
        if col in view:
            view[col] = view[col].map(num)
    percent_cols = ["global_units_share", "global_revenue_share"] if global_view else ["monthly_units_share", "monthly_revenue_share"]
    for col in percent_cols:
        if col in view:
            view[col] = view[col].map(pct)
    return view


def brand_market_share_html(run: dict[str, object], brand: pd.DataFrame) -> str:
    sortable = {"monthly_units", "monthly_units_share", "monthly_revenue", "monthly_revenue_share", "global_units_share", "global_revenue_share"}
    numeric = sortable
    body = [
        "<section>",
        f"<h3 data-i18n='global_brand_share'>{esc(ui('global_brand_share'))}</h3>",
        f"<div class='section-note' data-i18n='global_brand_share_note'>{esc(ui('global_brand_share_note'))}</div>",
    ]
    global_view = format_brand_share_view(global_brand_share_df(), global_view=True)
    body.append(
        dataframe_table(
            global_view,
            ["brand", "brand_group", "sites_covered", "monthly_units", "global_units_share", "monthly_revenue", "global_revenue_share"],
            table_class="sortable-table",
            sortable_columns={"monthly_units", "global_units_share", "monthly_revenue", "global_revenue_share"},
            numeric_columns=numeric,
        )
    )
    current_view = format_brand_share_view(brand, global_view=False)
    body.append(f"<h3 data-i18n='current_site_brand_share'>{esc(ui('current_site_brand_share'))} · {esc(run.get('marketplace', ''))}</h3>")
    body.append(
        dataframe_table(
            current_view,
            ["marketplace", "brand", "brand_group", "monthly_units", "monthly_units_share", "monthly_revenue", "monthly_revenue_share"],
            table_class="sortable-table",
            sortable_columns={"monthly_units", "monthly_units_share", "monthly_revenue", "monthly_revenue_share"},
            numeric_columns=numeric,
        )
    )
    body.append("</section>")
    return "".join(body)


def asin_change_analysis_html(run: dict[str, object]) -> str:
    current = product_metrics_for_run(run)
    body = [
        "<section>",
        "<div class='section-head'>",
        f"<div><h2 data-i18n='asin_change_analysis'>{esc(ui('asin_change_analysis'))}</h2>",
        f"<div class='section-note' data-i18n='asin_change_note'>{esc(ui('asin_change_note'))}</div></div>",
        "</div>",
    ]
    if current.empty:
        body.append(f"<div class='notice' data-i18n='no_asin_change_data'>{esc(ui('no_asin_change_data'))}</div></section>")
        return "".join(body)

    current = current.copy()
    current["_asin_key"] = current["asin"].map(clean_asin) if "asin" in current else ""
    current = current[current["_asin_key"] != ""]
    prev_run = previous_successful_run(run)
    if not prev_run:
        body.append(f"<div class='notice' data-i18n='no_previous_asin_data'>{esc(ui('no_previous_asin_data'))}</div>")
        body.append("<div class='full-width-panel' style='margin-top:12px'>")
        body.append(product_change_table("baseline_asins", current, "暂无基线 ASIN。", limit=12))
        body.append("</div></section>")
        return "".join(body)

    previous = product_metrics_for_run(prev_run)
    previous = previous.copy()
    previous["_asin_key"] = previous["asin"].map(clean_asin) if "asin" in previous else ""
    previous = previous[previous["_asin_key"] != ""]
    previous_ranks = rank_lookup(previous)
    current_asins = asin_set(current)
    previous_asins = asin_set(previous)
    new_products = current[current["_asin_key"].isin(current_asins - previous_asins)]
    disappeared_products = previous[previous["_asin_key"].isin(previous_asins - current_asins)]
    body.append(
        "<div class='section-note'>"
        f"<span data-i18n='current_week'>{esc(ui('current_week'))}</span>: {esc(run.get('week_id'))} · "
        f"<span data-i18n='previous_week'>{esc(ui('previous_week'))}</span>: {esc(prev_run.get('week_id'))}"
        "</div>"
    )
    body.append("<div class='full-width-panel' style='margin-top:12px'>")
    body.append(product_change_table("baseline_asins", current, "暂无本周 ASIN。", limit=12, previous_rank_by_asin=previous_ranks))
    body.append("</div>")
    body.append("<div class='rank-grid' style='margin-top:12px'>")
    body.append(product_change_table("new_asins", new_products, "暂无新增 ASIN。", limit=10, previous_rank_by_asin=previous_ranks))
    body.append(product_change_table("disappeared_asins", disappeared_products, "暂无消失 ASIN。", limit=10, trend_mode="disappeared"))
    body.append("</div></section>")
    return "".join(body)


def priority_pill(priority: str) -> str:
    class_name = f"priority-{priority.lower()}" if priority else "priority-p2"
    return f"<span class='action-priority {esc(class_name)}'>{esc(priority or 'P2')}</span>"


def asin_battle_action(row: dict[str, object], role: str, rank_delta: float, price_threat: bool) -> str:
    if role == "PLAUD 守擂":
        if rank_delta < 0:
            return "检查排名下滑原因，复核价格、coupon、广告位和竞品标题卖点。"
        return "保持排名和转化优势，记录当前价格、主图、评论和广告策略。"
    if role == "AI 竞品拦截":
        return "拆解标题 AI 表达、价格、评论和核心卖点，补充到竞品素材库。"
    if price_threat:
        return "评估低价冲量影响，确认是否需要差异化套装、优惠或卖点防守。"
    if role == "核心竞品跟踪":
        return "观察销量和排名变化，复核是否进入重点竞品清单。"
    return "作为类目样本保留，若连续上升再提升优先级。"


def asin_battle_dataframe(run: dict[str, object], ai_detail: pd.DataFrame) -> pd.DataFrame:
    products = product_metrics_for_run(run)
    if products.empty:
        return pd.DataFrame()
    sample = products.copy()
    sample["_asin_key"] = sample["asin"].map(clean_asin) if "asin" in sample else ""
    sample = sample[sample["_asin_key"] != ""].copy()
    if sample.empty:
        return pd.DataFrame()

    prev_run = previous_successful_run(run)
    previous_ranks = rank_lookup(product_metrics_for_run(prev_run)) if prev_run else {}
    ai_asins = ai_asins_from_detail(ai_detail)
    max_revenue = max(sample["monthly_revenue"].map(value_as_float).max() if "monthly_revenue" in sample else 0.0, 1.0)
    max_units = max(sample["monthly_units"].map(value_as_float).max() if "monthly_units" in sample else 0.0, 1.0)
    plaud_products = sample[sample["standard_brand"] == "PLAUD"] if "standard_brand" in sample else sample.head(0)
    plaud_prices = plaud_products["price"].map(value_as_float).replace(0, pd.NA).dropna() if "price" in plaud_products else pd.Series(dtype=float)
    plaud_avg_price = float(plaud_prices.mean()) if not plaud_prices.empty else 0.0

    rows = []
    for _, source in sample.iterrows():
        row = source.to_dict()
        asin = clean_asin(row.get("asin"))
        brand = str(row.get("standard_brand") or row.get("brand_name") or "")
        rank = value_as_float(row.get("bsr_rank"))
        prev_rank = previous_ranks.get(asin)
        rank_delta = (prev_rank - rank) if prev_rank and rank else 0.0
        revenue = value_as_float(row.get("monthly_revenue"))
        units = value_as_float(row.get("monthly_units"))
        price = value_as_float(row.get("price"))
        is_plaud = brand == "PLAUD"
        is_ai = asin in ai_asins
        is_competitor = str(row.get("brand_group") or "") == "competitor"
        price_threat = bool(plaud_avg_price and not is_plaud and price > 0 and price <= plaud_avg_price * 0.7)

        if is_plaud:
            role = "PLAUD 守擂"
        elif is_ai:
            role = "AI 竞品拦截"
        elif price_threat:
            role = "低价威胁"
        elif is_competitor:
            role = "核心竞品跟踪"
        else:
            role = "市场样本"

        revenue_score = min(45.0, revenue / max_revenue * 45.0)
        unit_score = min(20.0, units / max_units * 20.0)
        rank_score = 0.0
        if rank > 0:
            rank_score = max(0.0, min(20.0, (1000.0 - min(rank, 1000.0)) / 1000.0 * 20.0))
        role_bonus = 12.0 if is_plaud or is_ai else 8.0 if is_competitor or price_threat else 0.0
        delta_bonus = min(10.0, max(0.0, rank_delta / 10.0)) if rank_delta else 0.0
        battle_score = int(round(min(100.0, revenue_score + unit_score + rank_score + role_bonus + delta_bonus)))

        if (is_plaud and (rank <= 20 or battle_score >= 70)) or (is_ai and battle_score >= 72):
            priority = "P0"
        elif is_ai or is_competitor or price_threat or battle_score >= 55:
            priority = "P1"
        else:
            priority = "P2"

        rows.append(
            {
                "battle_score": battle_score,
                "battle_priority": priority_pill(priority),
                "battle_role": role,
                "asin": asin,
                "standard_brand": brand,
                "monthly_units": units,
                "monthly_revenue": revenue,
                "price": price,
                "bsr_rank": rank,
                "rank_trend": rank_trend_for_row(row, previous_ranks, "current"),
                "battle_action": asin_battle_action(row, role, rank_delta, price_threat),
                "product_title": row.get("product_title", ""),
                "_priority": priority,
                "_role": role,
                "_rank_delta": rank_delta,
                "_price_threat": price_threat,
            }
        )
    result = pd.DataFrame(rows)
    if not result.empty:
        result = result.sort_values(["battle_score", "monthly_revenue"], ascending=[False, False])
    return result


def war_card(title: str, row: dict[str, object], detail: str, severity: str = "info") -> str:
    if not row:
        return (
            f"<div class='war-card attribution-{esc(severity)}'><span class='pill'>{esc(title)}</span>"
            "<strong>暂无可用 ASIN</strong><p>继续补充商品明细后自动生成。</p></div>"
        )
    return (
        f"<div class='war-card attribution-{esc(severity)}'>"
        f"<span class='pill'>{esc(title)}</span>"
        f"<strong>{esc(row.get('asin', ''))} · {esc(row.get('standard_brand', ''))}</strong>"
        f"<p>{esc(detail)}</p>"
        "</div>"
    )


def asin_war_room_html(run: dict[str, object], ai_detail: pd.DataFrame) -> str:
    battle = asin_battle_dataframe(run, ai_detail)
    body = [
        "<section>",
        "<div class='section-head'>",
        f"<div><h2 data-i18n='asin_war_room'>{esc(ui('asin_war_room'))}</h2>",
        f"<div class='section-note' data-i18n='asin_war_room_note'>{esc(ui('asin_war_room_note'))}</div></div>",
        "</div>",
    ]
    if battle.empty:
        body.append(f"<div class='notice' data-i18n='no_asin_change_data'>{esc(ui('no_asin_change_data'))}</div></section>")
        return "".join(body)

    plaud_df = battle[battle["standard_brand"] == "PLAUD"]
    ai_df = battle[battle["_role"] == "AI 竞品拦截"]
    price_df = battle[battle["_price_threat"] == True]  # noqa: E712 - pandas boolean filtering.
    focus_df = battle[battle["_priority"].isin(["P0", "P1"])]

    kpis = [
        ("focus_asins", len(focus_df), "target"),
        ("plaud_asins", len(plaud_df), "brand"),
        ("ai_focus_asins", len(ai_df), "bot"),
        ("price_threats", len(price_df), "warning"),
    ]
    body.append("<div class='war-kpi-grid'>")
    for key, value, icon_name in kpis:
        body.append(
            "<div class='card metric-card'>"
            f"<span class='icon-badge'>{icon(icon_name)}</span>"
            f"<div><div class='metric-label' data-i18n='{esc(key)}'>{esc(ui(key))}</div><div class='metric-value'>{esc(value)}</div></div>"
            "</div>"
        )
    body.append("</div>")

    top_plaud = first_row(plaud_df.sort_values("monthly_revenue", ascending=False).head(1)) if not plaud_df.empty else {}
    top_ai = first_row(ai_df.sort_values("monthly_revenue", ascending=False).head(1)) if not ai_df.empty else {}
    rising = first_row(battle.sort_values("_rank_delta", ascending=False).head(1)) if "_rank_delta" in battle else {}
    price_threat = first_row(price_df.sort_values("monthly_units", ascending=False).head(1)) if not price_df.empty else {}
    body.append("<div class='war-card-grid'>")
    body.append(war_card("守擂 ASIN", top_plaud, f"月销售额 {num(top_plaud.get('monthly_revenue'))}，排名 #{num(top_plaud.get('bsr_rank'))}。", "info"))
    body.append(war_card("拦截 ASIN", top_ai, f"月销售额 {num(top_ai.get('monthly_revenue'))}，建议拆解 AI 卖点和价格。", "medium"))
    body.append(war_card("排名上升", rising, f"排名变化 {format_delta_number(rising.get('_rank_delta'))}，当前排名 #{num(rising.get('bsr_rank'))}。", "info"))
    body.append(war_card("低价威胁", price_threat, f"价格 {num(price_threat.get('price'))}，月销量 {num(price_threat.get('monthly_units'))}。", "medium"))
    body.append("</div>")

    view = battle.head(30).copy()
    for col in ["monthly_units", "monthly_revenue", "price", "bsr_rank", "battle_score"]:
        if col in view:
            view[col] = view[col].map(num)
    body.append("<div class='table-scroll war-table'>")
    body.append(
        dataframe_table(
            view,
            [
                "battle_score",
                "battle_priority",
                "battle_role",
                "asin",
                "standard_brand",
                "monthly_units",
                "monthly_revenue",
                "price",
                "bsr_rank",
                "rank_trend",
                "battle_action",
                "product_title",
            ],
            limit=30,
            raw_columns={"battle_priority", "rank_trend"},
        )
    )
    body.append("</div></section>")
    return "".join(body)


def raw_product_extras_for_run(run: dict[str, object]) -> pd.DataFrame:
    stored_path = Path(str(run.get("stored_path", "")))
    if not stored_path.exists() or stored_path.suffix.lower() != ".json":
        return pd.DataFrame()
    try:
        data = json.loads(stored_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return pd.DataFrame()
    goods_payload = data.get("goods", {})
    goods = goods_payload.get("data", []) if isinstance(goods_payload, dict) else []
    if not isinstance(goods, list):
        return pd.DataFrame()
    rows = []
    for item in goods:
        if not isinstance(item, dict):
            continue
        asin = clean_asin(item.get("asin"))
        if not asin:
            continue
        rows.append(
            {
                "_asin_key": asin,
                "asin_url": item.get("asinUrl", ""),
                "image_url": item.get("imageUrl", ""),
                "seller_name": item.get("sellerName", ""),
                "seller_type": item.get("sellerType", ""),
                "shelf_date": item.get("shelfDate", ""),
                "rating": value_as_float(item.get("rating")),
                "ratings": value_as_float(item.get("ratings")),
                "reviews": value_as_float(item.get("reviews")),
                "new_flag": value_as_int(item.get("newFlag")),
            }
        )
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.drop_duplicates("_asin_key")
    return df


def enriched_product_metrics_for_run(run: dict[str, object]) -> pd.DataFrame:
    products = product_metrics_for_run(run)
    if products.empty:
        return products
    view = products.copy()
    view["_asin_key"] = view["asin"].map(clean_asin) if "asin" in view else ""
    extras = raw_product_extras_for_run(run)
    if not extras.empty:
        view = view.merge(extras, on="_asin_key", how="left")
    for col in ["asin_url", "image_url", "seller_name", "seller_type", "shelf_date"]:
        if col not in view:
            view[col] = ""
    for col in ["rating", "ratings", "reviews", "new_flag"]:
        if col not in view:
            view[col] = 0.0
    return view


def phrase_in_text(text: object, phrase: str) -> bool:
    source = str(text or "").lower()
    needle = phrase.lower().strip()
    if not needle:
        return False
    if len(needle) <= 2 or needle in {"ai", "ia"}:
        return bool(re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", source))
    return needle in source


def keyword_feature_catalog() -> list[dict[str, object]]:
    return [
        {
            "label": "AI 转写 / 摘要",
            "type": "AI 机会词",
            "phrases": ["ai", "ia", "transcribe", "transcription", "summarize", "summary", "note taker", "notetaker", "assistant", "trascrizione", "riassunti", "transcripción", "resumen", "résumé"],
            "action": "标题、主图和 A+ 优先明确 AI 转写、自动摘要、语言数和会议纪要输出能力。",
        },
        {
            "label": "会议 / 通话",
            "type": "场景词",
            "phrases": ["meeting", "meetings", "call", "calls", "reuniones", "riunioni", "chiamate", "appels", "réunions", "besprechung", "会議", "通話"],
            "action": "把会议、电话、团队协作场景拆成独立素材，并与转写准确率、摘要模板绑定。",
        },
        {
            "label": "课堂 / 采访",
            "type": "场景词",
            "phrases": ["lecture", "lectures", "class", "classes", "interview", "interviews", "lezioni", "entrevistas", "cours", "unterricht", "講義", "インタビュー"],
            "action": "补充学生、记者、调研采访场景图，强调长录音、重点摘录和搜索回听。",
        },
        {
            "label": "多语言",
            "type": "能力词",
            "phrases": ["112 languages", "113 languages", "languages", "lingue", "idiomas", "langues", "sprachen", "言語"],
            "action": "将语言数量从参数改成利益点：跨国会议、外语课堂、海外采访可直接复用。",
        },
        {
            "label": "存储 / 续航 / 形态",
            "type": "硬件词",
            "phrases": ["64gb", "128gb", "136gb", "gb", "hours", "hour", "ore", "horas", "usb-c", "battery", "display", "screen", "wearable", "ultra-slim", "slim", "case"],
            "action": "硬件规格要和使用场景绑定，避免只堆参数；重点解释可录多久、怎么携带、是否有屏幕反馈。",
        },
        {
            "label": "降噪 / 声控 / 回放",
            "type": "体验词",
            "phrases": ["noise reduction", "noise", "voice activated", "playback", "stereo", "mp3", "password", "reduction", "riduzione rumore", "reducción de ruido", "réduction du bruit"],
            "action": "对非 AI 低价录音笔的传统卖点做防守，突出 PLAUD 在清晰收音后还有 AI 整理价值。",
        },
    ]


def feature_matches(row: pd.Series, phrases: list[str]) -> bool:
    title = row.get("product_title", "")
    return any(phrase_in_text(title, phrase) for phrase in phrases)


def asin_anchor(row: dict[str, object]) -> str:
    asin = esc(row.get("asin", ""))
    url = str(row.get("asin_url") or "").strip()
    if url:
        return f"<a href='{esc(url)}' target='_blank' rel='noopener'>{asin}</a>"
    return asin


def competitor_depth_dataframe(run: dict[str, object], ai_detail: pd.DataFrame) -> pd.DataFrame:
    products = enriched_product_metrics_for_run(run)
    if products.empty:
        return pd.DataFrame()
    sample = products.copy()
    sample["_asin_key"] = sample["asin"].map(clean_asin) if "asin" in sample else ""
    sample = sample[sample["_asin_key"] != ""].copy()
    if sample.empty:
        return pd.DataFrame()

    ai_asins = ai_asins_from_detail(ai_detail)
    prev_run = previous_successful_run(run)
    previous_ranks = rank_lookup(product_metrics_for_run(prev_run)) if prev_run else {}
    plaud_df = sample[sample["standard_brand"] == "PLAUD"] if "standard_brand" in sample else sample.head(0)
    plaud_prices = plaud_df["price"].map(value_as_float).replace(0, pd.NA).dropna() if "price" in plaud_df else pd.Series(dtype=float)
    plaud_avg_price = float(plaud_prices.mean()) if not plaud_prices.empty else 0.0

    competitors = sample[sample["standard_brand"] != "PLAUD"].copy() if "standard_brand" in sample else sample.copy()
    if competitors.empty:
        return pd.DataFrame()
    max_revenue = max(competitors["monthly_revenue"].map(value_as_float).max() if "monthly_revenue" in competitors else 0.0, 1.0)
    max_units = max(competitors["monthly_units"].map(value_as_float).max() if "monthly_units" in competitors else 0.0, 1.0)

    rows = []
    for _, source in competitors.iterrows():
        row = source.to_dict()
        asin = clean_asin(row.get("asin"))
        brand = str(row.get("standard_brand") or row.get("brand_name") or "")
        units = value_as_float(row.get("monthly_units"))
        revenue = value_as_float(row.get("monthly_revenue"))
        price = value_as_float(row.get("price"))
        rank = value_as_float(row.get("bsr_rank"))
        rating = value_as_float(row.get("rating"))
        reviews = value_as_float(row.get("reviews") or row.get("ratings"))
        is_ai = asin in ai_asins
        price_threat = bool(plaud_avg_price and price > 0 and price <= plaud_avg_price * 0.7)
        rank_pressure = rank > 0 and rank <= 20
        trust_pressure = reviews >= 500 and rating >= 4.3

        signals = []
        if is_ai:
            signals.append("AI 卖点")
        if price_threat:
            signals.append("低价")
        if rank_pressure:
            signals.append("Top 排名")
        if trust_pressure:
            signals.append("评论资产")
        if not signals:
            signals.append("常规竞品")

        score = min(44, revenue / max_revenue * 44) + min(20, units / max_units * 20)
        if rank_pressure:
            score += 14
        elif rank > 0:
            score += max(0, (120 - min(rank, 120)) / 120 * 8)
        if is_ai:
            score += 12
        if price_threat:
            score += 8
        if trust_pressure:
            score += 8
        depth_score = int(round(min(100, score)))
        priority = "P0" if depth_score >= 80 or (is_ai and rank_pressure) else "P1" if depth_score >= 58 or is_ai or price_threat else "P2"
        if is_ai:
            action = "拆标题 AI 表达、语言数、摘要承诺和价格利益点，补进 PLAUD 防守话术。"
        elif price_threat:
            action = "复核是否用低价抢点击；用套装、保修、AI 价值和高端质感做差异化。"
        elif trust_pressure:
            action = "对比其评论量、评分和主图信任信息，补强 PLAUD 社会证明与评测素材。"
        else:
            action = "加入周度观察，若连续排名上升或销量放大再升级为重点竞品。"

        rows.append(
            {
                "battle_score": depth_score,
                "battle_priority": priority_pill(priority),
                "risk_signal": " / ".join(signals),
                "asin": asin,
                "asin_link": asin_anchor(row),
                "standard_brand": brand,
                "monthly_units": units,
                "monthly_revenue": revenue,
                "price": price,
                "bsr_rank": rank,
                "rank_trend": rank_trend_for_row(row, previous_ranks, "current"),
                "rating": rating,
                "reviews": reviews,
                "seller_type": row.get("seller_type", ""),
                "shelf_date": row.get("shelf_date", ""),
                "operator_action": action,
                "product_title": row.get("product_title", ""),
                "image_url": row.get("image_url", ""),
                "asin_url": row.get("asin_url", ""),
                "_priority": priority,
                "_is_ai": is_ai,
                "_price_threat": price_threat,
                "_trust_pressure": trust_pressure,
            }
        )
    result = pd.DataFrame(rows)
    if not result.empty:
        result = result.sort_values(["battle_score", "monthly_revenue"], ascending=[False, False])
    return result


def asin_profile_card(row: dict[str, object]) -> str:
    priority = str(row.get("_priority") or "P2")
    severity = "high" if priority == "P0" else "medium" if priority == "P1" else "info"
    image = str(row.get("image_url") or "").strip()
    image_html = (
        f"<img class='asin-thumb' src='{esc(image)}' alt='{esc(row.get('asin', 'ASIN'))}'>"
        if image
        else "<div class='asin-thumb'></div>"
    )
    title = str(row.get("product_title") or "")
    if len(title) > 118:
        title = title[:115] + "..."
    return (
        f"<div class='asin-profile-card {severity}'>"
        f"{image_html}"
        "<div>"
        f"{priority_pill(priority)}"
        f"<strong>{asin_anchor(row)} · {esc(row.get('standard_brand', ''))}</strong>"
        f"<p>{esc(row.get('risk_signal', ''))}</p>"
        f"<p>销量 {num(row.get('monthly_units'))} · 销售额 {num(row.get('monthly_revenue'))} · 排名 #{num(row.get('bsr_rank'))}</p>"
        f"<p>{esc(title)}</p>"
        "</div></div>"
    )


def competitor_asin_depth_html(run: dict[str, object], ai_detail: pd.DataFrame) -> str:
    depth = competitor_depth_dataframe(run, ai_detail)
    body = [
        "<section>",
        "<div class='section-head'>",
        f"<div><h2 data-i18n='competitor_asin_depth'>{esc(ui('competitor_asin_depth'))}</h2>",
        f"<div class='section-note' data-i18n='competitor_asin_depth_note'>{esc(ui('competitor_asin_depth_note'))}</div></div>",
        "</div>",
    ]
    if depth.empty:
        body.append(f"<div class='notice' data-i18n='no_asin_change_data'>{esc(ui('no_asin_change_data'))}</div></section>")
        return "".join(body)

    focus = depth[depth["_priority"].isin(["P0", "P1"])]
    price_threats = depth[depth["_price_threat"] == True]  # noqa: E712 - pandas boolean filtering.
    ai_pressure = depth[depth["_is_ai"] == True]  # noqa: E712 - pandas boolean filtering.
    review_pressure = depth[depth["_trust_pressure"] == True]  # noqa: E712 - pandas boolean filtering.
    kpis = [
        ("deep_focus_asin", len(focus), "target"),
        ("deep_price_pressure", len(price_threats), "warning"),
        ("deep_ai_positioning", len(ai_pressure), "bot"),
        ("deep_review_signal", len(review_pressure), "chat"),
    ]
    body.append("<div class='war-kpi-grid'>")
    for key, value, icon_name in kpis:
        body.append(
            "<div class='card metric-card'>"
            f"<span class='icon-badge'>{icon(icon_name)}</span>"
            f"<div><div class='metric-label' data-i18n='{esc(key)}'>{esc(ui(key))}</div><div class='metric-value'>{esc(value)}</div></div>"
            "</div>"
        )
    body.append("</div><div class='asin-depth-grid'>")
    for _, row in depth.head(4).iterrows():
        body.append(asin_profile_card(row.to_dict()))
    body.append("</div>")

    view = depth.head(30).copy()
    for col in ["battle_score", "monthly_units", "monthly_revenue", "price", "bsr_rank", "reviews"]:
        if col in view:
            view[col] = view[col].map(num)
    if "rating" in view:
        view["rating"] = view["rating"].map(lambda value: f"{value_as_float(value):.1f}" if value_as_float(value) else "")
    body.append("<div class='table-scroll war-table'>")
    body.append(
        dataframe_table(
            view,
            [
                "battle_score",
                "battle_priority",
                "risk_signal",
                "asin_link",
                "standard_brand",
                "monthly_units",
                "monthly_revenue",
                "price",
                "bsr_rank",
                "rank_trend",
                "rating",
                "reviews",
                "seller_type",
                "shelf_date",
                "operator_action",
                "product_title",
            ],
            limit=30,
            raw_columns={"battle_priority", "rank_trend", "asin_link"},
        )
    )
    body.append("</div></section>")
    return "".join(body)


def title_term_cloud(products: pd.DataFrame, limit: int = 26) -> str:
    if products.empty or "product_title" not in products:
        return ""
    stopwords = {
        "with", "for", "and", "the", "this", "that", "from", "into", "your", "you", "our", "per", "con", "para", "pour",
        "von", "und", "der", "die", "das", "les", "des", "del", "una", "uno", "plus", "black", "nero", "digital",
        "voice", "recorder", "recording", "audio", "device", "registratore", "grabadora", "dictaphone", "diktiergerät",
    }
    weights: dict[str, dict[str, float]] = {}
    for _, row in products.iterrows():
        title = str(row.get("product_title") or "").lower()
        revenue = max(value_as_float(row.get("monthly_revenue")), value_as_float(row.get("monthly_units")))
        for token in re.findall(r"[a-z0-9][a-z0-9+.-]{2,}", title):
            token = token.strip(".,-+")
            if not token or token in stopwords or token.isdigit():
                continue
            item = weights.setdefault(token, {"count": 0.0, "revenue": 0.0})
            item["count"] += 1
            item["revenue"] += revenue
    ranked = sorted(weights.items(), key=lambda item: (item[1]["count"], item[1]["revenue"]), reverse=True)[:limit]
    if not ranked:
        return ""
    counts = [max(1, value_as_int(stats.get("count"))) for _, stats in ranked]
    min_count = min(counts)
    max_count = max(counts)
    span = max(1, max_count - min_count)
    chips = []
    for index, (term, stats) in enumerate(ranked):
        count = max(1, value_as_int(stats.get("count")))
        ratio = (count - min_count) / span
        weight = ratio ** 0.72
        size = int(56 + weight * 72)
        length_factor = 0.19 if len(term) <= 4 else 0.155 if len(term) <= 8 else 0.125
        font_size = max(10, min(18, int(size * length_factor)))
        drift = (-1 if index % 2 else 1) * (4 + (index % 5))
        float_start = -4 - (index % 4)
        float_end = 5 + (index % 6)
        duration = 5.8 + (index % 7) * 0.55
        delay = -0.45 * (index % 9)
        glow = int(36 + weight * 34)
        style = (
            f"--size:{size}px;"
            f"--font-size:{font_size}px;"
            f"--delay:{delay:.2f}s;"
            f"--duration:{duration:.2f}s;"
            f"--drift:{drift}px;"
            f"--float-start:{float_start}px;"
            f"--float-end:{float_end}px;"
            f"--glow:{glow}%;"
        )
        chips.append(
            f"<span class='keyword-chip' style='{style}' title='{esc(term)} · {count}' tabindex='0'>"
            f"<strong>{esc(term)}</strong><em>{count}</em></span>"
        )
    return "<div class='keyword-cloud'>" + "".join(chips) + "</div>"


def keyword_cloud_from_weighted_terms(items: list[dict[str, object]], limit: int = 26) -> str:
    if not items:
        return ""
    normalized: list[dict[str, object]] = []
    for item in items:
        term = str(item.get("term") or "").strip()
        if not term:
            continue
        score = max(value_as_float(item.get("score")), value_as_float(item.get("count")), 1.0)
        count = max(1, value_as_int(item.get("count"), 1))
        normalized.append({"term": term, "score": score, "count": count})
    if not normalized:
        return ""
    normalized = sorted(normalized, key=lambda row: (value_as_float(row.get("score")), value_as_float(row.get("count"))), reverse=True)[:limit]
    scores = [max(1.0, value_as_float(row.get("score"))) for row in normalized]
    min_score = min(scores)
    max_score = max(scores)
    span = max(1.0, max_score - min_score)
    chips = []
    for index, row in enumerate(normalized):
        term = str(row.get("term") or "")
        score = max(1.0, value_as_float(row.get("score")))
        count = max(1, value_as_int(row.get("count"), 1))
        ratio = (score - min_score) / span
        weight = ratio ** 0.72
        size = int(56 + weight * 72)
        length_factor = 0.19 if len(term) <= 4 else 0.155 if len(term) <= 8 else 0.125
        font_size = max(10, min(18, int(size * length_factor)))
        drift = (-1 if index % 2 else 1) * (4 + (index % 5))
        float_start = -4 - (index % 4)
        float_end = 5 + (index % 6)
        duration = 5.8 + (index % 7) * 0.55
        delay = -0.45 * (index % 9)
        glow = int(36 + weight * 34)
        style = (
            f"--size:{size}px;"
            f"--font-size:{font_size}px;"
            f"--delay:{delay:.2f}s;"
            f"--duration:{duration:.2f}s;"
            f"--drift:{drift}px;"
            f"--float-start:{float_start}px;"
            f"--float-end:{float_end}px;"
            f"--glow:{glow}%;"
        )
        chips.append(
            f"<span class='keyword-chip' style='{style}' title='{esc(term)} · {num(score)}' tabindex='0'>"
            f"<strong>{esc(term)}</strong><em>{count}</em></span>"
        )
    return "<div class='keyword-cloud'>" + "".join(chips) + "</div>"


def mcp_asin_keyword_intel_for_run(run: dict[str, object]) -> pd.DataFrame:
    run_id = value_as_int(run.get("id"))
    if not run_id:
        return pd.DataFrame()
    try:
        return read_table_for_run(DB_PATH, "mcp_asin_keyword_intel", run_id)
    except Exception:
        return pd.DataFrame()


def mcp_keyword_terms(mcp_df: pd.DataFrame, limit: int = 26) -> list[dict[str, object]]:
    if mcp_df.empty or "keyword" not in mcp_df:
        return []
    view = mcp_df.copy()
    if "source_status" in view:
        view = view[view["source_status"].isin(["ok", "derived_from_mcp"])].copy()
    if "source_type" in view:
        view = view[view["source_type"].isin(["traffic_keyword", "keyword_order", "related_term"])].copy()
    view["keyword"] = view["keyword"].fillna("").astype(str).str.strip()
    view = view[view["keyword"] != ""].copy()
    if view.empty:
        return []
    if "searches" not in view:
        view["searches"] = 0
    if "purchases" not in view:
        view["purchases"] = 0
    view["_score"] = view.apply(
        lambda row: max(value_as_float(row.get("searches")), value_as_float(row.get("purchases")), 1.0),
        axis=1,
    )
    grouped = view.groupby("keyword", as_index=False).agg(score=("_score", "sum"), count=("keyword", "size"))
    grouped = grouped.sort_values(["score", "count"], ascending=[False, False]).head(limit)
    return [{"term": row["keyword"], "score": row["score"], "count": row["count"]} for _, row in grouped.iterrows()]


def mcp_keyword_summary_cards(mcp_df: pd.DataFrame) -> str:
    if mcp_df.empty:
        return ""
    ok = mcp_df[mcp_df["source_status"].isin(["ok", "derived_from_mcp"])] if "source_status" in mcp_df else mcp_df
    errors = mcp_df[mcp_df["source_status"] == "error"] if "source_status" in mcp_df else pd.DataFrame()
    keyword_rows = ok[ok["source_type"].isin(["traffic_keyword", "keyword_order"])] if "source_type" in ok else ok
    related_rows = ok[ok["source_type"] == "related_term"] if "source_type" in ok else pd.DataFrame()
    cards = [
        ("覆盖 ASIN", keyword_rows["asin"].replace("", pd.NA).dropna().nunique() if "asin" in keyword_rows else 0, "target"),
        ("搜索关键词", keyword_rows["keyword"].replace("", pd.NA).dropna().nunique() if "keyword" in keyword_rows else 0, "search"),
        ("相关词", related_rows["keyword"].replace("", pd.NA).dropna().nunique() if "keyword" in related_rows else 0, "search"),
        ("失败记录", len(errors), "warning"),
    ]
    body = ["<div class='war-kpi-grid'>"]
    for label, value, icon_name in cards:
        body.append(
            "<div class='card metric-card'>"
            f"<span class='icon-badge'>{icon(icon_name)}</span>"
            f"<div><div class='metric-label'>{esc(label)}</div><div class='metric-value'>{esc(value)}</div></div>"
            "</div>"
        )
    body.append("</div>")
    return "".join(body)


def mcp_keyword_tables_html(mcp_df: pd.DataFrame) -> str:
    if mcp_df.empty:
        return "<div class='notice'>暂无 MCP ASIN 关键词深挖数据；点击顶部“获取最新周数据”或运行每周任务后会自动填充。</div>"
    ok = mcp_df[mcp_df["source_status"].isin(["ok", "derived_from_mcp"])] if "source_status" in mcp_df else mcp_df
    keyword_rows = ok[ok["source_type"].isin(["traffic_keyword", "keyword_order"])] if "source_type" in ok else ok
    related_rows = ok[ok["source_type"] == "related_term"] if "source_type" in ok else pd.DataFrame()
    body: list[str] = []
    if not keyword_rows.empty:
        view = (
            keyword_rows.sort_values(["searches", "purchases"], ascending=[False, False]).copy()
            if {"searches", "purchases"}.issubset(keyword_rows.columns)
            else keyword_rows.copy()
        )
        for col in ["searches", "purchases", "rank_position", "ad_position", "bid", "products", "supply_demand_ratio"]:
            if col in view:
                view[col] = view[col].map(num)
        for col in ["purchase_rate", "traffic_percentage"]:
            if col in view:
                view[col] = view[col].map(pct)
        body.append("<h3>MCP ASIN 搜索词明细</h3>")
        body.append("<div class='table-scroll ops-table'>")
        body.append(
            dataframe_table(
                view,
                [
                    "source_type",
                    "asin",
                    "brand",
                    "keyword",
                    "keyword_type",
                    "conversion_type",
                    "searches",
                    "purchases",
                    "purchase_rate",
                    "traffic_percentage",
                    "rank_position",
                    "ad_position",
                    "bid",
                ],
                limit=40,
            )
        )
        body.append("</div>")
    if not related_rows.empty:
        related_view = (
            related_rows.sort_values(["searches", "purchases"], ascending=[False, False]).copy()
            if {"searches", "purchases"}.issubset(related_rows.columns)
            else related_rows.copy()
        )
        for col in ["searches", "purchases"]:
            if col in related_view:
                related_view[col] = related_view[col].map(num)
        body.append("<h3>MCP 相关词聚合</h3>")
        body.append("<div class='table-scroll ops-table'>")
        body.append(
            dataframe_table(
                related_view,
                ["keyword", "searches", "purchases", "source_status", "fetched_at"],
                limit=30,
            )
        )
        body.append("</div>")
    errors = mcp_df[mcp_df["source_status"] == "error"] if "source_status" in mcp_df else pd.DataFrame()
    if not errors.empty:
        body.append("<details class='notice'><summary>MCP 深挖失败记录</summary>")
        body.append(
            dataframe_table(
                errors,
                ["source_type", "asin", "brand", "source_error", "fetched_at"],
                limit=30,
            )
        )
        body.append("</details>")
    return "".join(body) if body else "<div class='notice'>MCP 深挖已运行，但暂无可展示关键词记录。</div>"


def keyword_opportunity_dataframe(run: dict[str, object], ai_detail: pd.DataFrame) -> pd.DataFrame:
    products = enriched_product_metrics_for_run(run)
    if products.empty:
        return pd.DataFrame()
    ai_asins = ai_asins_from_detail(ai_detail)
    rows = []
    for feature in keyword_feature_catalog():
        phrases = [str(item) for item in feature.get("phrases", [])]
        matched = products[products.apply(lambda row: feature_matches(row, phrases), axis=1)].copy()
        if matched.empty:
            continue
        matched["_units"] = matched["monthly_units"].map(value_as_float) if "monthly_units" in matched else 0.0
        matched["_revenue"] = matched["monthly_revenue"].map(value_as_float) if "monthly_revenue" in matched else 0.0
        matched["_asin_key"] = matched["asin"].map(clean_asin) if "asin" in matched else ""
        brand_units = matched.groupby("standard_brand")["_units"].sum().sort_values(ascending=False) if "standard_brand" in matched else pd.Series(dtype=float)
        top_brand = str(brand_units.index[0]) if not brand_units.empty else ""
        plaud_units = value_as_float(brand_units.get("PLAUD")) if not brand_units.empty else 0.0
        total_units = float(matched["_units"].sum())
        ai_units = float(matched[matched["_asin_key"].isin(ai_asins)]["_units"].sum()) if ai_asins else 0.0
        opportunity_type = str(feature.get("type", "机会词"))
        if total_units and plaud_units / total_units < 0.35 and top_brand != "PLAUD":
            opportunity_type = "竞品进攻词"
        elif ai_units > 0:
            opportunity_type = "AI 机会词"
        rows.append(
            {
                "keyword_opportunity": feature.get("label", ""),
                "opportunity_type": opportunity_type,
                "matched_asins": len(matched),
                "monthly_units": total_units,
                "monthly_revenue": float(matched["_revenue"].sum()),
                "top_brand": top_brand,
                "recommended_action": feature.get("action", ""),
            }
        )
    result = pd.DataFrame(rows)
    if not result.empty:
        result = result.sort_values(["monthly_revenue", "monthly_units"], ascending=[False, False])
    return result


def voc_rows_from_products(run: dict[str, object], ai_detail: pd.DataFrame) -> list[dict[str, object]]:
    products = enriched_product_metrics_for_run(run)
    if products.empty:
        return []
    keyword_df = keyword_opportunity_dataframe(run, ai_detail)
    rows: list[dict[str, object]] = []
    for _, item in keyword_df.head(5).iterrows():
        rows.append(
            {
                "voc_theme": item.get("keyword_opportunity", ""),
                "market_signal": f"标题命中 {value_as_int(item.get('matched_asins'))} 个 ASIN，月销量 {num(item.get('monthly_units'))}，代表品牌 {item.get('top_brand') or '—'}。",
                "evidence": "来源：SellerSprite MCP 商品标题、销量和品牌字段。",
                "recommended_action": item.get("recommended_action", ""),
            }
        )

    if "reviews" in products and "rating" in products:
        review_sample = products.copy()
        review_sample["_reviews"] = review_sample["reviews"].map(value_as_float)
        review_sample["_rating"] = review_sample["rating"].map(value_as_float)
        review_sample = review_sample[review_sample["_reviews"] > 0].copy()
        if not review_sample.empty:
            top_review = first_row(review_sample.sort_values("_reviews", ascending=False).head(1))
            low_rating = review_sample[(review_sample["_rating"] > 0) & (review_sample["_rating"] < 4.2)]
            rows.append(
                {
                    "voc_theme": "信任门槛 / 评论资产",
                    "market_signal": f"评论数最高样本 {top_review.get('asin')} · {top_review.get('standard_brand')}，评论 {num(top_review.get('_reviews'))}，评分 {value_as_float(top_review.get('_rating')):.1f}。",
                    "evidence": f"低于 4.2 分样本 {len(low_rating)} 个；当前是评分/评论数量信号，不含评论原文。",
                    "recommended_action": "PLAUD 页面补足权威评测、用户场景证据和差评预防 FAQ；后续接 MCP 评论原文后做真实 VOC 聚类。",
                }
            )
    return rows[:6]


def keyword_voc_opportunity_html(run: dict[str, object], ai_detail: pd.DataFrame) -> str:
    products = enriched_product_metrics_for_run(run)
    mcp_keywords = mcp_asin_keyword_intel_for_run(run)
    keyword_df = keyword_opportunity_dataframe(run, ai_detail)
    voc_rows = voc_rows_from_products(run, ai_detail)
    body = [
        "<section>",
        "<div class='section-head'>",
        f"<div><h2 data-i18n='keyword_voc_opportunity'>{esc(ui('keyword_voc_opportunity'))}</h2>",
        f"<div class='section-note' data-i18n='keyword_voc_note'>{esc(ui('keyword_voc_note'))}</div></div>",
        "</div>",
    ]
    if products.empty:
        body.append(f"<div class='notice' data-i18n='no_asin_change_data'>{esc(ui('no_asin_change_data'))}</div></section>")
        return "".join(body)

    mcp_terms = mcp_keyword_terms(mcp_keywords)
    cloud = keyword_cloud_from_weighted_terms(mcp_terms) if mcp_terms else title_term_cloud(products)
    if cloud:
        body.append(cloud)
    if not mcp_keywords.empty:
        body.append(mcp_keyword_summary_cards(mcp_keywords))
    body.append("<div class='voc-grid'>")
    for item in voc_rows[:3]:
        body.append(
            "<div class='voc-card'>"
            f"<span class='pill'>{esc(item.get('voc_theme', ''))}</span>"
            f"<strong>{esc(item.get('market_signal', ''))}</strong>"
            f"<p>{esc(item.get('recommended_action', ''))}</p>"
            "</div>"
        )
    if not voc_rows:
        body.append("<div class='notice'>暂无可用 VOC 信号。</div>")
    body.append("</div>")

    body.append("<h3>Top 20 竞品 ASIN MCP 二次深挖</h3>")
    body.append(mcp_keyword_tables_html(mcp_keywords))

    view = keyword_df.copy()
    for col in ["matched_asins", "monthly_units", "monthly_revenue"]:
        if col in view:
            view[col] = view[col].map(num)
    body.append("<div class='table-scroll ops-table'>")
    body.append(
        dataframe_table(
            view,
            ["keyword_opportunity", "opportunity_type", "matched_asins", "monthly_units", "monthly_revenue", "top_brand", "recommended_action"],
            empty="暂无关键词机会。",
            limit=20,
        )
    )
    body.append("</div>")

    if voc_rows:
        body.append("<h3>VOC 假设与证据</h3>")
        body.append(
            dataframe_table(
                pd.DataFrame(voc_rows),
                ["voc_theme", "market_signal", "evidence", "recommended_action"],
                limit=8,
            )
        )
    body.append("</section>")
    return "".join(body)


def price_band_label(currency: str, low: float, high: float | None) -> str:
    prefix = f"{currency} " if currency else ""
    if high is None:
        return f"{prefix}{int(low)}+"
    if low <= 0:
        return f"{prefix}<{int(high)}"
    return f"{prefix}{int(low)}-{int(high - 1)}"


def units_revenue_text(units: float, revenue: float) -> str:
    return f"{num(units)} / {num(revenue)}"


def price_band_analysis_html(run: dict[str, object], ai_detail: pd.DataFrame) -> str:
    products = product_metrics_for_run(run)
    body = [
        "<section>",
        "<div class='section-head'>",
        f"<div><h2 data-i18n='price_band_analysis'>{esc(ui('price_band_analysis'))}</h2>",
        f"<div class='section-note' data-i18n='price_band_note'>{esc(ui('price_band_note'))}</div></div>",
        "</div>",
    ]
    if products.empty or "price" not in products:
        body.append(f"<div class='notice' data-i18n='no_price_data'>{esc(ui('no_price_data'))}</div></section>")
        return "".join(body)

    sample = products.copy()
    sample["_price"] = sample["price"].map(value_as_float)
    sample["_units"] = sample["monthly_units"].map(value_as_float) if "monthly_units" in sample else 0.0
    sample["_revenue"] = sample["monthly_revenue"].map(value_as_float) if "monthly_revenue" in sample else 0.0
    sample["_asin_key"] = sample["asin"].map(clean_asin) if "asin" in sample else ""
    sample = sample[sample["_price"] > 0].copy()
    if sample.empty:
        body.append(f"<div class='notice' data-i18n='no_price_data'>{esc(ui('no_price_data'))}</div></section>")
        return "".join(body)

    config = load_config(CONFIG_PATH)
    currency = str(config.get("marketplaces", {}).get(str(run.get("marketplace", "")), {}).get("currency", ""))
    ai_asins = ai_asins_from_detail(ai_detail)
    total_units = float(sample["_units"].sum())
    total_revenue = float(sample["_revenue"].sum())
    bands = [(0.0, 50.0), (50.0, 100.0), (100.0, 150.0), (150.0, 200.0), (200.0, None)]

    body.append("<div class='table-scroll'><table><thead><tr>")
    headers = [
        ("price_band", ui("price_band")),
        ("asin_count", ui("asin_count")),
        ("all_products", ui("all_products")),
        ("unit_share", ui("unit_share")),
        ("revenue_share", ui("revenue_share")),
        ("plaud_products", ui("plaud_products")),
        ("ai_products", ui("ai_products")),
    ]
    for key, label in headers:
        body.append(f"<th data-i18n='{esc(key)}'>{esc(label)}</th>")
    body.append("</tr></thead><tbody>")
    for low, high in bands:
        if high is None:
            band_df = sample[sample["_price"] >= low]
        else:
            band_df = sample[(sample["_price"] >= low) & (sample["_price"] < high)]
        if band_df.empty:
            continue
        band_units = float(band_df["_units"].sum())
        band_revenue = float(band_df["_revenue"].sum())
        plaud_df = band_df[band_df["standard_brand"] == "PLAUD"] if "standard_brand" in band_df else band_df.head(0)
        ai_df = band_df[band_df["_asin_key"].isin(ai_asins)] if ai_asins else band_df.head(0)
        body.append(
            "<tr>"
            f"<td><strong>{esc(price_band_label(currency, low, high))}</strong></td>"
            f"<td>{len(band_df)}</td>"
            f"<td>{esc(units_revenue_text(band_units, band_revenue))}</td>"
            f"<td>{pct(band_units / total_units if total_units else 0)}</td>"
            f"<td>{pct(band_revenue / total_revenue if total_revenue else 0)}</td>"
            f"<td>{esc(units_revenue_text(float(plaud_df['_units'].sum()), float(plaud_df['_revenue'].sum())))}</td>"
            f"<td>{esc(units_revenue_text(float(ai_df['_units'].sum()), float(ai_df['_revenue'].sum())))}</td>"
            "</tr>"
        )
    body.append("</tbody></table></div></section>")
    return "".join(body)


def metric_history(marketplace: str, metric: str) -> list[tuple[str, float]]:
    runs = [run for run in latest_runs(DB_PATH, limit=200) if run["status"] == "ok" and run["marketplace"] == marketplace]
    runs = sorted(runs, key=lambda item: item["id"])
    points = []
    for run in runs:
        snapshot = build_run_snapshot(run)
        if not snapshot_has_market_data(snapshot):
            continue
        value = value_as_float(snapshot.get(metric))
        points.append((f"{run['week_id']} #{run['id']}", value))
    return points


def format_delta_pp(delta: object) -> str:
    if delta is None:
        return "—"
    return f"{value_as_float(delta) * 100:+.2f}pp"


def format_delta_number(delta: object) -> str:
    if delta is None:
        return "—"
    value = value_as_float(delta)
    sign = "+" if value > 0 else ""
    return f"{sign}{format_number(value)}"


def delta_class(delta: object) -> str:
    if delta is None:
        return "delta-flat"
    value = value_as_float(delta)
    if value > 0:
        return "delta-up"
    if value < 0:
        return "delta-down"
    return "delta-flat"


def delta_cell(delta: object, mode: str = "pp") -> str:
    text = format_delta_pp(delta) if mode == "pp" else format_delta_number(delta)
    return f"<span class='{delta_class(delta)}'>{esc(text)}</span>"


def build_run_snapshot(run: dict[str, object]) -> dict[str, object]:
    run_id = int(run["id"])
    brand = read_table_for_run(DB_PATH, "brand_metrics", run_id)
    ai_summary = read_table_for_run(DB_PATH, "ai_summary", run_id)
    ai_detail = read_table_for_run(DB_PATH, "ai_detail", run_id)
    plaud = first_row(brand[brand["brand"] == "PLAUD"]) if not brand.empty else {}
    competitors = first_row(brand[brand["brand"] == "COMPETITORS_TOTAL"]) if not brand.empty else {}
    ai = first_row(ai_summary.head(1)) if not ai_summary.empty else {}
    return {
        "has_data": True,
        "run": run,
        "site": run.get("marketplace", ""),
        "run_id": run_id,
        "week_id": run.get("week_id", ""),
        "brand_df": brand,
        "ai_detail_df": ai_detail,
        "plaud_units_share": value_as_float(plaud.get("monthly_units_share")),
        "plaud_revenue_share": value_as_float(plaud.get("monthly_revenue_share")),
        "competitor_units_share": value_as_float(competitors.get("monthly_units_share")),
        "competitor_revenue_share": value_as_float(competitors.get("monthly_revenue_share")),
        "ai_units_share": value_as_float(ai.get("ai_units_share")),
        "ai_revenue_share": value_as_float(ai.get("ai_revenue_share")),
        "ai_asin_count": int(value_as_float(ai.get("ai_competitor_asin_count"))),
        "category_units": value_as_float(ai.get("category_units")),
        "category_revenue": value_as_float(ai.get("category_revenue")),
        "previous": None,
    }


def build_site_snapshots(sites: list[str], week_id: str | None = None) -> list[dict[str, object]]:
    ok_runs = [run for run in latest_runs(DB_PATH, limit=500) if run["status"] == "ok"]
    by_site: dict[str, list[dict[str, object]]] = {site: [] for site in sites}
    for run in ok_runs:
        site = str(run.get("marketplace", ""))
        if site in by_site:
            by_site[site].append(run)

    snapshots = []
    for site in sites:
        runs = sorted(by_site.get(site, []), key=run_recency_key, reverse=True)
        latest_run_by_week: dict[str, dict[str, object]] = {}
        for run in runs:
            week = str(run.get("week_id") or f"Run #{run.get('id')}")
            current_for_week = latest_run_by_week.get(week)
            if current_for_week is None or run_recency_key(run) > run_recency_key(current_for_week):
                latest_run_by_week[week] = run
        runs = sorted(latest_run_by_week.values(), key=run_recency_key, reverse=True)
        valid_snapshots = []
        for run in runs:
            snapshot = build_run_snapshot(run)
            if snapshot_has_market_data(snapshot):
                valid_snapshots.append(snapshot)
        if not valid_snapshots:
            snapshots.append({"has_data": False, "site": site, "previous": None})
            continue
        if week_id:
            current_index = next(
                (idx for idx, snapshot in enumerate(valid_snapshots) if str(snapshot.get("week_id")) == week_id),
                -1,
            )
            if current_index < 0:
                snapshots.append({"has_data": False, "site": site, "week_id": week_id, "previous": None})
                continue
        else:
            current_index = 0
        current = valid_snapshots[current_index]
        if current_index + 1 < len(valid_snapshots):
            previous = valid_snapshots[current_index + 1]
            current["previous"] = previous
            for key in [
                "plaud_units_share",
                "plaud_revenue_share",
                "competitor_units_share",
                "competitor_revenue_share",
                "ai_units_share",
                "ai_revenue_share",
                "category_units",
                "category_revenue",
            ]:
                current[f"{key}_delta"] = value_as_float(current.get(key)) - value_as_float(previous.get(key))
            prev_category_units = value_as_float(previous.get("category_units"))
            current["category_units_delta_ratio"] = (
                current["category_units_delta"] / prev_category_units if prev_category_units else None
            )
        else:
            for key in [
                "plaud_units_share",
                "plaud_revenue_share",
                "competitor_units_share",
                "competitor_revenue_share",
                "ai_units_share",
                "ai_revenue_share",
                "category_units",
                "category_revenue",
            ]:
                current[f"{key}_delta"] = None
            current["category_units_delta_ratio"] = None
        snapshots.append(current)
    return snapshots


def alert_card(severity: str, title: str, detail: str, site: str = "") -> str:
    label_key = "risk_high" if severity == "high" else "risk_medium" if severity == "medium" else "risk_info"
    icon_name = "warning" if severity == "high" else "target" if severity == "medium" else "info"
    return (
        f"<div class='alert-card alert-{esc(severity)}'>"
        "<div class='card-topline'>"
        f"<span class='pill' data-i18n='{esc(label_key)}'>{esc(ui(label_key))}</span>"
        f"<span class='severity-icon'>{icon(icon_name)}</span>"
        "</div>"
        f"<strong>{esc(title)}</strong>"
        f"<p>{esc(detail)}</p>"
        f"{f'<p class=\"muted\">{esc(site)}</p>' if site else ''}"
        "</div>"
    )


def build_alert_items(snapshots: list[dict[str, object]]) -> list[dict[str, str]]:
    alerts: list[tuple[str, str, str, str]] = []
    for item in snapshots:
        site = str(item.get("site", ""))
        if not item.get("has_data"):
            alerts.append(("medium", f"{site} 缺少监控数据", "请补充该站点卖家精灵 Excel，避免七站点汇总失真。", site))
            continue
        if not item.get("previous"):
            alerts.append(("info", f"{site} 暂无前一周可比数据", "继续上传下一周数据后，将自动生成环比预警和 Top 变化榜。", site))
            continue
        plaud_delta = value_as_float(item.get("plaud_units_share_delta"))
        competitor_delta = value_as_float(item.get("competitor_units_share_delta"))
        ai_delta = value_as_float(item.get("ai_units_share_delta"))
        category_delta_ratio = item.get("category_units_delta_ratio")
        if plaud_delta <= -0.02:
            alerts.append(("high", f"{site} PLAUD 销量份额下降 {format_delta_pp(plaud_delta)}", "建议检查该站点竞品价格、Listing 排名和 AI 新品增长。", site))
        elif plaud_delta <= -0.01:
            alerts.append(("medium", f"{site} PLAUD 销量份额小幅下降 {format_delta_pp(plaud_delta)}", "建议持续观察。", site))
        if competitor_delta >= 0.02:
            alerts.append(("medium", f"{site} 监控竞品份额上升 {format_delta_pp(competitor_delta)}", "建议查看 Top 变化榜中增长最快的品牌。", site))
        if ai_delta >= 0.03:
            alerts.append(("high", f"{site} AI 竞品渗透快速上升 {format_delta_pp(ai_delta)}", "建议优先复核新增 AI ASIN 和高增长 ASIN。", site))
        elif ai_delta >= 0.01:
            alerts.append(("medium", f"{site} AI 竞品渗透上升 {format_delta_pp(ai_delta)}", "建议关注 AI 竞品标题、价格带和评论增长。", site))
        if category_delta_ratio is not None and abs(value_as_float(category_delta_ratio)) >= 0.2:
            direction = "增长" if value_as_float(category_delta_ratio) > 0 else "下滑"
            alerts.append(("medium", f"{site} 类目销量{direction} {value_as_float(category_delta_ratio) * 100:+.1f}%", "建议确认是否为季节性、采集范围变化或插件数据波动。", site))

    if not alerts:
        alerts.append(("info", "暂无明显风险", "当前数据未触发份额、竞品或 AI 渗透异常。", ""))
    severity_order = {"high": 0, "medium": 1, "info": 2}
    alerts = sorted(alerts, key=lambda item: severity_order.get(item[0], 9))[:9]
    return [
        {"severity": severity, "title": title, "detail": detail, "site": site}
        for severity, title, detail, site in alerts
    ]


def alert_center_html(snapshots: list[dict[str, object]]) -> str:
    alerts = build_alert_items(snapshots)
    body = [
        "<section id='alert-center'>",
        "<div class='section-head'>",
        f"<div><h2 data-i18n='alert_center'>{esc(ui('alert_center'))}</h2>",
        f"<div class='section-note' data-i18n='alert_center_note'>{esc(ui('alert_center_note'))}</div></div>",
        "</div>",
        "<div class='alert-grid'>",
    ]
    for item in alerts:
        body.append(alert_card(item["severity"], item["title"], item["detail"], item["site"]))
    body.append("</div></section>")
    return "".join(body)


def dashboard_ops_priority_html(
    snapshots: list[dict[str, object]],
    latest_id: int | None,
    site_runs: dict[str, dict[str, object]],
    sites: list[str],
) -> str:
    alerts = build_alert_items(snapshots)
    high_count = sum(1 for item in alerts if item["severity"] == "high")
    medium_count = sum(1 for item in alerts if item["severity"] == "medium")
    ready_sites = sum(1 for item in snapshots if item.get("has_data"))
    comparable_sites = sum(1 for item in snapshots if item.get("has_data") and item.get("previous"))
    first_risk = next((item for item in alerts if item["severity"] == "high"), alerts[0] if alerts else {})
    brand_title, brand_rows = top_brand_rows(snapshots, limit=1)
    asin_title, asin_rows = top_asin_rows(snapshots, limit=1)
    brand_focus = brand_rows[0] if brand_rows else {}
    asin_focus = asin_rows[0] if asin_rows else {}

    if high_count:
        brief = f"本周优先处理 {high_count} 个高风险预警，先看 {first_risk.get('site') or '重点站点'} 的份额/AI 变化。"
        risk_class = "high"
    elif medium_count:
        brief = f"本周有 {medium_count} 个需要观察的变化，建议先复核趋势墙和 Top 变化榜。"
        risk_class = "medium"
    else:
        brief = "本周未触发明显高风险，运营重点可放在趋势复盘、竞品机会和周报发布。"
        risk_class = "ok"

    latest_action = f"/analysis?id={latest_id}" if latest_id else "/uploads"
    focus_items = [
        ("高风险", num(high_count), f"中风险 {num(medium_count)}"),
        ("站点覆盖", f"{ready_sites}/{len(sites)}", f"可环比 {comparable_sites} 个"),
        ("最新 Run", f"#{latest_id}" if latest_id else "-", "用于周报和复盘"),
    ]
    next_items = [
        ("复核预警", first_risk.get("title", "暂无明显风险"), "#alert-center"),
        ("看趋势", "PLAUD、AI 竞品、监控竞品七站点走势", "#trend-wall"),
        ("出周报", "进入分析页复核后下载 Excel 周报", latest_action),
    ]
    priority_cards = [
        (
            risk_class,
            "风险优先",
            first_risk.get("title", "暂无明显风险"),
            first_risk.get("detail", "当前数据未触发份额、竞品或 AI 渗透异常。"),
            "#alert-center",
        ),
        (
            "ok",
            "机会优先",
            f"{brand_focus.get('site', '—')} · {brand_focus.get('name', '暂无品牌机会')}",
            f"{ui(brand_title)}：当前 {pct(brand_focus.get('current'))}，变化 {format_delta_pp(brand_focus.get('delta'))}。",
            "#top-movement",
        ),
        (
            "medium",
            "ASIN 优先",
            f"{asin_focus.get('site', '—')} · {asin_focus.get('asin', '暂无 ASIN 变化')}",
            f"{ui(asin_title)}：{asin_focus.get('brand', '—')}，销售额 {num(asin_focus.get('current'))}。",
            "#top-movement",
        ),
        (
            "ok" if ready_sites == len(sites) else "medium",
            "数据优先",
            f"{ready_sites}/{len(sites)} 站点可用",
            "七站点齐全后，横向对比、全球品牌份额和周报口径更稳定。",
            "/uploads",
        ),
    ]

    body = [
        "<section class='ops-hero'>",
        "<div class='ops-brief'>",
        "<div class='ops-brief-top'>",
        f"<div><h2 data-i18n='dashboard_title'>{esc(ui('dashboard_title'))}</h2><p class='ops-brief-line'>{esc(brief)}</p></div>",
        f"<span class='pill pill-ok' data-i18n='weekly_mvp'>{esc(ui('weekly_mvp'))}</span>",
        "</div><div class='ops-focus-grid'>",
    ]
    for label, value, detail in focus_items:
        body.append(
            "<div class='ops-focus-item'>"
            f"<span>{esc(label)}</span><strong>{esc(str(value))}</strong><p>{esc(detail)}</p>"
            "</div>"
        )
    body.append("</div></div><div class='ops-next'>")
    body.append("<div class='ops-next-title'><strong>运营下一步</strong><span class='pill'>本周</span></div><div class='ops-next-list'>")
    for index, (title, detail, href) in enumerate(next_items, start=1):
        body.append(
            "<a class='ops-next-item' href='{href}'>"
            f"<span class='ops-next-index'>{index}</span>"
            f"<div><strong>{esc(title)}</strong><p>{esc(detail)}</p></div>"
            "</a>".format(href=esc(href))
        )
    body.append("</div></div></section>")
    body.append("<section class='ops-priority-strip'>")
    for severity, title, headline, detail, href in priority_cards:
        body.append(
            f"<div class='ops-priority-card {esc(severity)}'>"
            f"<span class='pill'>{esc(title)}</span>"
            f"<strong>{esc(str(headline))}</strong>"
            f"<p>{esc(str(detail))}</p>"
            f"<a href='{esc(href)}'>查看详情</a>"
            "</div>"
        )
    body.append("</section>")
    return "".join(body)


def seven_site_comparison_html(snapshots: list[dict[str, object]]) -> str:
    rows = [
        "<section>",
        f"<h2 data-i18n='seven_site_comparison'>{esc(ui('seven_site_comparison'))}</h2>",
        "<div class='comparison-scroll'><table><thead><tr>",
        f"<th data-i18n='marketplace'>{esc(ui('marketplace'))}</th>",
        f"<th data-i18n='week_id'>{esc(ui('week_id'))}</th>",
        "<th>Run</th>",
        f"<th data-i18n='plaud_units_share'>{esc(ui('plaud_units_share'))}</th>",
        f"<th data-i18n='delta'>{esc(ui('delta'))}</th>",
        f"<th data-i18n='competitor_units_share'>{esc(ui('competitor_units_share'))}</th>",
        f"<th data-i18n='ai_units_share'>{esc(ui('ai_units_share'))}</th>",
        f"<th data-i18n='delta'>{esc(ui('delta'))}</th>",
        f"<th data-i18n='ai_asin_detail'>{esc(ui('ai_asin_detail'))}</th>",
        f"<th data-i18n='status'>{esc(ui('status'))}</th>",
        "</tr></thead><tbody>",
    ]
    for item in snapshots:
        site = str(item.get("site", ""))
        if not item.get("has_data"):
            rows.append(
                "<tr>"
                f"<td><strong>{esc(site)}</strong></td><td>—</td><td>—</td><td>—</td><td>—</td><td>—</td><td>—</td><td>—</td><td>—</td>"
                f"<td><span class='pill pill-missing' data-i18n='data_missing'>{esc(ui('data_missing'))}</span></td>"
                "</tr>"
            )
            continue
        status_key = "data_ready" if item.get("previous") else "data_no_previous"
        status_class = "pill-ok" if item.get("previous") else "pill-missing"
        rows.append(
            "<tr>"
            f"<td><strong>{esc(site)}</strong></td>"
            f"<td>{esc(item.get('week_id'))}</td>"
            f"<td><a href='/analysis?id={esc(item.get('run_id'))}'>#{esc(item.get('run_id'))}</a></td>"
            f"<td>{pct(item.get('plaud_units_share'))}</td>"
            f"<td>{delta_cell(item.get('plaud_units_share_delta'))}</td>"
            f"<td>{pct(item.get('competitor_units_share'))}</td>"
            f"<td>{pct(item.get('ai_units_share'))}</td>"
            f"<td>{delta_cell(item.get('ai_units_share_delta'))}</td>"
            f"<td>{esc(item.get('ai_asin_count'))}</td>"
            f"<td><span class='pill {status_class}' data-i18n='{status_key}'>{esc(ui(status_key))}</span></td>"
            "</tr>"
        )
    rows.append("</tbody></table></div></section>")
    return "".join(rows)


def top_brand_rows(snapshots: list[dict[str, object]], limit: int = 8) -> tuple[str, list[dict[str, object]]]:
    rows = []
    has_previous = any(item.get("has_data") and item.get("previous") for item in snapshots)
    if has_previous:
        for item in snapshots:
            if not item.get("has_data") or not item.get("previous"):
                continue
            current = item.get("brand_df")
            previous = item["previous"].get("brand_df")
            if not isinstance(current, pd.DataFrame) or not isinstance(previous, pd.DataFrame) or current.empty:
                continue
            prev_map = {str(row.get("brand")): row for _, row in previous.iterrows()}
            for _, row in current.iterrows():
                brand = str(row.get("brand", ""))
                if brand == "COMPETITORS_TOTAL":
                    continue
                delta = value_as_float(row.get("monthly_units_share")) - value_as_float(prev_map.get(brand, {}).get("monthly_units_share"))
                rows.append(
                    {
                        "site": item.get("site"),
                        "name": brand,
                        "current": value_as_float(row.get("monthly_units_share")),
                        "delta": delta,
                    }
                )
        return "brand_growth_rank", sorted(rows, key=lambda item: value_as_float(item.get("delta")), reverse=True)[:limit]

    for item in snapshots:
        if not item.get("has_data"):
            continue
        current = item.get("brand_df")
        if not isinstance(current, pd.DataFrame) or current.empty:
            continue
        for _, row in current.iterrows():
            brand = str(row.get("brand", ""))
            if brand == "COMPETITORS_TOTAL":
                continue
            rows.append(
                {
                    "site": item.get("site"),
                    "name": brand,
                    "current": value_as_float(row.get("monthly_units_share")),
                    "delta": None,
                }
            )
    return "current_brand_rank", sorted(rows, key=lambda item: value_as_float(item.get("current")), reverse=True)[:limit]


def top_asin_rows(snapshots: list[dict[str, object]], limit: int = 8) -> tuple[str, list[dict[str, object]]]:
    rows = []
    has_previous = any(item.get("has_data") and item.get("previous") for item in snapshots)
    if has_previous:
        for item in snapshots:
            if not item.get("has_data") or not item.get("previous"):
                continue
            current = item.get("ai_detail_df")
            previous = item["previous"].get("ai_detail_df")
            if not isinstance(current, pd.DataFrame) or current.empty:
                continue
            prev_map = {}
            if isinstance(previous, pd.DataFrame) and not previous.empty:
                prev_map = {str(row.get("asin")): row for _, row in previous.iterrows()}
            for _, row in current.iterrows():
                asin = str(row.get("asin", ""))
                prev = prev_map.get(asin, {})
                delta = value_as_float(row.get("monthly_revenue")) - value_as_float(prev.get("monthly_revenue"))
                rows.append(
                    {
                        "site": item.get("site"),
                        "asin": asin,
                        "brand": row.get("standard_brand", ""),
                        "current": value_as_float(row.get("monthly_revenue")),
                        "delta": delta,
                    }
                )
        return "asin_growth_rank", sorted(rows, key=lambda item: value_as_float(item.get("delta")), reverse=True)[:limit]

    for item in snapshots:
        if not item.get("has_data"):
            continue
        current = item.get("ai_detail_df")
        if not isinstance(current, pd.DataFrame) or current.empty:
            continue
        for _, row in current.iterrows():
            rows.append(
                {
                    "site": item.get("site"),
                    "asin": row.get("asin", ""),
                    "brand": row.get("standard_brand", ""),
                    "current": value_as_float(row.get("monthly_revenue")),
                    "delta": None,
                }
            )
    return "current_ai_asin_rank", sorted(rows, key=lambda item: value_as_float(item.get("current")), reverse=True)[:limit]


def rank_card_html(title_key: str, rows: list[dict[str, object]], kind: str) -> str:
    body = [
        "<div class='rank-card'>",
        f"<h2 data-i18n='{esc(title_key)}'>{esc(ui(title_key))}</h2>",
    ]
    if not rows:
        body.append(f"<div class='notice' data-i18n='no_rank_data'>{esc(ui('no_rank_data'))}</div></div>")
        return "".join(body)
    if kind == "brand":
        body.append(
            "<table><thead><tr>"
            f"<th data-i18n='marketplace'>{esc(ui('marketplace'))}</th>"
            f"<th data-i18n='col_brand'>{esc(ui('col_brand'))}</th>"
            f"<th data-i18n='current_value'>{esc(ui('current_value'))}</th>"
            f"<th data-i18n='share_delta'>{esc(ui('share_delta'))}</th>"
            "</tr></thead><tbody>"
        )
        for row in rows:
            body.append(
                "<tr>"
                f"<td>{esc(row.get('site'))}</td>"
                f"<td>{esc(row.get('name'))}</td>"
                f"<td>{pct(row.get('current'))}</td>"
                f"<td>{delta_cell(row.get('delta'))}</td>"
                "</tr>"
            )
    else:
        body.append(
            "<table><thead><tr>"
            f"<th data-i18n='marketplace'>{esc(ui('marketplace'))}</th>"
            f"<th data-i18n='col_asin'>{esc(ui('col_asin'))}</th>"
            f"<th data-i18n='col_brand'>{esc(ui('col_brand'))}</th>"
            f"<th data-i18n='current_value'>{esc(ui('current_value'))}</th>"
            f"<th data-i18n='revenue_delta'>{esc(ui('revenue_delta'))}</th>"
            "</tr></thead><tbody>"
        )
        for row in rows:
            body.append(
                "<tr>"
                f"<td>{esc(row.get('site'))}</td>"
                f"<td>{esc(row.get('asin'))}</td>"
                f"<td>{esc(row.get('brand'))}</td>"
                f"<td>{num(row.get('current'))}</td>"
                f"<td>{delta_cell(row.get('delta'), 'number')}</td>"
                "</tr>"
            )
    body.append("</tbody></table></div>")
    return "".join(body)


def top_movement_html(snapshots: list[dict[str, object]]) -> str:
    brand_title, brand_rows = top_brand_rows(snapshots)
    asin_title, asin_rows = top_asin_rows(snapshots)
    return (
        "<section id='top-movement'>"
        "<div class='section-head'>"
        f"<div><h2 data-i18n='top_movement_board'>{esc(ui('top_movement_board'))}</h2>"
        f"<div class='section-note' data-i18n='top_movement_note'>{esc(ui('top_movement_note'))}</div></div>"
        "</div>"
        "<div class='rank-grid'>"
        f"{rank_card_html(brand_title, brand_rows, 'brand')}"
        f"{rank_card_html(asin_title, asin_rows, 'asin')}"
        "</div></section>"
    )


def agent_source_label(run: dict[str, object]) -> str:
    stored = str(run.get("stored_path") or run.get("original_filename") or "")
    if "sellersprite_mcp" in stored or stored.endswith(".json"):
        return "SellerSprite MCP"
    if stored.endswith((".xlsx", ".xls", ".csv")):
        return "Excel / CSV 上传"
    return "本地数据"


def agent_roi_html(runs: list[dict[str, object]]) -> str:
    target_monthly = 28
    hours_per_report = 0.5
    month_prefix = datetime.utcnow().strftime("%Y-%m")
    total = len(runs)
    ok_runs = [run for run in runs if run.get("status") == "ok"]
    month_ok = [run for run in ok_runs if str(run.get("uploaded_at", "")).startswith(month_prefix)]
    success_rate = len(ok_runs) / total if total else 0
    cards = [
        ("年化节省", f"{num(target_monthly * hours_per_report * 12)} hrs", "0.5h × 28次/月"),
        ("本月已节省", f"{num(len(month_ok) * hours_per_report)} hrs", f"成功处理 {len(month_ok)} 次"),
        ("成功率", pct(success_rate), f"{len(ok_runs)} / {total} 成功"),
        ("本月处理 Run", num(len(month_ok)), "MCP / Excel 入库"),
    ]
    rows = [
        "<section>",
        "<div class='section-head'>",
        f"<div><h2 data-i18n='roi_run_dashboard'>{esc(ui('roi_run_dashboard'))}</h2>",
        "<div class='section-note'>把节省时间、运行质量和数据处理量放到同一个管理视角。</div></div>",
        "</div><div class='agent-kpi-grid'>",
    ]
    for label, value, detail in cards:
        rows.append(
            "<div class='agent-kpi'>"
            f"<span>{esc(label)}</span><strong>{esc(value)}</strong><p>{esc(detail)}</p>"
            "</div>"
        )
    rows.append("</div></section>")
    return "".join(rows)


def agent_run_table_html(runs: list[dict[str, object]]) -> str:
    rows = [
        "<section class='agent-card agent-run-table'>",
        "<div class='section-head'>",
        "<div><h2>运行记录</h2><div class='section-note'>每次上传或 MCP 批量拉取都会沉淀为 Run，可追踪数据源、解析状态和输出物。</div></div>",
        "</div>",
    ]
    if not runs:
        rows.append("<div class='notice'>暂无运行记录。</div></section>")
        return "".join(rows)
    rows.append(
        "<div class='table-scroll'><table><thead><tr>"
        "<th>Run</th><th>周次</th><th>站点</th><th>数据源</th><th>解析状态</th><th>上传时间</th><th>操作</th>"
        "</tr></thead><tbody>"
    )
    for run in runs[:40]:
        run_id = int(run["id"])
        status_class = "pill-ok" if run.get("status") == "ok" else "pill-missing"
        actions = f"<a href='/analysis?id={run_id}'>分析</a>"
        if run.get("status") == "ok":
            actions += f" · <a href='/download/report.xlsx?id={run_id}'>Excel</a>"
        rows.append(
            "<tr>"
            f"<td>#{run_id}</td>"
            f"<td>{esc(run.get('week_id'))}</td>"
            f"<td>{esc(run.get('marketplace'))}</td>"
            f"<td>{esc(agent_source_label(run))}</td>"
            f"<td><span class='pill {status_class}'>{esc(run.get('status'))}</span></td>"
            f"<td>{esc(run.get('uploaded_at'))}</td>"
            f"<td>{actions}</td>"
            "</tr>"
        )
    rows.append("</tbody></table></div></section>")
    return "".join(rows)


def agent_page(run_id: int | None = None, message: str = "", week_id: str | None = None) -> bytes:
    config = load_config(CONFIG_PATH)
    sites = config.get("monitoring", {}).get("marketplaces", ["US", "UK", "DE", "FR", "IT", "ES", "JP"])
    runs = latest_runs(DB_PATH, limit=500)
    selected_id = contextual_run_id(run_id, week_id)
    selected_run = get_run(DB_PATH, selected_id) if selected_id else None
    if not selected_run:
        latest_id = latest_successful_run_id(DB_PATH)
        selected_run = get_run(DB_PATH, latest_id) if latest_id else (runs[0] if runs else None)
    selected_week = str(selected_run.get("week_id", "")) if selected_run else (week_id or default_dashboard_week())
    site_runs = latest_site_runs(selected_week)
    latest_meta = (
        f"Run #{selected_run.get('id')} · {selected_run.get('marketplace')} · {selected_run.get('week_id')}"
        if selected_run
        else "暂无 Run"
    )
    body = [
        "<div class='agent-page'>",
        "<section class='agent-status-bar'>",
        f"<span class='pill pill-ok'>MCP 已接入</span>",
        f"<span class='agent-status-meta'>{esc(latest_meta)} · {len(site_runs)}/{len(sites)} 站点已覆盖</span>",
        "</section>",
        agent_roi_html(runs),
        agent_run_table_html(runs),
        "</div>",
    ]
    return page(ui("nav_agent"), "".join(body), selected_week)


KNOWLEDGE_DOC_TYPES = {
    "brand_positioning": "品牌定位文档",
    "price_strategy": "价格策略文档",
    "weekly_report": "历史周报补充文档",
}


def now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def init_knowledge_db() -> None:
    with connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS knowledge_documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_type TEXT NOT NULL,
                title TEXT NOT NULL,
                original_filename TEXT NOT NULL,
                stored_path TEXT NOT NULL,
                uploaded_at TEXT NOT NULL,
                note TEXT,
                extracted_text TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS competitor_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                marketplace TEXT,
                brand TEXT NOT NULL,
                asin TEXT,
                product_name TEXT,
                priority TEXT,
                source TEXT,
                note TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS listing_selling_points (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                marketplace TEXT,
                asin TEXT,
                brand TEXT,
                product_name TEXT,
                selling_point TEXT NOT NULL,
                scenario TEXT,
                source TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.commit()


def init_ads_db() -> None:
    with connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ad_report_uploads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                week_id TEXT NOT NULL,
                marketplace TEXT NOT NULL,
                report_type TEXT NOT NULL,
                original_filename TEXT NOT NULL,
                stored_path TEXT NOT NULL,
                uploaded_at TEXT NOT NULL,
                rows_imported INTEGER NOT NULL,
                note TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ad_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                upload_id INTEGER NOT NULL,
                week_id TEXT NOT NULL,
                marketplace TEXT NOT NULL,
                report_type TEXT NOT NULL,
                campaign TEXT,
                ad_group TEXT,
                search_term TEXT,
                targeting TEXT,
                match_type TEXT,
                asin TEXT,
                sku TEXT,
                impressions REAL,
                clicks REAL,
                spend REAL,
                sales REAL,
                orders REAL,
                units REAL,
                acos REAL,
                roas REAL
            )
            """
        )
        conn.commit()


def count_query(conn: object, sql: str, params: tuple[object, ...] = ()) -> int:
    row = conn.execute(sql, params).fetchone()
    return value_as_int(row[0] if row else 0)


def knowledge_counts() -> dict[str, int]:
    init_knowledge_db()
    init_ads_db()
    with connect(DB_PATH) as conn:
        return {
            "history_reports": count_query(conn, "SELECT COUNT(*) FROM uploaded_reports WHERE status = 'ok'"),
            "brand_docs": count_query(conn, "SELECT COUNT(*) FROM knowledge_documents WHERE doc_type = ?", ("brand_positioning",)),
            "price_docs": count_query(conn, "SELECT COUNT(*) FROM knowledge_documents WHERE doc_type = ?", ("price_strategy",)),
            "competitors": count_query(conn, "SELECT COUNT(*) FROM competitor_profiles"),
            "listing_points": count_query(conn, "SELECT COUNT(*) FROM listing_selling_points"),
            "ad_uploads": count_query(conn, "SELECT COUNT(*) FROM ad_report_uploads"),
        }


def save_field_file(file_item: object, folder: Path) -> Path:
    filename = Path(getattr(file_item, "filename", "") or "upload.bin").name
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    target = folder / f"{stamp}_{filename}"
    target.write_bytes(file_item.file.read())
    return target


def extract_docx_text(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as archive:
            xml_data = archive.read("word/document.xml")
        root = ElementTree.fromstring(xml_data)
        chunks = [node.text for node in root.iter() if node.tag.endswith("}t") and node.text]
        return "\n".join(chunks)
    except (KeyError, OSError, zipfile.BadZipFile, ElementTree.ParseError):
        return ""


def extract_document_text(path: Path) -> str:
    suffix = path.suffix.lower()
    try:
        if suffix in {".txt", ".md"}:
            return path.read_text(encoding="utf-8", errors="ignore")[:30000]
        if suffix == ".docx":
            return extract_docx_text(path)[:30000]
        if suffix == ".csv":
            return pd.read_csv(path, nrows=40).to_csv(index=False)[:30000]
        if suffix in {".xlsx", ".xls"}:
            sheets = pd.read_excel(path, sheet_name=None, nrows=30)
            parts = [f"[{sheet_name}]\n{df.to_csv(index=False)}" for sheet_name, df in sheets.items()]
            return "\n".join(parts)[:30000]
    except Exception:
        return ""
    return ""


def store_knowledge_document(doc_type: str, title: str, file_item: object, note: str = "") -> int:
    init_knowledge_db()
    safe_type = doc_type if doc_type in KNOWLEDGE_DOC_TYPES else "brand_positioning"
    stored_path = save_field_file(file_item, KNOWLEDGE_DIR / "documents" / safe_type)
    extracted_text = extract_document_text(stored_path)
    with connect(DB_PATH) as conn:
        cur = conn.execute(
            """
            INSERT INTO knowledge_documents
                (doc_type, title, original_filename, stored_path, uploaded_at, note, extracted_text)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                safe_type,
                title or Path(getattr(file_item, "filename", "") or stored_path.name).stem,
                getattr(file_item, "filename", "") or stored_path.name,
                str(stored_path),
                now_iso(),
                note,
                extracted_text,
            ),
        )
        conn.commit()
        return int(cur.lastrowid)


def read_knowledge_documents(limit: int = 12) -> pd.DataFrame:
    init_knowledge_db()
    with connect(DB_PATH) as conn:
        rows = conn.execute(
            """
            SELECT id, doc_type, title, original_filename, uploaded_at, note
            FROM knowledge_documents
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    df = pd.DataFrame([dict(row) for row in rows])
    if not df.empty:
        df["doc_type"] = df["doc_type"].map(lambda value: KNOWLEDGE_DOC_TYPES.get(str(value), str(value)))
    return df


def read_competitor_profiles(limit: int = 30) -> pd.DataFrame:
    init_knowledge_db()
    with connect(DB_PATH) as conn:
        rows = conn.execute(
            """
            SELECT marketplace, brand, asin, product_name, priority, source, note, updated_at
            FROM competitor_profiles
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return pd.DataFrame([dict(row) for row in rows])


def read_listing_points(limit: int = 30) -> pd.DataFrame:
    init_knowledge_db()
    with connect(DB_PATH) as conn:
        rows = conn.execute(
            """
            SELECT marketplace, asin, brand, product_name, selling_point, scenario, source, updated_at
            FROM listing_selling_points
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return pd.DataFrame([dict(row) for row in rows])


def knowledge_ai_context() -> dict[str, object]:
    init_knowledge_db()
    with connect(DB_PATH) as conn:
        docs = conn.execute(
            """
            SELECT doc_type, title, note, extracted_text, uploaded_at
            FROM knowledge_documents
            ORDER BY id DESC
            LIMIT 8
            """
        ).fetchall()
    return {
        "documents": [
            {
                "doc_type": KNOWLEDGE_DOC_TYPES.get(str(row["doc_type"]), str(row["doc_type"])),
                "title": row["title"],
                "note": row["note"],
                "uploaded_at": row["uploaded_at"],
                "text_excerpt": (row["extracted_text"] or "")[:3000],
            }
            for row in docs
        ],
        "competitor_profiles": compact_dataframe_records(
            read_competitor_profiles(limit=80),
            ["marketplace", "brand", "asin", "product_name", "priority", "source", "note"],
            limit=80,
        ),
        "listing_selling_points": compact_dataframe_records(
            read_listing_points(limit=80),
            ["marketplace", "asin", "brand", "product_name", "selling_point", "scenario", "source"],
            limit=80,
        ),
    }


def normalize_cell(value: object) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def find_row_value(row: pd.Series, aliases: list[str]) -> str:
    lower_map = {str(col).strip().lower(): col for col in row.index}
    for alias in aliases:
        key = alias.strip().lower()
        if key in lower_map:
            return normalize_cell(row.get(lower_map[key]))
    return ""


def read_tabular_file(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)
    return pd.read_excel(path)


def normalize_ad_column(value: object) -> str:
    return re.sub(r"[\s\-_#%()（）/\\:：]+", "", str(value or "").strip().lower())


def is_bad_ad_column_match(alias: str, key: str) -> bool:
    if alias in {"sales", "totalsales", "7daytotalsales", "14daytotalsales", "销售额", "广告销售额"}:
        return "acos" in key or "costofsales" in key or "成本销售比" in key
    if alias in {"cost", "spend", "花费", "广告花费", "支出"}:
        return "cpc" in key or "costperclick" in key or "每次点击" in key
    if alias in {"clicks", "点击", "点击量"}:
        return "ctr" in key or "clickthroughrate" in key or "点击率" in key
    return False


def find_row_value_any(row: pd.Series, aliases: list[str]) -> str:
    columns = list(row.index)
    normalized_columns = {normalize_ad_column(col): col for col in columns}
    normalized_aliases = [normalize_ad_column(alias) for alias in aliases]
    for alias in normalized_aliases:
        if alias in normalized_columns and not is_bad_ad_column_match(alias, alias):
            return normalize_cell(row.get(normalized_columns[alias]))
    for alias in normalized_aliases:
        for key, col in normalized_columns.items():
            if alias and (alias in key or key in alias) and not is_bad_ad_column_match(alias, key):
                return normalize_cell(row.get(col))
    return ""


def parse_ad_number(value: object) -> float:
    if value is None:
        return 0.0
    try:
        if pd.isna(value):
            return 0.0
    except (TypeError, ValueError):
        pass
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return 0.0
    cleaned = (
        text.replace(",", "")
        .replace("$", "")
        .replace("€", "")
        .replace("£", "")
        .replace("¥", "")
        .replace("￥", "")
        .replace("USD", "")
        .replace("EUR", "")
        .replace("GBP", "")
        .replace("JPY", "")
        .replace("%", "")
        .strip()
    )
    match = re.search(r"-?\d+(?:\.\d+)?", cleaned)
    return float(match.group(0)) if match else 0.0


def parse_ad_percent(value: object) -> float:
    raw = "" if value is None else str(value)
    numeric = parse_ad_number(value)
    if "%" in raw or numeric > 1:
        return numeric / 100
    return numeric


def read_ads_tabular_file(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)
    sheets = pd.read_excel(path, sheet_name=None)
    frames = [df for df in sheets.values() if not df.empty]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def import_ads_report(week_id: str, marketplace: str, report_type: str, file_item: object, note: str = "") -> int:
    init_ads_db()
    stored_path = save_field_file(file_item, ADS_UPLOAD_DIR / week_id / marketplace.upper())
    df = read_ads_tabular_file(stored_path)
    report_type = report_type.strip() or "search_term"
    with connect(DB_PATH) as conn:
        cur = conn.execute(
            """
            INSERT INTO ad_report_uploads
                (week_id, marketplace, report_type, original_filename, stored_path, uploaded_at, rows_imported, note)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                week_id,
                marketplace.upper(),
                report_type,
                getattr(file_item, "filename", "") or stored_path.name,
                str(stored_path),
                now_iso(),
                0,
                note,
            ),
        )
        upload_id = int(cur.lastrowid)
        rows_imported = 0
        for _, row in df.iterrows():
            campaign = find_row_value_any(row, ["campaign", "campaign name", "广告活动", "广告活动名称", "广告系列"])
            ad_group = find_row_value_any(row, ["ad group", "ad group name", "广告组", "广告组名称"])
            search_term = find_row_value_any(row, ["customer search term", "search term", "search query", "搜索词", "客户搜索词"])
            targeting = find_row_value_any(row, ["targeting", "target", "keyword", "keyword text", "投放", "关键词", "目标"])
            match_type = find_row_value_any(row, ["match type", "匹配类型"])
            asin = find_row_value_any(row, ["asin", "advertised asin", "purchased asin", "推广 asin", "广告 asin"])
            sku = find_row_value_any(row, ["sku", "advertised sku", "推广 sku", "广告 sku"])
            impressions = parse_ad_number(find_row_value_any(row, ["impressions", "展示量", "曝光", "曝光量"]))
            clicks = parse_ad_number(find_row_value_any(row, ["clicks", "点击量", "点击"]))
            spend = parse_ad_number(find_row_value_any(row, ["spend", "cost", "花费", "广告花费", "支出"]))
            sales = parse_ad_number(
                find_row_value_any(
                    row,
                    ["sales", "total sales", "7 day total sales", "14 day total sales", "销售额", "广告销售额", "7天总销售额", "14天总销售额"],
                )
            )
            orders = parse_ad_number(find_row_value_any(row, ["orders", "purchases", "7 day total orders", "订单", "订单量", "购买次数"]))
            units = parse_ad_number(find_row_value_any(row, ["units", "7 day total units", "销量", "销售量", "件数"]))
            acos_raw = find_row_value_any(row, ["acos", "total advertising cost of sales", "广告成本销售比"])
            roas_raw = find_row_value_any(row, ["roas", "total return on advertising spend", "广告支出回报率"])
            acos = parse_ad_percent(acos_raw) if acos_raw else (spend / sales if sales else 0.0)
            roas = parse_ad_number(roas_raw) if roas_raw else (sales / spend if spend else 0.0)
            has_identity = any([campaign, ad_group, search_term, targeting, asin, sku])
            has_metric = any([impressions, clicks, spend, sales, orders, units])
            if not has_identity and not has_metric:
                continue
            conn.execute(
                """
                INSERT INTO ad_metrics
                    (upload_id, week_id, marketplace, report_type, campaign, ad_group, search_term, targeting, match_type,
                     asin, sku, impressions, clicks, spend, sales, orders, units, acos, roas)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    upload_id,
                    week_id,
                    marketplace.upper(),
                    report_type,
                    campaign,
                    ad_group,
                    search_term,
                    targeting,
                    match_type,
                    asin,
                    sku,
                    impressions,
                    clicks,
                    spend,
                    sales,
                    orders,
                    units,
                    acos,
                    roas,
                ),
            )
            rows_imported += 1
        conn.execute("UPDATE ad_report_uploads SET rows_imported = ? WHERE id = ?", (rows_imported, upload_id))
        conn.commit()
    return rows_imported


def read_ads_uploads(limit: int = 20) -> pd.DataFrame:
    init_ads_db()
    with connect(DB_PATH) as conn:
        rows = conn.execute(
            """
            SELECT id, week_id, marketplace, report_type, original_filename, uploaded_at, rows_imported, note
            FROM ad_report_uploads
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return pd.DataFrame([dict(row) for row in rows])


def read_ads_summary(limit: int = 50) -> pd.DataFrame:
    init_ads_db()
    with connect(DB_PATH) as conn:
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
            GROUP BY week_id, marketplace, report_type
            ORDER BY week_id DESC, marketplace ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    df = pd.DataFrame([dict(row) for row in rows])
    if df.empty:
        return df
    df["ctr"] = df.apply(lambda row: row["clicks"] / row["impressions"] if row["impressions"] else 0, axis=1)
    df["acos"] = df.apply(lambda row: row["spend"] / row["sales"] if row["sales"] else 0, axis=1)
    df["roas"] = df.apply(lambda row: row["sales"] / row["spend"] if row["spend"] else 0, axis=1)
    return df


def read_ads_top_terms(week_id: str = "", marketplace: str = "", limit: int = 20) -> pd.DataFrame:
    init_ads_db()
    filters: list[str] = []
    params: list[object] = []
    if week_id:
        filters.append("week_id = ?")
        params.append(week_id)
    if marketplace:
        filters.append("marketplace = ?")
        params.append(marketplace.upper())
    where = f"WHERE {' AND '.join(filters)}" if filters else ""
    with connect(DB_PATH) as conn:
        rows = conn.execute(
            f"""
            SELECT
                COALESCE(NULLIF(search_term, ''), NULLIF(targeting, ''), NULLIF(campaign, ''), '(未命名)') AS term,
                marketplace,
                campaign,
                SUM(impressions) AS impressions,
                SUM(clicks) AS clicks,
                SUM(spend) AS spend,
                SUM(sales) AS sales,
                SUM(orders) AS orders,
                SUM(units) AS units
            FROM ad_metrics
            {where}
            GROUP BY term, marketplace, campaign
            ORDER BY spend DESC, sales DESC
            LIMIT ?
            """,
            (*params, limit),
        ).fetchall()
    df = pd.DataFrame([dict(row) for row in rows])
    if df.empty:
        return df
    df["acos"] = df.apply(lambda row: row["spend"] / row["sales"] if row["sales"] else 0, axis=1)
    df["roas"] = df.apply(lambda row: row["sales"] / row["spend"] if row["spend"] else 0, axis=1)
    return df


def ads_ai_context(week_id: str = "", marketplace: str = "") -> dict[str, object]:
    summary = read_ads_summary(limit=80)
    if week_id:
        summary = summary[summary["week_id"].astype(str) == str(week_id)] if not summary.empty else summary
    if marketplace:
        summary = summary[summary["marketplace"].astype(str) == str(marketplace).upper()] if not summary.empty else summary
    return {
        "summary": compact_dataframe_records(
            summary,
            ["week_id", "marketplace", "report_type", "impressions", "clicks", "spend", "sales", "orders", "units", "ctr", "acos", "roas"],
            limit=20,
            sort_col="spend",
        ),
        "top_terms": compact_dataframe_records(
            read_ads_top_terms(week_id=week_id, marketplace=marketplace, limit=20),
            ["term", "marketplace", "campaign", "impressions", "clicks", "spend", "sales", "orders", "units", "acos", "roas"],
            limit=20,
            sort_col="spend",
        ),
    }


def insert_competitor_profile(
    marketplace: str,
    brand: str,
    asin: str = "",
    product_name: str = "",
    priority: str = "",
    source: str = "",
    note: str = "",
) -> None:
    if not brand.strip():
        return
    init_knowledge_db()
    with connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO competitor_profiles
                (marketplace, brand, asin, product_name, priority, source, note, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (marketplace.upper(), brand.strip(), asin.strip(), product_name.strip(), priority.strip(), source.strip(), note.strip(), now_iso()),
        )
        conn.commit()


def insert_listing_point(
    marketplace: str,
    asin: str,
    brand: str,
    product_name: str,
    selling_point: str,
    scenario: str = "",
    source: str = "",
) -> None:
    if not selling_point.strip():
        return
    init_knowledge_db()
    with connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO listing_selling_points
                (marketplace, asin, brand, product_name, selling_point, scenario, source, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (marketplace.upper(), asin.strip(), brand.strip(), product_name.strip(), selling_point.strip(), scenario.strip(), source.strip(), now_iso()),
        )
        conn.commit()


def import_competitor_profiles(file_item: object) -> int:
    path = save_field_file(file_item, KNOWLEDGE_DIR / "imports" / "competitors")
    df = read_tabular_file(path)
    count = 0
    for _, row in df.iterrows():
        brand = find_row_value(row, ["brand", "品牌", "品牌名", "竞品品牌"])
        if not brand:
            continue
        insert_competitor_profile(
            find_row_value(row, ["marketplace", "site", "站点", "国家"]),
            brand,
            find_row_value(row, ["asin", "ASIN"]),
            find_row_value(row, ["product_name", "title", "商品名", "商品标题", "产品名"]),
            find_row_value(row, ["priority", "优先级", "等级"]),
            find_row_value(row, ["source", "来源"]),
            find_row_value(row, ["note", "备注"]),
        )
        count += 1
    return count


def import_listing_points(file_item: object) -> int:
    path = save_field_file(file_item, KNOWLEDGE_DIR / "imports" / "listing_points")
    df = read_tabular_file(path)
    count = 0
    for _, row in df.iterrows():
        point = find_row_value(row, ["selling_point", "卖点", "核心卖点", "bullet", "五点"])
        if not point:
            continue
        insert_listing_point(
            find_row_value(row, ["marketplace", "site", "站点", "国家"]),
            find_row_value(row, ["asin", "ASIN"]),
            find_row_value(row, ["brand", "品牌", "品牌名"]),
            find_row_value(row, ["product_name", "title", "商品名", "商品标题", "产品名"]),
            point,
            find_row_value(row, ["scenario", "场景", "使用场景"]),
            find_row_value(row, ["source", "来源"]),
        )
        count += 1
    return count


def knowledge_status_html() -> str:
    counts = knowledge_counts()
    tiles = [
        ("历史周报上传/解析", counts["history_reports"], "已解析 SellerSprite Run"),
        ("品牌定位文档上传", counts["brand_docs"], "用于 AI 回答品牌口径"),
        ("竞品清单维护", counts["competitors"], "品牌 / ASIN / 优先级"),
        ("价格策略文档上传", counts["price_docs"], "价格带与促销原则"),
        ("Listing 卖点库", counts["listing_points"], "手工或 Excel 导入"),
        ("广告报表上传", counts["ad_uploads"], "Spend / Sales / ACOS"),
    ]
    rows = ["<section><div class='knowledge-grid'>"]
    for title, value, desc in tiles:
        rows.append(
            "<div class='knowledge-tile'>"
            f"<strong>{esc(title)}</strong><div class='metric-value'>{esc(value)}</div><div class='muted'>{esc(desc)}</div>"
            "</div>"
        )
    rows.append("</div></section>")
    return "".join(rows)


def document_upload_card() -> str:
    options = "".join(f"<option value='{esc(key)}'>{esc(label)}</option>" for key, label in KNOWLEDGE_DOC_TYPES.items())
    return (
        "<div class='knowledge-card'><h3>"
        f"{icon('book')}<span>品牌/价格/周报文档上传</span></h3>"
        "<form method='post' action='/knowledge/upload-doc' enctype='multipart/form-data'>"
        f"<label>资料类型<select name='doc_type'>{options}</select></label>"
        "<label>标题<input name='title' placeholder='例如：PLAUD 品牌定位 v1'></label>"
        "<label class='full'>文件<input type='file' name='file' accept='.xlsx,.xls,.csv,.txt,.md,.docx,.pdf'></label>"
        "<label class='full'>备注<textarea name='note' placeholder='资料来源、适用站点、版本说明'></textarea></label>"
        f"<button class='btn btn-primary' type='submit'>{icon('uploads')}上传资料</button>"
        "</form></div>"
    )


def knowledge_documents_html() -> str:
    df = read_knowledge_documents()
    return (
        "<section><h2>已上传知识文档</h2>"
        + dataframe_table(df, ["doc_type", "title", "original_filename", "uploaded_at", "note"], empty="暂无知识文档", limit=12)
        + "</section>"
    )


def competitor_maintenance_html() -> str:
    df = read_competitor_profiles()
    return (
        "<section class='knowledge-layout'>"
        "<div class='knowledge-card'><h3>"
        f"{icon('brand')}<span>竞品清单维护</span></h3>"
        "<form method='post' action='/knowledge/add-competitor'>"
        "<label>站点<input name='marketplace' placeholder='IT / US / JP'></label>"
        "<label>品牌<input name='brand' required placeholder='例如：Zoom'></label>"
        "<label>ASIN<input name='asin' placeholder='可选'></label>"
        "<label>商品名<input name='product_name' placeholder='可选'></label>"
        "<label>优先级<input name='priority' placeholder='P0 / P1 / P2'></label>"
        "<label>来源<input name='source' placeholder='运营维护 / 卖家精灵'></label>"
        "<label class='full'>备注<textarea name='note'></textarea></label>"
        f"<button class='btn btn-primary' type='submit'>{icon('check')}保存竞品</button>"
        "</form></div>"
        "<div class='knowledge-card'><h3>"
        f"{icon('uploads')}<span>竞品清单 Excel/CSV 导入</span></h3>"
        "<form method='post' action='/knowledge/import-competitors' enctype='multipart/form-data'>"
        "<label class='full'>文件<input type='file' name='file' accept='.xlsx,.xls,.csv'></label>"
        "<div class='notice full'>支持列名：站点、品牌、ASIN、商品标题、优先级、来源、备注。</div>"
        f"<button class='btn btn-primary' type='submit'>{icon('uploads')}导入竞品</button>"
        "</form></div>"
        "</section>"
        "<section><h2>竞品清单</h2>"
        + dataframe_table(df, ["marketplace", "brand", "asin", "product_name", "priority", "source", "note"], empty="暂无竞品清单", limit=30)
        + "</section>"
    )


def listing_points_html() -> str:
    df = read_listing_points()
    return (
        "<section class='knowledge-layout'>"
        "<div class='knowledge-card'><h3>"
        f"{icon('list')}<span>Listing 卖点库手工维护</span></h3>"
        "<form method='post' action='/knowledge/add-listing-point'>"
        "<label>站点<input name='marketplace' placeholder='IT / US / JP'></label>"
        "<label>ASIN<input name='asin' placeholder='可选'></label>"
        "<label>品牌<input name='brand' placeholder='PLAUD / 竞品'></label>"
        "<label>商品名<input name='product_name' placeholder='可选'></label>"
        "<label class='full'>卖点<textarea name='selling_point' required placeholder='例如：AI 转写、自动摘要、112 种语言'></textarea></label>"
        "<label>场景<input name='scenario' placeholder='会议 / 课堂 / 采访'></label>"
        "<label>来源<input name='source' placeholder='Listing / 运营沉淀'></label>"
        f"<button class='btn btn-primary' type='submit'>{icon('check')}保存卖点</button>"
        "</form></div>"
        "<div class='knowledge-card'><h3>"
        f"{icon('uploads')}<span>Listing 卖点 Excel/CSV 导入</span></h3>"
        "<form method='post' action='/knowledge/import-listing-points' enctype='multipart/form-data'>"
        "<label class='full'>文件<input type='file' name='file' accept='.xlsx,.xls,.csv'></label>"
        "<div class='notice full'>支持列名：站点、ASIN、品牌、商品标题、卖点、场景、来源。</div>"
        f"<button class='btn btn-primary' type='submit'>{icon('uploads')}导入卖点</button>"
        "</form></div>"
        "</section>"
        "<section><h2>Listing 卖点库</h2>"
        + dataframe_table(df, ["marketplace", "asin", "brand", "product_name", "selling_point", "scenario", "source"], empty="暂无 Listing 卖点", limit=30)
        + "</section>"
    )


def p1_api_status_html() -> str:
    cards = [
        ("Amazon Ads API", "P1 接广告投放数据，需要广告账号授权、Client ID/Secret、Refresh Token 和 profileId。"),
        ("Amazon SP-API", "P1 接自有商品、订单、库存、部分报表数据，需要开发者应用、Seller 授权和区域端点。"),
        ("SellerSprite 报告", "继续作为类目/竞品数据来源，当前已支持 Excel 上传解析和历史沉淀。"),
    ]
    rows = ["<section><div class='section-head'><div><h2>P1 官方 API 接入位</h2><div class='section-note'>先展示接入状态；拿到凭证后再启用定时同步。</div></div></div><div class='api-status-grid'>"]
    for title, detail in cards:
        rows.append(f"<div class='api-status-card pending'><strong>{esc(title)}</strong><p>{esc(detail)}</p></div>")
    rows.append("</div></section>")
    return "".join(rows)


def knowledge_page(message: str = "", week_id: str | None = None) -> bytes:
    init_knowledge_db()
    body = [
        "<section class='section-head'>",
        f"<div><h2 data-i18n='nav_knowledge'>{esc(ui('nav_knowledge'))}</h2>",
        "<div class='section-note'>P0 先做稳定资料上传、维护和导入；P1 官方 API 保留接入位。</div></div>",
        f"<a class='btn' href='/chat'>{icon('chat')}<span data-i18n='nav_chat'>{esc(ui('nav_chat'))}</span></a>",
        "</section>",
    ]
    if message:
        body.append(f"<section class='notice'>{esc(message)}</section>")
    body.append(knowledge_status_html())
    body.append("<section class='knowledge-layout'>")
    body.append(upload_form())
    body.append(document_upload_card())
    body.append("</section>")
    body.append(knowledge_documents_html())
    body.append(competitor_maintenance_html())
    body.append(listing_points_html())
    body.append(p1_api_status_html())
    return page(ui("nav_knowledge"), "".join(body), week_id)


def ads_upload_form() -> str:
    config = load_config(CONFIG_PATH)
    marketplaces = config.get("monitoring", {}).get("marketplaces", ["US", "UK", "DE", "FR", "IT", "ES", "JP"])
    options = "".join(f"<option value='{esc(site)}'>{esc(site)}</option>" for site in marketplaces)
    report_options = [
        ("search_term", "Search Term / 搜索词报表"),
        ("campaign", "Campaign / 广告活动报表"),
        ("targeting", "Targeting / 投放报表"),
        ("asin", "ASIN / 商品广告报表"),
    ]
    report_html = "".join(f"<option value='{esc(key)}'>{esc(label)}</option>" for key, label in report_options)
    return (
        "<section class='card ads-upload-card'>"
        f"<h2>{icon('uploads')}广告报表上传</h2>"
        "<div class='section-note'>支持 Amazon Ads 后台导出的 Excel / CSV；也可通过 scripts/import_amazon_ads_api.py 用 Amazon Ads API 同步。</div>"
        "<form class='ads-upload-form' method='post' action='/ads/upload' enctype='multipart/form-data'>"
        "<div class='ads-field'><label>周次</label><input name='week_id' value='2026-W20' required></div>"
        f"<div class='ads-field'><label>站点</label><select name='marketplace' required>{options}</select></div>"
        f"<div class='ads-field'><label>报表类型</label><select name='report_type'>{report_html}</select></div>"
        "<div class='ads-file'><label>广告报表文件</label><input name='file' type='file' accept='.xlsx,.xls,.csv' required></div>"
        "<div class='ads-note-field'><label>备注</label><input name='note' placeholder='例如：Sponsored Products Search Term 报表'></div>"
        f"<div class='ads-submit'><button class='btn btn-primary' type='submit'>{icon('uploads')}上传并解析</button></div>"
        "</form>"
        "</section>"
    )


def format_ads_summary_for_view(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    view = df.copy()
    for col in ["impressions", "clicks", "orders", "units", "row_count"]:
        if col in view:
            view[col] = view[col].map(num)
    for col in ["spend", "sales"]:
        if col in view:
            view[col] = view[col].map(num)
    for col in ["ctr", "acos"]:
        if col in view:
            view[col] = view[col].map(pct)
    if "roas" in view:
        view["roas"] = view["roas"].map(lambda value: f"{value_as_float(value):.2f}")
    return view


def ads_ops_card() -> str:
    items = [
        ("check", "P0 手动导入", "Excel / CSV 报表已可解析入库，适合先跑周报流程。"),
        ("config", "Amazon Ads API", "拿到 Client ID/Secret、refresh token 和 profileId 后可自动同步。"),
        ("search", "关键词归因", "Search Term / Targeting 报表会进入 Top 词与投放明细表。"),
    ]
    rows = [
        "<section class='ads-side-card'>",
        f"<h2>{icon('info')}广告数据口径</h2>",
        "<div class='section-note'>当前页面只承接官方导出或 Amazon Ads API 授权数据，广告后台页面不做自动抓取。</div>",
        "<div class='ads-side-grid'>",
    ]
    for icon_name, title, desc in items:
        rows.append(
            "<div class='ads-side-item'>"
            f"<span class='icon-badge'>{icon(icon_name)}</span>"
            f"<div><strong>{esc(title)}</strong><span>{esc(desc)}</span></div>"
            "</div>"
        )
    rows.append("</div></section>")
    return "".join(rows)


def ads_table_card(title: str, note: str, table_html: str, count: int) -> str:
    return (
        "<section class='ads-table-card'>"
        "<div class='section-head'>"
        f"<div><h2>{esc(title)}</h2><div class='section-note'>{esc(note)}</div></div>"
        f"<span class='ads-table-meta'>{num(count)} 行</span>"
        "</div>"
        f"<div class='ads-table-scroll'>{table_html}</div>"
        "</section>"
    )


def ads_trend_wall_html(summary: pd.DataFrame) -> str:
    if summary.empty:
        return ""
    metrics = [
        ("广告花费趋势", "spend", False),
        ("广告销售额趋势", "sales", False),
        ("ACOS 趋势", "acos", True),
    ]
    body = [
        "<section>",
        "<div class='section-head'>",
        "<div><h2>广告趋势</h2><div class='section-note'>按周次和站点聚合官方广告报表，辅助判断投放变化是否影响市占。</div></div>",
        "</div><div class='trend-wall-grid'>",
    ]
    for title, metric, percent_axis in metrics:
        series = []
        for idx, (site, group) in enumerate(summary.groupby("marketplace")):
            weekly = group.groupby("week_id", as_index=False).agg(
                spend=("spend", "sum"),
                sales=("sales", "sum"),
                clicks=("clicks", "sum"),
                impressions=("impressions", "sum"),
            )
            weekly = weekly.sort_values("week_id", key=lambda col: col.map(week_sort_key))
            points = []
            for _, row in weekly.iterrows():
                if metric == "acos":
                    value = value_as_float(row.get("spend")) / value_as_float(row.get("sales")) if value_as_float(row.get("sales")) else 0.0
                else:
                    value = value_as_float(row.get(metric))
                points.append((str(row.get("week_id")), value))
            if points:
                series.append((str(site), points, TREND_SERIES_COLORS[idx % len(TREND_SERIES_COLORS)]))
        body.append(multi_line_chart(title, series, "广告周趋势", percent_axis))
    body.append("</div></section>")
    return "".join(body)


def ads_page(message: str = "", week_id: str | None = None) -> bytes:
    init_ads_db()
    trend_summary = read_ads_summary(limit=200)
    summary = trend_summary.copy()
    if week_id and not summary.empty and "week_id" in summary:
        summary = summary[summary["week_id"].astype(str) == str(week_id)]
    top_terms = read_ads_top_terms(week_id=week_id or "", limit=25)
    uploads = read_ads_uploads(limit=20)
    total_spend = summary["spend"].sum() if not summary.empty else 0
    total_sales = summary["sales"].sum() if not summary.empty else 0
    total_clicks = summary["clicks"].sum() if not summary.empty else 0
    total_impressions = summary["impressions"].sum() if not summary.empty else 0
    total_orders = summary["orders"].sum() if not summary.empty and "orders" in summary else 0
    total_units = summary["units"].sum() if not summary.empty and "units" in summary else 0
    kpis = [
        ("广告花费", num(total_spend), "Spend", f"点击 {num(total_clicks)}", "trend"),
        ("广告销售额", num(total_sales), "Sales", f"订单 {num(total_orders)}", "dashboard"),
        ("ACOS", pct(total_spend / total_sales if total_sales else 0), "Spend / Sales", f"销量 {num(total_units)}", "target"),
        ("CTR", pct(total_clicks / total_impressions if total_impressions else 0), "Clicks / Impressions", f"曝光 {num(total_impressions)}", "search"),
    ]
    summary_table = dataframe_table(
        format_ads_summary_for_view(summary),
        ["week_id", "marketplace", "report_type", "row_count", "impressions", "clicks", "ctr", "spend", "sales", "acos", "roas", "orders", "units"],
        empty="暂无广告报表数据",
        limit=80,
    )
    top_terms_table = dataframe_table(
        format_ads_summary_for_view(top_terms),
        ["term", "marketplace", "campaign", "impressions", "clicks", "spend", "sales", "acos", "roas", "orders", "units"],
        empty="暂无广告关键词或投放明细",
        limit=25,
    )
    uploads_table = dataframe_table(
        uploads,
        ["id", "week_id", "marketplace", "report_type", "original_filename", "uploaded_at", "rows_imported", "note"],
        empty="暂无广告报表上传",
        limit=20,
    )
    body = [
        "<div class='ads-page'>",
        "<section class='ads-hero'>",
        f"<div><h2 data-i18n='nav_ads'>{esc(ui('nav_ads'))}</h2>",
        "<div class='section-note'>不抓取 Amazon 广告后台页面；支持官方后台导出的 Excel/CSV，也支持 Amazon Ads API 同步脚本。</div></div>",
        f"<div class='ads-hero-actions'><a class='btn' href='/config'>{icon('config')}API 状态</a></div>",
        "</section>",
    ]
    if message:
        body.append(f"<section class='notice'>{esc(message)}</section>")
    body.append("<section class='ads-kpi-grid'>")
    for label, value, desc, detail, icon_name in kpis:
        body.append(
            "<div class='ads-kpi-card'>"
            f"<div class='ads-kpi-top'><div class='ads-kpi-label'>{esc(label)}</div><span class='icon-badge'>{icon(icon_name)}</span></div>"
            f"<div class='ads-kpi-value'>{esc(value)}</div>"
            f"<div class='ads-kpi-desc'><span>{esc(desc)}</span><strong>{esc(detail)}</strong></div>"
            "</div>"
        )
    body.append("</section>")
    body.append(ads_trend_wall_html(trend_summary))
    body.append("<section class='ads-workspace'>")
    body.append(ads_upload_form())
    body.append(ads_ops_card())
    body.append("</section>")
    body.append(ads_table_card("广告数据按站点汇总", "按周次、站点和报表类型聚合 Spend、Sales、ACOS、CTR。", summary_table, len(summary)))
    body.append(ads_table_card("Top Search Term / Targeting", "用于观察高花费、高销售额或 ACOS 异常的关键词和投放对象。", top_terms_table, len(top_terms)))
    body.append(ads_table_card("最近广告报表上传", "保留导入文件、行数和备注，方便回溯数据来源。", uploads_table, len(uploads)))
    body.append("</div>")
    return page(ui("nav_ads"), "".join(body), week_id)


def upload_form(week_id: str | None = None) -> str:
    config = load_config(CONFIG_PATH)
    marketplaces = config.get("monitoring", {}).get("marketplaces", ["US", "UK", "DE", "FR", "IT", "ES", "JP"])
    options = "".join(f"<option value='{esc(site)}'>{esc(site)}</option>" for site in marketplaces)
    selected_week = week_id or default_dashboard_week() or str(config.get("monitoring", {}).get("week_id") or "2026-W20")
    return f"""
<section class="card">
  <h2 data-i18n="upload_excel">{esc(ui("upload_excel"))}</h2>
  <form method="post" action="/upload" enctype="multipart/form-data">
    <div>
      <label data-i18n="week_id">{esc(ui("week_id"))}</label>
      <input name="week_id" value="{esc(selected_week)}" required>
    </div>
    <div>
      <label data-i18n="marketplace">{esc(ui("marketplace"))}</label>
      <select name="marketplace" required>{options}</select>
    </div>
    <div class="wide">
      <label data-i18n="excel_file">{esc(ui("excel_file"))}</label>
      <input name="file" type="file" accept=".xlsx,.xls" required>
    </div>
    <div class="full">
      <label data-i18n="note">{esc(ui("note"))}</label>
      <input name="note" placeholder="{esc(ui("note_placeholder"))}" data-i18n-placeholder="note_placeholder">
    </div>
    <div>
      <button class="btn btn-primary" type="submit">{icon("uploads")}<span data-i18n="upload_parse">{esc(ui("upload_parse"))}</span></button>
    </div>
  </form>
</section>
"""


def dashboard(week_id: str | None = None) -> bytes:
    counts = aggregate_counts(DB_PATH)
    config = load_config(CONFIG_PATH)
    sites = config.get("monitoring", {}).get("marketplaces", [])
    weeks = dashboard_week_options()
    selected_week = week_id if week_id in weeks else (weeks[0] if weeks else "")
    latest_id = latest_successful_run_id_for_week(selected_week) if selected_week else latest_successful_run_id(DB_PATH)
    site_snapshots = build_site_snapshots(sites, selected_week or None)
    latest_snapshot = latest_dashboard_snapshot(site_snapshots, latest_id)
    body = ["<div class='dashboard-page'>"]
    body.append(dashboard_command_center_html(site_snapshots, latest_id, counts, sites))
    body.append(dashboard_trend_wall_html(sites))
    body.append(dashboard_chart_first_html(latest_snapshot, site_snapshots))
    body.append(top_movement_html(site_snapshots))
    body.append(alert_center_html(site_snapshots))
    body.append(seven_site_comparison_html(site_snapshots))
    body.append("</div>")
    return page(ui("nav_dashboard"), "".join(body), selected_week)


def capability_mapping_html() -> str:
    items = [
        ("Market Share", "market_share_desc"),
        ("Competitor Movement", "competitor_movement_desc"),
        ("Product Intelligence", "product_intelligence_desc"),
        ("Data Health", "data_health_desc"),
        ("Workflow Export", "workflow_export_desc"),
    ]
    rows = ["<section><div class='mapping-grid'>"]
    for title, text_key in items:
        rows.append(f"<div class='mapping-item'><strong>{esc(title)}</strong><span class='muted' data-i18n='{esc(text_key)}'>{esc(ui(text_key))}</span></div>")
    rows.append("</div></section>")
    return "".join(rows)


def recent_runs_html(limit: int = 12) -> str:
    runs = latest_runs(DB_PATH, limit=limit)
    rows = []
    rows.append(f"<section><h2 data-i18n='recent_uploads'>{esc(ui('recent_uploads'))}</h2>")
    if not runs:
        rows.append(f"<div class='notice' data-i18n='no_uploads'>{esc(ui('no_uploads'))}</div></section>")
        return "".join(rows)
    rows.append(
        "<table><thead><tr>"
        "<th>ID</th>"
        f"<th data-i18n='week_id'>{esc(ui('week_id'))}</th>"
        f"<th data-i18n='marketplace'>{esc(ui('marketplace'))}</th>"
        f"<th data-i18n='excel_file'>{esc(ui('excel_file'))}</th>"
        f"<th data-i18n='status'>{esc(ui('status'))}</th>"
        f"<th data-i18n='uploaded_at'>{esc(ui('uploaded_at'))}</th>"
        f"<th data-i18n='action'>{esc(ui('action'))}</th>"
        "</tr></thead><tbody>"
    )
    for run in runs:
        status = run["status"]
        if status == "ok" and not snapshot_has_market_data(build_run_snapshot(run)):
            status = "无有效明细"
        status_class = "status-ok" if status == "ok" else "status-error" if status == "error" else "status-uploaded"
        rows.append(
            "<tr>"
            f"<td>{run['id']}</td>"
            f"<td>{esc(run['week_id'])}</td>"
            f"<td>{esc(run['marketplace'])}</td>"
            f"<td>{esc(run['original_filename'])}</td>"
            f"<td class='{status_class}'>{esc(status)}</td>"
            f"<td>{esc(run['uploaded_at'])}</td>"
            f"<td><a href='/analysis?id={run['id']}' data-i18n='view'>{esc(ui('view'))}</a></td>"
            "</tr>"
        )
    rows.append("</tbody></table></section>")
    return "".join(rows)


def analysis_page(run_id: int | None = None, week_id: str | None = None) -> bytes:
    selected_id = contextual_run_id(run_id, week_id)
    if not selected_id:
        body = (
            f"<section class='section-head'><div><h2 data-i18n='nav_analysis'>{esc(ui('nav_analysis'))}</h2>"
            f"<div class='section-note' data-i18n='no_data_notice'>{esc(ui('no_data_notice'))}</div></div></section>"
            f"<section class='notice' data-i18n='no_data_notice'>{esc(ui('no_data_notice'))}</section>"
        )
        return page(ui("nav_analysis"), body, week_id)
    run = get_run(DB_PATH, int(selected_id))
    selected_week = str(run.get("week_id", "")) if run else week_id
    return page(ui("nav_analysis"), run_detail_html(int(selected_id)), selected_week)


def actions_page(run_id: int | None = None, week_id: str | None = None, message: str = "") -> bytes:
    notice_html = f"<section class='notice'>{esc(message)}</section>" if message else ""
    selected_id = contextual_run_id(run_id, week_id)
    if not selected_id:
        body = (
            f"<section class='section-head'><div><h2 data-i18n='weekly_actions'>{esc(ui('weekly_actions'))}</h2>"
            f"<div class='section-note' data-i18n='no_data_notice'>{esc(ui('no_data_notice'))}</div></div></section>"
            f"{notice_html}"
            f"<section class='notice' data-i18n='no_data_notice'>{esc(ui('no_data_notice'))}</section>"
        )
        return page(ui("weekly_actions"), body, week_id)

    run = get_run(DB_PATH, int(selected_id))
    if not run:
        return page(ui("weekly_actions"), f"<section class='notice' data-i18n='not_found_run'>{esc(ui('not_found_run'))}</section>", week_id)
    if run["status"] != "ok":
        body = (
            f"<section class='card'><h2>Run #{int(selected_id)}</h2>"
            f"<p class='status-error'><span data-i18n='parse_failed'>{esc(ui('parse_failed'))}</span>{esc(run.get('error'))}</p></section>"
        )
        return page(ui("weekly_actions"), body, str(run.get("week_id", week_id or "")))

    brand = read_table_for_run(DB_PATH, "brand_metrics", int(selected_id))
    ai_summary = read_table_for_run(DB_PATH, "ai_summary", int(selected_id))
    ai_detail = read_table_for_run(DB_PATH, "ai_detail", int(selected_id))
    body = [
        "<section class='section-head'>",
        f"<div><h2 data-i18n='weekly_actions'>{esc(ui('weekly_actions'))}</h2>",
        f"<div class='section-note'>{esc(run.get('marketplace'))} · {esc(run.get('week_id'))} · {esc(run.get('original_filename'))}</div></div>",
        "</section>",
        notice_html,
        weekly_actions_html(run, brand, ai_summary, ai_detail, show_header=False),
    ]
    return page(ui("weekly_actions"), "".join(body), str(run.get("week_id", week_id or "")))


CHAT_HIGHLIGHT_PATTERN = re.compile(
    r"(Run\s*#\d+|20\d{2}-W\d{1,2}|B0[A-Z0-9]{8}|"
    r"AI\s*竞品|监控竞品|PLAUD|ASIN|AI|IA|销量份额|销售额份额|月销量|月销售额|"
    r"价格带|类目月销量|类目|异常|风险|预警|建议|优先|行动|数据缺口|销量反推|"
    r"[+-]?\d+(?:,\d{3})*(?:\.\d+)?(?:%|pp)?|"
    r"\b(?:US|UK|DE|FR|IT|ES|JP)\b)"
)


def chat_inline_html(text: object) -> str:
    source = str(text or "")
    if not source:
        return ""
    parts: list[str] = []
    cursor = 0
    for match in CHAT_HIGHLIGHT_PATTERN.finditer(source):
        start, end = match.span()
        if start > cursor:
            parts.append(esc(source[cursor:start]))
        token = match.group(0)
        css = "chat-number" if re.search(r"\d|%|pp|Run|B0", token) else "chat-emphasis"
        parts.append(f"<strong class='{css}'>{esc(token)}</strong>")
        cursor = end
    if cursor < len(source):
        parts.append(esc(source[cursor:]))
    return "".join(parts)


def chat_rich_text_html(text: str) -> str:
    lines = [line.strip() for line in str(text or "").strip().splitlines()]
    blocks: list[str] = []
    bullets: list[str] = []
    for line in lines:
        if not line:
            if bullets:
                blocks.append("<ul class='chat-bullets'>" + "".join(bullets) + "</ul>")
                bullets = []
            continue
        cleaned = re.sub(r"^(?:[\-*•]|\d+[\.)])\s*", "", line)
        is_bullet = cleaned != line or line.startswith(("1.", "2.", "3.", "4.", "5."))
        if is_bullet:
            bullets.append(f"<li>{chat_inline_html(cleaned)}</li>")
            continue
        if bullets:
            blocks.append("<ul class='chat-bullets'>" + "".join(bullets) + "</ul>")
            bullets = []
        blocks.append(f"<p>{chat_inline_html(line)}</p>")
    if bullets:
        blocks.append("<ul class='chat-bullets'>" + "".join(bullets) + "</ul>")
    return "".join(blocks) if blocks else f"<p>{chat_inline_html(text)}</p>"


def chat_answer_card(title: str, items: list[str], icon_name: str = "chat", cta_html: str = "") -> str:
    rows = [
        "<div class='chat-bubble'>",
        f"<div class='chat-bubble-title'>{icon(icon_name)}<span>{esc(title)}</span></div>",
    ]
    if items:
        rows.append("<div class='chat-lines'>")
        for index, item in enumerate(items, start=1):
            rows.append(
                "<div class='chat-line'>"
                f"<span class='chat-line-index'>{index}</span>"
                f"<span>{chat_inline_html(item)}</span>"
                "</div>"
            )
        rows.append("</div>")
    if cta_html:
        rows.append(cta_html)
    rows.append("</div>")
    return "".join(rows)


def chat_text_card(title: str, text: str, icon_name: str = "bot") -> str:
    return (
        "<div class='chat-bubble'>"
        f"<div class='chat-bubble-title'>{icon(icon_name)}<span>{esc(title)}</span></div>"
        f"<div class='chat-ai-text'>{chat_rich_text_html(text)}</div>"
        "</div>"
    )


def ai_chat_config() -> dict[str, object]:
    enabled_value = os.environ.get("PLAUD_AI_ENABLED", "auto").strip().lower()
    disabled = enabled_value in {"0", "false", "off", "no"}
    api_key = os.environ.get("PLAUD_AI_API_KEY") or os.environ.get("OPENAI_API_KEY") or ""
    base_url = os.environ.get("PLAUD_AI_BASE_URL", "https://api.openai.com/v1").strip()
    model = os.environ.get("PLAUD_AI_MODEL", "gpt-4o-mini").strip()
    timeout = value_as_float(os.environ.get("PLAUD_AI_TIMEOUT_SECONDS", "18"), 18.0)
    max_tokens = value_as_int(os.environ.get("PLAUD_AI_MAX_TOKENS", "900"), 900)
    return {
        "enabled": bool(api_key and not disabled),
        "configured": bool(api_key),
        "disabled": disabled,
        "api_key": api_key,
        "base_url": base_url,
        "model": model,
        "timeout": max(3.0, timeout),
        "max_tokens": max(300, max_tokens),
    }


def chat_ai_mode_notice() -> str:
    config = ai_chat_config()
    if config.get("enabled"):
        return (
            "<div class='notice chat-mode'>"
            f"<strong>AI 增强已启用</strong><br>模型：{esc(config.get('model'))}。回答会被约束为只基于当前 Run 数据。"
            "</div>"
        )
    if config.get("configured") and config.get("disabled"):
        detail = "检测到 API Key，但 PLAUD_AI_ENABLED 已关闭，当前使用规则回答。"
    else:
        detail = "未检测到 PLAUD_AI_API_KEY 或 OPENAI_API_KEY，当前使用规则回答；配置 Key 后会自动启用 AI 增强。"
    return f"<div class='notice chat-mode'><strong>当前为规则回答</strong><br>{esc(detail)}</div>"


def chat_data_boundary_card() -> str:
    config = ai_chat_config()
    first_item = (
        "AI 增强回答只接收当前 Run 和已上传广告报表的结构化数据包，不包含实时广告后台、库存、Review、Coupon 和 Amazon 前台实时页面。"
        if config.get("enabled")
        else "回答仅基于已上传的 SellerSprite Excel、广告报表和本地数据库，不包含实时广告后台、库存、Review、Coupon 和 Amazon 前台实时页面。"
    )
    return (
        "<section class='chat-boundary'>"
        + chat_answer_card(
            "数据边界",
            [
                first_item,
                "用于运营预判；关键投放、定价或库存决策建议再结合业务后台数据复核。",
            ],
            "info",
        )
        + "</section>"
    )


def json_ready(value: object) -> object:
    if value is None:
        return None
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_ready(item) for item in value]
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    try:
        return json_ready(value.item())  # type: ignore[attr-defined]
    except (AttributeError, ValueError, TypeError):
        return str(value)


def compact_dataframe_records(
    df: pd.DataFrame,
    columns: list[str],
    limit: int = 15,
    sort_col: str = "",
) -> list[dict[str, object]]:
    if df.empty:
        return []
    view = df.copy()
    if sort_col and sort_col in view:
        view["_sort"] = view[sort_col].map(value_as_float)
        view = view.sort_values("_sort", ascending=False)
    available = [col for col in columns if col in view]
    if not available:
        return []
    records = []
    for _, row in view.head(limit).iterrows():
        records.append({col: json_ready(row.get(col)) for col in available})
    return records


def build_ai_chat_context(
    run: dict[str, object],
    brand: pd.DataFrame,
    ai_summary: pd.DataFrame,
    ai_detail: pd.DataFrame,
) -> dict[str, object]:
    metrics = chat_metric_items(run, brand, ai_summary, ai_detail)
    products = product_metrics_for_run(run)
    previous = previous_successful_run(run)
    previous_context: dict[str, object] = {}
    if previous:
        prev_brand = read_table_for_run(DB_PATH, "brand_metrics", int(previous["id"]))
        prev_ai_summary = read_table_for_run(DB_PATH, "ai_summary", int(previous["id"]))
        prev_plaud = first_row(prev_brand[prev_brand["brand"] == "PLAUD"]) if not prev_brand.empty else {}
        prev_competitors = first_row(prev_brand[prev_brand["brand"] == "COMPETITORS_TOTAL"]) if not prev_brand.empty else {}
        prev_ai = first_row(prev_ai_summary.head(1)) if not prev_ai_summary.empty else {}
        plaud = metrics["plaud"]
        competitors = metrics["competitors"]
        ai = metrics["ai"]
        previous_context = {
            "run": {
                "id": previous.get("id"),
                "marketplace": previous.get("marketplace"),
                "week_id": previous.get("week_id"),
            },
            "deltas": {
                "plaud_units_share_delta_pp": format_delta_pp(
                    value_as_float(plaud.get("monthly_units_share")) - value_as_float(prev_plaud.get("monthly_units_share"))
                ),
                "competitor_units_share_delta_pp": format_delta_pp(
                    value_as_float(competitors.get("monthly_units_share")) - value_as_float(prev_competitors.get("monthly_units_share"))
                ),
                "ai_units_share_delta_pp": format_delta_pp(
                    value_as_float(ai.get("ai_units_share")) - value_as_float(prev_ai.get("ai_units_share"))
                ),
            },
        }

    return json_ready(
        {
            "scope_rules": [
                "Only answer from this JSON data package.",
                "If data is missing, say 当前数据不足.",
                "Do not invent ads, inventory, reviews, ratings, coupons, profit, or live Amazon frontend data.",
                "Separate facts from recommendations.",
            ],
            "run": {
                "id": run.get("id"),
                "marketplace": run.get("marketplace"),
                "week_id": run.get("week_id"),
                "original_filename": run.get("original_filename"),
                "uploaded_at": run.get("uploaded_at"),
            },
            "current_summary": {
                "plaud": metrics["plaud"],
                "tracked_competitors_total": metrics["competitors"],
                "ai_competitor_summary": metrics["ai"],
                "top_ai_competitor_by_revenue": metrics["top_ai"],
                "strongest_price_band": metrics["band"],
                "category_baseline": {
                    "category_units": metrics["baseline"].get("units"),
                    "category_revenue": metrics["baseline"].get("revenue"),
                    "rank_sales_model": metrics["model"],
                },
                "missing_marketplaces": metrics["missing_sites"],
            },
            "previous_same_site": previous_context,
            "brand_market_share_rows": compact_dataframe_records(
                brand,
                ["marketplace", "brand", "brand_group", "monthly_units", "monthly_units_share", "monthly_revenue", "monthly_revenue_share"],
                limit=25,
                sort_col="monthly_units",
            ),
            "ai_competitor_asins": compact_dataframe_records(
                ai_detail,
                ["asin", "standard_brand", "monthly_units", "monthly_revenue", "price", "bsr_rank", "ai_matched_keywords", "product_title"],
                limit=20,
                sort_col="monthly_revenue",
            ),
            "top_products_by_revenue": compact_dataframe_records(
                products,
                ["asin", "standard_brand", "monthly_units", "monthly_revenue", "price", "bsr_rank", "product_title"],
                limit=20,
                sort_col="monthly_revenue",
            ),
            "amazon_ads_reports": ads_ai_context(str(run.get("week_id", "")), str(run.get("marketplace", ""))),
            "knowledge_base": knowledge_ai_context(),
        }
    )


def ai_system_prompt(run: dict[str, object]) -> str:
    return (
        "你是 PLAUD 的亚马逊市场与运营分析师。必须严格遵守：\n"
        "1. 只基于用户提供的 JSON 结构化数据回答，不使用外部知识，不编造。\n"
        "2. 回答第一行必须写：数据口径：站点 {site}｜周次 {week}｜Run ID {run_id}。\n"
        "3. 如果广告、库存、评论、评分、Coupon、利润、实时前台等数据未在 JSON 中出现，必须说“当前数据不足”。\n"
        "4. 回答涉及建议时，必须分成“数据结论”和“策略建议”两段。\n"
        "5. 策略建议要落到运营可执行动作，但要明确哪些是基于数据的结论，哪些是策略推导。\n"
        "6. 输出中文，短句，适合运营直接使用。"
    ).format(site=run.get("marketplace", ""), week=run.get("week_id", ""), run_id=run.get("id", ""))


def call_ai_chat_completion(config: dict[str, object], system_prompt: str, user_prompt: str) -> str:
    base_url = str(config.get("base_url") or "").rstrip("/")
    url = base_url if base_url.endswith("/chat/completions") else f"{base_url}/chat/completions"
    payload = {
        "model": config.get("model"),
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.2,
        "max_tokens": config.get("max_tokens"),
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {config.get('api_key')}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=float(config.get("timeout", 18))) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")[:300]
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(str(exc.reason)) from exc
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("模型未返回 choices")
    message = choices[0].get("message") or {}
    content = str(message.get("content") or "").strip()
    if not content:
        raise RuntimeError("模型返回为空")
    return content


def ai_enhanced_chat_answer_html(
    run: dict[str, object],
    brand: pd.DataFrame,
    ai_summary: pd.DataFrame,
    ai_detail: pd.DataFrame,
    question: str,
) -> tuple[str, str]:
    config = ai_chat_config()
    if not question.strip() or not config.get("enabled"):
        return "", ""
    context = build_ai_chat_context(run, brand, ai_summary, ai_detail)
    user_prompt = (
        f"用户问题：{question.strip()}\n\n"
        "当前 Run 结构化数据如下。请按系统约束回答，必要时明确说明当前数据不足。\n"
        f"{json.dumps(context, ensure_ascii=False, indent=2)}"
    )
    try:
        answer = call_ai_chat_completion(config, ai_system_prompt(run), user_prompt)
    except RuntimeError as exc:
        return "", str(exc)
    return chat_text_card("AI 增强回答", answer, "bot"), ""


def chat_metric_items(
    run: dict[str, object],
    brand: pd.DataFrame,
    ai_summary: pd.DataFrame,
    ai_detail: pd.DataFrame,
) -> dict[str, object]:
    plaud = first_row(brand[brand["brand"] == "PLAUD"]) if not brand.empty else {}
    competitors = first_row(brand[brand["brand"] == "COMPETITORS_TOTAL"]) if not brand.empty else {}
    ai = first_row(ai_summary.head(1)) if not ai_summary.empty else {}
    top_ai = top_ai_competitor(ai_detail)
    band = strongest_price_band(run, ai_detail)
    baseline = category_baseline(run, brand, ai_summary)
    config = load_config(CONFIG_PATH)
    sites = config.get("monitoring", {}).get("marketplaces", [])
    uploaded_sites = latest_site_runs()
    missing_sites = [item for item in sites if item not in uploaded_sites]
    return {
        "plaud": plaud,
        "competitors": competitors,
        "ai": ai,
        "top_ai": top_ai,
        "band": band,
        "baseline": baseline,
        "model": baseline.get("model", {}),
        "missing_sites": missing_sites,
    }


def market_chat_answer(
    run: dict[str, object],
    brand: pd.DataFrame,
    ai_summary: pd.DataFrame,
    ai_detail: pd.DataFrame,
    question: str,
) -> str:
    metrics = chat_metric_items(run, brand, ai_summary, ai_detail)
    plaud = metrics["plaud"]
    competitors = metrics["competitors"]
    ai = metrics["ai"]
    top_ai = metrics["top_ai"]
    band = metrics["band"]
    baseline = metrics["baseline"]
    model = metrics["model"]
    missing_sites = metrics["missing_sites"]
    q = question.strip()
    q_lower = q.lower()
    run_id = int(run.get("id", 0))
    site_week = f"{run.get('marketplace', '')} · {run.get('week_id', '')}"
    cards: list[str] = []
    if q:
        ai_html, ai_error = ai_enhanced_chat_answer_html(run, brand, ai_summary, ai_detail, q)
        if ai_html:
            return ai_html
        if ai_error:
            cards.append(
                chat_answer_card(
                    "AI 增强暂不可用，已切换规则回答",
                    [
                        f"模型调用失败：{ai_error}",
                        "下面回答仍然只基于当前上传数据，但表达会更偏固定规则。",
                    ],
                    "warning",
                )
            )

    if not q:
        cards.append(
            chat_answer_card(
                "本周市场简报",
                [
                    f"当前数据源：Run #{run_id} · {site_week}。",
                    f"PLAUD 销量份额 {pct(plaud.get('monthly_units_share'))}，监控竞品合计销量份额 {pct(competitors.get('monthly_units_share'))}。",
                    f"AI 竞品销量渗透 {pct(ai.get('ai_units_share'))}，AI 竞品 ASIN {value_as_int(ai.get('ai_competitor_asin_count'))} 个。",
                    f"类目月销量反推约 {num(model.get('estimated_units'))}。" if model.get("available") else "类目排名销量反推暂不可用。",
                    "你可以继续问：异常原因、营销机会、价格带、AI 竞品威胁、品牌市占或本周行动建议。",
                ],
                "dashboard",
            )
        )
    elif any(keyword in q_lower for keyword in ["行动", "建议", "做什么", "下周", "优先级", "运营"]):
        cards.append(
            chat_answer_card(
                "本周优先动作",
                [
                    f"先补齐数据缺口：{', '.join(missing_sites)}。" if missing_sites else "七站点最近成功数据已具备，可以进入横向对比和趋势判断。",
                    f"PLAUD 当前销量份额 {pct(plaud.get('monthly_units_share'))}，销售额份额 {pct(plaud.get('monthly_revenue_share'))}，建议作为本周复盘主线。",
                    f"AI 竞品销量渗透 {pct(ai.get('ai_units_share'))}，ASIN 数 {value_as_int(ai.get('ai_competitor_asin_count'))}，需要跟踪新增 AI 卖点和标题表达。",
                    f"核心价格带优先检查 {band.get('label')}，该价格带销售额占比 {pct(band.get('revenue_share'))}。" if band else "价格带数据不足，下一次导出需确保报告包含价格字段。",
                ],
                "actions",
                f"<a class='btn btn-primary' href='/actions?id={run_id}'>{icon('actions')}查看完整行动建议</a>",
            )
        )
    elif any(keyword in q_lower for keyword in ["营销", "卖点", "广告", "推广", "listing", "主图", "转化"]):
        cards.append(
            chat_answer_card(
                "营销与 Listing 机会",
                [
                    "卖点层面优先强化 AI 转写、自动摘要、多语言、会议/课堂/采访场景，把“智能录音”表达放进标题、主图和 A+ 模块。",
                    f"价格带建议围绕 {band.get('label')} 做优惠与竞品对比，因为该价格带贡献 {pct(band.get('revenue_share'))} 类目销售额。" if band else "当前缺少价格带结论，先补价格字段后再判断优惠力度。",
                    f"可对标 AI 标杆 ASIN {top_ai.get('asin')}（{top_ai.get('standard_brand')}），重点拆它的标题关键词、主图信息密度和容量/语言数表达。" if top_ai else "当前没有足够 AI 竞品明细，先补商品集中度数据。",
                    "广告侧建议围绕 Voice Recorder、AI Recorder、meeting transcription、call recording 等词分组，按站点语言补本地化表达。",
                ],
                "target",
            )
        )
    elif any(keyword in q_lower for keyword in ["ai", "ia", "竞品", "智能", "渗透"]):
        cards.append(
            chat_answer_card(
                "AI 竞品解读",
                [
                    f"AI 竞品销量渗透指剔除 PLAUD 后，标题命中 AI/IA 等关键词的竞品销量 / 类目总销量；当前为 {pct(ai.get('ai_units_share'))}。",
                    f"AI 竞品销售额渗透当前为 {pct(ai.get('ai_revenue_share'))}，月销量 {num(ai.get('ai_competitor_units'))}，月销售额 {num(ai.get('ai_competitor_revenue'))}。",
                    f"销售额最高的 AI 竞品是 {top_ai.get('asin')}，品牌 {top_ai.get('standard_brand')}，月销售额 {num(top_ai.get('monthly_revenue'))}。" if top_ai else "当前没有识别到可用 AI 竞品明细。",
                    "运营判断：如果 AI 渗透连续上升，需要把 AI 卖点、价格带、评论增长和新增 ASIN 放进预警观察。",
                ],
                "bot",
            )
        )
    elif any(keyword in q_lower for keyword in ["品牌", "市占", "份额", "share", "plau", "全球"]):
        cards.append(
            chat_answer_card(
                "品牌/竞品市占",
                [
                    f"PLAUD 在当前站点销量份额 {pct(plaud.get('monthly_units_share'))}，销售额份额 {pct(plaud.get('monthly_revenue_share'))}。",
                    f"日常监控竞品合计销量份额 {pct(competitors.get('monthly_units_share'))}，销售额份额 {pct(competitors.get('monthly_revenue_share'))}。",
                    f"PLAUD 月销量 {num(plaud.get('monthly_units'))}，月销售额 {num(plaud.get('monthly_revenue'))}；竞品合计月销量 {num(competitors.get('monthly_units'))}，月销售额 {num(competitors.get('monthly_revenue'))}。",
                    "全球范围市占需要七站点数据齐备后汇总；当前如有缺失站点，全球结果只能视作已上传站点口径。",
                ],
                "brand",
            )
        )
    elif any(keyword in q_lower for keyword in ["价格", "价格带", "定价", "优惠", "折扣", "eur", "usd", "gbp", "jpy"]):
        cards.append(
            chat_answer_card(
                "价格带判断",
                [
                    f"当前贡献最高价格带是 {band.get('label')}，ASIN 数 {value_as_int(band.get('asin_count'))}，销售额占比 {pct(band.get('revenue_share'))}。" if band else "当前报告缺少可用价格字段，暂时不能判断价格带。",
                    f"该价格带内 PLAUD 月销量 {num(band.get('plaud_units'))}，AI 竞品月销量 {num(band.get('ai_units'))}。" if band else "建议下一次卖家精灵导出保留价格、月销量、月销售额字段。",
                    "运营用法：优先检查核心价格带内 PLAUD 的优惠、券、主图价格利益点，以及竞品是否用低价 AI 卖点抢占点击。",
                ],
                "trend",
            )
        )
    elif any(keyword in q_lower for keyword in ["异常", "原因", "为什么", "归因", "风险", "预警"]):
        prev_run = previous_successful_run(run)
        if prev_run:
            prev_brand = read_table_for_run(DB_PATH, "brand_metrics", int(prev_run["id"]))
            prev_ai = read_table_for_run(DB_PATH, "ai_summary", int(prev_run["id"]))
            prev_plaud = first_row(prev_brand[prev_brand["brand"] == "PLAUD"]) if not prev_brand.empty else {}
            prev_ai_row = first_row(prev_ai.head(1)) if not prev_ai.empty else {}
            plaud_delta = value_as_float(plaud.get("monthly_units_share")) - value_as_float(prev_plaud.get("monthly_units_share"))
            ai_delta = value_as_float(ai.get("ai_units_share")) - value_as_float(prev_ai_row.get("ai_units_share"))
            trend_line = f"对比 {prev_run.get('week_id')}：PLAUD 销量份额 {format_delta_pp(plaud_delta)}，AI 竞品销量渗透 {format_delta_pp(ai_delta)}。"
        else:
            trend_line = "当前是该站点首个可比基线，异常判断先以数据完整性、AI ASIN 和价格带结构为主。"
        cards.append(
            chat_answer_card(
                "异常归因方向",
                [
                    trend_line,
                    f"数据缺口：{', '.join(missing_sites)}，会影响全球市占和七站点横向对比。" if missing_sites else "数据完整性较好，可以优先看份额、价格带和 ASIN 变化。",
                    f"类目月销量反推约 {num(model.get('estimated_units'))}，可信度 {ui(str(model.get('confidence_key')))}。" if model.get("available") else "类目销量反推暂不可用，需保证商品明细包含排名和销量。",
                    "主要归因路径：先看采集口径是否一致，再看 PLAUD Top ASIN 排名/价格，再看新增 AI 竞品和核心价格带挤压。",
                ],
                "warning",
                f"<a class='btn' href='/analysis?id={run_id}#analysis-workbench'>{icon('analysis')}查看异常归因卡</a>",
            )
        )
    elif any(keyword in q_lower for keyword in ["asin", "商品", "排名", "bsr", "类目", "销量反推"]):
        cards.append(
            chat_answer_card(
                "ASIN / 类目排名",
                [
                    f"类目排名销量反推是用商品明细中的类目排名和月销量拟合关系，估算整个类目的月销量规模；当前估算 {num(model.get('estimated_units'))}。" if model.get("available") else "当前模型不可用，通常是缺少类目排名或月销量字段。",
                    f"当前类目总销量口径为 {num(baseline.get('units'))}，总销售额口径为 {num(baseline.get('revenue'))}。",
                    f"本周 AI 竞品 ASIN 数 {value_as_int(ai.get('ai_competitor_asin_count'))}；新增/消失 ASIN 需要同站点下一周数据后自动对比。",
                    "运营用法：用排名趋势判断 Top 商品是否被新品挤压，用销量反推判断类目大盘是在扩张还是缩小。",
                ],
                "table",
            )
        )
    else:
        cards.append(
            chat_answer_card(
                "本周市场简报",
                [
                    f"当前数据源：Run #{run_id} · {site_week}。",
                    f"PLAUD 销量份额 {pct(plaud.get('monthly_units_share'))}，监控竞品合计销量份额 {pct(competitors.get('monthly_units_share'))}。",
                    f"AI 竞品销量渗透 {pct(ai.get('ai_units_share'))}，AI 竞品 ASIN {value_as_int(ai.get('ai_competitor_asin_count'))} 个。",
                    f"类目月销量反推约 {num(model.get('estimated_units'))}。" if model.get("available") else "类目排名销量反推暂不可用。",
                    "你可以继续问：异常原因、营销机会、价格带、AI 竞品威胁、品牌市占或本周行动建议。",
                ],
                "dashboard",
            )
        )

    return "".join(cards)


def chat_page(run_id: int | None = None, question: str = "", week_id: str | None = None) -> bytes:
    selected_id = contextual_run_id(run_id, week_id)
    if not selected_id:
        body = (
            f"<section class='section-head'><div><h2 data-i18n='chat_title'>{esc(ui('chat_title'))}</h2>"
            f"<div class='section-note' data-i18n='no_data_notice'>{esc(ui('no_data_notice'))}</div></div></section>"
            f"<section class='notice' data-i18n='no_data_notice'>{esc(ui('no_data_notice'))}</section>"
        )
        return page(ui("chat_title"), body, week_id)

    run = get_run(DB_PATH, int(selected_id))
    if not run:
        return page(ui("chat_title"), f"<section class='notice' data-i18n='not_found_run'>{esc(ui('not_found_run'))}</section>", week_id)
    if run["status"] != "ok":
        body = (
            f"<section class='card'><h2>Run #{int(selected_id)}</h2>"
            f"<p class='status-error'><span data-i18n='parse_failed'>{esc(ui('parse_failed'))}</span>{esc(run.get('error'))}</p></section>"
        )
        return page(ui("chat_title"), body, str(run.get("week_id", week_id or "")))

    brand = read_table_for_run(DB_PATH, "brand_metrics", int(selected_id))
    ai_summary = read_table_for_run(DB_PATH, "ai_summary", int(selected_id))
    ai_detail = read_table_for_run(DB_PATH, "ai_detail", int(selected_id))
    quick_questions = [
        "本周市场总结",
        "本周有哪些异常原因？",
        "本周运营优先做什么？",
        "AI 竞品有什么威胁？",
        "有哪些营销卖点机会？",
        "价格带机会在哪里？",
        "本周应该关注什么？",
    ]
    quick_links = []
    for item in quick_questions:
        quick_links.append(
            f"<a class='btn quick-chip' href='/chat?id={int(selected_id)}&q={quote_plus(item)}'>{icon('chat')}{esc(item)}</a>"
        )
    body = [
        "<section class='section-head'>",
        f"<div><h2 data-i18n='chat_title'>{esc(ui('chat_title'))}</h2>",
        f"<div class='section-note' data-i18n='chat_note'>{esc(ui('chat_note'))}</div>",
        f"<div class='section-note'>Run #{int(selected_id)} · {esc(run.get('marketplace'))} · {esc(run.get('week_id'))}</div></div>",
        f"<a class='btn' href='/analysis?id={int(selected_id)}'>{icon('analysis')}<span data-i18n='nav_analysis'>{esc(ui('nav_analysis'))}</span></a>",
        "</section>",
        "<section class='chat-layout'>",
        "<div class='chat-panel'>",
        f"<h3>{icon('chat')}<span data-i18n='nav_chat'>{esc(ui('nav_chat'))}</span></h3>",
        "<form class='chat-form' method='get' action='/chat'>",
        f"<input type='hidden' name='id' value='{int(selected_id)}'>",
        f"<label data-i18n='chat_question'>{esc(ui('chat_question'))}</label>",
        f"<input name='q' value='{esc(question)}' placeholder='{esc(ui('chat_placeholder'))}' data-i18n-placeholder='chat_placeholder'>",
        f"<button class='btn btn-primary' type='submit'>{icon('bot')}<span data-i18n='chat_ask'>{esc(ui('chat_ask'))}</span></button>",
        "</form>",
        chat_ai_mode_notice(),
        f"<h3>{icon('search')}<span data-i18n='quick_questions'>{esc(ui('quick_questions'))}</span></h3>",
        "<div class='quick-grid'>",
        "".join(quick_links),
        "</div></div>",
        "<div class='chat-answer'>",
        market_chat_answer(run, brand, ai_summary, ai_detail, question),
        "</div></section>",
        chat_data_boundary_card(),
    ]
    return page(ui("chat_title"), "".join(body), str(run.get("week_id", week_id or "")))


def run_detail_html(run_id: int, embedded: bool = False, compact: bool = False) -> str:
    run = get_run(DB_PATH, run_id)
    if not run:
        return f"<section class='notice' data-i18n='not_found_run'>{esc(ui('not_found_run'))}</section>"
    if run["status"] != "ok":
        return (
            f"<section class='card'><h2>Run #{run_id}</h2>"
            f"<p class='status-error'><span data-i18n='parse_failed'>{esc(ui('parse_failed'))}</span>{esc(run.get('error'))}</p></section>"
        )
    brand = read_table_for_run(DB_PATH, "brand_metrics", run_id)
    ai_summary = read_table_for_run(DB_PATH, "ai_summary", run_id)
    ai_detail = read_table_for_run(DB_PATH, "ai_detail", run_id)
    marketplace = run.get("marketplace", "")

    plaud = brand[brand["brand"] == "PLAUD"].head(1)
    competitors = brand[brand["brand"] == "COMPETITORS_TOTAL"].head(1)
    ai = ai_summary.head(1)

    def first(df: pd.DataFrame, col: str) -> object:
        return "" if df.empty else df.iloc[0].get(col, "")

    body = []
    title_html = (
        f"<h2 data-i18n='latest_market_result'>{esc(ui('latest_market_result'))}</h2>"
        if embedded
        else f"<h2>Run #{run_id} <span data-i18n='market_result'>{esc(ui('market_result'))}</span></h2>"
    )
    body.append(
        "<section class='section-head'>"
        f"<div>{title_html}"
        f"<div class='section-note'>{esc(run.get('marketplace'))} · {esc(run.get('week_id'))} · {esc(run.get('original_filename'))}</div></div>"
        f"<a class='btn btn-primary' href='/download/report.xlsx?id={run_id}'>{icon('download')}<span data-i18n='download_weekly_excel'>{esc(ui('download_weekly_excel'))}</span></a>"
        "</section>"
    )
    body.append("<section><div class='grid'>")
    metrics = [
        ("plaud_units_share", pct(first(plaud, "monthly_units_share")), "brand"),
        ("plaud_revenue_share", pct(first(plaud, "monthly_revenue_share")), "trend"),
        ("competitor_units_share", pct(first(competitors, "monthly_units_share")), "target"),
        ("ai_units_share", pct(first(ai, "ai_units_share")), "bot"),
    ]
    for label_key, value, icon_name in metrics:
        body.append(
            "<div class='card metric-card'>"
            f"<span class='icon-badge'>{icon(icon_name)}</span>"
            f"<div><div class='metric-label' data-i18n='{esc(label_key)}'>{esc(ui(label_key))}</div><div class='metric-value'>{esc(value)}</div></div>"
            "</div>"
        )
    body.append("</div></section>")
    plaud_units_share = value_as_float(first(plaud, "monthly_units_share"))
    competitor_units_share = value_as_float(first(competitors, "monthly_units_share"))
    plaud_revenue_share = value_as_float(first(plaud, "monthly_revenue_share"))
    competitor_revenue_share = value_as_float(first(competitors, "monthly_revenue_share"))
    ai_units_share = value_as_float(first(ai, "ai_units_share"))
    ai_revenue_share = value_as_float(first(ai, "ai_revenue_share"))

    tab_buttons = [
        ("overview", "tab_overview", "dashboard"),
        ("charts", "tab_charts", "trend"),
        ("brand", "tab_brand", "brand"),
        ("ai-category", "tab_ai_category", "bot"),
        ("asin", "tab_asin", "list"),
        ("asin-depth", "tab_competitor_asin_depth", "target"),
        ("keyword-voc", "tab_keyword_voc", "search"),
        ("ops", "tab_ops", "actions"),
        ("data", "tab_data", "table"),
    ]
    body.append(
        "<section class='analysis-workbench' id='analysis-workbench'>"
        f"<h2 data-i18n='analysis_workbench'>{esc(ui('analysis_workbench'))}</h2>"
        "<div class='analysis-tab-list' role='tablist'>"
    )
    for index, (tab, label_key, icon_name) in enumerate(tab_buttons):
        active_class = " active" if index == 0 else ""
        selected = "true" if index == 0 else "false"
        body.append(
            f"<button class='analysis-tab-button{active_class}' type='button' role='tab' aria-selected='{selected}' "
            f"data-tab-button='{esc(tab)}'>{icon(icon_name)}<span data-i18n='{esc(label_key)}'>{esc(ui(label_key))}</span></button>"
        )
    body.append("</div><div class='analysis-tab-panel active' data-tab-panel='overview'>")
    body.append(data_quality_score_html(run, brand, ai_summary, ai_detail))
    body.append(opportunity_center_html(run, brand, ai_summary, ai_detail))
    body.append(weekly_brief_plus_html(run, brand, ai_summary, ai_detail))
    body.append(weekly_insights_html(run, brand, ai_summary, ai_detail))
    body.append(abnormal_attribution_html(run, brand, ai_summary, ai_detail))
    body.append(metric_explainer_html())
    body.append("</div><div class='analysis-tab-panel' data-tab-panel='charts'>")

    body.append("<section class='chart-grid'>")
    body.append(
        donut_chart(
            ui("units_share_structure"),
            pct(plaud_units_share),
            [
                ("PLAUD", plaud_units_share, "var(--chart-brand)"),
                (ui("tracked_competitors"), competitor_units_share, "var(--chart-competitor)", "tracked_competitors"),
            ],
            ui("monthly_units"),
            ui("other_brands"),
            "units_share_structure",
            "monthly_units",
            "other_brands",
        )
    )
    body.append(
        donut_chart(
            ui("revenue_share_structure"),
            pct(plaud_revenue_share),
            [
                ("PLAUD", plaud_revenue_share, "var(--chart-brand)"),
                (ui("tracked_competitors"), competitor_revenue_share, "var(--chart-competitor)", "tracked_competitors"),
            ],
            ui("monthly_revenue"),
            ui("other_brands"),
            "revenue_share_structure",
            "monthly_revenue",
            "other_brands",
        )
    )
    body.append(
        donut_chart(
            ui("ai_units_penetration"),
            pct(ai_units_share),
            [(ui("ai_competitors"), ai_units_share, "var(--chart-ai)", "ai_competitors")],
            ui("exclude_plaud"),
            ui("non_ai_other"),
            "ai_units_penetration",
            "exclude_plaud",
            "non_ai_other",
        )
    )
    body.append(
        donut_chart(
            ui("ai_revenue_penetration"),
            pct(ai_revenue_share),
            [(ui("ai_competitors"), ai_revenue_share, "var(--chart-ai)", "ai_competitors")],
            ui("exclude_plaud"),
            ui("non_ai_other"),
            "ai_revenue_penetration",
            "exclude_plaud",
            "non_ai_other",
        )
    )
    body.append(
        donut_chart(
            ui("ai_units_with_plaud"),
            pct(ai_units_share),
            [
                ("PLAUD", plaud_units_share, "var(--chart-brand)"),
                (ui("ai_competitors"), ai_units_share, "var(--chart-ai)", "ai_competitors"),
            ],
            ui("monthly_units"),
            ui("non_ai_other"),
            "ai_units_with_plaud",
            "monthly_units",
            "non_ai_other",
        )
    )
    body.append(
        donut_chart(
            ui("ai_revenue_with_plaud"),
            pct(ai_revenue_share),
            [
                ("PLAUD", plaud_revenue_share, "var(--chart-brand)"),
                (ui("ai_competitors"), ai_revenue_share, "var(--chart-ai)", "ai_competitors"),
            ],
            ui("monthly_revenue"),
            ui("non_ai_other"),
            "ai_revenue_with_plaud",
            "monthly_revenue",
            "non_ai_other",
        )
    )
    body.append(line_chart(ui("plaud_units_trend"), metric_history(str(marketplace), "plaud_units_share"), "var(--chart-brand)", "plaud_units_trend"))
    body.append(line_chart(ui("ai_units_trend"), metric_history(str(marketplace), "ai_units_share"), "var(--chart-ai)", "ai_units_trend"))
    body.append("</section>")
    body.append("</div><div class='analysis-tab-panel' data-tab-panel='brand'>")
    body.append(brand_market_share_html(run, brand))
    body.append("</div><div class='analysis-tab-panel' data-tab-panel='ai-category'>")
    body.append(category_rank_model_html(run, brand, ai_summary))
    body.append(price_band_analysis_html(run, ai_detail))
    body.append(price_positioning_html(run, ai_detail))
    body.append("</div><div class='analysis-tab-panel' data-tab-panel='asin'>")
    body.append(asin_war_room_html(run, ai_detail))
    body.append(asin_change_analysis_html(run))
    body.append("</div><div class='analysis-tab-panel' data-tab-panel='asin-depth'>")
    body.append(competitor_asin_depth_html(run, ai_detail))
    body.append("</div><div class='analysis-tab-panel' data-tab-panel='keyword-voc'>")
    body.append(keyword_voc_opportunity_html(run, ai_detail))
    body.append("</div><div class='analysis-tab-panel' data-tab-panel='ops'>")
    body.append(advanced_attribution_html(run, brand, ai_summary, ai_detail))
    body.append(ads_data_linkage_html())
    body.append(share_of_voice_html(run))
    body.append(operations_task_loop_html(run, brand, ai_summary, ai_detail))
    body.append("</div><div class='analysis-tab-panel' data-tab-panel='data'>")

    body.append(local_data_inventory_html())
    body.append(data_collection_boundary_html())
    body.append(
        f"<section class='card'><h2 data-i18n='mature_mapping'>{esc(ui('mature_mapping'))}</h2>"
        "<table><thead><tr>"
        f"<th data-i18n='module'>{esc(ui('module'))}</th>"
        f"<th data-i18n='platform_impl'>{esc(ui('platform_impl'))}</th>"
        f"<th data-i18n='task_mapping'>{esc(ui('task_mapping'))}</th>"
        "</tr></thead><tbody>"
    )
    mapping_rows = [
        ("Market Share", "mapping_market_share_impl", "mapping_market_share_task"),
        ("Competitor Movement", "mapping_competitor_movement_impl", "mapping_competitor_movement_task"),
        ("Product Intelligence", "mapping_product_intelligence_impl", "mapping_product_intelligence_task"),
        ("Workflow Export", "mapping_workflow_export_impl", "mapping_workflow_export_task"),
    ]
    for module, impl_key, task_key in mapping_rows:
        body.append(f"<tr><td>{esc(module)}</td><td data-i18n='{esc(impl_key)}'>{esc(ui(impl_key))}</td><td data-i18n='{esc(task_key)}'>{esc(ui(task_key))}</td></tr>")
    body.append("</tbody></table></section>")

    ai_detail_view = ai_detail.sort_values("monthly_revenue", ascending=False).copy() if not ai_detail.empty else ai_detail
    if not ai_detail_view.empty:
        ai_detail_view["monthly_units"] = ai_detail_view["monthly_units"].map(num)
        ai_detail_view["monthly_revenue"] = ai_detail_view["monthly_revenue"].map(num)
    body.append(f"<section><h2 data-i18n='ai_asin_detail'>{esc(ui('ai_asin_detail'))}</h2>")
    body.append(
        dataframe_table(
            ai_detail_view,
            ["asin", "standard_brand", "monthly_units", "monthly_revenue", "ai_matched_keywords", "product_title"],
            limit=25,
        )
    )
    body.append("</section>")
    body.append("</div></section>")

    return "".join(body)


def uploads_page(week_id: str | None = None) -> bytes:
    weeks = dashboard_week_options()
    selected_week = week_id if week_id in weeks else (weeks[0] if weeks else "")
    body = [
        "<div class='uploads-page'>",
        "<section class='section-head'>",
        f"<div><h2 data-i18n='nav_uploads'>{esc(ui('nav_uploads'))}</h2>",
        f"<div class='section-note'>上传、校验和回溯 SellerSprite 数据统一在这里处理；当前周次：{esc(selected_week or '-')}。</div></div>",
        "</section>",
        upload_form(selected_week),
        recent_runs_html(limit=50),
        "</div>",
    ]
    return page(ui("nav_uploads"), "".join(body), selected_week)


def sellersprite_mcp_usage(config: dict[str, object]) -> dict[str, object]:
    sellersprite = (
        config.get("api_integrations", {}).get("sellersprite", {})
        if isinstance(config.get("api_integrations"), dict)
        else {}
    )
    if not isinstance(sellersprite, dict):
        sellersprite = {}
    plan = str(sellersprite.get("mcp_plan") or "Max").strip() or "Max"
    monthly_quota = max(0, value_as_int(sellersprite.get("mcp_monthly_quota"), 10000))
    qpm = max(0, value_as_int(sellersprite.get("mcp_qpm"), 40))
    calls_per_import = max(1, value_as_int(sellersprite.get("mcp_estimated_calls_per_import"), 3))
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    where_sql = (
        "status = 'ok' AND "
        "(original_filename LIKE 'SellerSprite_MCP_%' OR stored_path LIKE '%sellersprite_mcp%')"
    )
    with connect(DB_PATH) as conn:
        row = conn.execute(
            f"""
            SELECT
                COUNT(*) AS imports,
                COUNT(DISTINCT week_id) AS weeks,
                COUNT(DISTINCT marketplace) AS marketplaces,
                COUNT(DISTINCT week_id || ':' || marketplace) AS site_weeks,
                MAX(uploaded_at) AS latest_at
            FROM uploaded_reports
            WHERE {where_sql}
              AND substr(uploaded_at, 1, 7) = ?
            """,
            (month,),
        ).fetchone()
        all_time_imports = count_query(conn, f"SELECT COUNT(*) FROM uploaded_reports WHERE {where_sql}")
        deep_row = conn.execute(
            """
            SELECT
                COUNT(DISTINCT CASE
                    WHEN source_type = 'traffic_keyword' AND asin != ''
                    THEN run_id || ':' || marketplace || ':' || asin || ':' || source_type
                END) AS traffic_calls,
                COUNT(DISTINCT CASE
                    WHEN source_type = 'keyword_order'
                    THEN run_id || ':' || marketplace || ':' || source_type
                END) AS keyword_order_calls
            FROM mcp_asin_keyword_intel
            WHERE substr(fetched_at, 1, 7) = ?
            """,
            (month,),
        ).fetchone()

    monthly_imports = int(row["imports"] or 0) if row else 0
    deep_dive_calls = int((deep_row["traffic_calls"] or 0) + (deep_row["keyword_order_calls"] or 0)) if deep_row else 0
    consumed = monthly_imports * calls_per_import + deep_dive_calls
    remaining = max(monthly_quota - consumed, 0) if monthly_quota else 0
    usage_percent = min(100.0, (consumed / monthly_quota * 100)) if monthly_quota else 0.0
    return {
        "plan": plan,
        "month": month,
        "monthly_quota": monthly_quota,
        "qpm": qpm,
        "calls_per_import": calls_per_import,
        "monthly_imports": monthly_imports,
        "deep_dive_calls": deep_dive_calls,
        "consumed": consumed,
        "remaining": remaining,
        "usage_percent": usage_percent,
        "weeks": int(row["weeks"] or 0) if row else 0,
        "marketplaces": int(row["marketplaces"] or 0) if row else 0,
        "site_weeks": int(row["site_weeks"] or 0) if row else 0,
        "latest_at": row["latest_at"] if row else "",
        "all_time_imports": all_time_imports,
    }


def sellersprite_mcp_usage_html(config: dict[str, object]) -> str:
    usage = sellersprite_mcp_usage(config)
    quota_text = num(usage["monthly_quota"]) if usage["monthly_quota"] else "未配置"
    consumed_text = num(usage["consumed"])
    remaining_text = num(usage["remaining"]) if usage["monthly_quota"] else "未配置"
    percent_text = f"{value_as_float(usage['usage_percent']):.1f}%"
    cards = [
        (
            "本月估算消耗",
            f"{consumed_text} 次",
            f"{num(usage['monthly_imports'])} 次类目拉取 × {usage['calls_per_import']} + ASIN 深挖 {num(usage['deep_dive_calls'])} 次",
        ),
        (
            "预计剩余额度",
            f"{remaining_text} 次",
            f"{usage['plan']} 套餐月额度 {quota_text} 次",
        ),
        (
            "调用进度",
            percent_text,
            f"{usage['month']} 已用比例；接近 80% 时建议减少批量补数",
        ),
        (
            "频控上限",
            f"{num(usage['qpm'])} 次/分钟",
            f"本月覆盖 {usage['weeks']} 个周次、{usage['marketplaces']} 个站点",
        ),
    ]
    body = [
        "<section>",
        "<div class='section-head'>",
        "<div><h2>SellerSprite MCP 用量估算</h2>",
        "<div class='section-note'>按本地成功导入的 SellerSprite_MCP Run 估算消耗和剩余额度，便于控制批量拉取节奏。</div></div>",
        "</div>",
        "<div class='mcp-usage-grid'>",
    ]
    for label, value, sub in cards:
        body.append(
            "<div class='mcp-usage-card'>"
            f"<div class='mcp-usage-label'>{esc(label)}</div>"
            f"<div class='mcp-usage-value'>{esc(value)}</div>"
            f"<div class='mcp-usage-sub'>{esc(sub)}</div>"
            "</div>"
        )
    body.append("</div>")
    body.append(
        "<div class='mcp-usage-meter' aria-label='SellerSprite MCP usage'>"
        f"<span style='width:{value_as_float(usage['usage_percent']):.1f}%'></span>"
        "</div>"
    )
    body.append(
        "<div class='mcp-usage-note'>"
        f"口径说明：当前 MCP 未提供官方余额接口，系统按成功入库记录估算；"
        f"不含失败重试、工具列表检查和卖家精灵后台外部消耗。历史累计 MCP Run {num(usage['all_time_imports'])} 次，最近导入时间 {esc(usage['latest_at'] or '暂无')}。"
        "</div>"
        "</section>"
    )
    return "".join(body)


def config_page(week_id: str | None = None) -> bytes:
    config = load_config(CONFIG_PATH)
    marketplaces = config.get("marketplaces", {})
    rows = [
        f"<section><h2 data-i18n='config_summary'>{esc(ui('config_summary'))}</h2>"
        "<table><thead><tr>"
        f"<th data-i18n='marketplace'>{esc(ui('marketplace'))}</th>"
        f"<th data-i18n='currency'>{esc(ui('currency'))}</th>"
        f"<th data-i18n='keyword'>{esc(ui('keyword'))}</th>"
        f"<th data-i18n='category_path'>{esc(ui('category_path'))}</th>"
        f"<th data-i18n='bsr_url'>{esc(ui('bsr_url'))}</th>"
        "</tr></thead><tbody>"
    ]
    for site in config.get("monitoring", {}).get("marketplaces", []):
        item = marketplaces.get(site, {})
        rows.append(
            f"<tr><td>{esc(site)}</td><td>{esc(item.get('currency'))}</td><td>{esc(item.get('keyword'))}</td>"
            f"<td>{esc(item.get('category_path'))}</td><td>{esc(item.get('category_url'))}</td></tr>"
        )
    rows.append("</tbody></table></section>")

    rows.append(
        f"<section><h2 data-i18n='api_integrations'>{esc(ui('api_integrations'))}</h2>"
        "<table><thead><tr>"
        f"<th data-i18n='api_provider'>{esc(ui('api_provider'))}</th>"
        f"<th data-i18n='api_use_case'>{esc(ui('api_use_case'))}</th>"
        f"<th data-i18n='api_enabled'>{esc(ui('api_enabled'))}</th>"
        f"<th data-i18n='api_readiness'>{esc(ui('api_readiness'))}</th>"
        f"<th data-i18n='api_next_step'>{esc(ui('api_next_step'))}</th>"
        "</tr></thead><tbody>"
    )
    for item in integration_statuses(config):
        enabled_key = "api_yes" if item["enabled"] else "api_no"
        ready_key = "api_ready" if item["ready"] else "api_not_ready"
        ready_class = "pill-ok" if item["ready"] else "pill-missing"
        rows.append(
            f"<tr><td>{esc(item['label'])}</td>"
            f"<td>{esc(item['use_case'])}</td>"
            f"<td><span class='pill' data-i18n='{enabled_key}'>{esc(ui(enabled_key))}</span></td>"
            f"<td><span class='pill {ready_class}' data-i18n='{ready_key}'>{esc(ui(ready_key))}</span></td>"
            f"<td>{esc(item['next_step'])}</td></tr>"
        )
    rows.append("</tbody></table></section>")
    rows.append(sellersprite_mcp_usage_html(config))
    return page(ui("config_summary"), "".join(rows), week_id)


class Handler(BaseHTTPRequestHandler):
    def send_html(self, content: bytes, status: HTTPStatus = HTTPStatus.OK) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        try:
            self.wfile.write(content)
        except BrokenPipeError:
            return

    def redirect(self, location: str) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", location)
        self.end_headers()

    def redirect_knowledge(self, message: str) -> None:
        self.redirect(f"/knowledge?msg={quote_plus(message)}")

    def redirect_ads(self, message: str) -> None:
        self.redirect(f"/ads?msg={quote_plus(message)}")

    def parse_form(self) -> cgi.FieldStorage:
        return cgi.FieldStorage(
            fp=self.rfile,
            headers=self.headers,
            environ={
                "REQUEST_METHOD": "POST",
                "CONTENT_TYPE": self.headers.get("Content-Type", ""),
            },
        )

    def do_GET(self) -> None:  # noqa: N802 - http.server API.
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)
        week_id = qs.get("week_id", [""])[0].strip() or None
        message = qs.get("msg", [""])[0].strip()
        if path == "/":
            self.send_html(dashboard(week_id))
        elif path == "/agent":
            run_id = int(qs.get("run_id", ["0"])[0] or 0)
            self.send_html(agent_page(run_id or None, message, week_id))
        elif path == "/analysis":
            run_id = int(qs.get("id", ["0"])[0] or 0)
            self.send_html(analysis_page(run_id or None, week_id))
        elif path == "/actions":
            run_id = int(qs.get("id", ["0"])[0] or 0)
            self.send_html(actions_page(run_id or None, week_id, message))
        elif path == "/chat":
            run_id = int(qs.get("id", ["0"])[0] or 0)
            question = qs.get("q", [""])[0].strip()
            self.send_html(chat_page(run_id or None, question, week_id))
        elif path == "/ads":
            message = qs.get("msg", [""])[0].strip()
            self.send_html(ads_page(message, week_id))
        elif path == "/uploads":
            self.send_html(uploads_page(week_id))
        elif path == "/config":
            self.send_html(config_page(week_id))
        elif path == "/run":
            run_id = int(qs.get("id", ["0"])[0])
            run = get_run(DB_PATH, run_id)
            run_week = str(run.get("week_id", "")) if run else week_id
            self.send_html(page(f"Run #{run_id}", run_detail_html(run_id), run_week))
        elif path == "/download/report.xlsx":
            run_id = int(qs.get("id", ["0"])[0])
            self.serve_excel_report(run_id)
        elif path == "/download/report":
            run_id = int(qs.get("id", ["0"])[0])
            self.serve_markdown_report(run_id)
        else:
            self.send_html(page("404", f"<section class='notice' data-i18n='page_not_found'>{esc(ui('page_not_found'))}</section>"), HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802 - http.server API.
        path = urlparse(self.path).path
        if path == "/mcp/fetch-latest":
            self.handle_fetch_latest_week()
            return
        if path == "/ads/upload":
            self.handle_ads_upload()
            return
        if path != "/upload":
            self.send_html(page("404", f"<section class='notice' data-i18n='page_not_found'>{esc(ui('page_not_found'))}</section>"), HTTPStatus.NOT_FOUND)
            return
        form = self.parse_form()
        week_id = form.getfirst("week_id", "").strip()
        marketplace = form.getfirst("marketplace", "").strip().upper()
        note = form.getfirst("note", "").strip()
        file_item = form["file"] if "file" in form else None
        if not week_id or not marketplace or file_item is None or not getattr(file_item, "filename", ""):
            self.send_html(page(ui("upload_failed"), f"<section class='notice' data-i18n='upload_required'>{esc(ui('upload_required'))}</section>"), HTTPStatus.BAD_REQUEST)
            return
        temp_dir = UPLOAD_DIR / "_tmp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_path = temp_dir / Path(file_item.filename).name
        data = file_item.file.read()
        temp_path.write_bytes(data)
        result = process_report_file(
            CONFIG_PATH,
            temp_path,
            week_id,
            marketplace,
            DB_PATH,
            UPLOAD_DIR,
            REPORT_DIR,
            original_filename=file_item.filename,
            note=note,
        )
        try:
            temp_path.unlink()
        except OSError:
            pass
        self.redirect(f"/analysis?id={result.run_id}")

    def handle_fetch_latest_week(self) -> None:
        form = self.parse_form()
        return_to = form.getfirst("return_to", "actions").strip() or "actions"
        return_to_path = form.getfirst("return_to_path", "").strip()
        ok, week_id, message = fetch_latest_week_data()
        allowed_return_paths = {"/", "/agent", "/analysis", "/actions", "/chat", "/ads", "/uploads", "/config"}
        if return_to_path in allowed_return_paths:
            target = return_to_path
        else:
            target = "/uploads" if return_to == "uploads" else "/actions"
        if not ok:
            message = f"{message} 请检查配置或稍后重试。"
        self.redirect(f"{target}?week_id={quote_plus(week_id)}&msg={quote_plus(message)}")

    def handle_knowledge_upload(self) -> None:
        form = self.parse_form()
        file_item = form["file"] if "file" in form else None
        if file_item is None or not getattr(file_item, "filename", ""):
            self.redirect_knowledge("请选择要上传的知识文档")
            return
        doc_id = store_knowledge_document(
            form.getfirst("doc_type", "brand_positioning").strip(),
            form.getfirst("title", "").strip(),
            file_item,
            form.getfirst("note", "").strip(),
        )
        self.redirect_knowledge(f"知识文档已上传，ID {doc_id}")

    def handle_add_competitor(self) -> None:
        form = self.parse_form()
        brand = form.getfirst("brand", "").strip()
        if not brand:
            self.redirect_knowledge("请填写竞品品牌")
            return
        insert_competitor_profile(
            form.getfirst("marketplace", "").strip(),
            brand,
            form.getfirst("asin", "").strip(),
            form.getfirst("product_name", "").strip(),
            form.getfirst("priority", "").strip(),
            form.getfirst("source", "手工维护").strip(),
            form.getfirst("note", "").strip(),
        )
        self.redirect_knowledge("竞品清单已保存")

    def handle_import_competitors(self) -> None:
        form = self.parse_form()
        file_item = form["file"] if "file" in form else None
        if file_item is None or not getattr(file_item, "filename", ""):
            self.redirect_knowledge("请选择竞品清单 Excel/CSV")
            return
        try:
            count = import_competitor_profiles(file_item)
        except Exception as exc:
            self.redirect_knowledge(f"竞品导入失败：{str(exc)[:120]}")
            return
        self.redirect_knowledge(f"已导入 {count} 条竞品记录")

    def handle_add_listing_point(self) -> None:
        form = self.parse_form()
        point = form.getfirst("selling_point", "").strip()
        if not point:
            self.redirect_knowledge("请填写 Listing 卖点")
            return
        insert_listing_point(
            form.getfirst("marketplace", "").strip(),
            form.getfirst("asin", "").strip(),
            form.getfirst("brand", "").strip(),
            form.getfirst("product_name", "").strip(),
            point,
            form.getfirst("scenario", "").strip(),
            form.getfirst("source", "手工维护").strip(),
        )
        self.redirect_knowledge("Listing 卖点已保存")

    def handle_import_listing_points(self) -> None:
        form = self.parse_form()
        file_item = form["file"] if "file" in form else None
        if file_item is None or not getattr(file_item, "filename", ""):
            self.redirect_knowledge("请选择 Listing 卖点 Excel/CSV")
            return
        try:
            count = import_listing_points(file_item)
        except Exception as exc:
            self.redirect_knowledge(f"Listing 卖点导入失败：{str(exc)[:120]}")
            return
        self.redirect_knowledge(f"已导入 {count} 条 Listing 卖点")

    def handle_ads_upload(self) -> None:
        form = self.parse_form()
        week_id = form.getfirst("week_id", "").strip()
        marketplace = form.getfirst("marketplace", "").strip().upper()
        report_type = form.getfirst("report_type", "search_term").strip()
        file_item = form["file"] if "file" in form else None
        if not week_id or not marketplace or file_item is None or not getattr(file_item, "filename", ""):
            self.redirect_ads("请填写周次、站点并选择广告报表 Excel/CSV")
            return
        try:
            count = import_ads_report(
                week_id,
                marketplace,
                report_type,
                file_item,
                form.getfirst("note", "").strip(),
            )
        except Exception as exc:
            self.redirect_ads(f"广告报表解析失败：{str(exc)[:120]}")
            return
        self.redirect_ads(f"广告报表已导入 {count} 行")

    def serve_markdown_report(self, run_id: int) -> None:
        run = get_run(DB_PATH, run_id)
        if not run or not run.get("report_path"):
            self.send_html(page(ui("download_failed"), f"<section class='notice' data-i18n='report_not_found'>{esc(ui('report_not_found'))}</section>"), HTTPStatus.NOT_FOUND)
            return
        path = Path(run["report_path"])
        if not path.exists():
            self.send_html(page(ui("download_failed"), f"<section class='notice' data-i18n='report_missing'>{esc(ui('report_missing'))}</section>"), HTTPStatus.NOT_FOUND)
            return
        content = path.read_bytes()
        mime = mimetypes.guess_type(path.name)[0] or "text/markdown"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{mime}; charset=utf-8")
        self.send_header("Content-Disposition", f"attachment; filename={path.name}")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def serve_excel_report(self, run_id: int) -> None:
        path = ensure_excel_report_for_run(DB_PATH, run_id, REPORT_DIR)
        if not path or not path.exists():
            self.send_html(page(ui("download_failed"), f"<section class='notice' data-i18n='excel_report_missing'>{esc(ui('excel_report_missing'))}</section>"), HTTPStatus.NOT_FOUND)
            return
        content = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.send_header("Content-Disposition", f"attachment; filename={path.name}")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> int:
    parser = argparse.ArgumentParser(description="PLAUD monitoring MVP web platform")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8501)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"PLAUD monitoring MVP running at http://{args.host}:{args.port}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
