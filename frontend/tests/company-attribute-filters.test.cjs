const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const filters = require("../../static/js/shared/company-attribute-filters.js");
const root = path.resolve(__dirname, "../..");
const source = fs.readFileSync(
  path.join(root, "static/js/shared/company-attribute-filters.js"),
  "utf8"
);
const styles = fs.readFileSync(
  path.join(root, "static/css/company-attribute-filters.css"),
  "utf8"
);
const dialogTemplate = fs.readFileSync(
  path.join(root, "templates/partials/company_attribute_filter_dialog.html"),
  "utf8"
);
const segmentsSource = fs.readFileSync(
  path.join(root, "static/js/shared/company-segments.js"),
  "utf8"
);

function fixtureAttributes() {
  return filters.normalizeAttributes([
    {
      id: 10,
      name: "Plan",
      type: "single_select",
      type_label: "Select",
      options: [
        { id: 22, label: "Business" },
        { id: 11, label: "Enterprise" },
      ],
    },
    { id: 2, name: "ARR", type: "money", currency: "USD" },
    { id: 3, name: "Seats", type: "number" },
    { id: 4, name: "Notes", type: "text" },
    { id: 5, name: "Renewal", type: "date" },
    { id: 6, name: "Strategic", type: "boolean" },
  ]);
}

test("metadata normalization keeps numeric IDs and the complete typed operator contract", () => {
  const attributes = fixtureAttributes();
  const plan = attributes.find((attribute) => attribute.id === "10");
  const money = attributes.find((attribute) => attribute.id === "2");
  const text = attributes.find((attribute) => attribute.id === "4");
  const date = attributes.find((attribute) => attribute.id === "5");

  assert.equal(plan.typeLabel, "Select");
  assert.deepEqual(plan.operators.map(([code]) => code), ["in", "not_in", "empty", "not_empty"]);
  assert.deepEqual(
    money.operators.map(([code]) => code),
    ["eq", "gt", "gte", "lt", "lte", "between", "empty", "not_empty"]
  );
  assert.deepEqual(
    text.operators.map(([code]) => code),
    ["contains", "not_contains", "eq", "neq", "empty", "not_empty"]
  );
  assert.deepEqual(
    date.operators.map(([code]) => code),
    ["on", "before", "after", "between", "empty", "not_empty"]
  );
});

test("draft validation covers all types and counts rows rather than select values", () => {
  const attributes = fixtureAttributes();
  const valid = {
    10: { op: "in", values: ["22", "11"] },
    2: { op: "gte", value: "250000.01" },
    3: { op: "between", min: "10", max: "20" },
    4: { op: "contains", value: " customer " },
    5: { op: "between", from: "2026-07-01", to: "2026-07-31" },
    6: { op: "eq", value: "true" },
  };

  assert.deepEqual(filters.validateDraft(attributes, valid), {
    valid: true,
    errors: {},
    activeCount: 6,
  });

  const invalid = structuredClone(valid);
  invalid[10].values = [];
  invalid[2] = { op: "between", min: "10000000000000000000.01", max: "10000000000000000000.001" };
  invalid[3] = { op: "eq", value: "100000000000000000000" };
  invalid[4].value = "   ";
  invalid[5].from = "2026-08-01";
  invalid[6].value = "maybe";
  const result = filters.validateDraft(attributes, invalid);

  assert.equal(result.valid, false);
  assert.equal(result.activeCount, 6);
  assert.match(result.errors["10"], /Select at least one option/);
  assert.match(result.errors["2"], /lower bound/);
  assert.match(result.errors["3"], /valid number/);
  assert.match(result.errors["4"], /Enter text/);
  assert.match(result.errors["5"], /start date/);
  assert.match(result.errors["6"], /Yes or No/);
});

test("money range comparison uses exact decimal strings", () => {
  assert.equal(
    filters.compareDecimalStrings("100000000000000000000.01", "100000000000000000000.001"),
    1
  );
  assert.equal(filters.compareDecimalStrings("-0.100", "-0.1"), 0);
  assert.equal(filters.compareDecimalStrings("-1.000000000000000001", "-1"), -1);
  assert.equal(filters.compareDecimalStrings("not-a-number", "1"), null);
});

test("canonical URL pairs are deterministic and use repeated numeric option IDs", () => {
  const pairs = filters.canonicalPairs(fixtureAttributes(), {
    10: { op: "in", values: ["22", "11", "22"] },
    2: { op: "between", min: " 100.10 ", max: " 200.20 " },
    5: { op: "empty" },
    6: { op: "eq", value: "false" },
  });

  assert.deepEqual(pairs, [
    ["ca.2.op", "between"],
    ["ca.2.min", "100.10"],
    ["ca.2.max", "200.20"],
    ["ca.5.op", "empty"],
    ["ca.6.op", "eq"],
    ["ca.6.value", "false"],
    ["ca.10.op", "in"],
    ["ca.10.value", "11"],
    ["ca.10.value", "22"],
  ]);
});

test("Apply replaces only ca params, preserves unrelated repeated params, and resets page", () => {
  const next = new URL(filters.buildApplyUrl(
    "https://example.test/companies/?range=last_30_days&product_area=core&product_area=billing&ca.99.op=empty&page=4#table",
    fixtureAttributes(),
    {
      10: { op: "not_in", values: ["22", "11"] },
      4: { op: "eq", value: "  Exact text  " },
    }
  ));

  assert.equal(next.searchParams.get("range"), "last_30_days");
  assert.deepEqual(next.searchParams.getAll("product_area"), ["core", "billing"]);
  assert.equal(next.searchParams.has("page"), false);
  assert.equal(next.searchParams.has("ca.99.op"), false);
  assert.equal(next.searchParams.get("ca.10.op"), "not_in");
  assert.deepEqual(next.searchParams.getAll("ca.10.value"), ["11", "22"]);
  assert.equal(next.searchParams.get("ca.4.value"), "Exact text");
  assert.equal(next.hash, "#table");
});

test("preview requests share current scope and draft ca pairs without pagination", () => {
  const preview = new URL(filters.buildPreviewUrl(
    "/filters/preview/?format=json",
    "https://example.test/pages/?range=last_90_days&product_area=core&product_area=billing&page=3&ca.2.op=empty",
    "pages",
    fixtureAttributes(),
    { 3: { op: "gte", value: "50" } }
  ));

  assert.equal(preview.pathname, "/filters/preview/");
  assert.equal(preview.searchParams.get("format"), "json");
  assert.equal(preview.searchParams.get("surface"), "pages");
  assert.equal(preview.searchParams.has("page"), false);
  assert.deepEqual(preview.searchParams.getAll("product_area"), ["core", "billing"]);
  assert.equal(preview.searchParams.has("ca.2.op"), false);
  assert.equal(preview.searchParams.get("ca.3.op"), "gte");
  assert.equal(preview.searchParams.get("ca.3.value"), "50");
});

test("dialog code maintains applied and draft state, stale-safe debounced preview, and focus restoration", () => {
  assert.match(source, /draft = cloneState\(initialApplied\)/);
  assert.match(source, /var PREVIEW_DELAY_MS = 350/);
  assert.match(source, /new view\.AbortController\(\)/);
  assert.match(source, /requestSequence !== previewSequence/);
  assert.match(source, /anchor\.focus\(\)/);
  assert.match(source, /event\.key === "Escape"[\s\S]*closeDialog\(true\)/);
  assert.match(source, /documentRef\.addEventListener\("pointerdown"[\s\S]*closeDialog\(false\)/);
  // Committing a scope belongs to the segments controller now.
  assert.doesNotMatch(source, /location\.assign/);
  assert.match(segmentsSource, /view\.location\.assign\(next\.href\)/);
});

test("dialog validation waits for a submit and never disables its actions", () => {
  // Only rows the last submission flagged show a message, and editing a row
  // drops it again, so nothing appears on open, on typing, or on blur.
  assert.match(source, /var message = errorAttributeIds\.has\(attributeId\)/);
  assert.match(source, /errorAttributeIds = new Set\(Object\.keys\(validation\.errors\)\);/);
  assert.match(source, /function noteDraftEdit\(attributeId\) \{\s*errorAttributeIds\.delete/);
  assert.doesNotMatch(source, /addEventListener\("blur"/);
  assert.doesNotMatch(source, /apply\.disabled/);
  assert.doesNotMatch(source, /\.disabled = !validation\.valid/);
  // The only guard is the in-flight one, applied after a valid submission.
  assert.match(source, /control\.disabled = pending;/);
  assert.match(source, /documentElement\.dataset\.companyScopeBusy = "true"/);
});

test("Clear sits beside the match count and the AND note panel is gone", () => {
  // The standalone note above the rows was removed; the AND rule is documented
  // rather than repeated in a panel on every open.
  assert.doesNotMatch(dialogTemplate, /combined with AND/);
  assert.doesNotMatch(dialogTemplate, /company-attribute-filter-logic-note/);

  const heading = dialogTemplate.slice(
    dialogTemplate.indexOf("attribute-filter-preview-heading"),
    dialogTemplate.indexOf("attribute-filter-preview-track")
  );
  assert.match(heading, /data-attribute-filter-preview-label/);
  assert.match(heading, /data-attribute-filter-reset hidden>Clear</);

  // Visible only while the draft has something to clear, which also hides it
  // again the moment it is used.
  assert.match(source, /if \(reset\) reset\.hidden = validation\.activeCount === 0;/);
});

test("selected-option clear button stays visually centered in its field", () => {
  const rule = styles.slice(
    styles.indexOf(".attribute-filter-multiselect-clear {"),
    styles.indexOf(".attribute-filter-multiselect-clear:hover")
  );

  assert.match(rule, /top: 50%;/);
  assert.match(rule, /align-items: center;/);
  assert.match(rule, /justify-content: center;/);
  assert.match(rule, /transform: translateY\(-50%\);/);
});

test("select option search uses the compact placeholder", () => {
  assert.match(source, /placeholder="Search…"/);
  assert.doesNotMatch(source, /placeholder="Search options…"/);
});

test("editing a saved segment is labelled as such", () => {
  assert.match(source, /"Edit company segment"/);
  assert.match(source, /actionButtonHtml\("save-changes", "Save changes", "primary"\)/);
  // Apply and Save as segment… belong to filtering, not to editing a segment.
  assert.match(
    source,
    /if \(mode === "edit-segment"\) \{[\s\S]*?"Cancel", "secondary"\)\s*\+ actionButtonHtml\("save-changes"[\s\S]*?\}\s*return \(canSaveSegments/
  );
  assert.match(source, /"Using segment: " \+ session\.segment\.name/);
  assert.match(source, /"Custom filter based on " \+ session\.segment\.name \+ "\. The saved segment won’t be changed\."/);
});

test("no-attributes state is exact and omits AND note, footer, and Apply in its branch", () => {
  const emptyBranch = dialogTemplate.slice(dialogTemplate.lastIndexOf("{% else %}"));

  assert.match(emptyBranch, />No company attributes yet</);
  assert.match(
    emptyBranch,
    /Create and set company attributes in project settings\. Once configured, you can use them here to filter companies\./
  );
  assert.match(emptyBranch, />Go to company attribute settings</);
  assert.doesNotMatch(emptyBranch, /attribute-filter-preview/);
  assert.doesNotMatch(emptyBranch, /company-attribute-filter-footer/);
  assert.doesNotMatch(emptyBranch, /data-attribute-filter-actions/);
});

test("only the four overview templates include the shared filter UI", () => {
  const overviewTemplates = [
    "apps/projects/templates/projects/companies.html",
    "apps/projects/templates/projects/users.html",
    "apps/pages/templates/pages/overview.html",
    "apps/tracker/templates/tracker/visits.html",
  ];
  const detailTemplates = [
    "apps/projects/templates/projects/company_detail.html",
    "apps/projects/templates/projects/user_detail.html",
    "apps/pages/templates/pages/detail.html",
    "apps/tracker/templates/tracker/recording.html",
  ];

  overviewTemplates.forEach((relativePath) => {
    const template = fs.readFileSync(path.join(root, relativePath), "utf8");
    assert.match(template, /company_scope_selector\.html/, relativePath);
    assert.match(template, /company_attribute_filter_summary\.html/, relativePath);
    assert.match(template, /company_attribute_filter_dialog\.html/, relativePath);
    assert.match(template, /js\/shared\/company-segments\.js/, relativePath);
  });
  detailTemplates.forEach((relativePath) => {
    const template = fs.readFileSync(path.join(root, relativePath), "utf8");
    assert.doesNotMatch(
      template,
      /company_(?:scope_selector|attribute_filter_summary|attribute_filter_dialog)\.html/,
      relativePath
    );
  });
});

test("overview AJAX adapters forward all repeated ca params while detail adapters stay untouched", () => {
  [
    "static/js/companies/django-companies-data.js",
    "static/js/users/django-users-data.js",
    "static/js/pages/django-pages-data.js",
    "static/js/tracker/visits-filters.js",
  ].forEach((relativePath) => {
    const adapter = fs.readFileSync(path.join(root, relativePath), "utf8");
    assert.match(adapter, /function appendCompanyAttributeParams/, relativePath);
    assert.match(adapter, /startsWith\("ca\."\)/, relativePath);
    assert.match(adapter, /searchParams\.append\(key, value\)/, relativePath);
  });
});
