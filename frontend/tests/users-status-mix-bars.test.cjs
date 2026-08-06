const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const root = path.resolve(__dirname, "../..");
const analyticsTooltips = require(path.join(root, "static/js/shared/analytics-tooltips.js"));
const analyticsSource = fs.readFileSync(
  path.join(root, "static/js/users/users-analytics.js"),
  "utf8"
);
const usersTemplate = fs.readFileSync(
  path.join(root, "apps/projects/templates/projects/users.html"),
  "utf8"
);
const companiesAnalyticsSource = fs.readFileSync(
  path.join(root, "static/js/companies/companies-analytics.js"),
  "utf8"
);
const analyticsDocument = {
  body: { dataset: {} },
  documentElement: {},
  addEventListener() {}
};
const analyticsWindow = {
  __HymetryExposeTestHooks: true,
  document: analyticsDocument,
  HymetryAnalyticsTooltips: analyticsTooltips,
  HymetryUsersDemoData: {
    DEFAULT_PERIOD: "180d",
    productAreas: [],
    productAreaOptions: [],
    featureProductAreas: {},
    coercePeriodKey: (value) => value,
    getUsersAnalyticsData: () => ({})
  },
  addEventListener() {},
  clearTimeout,
  setTimeout,
  location: { pathname: "/projects/1/users/", search: "" }
};

vm.runInContext(
  analyticsSource,
  vm.createContext({
    console,
    document: analyticsDocument,
    Intl,
    URLSearchParams,
    window: analyticsWindow
  }),
  { filename: "users-analytics.js" }
);

const {
  createStatusMixComparisonOption,
  statusMixDistributionRow
} = analyticsWindow.HymetryUsersAnalyticsTesting;

// A distribution that omits a status still has to produce a cell for it, so the
// two bars always compare the same statuses in the same order.
assert.equal(
  JSON.stringify(statusMixDistributionRow([
    { status: "Power", count: 3 },
    { status: "Light", count: 1 }
  ]).map((item) => [item.status, item.count])),
  JSON.stringify([
    ["Power", 3],
    ["Healthy", 0],
    ["Light", 1],
    ["Passive", 0],
    ["Dropped", 0]
  ])
);

const selected = [
  { status: "Power", count: 4 },
  { status: "Healthy", count: 4 },
  { status: "Light", count: 1 },
  { status: "Passive", count: 0 },
  { status: "Dropped", count: 1 }
];
const previous = [
  { status: "Power", count: 1 },
  { status: "Healthy", count: 5 },
  { status: "Light", count: 4 },
  { status: "Passive", count: 0 },
  { status: "Dropped", count: 0 }
];
const option = createStatusMixComparisonOption(selected, previous);

// Selected period on top: it is what the reader came for, with the previous
// period underneath as the thing it is measured against.
assert.equal(
  JSON.stringify(option.yAxis.data),
  JSON.stringify(["Selected period", "Previous period"])
);
assert.equal(
  option.yAxis.inverse,
  true,
  "ECharts must render the first category at the top"
);
assert.equal(option.xAxis.min, 0);
assert.equal(option.xAxis.max, 100, "each bar is normalized to its own total");

const segments = option.series[0].data;
assert.equal(option.series[0].type, "custom");
assert.ok(
  segments.every((segment) => segment.count > 0),
  "a status nobody holds contributes no segment"
);
assert.equal(
  segments.filter((segment) => segment.rowIndex === 0).map((segment) => segment.status).join(","),
  "Power,Healthy,Light,Dropped"
);
assert.equal(
  segments.filter((segment) => segment.rowIndex === 1).map((segment) => segment.status).join(","),
  "Power,Healthy,Light"
);

// Shares are of the bar's own total, so the two bars are comparable even when
// their head counts differ: 4 of 10 against 1 of 10.
const share = (rowIndex, status) => segments
  .find((segment) => segment.rowIndex === rowIndex && segment.status === status);
assert.equal(share(0, "Power").pctLabel, "40%");
assert.equal(share(1, "Power").pctLabel, "10%");
assert.equal(share(1, "Light").pctLabel, "40%");

// Both bars fill their track exactly, after the narrow-segment widening the
// Company health distribution uses.
[0, 1].forEach((rowIndex) => {
  const rowSegments = segments.filter((segment) => segment.rowIndex === rowIndex);
  const total = rowSegments.reduce((sum, segment) => sum + segment.widthPct, 0);
  assert.ok(Math.abs(total - 100) <= 1e-9, `row ${rowIndex} should fill its track`);
  rowSegments.forEach((segment, index) => {
    if (index === 0) {
      assert.equal(segment.value[0], 0);
      return;
    }
    assert.ok(
      Math.abs(segment.value[0] - rowSegments[index - 1].value[1]) <= 1e-9,
      "segments should abut without gaps"
    );
  });
  assert.ok(
    rowSegments.every((segment) => segment.value[2] === rowIndex),
    "every segment should sit on its own bar"
  );
});

// Tooltips name the period as well as the status, and carry both the count and
// the share so a bar can be read without measuring it.
const tooltip = option.tooltip.formatter({ data: share(1, "Light") });
assert.match(tooltip, /Previous period — Light/);
assert.match(tooltip, /Users[\s\S]*?>4</);
assert.match(tooltip, /Share[\s\S]*?>40%</);

// Same treatment as Company health distribution, not a second look-alike: both
// draw rounded 64px rects at 0.66 opacity with a white 2px separator.
[
  /const height = 64;/,
  /opacity: 0\.66,/,
  /stroke: chartTheme\.colors\.white,\s*lineWidth: 2/,
  /r: 5/
].forEach((pattern) => {
  assert.match(analyticsSource, pattern, `users status mix should match ${pattern}`);
  assert.match(companiesAnalyticsSource, pattern, `company health should match ${pattern}`);
});

// The daily stacked-area timeline it replaced is gone, along with the payload
// key that fed it.
assert.doesNotMatch(analyticsSource, /createStatusStackedAreaOption/);
assert.doesNotMatch(analyticsSource, /statusMixByDate/);
assert.match(usersTemplate, /User status mix<\/h3>/);
assert.doesNotMatch(usersTemplate, /Status mix vs previous period/);

console.log("users status mix bar tests passed");
