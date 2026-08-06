const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.resolve(__dirname, "../..");

test("the page quick jumper does not filter or reload the metrics table", () => {
  const source = fs.readFileSync(path.join(root, "static/js/pages/pages-analytics.js"), "utf8");
  const quickJumperInputReferences = source.match(/pages-global-search/g) || [];

  assert.equal(quickJumperInputReferences.length, 1);
  assert.doesNotMatch(source, /getOverviewSearch/);
  assert.match(
    source,
    /function getVisibleChangeRows\(rows\) \{\s*return sortChangeRows\(rows, getChangeTableSort\(\)\);\s*\}/
  );
});

test("quick jumpers use the shared clear button and refresh results after reset", () => {
  const partial = fs.readFileSync(path.join(root, "templates/partials/overview_quick_jumper.html"), "utf8");
  const script = fs.readFileSync(path.join(root, "static/js/shared/overview-quick-jumper.js"), "utf8");

  assert.match(partial, /data-overview-quick-jumper-reset/);
  assert.match(partial, /m329\.08-286\.54-42\.54-42\.54L437\.46-480/);
  assert.match(script, /reset\.hidden = input\.value\.length === 0/);
  assert.match(script, /input\.value = ""/);
  assert.match(script, /input\.dispatchEvent\(new globalScope\.Event\("input", \{ bubbles: true \}\)\)/);
  assert.match(script, /input\.focus\(\)/);
});
