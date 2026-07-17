# PLAUD 亚马逊周度监控数据处理框架

这是一套可配置的数据处理框架，用于在真实卖家精灵数据到位前先跑通开发链路。当前版本支持：

- 按配置读取 7 个站点的卖家精灵 Excel。
- 解析 `品牌集中度` 与 `商品集中度` Sheet。
- 标准化品牌名、销量、销售额、占比等字段。
- 计算 PLAUD 与竞品品牌市占。
- 根据多语言关键词筛选非 PLAUD 的 AI 竞品。
- 计算 AI 竞品销量/销售额市占率。
- 支持上一周快照对比，生成周环比字段。
- 输出 CSV、Markdown 周报、运行日志和指标快照。

## 目录结构

```text
plaud_monitor/                  核心处理框架
config/monitor_config.example.json
scripts/create_mock_reports.py  生成模拟卖家精灵 Excel
tests/test_pipeline.py          基础测试
outputs/                        运行后生成
data/mock/raw/                  模拟原始数据
```

## 快速试跑

使用当前工作区的 bundled Python：

```bash
/Users/plaud/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 scripts/create_mock_reports.py \
  --config config/monitor_config.example.json \
  --week 2026-W20 \
  --output-dir data/mock/raw

/Users/plaud/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m plaud_monitor run \
  --config config/monitor_config.example.json \
  --week 2026-W20 \
  --input-dir data/mock/raw \
  --output-dir outputs
```

输出目录：

```text
outputs/2026-W20/
  brand_share.csv
  ai_competitor_summary.csv
  ai_competitor_asins.csv
  run_log.csv
  weekly_report.md
  metrics_snapshot.json
```

## 本阶段三个交付物

### 1. 配置文件结构

配置文件在：

```text
config/monitor_config.example.json
```

现在已经包含站点、类目、PLAUD 别名、竞品品牌、AI 多语言关键词、字段别名、Sheet 名称、输入目录和输出目录。真实业务数据到位后，优先改这个配置，不需要改解析代码。

### 2. 模拟卖家精灵 Excel

生成模拟 Excel：

```bash
/Users/plaud/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 scripts/create_mock_reports.py \
  --config config/monitor_config.example.json \
  --week 2026-W20 \
  --output-dir data/mock/raw
```

生成路径示例：

```text
data/mock/raw/2026-W20/US/2026-W20_US_VoiceRecorders.xlsx
```

每个模拟文件包含两个 Sheet：

```text
品牌集中度
商品集中度
```

### 3. Excel 解析器

解析单个 Excel 并导出标准化预览：

```bash
/Users/plaud/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 scripts/parse_report_preview.py \
  --config config/monitor_config.example.json \
  --file data/mock/raw/2026-W20/US/2026-W20_US_VoiceRecorders.xlsx \
  --marketplace US \
  --output-dir outputs/parse_preview
```

输出：

```text
outputs/parse_preview/US_brand_concentration_normalized.csv
outputs/parse_preview/US_product_concentration_normalized.csv
```

解析器核心代码：

```text
plaud_monitor/excel_parser.py
plaud_monitor/normalizers.py
```

## 接入真实卖家精灵 Excel

把真实 Excel 放到配置指定目录，例如：

```text
data/raw/2026-W20/US/2026-W20_US_VoiceRecorders.xlsx
data/raw/2026-W20/UK/2026-W20_UK_VoiceRecorders.xlsx
```

然后运行：

```bash
/Users/plaud/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m plaud_monitor run \
  --config config/monitor_config.example.json \
  --week 2026-W20 \
  --input-dir data/raw \
  --output-dir outputs
```

## 配置项说明

主要配置都在 `config/monitor_config.example.json`：

- `monitoring.marketplaces`：监控站点。
- `marketplaces`：各站点关键词、类目路径、类目 URL、币种。
- `plaud.aliases`：PLAUD 品牌别名。
- `competitors`：竞品品牌、别名、优先级、是否纳入竞品合计。
- `ai_rules.default_keywords`：通用 AI 关键词。
- `ai_rules.marketplace_keywords`：各站点本地语言 AI 关键词。
- `ai_rules.exclude_terms`：误匹配排除词，例如 `MAIN`。
- `field_aliases`：卖家精灵 Excel 字段名映射，可适配真实文件字段变化。
- `sheets`：目标 Sheet 名称，可配置中英文或变体名称。

## 周环比

第一次运行会生成：

```text
outputs/2026-W20/metrics_snapshot.json
```

下一周运行时传入上一周快照：

```bash
/Users/plaud/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m plaud_monitor run \
  --config config/monitor_config.example.json \
  --week 2026-W21 \
  --input-dir data/raw \
  --output-dir outputs \
  --previous-snapshot outputs/2026-W20/metrics_snapshot.json
```

## 当前边界

当前框架按合规白名单采集数据：

- SellerSprite MCP/API：用于自动拉取类目市场、竞品 ASIN、销量/销售额估算和 BSR 相关字段。
- 卖家精灵 Excel：MCP/API 不可用时，由运营导出后上传解析。
- Amazon Ads API：拿到授权应用、refresh token 和 profileId 后拉取广告报表；不自动化抓取广告后台页面。
- Amazon SP-API：拿到 LWA、AWS 凭证和已批准角色后拉取官方经营数据；受限数据按 Amazon 角色和 Restricted Data Token 要求处理。
- Amazon 公开前台：只做低频公开页校验，例如标题、价格、评分、评论数、BSR、优惠和可售状态；不做登录、验证码、代理轮换或大规模 SERP 抓取。

系统不会自动控制浏览器登录 Seller Central、Advertising Console 或第三方后台，也不会读取 Cookie、绕验证码或抓取买家隐私数据。

## 官方 API 接入

当前已预留 Amazon Ads API、Amazon SP-API、SellerSprite API 的接入层：

```text
plaud_monitor/integrations/
scripts/check_api_integrations.py
docs/api_integrations.md
```

本地检查配置和环境变量：

```bash
/Users/plaud/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 scripts/check_api_integrations.py \
  --config config/monitor_config.p0.json
```

配置项在 `api_integrations` 下，所有密钥只通过环境变量读取，不写入配置文件。业务方补齐授权后，把对应服务的 `enabled` 改为 `true` 即可开始联调。

## MVP 可视化平台

本项目已包含一个零新增依赖的本地 Web MVP：

```text
app.py                  可视化入口
data/uploads/           运营上传的 Excel
data/db.sqlite          本地数据库
outputs/reports/        周报输出
plaud_monitor/          现有解析和计算模块
```

启动平台，仅自己电脑访问：

```bash
/Users/plaud/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 scripts/start_platform.py \
  --host 127.0.0.1 \
  --port 8501
```

打开：

```text
http://127.0.0.1:8501
```

启动平台，让同一公司内网/VPN 的同事访问：

```bash
/Users/plaud/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 scripts/start_platform.py \
  --host 0.0.0.0 \
  --port 8501
```

同事访问地址格式：

```text
http://<你的电脑内网IP>:8501
```

长期保持内网链接有效（登录后自动启动，异常退出自动重启，并用 `caffeinate` 防止登录状态下系统睡眠）：

```bash
cd "/Users/plaud/Documents/New project"
lsof -ti tcp:8501 | xargs kill -9 2>/dev/null || true
/Users/plaud/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 scripts/install_platform_launch_agent.py \
  --host 0.0.0.0 \
  --port 8501
```

当前固定内网链接：

```text
http://10.0.153.253:8501/?week_id=2026-W29
```

如果 Mac 的内网 IP 变化，需要把链接里的 IP 换成新的内网 IP；要让 `10.0.153.253` 永久不变，需要在公司路由器/DHCP 上给这台 Mac 做地址保留。

安装脚本还会同时安装一个每 60 秒运行一次的健康检查。如果 `http://127.0.0.1:8501/?week_id=2026-W29` 无法响应，watchdog 会自动重启平台服务。

为了让链接在无人值守时也稳定，建议再关闭 macOS 自动系统睡眠：

```bash
sudo pmset -c sleep 0
sudo pmset -c disksleep 0
sudo pmset -c womp 1
```

MacBook 合盖通常仍会睡眠；如需合盖运行，需要接电并使用外接显示器/键盘鼠标的 clamshell 模式，或保持开盖。

停止平台：

```bash
/Users/plaud/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 scripts/stop_platform.py
```

卸载长期守护：

```bash
/Users/plaud/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 scripts/install_platform_launch_agent.py --uninstall
```

运营使用路径：

```text
上传 Excel → 选择站点 → 点击解析 → 查看图表 → 下载周报 Excel
```

Excel 周报会输出到：

```text
outputs/reports/<week_id>/<marketplace>/report_run_<id>.xlsx
```

工作簿包含：

```text
汇总
品牌市占
AI竞品汇总
AI竞品明细
运行日志
```

## 每周自动周报与飞书分发

自动拉取 SellerSprite MCP 七站点数据、生成合并 Excel 周报，并推送飞书：

```bash
/Users/plaud/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 scripts/run_weekly_delivery.py \
  --week-id auto \
  --notify auto
```

上线前可先用已有数据 dry-run：

```bash
/Users/plaud/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 scripts/run_weekly_delivery.py \
  --week-id 2026-W27 \
  --skip-fetch \
  --notify none
```

飞书 webhook、应用机器人、cron 配置见：

```text
docs/weekly_feishu_automation.md
```
