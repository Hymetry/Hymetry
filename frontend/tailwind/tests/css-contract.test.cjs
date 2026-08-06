const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const packageRoot = path.resolve(__dirname, "..");
const repositoryRoot = path.resolve(packageRoot, "..", "..");
const outputPath = path.join(repositoryRoot, "static", "css", "output.css");

assert.ok(fs.existsSync(outputPath), "Build static/css/output.css before running the CSS contract test");

const outputCss = fs.readFileSync(outputPath, "utf8");

function walkCssFiles(directory) {
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const entryPath = path.join(directory, entry.name);
    if (entry.isDirectory()) return walkCssFiles(entryPath);
    if (entry.isFile() && entry.name.endsWith(".css") && entryPath !== outputPath) return [entryPath];
    return [];
  });
}

const handwrittenCss = [
  path.join(packageRoot, "input.css"),
  ...walkCssFiles(path.join(repositoryRoot, "static", "css")),
]
  .map((filePath) => fs.readFileSync(filePath, "utf8"))
  .join("\n");

const referencedColorVariables = new Set(
  [...handwrittenCss.matchAll(/var\((--color-[A-Za-z0-9-]+)/g)].map((match) => match[1]),
);
const emittedColorVariables = new Set(
  [...outputCss.matchAll(/(--color-[A-Za-z0-9-]+)\s*:/g)].map((match) => match[1]),
);
const missingColorVariables = [...referencedColorVariables]
  .filter((variable) => !emittedColorVariables.has(variable))
  .sort();

assert.deepEqual(
  missingColorVariables,
  [],
  `Tailwind output is missing color variables used by handwritten CSS: ${missingColorVariables.join(", ")}`,
);

for (const utility of ["scale-95", "scale-100"]) {
  assert.match(outputCss, new RegExp(`\\.${utility}(?:[\\s:{])`), `Missing dynamic utility .${utility}`);
}

for (const component of [
  "page-shell",
  "status-badge",
  "workspace-role-picker-trigger",
  "workspace-role-picker-menu",
  "workspace-role-picker-option",
]) {
  assert.match(outputCss, new RegExp(`\\.${component}(?:[\\s:{])`), `Missing shared component .${component}`);
}

for (const status of [
  "trial_active",
  "trial_ends_soon",
  "paid_plan",
  "active",
  "trial_ended",
  "scheduled_for_deletion",
  "read_only",
  "setup_required",
]) {
  assert.match(
    outputCss,
    new RegExp(`data-status=["']?${status}["']?`),
    `Missing semantic badge styles for ${status}`,
  );
}

for (const productColor of [
  "blue",
  "orange",
  "red",
  "teal",
  "green",
  "rose",
  "purple",
  "light-blue",
  "brown",
]) {
  assert.ok(
    outputCss.includes(`.bg-c-${productColor}\\/90`),
    `Missing safelisted product-area utility .bg-c-${productColor}/90`,
  );
}

assert.ok(outputCss.includes("/static/fonts/InterVariable.woff2"), "The local Inter font is not in the compiled CSS");
assert.ok(!outputCss.includes("fonts.googleapis.com"), "Compiled CSS must not fetch Inter from Google Fonts");

console.log(
  `CSS contract passed: ${referencedColorVariables.size} color variables and dynamic utilities are available.`,
);
