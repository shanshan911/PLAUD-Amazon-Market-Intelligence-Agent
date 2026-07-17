import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const OUTPUT = "/Users/plaud/Documents/New project/PLAUD_监控Agent_资源准备清单_补充版.xlsx";
const input = await FileBlob.load(OUTPUT);
const workbook = await SpreadsheetFile.importXlsx(input);

const summary = await workbook.inspect({
  kind: "table",
  range: "0-完整资源清单!A1:H22",
  include: "values",
  tableMaxRows: 22,
  tableMaxCols: 8,
});
console.log(summary.ndjson);

const gaps = await workbook.inspect({
  kind: "table",
  range: "0-当前缺口追踪!A1:G18",
  include: "values",
  tableMaxRows: 18,
  tableMaxCols: 7,
});
console.log(gaps.ndjson);

const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 100 },
  summary: "formula error scan",
});
console.log(errors.ndjson);
