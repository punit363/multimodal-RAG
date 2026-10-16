import { readdir, readFile } from "node:fs/promises";
import path from "node:path";

const cssDirectory = path.join(".next", "static", "css");
const cssFiles = (await readdir(cssDirectory)).filter((file) => file.endsWith(".css"));
const stylesheets = await Promise.all(
  cssFiles.map((file) => readFile(path.join(cssDirectory, file), "utf8"))
);
const css = stylesheets.join("\n");

if (cssFiles.length === 0 || css.includes("@tailwind utilities")) {
  throw new Error("Production CSS contains unprocessed Tailwind directives.");
}

for (const utility of [".flex{", ".min-h-screen{", ".text-xs{"]) {
  if (!css.includes(utility)) {
    throw new Error(`Production CSS is missing the expected ${utility} utility.`);
  }
}

console.log("Production Tailwind CSS is compiled.");
