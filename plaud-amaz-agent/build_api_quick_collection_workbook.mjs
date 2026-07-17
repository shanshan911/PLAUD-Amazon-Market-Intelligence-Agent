import fs from "node:fs/promises";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const OUTPUT_DIR = "/Users/plaud/Documents/New project/outputs/api_collection";
const OUTPUT = `${OUTPUT_DIR}/PLAUD_官方API快速测试收集表.xlsx`;

const rows = [
  [
    "优先级",
    "服务",
    "资料项",
    "环境变量名 / 配置项",
    "Secret 真实值 / 填写内容",
    "适用站点",
    "必填性",
    "负责人",
    "状态",
    "备注",
    "参考链接",
  ],
  ["P0", "SellerSprite API", "secret-key", "SELLERSPRITE_SECRET_KEY", "", "US/UK/DE/FR/IT/ES/JP", "必填", "", "待提供", "用于调用 SellerSprite API。", "https://sellersprite.github.io/"],
  ["P0", "SellerSprite API", "API Base URL", "base_url", "https://api.sellersprite.com", "全站点", "必填", "", "已预填", "如业务方有私有 endpoint，请覆盖。", "https://sellersprite.github.io/"],
  ["P0", "SellerSprite API", "额度 / QPS", "quota_qps", "", "全站点", "必填", "", "待确认", "填写日额度、分钟限流、并发限制。", "https://sellersprite.ai/v3/knowledge/feature/about-api"],
  ["P0", "SellerSprite API", "可用 endpoint", "enabled_endpoints", "", "全站点", "必填", "", "待确认", "例如：ASIN详情、BSR销量预测、类目节点、关键词。", "https://sellersprite.github.io/"],
  ["P0", "Amazon SP-API", "LWA Client ID", "SP_API_LWA_CLIENT_ID", "", "全站点", "必填", "", "待提供", "SP-API 授权应用。", "https://developer-docs.amazon.com/sp-api/lang-en_US/docs/sp-api-registration-overview\nhttps://developer-docs.amazon.com/sp-api/lang-US/docs/connecting-to-the-selling-partner-api"],
  ["P0", "Amazon SP-API", "LWA Client Secret", "SP_API_LWA_CLIENT_SECRET", "", "全站点", "必填", "", "待提供", "敏感信息，仅测试环境临时填写。", "https://developer-docs.amazon.com/sp-api/lang-en_US/docs/sp-api-registration-overview\nhttps://developer-docs.amazon.com/sp-api/lang-US/docs/connecting-to-the-selling-partner-api"],
  ["P0", "Amazon SP-API", "Refresh Token", "SP_API_REFRESH_TOKEN", "", "全站点", "必填", "", "待提供", "店铺授权后生成。", "https://developer-docs.amazon.com/sp-api/lang-US/docs/authorize-public-applications\nhttps://developer-docs.amazon.com/sp-api/lang-US/docs/connecting-to-the-selling-partner-api"],
  ["P0", "Amazon SP-API", "AWS Access Key ID", "SP_API_AWS_ACCESS_KEY_ID", "", "全站点", "必填", "", "待提供", "用于 AWS SigV4 签名。", "https://developer-docs.amazon.com/sp-api/lang-US/docs/connecting-to-the-selling-partner-api\nhttps://developer-docs.amazon.com/sp-api/lang-US/docs/sp-api-endpoints"],
  ["P0", "Amazon SP-API", "AWS Secret Access Key", "SP_API_AWS_SECRET_ACCESS_KEY", "", "全站点", "必填", "", "待提供", "敏感信息，仅测试环境临时填写。", "https://developer-docs.amazon.com/sp-api/lang-US/docs/connecting-to-the-selling-partner-api\nhttps://developer-docs.amazon.com/sp-api/lang-US/docs/sp-api-endpoints"],
  ["P1", "Amazon SP-API", "AWS Session Token", "SP_API_AWS_SESSION_TOKEN", "", "全站点", "可选", "", "待确认", "仅使用临时凭证时填写。", "https://developer-docs.amazon.com/sp-api/lang-US/docs/connecting-to-the-selling-partner-api"],
  ["P0", "Amazon SP-API", "已授权站点", "authorized_marketplaces", "", "US/UK/DE/FR/IT/ES/JP", "必填", "", "待确认", "填写已授权站点，例如 US,UK,DE。", "https://developer-docs.amazon.com/sp-api/lang-US/docs/authorize-public-applications\nhttps://developer-docs.amazon.com/sp-api/lang-en_EN/docs/marketplace-ids"],
  ["P0", "Amazon SP-API", "已授权角色", "authorized_roles", "", "全站点", "必填", "", "待确认", "建议至少确认 Reports、Sales、Catalog、Orders、Pricing、Inventory。", "https://developer-docs.amazon.com/sp-api/docs/what-is-the-selling-partner-api\nhttps://developer-docs.amazon.com/sp-api/lang-US/docs/authorize-public-applications"],
  ["P1", "Amazon Ads API", "Client ID", "AMAZON_ADS_CLIENT_ID", "", "全站点", "必填", "", "待提供", "广告 API 授权应用。", "https://advertising.amazon.com/about-api"],
  ["P1", "Amazon Ads API", "Client Secret", "AMAZON_ADS_CLIENT_SECRET", "", "全站点", "必填", "", "待提供", "敏感信息，仅测试环境临时填写。", "https://advertising.amazon.com/about-api"],
  ["P1", "Amazon Ads API", "Refresh Token", "AMAZON_ADS_REFRESH_TOKEN", "", "全站点", "必填", "", "待提供", "用于换取 Ads access token。", "https://advertising.amazon.com/about-api\nhttps://d3a0d0y2hgofx6.cloudfront.net/ja-jp/guides/account-management/authorization/profiles.html"],
  ["P1", "Amazon Ads API", "默认 Profile ID", "AMAZON_ADS_PROFILE_ID", "", "默认/单站点", "建议", "", "待确认", "多站点建议在第二个 Sheet 分站填写。", "https://d3a0d0y2hgofx6.cloudfront.net/ja-jp/guides/account-management/authorization/profiles.html"],
  ["P1", "Amazon Ads API", "报表范围", "ads_report_scope", "", "全站点", "建议", "", "待确认", "SP/SB/SD、Campaign、Keyword、Search Term 等。", "https://advertising.amazon.com/about-api"],
  ["P1", "联调联系人", "业务/IT/账号负责人", "contact_owner", "", "全站点", "必填", "", "待提供", "填写姓名、部门、联系方式。", "内部 SOP / 飞书项目文档"],
];

const siteRows = [
  ["站点", "币种", "SellerSprite Marketplace", "SP-API endpoint", "AWS region", "SP-API marketplaceId（参考）", "SP 授权状态", "Ads profileId", "备注"],
  ["US", "USD", "US", "https://sellingpartnerapi-na.amazon.com", "us-east-1", "ATVPDKIKX0DER", "待确认", "", ""],
  ["UK", "GBP", "UK", "https://sellingpartnerapi-eu.amazon.com", "eu-west-1", "A1F83G8C2ARO7P", "待确认", "", ""],
  ["DE", "EUR", "DE", "https://sellingpartnerapi-eu.amazon.com", "eu-west-1", "A1PA6795UKMFR9", "待确认", "", ""],
  ["FR", "EUR", "FR", "https://sellingpartnerapi-eu.amazon.com", "eu-west-1", "A13V1IB3VIYZZH", "待确认", "", ""],
  ["IT", "EUR", "IT", "https://sellingpartnerapi-eu.amazon.com", "eu-west-1", "APJ6JRA9NG5V4", "待确认", "", ""],
  ["ES", "EUR", "ES", "https://sellingpartnerapi-eu.amazon.com", "eu-west-1", "A1RKKUPIHCS9HS", "待确认", "", ""],
  ["JP", "JPY", "JP", "https://sellingpartnerapi-fe.amazon.com", "us-west-2", "A1VC38T7YXB528", "待确认", "", ""],
];

const docRows = [
  ["服务", "对应资料项", "需求方从哪里拿", "官方参考链接", "备注"],
  ["SellerSprite API", "secret-key / base_url / endpoint", "向 SellerSprite API 商务或账号后台申请 API Key；接口 Header 使用 secret-key。", "https://sellersprite.github.io/", "文档包含请求网关、公共 Header、返回格式和接口目录。"],
  ["SellerSprite API", "额度 / QPS / 套餐权限", "查看 SellerSprite API 套餐页或让商务确认当前账号套餐、并发、调用额度。", "https://sellersprite.ai/v3/knowledge/feature/about-api", "页面说明 API 包、支持站点、常见并发等信息。"],
  ["Amazon SP-API", "可拉取的数据范围 / 角色", "用于确认 SP-API 能覆盖订单、库存、支付、目录、定价等官方经营数据。", "https://developer-docs.amazon.com/sp-api/docs/what-is-the-selling-partner-api", "正式可用范围仍取决于账号角色和授权。"],
  ["Amazon SP-API", "开发者应用 / LWA client id / client secret", "在 Seller Central / Solution Provider Portal 完成 SP-API 开发者注册与应用注册后获取。", "https://developer-docs.amazon.com/sp-api/lang-en_US/docs/sp-api-registration-overview", "先注册开发者，再注册应用。"],
  ["Amazon SP-API", "Refresh token / 授权站点 / 授权角色", "通过公有应用授权流程或私有应用自授权流程生成 refresh token，并确认区域/站点授权。", "https://developer-docs.amazon.com/sp-api/lang-US/docs/authorize-public-applications", "私有应用可按 Amazon 文档走 self-authorization。"],
  ["Amazon SP-API", "LWA access token / AWS SigV4 / user-agent", "联调时按文档用 refresh token 换 access token，并用 AWS 凭证做 SigV4 签名。", "https://developer-docs.amazon.com/sp-api/lang-US/docs/connecting-to-the-selling-partner-api", "文档列出了 token 请求、Header、签名和请求构造。"],
  ["Amazon SP-API", "SP endpoint / AWS region", "按站点区域选择 endpoint 和 AWS region，例如 NA/us-east-1、EU/eu-west-1、FE/us-west-2。", "https://developer-docs.amazon.com/sp-api/lang-US/docs/sp-api-endpoints", "SigV4 credential scope 要使用对应 AWS region。"],
  ["Amazon SP-API", "marketplaceId / 七站点映射", "按国家站点复制 marketplaceId 到站点映射表。", "https://developer-docs.amazon.com/sp-api/lang-en_EN/docs/marketplace-ids", "US/UK/DE/FR/IT/ES/JP 已在站点映射 Sheet 预填参考值。"],
  ["Amazon Ads API", "Ads API 应用 / Client ID / Client Secret / 报表范围", "在 Amazon Ads API 申请并获批后，由广告账号或开发者应用侧提供授权信息。", "https://advertising.amazon.com/about-api", "Amazon Ads API 需要申请审批，适合广告投放和报表自动化。"],
  ["Amazon Ads API", "profileId / Refresh token / 账号映射", "通过 Ads API profile 列表或广告后台确认每个广告账号和站点的 profileId。", "https://d3a0d0y2hgofx6.cloudfront.net/ja-jp/guides/account-management/authorization/profiles.html", "请求广告报表通常需要指定 profile scope。"],
  ["内部流程", "联系人 / 数据边界 / 交付方式", "由业务、IT、账号负责人共同确认。", "内部 SOP / 飞书项目文档", "建议同步明确密钥交付、权限、轮换、异常响应人。"],
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

function rangeFor(startCol, startRow, rowCount, colCount) {
  return `${colName(startCol)}${startRow}:${colName(startCol + colCount - 1)}${startRow + rowCount - 1}`;
}

function addTitle(sheet, headingRange, noteRange, heading, note) {
  const headingCols = headingRange.split(":")[1].match(/[A-Z]+/)[0].charCodeAt(0) - headingRange.split(":")[0].match(/[A-Z]+/)[0].charCodeAt(0) + 1;
  sheet.getRange(headingRange).values = [[heading, ...Array(headingCols - 1).fill("")]];
  sheet.getRange(noteRange).values = [[note, ...Array(headingCols - 1).fill("")]];
  sheet.getRange(headingRange).merge();
  sheet.getRange(noteRange).merge();
  sheet.getRange(headingRange).format = {
    fill: "#174A7C",
    font: { name: "Microsoft YaHei", size: 16, color: "#FFFFFF", bold: true },
    verticalAlignment: "center",
  };
  sheet.getRange(noteRange).format = {
    fill: "#FFF2CC",
    font: { name: "Microsoft YaHei", size: 10, color: "#7A4A00", bold: true },
    wrapText: true,
    verticalAlignment: "center",
  };
}

function styleTable(sheet, allRange, headerRange) {
  sheet.getRange(allRange).format = {
    font: { name: "Microsoft YaHei", size: 10, color: "#1F2937" },
    borders: { preset: "all", style: "thin", color: "#D9E2EC" },
    verticalAlignment: "center",
    wrapText: true,
  };
  sheet.getRange(headerRange).format = {
    fill: "#EAF3FB",
    font: { name: "Microsoft YaHei", size: 10, color: "#174A7C", bold: true },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    borders: { preset: "all", style: "thin", color: "#D9E2EC" },
    wrapText: true,
  };
}

function stylePriorities(sheet, startRow, endRow) {
  const colors = {
    P0: ["#FCE4D6", "#9C0006"],
    P1: ["#FFF2CC", "#7A5A00"],
  };
  for (let row = startRow; row <= endRow; row += 1) {
    const value = sheet.getRange(`A${row}:A${row}`).values?.[0]?.[0];
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

const quick = workbook.worksheets.add("快速收集表");
addTitle(
  quick,
  "A1:K1",
  "A2:K2",
  "PLAUD 官方 API 快速测试收集表",
  "可填写 Secret 真实值，仅限本地临时测试使用；转发、归档或上传飞书前，请删除真实密钥或迁移到密钥管理系统。"
);
quick.getRange(rangeFor(1, 4, rows.length, 11)).values = rows;
styleTable(quick, rangeFor(1, 4, rows.length, 11), "A4:K4");
stylePriorities(quick, 5, rows.length + 3);
quick.getRange("A:A").format.columnWidthPx = 70;
quick.getRange("B:B").format.columnWidthPx = 130;
quick.getRange("C:C").format.columnWidthPx = 165;
quick.getRange("D:D").format.columnWidthPx = 235;
quick.getRange("E:E").format.columnWidthPx = 300;
quick.getRange("F:F").format.columnWidthPx = 150;
quick.getRange("G:G").format.columnWidthPx = 80;
quick.getRange("H:H").format.columnWidthPx = 110;
quick.getRange("I:I").format.columnWidthPx = 95;
quick.getRange("J:J").format.columnWidthPx = 260;
quick.getRange("K:K").format.columnWidthPx = 360;
quick.freezePanes.freezeRows(4);

const sites = workbook.worksheets.add("站点映射");
addTitle(
  sites,
  "A1:I1",
  "A2:I2",
  "七站点最小映射",
  "用于快速测试七站点授权覆盖和 Ads profileId；Marketplace ID 为参考值，联调时请再次确认。"
);
sites.getRange(rangeFor(1, 4, siteRows.length, 9)).values = siteRows;
styleTable(sites, rangeFor(1, 4, siteRows.length, 9), "A4:I4");
sites.getRange("A:C").format.columnWidthPx = 90;
sites.getRange("D:D").format.columnWidthPx = 260;
sites.getRange("E:E").format.columnWidthPx = 110;
sites.getRange("F:F").format.columnWidthPx = 190;
sites.getRange("G:I").format.columnWidthPx = 120;
sites.freezePanes.freezeRows(4);

const docs = workbook.worksheets.add("参考文档");
addTitle(
  docs,
  "A1:E1",
  "A2:E2",
  "数据获取参考文档",
  "这里直接列出对应资料项的官方参考链接和获取路径。联调时优先使用官方文档与账号后台实际状态。"
);
docs.getRange(rangeFor(1, 4, docRows.length, 5)).values = docRows;
styleTable(docs, rangeFor(1, 4, docRows.length, 5), "A4:E4");
docs.getRange("A:A").format.columnWidthPx = 150;
docs.getRange("B:B").format.columnWidthPx = 220;
docs.getRange("C:C").format.columnWidthPx = 340;
docs.getRange("D:D").format.columnWidthPx = 520;
docs.getRange("E:E").format.columnWidthPx = 280;
docs.freezePanes.freezeRows(4);

await fs.mkdir(OUTPUT_DIR, { recursive: true });

const check = await workbook.inspect({
  kind: "table",
  range: "快速收集表!A1:K18",
  include: "values",
  tableMaxRows: 18,
  tableMaxCols: 11,
});
console.log(check.ndjson);

const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 100 },
  summary: "formula error scan",
});
console.log(errors.ndjson);

for (const [sheetName, range, fileName] of [
  ["快速收集表", "A1:K22", "api_quick_main.png"],
  ["站点映射", "A1:I12", "api_quick_sites.png"],
  ["参考文档", "A1:E16", "api_quick_docs.png"],
]) {
  const image = await workbook.render({ sheetName, range, scale: 1 });
  await fs.writeFile(`${OUTPUT_DIR}/${fileName}`, Buffer.from(await image.arrayBuffer()));
}

const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(OUTPUT);
console.log(OUTPUT);
