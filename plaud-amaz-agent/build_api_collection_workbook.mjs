import fs from "node:fs/promises";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const OUTPUT_DIR = "/Users/plaud/Documents/New project/outputs/api_collection";
const OUTPUT = `${OUTPUT_DIR}/PLAUD_官方API接入资料收集表.xlsx`;

const collectionRows = [
  [
    "优先级",
    "API / 模块",
    "资料项",
    "需求方需提供/确认内容",
    "建议填写方式",
    "必填性",
    "安全等级",
    "负责人",
    "当前状态",
    "预计提供日期",
    "存放位置 / 环境变量名",
    "备注",
  ],
  ["P0", "SellerSprite API", "secret-key", "提供可调用 SellerSprite API 的 secret-key。不要直接填真实密钥到本表。", "由 IT/账号负责人配置到服务器环境变量，并在本表填写“已配置”。", "必填", "敏感", "", "待提供", "", "SELLERSPRITE_SECRET_KEY", "官方请求头为 secret-key。"],
  ["P0", "SellerSprite API", "套餐权限", "确认账号套餐是否包含 API、类目市场、竞品 ASIN、关键词、BSR/ASIN 销量预测等权限。", "填写套餐名称、开通功能、到期日。", "必填", "普通", "", "待确认", "", "账号后台/合同", "决定能否替代人工下载 Excel。"],
  ["P0", "SellerSprite API", "额度 / QPS", "提供每分钟/每日/每月调用额度、并发限制、超限处理方式。", "填写官方额度截图或商务确认。", "必填", "普通", "", "待确认", "", "账号后台/商务邮件", "用于设计自动任务频率与重试策略。"],
  ["P0", "SellerSprite API", "endpoint 清单", "确认可调用 endpoint：类目节点、ASIN 详情、BSR 销量预测、ASIN 销量预测、关键词等。", "提供官方文档链接或接口清单。", "必填", "普通", "", "待确认", "", "飞书/文档链接", "不同套餐可能开放接口不同。"],
  ["P0", "SP-API", "开发者应用", "确认 Seller Central 开发者应用已创建/获批，并可授权 PLAUD 店铺。", "填写应用名称、应用 ID、所属账号。", "必填", "普通", "", "待确认", "", "Seller Central", "正式拉官方经营数据的前置条件。"],
  ["P0", "SP-API", "LWA Client ID", "提供 LWA client id。", "真实值走安全渠道；表内只填是否已配置。", "必填", "敏感", "", "待提供", "", "SP_API_LWA_CLIENT_ID", "不要把真实值写入表格。"],
  ["P0", "SP-API", "LWA Client Secret", "提供 LWA client secret。", "真实值走安全渠道；表内只填是否已配置。", "必填", "高度敏感", "", "待提供", "", "SP_API_LWA_CLIENT_SECRET", "不要把真实值写入表格。"],
  ["P0", "SP-API", "Refresh Token", "提供店铺授权后的 refresh token。", "真实值走安全渠道；表内只填是否已配置。", "必填", "高度敏感", "", "待提供", "", "SP_API_REFRESH_TOKEN", "按授权站点确认覆盖范围。"],
  ["P0", "SP-API", "AWS Access Key", "提供用于 SigV4 签名的 AWS access key，或确认使用临时凭证/角色方案。", "真实值走安全渠道；表内只填是否已配置。", "必填", "高度敏感", "", "待提供", "", "SP_API_AWS_ACCESS_KEY_ID", "如走角色/STS，需补充轮换方式。"],
  ["P0", "SP-API", "AWS Secret Key", "提供用于 SigV4 签名的 AWS secret key。", "真实值走安全渠道；表内只填是否已配置。", "必填", "高度敏感", "", "待提供", "", "SP_API_AWS_SECRET_ACCESS_KEY", "不要把真实值写入表格。"],
  ["P0", "SP-API", "授权角色 / Scopes", "确认已授权 Reports、Sales、Catalog、Inventory、Pricing、Orders 等所需角色。", "逐项勾选已授权角色，标注未授权原因。", "必填", "普通", "", "待确认", "", "Seller Central 截图/授权页", "决定能拉哪些官方数据。"],
  ["P0", "SP-API", "站点覆盖范围", "确认 US/UK/DE/FR/IT/ES/JP 哪些站点已授权。", "在“站点映射”Sheet 填写每站点授权状态。", "必填", "普通", "", "待确认", "", "站点映射 Sheet", "影响七站点横向对比。"],
  ["P0", "安全与运维", "密钥交付方式", "确认通过 1Password/企业密钥管理/服务器环境变量等安全方式交付。", "填写交付渠道、配置人、确认人。", "必填", "高度敏感", "", "待确认", "", "安全渠道", "不建议飞书明文发送密钥。"],
  ["P1", "Amazon Ads API", "Ads API 应用", "确认 Amazon Ads API 应用已申请通过，且账号有访问广告数据权限。", "填写应用名称、申请状态、所属广告账号。", "必填", "普通", "", "待确认", "", "Amazon Ads Console", "用于广告归因与投放效果分析。"],
  ["P1", "Amazon Ads API", "Client ID", "提供 Amazon Ads API LWA client id。", "真实值走安全渠道；表内只填是否已配置。", "必填", "敏感", "", "待提供", "", "AMAZON_ADS_CLIENT_ID", "不要把真实值写入表格。"],
  ["P1", "Amazon Ads API", "Client Secret", "提供 Amazon Ads API LWA client secret。", "真实值走安全渠道；表内只填是否已配置。", "必填", "高度敏感", "", "待提供", "", "AMAZON_ADS_CLIENT_SECRET", "不要把真实值写入表格。"],
  ["P1", "Amazon Ads API", "Refresh Token", "提供授权后的 refresh token。", "真实值走安全渠道；表内只填是否已配置。", "必填", "高度敏感", "", "待提供", "", "AMAZON_ADS_REFRESH_TOKEN", "用于换取 access token。"],
  ["P1", "Amazon Ads API", "Profile ID 列表", "提供每个广告账号/站点对应的 profileId。", "在“站点映射”Sheet 按站点填写。", "必填", "普通", "", "待确认", "", "AMAZON_ADS_PROFILE_ID / 站点映射", "一个账号可能有多个 profile。"],
  ["P1", "Amazon Ads API", "广告账号与站点映射", "确认 US/UK/DE/FR/IT/ES/JP 对应哪个广告账号、币种、时区。", "在“站点映射”Sheet 填写。", "必填", "普通", "", "待确认", "", "站点映射 Sheet", "用于跨站点广告表现汇总。"],
  ["P1", "Amazon Ads API", "报表范围", "确认需要 Sponsored Products / Brands / Display 哪些报表，字段粒度到 campaign、ad group、keyword/search term。", "填写需要的报表类型和最小粒度。", "建议必填", "普通", "", "待确认", "", "需求说明", "避免一次性拉过多无用数据。"],
  ["P1", "全局", "调用频率限制", "确认三类 API 的限流、重试、失败告警要求。", "填写官方限制或账号侧限制。", "必填", "普通", "", "待确认", "", "官方文档/商务确认", "影响调度、重试与告警中心。"],
  ["P1", "全局", "数据使用边界", "确认 API 数据可用于内部看板、周报、存储周期、访问范围。", "填写合规/IT 确认意见。", "必填", "合规", "", "待确认", "", "合规/IT 确认", "决定数据留存和权限控制。"],
  ["P1", "全局", "联系人与升级路径", "提供业务负责人、IT 配置人、账号负责人、异常升级联系人。", "填写姓名、部门、联系方式。", "必填", "普通", "", "待提供", "", "联系人", "用于联调和故障恢复。"],
  ["P2", "全局", "密钥轮换策略", "确认多久轮换一次、谁负责、轮换后如何通知技术侧。", "填写轮换周期和负责人。", "建议", "高度敏感", "", "待确认", "", "安全 SOP", "降低长期运行风险。"],
  ["P2", "全局", "沙盒/测试账号", "如有测试店铺或测试广告账号，提供用于联调。", "填写账号范围和权限。", "可选", "敏感", "", "待确认", "", "测试环境", "降低对生产账号影响。"],
];

const siteRows = [
  ["站点", "币种", "Amazon Ads 区域", "SP-API 区域", "SP-API endpoint", "AWS region", "SP-API marketplaceId（参考）", "SP-API 授权状态", "Ads profileId", "SellerSprite marketplace", "业务确认人", "备注"],
  ["US", "USD", "NA", "NA", "https://sellingpartnerapi-na.amazon.com", "us-east-1", "ATVPDKIKX0DER", "待确认", "", "US", "", ""],
  ["UK", "GBP", "EU", "EU", "https://sellingpartnerapi-eu.amazon.com", "eu-west-1", "A1F83G8C2ARO7P", "待确认", "", "UK", "", ""],
  ["DE", "EUR", "EU", "EU", "https://sellingpartnerapi-eu.amazon.com", "eu-west-1", "A1PA6795UKMFR9", "待确认", "", "DE", "", ""],
  ["FR", "EUR", "EU", "EU", "https://sellingpartnerapi-eu.amazon.com", "eu-west-1", "A13V1IB3VIYZZH", "待确认", "", "FR", "", ""],
  ["IT", "EUR", "EU", "EU", "https://sellingpartnerapi-eu.amazon.com", "eu-west-1", "APJ6JRA9NG5V4", "待确认", "", "IT", "", ""],
  ["ES", "EUR", "EU", "EU", "https://sellingpartnerapi-eu.amazon.com", "eu-west-1", "A1RKKUPIHCS9HS", "待确认", "", "ES", "", ""],
  ["JP", "JPY", "FE", "FE", "https://sellingpartnerapi-fe.amazon.com", "us-west-2", "A1VC38T7YXB528", "待确认", "", "JP", "", ""],
];

const envRows = [
  ["服务", "环境变量名", "用途", "是否必填", "当前状态", "配置人", "配置日期", "备注"],
  ["SellerSprite API", "SELLERSPRITE_SECRET_KEY", "SellerSprite API secret-key", "P0 必填", "待配置", "", "", "不要写真实密钥。"],
  ["SP-API", "SP_API_LWA_CLIENT_ID", "LWA client id", "P0 必填", "待配置", "", "", ""],
  ["SP-API", "SP_API_LWA_CLIENT_SECRET", "LWA client secret", "P0 必填", "待配置", "", "", "不要写真实密钥。"],
  ["SP-API", "SP_API_REFRESH_TOKEN", "SP-API refresh token", "P0 必填", "待配置", "", "", "不要写真实密钥。"],
  ["SP-API", "SP_API_AWS_ACCESS_KEY_ID", "AWS SigV4 access key", "P0 必填", "待配置", "", "", "可替换为角色/STS 方案。"],
  ["SP-API", "SP_API_AWS_SECRET_ACCESS_KEY", "AWS SigV4 secret key", "P0 必填", "待配置", "", "", "不要写真实密钥。"],
  ["SP-API", "SP_API_AWS_SESSION_TOKEN", "AWS 临时凭证 token", "可选", "待确认", "", "", "只有使用临时凭证时需要。"],
  ["Amazon Ads API", "AMAZON_ADS_CLIENT_ID", "Ads API client id", "P1 必填", "待配置", "", "", ""],
  ["Amazon Ads API", "AMAZON_ADS_CLIENT_SECRET", "Ads API client secret", "P1 必填", "待配置", "", "", "不要写真实密钥。"],
  ["Amazon Ads API", "AMAZON_ADS_REFRESH_TOKEN", "Ads API refresh token", "P1 必填", "待配置", "", "", "不要写真实密钥。"],
  ["Amazon Ads API", "AMAZON_ADS_PROFILE_ID", "默认 Ads profileId", "P1 建议", "待配置", "", "", "多站点建议在站点映射 Sheet 分站填写。"],
];

const docsRows = [
  ["API", "官方文档", "需要需求方确认的重点"],
  ["Amazon SP-API", "https://developer-docs.amazon.com/sp-api/lang-US/docs/connecting-to-the-selling-partner-api", "LWA 授权、refresh token、已批准角色。"],
  ["Amazon SP-API endpoints", "https://developer-docs.amazon.com/sp-api/lang-US/docs/sp-api-endpoints", "站点区域、endpoint、AWS region。"],
  ["Amazon Ads API", "https://advertising.amazon.com/about-api", "应用申请状态、广告账号权限。"],
  ["Amazon Ads profiles", "https://d3a0d0y2hgofx6.cloudfront.net/ja-jp/guides/account-management/authorization/profiles.html", "profileId 与广告账号/站点映射。"],
  ["SellerSprite API", "https://sellersprite.github.io/", "secret-key、可调用 endpoint、额度/QPS。"],
];

function colName(num) {
  let out = "";
  while (num > 0) {
    const rem = (num - 1) % 26;
    out = String.fromCharCode(65 + rem) + out;
    num = Math.floor((num - 1) / 26);
  }
  return out;
}

function rangeFor(startCol, startRow, rows, cols) {
  return `${colName(startCol)}${startRow}:${colName(startCol + cols - 1)}${startRow + rows - 1}`;
}

function title(sheet, range, heading, subtitle) {
  sheet.getRange(range.heading).values = [[heading, ...Array(range.cols - 1).fill("")]];
  sheet.getRange(range.subtitle).values = [[subtitle, ...Array(range.cols - 1).fill("")]];
  sheet.getRange(range.heading).merge();
  sheet.getRange(range.subtitle).merge();
  sheet.getRange(range.heading).format = {
    fill: "#174A7C",
    font: { name: "Microsoft YaHei", size: 16, color: "#FFFFFF", bold: true },
    verticalAlignment: "center",
  };
  sheet.getRange(range.subtitle).format = {
    fill: "#EAF3FB",
    font: { name: "Microsoft YaHei", size: 10, color: "#1F2937" },
    verticalAlignment: "center",
    wrapText: true,
  };
}

function styleTable(sheet, a1, headerA1) {
  sheet.getRange(a1).format = {
    font: { name: "Microsoft YaHei", size: 10, color: "#1F2937" },
    borders: { preset: "all", style: "thin", color: "#D9E2EC" },
    verticalAlignment: "center",
    wrapText: true,
  };
  sheet.getRange(headerA1).format = {
    fill: "#F2F4F7",
    font: { name: "Microsoft YaHei", size: 10, color: "#174A7C", bold: true },
    borders: { preset: "all", style: "thin", color: "#D9E2EC" },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    wrapText: true,
  };
}

function stylePriority(sheet, startRow, endRow) {
  for (let row = startRow; row <= endRow; row += 1) {
    const value = sheet.getRange(`A${row}:A${row}`).values?.[0]?.[0];
    const colors = {
      P0: ["#FCE4D6", "#9C0006"],
      P1: ["#FFF2CC", "#7A5A00"],
      P2: ["#E2F0D9", "#375623"],
      P3: ["#DDEBF7", "#1F4E79"],
    };
    const [fill, color] = colors[value] || ["#FFFFFF", "#1F2937"];
    sheet.getRange(`A${row}:A${row}`).format = {
      fill,
      font: { name: "Microsoft YaHei", size: 10, color, bold: true },
      horizontalAlignment: "center",
      verticalAlignment: "center",
      borders: { preset: "all", style: "thin", color: "#D9E2EC" },
    };
  }
}

const workbook = Workbook.create();

const main = workbook.worksheets.add("API资料收集总表");
title(
  main,
  { heading: "A1:L1", subtitle: "A2:L2", cols: 12 },
  "PLAUD 官方 API 接入资料收集表",
  "请需求方按 P0/P1 优先补齐。敏感密钥不要写入本表，只填写“已通过安全渠道配置到环境变量/密钥管理系统”。"
);
main.getRange(rangeFor(1, 4, collectionRows.length, 12)).values = collectionRows;
styleTable(main, rangeFor(1, 4, collectionRows.length, 12), "A4:L4");
stylePriority(main, 5, collectionRows.length + 3);
main.getRange("A:A").format.columnWidthPx = 70;
main.getRange("B:B").format.columnWidthPx = 130;
main.getRange("C:C").format.columnWidthPx = 160;
main.getRange("D:D").format.columnWidthPx = 310;
main.getRange("E:E").format.columnWidthPx = 240;
main.getRange("F:F").format.columnWidthPx = 80;
main.getRange("G:G").format.columnWidthPx = 90;
main.getRange("H:H").format.columnWidthPx = 110;
main.getRange("I:I").format.columnWidthPx = 100;
main.getRange("J:J").format.columnWidthPx = 110;
main.getRange("K:K").format.columnWidthPx = 210;
main.getRange("L:L").format.columnWidthPx = 230;
main.freezePanes.freezeRows(4);

const sites = workbook.worksheets.add("站点映射");
title(
  sites,
  { heading: "A1:L1", subtitle: "A2:L2", cols: 12 },
  "七站点 API 区域与账号映射",
  "Marketplace ID 为预填参考值，请需求方/IT 联调时最终确认；Ads profileId 需由 Amazon Ads profiles 接口或广告后台确认。"
);
sites.getRange(rangeFor(1, 4, siteRows.length, 12)).values = siteRows;
styleTable(sites, rangeFor(1, 4, siteRows.length, 12), "A4:L4");
sites.getRange("A:A").format.columnWidthPx = 60;
sites.getRange("B:B").format.columnWidthPx = 70;
sites.getRange("C:D").format.columnWidthPx = 105;
sites.getRange("E:E").format.columnWidthPx = 260;
sites.getRange("F:F").format.columnWidthPx = 110;
sites.getRange("G:G").format.columnWidthPx = 190;
sites.getRange("H:L").format.columnWidthPx = 125;
sites.freezePanes.freezeRows(4);

const env = workbook.worksheets.add("环境变量清单");
title(
  env,
  { heading: "A1:H1", subtitle: "A2:H2", cols: 8 },
  "环境变量与密钥配置清单",
  "技术侧只读取环境变量；需求方/IT 负责通过安全渠道配置，表格只记录状态和负责人。"
);
env.getRange(rangeFor(1, 4, envRows.length, 8)).values = envRows;
styleTable(env, rangeFor(1, 4, envRows.length, 8), "A4:H4");
env.getRange("A:A").format.columnWidthPx = 145;
env.getRange("B:B").format.columnWidthPx = 240;
env.getRange("C:C").format.columnWidthPx = 220;
env.getRange("D:D").format.columnWidthPx = 95;
env.getRange("E:E").format.columnWidthPx = 100;
env.getRange("F:H").format.columnWidthPx = 130;
env.freezePanes.freezeRows(4);

const docs = workbook.worksheets.add("官方文档与确认点");
title(
  docs,
  { heading: "A1:C1", subtitle: "A2:C2", cols: 3 },
  "官方文档与需求方确认点",
  "联调前按这里逐项确认授权、endpoint、额度和账号映射。"
);
docs.getRange(rangeFor(1, 4, docsRows.length, 3)).values = docsRows;
styleTable(docs, rangeFor(1, 4, docsRows.length, 3), "A4:C4");
docs.getRange("A:A").format.columnWidthPx = 170;
docs.getRange("B:B").format.columnWidthPx = 520;
docs.getRange("C:C").format.columnWidthPx = 360;
docs.freezePanes.freezeRows(4);

await fs.mkdir(OUTPUT_DIR, { recursive: true });

const preview = await workbook.inspect({
  kind: "table",
  range: "API资料收集总表!A1:L12",
  include: "values",
  tableMaxRows: 12,
  tableMaxCols: 12,
});
console.log(preview.ndjson);

const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 100 },
  summary: "formula error scan",
});
console.log(errors.ndjson);

const renderTargets = [
  ["API资料收集总表", "A1:L18", "api_collection_main.png"],
  ["站点映射", "A1:L12", "api_collection_sites.png"],
  ["环境变量清单", "A1:H18", "api_collection_env.png"],
  ["官方文档与确认点", "A1:C12", "api_collection_docs.png"],
];
for (const [sheetName, range, fileName] of renderTargets) {
  const image = await workbook.render({ sheetName, range, scale: 1 });
  await fs.writeFile(`${OUTPUT_DIR}/${fileName}`, Buffer.from(await image.arrayBuffer()));
}

const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(OUTPUT);
console.log(OUTPUT);
