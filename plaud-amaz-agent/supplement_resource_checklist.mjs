import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const INPUT = "/Users/plaud/Downloads/PLAUD_监控Agent_资源准备清单.xlsx";
const OUTPUT = "/Users/plaud/Documents/New project/PLAUD_监控Agent_资源准备清单_补充版.xlsx";

const priorityDefinitions = [
  ["重要等级", "定义", "处理建议"],
  ["P0", "启动必需。缺失会导致无法开始采集、无法登录、无法定位类目或无法交付结果。", "Kick-off 前必须补齐。"],
  ["P1", "正式上线必需。缺失会影响指标口径、趋势分析、准确性或业务可用性。", "试跑前确认，正式周报前必须补齐。"],
  ["P2", "准确性/稳定性增强。缺失不阻塞试跑，但会影响长期稳定性和解释质量。", "首月内逐步补齐。"],
  ["P3", "二期优化。主要用于自动化、看板化、扩展分析和效率提升。", "进入稳定运行后规划。"],
];

const checklistRows = [
  ["P0", "卖家精灵账号", "账号邮箱/用户名", "必填", "可登录卖家精灵且可使用插件的账号；密码或登录方式需通过安全渠道交付。", "缺失", "1-卖家精灵账号", "能成功登录并打开市场分析功能。"],
  ["P0", "卖家精灵账号", "订阅等级与功能权限", "必填", "确认账号订阅等级，必须包含“市场分析”“加载全部产品”“导出 Excel”权限。", "缺失", "1-卖家精灵账号", "7 个站点均可下载类目市场分析报告。"],
  ["P0", "卖家精灵账号", "月度导出额度", "必填", "确认每月可导出次数；周度 7 站点约 28 次/月，建议预留至少 35 次/月。", "缺失", "1-卖家精灵账号", "额度覆盖周度任务和重跑需求。"],
  ["P0", "卖家精灵账号", "插件版本与安装方式", "必填", "提供 Chrome 插件版本、安装方式及更新要求。", "缺失", "1-卖家精灵账号", "固定浏览器环境可正常唤起插件。"],
  ["P0", "卖家精灵账号", "账号到期日与备用账号", "必填", "提供账号到期日；如有备用账号需列明切换条件。", "缺失", "1-卖家精灵账号", "账号过期、限流或异常时可恢复任务。"],
  ["P0", "亚马逊访问账号", "7 站点买家账号", "必填", "US/UK/DE/FR/IT/ES/JP 的浏览账号邮箱、账号年龄、是否有历史购买、Prime 状态。", "缺失", "2-亚马逊买家账号", "能稳定访问搜索页、PDP 和 BSR 类目页。"],
  ["P0", "亚马逊访问账号", "站点地区/邮编设置", "必填", "每站点建议地址或邮编，如 US 10001、UK 伦敦邮编等，由业务确认。", "缺失", "2-亚马逊买家账号", "每周采集展示口径一致。"],
  ["P0", "目标类目", "7 站点 BSR 类目 URL", "必填", "US/UK/DE/FR/IT/ES/JP 最终 BSR 类目 URL。", "缺失", "3-目标类目URL", "可直接打开正确类目 BSR 页面。"],
  ["P0", "目标类目", "类目完整路径", "必填", "每站点类目路径，例如 Office Products > Electronics > Voice Recorders。", "缺失", "3-目标类目URL", "采集前后可校验类目是否一致。"],
  ["P0", "目标类目", "核心搜索词", "必填", "每站点兜底搜索词，明确英文还是本地语言。", "缺失", "3-目标类目URL", "当类目 URL 失效时可重新定位类目。"],
  ["P0", "竞品品牌", "核心竞品品牌清单", "必填", "每站点 3-10 个核心竞品品牌，需与卖家精灵“品牌名”列一致。", "缺失", "5-竞品品牌清单", "可计算 PLAUD 以外竞品品牌合计。"],
  ["P0", "竞品品牌", "竞品监控优先级", "必填", "标注高/中/低优先级，明确是否纳入竞品合计。", "缺失", "5-竞品品牌清单", "周报可区分核心竞品和一般竞品。"],
  ["P0", "交付配置", "交付渠道", "必填", "确认飞书、邮件、钉钉/企微或其他渠道是否启用，并提供 webhook/邮箱。", "缺失", "7-交付配置", "周报可以按时触达指定对象。"],
  ["P0", "交付配置", "接收人与责任人", "必填", "业务负责人、运营对接人、项目对接人、应急联系人姓名和联系方式。", "缺失", "7-交付配置", "异常时可快速确认口径或处理账号问题。"],
  ["P0", "安全与权限", "账号交付方式", "必填", "确认账号密码、验证码、2FA、cookie 或浏览器 Profile 的安全交付方式。", "未覆盖", "建议新增到 1/2/7 或备注", "技术侧不通过非安全渠道保存敏感信息。"],
  ["P0", "自动化环境", "固定浏览器 Profile", "必填", "提供或确认用于采集的 Chrome Profile，保持亚马逊与卖家精灵登录状态。", "未覆盖", "建议新增到 2-亚马逊买家账号", "减少每周重复登录和风控。"],
  ["P0", "自动化环境", "是否允许 RPA/浏览器自动化", "必填", "确认是否允许自动打开页面、点击插件、下载报告。", "未覆盖", "建议新增到 7-交付配置", "决定采集是人工、半自动还是自动化。"],

  ["P1", "PLAUD 品牌", "PLAUD 品牌别名确认", "必填", "确认 PLAUD、PLAUD AI、PLAUD NOTE、Plaud、PLAUD-AI 是否全部归一为 PLAUD。", "部分已填，未确认", "4-PLAUD品牌别名", "自营品牌识别不漏算、不误算。"],
  ["P1", "PLAUD 品牌", "自有 ASIN 清单", "建议必填", "提供各站点 PLAUD 自有 ASIN，用于品牌识别异常时兜底剔除。", "未覆盖", "建议新增 Sheet 或备注", "AI 竞品统计可准确排除自营。"],
  ["P1", "AI 判定", "AI 关键词确认", "必填", "确认各站点 AI/IA/KI/人工知能等关键词是否采用当前词典。", "有初稿，未确认", "6-AI判定规则", "AI 竞品筛选规则可执行。"],
  ["P1", "AI 判定", "AI 判定边界", "必填", "确认 AI Translation、AI Noise Cancellation、ChatGPT/GPT、Smart 无 AI 等场景是否算 AI 竞品。", "缺失", "6-AI判定规则", "减少误匹配和口径争议。"],
  ["P1", "历史数据", "上一周卖家精灵原始 Excel", "必填", "至少提供上一周 7 个站点原始 Excel 报告。", "未覆盖", "建议新增 Sheet/文件夹", "可做首轮周环比。"],
  ["P1", "历史数据", "最近 8-12 周历史数据", "建议必填", "提供历史原始 Excel 或历史指标表。", "未覆盖", "建议新增 Sheet/文件夹", "可做趋势和异常判断。"],
  ["P1", "金额口径", "币种与汇率规则", "必填", "确认保留本币还是统一 USD/RMB；提供汇率来源和汇率周期。", "未覆盖", "建议新增 Sheet", "跨站点销售额可比较。"],
  ["P1", "金额口径", "销售额含税/不含税口径", "必填", "确认沿用卖家精灵口径还是需要财务调整。", "未覆盖", "建议新增 Sheet", "避免销售额解读偏差。"],
  ["P1", "指标口径", "品牌市占计算口径", "必填", "确认使用品牌集中度 Sheet 的月销量占比、月销售额占比。", "未覆盖", "建议新增到说明", "PLAUD 与竞品合计口径一致。"],
  ["P1", "指标口径", "AI 竞品市占计算口径", "必填", "确认 AI 竞品销量/销售额 ÷ 类目总销量/总销售额。", "未覆盖", "建议新增到说明", "AI 市占率可复核。"],
  ["P1", "任务时间", "每周采集和交付时间", "必填", "确认每周几、几点采集，几点前出周报，使用哪个时区。", "未覆盖", "7-交付配置", "任务调度和业务预期一致。"],
  ["P1", "异常处理", "验证码/登录失效处理 SOP", "必填", "账号被风控、验证码、2FA、插件登录失效时的处理人和处理时限。", "未覆盖", "建议新增到 2/7", "任务失败可快速恢复。"],
  ["P1", "异常处理", "类目路径变更处理 SOP", "必填", "类目 URL 失效、类目层级变化、最终类目不一致时以谁确认为准。", "未覆盖", "3-目标类目URL", "避免错误类目导致周报不可比。"],
  ["P1", "文件管理", "原始报告存储位置", "必填", "确认每周 Excel 原始报告保存路径、命名规则和访问权限。", "未覆盖", "建议新增 Sheet", "历史可追溯、可重算。"],
  ["P1", "文件管理", "文件命名规则", "必填", "建议 YYYY-WW_站点_类目_SellerSprite.xlsx。", "未覆盖", "建议新增 Sheet", "防止多站点文件混淆。"],

  ["P2", "竞品品牌", "竞品品牌别名/母公司映射", "建议", "补充竞品品牌大小写、空格、子品牌、母公司归属。", "缺失", "5-竞品品牌清单", "提升品牌市占识别准确性。"],
  ["P2", "AI 判定", "误匹配排除词", "建议", "如 MAIN 含 AI 但非 AI，或 IA 在非人工智能语义中出现。", "部分场景未填", "6-AI判定规则", "降低假阳性。"],
  ["P2", "采集校验", "每站点参考非广告 ASIN", "建议", "提供 1-3 个可用于进入类目路径的非广告商品 ASIN 或链接。", "未覆盖", "3-目标类目URL", "URL 失效时可人工/自动兜底定位。"],
  ["P2", "采集校验", "类目样本截图或路径截图", "建议", "提供每个站点 BSR 路径截图，便于技术侧校验页面位置。", "未覆盖", "3-目标类目URL", "降低类目定位误差。"],
  ["P2", "报告分析", "重点关注 ASIN/品牌", "建议", "业务指定重点观察对象，可在周报中置顶展示。", "未覆盖", "建议新增 Sheet", "周报更贴合业务关注。"],
  ["P2", "报告分析", "大促/活动日历", "建议", "Prime Day、黑五、站内活动、新品发布等时间点。", "未覆盖", "建议新增 Sheet", "解释份额波动原因。"],
  ["P2", "质量控制", "手工抽检规则", "建议", "每周抽检几个站点/几个 ASIN，谁确认，允许误差范围。", "未覆盖", "建议新增到说明", "提升数据可信度。"],
  ["P2", "权限管理", "数据访问权限名单", "建议", "谁可查看原始报告、账号资料、周报和看板。", "未覆盖", "7-交付配置", "避免敏感信息扩散。"],
  ["P2", "备份机制", "备用浏览器/备用设备", "建议", "主环境不可用时的备用环境、备用账号和切换流程。", "部分未填", "1/2/7", "减少任务中断。"],

  ["P3", "自动化升级", "卖家精灵 API 或导出接口", "可选", "如卖家精灵支持官方 API，提供 API 文档、Key、额度和合规许可。", "未覆盖", "1-卖家精灵账号", "减少插件点击依赖。"],
  ["P3", "自动化升级", "无人值守运行机器", "可选", "固定执行机器、运行时间窗口、系统权限和维护人。", "未覆盖", "建议二期补充", "支持全自动周度运行。"],
  ["P3", "看板化", "BI/数据看板需求", "可选", "指标口径、筛选维度、访问权限、刷新频率。", "部分提及，未配置", "7-交付配置", "支持长期趋势可视化。"],
  ["P3", "告警升级", "精细化告警规则", "可选", "按站点、品牌、ASIN、AI 市占、新入榜 ASIN 等配置差异化阈值。", "仅有默认阈值", "7-交付配置", "减少无效告警，突出关键变化。"],
  ["P3", "数据仓库", "长期数据沉淀方案", "可选", "数据库、数据表、字段字典、保留周期、备份策略。", "未覆盖", "建议二期补充", "支持年度趋势和复盘。"],
  ["P3", "多语言扩展", "本地语义词库维护机制", "可选", "多语种 AI 表达、同义词、排除词由谁维护、多久更新。", "初稿未确认", "6-AI判定规则", "支持更多品类和语言扩展。"],
];

const gapRows = [
  ["优先级", "当前缺口", "当前文件情况", "影响", "建议补充动作", "建议负责人", "建议完成时间"],
  ["P0", "7 站点目标 BSR 类目 URL 未填", "Sheet 3 中 US/UK/DE/FR/IT/ES/JP 均为空，仅有 US 示例。", "无法稳定进入类目页，也无法下载正确类目报告。", "业务逐站复制最终 BSR 类目 URL，并填写类目完整路径和兜底搜索词。", "运营对接人", "Kick-off 前"],
  ["P0", "卖家精灵账号与权限未填", "Sheet 1 账号邮箱、订阅等级、导出额度、插件版本、到期日均为空。", "无法确认是否能下载市场分析 Excel，且可能导出额度不足。", "补充账号、权限、额度、插件版本、到期日和备用账号。", "业务负责人/运营", "Kick-off 前"],
  ["P0", "亚马逊买家账号未填", "Sheet 2 七个站点账号均为空。", "无法稳定浏览站点、进入 PDP 和 BSR 页面。", "补充账号、账号年龄、Prime 状态、建议邮编、语言设置。", "运营对接人", "Kick-off 前"],
  ["P0", "竞品品牌清单未填", "Sheet 5 仅有示例 Sony，无实际竞品。", "无法计算竞品品牌市占和竞品合计。", "每站点补充核心竞品品牌，标注优先级和是否纳入合计。", "业务负责人", "Kick-off 前"],
  ["P0", "交付渠道和责任人未填", "Sheet 7 webhook、邮箱、业务负责人、运营对接人等为空。", "周报无法推送，异常无法通知。", "确认启用渠道，填写 webhook/邮箱和各责任人联系方式。", "项目对接人", "Kick-off 前"],
  ["P0", "安全交付方式未定义", "原模板未明确账号密码、2FA、浏览器 Profile 的交付方式。", "存在账号交付和登录维护风险。", "明确通过密码管理器、企业安全渠道或指定人工登录交付。", "业务负责人/IT", "Kick-off 前"],
  ["P1", "PLAUD 别名未确认", "Sheet 4 有 5 个别名，但未见确认标记或归一化规则说明。", "可能造成 PLAUD 销量漏算或 AI 竞品误算。", "确认每个别名是否归入 PLAUD，并补充自有 ASIN 清单。", "运营对接人", "试跑前"],
  ["P1", "AI 判定边界未确认", "Sheet 6 关键词有初稿，但确认列为空；边界场景为空。", "AI 竞品筛选存在误匹配和口径争议。", "逐项确认 AI Translation、Noise Cancellation、ChatGPT/GPT、Smart 等场景。", "业务负责人/产品", "试跑前"],
  ["P1", "历史数据未准备", "当前工作簿未收集上一周或 8-12 周历史报告。", "无法做周环比或长期趋势分析。", "提供上一周原始 Excel；推荐补齐 8-12 周历史数据。", "运营对接人", "首份周报前"],
  ["P1", "金额和汇率口径缺失", "当前工作簿未覆盖币种、汇率来源、含税口径。", "跨站点销售额不可比较，销售额趋势可能口径不一致。", "确认保留本币或换算 USD/RMB，提供汇率来源和周期。", "业务/财务", "首份周报前"],
  ["P1", "采集时间和交付 SLA 未明确", "Sheet 7 仅示例推荐周一 10 点，未明确正式时间。", "任务调度和业务预期不一致。", "确认每周采集时间、周报输出时间、时区和节假日处理。", "业务负责人", "试跑前"],
  ["P1", "异常处理 SOP 缺失", "未覆盖验证码、登录失效、插件失败、类目变更处理方式。", "采集中断时无法快速恢复。", "补充异常类型、处理人、处理时限和重跑规则。", "项目对接人/运营", "试跑前"],
  ["P1", "原始报告存储与命名规则缺失", "当前工作簿未定义每周 Excel 保存位置和文件命名。", "历史追溯和重算困难。", "确认存储路径、权限和命名规则：YYYY-WW_站点_类目_SellerSprite.xlsx。", "项目对接人", "首份周报前"],
  ["P2", "竞品别名和母公司映射缺失", "Sheet 5 尚未填写竞品，更无别名映射。", "品牌集中度统计可能被大小写/子品牌拆分。", "补充竞品别名、子品牌和母公司字段。", "业务负责人", "首月内"],
  ["P2", "大促/活动日历缺失", "当前工作簿未覆盖业务活动日历。", "趋势波动解释不足。", "补充 Prime Day、黑五、新品发布、站内活动等日历。", "运营对接人", "首月内"],
  ["P3", "BI 看板与 API 自动化未定义", "Sheet 7 仅提到看板可二期建设；Sheet 1 API 是否允许未选择。", "长期自动化和看板化需要二期评估。", "稳定跑通后再确认 API、看板指标和数据仓库方案。", "项目负责人", "二期规划"],
];

function rangeFor(startCol, startRow, rows, cols) {
  const colName = (num) => {
    let s = "";
    while (num > 0) {
      const rem = (num - 1) % 26;
      s = String.fromCharCode(65 + rem) + s;
      num = Math.floor((num - 1) / 26);
    }
    return s;
  };
  const endCol = startCol + cols - 1;
  const endRow = startRow + rows - 1;
  return `${colName(startCol)}${startRow}:${colName(endCol)}${endRow}`;
}

function applyTitle(sheet, title, subtitle) {
  sheet.getRange("A1:H1").values = [[title, "", "", "", "", "", "", ""]];
  sheet.getRange("A2:H2").values = [[subtitle, "", "", "", "", "", "", ""]];
  sheet.getRange("A1:H1").merge();
  sheet.getRange("A2:H2").merge();
  sheet.getRange("A1:H1").format = {
    fill: "#1F4D78",
    font: { name: "Microsoft YaHei", size: 16, color: "#FFFFFF", bold: true },
    horizontalAlignment: "left",
    verticalAlignment: "center",
  };
  sheet.getRange("A2:H2").format = {
    fill: "#EAF2F8",
    font: { name: "Microsoft YaHei", size: 10, color: "#1F2937" },
    horizontalAlignment: "left",
    verticalAlignment: "center",
    wrapText: true,
  };
  sheet.getRange("A1:H1").format.rowHeightPx = 28;
  sheet.getRange("A2:H2").format.rowHeightPx = 34;
}

function applyTableStyle(sheet, rangeA1, headerRows = 1) {
  const range = sheet.getRange(rangeA1);
  range.format = {
    font: { name: "Microsoft YaHei", size: 10, color: "#1F2937" },
    borders: { preset: "all", style: "thin", color: "#D9E2EC" },
    verticalAlignment: "center",
    wrapText: true,
  };
  const header = sheet.getRange(rangeA1).getRowsAbove ? null : null;
  // Header rows are formatted by explicit ranges below because artifact-tool's
  // simple API keeps this builder portable across versions.
}

function styleHeader(sheet, rangeA1) {
  sheet.getRange(rangeA1).format = {
    fill: "#F2F4F7",
    font: { name: "Microsoft YaHei", size: 10, color: "#1F4D78", bold: true },
    borders: { preset: "all", style: "thin", color: "#D9E2EC" },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    wrapText: true,
  };
}

function stylePriorityColumn(sheet, startRow, endRow) {
  for (let r = startRow; r <= endRow; r += 1) {
    const value = sheet.getRange(`A${r}:A${r}`).values?.[0]?.[0];
    let fill = "#FFFFFF";
    let color = "#1F2937";
    if (value === "P0") {
      fill = "#FCE4D6";
      color = "#9C0006";
    } else if (value === "P1") {
      fill = "#FFF2CC";
      color = "#7A5A00";
    } else if (value === "P2") {
      fill = "#E2F0D9";
      color = "#375623";
    } else if (value === "P3") {
      fill = "#DDEBF7";
      color = "#1F4E79";
    }
    sheet.getRange(`A${r}:A${r}`).format = {
      fill,
      font: { name: "Microsoft YaHei", size: 10, color, bold: true },
      horizontalAlignment: "center",
      verticalAlignment: "center",
      borders: { preset: "all", style: "thin", color: "#D9E2EC" },
    };
  }
}

const input = await FileBlob.load(INPUT);
const workbook = await SpreadsheetFile.importXlsx(input);

const checklist = workbook.worksheets.add("0-完整资源清单");
applyTitle(
  checklist,
  "完整资源准备清单（按重要等级）",
  "P0 为启动必需，P1 为正式上线必需，P2 为准确性/稳定性增强，P3 为二期优化。请业务方按优先级补齐。"
);

checklist.getRange(`A4:C${3 + priorityDefinitions.length}`).values = priorityDefinitions;
applyTableStyle(checklist, `A4:C${3 + priorityDefinitions.length}`);
styleHeader(checklist, "A4:C4");
stylePriorityColumn(checklist, 5, 8);

const startRow = 11;
const allRows = [
  ["重要等级", "模块", "资源项", "必填性", "业务方需提供内容", "当前状态", "填写位置/建议位置", "验收标准/用途"],
  ...checklistRows,
];
checklist.getRange(rangeFor(1, startRow, allRows.length, 8)).values = allRows;
applyTableStyle(checklist, rangeFor(1, startRow, allRows.length, 8));
styleHeader(checklist, `A${startRow}:H${startRow}`);
stylePriorityColumn(checklist, startRow + 1, startRow + allRows.length - 1);

checklist.getRange("A:A").format.columnWidthPx = 70;
checklist.getRange("B:B").format.columnWidthPx = 110;
checklist.getRange("C:C").format.columnWidthPx = 160;
checklist.getRange("D:D").format.columnWidthPx = 75;
checklist.getRange("E:E").format.columnWidthPx = 340;
checklist.getRange("F:F").format.columnWidthPx = 125;
checklist.getRange("G:G").format.columnWidthPx = 150;
checklist.getRange("H:H").format.columnWidthPx = 260;
checklist.freezePanes.freezeRows(startRow);

const gaps = workbook.worksheets.add("0-当前缺口追踪");
applyTitle(
  gaps,
  "当前缺口追踪（基于现有填写情况）",
  "本表按当前文件内容核对生成，用于业务方快速补齐最影响启动和上线的资源。"
);
gaps.getRange(rangeFor(1, 4, gapRows.length, 7)).values = gapRows;
applyTableStyle(gaps, rangeFor(1, 4, gapRows.length, 7));
styleHeader(gaps, "A4:G4");
stylePriorityColumn(gaps, 5, gapRows.length + 3);
gaps.getRange("A:A").format.columnWidthPx = 70;
gaps.getRange("B:B").format.columnWidthPx = 210;
gaps.getRange("C:C").format.columnWidthPx = 280;
gaps.getRange("D:D").format.columnWidthPx = 250;
gaps.getRange("E:E").format.columnWidthPx = 330;
gaps.getRange("F:F").format.columnWidthPx = 125;
gaps.getRange("G:G").format.columnWidthPx = 115;
gaps.freezePanes.freezeRows(4);

// Add a short note to the original instruction sheet without changing its existing template.
const instruction = workbook.worksheets.getItem("说明");
instruction.getRange("A25:F29").values = [
  ["补充说明", "", "", "", "", ""],
  ["本补充版新增 Sheet：0-完整资源清单、0-当前缺口追踪。", "", "", "", "", ""],
  ["请优先补齐 P0 项，再补 P1 项。P2/P3 可在试跑或稳定运行后逐步完善。", "", "", "", "", ""],
  ["重要等级定义：P0=启动必需；P1=正式上线必需；P2=准确性/稳定性增强；P3=二期优化。", "", "", "", "", ""],
  ["", "", "", "", "", ""],
];
instruction.getRange("A25:F28").format = {
  fill: "#EAF2F8",
  font: { name: "Microsoft YaHei", size: 10, color: "#1F2937" },
  borders: { preset: "outside", style: "thin", color: "#D9E2EC" },
  wrapText: true,
};
instruction.getRange("A25:F25").format = {
  fill: "#1F4D78",
  font: { name: "Microsoft YaHei", size: 11, color: "#FFFFFF", bold: true },
};

await fs.mkdir("/Users/plaud/Documents/New project", { recursive: true });
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(OUTPUT);
console.log(OUTPUT);
