const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const root = path.resolve(__dirname, "../..");
const metricDynamics = require(path.join(root, "static/js/shared/metric-dynamics.js"));

function createAnalyticsTooltipsStub() {
  return {
    echarts(options) {
      return options;
    },
    render(payload) {
      return JSON.stringify(payload);
    }
  };
}

function loadConsumer(scriptRelativePath, hooksName, extraGlobals = {}) {
  const binderCalls = [];
  const initializedCharts = [];
  const document = {
    body: { dataset: {} },
    documentElement: {},
    addEventListener() {},
    getElementById() {
      return null;
    },
    querySelector() {
      return null;
    },
    querySelectorAll() {
      return [];
    }
  };
  const window = {
    __HymetryExposeTestHooks: true,
    document,
    echarts: {
      graphic: {
        LinearGradient: class LinearGradient {}
      },
      init(element) {
        const chart = {
          element,
          option: null,
          dispose() {},
          resize() {},
          setOption(option) {
            this.option = option;
          }
        };

        initializedCharts.push(chart);
        return chart;
      }
    },
    getComputedStyle() {
      return {
        getPropertyValue() {
          return "";
        }
      };
    },
    HymetryAnalyticsTooltips: createAnalyticsTooltipsStub(),
    HymetryCompaniesDemoData: {
      DEFAULT_PERIOD: "30",
      coercePeriodKey(value) {
        return String(value);
      }
    },
    HymetryMetricDynamics: {
      ...metricDynamics,
      bindLineTrendHover(chart, lineSeriesCount, element) {
        binderCalls.push({ chart, lineSeriesCount, element });
        return chart;
      }
    },
    addEventListener() {},
    removeEventListener() {},
    clearTimeout,
    location: {
      href: "https://example.com/projects/demo/companies/",
      origin: "https://example.com",
      pathname: "/projects/demo/companies/",
      search: "",
      hash: ""
    },
    setTimeout,
    ...extraGlobals
  };
  window.window = window;

  const context = vm.createContext({
    window,
    document,
    console,
    Intl,
    URL,
    URLSearchParams,
    clearTimeout,
    setTimeout
  });
  const sourcePath = path.join(root, scriptRelativePath);
  const source = fs.readFileSync(sourcePath, "utf8");

  vm.runInContext(source, context, { filename: scriptRelativePath });

  const hooks = window[hooksName];
  assert.ok(hooks, `${hooksName} should be exposed in test mode`);

  return { binderCalls, hooks, initializedCharts, source };
}

function assertSeriesValues(actual, expected, message) {
  assert.equal(actual.length, expected.length, message);
  expected.forEach((expectedValue, index) => {
    if (expectedValue === null) {
      assert.equal(actual[index], null, message);
      return;
    }

    assert.ok(Math.abs(actual[index] - expectedValue) <= 1e-10, message);
  });
}

function assertThreeBlockLineOption(option, expectedTrends) {
  const lineSeriesCount = expectedTrends.length;

  assert.equal(
    option.series.length,
    lineSeriesCount * 3,
    "The option should contain N main lines, N end-label connectors, and N hover trends"
  );

  expectedTrends.forEach((expectedTrend, index) => {
    const main = option.series[index];
    const connector = option.series[lineSeriesCount + index];
    const trend = option.series[lineSeriesCount * 2 + index];

    assert.equal(main.type, "line");
    assert.equal(main.triggerLineEvent, true);
    assert.equal(main.cursor, "default");
    assert.equal(main.emphasis.focus, "series");

    assert.equal(connector.type, "line");
    assert.equal(connector.silent, false);
    assert.equal(connector.triggerLineEvent, true);
    assert.equal(connector.cursor, "default");
    assert.equal(connector.tooltip.show, false);
    assert.equal(connector.emphasis.disabled, true);
    assert.equal(connector.lineStyle.color, main.lineStyle.color);

    assert.equal(trend.type, "line");
    assert.equal(trend.silent, true);
    assert.equal(trend.tooltip.show, false);
    assert.equal(trend.smooth, false);
    assert.equal(trend.symbol, "none");
    assert.equal(trend.lineStyle.color, main.lineStyle.color);
    assert.equal(trend.lineStyle.opacity, 0);
    assert.equal(trend.blur.lineStyle.opacity, 0);
    assert.deepEqual(Array.from(trend.emphasis.lineStyle.type), [6, 4]);
    assert.equal(trend.emphasis.lineStyle.opacity, 0.58);
    assert.equal(trend.emphasis.lineStyle.width, 2);
    assert.equal(trend.z, 4);
    assertSeriesValues(
      trend.data,
      expectedTrend.concat(null),
      "Each hidden trend should contain the independently expected OLS values plus the label spacer"
    );
  });
}

function assertTooltipOnlyIncludesMainSeries(option, axisValue, value) {
  const main = option.series[0];
  const lineSeriesCount = option.series.length / 3;
  const connector = option.series[lineSeriesCount];
  const trend = option.series[lineSeriesCount * 2];
  const tooltip = option.tooltip.formatter([
    {
      axisValue,
      dataIndex: 0,
      seriesName: main.name,
      value
    },
    {
      axisValue,
      dataIndex: 0,
      seriesName: connector.name,
      value
    },
    {
      axisValue,
      dataIndex: 0,
      seriesName: trend.name,
      value
    }
  ]);
  const payload = JSON.parse(tooltip);

  assert.equal(payload.rows.length, 1, "Connector and hover-trend values should be filtered from the tooltip");
  assert.equal(payload.rows[0].label, main.name);
  assert.ok(
    payload.rows.every((row) => !row.label.endsWith(" label connector") && !row.label.endsWith(" hover trend")),
    "No auxiliary line should produce a tooltip row"
  );
}

const companies = loadConsumer(
  "static/js/companies/companies-analytics.js",
  "HymetryCompaniesAnalyticsTesting"
);
const companyKpiOption = companies.hooks.createKpiTrendOption(
  [1, 3],
  {},
  "positive",
  ["Jul 1", "Jul 2"],
  "Daily active companies",
  "number",
  "daily"
);
const companyKpiTooltip = JSON.parse(companyKpiOption.tooltip.formatter([{
  axisValue: "Jul 2",
  axisValueLabel: "Jul 2",
  value: 3
}]));
assert.equal(companyKpiTooltip.title, "Jul 2");
assert.equal(companyKpiTooltip.rows[0].label, "Daily active companies");
assert.equal(companyKpiOption.series[0].smooth, false);
// A card that declares no render mode keeps the filled line it always had. Only
// the two cards that asked for a different reading change shape, so this is the
// guard against a shared refactor quietly restyling the rest.
assert.equal(companyKpiOption.series[0].type, "line");
assert.ok(companyKpiOption.series[0].areaStyle, "an untouched daily card keeps its fill");
assert.equal(companyKpiOption.series[0].step, false);
assert.equal(companyKpiOption.series[0].emphasis.disabled, true);

const columnsKpiOption = companies.hooks.createKpiTrendOption(
  [0, 1, 2],
  {},
  "positive",
  ["Jul 1", "Jul 2", "Jul 3"],
  "Daily new / reactivated",
  "number",
  "daily",
  "columns"
);
assert.equal(columnsKpiOption.series[0].type, "bar");
assert.equal(columnsKpiOption.series[0].areaStyle, undefined);
assert.equal(columnsKpiOption.series[0].emphasis.disabled, true);
// Columns are read against zero, so the axis cannot float up to the lowest bar.
assert.equal(columnsKpiOption.yAxis.min, 0);
assert.equal(columnsKpiOption.xAxis.boundaryGap, true);

const stepKpiOption = companies.hooks.createKpiTrendOption(
  [0, 1, 2],
  {},
  "negative",
  ["Jul 1", "Jul 2", "Jul 3"],
  "At-risk companies",
  "number",
  "as_of",
  "step"
);
assert.equal(stepKpiOption.series[0].step, "end");
assert.equal(stepKpiOption.series[0].smooth, false);
assert.equal(stepKpiOption.series[0].areaStyle, undefined, "the at-risk step line is unfilled");
assert.equal(stepKpiOption.series[0].emphasis.disabled, true);

const atRiskKpiOption = companies.hooks.createKpiTrendOption(
  [1, 2],
  {},
  "negative",
  ["Jul 1", "Jul 2"],
  "At-risk companies",
  "number",
  "as_of"
);
const atRiskKpiTooltip = JSON.parse(atRiskKpiOption.tooltip.formatter([{
  axisValue: "Jul 2",
  axisValueLabel: "Jul 2",
  value: 2
}]));
assert.equal(atRiskKpiTooltip.title, "As of Jul 2");
assert.equal(atRiskKpiOption.series[0].smooth, false);

const medianKpiOption = companies.hooks.createKpiTrendOption(
  [1, 1.5],
  {},
  "positive",
  ["Jul 1", "Jul 2"],
  "Daily adoption breadth",
  "areas",
  "daily"
);
const medianKpiTooltip = JSON.parse(medianKpiOption.tooltip.formatter([{
  axisValue: "Jul 2",
  axisValueLabel: "Jul 2",
  value: 1.5
}]));
assert.equal(medianKpiTooltip.rows[0].value, "1.5 areas");
assert.equal(medianKpiTooltip.title, "Jul 2");
assert.match(
  companies.source,
  /secondaryElement\.textContent = kpi\.secondary \|\| ""[\s\S]*?deltaElement\.textContent = kpi\.delta \|\| ""/,
  "company cards render lifecycle support text without hiding the comparison delta"
);
const datePoints = [
  ["2026-07-01", 1, 8],
  ["2026-07-02", 2, 1],
  ["2026-07-03", 10, 6],
  ["2026-07-04", 4, 0]
].flatMap(([date, core, admin]) => [
  { productArea: "Core", date, adoptionPct: core },
  { productArea: "Admin", date, adoptionPct: admin }
]);
const adoptionOption = companies.hooks.createProductAreaAdoptionOption(datePoints);

assertThreeBlockLineOption(adoptionOption, [
  [1.7, 3.4, 5.1, 6.8],
  [6.6, 4.7, 2.8, 0.9]
]);
assertTooltipOnlyIncludesMainSeries(adoptionOption, "2026-07-01", 1);

const insufficientOption = companies.hooks.createProductAreaAdoptionOption([
  { productArea: "Core", date: "2026-07-01", adoptionPct: 10 },
  { productArea: "Core", date: "2026-07-02", adoptionPct: 20 }
]);
assertSeriesValues(
  insufficientOption.series[2].data,
  [null, null, null],
  "A series with fewer than three observations should reserve an all-null hover trend"
);

const rampPoints = [
  [0, 5, 60],
  [7, 15, 50],
  [14, 25, 40],
  [21, 35, 30]
].flatMap(([dayOffset, core, admin]) => [
  { productArea: "Core", dayOffset, adoptionPct: core },
  { productArea: "Admin", dayOffset, adoptionPct: admin }
]);
const rampOption = companies.hooks.createAdoptionRampOption(rampPoints);

assertThreeBlockLineOption(rampOption, [
  [5, 15, 25, 35],
  [60, 50, 40, 30]
]);
assertTooltipOnlyIncludesMainSeries(rampOption, 0, 5);

const overviewElement = {};
const mountedOverviewChart = companies.hooks.mountLineHoverTrendChart(
  overviewElement,
  adoptionOption,
  2
);
assert.equal(mountedOverviewChart, companies.initializedCharts.at(-1));
assert.equal(mountedOverviewChart.option, adoptionOption);
assert.deepEqual(companies.binderCalls.at(-1), {
  chart: mountedOverviewChart,
  lineSeriesCount: 2,
  element: overviewElement
});

const companyDetail = loadConsumer(
  "static/js/companies/company-detail.js",
  "HymetryCompanyDetailTesting",
  {
    HymetryCompanyDetailHelpers: {}
  }
);
const detailData = {
  adoptionBreadthSeries: {
    dates: ["2026-07-01", "2026-07-02", "2026-07-03", "2026-07-04"],
    series: [
      {
        productArea: "Core",
        color: "#4269d0",
        values: [100, 130, 160, 190]
      },
      {
        productArea: "Admin",
        color: "#efb118",
        values: [240, 220, 200, 180]
      }
    ]
  }
};
const breadthOption = companyDetail.hooks.createAdoptionBreadthOption(detailData);

// Each point is the engaged time recorded on that one date, so this chart is a
// plain read of daily activity: two lines and their end-label connectors, with
// no fitted trend behind them and nothing to reveal on hover.
assert.equal(breadthOption.series.length, 4);
assert.deepEqual(
  breadthOption.series.map((series) => series.name),
  ["Core", "Admin", "Core label connector", "Admin label connector"]
);
breadthOption.series.slice(0, 2).forEach((series) => {
  assert.equal(series.type, "line");
  assert.equal(series.triggerLineEvent, true);
  assert.equal(series.emphasis.focus, "series");
  assert.equal(series.areaStyle, undefined, "product-area usage lines stay unfilled");
});
assert.ok(
  breadthOption.series.every((series) => !/hover trend$/.test(series.name)),
  "No hidden fitted-trend series should remain on the daily product-area chart"
);
assert.equal(breadthOption.yAxis.name, "Engaged time");

const breadthTooltip = JSON.parse(breadthOption.tooltip.formatter([
  { axisValue: "2026-07-01", dataIndex: 0, seriesName: "Core", value: 100 },
  { axisValue: "2026-07-01", dataIndex: 0, seriesName: "Core label connector", value: 100 }
]));
assert.equal(breadthTooltip.rows.length, 1, "The end-label connector is filtered from the tooltip");
assert.equal(breadthTooltip.rows[0].label, "Core");

const detailElement = {};
const binderCallsBeforeDetailMount = companyDetail.binderCalls.length;
const mountedDetailChart = companyDetail.hooks.mountAdoptionBreadthChart(detailElement, detailData);
assert.equal(mountedDetailChart, companyDetail.initializedCharts.at(-1));
assert.equal(mountedDetailChart.option.series.length, 4);
assert.equal(
  companyDetail.binderCalls.length,
  binderCallsBeforeDetailMount,
  "Without hover trends to reveal there is nothing for the hover binder to do"
);

const periodToDateMetricOption = companyDetail.hooks.createMiniMetricChartOption({
  key: "visits",
  valueType: "number",
  dailySeries: [
    { date: "2026-07-01", value: 2 },
    { date: "2026-07-02", value: 5 },
    { date: "2026-07-03", value: 9 }
  ],
  benchmarkSeries: [],
  peerSeries: []
});
const periodToDateTooltip = JSON.parse(periodToDateMetricOption.tooltip.formatter([{ dataIndex: 1 }]));
assert.equal(periodToDateTooltip.title, "Through Jul 2");
assert.equal(periodToDateTooltip.sections[0].rows[0].label, "Period to date");

// A running total is drawn as a filled curve with no fitted line of its own: the
// fit would only restate a series that can never fall. It stays out of the
// tooltip too, not just off the canvas.
const periodToDateLine = periodToDateMetricOption.series.at(-1);
assert.equal(periodToDateMetricOption.series.length, 1);
assert.equal(periodToDateLine.step, false);
assert.equal(periodToDateLine.smooth, true);
assert.ok(periodToDateLine.areaStyle, "cumulative totals keep a subtle fill");
assert.deepEqual(
  periodToDateTooltip.sections[0].rows.map((row) => row.label),
  ["Period to date", "Benchmark"],
  "a cumulative-total tooltip reports its value and the benchmark, but no self-trend"
);

// A rate is recomputed over the elapsed period and can move either way, so it
// keeps its fitted trend and drops the fill an area under a ratio would imply.
const rateMetricOption = companyDetail.hooks.createMiniMetricChartOption({
  key: "interaction",
  valueType: "percent",
  dailySeries: [
    { date: "2026-07-01", value: 40 },
    { date: "2026-07-02", value: 55 },
    { date: "2026-07-03", value: 48 }
  ],
  benchmarkSeries: [],
  peerSeries: []
});
const rateLine = rateMetricOption.series.at(-1);
assert.equal(rateMetricOption.series.length, 2, "the rate panel keeps its fitted trend");
assert.equal(rateMetricOption.series[0].name, "Current trend");
assert.equal(rateLine.areaStyle, undefined, "rates are unfilled");
assert.equal(rateLine.step, false);

// Adoption breadth counts distinct areas over the elapsed period: it holds a
// level until something new is used, so it steps and needs no fit either.
const breadthMetricOption = companyDetail.hooks.createMiniMetricChartOption({
  key: "adoptionBreadth",
  valueType: "number",
  dailySeries: [
    { date: "2026-07-01", value: 1 },
    { date: "2026-07-02", value: 1 },
    { date: "2026-07-03", value: 2 }
  ],
  benchmarkSeries: [],
  peerSeries: []
});
const breadthMetricLine = breadthMetricOption.series.at(-1);
assert.equal(breadthMetricOption.series.length, 1);
assert.equal(breadthMetricLine.step, "end");
assert.equal(breadthMetricLine.smooth, false);
assert.ok(breadthMetricLine.areaStyle, "discrete cumulative counts keep a subtle fill");

const atRiskMetricOption = companyDetail.hooks.createMiniMetricChartOption({
  key: "atRiskUsers",
  valueType: "number",
  dailySeries: [
    { date: "2026-07-01", value: 2 },
    { date: "2026-07-02", value: 3 },
    { date: "2026-07-03", value: 1 }
  ],
  benchmarkSeries: [],
  peerSeries: []
});
const atRiskTooltip = JSON.parse(atRiskMetricOption.tooltip.formatter([{ dataIndex: 1 }]));
assert.equal(atRiskTooltip.title, "As of Jul 2");
assert.equal(atRiskTooltip.sections[0].rows[0].label, "As of date");

// At-risk users is an end-of-day state that holds until the next date, so it
// steps and stays unfilled, but it can fall and so keeps its fitted trend.
const atRiskLine = atRiskMetricOption.series.at(-1);
assert.equal(atRiskMetricOption.series.length, 2);
assert.equal(atRiskMetricOption.series[0].name, "Current trend");
assert.equal(atRiskLine.step, "end");
assert.equal(atRiskLine.smooth, false);
assert.equal(atRiskLine.areaStyle, undefined, "an end-of-day state carries no fill");

const durationMetricMarkup = companyDetail.hooks.metricPanelMarkup({
  key: "engaged",
  label: "ENGAGED",
  valueType: "duration",
  value: 151,
  deltaDirection: "neutral",
  formattedDelta: "0%"
}, 0);
assert.match(durationMetricMarkup, />2m 31s</, "duration headlines match the final-point tooltip precision");

const companiesTemplate = fs.readFileSync(
  path.join(root, "apps/projects/templates/projects/companies.html"),
  "utf8"
);
const companyDetailTemplate = fs.readFileSync(
  path.join(root, "apps/projects/templates/projects/company_detail.html"),
  "utf8"
);
const companyDetailSource = fs.readFileSync(
  path.join(root, "static/js/companies/company-detail.js"),
  "utf8"
);
assert.match(
  companiesTemplate,
  /data-pages-kpi-secondary/,
  "company KPI cards should expose a dedicated lifecycle support-text element"
);
assert.match(
  companiesTemplate,
  /data-pages-kpi-value-row[^>]*class="[^"]*items-baseline[^"]*"[\s\S]*?data-pages-kpi-value[\s\S]*?data-pages-kpi-secondary/,
  "the lifecycle support text should share the headline value row"
);
assert.match(
  companiesTemplate,
  /data-pages-kpi-secondary[^>]*class="[^"]*truncate[^"]*"/,
  "long lifecycle support text should truncate before it disrupts the card layout"
);

function assertSharedHelperLoadsBeforeConsumer(template, consumerPath) {
  const helperPath = "js/shared/metric-dynamics.js";
  const helperIndex = template.indexOf(helperPath);
  const consumerIndex = template.indexOf(consumerPath);

  assert.notEqual(helperIndex, -1, `${helperPath} should be loaded by the template`);
  assert.notEqual(consumerIndex, -1, `${consumerPath} should be loaded by the template`);
  assert.ok(helperIndex < consumerIndex, `${helperPath} should load before ${consumerPath}`);
}

assertSharedHelperLoadsBeforeConsumer(companiesTemplate, "js/companies/companies-analytics.js");
assertSharedHelperLoadsBeforeConsumer(companyDetailTemplate, "js/companies/company-detail.js");
assert.doesNotMatch(
  companyDetailTemplate,
  /company-detail-helpers\.js/,
  "the Django detail surface must not load the synthetic metric-history fallback"
);
assert.doesNotMatch(
  companyDetailSource,
  /detailHelpers\.buildCompanyDetailsData/,
  "a missing detail provider must not fabricate KPI histories"
);

console.log("companies line trend consumer tests passed");
