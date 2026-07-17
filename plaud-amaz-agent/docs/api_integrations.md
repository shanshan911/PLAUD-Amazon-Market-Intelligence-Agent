# PLAUD 官方 API 接入说明

本文档说明当前 MVP 如何接入 Amazon Ads API、Amazon SP-API 与 SellerSprite API。当前代码已完成可配置接入层和本地自检；正式拉数前只需要业务/IT 补齐授权与环境变量。

## 接入边界

- Amazon Ads API：用于广告投放、广告报告、Search Term、Campaign/Ad Group、ACOS/TACOS 与广告驱动的市场份额解释。
- Amazon SP-API：用于卖家官方经营数据，例如 Orders、Reports、Sales、Catalog、Inventory、Pricing 等，具体可用范围取决于授权角色。
- SellerSprite API：用于第三方市场估算、竞品 ASIN、关键词、类目节点、BSR 销量反推等，承接目前卖家精灵 Excel 的半自动流程。

## 合规采集策略

原则：系统只拉取当前任务必要数据；有官方授权或第三方授权的数据走 API；没有授权但属于公开页面的小样本信息只做低频校验；涉及登录后台、验证码、会话绕过、买家隐私或受限角色的数据不拉取。

| 采集等级 | 数据来源 | 当前处理 | 可采集字段/用途 | 不采集内容 |
| --- | --- | --- | --- | --- |
| 自动拉取 | SellerSprite MCP / SellerSprite API | 已接入 MCP；API 凭证齐后可替代插件 Excel | 类目市场、品牌集中度、商品集中度、ASIN、销量/销售额估算、BSR 相关字段 | 绕过 SellerSprite 后台授权的页面抓取 |
| 自动读取 | 卖家精灵 Excel / 本地 SQLite | 已支持上传、解析、历史沉淀 | 周度市占、AI 竞品、价格带、Top ASIN、趋势图、周报导出 | 不额外抓网页补齐 Excel 不含字段 |
| 授权后拉取 | Amazon Ads API | 凭证齐后启用 | Spend、Sales、ACOS、CTR、Campaign、Targeting、Search Term、ASIN 广告报表 | 自动登录广告后台页面、验证码、追踪或抓后台 DOM |
| 授权后拉取 | Amazon SP-API | 凭证、AWS 签名和角色审批齐后启用 | 官方订单聚合、Sales、Catalog、Listings、库存、Pricing、Reports；按已批准角色限制调用 | 买家 PII、配送/订单受限数据，除非业务明确获批对应角色和 Restricted Data Token |
| 低频校验 | Amazon 公开商品页 | 仅用于人工校验与小样本补充 | 标题、品牌、价格、评分、评论数、BSR、优惠、可售状态、主图、ASIN | 大规模 SERP 抓取、代理轮换、验证码页、登录态页面、购物车/账号数据 |
| 人工上传 | Seller Central / Advertising Console 导出报表 | 运营导出 Excel/CSV 后上传 | 后台报表、Bulk operations、广告报表、库存/经营报表 | 系统自动控制浏览器登录后台、读取 Cookie、模拟点击下载 |

执行规则：

- 周度市场数据：优先 SellerSprite MCP 自动拉取；MCP 不可用时运营上传卖家精灵 Excel。
- 广告数据：只接受 Amazon Ads API 或官方后台导出的 Excel/CSV。
- 官方经营数据：只接受 SP-API 授权数据或业务方人工导出报表。
- Amazon 前台数据：仅作为低频公开页校验，不作为大规模自动采集主数据源。
- 遇到登录页、验证码、403/429/503、Robot Check 或受限字段时，脚本必须跳过并记录原因。

## 配置位置

```text
config/monitor_config.p0.json
config/monitor_config.example.json
```

新增配置块：

```json
{
  "api_integrations": {
    "amazon_ads": {
      "enabled": false,
      "region": "EU",
      "client_id_env": "AMAZON_ADS_CLIENT_ID",
      "client_secret_env": "AMAZON_ADS_CLIENT_SECRET",
      "refresh_token_env": "AMAZON_ADS_REFRESH_TOKEN",
      "profile_id_env": "AMAZON_ADS_PROFILE_ID"
    },
    "sp_api": {
      "enabled": false,
      "selling_region": "EU",
      "endpoint": "https://sellingpartnerapi-eu.amazon.com",
      "aws_region": "eu-west-1",
      "lwa_client_id_env": "SP_API_LWA_CLIENT_ID",
      "lwa_client_secret_env": "SP_API_LWA_CLIENT_SECRET",
      "refresh_token_env": "SP_API_REFRESH_TOKEN",
      "aws_access_key_env": "SP_API_AWS_ACCESS_KEY_ID",
      "aws_secret_key_env": "SP_API_AWS_SECRET_ACCESS_KEY",
      "aws_session_token_env": "SP_API_AWS_SESSION_TOKEN"
    },
    "sellersprite": {
      "enabled": false,
      "base_url": "https://api.sellersprite.com",
      "secret_key_env": "SELLERSPRITE_SECRET_KEY"
    }
  }
}
```

正式启用时，把对应 `enabled` 改成 `true`，并在服务器/本机环境变量里配置密钥。不要把密钥写进 JSON、Excel、README 或飞书文档。

## 业务方需要提供

| 等级 | API | 需要提供 | 用途 |
| --- | --- | --- | --- |
| P0 | SellerSprite API | `secret-key`、套餐权限、QPS/日额度、可调用 endpoint 清单 | 替代/补充卖家精灵 Excel，拉取类目与 BSR 销量估算 |
| P0 | SP-API | Seller Central 开发者应用、LWA client id/secret、refresh token、授权站点、已批准角色 | 拉取官方经营数据，校准卖家精灵估算 |
| P0 | SP-API | AWS IAM access key/secret 或已可用的临时凭证方案 | 对 SP-API 请求做 AWS SigV4 签名 |
| P1 | Amazon Ads API | Ads API 申请通过的应用、LWA client id/secret、refresh token、profileId 列表 | 拉取广告表现，解释份额变化是否由投放驱动 |
| P1 | Amazon Ads API | 广告账号与站点映射、币种、时区、Campaign 命名规范 | 支持站点级广告归因与横向对比 |
| P1 | 全部 | API 调用频率限制、失败重试 SOP、密钥轮换负责人 | 确保稳定运行和合规 |

## 本地自检

只检查配置与环境变量，不发起外部请求：

```bash
/Users/plaud/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 scripts/check_api_integrations.py \
  --config config/monitor_config.p0.json
```

输出 JSON：

```bash
/Users/plaud/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 scripts/check_api_integrations.py \
  --config config/monitor_config.p0.json \
  --json
```

有凭证后可做非写入 live check：

```bash
/Users/plaud/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 scripts/check_api_integrations.py \
  --config config/monitor_config.p0.json \
  --live
```

## 官方文档来源

- Amazon SP-API 连接流程：`https://developer-docs.amazon.com/sp-api/lang-US/docs/connecting-to-the-selling-partner-api`
- Amazon SP-API endpoint 与 AWS region：`https://developer-docs.amazon.com/sp-api/lang-US/docs/sp-api-endpoints`
- Amazon Ads API 申请与能力说明：`https://advertising.amazon.com/about-api`
- Amazon Ads API profile 授权说明：`https://d3a0d0y2hgofx6.cloudfront.net/ja-jp/guides/account-management/authorization/profiles.html`
- SellerSprite API 说明：`https://sellersprite.ai/v3/knowledge/feature/about-api`
- SellerSprite endpoint 文档：`https://sellersprite.github.io/`
