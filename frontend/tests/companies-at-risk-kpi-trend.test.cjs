const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const root = path.resolve(__dirname, "../..");
const adapterPath = path.join(
  root,
  "static/js/companies/django-companies-data.js"
);
const analyticsPath = path.join(
  root,
  "static/js/companies/companies-analytics.js"
);
const templatePath = path.join(
  root,
  "apps/projects/templates/projects/companies.html"
);
const adapterSource = fs.readFileSync(adapterPath, "utf8");
const analyticsSource = fs.readFileSync(analyticsPath, "utf8");
const templateSource = fs.readFileSync(templatePath, "utf8");

function loadAdapter(payload) {
  const window = {
    document: null,
    location: {
      assign() {},
      origin: "https://example.test",
      pathname: "/projects/demo/companies/",
      search: ""
    }
  };
  const document = {
    documentElement: { style: { setProperty() {} } },
    body: { dataset: {} },
    getElementById(id) {
      return id === "companies-overview-data"
        ? { textContent: JSON.stringify(payload) }
        : null;
    },
    querySelectorAll() {
      return [];
    },
    readyState: "complete",
    addEventListener() {}
  };

  window.document = document;
  vm.runInContext(
    adapterSource,
    vm.createContext({
      console,
      document,
      URL,
      URLSearchParams,
      window
    }),
    { filename: "django-companies-data.js" }
  );

  return window.HymetryCompaniesDemoData.getCompaniesDemoData("30d");
}

const mapped = loadAdapter({
  period: { days: 3, end_date: "2026-07-27" },
  productAreas: [],
  companies: [],
  healthDistribution: [],
  kpis: [
    {
      label: "Avg daily active companies",
      value: 4,
      trend: [3, 4, 5],
      trend_scope: "daily"
    },
    {
      label: "Avg daily new / reactivated",
      value: 1,
      trend: [0, 1, 2],
      trend_scope: "daily"
    },
    {
      label: "Avg daily adoption breadth",
      value: 2,
      trend: [1.5, 2, 2.5],
      trend_scope: "daily"
    },
    {
      label: "At-risk companies",
      value: 2,
      delta: { label: "+1 vs previous ending", direction: "negative", value: 1 },
      trend: [0, 1, 2],
      trend_labels: ["2026-07-25", "2026-07-26", "2026-07-27"],
      trend_scope: "as_of",
      trend_label: "At-risk companies"
    }
  ],
  atRiskCompanies: [],
  newReactivatedCompanies: [],
  expansionOpportunities: []
});

assert.deepEqual(
  Array.from(mapped.kpis.activeCompanies.sparkline),
  [3, 4, 5],
  "the active-company daily chart remains unchanged"
);
assert.deepEqual(
  Array.from(mapped.kpis.newReactivatedCompanies.sparkline),
  [0, 1, 2],
  "the lifecycle daily chart remains unchanged"
);
assert.deepEqual(
  Array.from(mapped.kpis.medianAdoptionBreadth.sparkline),
  [1.5, 2, 2.5],
  "the adoption-breadth daily chart remains unchanged"
);

const atRisk = mapped.kpis.atRiskCompanies;
assert.deepEqual(Array.from(atRisk.sparkline), [0, 1, 2]);
assert.deepEqual(
  Array.from(atRisk.sparklineLabels),
  ["2026-07-25", "2026-07-26", "2026-07-27"]
);
assert.equal(atRisk.sparklineScope, "as_of");
assert.equal(atRisk.sparklineLabel, "At-risk companies");
assert.equal(
  atRisk.sparkline.at(-1),
  Number(atRisk.value),
  "the final as-of count reconciles with the headline"
);
// The card reports a state, so the delta slot compares this period's ending
// count with the previous period's rather than restating the headline.
assert.equal(atRisk.delta, "+1 vs previous ending");
assert.equal(atRisk.deltaType, "negative");
assert.equal(
  Object.hasOwn(atRisk, "context"),
  false,
  "a real chart no longer carries the share-context placeholder"
);

// An end-of-day cohort holds its level until the next date reclassifies it, and
// each new/reactivated date stands alone, so neither is a sloping line.
assert.equal(atRisk.sparklineRender, "step");
assert.equal(mapped.kpis.newReactivatedCompanies.sparklineRender, "columns");
// The other two cards were not part of that change, so they declare no render
// mode and keep the filled line they already had. What that resolves to on the
// canvas is asserted in companies-line-trend-consumers.test.cjs, where the
// renderer is actually instantiated.
assert.equal(mapped.kpis.activeCompanies.sparklineRender, undefined);
assert.equal(mapped.kpis.medianAdoptionBreadth.sparklineRender, undefined);

assert.doesNotMatch(
  templateSource,
  /data-companies-kpi-context/,
  "the obsolete no-trend context element is removed"
);
const companiesAssetVersion = (pattern, label) => {
  const match = templateSource.match(pattern);
  assert.ok(match, `${label} busts its asset`);
  return match[1];
};
assert.equal(
  companiesAssetVersion(/django-companies-data\.js' %\}\?v=([\w.-]+)/, "the adapter"),
  companiesAssetVersion(/companies-analytics\.js' %\}\?v=([\w.-]+)/, "the renderer"),
  "the adapter and renderer are busted together, since the render mode crosses both"
);
assert.match(
  analyticsSource,
  /if \(render === "columns"\) \{/,
  "the trend renderer branches on an explicit render mode"
);
assert.match(
  analyticsSource,
  /step: render === "step" \? "end" : false/,
  "step lines hold each level until the next date"
);

console.log("companies at-risk KPI trend tests passed");
