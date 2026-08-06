const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const segments = require("../../static/js/shared/company-segments.js");
const filters = require("../../static/js/shared/company-attribute-filters.js");
const root = path.resolve(__dirname, "../..");
const source = fs.readFileSync(
  path.join(root, "static/js/shared/company-segments.js"),
  "utf8"
);
const filterSource = fs.readFileSync(
  path.join(root, "static/js/shared/company-attribute-filters.js"),
  "utf8"
);
const dialogStyles = fs.readFileSync(
  path.join(root, "static/css/company-attribute-filters.css"),
  "utf8"
);
const selectorTemplate = fs.readFileSync(
  path.join(root, "templates/partials/company_scope_selector.html"),
  "utf8"
);
const dialogsTemplate = fs.readFileSync(
  path.join(root, "templates/partials/company_segment_dialogs.html"),
  "utf8"
);

function fixtureAttributes() {
  return filters.normalizeAttributes([
    {
      id: 10,
      // A user may name an attribute after the feature itself; nothing may
      // treat that label as a system identifier.
      name: "Company segment",
      type: "single_select",
      options: [
        { id: 22, label: "Business" },
        { id: 11, label: "Enterprise" },
      ],
    },
    { id: 2, name: "ARR", type: "money", currency: "USD" },
  ]);
}

const enterpriseEurope = {
  id: "7",
  name: "Enterprise Europe",
  definition: { 10: { op: "in", values: ["11"] } },
};

test("definitions normalize away key order, duplicates, and whitespace", () => {
  const left = segments.normalizeDefinition({
    " 10 ": { op: "in", values: ["22", "11", "22"] },
    2: { op: "gte", value: "  250000  " },
  });

  assert.deepEqual(left, {
    2: { op: "gte", value: "250000" },
    10: { op: "in", values: ["11", "22"] },
  });
  assert.equal(segments.activeConditionCount(left), 2);
  assert.equal(
    segments.areDefinitionsEqual(left, {
      2: { op: "gte", value: "250000" },
      10: { op: "in", values: ["22", "11"] },
    }),
    true
  );
  assert.equal(segments.activeConditionCount({ 2: { op: "" } }), 0);
});

test("applying an unchanged draft keeps the saved segment active", () => {
  const scope = segments.scopeForSegment(enterpriseEurope);
  const next = segments.scopeAfterApplyingDraft(
    scope,
    { 10: { op: "in", values: ["11"] } },
    enterpriseEurope
  );

  assert.equal(next.type, "segment");
  assert.equal(next.segmentId, "7");
  assert.equal(next.segmentName, "Enterprise Europe");
});

test("applying a changed draft becomes a custom filter and leaves the segment alone", () => {
  const scope = segments.scopeForSegment(enterpriseEurope);
  const next = segments.scopeAfterApplyingDraft(
    scope,
    { 10: { op: "in", values: ["11", "22"] } },
    enterpriseEurope
  );

  assert.equal(next.type, "custom");
  assert.deepEqual(next.definition, { 10: { op: "in", values: ["11", "22"] } });
  assert.deepEqual(enterpriseEurope.definition, { 10: { op: "in", values: ["11"] } });
});

test("changing a value and restoring it counts as unchanged", () => {
  const scope = segments.scopeForSegment(enterpriseEurope);
  const edited = segments.scopeAfterApplyingDraft(
    scope,
    { 10: { op: "in", values: ["22"] } },
    enterpriseEurope
  );
  const restored = segments.scopeAfterApplyingDraft(
    scope,
    { 10: { op: "in", values: ["11"] } },
    enterpriseEurope
  );

  assert.equal(edited.type, "custom");
  assert.equal(restored.type, "segment");
});

test("applying an empty draft returns to All companies", () => {
  const next = segments.scopeAfterApplyingDraft(
    segments.scopeForSegment(enterpriseEurope),
    {},
    enterpriseEurope
  );

  assert.deepEqual(next, { type: "all", definition: {} });
});

test("deleting the active segment keeps its conditions as a custom filter", () => {
  const active = segments.scopeForSegment(enterpriseEurope);

  assert.deepEqual(segments.scopeAfterSegmentDelete(active, "7"), {
    type: "custom",
    definition: { 10: { op: "in", values: ["11"] } },
  });
  assert.deepEqual(segments.scopeAfterSegmentDelete(active, "8"), active);
});

test("segment names validate only what the server also enforces", () => {
  assert.deepEqual(segments.validateSegmentName("   "), {
    valid: false,
    name: "",
    message: "Enter a segment name.",
  });
  assert.deepEqual(segments.validateSegmentName("  Enterprise Europe  "), {
    valid: true,
    name: "Enterprise Europe",
    message: "",
  });
  assert.equal(segments.validateSegmentName("x".repeat(101), 100).valid, false);
  assert.equal(segments.validateSegmentName("x".repeat(100), 100).valid, true);
});

test("scope labels use the approved copy", () => {
  assert.equal(segments.scopeLabel({ type: "all" }), "All companies");
  assert.equal(segments.scopeLabel({ type: "custom" }), "Custom filter");
  assert.equal(
    segments.scopeLabel({ type: "segment", segmentName: "Strategic accounts" }),
    "Strategic accounts"
  );
});

test("attribute labels are never treated as system identifiers", () => {
  const attributes = fixtureAttributes();
  const segmentNamedAttribute = attributes.find((attribute) => attribute.id === "10");

  assert.equal(segmentNamedAttribute.name, "Company segment");
  assert.deepEqual(
    filters.canonicalPairs(attributes, { 10: { op: "in", values: ["11"] } }),
    [
      ["ca.10.op", "in"],
      ["ca.10.value", "11"],
    ]
  );
  assert.doesNotMatch(source, /=== "Company segment"/);
  assert.doesNotMatch(source, /attribute\.name ===/);
});

test("scope URLs carry the segment id only for a saved segment", () => {
  const href = "https://example.test/companies/?range=last_30_days&page=4&segment=3&ca.9.op=empty";
  const attributes = fixtureAttributes();

  const segmentUrl = new URL(filters.buildApplyUrl(href, attributes, enterpriseEurope.definition, "7"));
  assert.equal(segmentUrl.searchParams.get("segment"), "7");
  assert.equal(segmentUrl.searchParams.get("ca.10.op"), "in");
  assert.equal(segmentUrl.searchParams.has("page"), false);
  assert.equal(segmentUrl.searchParams.has("ca.9.op"), false);
  assert.equal(segmentUrl.searchParams.get("range"), "last_30_days");

  const customUrl = new URL(filters.buildApplyUrl(href, attributes, enterpriseEurope.definition));
  assert.equal(customUrl.searchParams.has("segment"), false);
  assert.equal(customUrl.searchParams.get("ca.10.op"), "in");

  const allUrl = new URL(filters.buildApplyUrl(href, attributes, {}));
  assert.equal(allUrl.searchParams.has("segment"), false);
  assert.equal(allUrl.searchParams.has("ca.10.op"), false);
  assert.equal(allUrl.searchParams.get("range"), "last_30_days");
});

test("segment mutations address segments by id through server-provided templates", () => {
  assert.match(source, /segmentUrl\("create"\)/);
  assert.match(source, /segmentUrl\("update", segment\.id\)/);
  assert.match(source, /segmentUrl\("delete", segment\.id\)/);
  assert.match(source, /template\.replace\("__segment_id__"/);
  assert.match(source, /"X-CSRFToken": csrfToken\(\)/);
});

test("popover renders the approved rows, counts, and actions", () => {
  [
    'label: "All companies"',
    "Company segments</div>",
    '"filter-attributes", "Filter by company attributes…"',
    '"save-current", "Save as segment…"',
    '"manage", "Manage segments"',
    '"Manage company segments"',
    '"Save company segment"',
    '"Rename company segment"',
    'layerButton("Delete segment", "delete", "danger")',
    'layerButton("Save & apply", "save-and-apply", "primary")',
    'layerButton("Rename", "rename", "primary")',
    "company-scope__match-count",
    " matching</span>",
  ].forEach((snippet) => {
    assert.ok(source.includes(snippet), `missing approved UI copy: ${snippet}`);
  });
  // A zero-match segment stays a normal, selectable row.
  assert.doesNotMatch(source, /matchingCompanyCount === 0/);
  assert.doesNotMatch(source, /company-scope__menu-item[^"]*" [^>]*disabled/);
});

test("Manage segments uses the reference settings icon", () => {
  assert.match(source, /manage:\s*[\r\n]+\s*'<svg[^']*<path d="m387\.69-100/);
  assert.doesNotMatch(source, /manage:\s*[\r\n]+\s*'<svg[^']*<path d="M200-160v-80h560/);
});

test("menu actions appear only when they can do something", () => {
  // Save as segment… needs an unsaved custom filter to save.
  assert.match(
    source,
    /if \(committedScope\.type === "custom"\) \{\s*markup \+= actionMarkup\("save-current", "Save as segment…"/
  );
  // Manage segments needs at least one saved segment.
  assert.match(
    source,
    /if \(segmentListState === "ready" && segments\.length\) \{\s*markup \+= actionMarkup\("manage", "Manage segments"/
  );
  // Filtering is always available, so it is outside both guards.
  assert.match(
    source,
    /markup \+= '<div class="company-scope__divider"><\/div>'\s*\+ actionMarkup\("filter-attributes"/
  );
});

test("a read-only surface lists segments without offering to change them", () => {
  // Listing and applying follows segmentsEnabled…
  assert.match(
    source,
    /if \(segmentsEnabled\) \{\s*markup \+= '<div class="company-scope__section-label">Company segments<\/div>'/
  );
  // …while every mutation follows canManageSegments, which the demo lacks.
  assert.match(
    source,
    /var canManageSegments = segmentsEnabled\s*&& Boolean\(payload\.canManageSegments\)\s*&& Boolean\(segmentUrls\.create\)/
  );
  assert.match(source, /if \(canManageSegments\) \{\s*if \(committedScope\.type === "custom"\) \{/);
  assert.match(source, /function handleBuilderSaveAs\(draft\) \{\s*if \(!canManageSegments\) return;/);
  assert.match(source, /function openManageDialog\(\) \{\s*if \(!canManageSegments\) return;/);
  assert.match(
    source,
    /function openSaveCurrentDialog\(\) \{\s*if \(!canManageSegments \|\| committedScope\.type !== "custom"\) return;/
  );
  assert.match(
    source,
    /function handleSegmentAction\(action, segmentId, returnKind\) \{\s*if \(!canManageSegments\) return;/
  );
  assert.match(source, /canSaveSegments: canManageSegments/);
  // Every dialog in the shell mutates a segment, so it renders only where that
  // is possible.
  assert.match(dialogsTemplate, /\{% if company_attribute_filter\.segments_manageable %\}/);
});

test("name validation runs on submit, not while typing", () => {
  assert.match(source, /function saveAndApplySegment\(button\) \{[\s\S]*var validation = submittedName\(\);/);
  assert.match(source, /function renameSegment\(button\) \{[\s\S]*var validation = submittedName\(\);/);
  assert.match(source, /if \(event\.target\.id === "company-segment-name"\) setNameError\(""\);/);
  assert.doesNotMatch(source, /addEventListener\("blur"/);
});

test("segment dialogs use the reference anchoring and dismiss from outside clicks", () => {
  assert.match(source, /triggerRect\.right - dialogWidth/);
  assert.match(source, /layerState\.kind === "manage"/);
  assert.match(source, /spaceBelow < 240 && spaceAbove > spaceBelow/);
  assert.match(source, /parentRect\s*\?\s*parentRect\.top \+ childOffset/);
  assert.match(source, /if \(event\.target === layer\) \{\s*dismissLayer\(true\);/);
  assert.match(source, /segmentDialog\.setAttribute\("aria-modal", kind === "manage" \? "false" : "true"\)/);
  assert.match(source, /view\.addEventListener\("scroll"[\s\S]*positionLayer\(\);[\s\S]*true\);/);

  assert.match(filterSource, /spaceBelow < 360 && spaceAbove > spaceBelow/);
  assert.match(filterSource, /--attribute-filter-popup-max-height", Math\.round\(availableHeight\)/);

  assert.match(dialogStyles, /\.company-segment-dialog-layer \{[\s\S]*overflow: visible;[\s\S]*background: transparent;/);
  assert.match(dialogStyles, /\.company-attribute-filter-dialog \{[\s\S]*min-height: 0;/);
});

test("segment action menus float outside the scrollable Manage dialog", () => {
  assert.match(
    dialogStyles,
    /\.company-segment-overflow-menu \{\s*position: fixed;\s*top: var\(--company-segment-menu-top[\s\S]*left: var\(--company-segment-menu-left/
  );
  assert.match(source, /function positionOverflowMenu\(overflow, menu\)/);
  assert.match(source, /spaceBelow >= menuRect\.height \|\| spaceBelow >= spaceAbove/);
  assert.match(source, /menu\.hidden = false;\s*positionOverflowMenu\(overflow, menu\);/);
});

test("the Companies selector renders before page filters and stays keyboard reachable", () => {
  assert.match(selectorTemplate, /data-company-scope-trigger/);
  assert.match(selectorTemplate, /aria-haspopup="menu"/);
  assert.match(selectorTemplate, /Companies:/);
  assert.match(dialogsTemplate, /csrf_token/);
  assert.match(dialogsTemplate, /data-company-segment-dialog-layer/);

  [
    "apps/projects/templates/projects/companies.html",
    "apps/projects/templates/projects/users.html",
    "apps/pages/templates/pages/overview.html",
    "apps/tracker/templates/tracker/visits.html",
  ].forEach((relativePath) => {
    const template = fs.readFileSync(path.join(root, relativePath), "utf8");
    const scopeIndex = template.indexOf("partials/company_scope_selector.html");
    const periodIndex = template.indexOf("partials/analytics_period_selector.html");
    assert.ok(scopeIndex > -1, relativePath);
    if (periodIndex > -1) {
      assert.ok(scopeIndex < periodIndex, `${relativePath}: selector must precede the period filter`);
    }
  });

  const pagesTemplate = fs.readFileSync(
    path.join(root, "apps/pages/templates/pages/overview.html"),
    "utf8"
  );
  assert.ok(
    pagesTemplate.indexOf("partials/company_scope_selector.html")
      < pagesTemplate.indexOf('id="product-area-filter"'),
    "the Companies selector must precede the product area filter"
  );

  const visitsTemplate = fs.readFileSync(
    path.join(root, "apps/tracker/templates/tracker/visits.html"),
    "utf8"
  );
  assert.ok(
    visitsTemplate.indexOf("partials/company_scope_selector.html")
      < visitsTemplate.indexOf('data-visits-filter="entity"'),
    "the Companies selector must precede the visits entity filter"
  );
});
