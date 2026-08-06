const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "../..");
const {
  bindLineTrendHover,
  buildMetricDynamicsSeries,
  buildStraightTrendLine,
  getMetricDynamicsShape
} = require(path.join(root, "static/js/shared/metric-dynamics.js"));

// How a metric dynamics panel is drawn follows from what its points mean. The
// keys arrive from three different detail pages in three different casings, so
// the mapping has to survive normalization.
[
  ["companies", "cumulative_total"],
  ["visits", "cumulative_total"],
  ["engaged", "cumulative_total"],
  ["engaged_time", "cumulative_total"],
  ["activeUsers", "cumulative_total"],
  ["newReactivatedUsers", "cumulative_total"],
  ["adoption", "rate"],
  ["penetration", "rate"],
  ["avg_visit", "rate"],
  ["clicks_per_visit", "rate"],
  ["interaction", "rate"],
  ["interaction_rate", "rate"],
  ["avgPerUser", "rate"],
  ["intensity", "rate"],
  ["adoptionBreadth", "discrete_cumulative"],
  ["pages_used", "discrete_cumulative"],
  ["areas_used", "discrete_cumulative"],
  ["atRiskUsers", "daily_state"]
].forEach(([metricType, expectedShape]) => {
  assert.equal(getMetricDynamicsShape(metricType).name, expectedShape, metricType);
});

// Totals carry a fill and no self-trend; rates are unfilled and keep one.
// Distinct counts and end-of-day states step instead of sloping.
assert.deepEqual(getMetricDynamicsShape("visits"), {
  name: "cumulative_total",
  step: false,
  filled: true,
  selfTrend: false
});
assert.deepEqual(getMetricDynamicsShape("adoption"), {
  name: "rate",
  step: false,
  filled: false,
  selfTrend: true
});
assert.deepEqual(getMetricDynamicsShape("pages_used"), {
  name: "discrete_cumulative",
  step: true,
  filled: true,
  selfTrend: false
});
assert.deepEqual(getMetricDynamicsShape("atRiskUsers"), {
  name: "daily_state",
  step: true,
  filled: false,
  selfTrend: true
});

// The shape rides along with the series so the panels do not have to re-derive
// it, but the fit itself is still computed: other consumers draw it as their
// main line rather than as an overlay to be suppressed.
const cumulativeDynamics = buildMetricDynamicsSeries({
  currentSeries: [1, 2, 3],
  metricType: "visits"
});
assert.equal(cumulativeDynamics.shape.name, "cumulative_total");
assert.equal(cumulativeDynamics.shape.selfTrend, false);
assert.equal(cumulativeDynamics.currentStraightTrendSeries.length, 3);
assert.equal(
  buildMetricDynamicsSeries({
    currentSeries: [10, 20, 15],
    metricType: "adoption"
  }).shape.selfTrend,
  true
);

function assertCloseSeries(actual, expected, tolerance = 1e-10) {
  assert.equal(actual.length, expected.length);
  actual.forEach((value, index) => {
    assert.ok(
      Math.abs(value - expected[index]) <= tolerance,
      `Expected value ${value} at index ${index} to be within ${tolerance} of ${expected[index]}`
    );
  });
}

assertCloseSeries(
  buildStraightTrendLine([1, 3, 5, 7, 9], 30),
  [1, 3, 5, 7, 9]
);

assertCloseSeries(
  buildStraightTrendLine([9, 7, 5, 3, 1], 30),
  [9, 7, 5, 3, 1]
);

assertCloseSeries(
  buildStraightTrendLine([4, 4, 4, 4], 30),
  [4, 4, 4, 4]
);

assertCloseSeries(
  buildStraightTrendLine([1, null, 5, null, 9], 30),
  [1, 3, 5, 7, 9]
);
assert.deepEqual(buildStraightTrendLine([1, null, 3], 30), []);

const undersizedBenchmark = buildMetricDynamicsSeries({
  currentSeries: [1, 2, 3],
  benchmarkSeries: [2, 3, 4],
  benchmarkEligiblePeerCount: 1,
  minPeerCount: 5
});
assert.deepEqual(
  undersizedBenchmark.benchmarkStraightTrendSeries,
  [],
  "an explicit benchmark must still meet the peer-count minimum"
);
const eligibleBenchmark = buildMetricDynamicsSeries({
  currentSeries: [1, 2, 3],
  benchmarkSeries: [2, 3, 4],
  benchmarkEligiblePeerCount: 5,
  minPeerCount: 5
});
assert.deepEqual(
  eligibleBenchmark.benchmarkStraightTrendSeries,
  [2, 3, 4],
  "an explicit benchmark is rendered once enough peers contributed"
);

const seasonalDecline = Array.from(
  { length: 28 },
  (_, index) => 200 - index * 2 + [30, 20, 10, 0, -10, -20, -30][index % 7]
);
const seasonalTrend = buildStraightTrendLine(seasonalDecline, 30);
assert.equal(seasonalTrend.length, seasonalDecline.length);
assert.ok(
  seasonalTrend.at(-1) < seasonalTrend[0],
  "A declining series with weekly seasonality should have a falling OLS trend"
);

const endpointTrap = Array(6).fill(0)
  .concat([100], Array(14).fill(100), Array(7).fill(1));
const endpointTrapTrend = buildStraightTrendLine(endpointTrap, 30);
assert.ok(
  endpointTrapTrend.at(-1) < endpointTrapTrend[0],
  "OLS should detect the full-series decline even when endpoint-window medians rise"
);

const dashboardVisits = [
  185, 165, 148, 41, 12, 144, 212, 161, 156, 159,
  49, 16, 106, 111, 132, 179, 151, 35, 10, 157,
  187, 170, 206, 142, 30, 15, 157, 219, 187, 175
];
const dashboardTrend = buildStraightTrendLine(dashboardVisits, 30);
assert.ok(Math.abs(dashboardTrend[0] - 116.39139784946236) <= 1e-10);
assert.ok(Math.abs(dashboardTrend.at(-1) - 138.0752688172043) <= 1e-10);

const userDetailSource = fs.readFileSync(
  path.join(root, "static/js/users/user-detail.js"),
  "utf8"
);
const userDetailTemplate = fs.readFileSync(
  path.join(root, "apps/projects/templates/projects/user_detail.html"),
  "utf8"
);
assert.match(
  userDetailSource,
  /function createProductAreaMixChartOption[\s\S]{0,1200}const currentTrendSeries = dynamics\.currentStraightTrendSeries \|\| dynamics\.currentTrend \|\| \[\];/,
  "The product-area comparison should reuse the shared OLS trend"
);
assert.doesNotMatch(
  userDetailSource,
  /function linearApproximationValues/,
  "User detail should not retain a separate endpoint-window trend calculation"
);
assert.ok(
  userDetailTemplate.indexOf("js/shared/metric-dynamics.js") < userDetailTemplate.indexOf("js/users/user-detail.js"),
  "User detail should load the shared OLS helper before its chart consumer"
);

function createFakeChart() {
  const actions = [];
  const handlers = new Map();
  const zrHandlers = new Map();

  return {
    actions,
    handlers,
    zrHandlers,
    on(eventName, handler) {
      handlers.set(eventName, handler);
    },
    dispatchAction(action) {
      actions.push(action);
    },
    getZr() {
      return {
        on(eventName, handler) {
          zrHandlers.set(eventName, handler);
        }
      };
    }
  };
}

const chart = createFakeChart();
const elementHandlers = new Map();
const element = {
  addEventListener(eventName, handler) {
    elementHandlers.set(eventName, handler);
  }
};
const highlightSeries = (seriesIndex) => ({
  type: "highlight",
  batch: [
    { seriesIndex },
    { seriesIndex: 4 + seriesIndex, notBlur: true }
  ]
});
const downplaySeries = (seriesIndex) => ({
  type: "downplay",
  batch: [
    { seriesIndex },
    { seriesIndex: 4 + seriesIndex }
  ]
});

assert.equal(bindLineTrendHover(chart, 2, element), chart);
assert.ok(chart.handlers.has("mouseover"));
assert.ok(chart.handlers.has("mouseout"));
assert.ok(chart.zrHandlers.has("globalout"));
assert.ok(elementHandlers.has("pointerleave"));
assert.ok(elementHandlers.has("mouseleave"));

chart.handlers.get("mouseover")({ seriesType: "line", seriesIndex: 0 });
assert.deepEqual(chart.actions, [highlightSeries(0)]);

chart.handlers.get("mouseover")({ seriesType: "line", seriesIndex: 0 });
assert.equal(chart.actions.length, 1, "Repeated hover should preserve the active series");

chart.handlers.get("mouseover")({ seriesType: "line", seriesIndex: 3 });
assert.deepEqual(chart.actions.slice(-2), [downplaySeries(0), highlightSeries(1)]);

chart.handlers.get("mouseout")({ seriesType: "line", seriesIndex: 2 });
assert.deepEqual(
  chart.actions.at(-1),
  highlightSeries(1),
  "Mouseout from an unrelated connector should preserve the active series"
);

chart.handlers.get("mouseout")({ seriesType: "line", seriesIndex: 3 });
assert.deepEqual(chart.actions.at(-1), downplaySeries(1));

const actionCountBeforeIgnoredSeries = chart.actions.length;
chart.handlers.get("mouseover")({ seriesType: "bar", seriesIndex: 0 });
chart.handlers.get("mouseover")({ seriesType: "line", seriesIndex: 4 });
assert.equal(chart.actions.length, actionCountBeforeIgnoredSeries);

chart.handlers.get("mouseover")({ seriesType: "line", seriesIndex: 1 });
chart.zrHandlers.get("globalout")();
assert.deepEqual(chart.actions.slice(-2), [highlightSeries(1), downplaySeries(1)]);

chart.handlers.get("mouseover")({ seriesType: "line", seriesIndex: 0 });
elementHandlers.get("pointerleave")();
assert.deepEqual(chart.actions.slice(-2), [highlightSeries(0), downplaySeries(0)]);

chart.handlers.get("mouseover")({ seriesType: "line", seriesIndex: 1 });
elementHandlers.get("mouseleave")();
assert.deepEqual(chart.actions.slice(-2), [highlightSeries(1), downplaySeries(1)]);

console.log("metric-dynamics trend tests passed");
