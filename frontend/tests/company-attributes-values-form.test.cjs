const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const source = fs.readFileSync(
  path.resolve(__dirname, "../../static/js/projects/company-attributes.js"),
  "utf8"
);

function sourceBetween(startMarker, endMarker) {
  const start = source.indexOf(startMarker);
  const end = source.indexOf(endMarker, start);
  assert.notEqual(start, -1, `Missing source marker: ${startMarker}`);
  assert.notEqual(end, -1, `Missing source marker: ${endMarker}`);
  return source.slice(start, end);
}

test("company value labels do not activate their inputs or pickers", () => {
  const valuesFormSource = sourceBetween(
    "function inputId(attribute)",
    "function openValues(companyId)"
  );

  assert.match(valuesFormSource, /function valueLabelId\(attribute\)/);
  assert.match(valuesFormSource, /aria-labelledby=/);
  assert.match(valuesFormSource, /<span class="attributes-form-label" id=/);
  assert.doesNotMatch(valuesFormSource, /<label class="attributes-form-label"/);
});

test("enhanced value pickers retain the static label as an accessible name", () => {
  const selectSource = sourceBetween(
    "function enhanceAttributesSelect(select, index)",
    "function enhanceAttributesSelects(container)"
  );

  assert.match(selectSource, /const labelledBy = select\.getAttribute\("aria-labelledby"\)/);
  assert.match(selectSource, /trigger\.setAttribute\("aria-labelledby", labelledBy \+ " " \+ triggerLabel\.id\)/);
  assert.match(selectSource, /menu\.setAttribute\("aria-labelledby", labelledBy\)/);
});
