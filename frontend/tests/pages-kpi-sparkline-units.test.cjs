const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const root = path.resolve(__dirname, "../..");
const analyticsTooltips = require(path.join(root, "static/js/shared/analytics-tooltips.js"));
const metricDynamics = require(path.join(root, "static/js/shared/metric-dynamics.js"));
const document = {
  body: { dataset: {} },
  documentElement: {},
  addEventListener() {},
  getElementById() { return null; },
  querySelectorAll() { return []; }
};
const window = {
  __HymetryExposeTestHooks: true,
  document,
  echarts: { graphic: { LinearGradient: class LinearGradient {} } },
  HymetryAnalyticsTooltips: analyticsTooltips,
  HymetryMetricDynamics: metricDynamics,
  HymetryPagesAnalyticsData: {
    getMockPagesOverviewData() { return {}; },
    getMockPageDetailsData() { return null; }
  },
  addEventListener() {},
  clearTimeout,
  getComputedStyle() {
    return { getPropertyValue() { return ""; } };
  },
  location: {
    href: "https://example.com/projects/demo/pages/",
    origin: "https://example.com",
    pathname: "/projects/demo/pages/",
    search: "",
    hash: ""
  },
  setTimeout
};
window.window = window;

const source = fs.readFileSync(path.join(root, "static/js/pages/pages-analytics.js"), "utf8");
const templateSource = fs.readFileSync(path.join(root, "apps/pages/templates/pages/overview.html"), "utf8");
const detailTemplateSource = fs.readFileSync(path.join(root, "apps/pages/templates/pages/detail.html"), "utf8");
const cssSource = fs.readFileSync(path.join(root, "static/css/pages/overview.css"), "utf8");

vm.runInContext(
  source,
  vm.createContext({
    window,
    document,
    console,
    Intl,
    URL,
    URLSearchParams,
    clearTimeout,
    setTimeout
  }),
  { filename: "static/js/pages/pages-analytics.js" }
);

const {
  createKpiTrendOption,
  finiteNumericValues,
  kpiNoTrendContext
} = window.HymetryPagesAnalyticsTesting;
const labels = ["Jul 4", "Jul 5"];

function tooltipFor(kpi) {
  const option = createKpiTrendOption(
    kpi.trend_values,
    null,
    labels,
    kpi.trend_label || kpi.label,
    kpi.trend_format,
    kpi.trend_scope
  );

  return (dataIndex) => option.tooltip.formatter([{
    axisValueLabel: labels[dataIndex],
    dataIndex,
    value: kpi.trend_values[dataIndex]
  }]);
}

// `_build_kpis` in apps/pages/services.py types every KPI trend, and the card
// value it ships alongside is already formatted, so the hover must match it.
const engagedTooltip = tooltipFor({
  label: "Most used page",
  trend_values: [45, 90],
  trend_format: "duration",
  trend_scope: "daily",
  trend_label: "Daily engaged"
});

assert.match(engagedTooltip(1), />1m 30s</, "engaged-time trends are shown as durations");
assert.match(
  createKpiTrendOption([151], null, ["Jul 13"], "Cumulative engaged", "duration").tooltip.formatter([{ dataIndex: 0, value: 151 }]),
  />2m 31s</,
  "duration trend endpoints keep the same precision as their KPI labels"
);
assert.match(engagedTooltip(0), />45s</, "sub-minute engaged time keeps second precision");
assert.doesNotMatch(engagedTooltip(1), />90</, "raw seconds must not reach the tooltip");
assert.match(engagedTooltip(1), /Jul 5/, "daily KPI dates identify the observed day");
assert.doesNotMatch(engagedTooltip(1), /Through Jul 5/, "daily KPI dates are not described as cumulative");
assert.equal(
  createKpiTrendOption([45, 90], null, labels, "Daily engaged", "duration", "daily").series[0].smooth,
  false,
  "daily KPI lines do not curve beyond their observed points"
);

const adoptionTooltip = tooltipFor({
  label: "Avg daily adoption",
  trend_values: [41.5, 46],
  trend_format: "percent",
  trend_scope: "daily",
  trend_label: "Average page adoption"
});

assert.match(adoptionTooltip(1), />46%</, "adoption trends keep their percent sign");
assert.match(adoptionTooltip(0), />42%</, "fractional percentages are rounded like the card");

// The Fastest-growing card no longer draws a series at all; its two-period bars
// are covered by pages-overview-comparison-bars.test.cjs. What remains here is
// the daily contract every other card shares.
const gappedDailyOption = createKpiTrendOption(
  [null, 50, 100],
  null,
  ["Jul 4", "Jul 5", "Jul 6"],
  "Average page adoption",
  "percent",
  "daily"
);
assert.deepEqual(
  Array.from(gappedDailyOption.series[0].data),
  [null, 50, 100],
  "an undefined day remains a chart gap"
);
assert.equal(gappedDailyOption.series[0].connectNulls, false, "gaps are not bridged");
assert.equal(
  gappedDailyOption.series[0].smooth,
  false,
  "daily observations are real points and cannot be curved past"
);
assert.equal(
  createKpiTrendOption(
    [null, 25],
    null,
    ["Jul 4", "Jul 5"],
    "Average page adoption",
    "percent",
    "daily"
  ).series[0].symbol,
  "circle",
  "a lone comparable point remains visible"
);
assert.match(
  gappedDailyOption.tooltip.formatter([{ axisValueLabel: "Jul 4", dataIndex: 0, value: null }]),
  />Unavailable</,
  "a gap has an explicit unavailable tooltip state rather than reading as zero"
);
assert.match(
  gappedDailyOption.tooltip.formatter([{ axisValueLabel: "Jul 6", dataIndex: 2, value: 100 }]),
  /Jul 6/,
  "a daily point is titled with its own date, not a through-date"
);
assert.doesNotMatch(
  gappedDailyOption.tooltip.formatter([{ axisValueLabel: "Jul 6", dataIndex: 2, value: 100 }]),
  /Through Jul 6/,
  "a daily point is not described as period-to-date"
);
assert.deepEqual(
  Array.from(finiteNumericValues([null, undefined, "", 0, "12", Number.NaN])),
  [0, 12],
  "null and empty gaps are ignored without discarding a real zero"
);

const adoptedPagesTooltip = tooltipFor({
  label: "Avg daily adopted pages",
  trend_values: [1200, 1500],
  trend_format: "number",
  trend_scope: "daily"
});

assert.match(adoptedPagesTooltip(1), />1,500</, "counted KPIs keep plain number formatting");

// Overview payloads cached before the KPI trend was typed carry no format.
const untypedTooltip = tooltipFor({
  label: "Avg daily adopted pages",
  trend_values: [7, 9],
  trend_format: undefined
});

assert.match(untypedTooltip(1), />9</, "a missing trend format falls back to a plain number");

assert.match(
  source,
  /createKpiTrendOption\([\s\S]*?kpi\.trend_values,[\s\S]*?kpi\.trend_label \|\| kpi\.label[\s\S]*?kpi\.trend_format,[\s\S]*?kpi\.trend_scope[\s\S]*?\)/,
  "the KPI cards must mount their trend with the format and grain the payload declares"
);
assert.equal(
  kpiNoTrendContext({ label: "Fastest-growing" }),
  "",
  "the renderer does not invent a generic placeholder for a missing trend"
);
assert.equal(
  kpiNoTrendContext({ label: "Fastest-growing", context_line: "Custom context" }),
  "Custom context",
  "only explicit backend context is rendered"
);
assert.match(
  source,
  /const hasTrend = finiteNumericValues\(kpi\?\.trend_values\)\.length > 0/,
  "the card renderer requires a finite point rather than a non-empty gap array"
);
assert.match(
  source,
  /trendElement\.hidden = !hasTrend/,
  "period-ranked cards without an honest daily series hide the empty chart"
);
assert.match(
  source,
  /const contextText = hasTrend \? "" : kpiNoTrendContext\(kpi\)/,
  "daily charts keep their chart slot while no-trend cards receive context"
);
assert.match(
  source,
  /contextElement\.hidden = !contextText/,
  "the context line is hidden whenever a chart is available"
);
assert.match(
  templateSource,
  /data-pages-kpi-context[\s\S]*?hidden/,
  "the KPI template includes a hidden accessible context line"
);
assert.doesNotMatch(
  templateSource,
  /data-pages-kpi-context[^>]*role="note"/,
  "the context remains natural text without adding a noisy landmark role"
);
assert.match(
  cssSource,
  /#pages-kpis \[data-pages-kpi-context\]:not\(\[hidden\]\)[\s\S]*?display: flex;[\s\S]*?min-height: 3rem;/,
  "the context line occupies at least the same slot as a KPI chart and can grow when text wraps"
);
// Both templates share this renderer, so a change to it has to be busted in
// both at once rather than pinned to one release's stamp here.
const assetVersion = (template, label) => {
  const match = template.match(/pages-analytics\.js' %}\?v=([\w.-]+)/);
  assert.ok(match, `${label} busts the KPI renderer asset`);
  return match[1];
};
assert.equal(
  assetVersion(templateSource, "overview"),
  assetVersion(detailTemplateSource, "detail"),
  "overview and detail bust the shared renderer together"
);
// The product-area sparklines are per-day, so their tooltip names the date
// rather than claiming a running total through it.
assert.doesNotMatch(
  source,
  /title: item\.axisValueLabel \? `Through \$\{item\.axisValueLabel\}`/,
  "product-area daily sparkline tooltips do not use through-date titles"
);
assert.match(source, /`Through \$\{formatDetailDate\(dates\[index\]\)\}`/, "page-detail trend tooltips use through-date titles");
assert.match(source, /metricTooltipRow\("Period to date"/, "page-detail current values are labelled as period to date");

console.log("pages KPI sparkline unit tests passed");
