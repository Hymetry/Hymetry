const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const helperPath = path.resolve(
  __dirname,
  "../../static/js/shared/analytics-tooltips.js"
);
const tooltipUi = require(helperPath);

const html = tooltipUi.render({
  title: "Engagement <overview>",
  rows: [
    { label: "Company", value: "Edgewater & Labs" },
    { label: "Visits", value: "529", marker: { color: "#4269d0" } }
  ]
});

assert.match(html, /class="analytics-tooltip analytics-tooltip--table"/);
assert.match(html, /class="analytics-tooltip__label">Company/);
assert.match(html, /<strong class="analytics-tooltip__value">529<\/strong>/);
assert.match(html, /analytics-tooltip__row--marker/);
assert.match(html, /--analytics-tooltip-marker:#4269d0/);
assert.match(html, /Engagement &lt;overview&gt;/);
assert.match(html, /Edgewater &amp; Labs/);
assert.doesNotMatch(html, /<script/i);

const modernColorHtml = tooltipUi.render({
  rows: [{ label: "Users", value: "42", marker: { color: "oklch(70.7% 0.165 254.624)" } }]
});
assert.match(modernColorHtml, /--analytics-tooltip-marker:oklch\(70\.7% 0\.165 254\.624\)/);
assert.doesNotMatch(
  tooltipUi.render({ rows: [{ label: "Users", value: "42", marker: { color: "red;position:fixed" } }] }),
  /red;position/
);

const threeColumnHtml = tooltipUi.render({
  rows: [{
    label: "Passive",
    value: "75%",
    secondaryValue: "2,146 users",
    marker: { color: "#9c6b4e" }
  }]
});
assert.match(threeColumnHtml, /analytics-tooltip__row--three-column/);
assert.match(threeColumnHtml, /analytics-tooltip__rows--three-column/);
assert.match(threeColumnHtml, /analytics-tooltip__rows--with-markers/);
assert.match(threeColumnHtml, /<strong class="analytics-tooltip__value">75%<\/strong>/);
assert.match(threeColumnHtml, /<strong class="analytics-tooltip__secondary-value">2,146 users<\/strong>/);

const sectionedHtml = tooltipUi.render({
  sections: [
    { rows: [{ label: "Current period", value: "3,800" }] },
    { title: "Area usage", rows: [{ label: "Core workspace", value: "38m" }] }
  ]
});
assert.match(sectionedHtml, /analytics-tooltip__divider/);
assert.match(sectionedHtml, /class="analytics-tooltip__section-title">Area usage/);
assert.match(sectionedHtml, /class="analytics-tooltip__label">Core workspace/);
assert.doesNotMatch(
  tooltipUi.render({ title: "Dashboard", rows: [] }),
  /analytics-tooltip--table/
);
assert.equal(
  tooltipUi.text([
    { label: "Current period", value: "3,800" },
    { label: "Change", value: "+6.6%" }
  ]),
  "Current period: 3,800. Change: +6.6%"
);
assert.equal(
  tooltipUi.text([{ label: "Passive", value: "75%", secondaryValue: "2,146 users" }]),
  "Passive: 75%, 2,146 users"
);

const echartsTooltip = tooltipUi.echarts({ trigger: "axis" });
assert.equal(echartsTooltip.renderMode, "html");
assert.equal(echartsTooltip.textStyle.fontSize, 14);
assert.equal(echartsTooltip.textStyle.color, "#334155");
assert.equal(echartsTooltip.textStyle.fontWeight, 400);
assert.match(echartsTooltip.extraCssText, /font-size:14px/);
assert.match(echartsTooltip.extraCssText, /color:#334155/);
assert.match(echartsTooltip.extraCssText, /white-space:normal/);
assert.equal(
  tooltipUi.floatingTooltipLeft({
    triggerRect: { left: 100, width: 800 },
    tooltipWidth: 200,
    viewportWidth: 1_000
  }),
  400
);
assert.equal(
  tooltipUi.floatingTooltipLeft({
    triggerRect: { left: 100, width: 800 },
    tooltipWidth: 200,
    viewportWidth: 1_000,
    pointerX: 150
  }),
  50
);
assert.equal(
  tooltipUi.floatingTooltipLeft({
    triggerRect: { left: 100, width: 800 },
    tooltipWidth: 200,
    viewportWidth: 1_000,
    pointerX: 20
  }),
  8
);
assert.equal(
  tooltipUi.floatingTooltipLeft({
    triggerRect: { left: 100, width: 800 },
    tooltipWidth: 200,
    viewportWidth: 1_000,
    pointerX: 990
  }),
  792
);

const helperSource = fs.readFileSync(helperPath, "utf8");
const tooltipCss = fs.readFileSync(path.resolve(
  __dirname,
  "../../static/css/table-tooltips.css"
), "utf8");
assert.match(tooltipCss, /\.analytics-tooltip__rows--three-column\s*\{[\s\S]*?grid-template-columns:\s*minmax\(0, 1fr\) auto auto;/);
assert.match(tooltipCss, /\.analytics-tooltip__rows--three-column\.analytics-tooltip__rows--with-markers\s*\{[\s\S]*?grid-template-columns:\s*auto minmax\(0, 1fr\) auto auto;/);
assert.match(tooltipCss, /\.analytics-tooltip__rows--three-column \.analytics-tooltip__row--three-column\s*\{[\s\S]*?display:\s*contents;/);
assert.match(helperSource, /triggerRect\.bottom < 0/);
assert.match(helperSource, /triggerRect\.top > viewportHeight/);
assert.match(helperSource, /const maxTop = Math\.max\(margin, viewportHeight - tooltipRect\.height - margin\)/);
assert.match(helperSource, /const top = Math\.min\(Math\.max\(desiredTop, margin\), maxTop\)/);
assert.match(helperSource, /documentObject\.addEventListener\("pointermove"/);

console.log("analytics-tooltips tests passed");
