const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const adapterSource = fs.readFileSync(
  path.resolve(__dirname, "../../static/js/companies/django-companies-data.js"),
  "utf8"
);
const analyticsSource = fs.readFileSync(
  path.resolve(__dirname, "../../static/js/companies/companies-analytics.js"),
  "utf8"
);
const templateSource = fs.readFileSync(
  path.resolve(__dirname, "../../apps/projects/templates/projects/companies.html"),
  "utf8"
);

const initialPayload = {
  period: { days: 30, end_date: "2026-07-27" },
  companies: [],
  productAreas: [{ name: "Core product", shortName: "Core" }],
  atRiskCompanies: [
    {
      companyId: "acme",
      companyName: "Acme Inc.",
      status: "at_risk",
      riskReason: "Engaged drop",
      riskScore: 55,
      suggestedAction: "Review workflow value",
      activeUsers: 4,
      productAreasUsed: 2,
      engagedSeconds: 900,
      productAreas: ["Core product"],
      productAreaDistribution: []
    },
    {
      companyId: "actionless",
      companyName: "Actionless Ltd.",
      status: "at_risk",
      riskReason: "Only 1 active user",
      riskScore: 40,
      // No stored recommendation. The server never emits this, so the only
      // thing that should happen is the defensive default.
      activeUsers: 1,
      engagedSeconds: 120,
      productAreas: [],
      productAreaDistribution: []
    },
    {
      companyId: "newco",
      companyName: "Newco",
      status: "new",
      isNew: true,
      riskReason: "Engaged drop",
      riskScore: 90,
      activeUsers: 1,
      engagedSeconds: 60,
      productAreas: [],
      productAreaDistribution: []
    }
  ],
  expansionOpportunities: [],
  tableData: {
    atRisk: { pagination: { page: 1, pageSize: 20, totalRows: 23, totalPages: 2 } }
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
        table: "atRisk",
        rows: [
          {
            companyId: "zulu",
            companyName: "Zulu Ltd.",
            status: "at_risk",
            riskReason: "No activity 7d",
            riskScore: 12,
            activeUsers: 1,
            engagedSeconds: 30,
            productAreas: [],
            productAreaDistribution: []
          }
        ],
        pagination: { page: 2, pageSize: 20, totalRows: 23, totalPages: 2 }
      })
    };
  },
  location: {
    assign() {},
    origin: "https://example.test",
    pathname: "/projects/1/companies/",
    search: ""
  }
};
const document = {
  documentElement: { style: { setProperty() {} } },
  body: {
    dataset: {
      companiesTableUrl: "/projects/1/companies/table-data/"
    }
  },
  getElementById(id) {
    return id === "companies-overview-data"
      ? { textContent: JSON.stringify(initialPayload) }
      : null;
  },
  querySelectorAll() {
    return [];
  },
  readyState: "complete",
  addEventListener() {}
};

window.document = document;

const context = vm.createContext({
  console,
  document,
  URL,
  URLSearchParams,
  window
});

vm.runInContext(adapterSource, context, { filename: "django-companies-data.js" });

(async () => {
  const provider = window.HymetryCompaniesDemoData;
  const initial = provider.getCompaniesDemoData("30d");

  assert.equal(requests.length, 0, "the embedded payload must not trigger an at-risk fetch");
  assert.equal(
    initial.atRiskCompanies.length,
    2,
    "new and reactivated accounts never belong in the at-risk cohort"
  );
  assert.equal(initial.atRiskCompanies[0].companyName, "Acme Inc.");

  // Sorting Suggested action server-side is only sound because the stored
  // recommendation reaches the cell unchanged. The browser must not rewrite it.
  assert.equal(
    initial.atRiskCompanies[0].suggestedAction,
    "Review workflow value",
    "a stored recommendation is displayed exactly as the server ordered it"
  );
  assert.equal(
    initial.atRiskCompanies[1].suggestedAction,
    "Review account health",
    "a row with no stored recommendation falls back to the server's own default"
  );
  assert.equal(
    initial.atRiskCompanies[0].riskScore,
    55,
    "risk score survives mapping so the client can order by severity"
  );
  assert.equal(initial.tableData.atRisk.pagination.totalRows, 23);

  const page = await provider.loadAtRiskTable({
    page: 2,
    page_size: 20,
    sort: "engagedSeconds",
    direction: "desc",
    period: "30d"
  });

  assert.equal(requests.length, 1);
  assert.equal(page.rows.length, 1);
  assert.equal(page.rows[0].companyName, "Zulu Ltd.");
  assert.equal(page.rows[0].riskReason, "No activity 7d");
  assert.ok(page.rows[0].suggestedAction, "server pages still receive a rendered suggested action");
  assert.equal(page.pagination.page, 2);

  const requestUrl = new URL(requests[0].url, window.location.origin);
  assert.equal(requestUrl.pathname, "/projects/1/companies/table-data/");
  assert.equal(
    requestUrl.searchParams.get("table"),
    "atRisk",
    "the at-risk table shares the companies endpoint and names itself"
  );
  assert.equal(requestUrl.searchParams.get("page"), "2");
  assert.equal(requestUrl.searchParams.get("page_size"), "20");
  assert.equal(requestUrl.searchParams.get("sort"), "engagedSeconds");
  assert.equal(requestUrl.searchParams.get("direction"), "desc");

  // The browser must not re-derive recommendations. A second copy of the
  // server's rules would have to stay in lockstep with it, and the at-risk
  // table now sorts on the stored value, so drift would put the sort order
  // silently out of step with the text in the cell.
  assert.doesNotMatch(adapterSource, /LEGACY_AT_RISK_ACTIONS|LEGACY_EXPANSION_ACTIONS/);
  assert.doesNotMatch(
    adapterSource,
    /Reconnect recent power users|Restart cross-area usage|Re-engage active cohort/,
    "recommendation wordings belong to _suggested_action on the server alone"
  );
  // The expansion table's rules are cohort-relative (p75 of the active company
  // set), which the browser cannot compute from one page of rows. Re-deriving
  // them here can only ever approximate the server.
  assert.doesNotMatch(
    adapterSource,
    /Map executive expansion path|Identify team champions|Package cross-area expansion/,
    "expansion wordings belong to _expansion_reason_and_action on the server alone"
  );

  // Both overview tables page through one controller, so "same pagination
  // style" cannot drift between them.
  const controllerCount = (analyticsSource.match(/createTablePaginationController\(\{/g) || []).length;
  assert.equal(controllerCount, 4, "every overview table pages through the shared controller");
  assert.match(analyticsSource, /tableKey: "newReactivated",\s+rowKey: "newReactivatedCompanies",/);
  assert.match(analyticsSource, /tableKey: "expansion",\s+rowKey: "expansionOpportunities",/);
  assert.match(analyticsSource, /provider\.loadNewReactivatedTable/);
  assert.match(analyticsSource, /provider\.loadExpansionTable/);
  assert.match(
    analyticsSource,
    /tableRowsForRender\(data, "newReactivated", allRows, newReactivatedTableState, newReactivatedPageSize\)/
  );
  assert.match(
    analyticsSource,
    /tableRowsForRender\(data, "expansion", allRows, expansionTableState, expansionPageSize\)/
  );

  // Activation stage is a server definition now; nothing may recompute it, and
  // the row cap that used to hide rows below the page size is gone.
  assert.doesNotMatch(adapterSource, /function activationStatus/);
  assert.doesNotMatch(adapterSource, /slice\(0, 12\)/);
  assert.doesNotMatch(analyticsSource, /function sortNewReactivatedRows/);

  // Adoption-matrix cells are presented as measurements. They must be read from
  // the payload, never spread from a company total.
  assert.match(adapterSource, /activeUsers: Number\(area\?\.active_users/);
  assert.match(adapterSource, /pagesUsed: Number\(area\?\.pages_used/);
  assert.doesNotMatch(
    adapterSource,
    /\* 0\.75|row\.pagesUsed\) \|\| 0\) \/ Math\.max/,
    "per-area users and pages must not be estimated from company totals"
  );
  assert.match(analyticsSource, /tableKey: "atRisk",\s*\n\s*rowKey: "atRiskCompanies",/);
  assert.match(analyticsSource, /tableRowsForRender\(data, "atRisk", sortedRows, atRiskTableState, atRiskPageSize\)/);
  assert.match(analyticsSource, /provider\.loadAtRiskTable/);

  // Every column sorts on the value the server orders by. Suggested action
  // qualifies because the browser passes the stored recommendation through
  // untouched unless it is blank or a retired wording.
  const sortKeys = Array.from(templateSource.matchAll(/data-at-risk-sort="([^"]+)"/g)).map((match) => match[1]);
  assert.deepEqual(sortKeys, [
    "name", "riskScore", "activeUsers", "engagedSeconds", "productAreasUsed", "suggestedAction"
  ]);
  assert.match(templateSource, /data-at-risk-table-scroll/);
  assert.match(templateSource, /data-at-risk-table-loading/);
  assert.match(templateSource, /data-at-risk-pagination/);

  console.log("companies at-risk table tests passed");
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
