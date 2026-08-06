const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const vega = require("../../static/js/vendor/vega.min.js");

const adapterPath = path.resolve(
  __dirname,
  "../../static/js/users/django-users-data.js"
);
const analyticsPath = path.resolve(
  __dirname,
  "../../static/js/users/users-analytics.js"
);
const adapterSource = fs.readFileSync(adapterPath, "utf8");
const analyticsSource = fs.readFileSync(analyticsPath, "utf8");
const initialScatter = Array.from({ length: 320 }, (_, index) => ({
  id: `stable-point-${index + 1}`,
  name: `Stable Point ${index + 1}`
}));
const initialPayload = {
  period: { days: 180 },
  users: [{ id: "initial-user" }],
  scatter: initialScatter,
  tableData: {
    users: {
      pagination: { page: 1, pageSize: 20, totalRows: 61, totalPages: 4 }
    }
  }
};
const requests = [];
const window = {
  document: null,
  fetch: async (url, options) => {
    requests.push({ url, options });
    return {
      ok: true,
      json: async () => ({
        table: "users",
        rows: [{ id: "page-two-user" }],
        pagination: { page: 2, pageSize: 20, totalRows: 61, totalPages: 4 },
        scatter: [{ id: "must-not-replace-chart" }]
      })
    };
  },
  location: {
    assign() {},
    origin: "https://example.test",
    pathname: "/projects/1/users/",
    search: "?range=last_180_days"
  }
};
const document = {
  body: {
    dataset: {
      usersRangeKey: "last_180_days",
      usersTableUrl: "/projects/1/users/table-data/"
    }
  },
  getElementById(id) {
    return id === "users-overview-data"
      ? { textContent: JSON.stringify(initialPayload) }
      : null;
  }
};

window.document = document;

const context = vm.createContext({
  console,
  document,
  URL,
  URLSearchParams,
  window
});

vm.runInContext(adapterSource, context, { filename: "django-users-data.js" });

(async () => {
  const provider = window.HymetryUsersDemoData;
  const initial = provider.getUsersAnalyticsData("180d");

  assert.equal(requests.length, 0, "initial analytics data must not trigger a deferred users fetch");
  assert.equal(initial.users[0].id, "initial-user");
  assert.equal(initial.scatter.length, 300, "the stable scatter is capped at 300 rows");
  assert.equal(initial.tableData.users.pagination.totalRows, 61);
  assert.equal(typeof provider.loadDeferredUsersData, "undefined");

  const page = await provider.loadUsersTable({
    page: 2,
    page_size: 20,
    sort: "name",
    direction: "asc",
    company: "Edgewater Labs",
    role: "Admin",
    status: "Healthy",
    q: "alex",
    identified: "1",
    feature: "Dashboard",
    period: "180d"
  });

  assert.equal(page.rows[0].id, "page-two-user");
  assert.equal(page.pagination.page, 2);
  assert.equal(requests.length, 1);
  assert.equal(requests[0].options.credentials, "same-origin");

  const requestUrl = new URL(requests[0].url, window.location.origin);
  assert.equal(requestUrl.pathname, "/projects/1/users/table-data/");
  assert.equal(requestUrl.searchParams.get("range"), "last_180_days");
  assert.equal(requestUrl.searchParams.get("page"), "2");
  assert.equal(requestUrl.searchParams.get("page_size"), "20");
  assert.equal(requestUrl.searchParams.get("sort"), "name");
  assert.equal(requestUrl.searchParams.get("direction"), "asc");
  assert.equal(requestUrl.searchParams.get("company"), "Edgewater Labs");
  assert.equal(requestUrl.searchParams.get("role"), "Admin");
  assert.equal(requestUrl.searchParams.get("status"), "Healthy");
  assert.equal(requestUrl.searchParams.get("q"), "alex");
  assert.equal(requestUrl.searchParams.get("identified"), "1");
  assert.equal(requestUrl.searchParams.get("feature"), "Dashboard");
  assert.equal(requestUrl.searchParams.has("period"), false);

  const afterPageLoad = provider.getUsersAnalyticsData("180d");
  assert.equal(afterPageLoad.users[0].id, "initial-user", "table responses are applied by the table renderer only");
  assert.equal(afterPageLoad.scatter[0].id, "stable-point-1");
  assert.equal(afterPageLoad.scatter.at(-1).id, "stable-point-300");

  const tableLoaderSource = analyticsSource.match(
    /function loadUsersTablePage[\s\S]*?\n  function simulateUsersTableLoad/
  )?.[0] || "";
  assert.match(tableLoaderSource, /provider\.loadUsersTable/);
  assert.doesNotMatch(
    tableLoaderSource,
    /mountConsistencyIntensityScatter/,
    "table page loads must never remount the scatter chart"
  );
  assert.match(analyticsSource, /const serverTable = hasServerUsersTable\(\)/);
  assert.match(analyticsSource, /const pageRows = serverTable \? rows : rows\.slice/);
  assert.match(analyticsSource, /from: \{ data: "userPoints" \}/);
  assert.match(analyticsSource, /datum\.datum\.showLabel \? datum\.datum\.userName : ''/);
  assert.match(analyticsSource, /datum\.datum\.showLabel \? 1 : 0/);
  assert.match(analyticsSource, /identified: \(!identifiedControl \|\| identifiedControl\.checked\) \? "1" : "0"/);
  assert.match(analyticsSource, /data\.tableData\?\.users\?\.filterOptions/);
  assert.doesNotMatch(analyticsSource, /hydrateDeferredUsersData|loadDeferredUsersData/);

  const analyticsDocument = {
    body: { dataset: {} },
    documentElement: {},
    addEventListener() {}
  };
  const analyticsWindow = {
    __HymetryExposeTestHooks: true,
    document: analyticsDocument,
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
  const analyticsContext = vm.createContext({
    console,
    document: analyticsDocument,
    Intl,
    URLSearchParams,
    window: analyticsWindow
  });

  vm.runInContext(analyticsSource, analyticsContext, { filename: "users-analytics.js" });
  const scatterSpec = analyticsWindow.HymetryUsersAnalyticsTesting.createUserConsistencyScatterSpec([
    {
      userName: "Selected label",
      sessionsPerWeek: 2,
      avgEngagedPerSession: 120,
      status: "Healthy",
      pointSize: 46,
      showLabel: true
    },
    {
      userName: "Hidden label",
      sessionsPerWeek: 1,
      avgEngagedPerSession: 60,
      status: "Light",
      pointSize: 46,
      showLabel: false
    }
  ], { width: 640 });
  const labelMark = scatterSpec.marks.find((mark) => mark.type === "text" && mark.from?.data === "userPoints");

  assert.ok(labelMark, "scatter labels must derive from the rendered point marks");
  assert.equal(labelMark.encode.enter.text.signal, "datum.datum.showLabel ? datum.datum.userName : ''");
  assert.equal(labelMark.encode.enter.opacity.signal, "datum.datum.showLabel ? 1 : 0");
  assert.doesNotThrow(() => vega.parse(scatterSpec), "the stable selected-label Vega spec must compile");

  console.log("users table data tests passed");
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
