const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const analyticsTooltips = require("../../static/js/shared/analytics-tooltips.js");

const analyticsPath = path.resolve(
  __dirname,
  "../../static/js/users/users-analytics.js"
);
const analyticsSource = fs.readFileSync(analyticsPath, "utf8");
const usersTemplateSource = fs.readFileSync(
  path.resolve(__dirname, "../../apps/projects/templates/projects/users.html"),
  "utf8"
);
const userDetailSource = fs.readFileSync(
  path.resolve(__dirname, "../../static/js/users/user-detail.js"),
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
  createKpiTrendOption,
  formatKpiHeadlineValue,
  kpiTrendValueFormat
} = analyticsWindow.HymetryUsersAnalyticsTesting;

function tooltipFor(kpi, values, labels) {
  const option = createKpiTrendOption(
    values,
    kpi.deltaType,
    labels,
    kpi.sparklineLabel || kpi.label,
    kpiTrendValueFormat(kpi),
    kpi.sparklineScope
  );

  return (dataIndex) => option.tooltip.formatter([{ dataIndex, value: values[dataIndex] }]);
}

const labels = ["2026-07-04", "2026-07-05"];

// Daily averages still carry raw seconds and need duration formatting.
const engagedTooltip = tooltipFor(
  {
    key: "engagedPerUser",
    label: "Avg daily engaged / user",
    sparklineLabel: "Daily engaged / user",
    sparklineScope: "daily",
    deltaType: "positive"
  },
  [45, 90],
  labels
);

assert.match(engagedTooltip(1), /Jul 5/, "the tooltip identifies the observed day");
assert.doesNotMatch(engagedTooltip(1), /Through Jul 5/, "a daily average is not labelled period to date");
assert.match(engagedTooltip(1), />1m 30s</, "engaged time per user is shown as a duration");
assert.match(engagedTooltip(0), />45s</, "sub-minute engaged time keeps second precision");
assert.doesNotMatch(engagedTooltip(1), />90</, "raw seconds must not reach the tooltip");

const activeUsersTooltip = tooltipFor(
  {
    key: "activeUsers",
    label: "Avg daily active users",
    sparklineLabel: "Daily active users",
    sparklineScope: "daily",
    deltaType: "positive"
  },
  [1200, 1500],
  labels
);

assert.match(activeUsersTooltip(1), />1,500</, "counted KPIs keep plain number formatting");
assert.doesNotMatch(activeUsersTooltip(1), /Through Jul 5/, "all overview user KPI lines use daily dates");

const emptyDayOption = createKpiTrendOption(
  [45, null, 90],
  "neutral",
  ["2026-07-04", "2026-07-05", "2026-07-06"],
  "Daily engaged / user",
  "duration",
  "daily"
);
assert.equal(emptyDayOption.series[0].data[1], null, "empty denominator days remain chart gaps");
assert.equal(emptyDayOption.yAxis.min, 45, "chart bounds ignore null gaps");
assert.equal(emptyDayOption.series[0].smooth, false, "daily KPI lines do not curve beyond observed values");

assert.equal(kpiTrendValueFormat({ key: "powerUsers" }), "number");
assert.equal(kpiTrendValueFormat(undefined), "number");
assert.equal(
  formatKpiHeadlineValue({ value: 0.17, sparklineScope: "daily" }),
  "0.17",
  "daily-average count headlines preserve meaningful fractions"
);
assert.equal(
  formatKpiHeadlineValue({ value: 1200, sparklineScope: "daily" }),
  "1,200",
  "whole daily-average count headlines retain thousands separators"
);

assert.match(
  analyticsSource,
  /createKpiTrendOption\([\s\S]*?kpi\.sparkline,[\s\S]*?kpi\.sparklineLabel \|\| kpi\.label,[\s\S]*?kpiTrendValueFormat\(kpi\),[\s\S]*?kpi\.sparklineScope[\s\S]*?\)/,
  "the KPI cards must mount their sparkline with the KPI's own label, value format, and grain"
);

assert.doesNotMatch(
  usersTemplateSource,
  /data-users-kpi-secondary/,
  "all Users overview KPI sparklines share the same vertical position"
);
assert.doesNotMatch(
  analyticsSource,
  /data-users-kpi-secondary|kpi\.secondary/,
  "the Users overview renderer does not add a second text row above selected sparklines"
);

assert.match(
  userDetailSource,
  /title:\s*dateLabel\s*\?\s*`Through \$\{dateLabel\}`\s*:\s*"Period to date"/,
  "User-detail metric tooltips identify period-to-date points"
);
assert.match(
  userDetailSource,
  /metricTooltipRow\("Period to date",\s*actualValue/,
  "User-detail metric tooltips name the plotted value at its period-to-date grain"
);
assert.match(
  userDetailSource,
  /valueType === "percent"[\s\S]*?const roundedValue = Math\.round\(\(numericValue \+ Number\.EPSILON\) \* factor\) \/ factor;[\s\S]*?return `\$\{roundedValue\.toFixed\(decimals\)\}%`/,
  "User-detail series percentages are already percentage points and are not multiplied again"
);
assert.match(
  userDetailSource,
  /formattedDelta = card\?\.deltaLabel \|\| helpers\.formatDelta/,
  "User-detail cards preserve zero-baseline New labels"
);
assert.match(
  userDetailSource,
  /const isNew = comparisonAvailable !== false && deltaLabel === "New"/,
  "User page rows render zero-baseline changes as New"
);
assert.doesNotMatch(
  userDetailSource,
  /syntheticTrendValues|deterministicNumber/,
  "User-detail metric and product-area charts must not fabricate peer histories from period scalars"
);
assert.match(
  userDetailSource,
  /minPeerCount:\s*5/,
  "User-detail benchmark trends require the documented five observed peers"
);

console.log("users KPI sparkline unit tests passed");
