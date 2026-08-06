const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "../..");
const userDetailSource = fs.readFileSync(
  path.join(root, "static/js/users/user-detail.js"),
  "utf8"
);
const userDetailHelpersSource = fs.readFileSync(
  path.join(root, "static/js/users/user-details-helpers.js"),
  "utf8"
);
const detailCss = fs.readFileSync(
  path.join(root, "static/css/users/detail.css"),
  "utf8"
);
const activityStripLayout = new Function(`${userDetailSource.slice(
  userDetailSource.indexOf("const activityStripSingleRowLimit"),
  userDetailSource.indexOf("function activityStripMarkup")
)}\nreturn activityStripLayout;`)();

// One card, not two: the strip card replaces both the Active days and the
// Consistency sparkline panels and is recognised by its own render mode rather
// than by its position in the grid.
assert.match(
  userDetailSource,
  /function isActivityStripCard\(card\) \{\s*return card\?\.render === "activity_strip" && Array\.isArray\(card\?\.activityStrip\);/,
  "the strip card is identified by an explicit render mode"
);
assert.match(
  userDetailSource,
  /if \(isActivityStripCard\(card\)\) \{\s*return activityStripPanelMarkup\(card, index\);/,
  "the strip card renders its own panel"
);
assert.match(
  userDetailSource,
  /metrics\.forEach\(\(card, index\) => \{\s*if \(isActivityStripCard\(card\)\) \{\s*return;/,
  "the strip card mounts no chart"
);
assert.doesNotMatch(
  userDetailSource,
  /consistency: "Share of selected days/,
  "the Consistency card description is gone with the card"
);
assert.match(
  userDetailSource,
  /function isMetricPercent\(card\) \{\s*return card\?\.id === "interaction_rate";/,
  "Consistency no longer needs percentage handling"
);

// The card leads with "X of N days" and the share, and the strip carries one
// cell per date with the date, engaged time, and visits in its tooltip.
assert.match(
  userDetailSource,
  /escapeHtml\(card\.value\)[\s\S]{0,200}escapeHtml\(card\.consistencyLabel \|\| ""\)/,
  "the card shows the count and the share together"
);
assert.match(
  userDetailSource,
  /title: formatDateShort\(day\.date\),\s*rows: tooltipRows/,
  "each strip cell names its date"
);
assert.match(
  userDetailSource,
  /\{ label: "Engaged", value: formatDurationWithSeconds\(day\.engagedSeconds\) \},\s*\{ label: "Visits", value: helpers\.formatNumber\(day\.visits\) \}/,
  "each strip cell reports that date's engaged time and visits"
);
assert.match(
  userDetailSource,
  /data-active="\$\{day\.active \? "true" : "false"\}"/,
  "the strip is binary: a date is either active or it is not"
);
assert.doesNotMatch(
  userDetailSource,
  /user-activity-strip__cell[^`]*tabindex/,
  "a period's worth of cells must not each become a tab stop"
);
assert.match(
  userDetailSource,
  /class="user-activity-strip" role="img" aria-label="\$\{escapeHtml\(summary\)\}"/,
  "the strip carries its summary for anyone not reading it visually"
);

// The card's own delta is in points, so the insight sentence that reports a
// number of days has to read the day difference instead.
assert.match(
  userDetailHelpersSource,
  /const activeDaysDelta = Number\(activeDaysCard\?\.activeDaysDelta\);/,
  "the days insight reads the dedicated day-difference field"
);
assert.match(
  userDetailHelpersSource,
  /Number\.isFinite\(activeDaysDelta\) && activeDaysDelta >= 4/,
  "the days insight still requires a real day increase"
);

// One column wide like every other KPI: the slot it used to take twice over is
// now the Areas used card, so the strip has to hold a long period by wrapping
// rather than by squeezing its dates into slivers.
assert.doesNotMatch(
  userDetailSource,
  /user-detail-kpi-grid__wide/,
  "the strip card no longer claims a second column"
);
assert.doesNotMatch(detailCss, /user-detail-kpi-grid__wide/);
assert.match(detailCss, /\.user-activity-strip \{[\s\S]*?display: grid;/);
assert.match(
  detailCss,
  /grid-template-columns: repeat\(var\(--user-activity-strip-columns, 30\), minmax\(0, 1fr\)\);/,
  "the card decides how many columns the period needs"
);
assert.match(
  detailCss,
  /grid-auto-rows: var\(--user-activity-strip-cell-height, 2\.25rem\);/
);
assert.match(
  detailCss,
  /\.user-activity-strip__cell\[data-active="true"\] \{\s*background: var\(--color-c-blue, #4269d0\);/
);

// A month or less stays the single tall row it already was; anything longer
// wraps into a calendar-style block of shorter cells.
assert.deepEqual(activityStripLayout(7), { columns: 7, cellHeight: "2.25rem" });
assert.deepEqual(activityStripLayout(30), { columns: 30, cellHeight: "2.25rem" });
assert.deepEqual(activityStripLayout(90), { columns: 30, cellHeight: "0.5rem" });
assert.deepEqual(activityStripLayout(180), { columns: 30, cellHeight: "0.5rem" });

console.log("user detail active days card tests passed");
