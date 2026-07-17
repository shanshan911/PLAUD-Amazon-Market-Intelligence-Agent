import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const OUTPUT = "/Users/plaud/Documents/New project/PLAUD_监控Agent_资源准备清单_补充版.xlsx";
const input = await FileBlob.load(OUTPUT);
const workbook = await SpreadsheetFile.importXlsx(input);

await fs.mkdir("/Users/plaud/Documents/New project/rendered_workbook_checks", { recursive: true });
const image1 = await workbook.render({
  sheetName: "0-完整资源清单",
  range: "A1:H40",
  scale: 1,
});
await fs.writeFile(
  "/Users/plaud/Documents/New project/rendered_workbook_checks/完整资源清单.png",
  Buffer.from(await image1.arrayBuffer())
);

const image2 = await workbook.render({
  sheetName: "0-当前缺口追踪",
  range: "A1:G20",
  scale: 1,
});
await fs.writeFile(
  "/Users/plaud/Documents/New project/rendered_workbook_checks/当前缺口追踪.png",
  Buffer.from(await image2.arrayBuffer())
);

console.log("rendered");
