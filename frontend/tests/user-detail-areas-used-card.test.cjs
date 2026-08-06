const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "../..");
const userDetailSource = fs.readFileSync(
  path.join(root, "static/js/users/user-detail.js"),
  "utf8"
);
const { getMetricDynamicsShape } = require(
  path.join(root, "static/js/shared/metric-dynamics.js")
);

// Areas used sits in the slot the merged Active days card gave back, so it is
// an ordinary KPI panel: a headline, a period delta, and a chart.
assert.match(
  userDetailSource,
  /areas_used: "Number of distinct product areas this user used during the selected period"/,
  "the card names what it counts"
);

// A distinct count holds its level until a new area is touched, so it steps and
// carries a fill, and a fit through it would only restate that shape.
assert.deepEqual(getMetricDynamicsShape("areas_used"), {
  name: "discrete_cumulative",
  step: true,
  filled: true,
  selfTrend: false
});

// The headline reads "N product areas", so the comparison tooltip has to read
// the previous period the same way instead of putting a bare number beside it.
assert.match(
  userDetailSource,
  /card\?\.previousValueLabel \|\| formatValueByType\(previousUserMetricValue\(card\), valueTypeForMetric\(card\)\)/,
  "a unit-carrying card supplies its own previous-period wording"
);

// Its value is a count, not a duration or a share.
const valueTypeForMetricSource = userDetailSource.slice(
  userDetailSource.indexOf("function valueTypeForMetric(card) {"),
  userDetailSource.indexOf("function metricTypeForDynamics(card) {")
);

assert.ok(valueTypeForMetricSource, "valueTypeForMetric is still where the test looks for it");
assert.doesNotMatch(
  valueTypeForMetricSource,
  /areas_used/,
  "areas used falls through to plain number formatting"
);
assert.match(
  userDetailSource,
  /function isMetricPercent\(card\) \{\s*return card\?\.id === "interaction_rate";/,
  "interaction rate is still the only percentage card"
);

console.log("user detail areas used card tests passed");
