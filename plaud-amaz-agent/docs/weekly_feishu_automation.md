# 每周自动拉取与飞书分发

## 目标

每周固定时间自动完成：

1. 拉取 SellerSprite MCP 七站点数据：US、UK、DE、FR、IT、ES、JP。
2. 对每个站点 Top 20 竞品 ASIN 做 MCP 二次深挖，拉取 ASIN 搜索关键词、关键词反查信号，并聚合相关词。
3. 入库并生成各站点周报。
4. 汇总生成一份七站点 Excel 周报，包含 `Top ASIN关键词深挖` Sheet。
5. 生成行动建议摘要。
6. 发送到飞书给运营。

脚本入口：

```bash
/Users/plaud/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 scripts/run_weekly_delivery.py
```

## 环境变量

必须：

```bash
SELLERSPRITE_SECRET_KEY=卖家精灵 MCP secret-key
PLAUD_PUBLIC_BASE_URL=http://服务器IP或域名:8501
```

飞书发送有两种模式。

### 方式 A：飞书群机器人 webhook

优点：配置简单。  
限制：只能发送文字摘要和看板链接，不能真正上传 Excel 附件。

```bash
FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/xxx
FEISHU_WEBHOOK_SECRET=如果机器人启用了签名校验则填写
```

### 方式 B：飞书应用机器人

优点：可以发送文字摘要，并上传 Excel 周报和 Markdown 摘要文件。  
需要飞书应用具备消息发送、文件上传相关权限，并把机器人加入目标群。

```bash
FEISHU_APP_ID=cli_xxx
FEISHU_APP_SECRET=xxx
FEISHU_RECEIVE_ID_TYPE=chat_id
FEISHU_RECEIVE_ID=目标群 chat_id
```

## 本地测试

只使用已有数据库数据生成周报，不拉 MCP、不发飞书：

```bash
/Users/plaud/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 scripts/run_weekly_delivery.py \
  --week-id 2026-W27 \
  --skip-fetch \
  --notify none
```

输出示例：

```text
outputs/weekly_delivery/2026-W27/PLAUD_亚马逊监控周报_2026-W27.xlsx
outputs/weekly_delivery/2026-W27/PLAUD_亚马逊监控周报_2026-W27_摘要.md
```

## 手动拉取并发送

```bash
/Users/plaud/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 scripts/run_weekly_delivery.py \
  --week-id auto \
  --notify auto
```

默认逻辑：

- `--week-id auto` 使用当前北京时间的 ISO 周次，例如 `2026-W27`。
- 如果该周次某站点已有成功 Run，会复用已有数据，避免重复消耗 MCP 额度。
- 如果希望强制重新拉取，加 `--force-refresh`。
- 默认会对成功 Run 自动执行 Top 20 竞品 ASIN 关键词深挖。
- 如果只想拉类目数据、不跑 ASIN 深挖，可加 `--skip-asin-deep-dive`。

单独补跑某个 Run 的 ASIN 深挖：

```bash
/Users/plaud/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 scripts/import_sellersprite_asin_keywords.py \
  --run-ids 243 \
  --top-asins 20 \
  --keyword-limit 20 \
  --force-refresh
```

按周次补跑七站点 ASIN 深挖：

```bash
/Users/plaud/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 scripts/import_sellersprite_asin_keywords.py \
  --week-id 2026-W27 \
  --marketplaces US,UK,DE,FR,IT,ES,JP \
  --top-asins 20 \
  --keyword-limit 20 \
  --force-refresh
```

## cron 定时

示例：每周一北京时间 09:30 自动拉取并推送。

```cron
TZ=Asia/Shanghai
30 9 * * 1 cd "/Users/plaud/Documents/New project" && /Users/plaud/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 scripts/run_weekly_delivery.py --week-id auto --notify auto >> outputs/weekly_delivery/cron.log 2>&1
```

这条 cron 是真实周度快照拉取链路，不使用 `scripts/import_sellersprite_mcp_range.py` 的历史周回填模式。

## 运营收到什么

飞书文字摘要包含：

- 覆盖站点数量
- 首页看板链接
- 行动建议页链接
- 七站点核心指标
- Top 行动建议
- 拉取失败站点

飞书应用机器人模式还会发送：

- `PLAUD_亚马逊监控周报_YYYY-Wxx.xlsx`
- `PLAUD_亚马逊监控周报_YYYY-Wxx_摘要.md`

网页端同步更新：

- 分析工作台 > 关键词 / VOC：优先展示 MCP ASIN 深挖关键词云、搜索词明细和相关词聚合。
- 上传记录 > SellerSprite MCP 用量估算：会把类目拉取和 ASIN 深挖调用一起估算。

## 广告归因自动化

新增广告周报链路：

1. 每周拉取 Amazon Ads API 报表。
2. 自动入库到广告数据表，广告页会同步读取这些数据。
3. 生成广告归因 Excel 周报和 Markdown 摘要。
4. 通过飞书发送摘要、广告页链接和周报附件。

脚本入口：

```bash
/Users/plaud/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 scripts/run_weekly_ads_delivery.py
```

需要先在 `config/monitor_config.p0.json` 启用 `api_integrations.amazon_ads.enabled=true`，并配置以下环境变量：

```bash
AMAZON_ADS_CLIENT_ID=xxx
AMAZON_ADS_CLIENT_SECRET=xxx
AMAZON_ADS_REFRESH_TOKEN=xxx
AMAZON_ADS_PROFILE_ID=默认广告 profileId
```

如果七站点对应不同广告 profileId，使用站点级环境变量：

```bash
AMAZON_ADS_PROFILE_ID_US=xxx
AMAZON_ADS_PROFILE_ID_UK=xxx
AMAZON_ADS_PROFILE_ID_DE=xxx
AMAZON_ADS_PROFILE_ID_FR=xxx
AMAZON_ADS_PROFILE_ID_IT=xxx
AMAZON_ADS_PROFILE_ID_ES=xxx
AMAZON_ADS_PROFILE_ID_JP=xxx
```

本地干跑，只验证请求体、Excel 和摘要产出，不请求 Amazon Ads API、不发送飞书：

```bash
/Users/plaud/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 scripts/run_weekly_ads_delivery.py \
  --marketplaces JP \
  --report-types search_term \
  --week-id 2026-W27 \
  --start-date 2026-06-29 \
  --end-date 2026-07-05 \
  --notify none \
  --dry-run
```

正式手动运行：

```bash
/Users/plaud/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 scripts/run_weekly_ads_delivery.py \
  --notify auto
```

默认会拉取上一完整自然周，覆盖 US、UK、DE、FR、IT、ES、JP，并生成：

- `outputs/weekly_ads_delivery/YYYY-Wxx/PLAUD_广告归因周报_YYYY-Wxx.xlsx`
- `outputs/weekly_ads_delivery/YYYY-Wxx/PLAUD_广告归因周报_YYYY-Wxx_摘要.md`

当前已创建 Codex 每周自动任务 `PLAUD Amazon Ads 周度归因同步`，因为 Amazon Ads API 凭证尚未启用，任务先保持暂停。凭证和飞书配置就绪后，把任务改为启用即可。
