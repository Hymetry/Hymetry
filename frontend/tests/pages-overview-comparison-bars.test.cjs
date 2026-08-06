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
  createKpiPeriodComparisonOption,
  isKpiPeriodComparison
} = window.HymetryPagesAnalyticsTesting;

const fastestGrowingKpi = {
  label: "Fastest-growing",
  value: "Invoices",
  delta: "+67% companies",
  delta_value: 67,
  trend_values: [3, 5],
  trend_labels: ["Previous period", "Selected period"],
  trend_format: "number",
  trend_label: "Companies",
  trend_scope: "period_comparison",
  trend_delta_value: 67
};

assert.equal(isKpiPeriodComparison(fastestGrowingKpi), true);
// A daily series is not a two-period comparison, and neither is a scope that
// claims to be one without exactly two totals to compare.
assert.equal(
  isKpiPeriodComparison({ trend_scope: "daily", trend_values: [1, 2, 3] }),
  false
);
assert.equal(
  isKpiPeriodComparison({ trend_scope: "period_comparison", trend_values: [5] }),
  false
);

const option = createKpiPeriodComparisonOption(fastestGrowingKpi, null);

// Selected period reads first, so it sits on top with the previous period under
// it, and both bars start from zero so their lengths are comparable.
assert.equal(
  option.yAxis.data.join(","),
  "Selected period,Previous period"
);
assert.equal(
  option.yAxis.inverse,
  true,
  "ECharts must render the selected period at the top"
);
assert.equal(option.xAxis.min, 0);
assert.equal(option.series.length, 1);
assert.equal(option.series[0].type, "bar");
assert.equal(
  option.series[0].data.map((bar) => bar.value).join(","),
  "5,3",
  "the bars carry the two company counts, selected first"
);
assert.notEqual(
  option.series[0].data[0].itemStyle.color,
  option.series[0].data[1].itemStyle.color,
  "the previous period is drawn at lower weight than the selected one"
);
assert.equal(option.series[0].label.show, true, "each bar is labelled with its count");
assert.equal(option.series[0].label.formatter({ value: 5 }), "5");

// The tooltip carries the percentage change as well as the count, so the card
// answers "how much did it grow" without leaving the chart.
const tooltip = option.tooltip.formatter({ dataIndex: 1 });
assert.match(tooltip, /Previous period/);
assert.match(tooltip, /Companies[\s\S]*?>3</);
assert.match(tooltip, /Change[\s\S]*?>\+67%</);

// Two labelled bars need more vertical room than the sparkline slot the other
// cards use.
assert.match(
  source,
  /if \(isKpiPeriodComparison\(kpi\)\) \{\s*trendElement\.classList\.remove\("h-12"\);\s*trendElement\.classList\.add\("h-16"\);/,
  "the comparison card gets a taller chart slot"
);

// The product-area sparklines are read down a column, so every row in a metric
// column shares one scale rather than each row scaling to itself.
assert.match(
  source,
  /function getProductAreaTrendScaleByMetric\(rows\) \{[\s\S]*?compactAxisMax\(\s*rows\.flatMap\(\(row\) => row\.trends\?\.\[metric\.key\] \|\| \[\]\),\s*\);/,
  "the column scale is built from every row in the column"
);
assert.match(
  source,
  /min: 0,\s*max: Number\.isFinite\(Number\(config\.axisMax\)\) \? Number\(config\.axisMax\) : compactAxisMax\(series\)/,
  "each product-area sparkline honours the shared column maximum"
);
assert.doesNotMatch(
  cssSource,
  /--product-area-trend-fill-color/,
  "the product-area sparklines are unfilled, so no fill colour is declared"
);

console.log("pages overview comparison bar tests passed");
