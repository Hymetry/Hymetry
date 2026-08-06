const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const source = fs.readFileSync(
  path.resolve(__dirname, "../../static/js/projects/company-attributes.js"),
  "utf8"
);
const styles = fs.readFileSync(
  path.resolve(__dirname, "../../static/css/projects/company-attributes.css"),
  "utf8"
);

function sourceBetween(startMarker, endMarker) {
  const start = source.indexOf(startMarker);
  const end = source.indexOf(endMarker, start);
  assert.notEqual(start, -1, `Missing source marker: ${startMarker}`);
  assert.notEqual(end, -1, `Missing source marker: ${endMarker}`);
  return source.slice(start, end);
}

test("company attribute table values do not create native title tooltips", () => {
  const tableSource = sourceBetween(
    "function companyLink(company)",
    "function paginationHtml()"
  );

  assert.doesNotMatch(tableSource, /\btitle=/);
});

test("company attribute columns fill available width, stop content at a maximum, and wrap", () => {
  const tableRule = styles.match(/\.company-attributes-table\s*{[^}]*}/s)[0];

  assert.doesNotMatch(source, /function attributeColumnWidth\(/);
  assert.doesNotMatch(source, /function attributeTableWidth\(/);
  assert.doesNotMatch(source, /function tableColgroup\(/);
  assert.match(tableRule, /width:\s*max-content;/);
  assert.match(tableRule, /min-width:\s*100%;/);
  assert.match(tableRule, /table-layout:\s*auto;/);
  assert.match(styles, /\.company-attributes-company-column\s*{[^}]*max-width:\s*var\(--company-attributes-company-max-width\);/s);
  assert.match(styles, /\.company-attributes-value-column\s*{[^}]*max-width:\s*var\(--company-attributes-value-max-width\);/s);
  assert.match(styles, /\.company-attributes-value\s*{[^}]*overflow-wrap:\s*anywhere;[^}]*white-space:\s*normal;/s);
});
