import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const input = await FileBlob.load("/Users/plaud/Downloads/PLAUD_监控Agent_资源准备清单.xlsx");
const workbook = await SpreadsheetFile.importXlsx(input);
console.log(Object.keys(workbook));
console.log("worksheets", workbook.worksheets?.length, Object.keys(workbook.worksheets || {}));
console.log(await workbook.inspect({ kind: "table", range: "说明!A1:F8", include: "values", tableMaxRows: 8, tableMaxCols: 6 }).then(r => r.ndjson));
