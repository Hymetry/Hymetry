const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const root = path.resolve(__dirname, "../..");
const metricDynamics = require(path.join(root, "static/js/shared/metric-dynamics.js"));
const windowHandlers = new Map();
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
  echarts: {
    graphic: {
      LinearGradient: class LinearGradient {}
    }
  },
  HymetryPagesAnalyticsData: {
    getMockPagesOverviewData() { return {}; },
    getMockPageDetailsData() { return null; }
  },
  HymetryMetricDynamics: metricDynamics,
  addEventListener(eventName, handler) {
    const handlers = windowHandlers.get(eventName) || [];
    handlers.push(handler);
    windowHandlers.set(eventName, handlers);
  },
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
const sourcePath = path.join(root, "static/js/pages/pages-analytics.js");
const source = fs.readFileSync(sourcePath, "utf8");
const overviewCss = fs.readFileSync(path.join(root, "static/css/pages/overview.css"), "utf8");
const overviewTemplate = fs.readFileSync(path.join(root, "apps/pages/templates/pages/overview.html"), "utf8");

vm.runInContext(source, context, { filename: "static/js/pages/pages-analytics.js" });

const hooks = window.HymetryPagesAnalyticsTesting;
assert.ok(hooks, "Page analytics test hooks should be exposed in test mode");

const labels = [
  "2026-07-01",
  "2026-07-02",
  "2026-07-03",
  "2026-07-04",
  "2026-07-05",
  "2026-07-06",
  "2026-07-07"
];
const dailyValues = (base) => labels.map((_label, index) => base + index);

// Seven candidate pages, deliberately out of order, so the selection has to sort
// by period total rather than trusting the payload order.
const timeData = {
  labels,
  series: [
    { page_name: "Third", total: 300, values: dailyValues(30) },
    { page_name: "First", total: 700, values: dailyValues(70) },
    { page_name: "Sixth", total: 120, values: dailyValues(12) },
    { page_name: "Second", total: 500, values: dailyValues(50) },
    { page_name: "Seventh", total: 60, values: dailyValues(6) },
    { page_name: "Fifth", total: 180, values: dailyValues(18) },
    { page_name: "Fourth", total: 240, values: dailyValues(24) }
  ]
};

assert.deepEqual(
  hooks.topPagesTimeSeriesRows(timeData).map((row) => row.page_name),
  ["First", "Second", "Third", "Fourth", "Fifth"],
  "The chart plots the five pages with the largest period totals"
);

// Without an explicit total the rows still have to be ranked, so the daily
// values are summed instead.
assert.deepEqual(
  hooks.topPagesTimeSeriesRows({
    labels,
    series: [
      { page_name: "Quiet", values: [1, 1] },
      { page_name: "Busy", values: [9, 9] }
    ]
  }).map((row) => row.page_name),
  ["Busy", "Quiet"]
);

const option = hooks.createTopPagesTimeOption(timeData, {
  yAxisName: "Visits",
  formatValue: (value) => String(value),
  selectedPeriodDays: 7
});

// Five lines, five end-label connectors, and five hidden fitted trends.
assert.equal(option.series.length, 15);
assert.deepEqual(
  option.series.slice(0, 5).map((series) => series.name),
  ["First", "Second", "Third", "Fourth", "Fifth"]
);
option.series.slice(0, 5).forEach((series, index) => {
  assert.equal(series.type, "line", `series ${index} should be a line`);
  assert.equal(series.emphasis.focus, "series");
  assert.equal(series.triggerLineEvent, true);
  assert.equal(series.areaStyle, undefined, "top-pages lines are unfilled");
  assert.equal(series.data.at(-1), null, "the label spacer category carries no value");
});
option.series.slice(5).forEach((series) => {
  assert.equal(series.tooltip.show, false);
});
option.series.slice(5, 10).forEach((series, index) => {
  assert.match(series.name, / label connector$/);
  assert.equal(series.endLabel.show, true);
  assert.equal(series.silent, false);
  assert.equal(series.triggerLineEvent, true);
  assert.equal(series.cursor, "default");
  assert.equal(series.lineStyle.color, option.series[index].lineStyle.color);
  assert.equal(series.emphasis.disabled, true);
});
option.series.slice(10).forEach((series, index) => {
  assert.match(series.name, / hover trend$/);
  assert.equal(series.silent, true);
  assert.equal(series.smooth, false);
  assert.equal(series.symbol, "none");
  assert.equal(series.lineStyle.color, option.series[index].lineStyle.color);
  assert.equal(series.lineStyle.opacity, 0);
  assert.equal(series.blur.lineStyle.opacity, 0);
  assert.deepEqual(Array.from(series.emphasis.lineStyle.type), [6, 4]);
  assert.equal(series.emphasis.lineStyle.opacity, 0.58);
  assert.equal(series.emphasis.lineStyle.width, 2);
  assert.equal(series.z, 4);
});
assert.deepEqual(
  Array.from(option.series[10].data.slice(0, -1)),
  metricDynamics.buildStraightTrendLine(timeData.series[1].values, 7),
  "The first rendered page gets a trend fitted to its own sorted row"
);
assert.equal(option.series[10].data.at(-1), null);
assert.equal(option.yAxis.min, 0);
const tooltipHtml = option.tooltip.formatter([
  { seriesIndex: 0, seriesName: "First", axisValueLabel: labels[0], value: 70, color: "#4269D0" },
  { seriesIndex: 5, seriesName: "First label connector", axisValueLabel: labels[0], value: 70, color: "#4269D0" },
  { seriesIndex: 10, seriesName: "First hover trend", axisValueLabel: labels[0], value: 70, color: "#4269D0" }
]);
assert.match(tooltipHtml, /First/);
assert.doesNotMatch(tooltipHtml, /label connector|hover trend/, "Auxiliary label and trend series stay out of the tooltip");

function createFakeChart() {
  const handlers = new Map();
  const zrHandlers = new Map();
  const actions = [];

  return {
    actions,
    handlers,
    zrHandlers,
    dispatchAction(action) {
      actions.push(JSON.parse(JSON.stringify(action)));
    },
    getZr() {
      return {
        on(eventName, handler) {
          zrHandlers.set(eventName, handler);
        }
      };
    },
    on(eventName, handler) {
      handlers.set(eventName, handler);
    },
    resize() {},
    setOption(option) {
      this.option = option;
    }
  };
}

const chart = createFakeChart();
const elementHandlers = new Map();
const chartElement = {
  addEventListener(eventName, handler) {
    elementHandlers.set(eventName, handler);
  },
  contains(target) {
    return target === chartElement;
  }
};
assert.equal(hooks.bindTopPagesTimeHover(chart, 5, chartElement), chart);
assert.ok(chart.handlers.has("mouseover"));
assert.ok(chart.handlers.has("mouseout"));
assert.ok(chart.zrHandlers.has("globalout"));
assert.ok(elementHandlers.has("pointerleave"));
assert.ok(elementHandlers.has("mouseleave"));
const directMousemoveHandler = windowHandlers.get("mousemove").at(-1);

const highlightSeries = (mainSeriesIndex) => ({
  type: "highlight",
  batch: [
    { seriesIndex: mainSeriesIndex },
    { seriesIndex: 10 + mainSeriesIndex, notBlur: true }
  ]
});
const downplaySeries = (mainSeriesIndex) => ({
  type: "downplay",
  batch: [
    { seriesIndex: mainSeriesIndex },
    { seriesIndex: 10 + mainSeriesIndex }
  ]
});

// The payload can contain more candidates than the rendered top five. Mounting
// must bind the auxiliary series blocks using the rendered count.
const mountedChart = createFakeChart();
const mountedElement = {
  addEventListener() {},
  contains() { return true; }
};
window.echarts.init = () => mountedChart;
assert.equal(hooks.mountTopPagesTimeChart(mountedElement, timeData, {
  yAxisName: "Visits",
  formatValue: (value) => String(value),
  selectedPeriodDays: 7
}), mountedChart);
assert.equal(mountedChart.option.series.length, 15);
mountedChart.handlers.get("mouseover")({ seriesType: "line", seriesIndex: 5 });
assert.deepEqual(mountedChart.actions, [highlightSeries(0)]);

// The first connector is the direct end label for the first page. Hovering it
// highlights only that page and makes its paired hidden trend visible.
chart.handlers.get("mouseover")({ seriesType: "line", seriesIndex: 5 });
assert.deepEqual(chart.actions, [highlightSeries(0)]);

chart.handlers.get("mouseover")({ seriesType: "line", seriesIndex: 5 });
chart.handlers.get("mouseout")({ seriesType: "line", seriesIndex: 6 });
directMousemoveHandler({ target: chartElement });
assert.equal(chart.actions.length, 1, "Repeated or unrelated events should preserve the active page");

chart.handlers.get("mouseover")({ seriesType: "line", seriesIndex: 6 });
assert.deepEqual(chart.actions.slice(-2), [downplaySeries(0), highlightSeries(1)]);

chart.handlers.get("mouseout")({ seriesType: "line", seriesIndex: 6 });
assert.deepEqual(chart.actions.at(-1), downplaySeries(1));

chart.handlers.get("mouseover")({ seriesType: "line", seriesIndex: 4 });
assert.deepEqual(chart.actions.at(-1), highlightSeries(4));
elementHandlers.get("pointerleave")();
assert.deepEqual(chart.actions.at(-1), downplaySeries(4));

const actionCountBeforeIgnoredSeries = chart.actions.length;
chart.handlers.get("mouseover")({ seriesType: "bar", seriesIndex: 5 });
chart.handlers.get("mouseover")({ seriesType: "line", seriesIndex: 10 });
assert.equal(chart.actions.length, actionCountBeforeIgnoredSeries, "Trend and unrelated series events should be ignored");

chart.handlers.get("mouseover")({ seriesType: "line", seriesIndex: 9 });
chart.zrHandlers.get("globalout")();
assert.deepEqual(chart.actions.slice(-2), [highlightSeries(4), downplaySeries(4)]);

chart.handlers.get("mouseover")({ seriesType: "line", seriesIndex: 5 });
elementHandlers.get("mouseleave")();
assert.deepEqual(chart.actions.slice(-2), [highlightSeries(0), downplaySeries(0)]);

chart.handlers.get("mouseover")({ seriesType: "line", seriesIndex: 6 });
directMousemoveHandler({ target: {} });
assert.deepEqual(chart.actions.slice(-2), [highlightSeries(1), downplaySeries(1)]);

assert.match(
  overviewCss,
  /#top-pages-visits-time-chart > div,[\s\S]*#top-pages-engaged-time-chart canvas \{\s*cursor: default !important;/
);
assert.ok(
  overviewTemplate.indexOf("js/shared/metric-dynamics.js") < overviewTemplate.indexOf("js/pages/pages-analytics.js"),
  "The overview should load the shared detail-page trend helper before page analytics"
);
assert.match(
  source,
  /mountTopPagesTimeChart\(\s*document\.getElementById\("top-pages-visits-time-chart"\)/
);
assert.match(
  source,
  /mountTopPagesTimeChart\(\s*document\.getElementById\("top-pages-engaged-time-chart"\)/
);

console.log("pages overview time chart tests passed");
