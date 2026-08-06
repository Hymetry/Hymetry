const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const root = path.resolve(__dirname, "../..");
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
      LinearGradient: class LinearGradient {
        constructor(x, y, x2, y2, colorStops) {
          this.x = x;
          this.y = y;
          this.x2 = x2;
          this.y2 = y2;
          this.colorStops = colorStops;
        }
      }
    }
  },
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
    href: "https://example.com/projects/demo/pages/1/?period=30",
    origin: "https://example.com",
    pathname: "/projects/demo/pages/1/",
    search: "?period=30",
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

for (const relativePath of [
  "static/js/shared/product-area-colors.js",
  "static/js/pages/pages-analytics.js"
]) {
  vm.runInContext(
    fs.readFileSync(path.join(root, relativePath), "utf8"),
    context,
    { filename: relativePath }
  );
}

const data = {
  productAreas: [
    { name: "Project management", color: "#4269D0" },
    { name: "Core workspace", color: "#EFB118" },
    { name: "Reporting", color: "#6CC5B0" }
  ],
  page: {
    displayName: "Task details",
    productAreaName: "Project management",
    productAreaColor: "#4269D0"
  },
  metrics: [{ key: "visits", value: 100 }],
  flow: {
    entryRate: 10,
    exitRate: 20,
    previousPages: [{
      pageName: "Dashboard",
      visits: 50,
      productAreaName: "Core workspace",
      productAreaColor: "#EFB118"
    }],
    nextPages: [{
      pageName: "Reports",
      visits: 40,
      productAreaName: "Reporting",
      productAreaColor: "#6CC5B0"
    }]
  }
};

const hooks = window.HymetryPagesAnalyticsTesting;
assert.ok(hooks, "Page analytics test hooks should be exposed in test mode");
hooks.syncProductAreaPalette(data);

const option = hooks.createDetailPageFlowOption(data);
const nodes = new Map(option.series[0].data.map((node) => [node.name, node]));

assert.equal(nodes.get("current-page").itemStyle.color, "#4269D0");
assert.equal(nodes.get("previous-0").itemStyle.color, "#EFB118");
assert.equal(nodes.get("next-0").itemStyle.color, "#6CC5B0");
assert.equal(nodes.get("direct-entry").itemStyle.color, "#64748b");
assert.equal(nodes.get("page-exit").itemStyle.color, "#64748b");
assert.equal(option.series[0].lineStyle.color, "gradient");

const overviewOption = hooks.createSankeyOption({
  sankey: {
    nodes: [
      { name: "Dashboard", productAreaName: "Core workspace", productAreaColor: "#EFB118" },
      { name: "Reports", productAreaName: "Reporting", productAreaColor: "#6CC5B0" }
    ],
    links: [{ source: "Dashboard", target: "Reports", value: 25 }]
  }
});
const overviewSeries = overviewOption.series[0];
const overviewNodes = new Map(overviewSeries.data.map((node) => [node.name, node]));
const overviewLinkGradient = overviewSeries.links[0].lineStyle.color;

assert.equal(overviewSeries.lineStyle.color, "gradient");
assert.equal(overviewSeries.lineStyle.opacity, 1);
assert.equal(overviewSeries.lineStyle.borderColor, "#ffffff");
assert.equal(overviewSeries.lineStyle.borderWidth, 2);
assert.equal(overviewNodes.get("Dashboard").itemStyle.color, "#EFB118");
assert.equal(overviewNodes.get("Reports").itemStyle.color, "#6CC5B0");
assert.equal(overviewLinkGradient.colorStops[0].color, "#f9e4ae");
assert.equal(overviewLinkGradient.colorStops[1].color, "#ccebe3");

const engagementSpec = hooks.createCompanyEngagementScatterSpec({
  name: "Core workspace",
  product_area_color: "#EFB118",
  points: [{
    company_name: "Edgewater Labs",
    active_users: 5.5,
    active_users_label: "5.5",
    avg_engaged_seconds_per_user: 183.33,
    avg_engaged_label: "3m",
    total_engaged_label: "18m",
    visits: 74
  }]
}, { width: 640 });
const engagementTooltipSignal = engagementSpec.marks
  .find((mark) => mark.name === "companyPoints")
  .encode.update.tooltip.signal;
const engagementPointEncoding = engagementSpec.marks
  .find((mark) => mark.name === "companyPoints")
  .encode.update;

for (const label of [
  "Avg active users",
  "Avg engaged time / user",
  "Total engaged time",
  "Visits"
]) {
  assert.ok(engagementTooltipSignal.includes(`'${label}'`), `${label} should be present in the engagement tooltip`);
}
assert.ok(engagementTooltipSignal.includes("'title': datum.company_name"));
assert.ok(!engagementTooltipSignal.includes("'Company'"));
assert.equal(engagementPointEncoding.cursor.value, "default");
assert.equal(engagementSpec.data[0].values[0].active_users, 5.5);
assert.equal(engagementSpec.data[0].values[0].avg_engaged_seconds_per_user, 183.33);

const pagesAnalyticsSource = fs.readFileSync(
  path.join(root, "static/js/pages/pages-analytics.js"),
  "utf8"
);
assert.doesNotMatch(pagesAnalyticsSource, /data-page-detail-href/);
assert.doesNotMatch(pagesAnalyticsSource, /function mountPageRowNavigation/);
assert.match(pagesAnalyticsSource, /href="\$\{link\}">\$\{pageName\}<\/a>/);

console.log("pages-detail-flow-colors tests passed");
