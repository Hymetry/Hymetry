(function mountDjangoCompanyDetailData(globalScope) {
  const dataElement = document.getElementById("company-detail-data");
  const body = document.body;
  let bundle = {};

  try {
    bundle = JSON.parse(dataElement?.textContent || "{}");
  } catch {
    bundle = {};
  }

  const payload = bundle.payload || null;
  let periodNavigationPending = false;
  const PERIOD_OPTIONS = [7, 30, 90, 180];
  const DEFAULT_PERIOD = coercePeriodKey(payload?.period?.key || bundle.selected_period || "30d");
  const secondaryAreaNamePattern = /admin|setting|permission|support|setup|technical/i;

  function coercePeriodKey(value) {
    const normalized = String(value || "30d").trim().toLowerCase();
    const digits = normalized.replace(/[^0-9]/g, "");
    const days = Number(digits) || 30;

    return PERIOD_OPTIONS.includes(days) ? `${days}d` : "30d";
  }

  function periodDigits(period) {
    return coercePeriodKey(period).replace("d", "");
  }

  function appendParams(url, params) {
    const separator = String(url).includes("?") ? "&" : "?";

    return `${url}${separator}${params.toString()}`;
  }

  function optionsUrl(baseUrl, query, periodValue, limit = 20) {
    const nextUrl = new URL(baseUrl, globalScope.location.origin);

    nextUrl.searchParams.set("period", coercePeriodKey(periodValue || payload?.period?.key || DEFAULT_PERIOD));
    nextUrl.searchParams.set("limit", String(limit));

    if (String(query || "").trim()) {
      nextUrl.searchParams.set("q", String(query || "").trim());
    } else {
      nextUrl.searchParams.delete("q");
    }

    return `${nextUrl.pathname}${nextUrl.search}`;
  }

  function tableRequestUrl(baseUrl, options = {}) {
    const nextUrl = new URL(baseUrl, globalScope.location.origin);

    nextUrl.searchParams.set("period", coercePeriodKey(options.period || options.periodValue || payload?.period?.key || DEFAULT_PERIOD));

    Object.entries(options).forEach(([key, value]) => {
      if (key === "period" || key === "periodValue" || value === undefined || value === null || value === "") {
        return;
      }
      nextUrl.searchParams.set(key, String(value));
    });

    return `${nextUrl.pathname}${nextUrl.search}`;
  }

  function fetchTable(baseUrl, options = {}) {
    if (!baseUrl || !globalScope.fetch) {
      return Promise.resolve(null);
    }

    return globalScope.fetch(tableRequestUrl(baseUrl, options), {
      credentials: "same-origin",
      headers: { Accept: "application/json" }
    })
      .then((response) => (response.ok ? response.json() : null))
      .catch(() => null);
  }

  function navigateToPeriod(period) {
    const requestedPeriod = coercePeriodKey(period);

    if (requestedPeriod === DEFAULT_PERIOD) {
      return false;
    }

    const params = new URLSearchParams(globalScope.location.search);
    params.set("period", requestedPeriod);
    periodNavigationPending = true;
    globalScope.location.assign(`${globalScope.location.pathname}?${params.toString()}`);
    return true;
  }

  function isPeriodNavigationPending() {
    return periodNavigationPending;
  }

  function isPayloadPending() {
    return !payload && (bundle.status === "preparing" || bundle.status === "pending");
  }

  function orderedProductAreaNames(areas) {
    const names = (areas || [])
      .map((area) => (typeof area === "string" ? area : area?.name || area?.productArea || ""))
      .filter(Boolean);

    return Array.from(new Set(names)).sort((a, b) => {
      const aSecondary = secondaryAreaNamePattern.test(a) ? 1 : 0;
      const bSecondary = secondaryAreaNamePattern.test(b) ? 1 : 0;

      return aSecondary - bSecondary ||
        names.indexOf(a) - names.indexOf(b) ||
        String(a).localeCompare(String(b));
    });
  }

  function productAreaNames() {
    return orderedProductAreaNames(bundle.productAreas || payload?.productAreas || []);
  }

  function fallbackCompanyRows() {
    const rows = [];

    if (payload?.company) {
      rows.push(payload.company);
    }

    (payload?.peerComparison?.rows || []).forEach((row) => {
      if (row?.id && !rows.some((company) => company.id === row.id)) {
        rows.push(row);
      }
    });

    return rows;
  }

  function normalizeCompany(row) {
    const id = row.id || row.companyId || row.company_id || "";
    const name = row.name || row.companyName || row.company_name || id;
    const productAreaDistribution = (row.productAreaDistribution || []).map((area) => ({
      ...area,
      productArea: area.productArea || area.product_area_name || area.name || "Unassigned",
      percent: Number(area.percent) || 0,
      engagedSeconds: Number(area.engagedSeconds || area.engaged_seconds || 0),
      visits: Number(area.visits) || 0
    }));

    return {
      id,
      companyId: id,
      name,
      companyName: name,
      domain: row.domain || "",
      status: row.status || "healthy",
      activeUsers: Number(row.activeUsers || row.active_users || 0),
      productAreasUsed: Number(row.productAreasUsed || row.product_areas_used || 0),
      pagesUsed: Number(row.pagesUsed || row.pages_used || 0),
      visits: Number(row.visits || 0),
      engagedSeconds: Number(row.engagedSeconds || row.engaged_seconds || 0),
      avgEngagedSecondsPerUser: Number(row.avgEngagedSecondsPerUser || row.avg_engaged_seconds_per_user || 0),
      interactionPct: Number(row.interactionPct || row.interaction_pct || 0),
      lastSeen: row.lastSeen || row.lastActiveAt || "",
      lastSeenDays: Number(row.lastSeenDays || 0),
      productAreaDistribution,
      productAreaAdoption: row.productAreaAdoption || []
    };
  }

  function companyRows() {
    const source = fallbackCompanyRows();
    const rows = source.map(normalizeCompany).filter((company) => company.id);

    return rows;
  }

  function getCompaniesDemoData(periodValue) {
    navigateToPeriod(periodValue);

    return {
      period: DEFAULT_PERIOD,
      productAreas: productAreaNames(),
      productAreaOptions: (bundle.productAreas || []).map((area) => ({
        name: typeof area === "string" ? area : area.name,
        shortName: typeof area === "string" ? area : area.shortName || area.short_name || area.name,
        color: typeof area === "string" ? "" : area.color || ""
      })),
      companies: companyRows()
    };
  }

  function getCompanyDetailsData(companyId, periodValue) {
    if (navigateToPeriod(periodValue)) {
      return null;
    }

    if (!payload?.company) {
      return null;
    }

    const requestedId = String(companyId || "");

    if (requestedId && requestedId !== String(payload.company.id || "")) {
      return null;
    }

    return payload;
  }

  function companyDetailHref(company, periodValue) {
    const companyId = typeof company === "string" ? company : company?.id || company?.companyId || "";
    const params = new URLSearchParams();
    const baseUrl = body?.dataset.companyDetailBaseUrl || bundle.urls?.companyDetailBaseUrl || "detail.html";

    params.set("company_id", companyId);
    params.set("period", coercePeriodKey(periodValue || payload?.period?.key || DEFAULT_PERIOD));

    return appendParams(baseUrl, params);
  }

  function userDetailHref(user, periodValue) {
    const userId = typeof user === "string" ? user : user?.id || user?.userId || user?.user_id || "";
    const params = new URLSearchParams();
    const baseUrl = body?.dataset.userDetailBaseUrl || bundle.urls?.userDetailBaseUrl || "../users/detail.html";

    params.set("user_id", userId);
    params.set("period", coercePeriodKey(periodValue || payload?.period?.key || DEFAULT_PERIOD));

    return appendParams(baseUrl, params);
  }

  function companiesOverviewHref(periodValue) {
    const params = new URLSearchParams();
    const baseUrl = body?.dataset.companiesOverviewUrl || bundle.urls?.companiesOverviewUrl || "index.html";

    params.set("period", coercePeriodKey(periodValue || DEFAULT_PERIOD));

    return appendParams(baseUrl, params);
  }

  function pageDetailHref(pageRuleId, periodValue) {
    const baseUrl = body?.dataset.pagesDetailBaseUrl || bundle.urls?.pagesDetailBaseUrl || "../Pages/";
    const params = new URLSearchParams();

    params.set("period", periodDigits(periodValue || payload?.period?.key || DEFAULT_PERIOD));

    if (String(baseUrl).endsWith("/")) {
      return `${baseUrl}${encodeURIComponent(pageRuleId)}/?${params.toString()}`;
    }

    params.set("page_rule_id", pageRuleId);
    return appendParams(baseUrl, params);
  }

  function searchCompanies(query = "", options = {}) {
    const baseUrl = body?.dataset.companyOptionsUrl || bundle.urls?.companyOptionsUrl || "";

    if (!baseUrl || !globalScope.fetch) {
      return Promise.resolve([]);
    }

    return globalScope.fetch(optionsUrl(baseUrl, query, options.period || options.periodValue, options.limit || 20), {
      credentials: "same-origin",
      headers: {
        Accept: "application/json"
      }
    })
      .then((response) => {
        if (!response.ok) {
          return null;
        }

        return response.json();
      })
      .then((data) => (Array.isArray(data?.companies) ? data.companies : Array.isArray(data?.results) ? data.results : []))
      .then((rows) => rows.map(normalizeCompany).filter((company) => company.id))
      .catch(() => []);
  }

  function loadCompanyDetailTable(table, options = {}) {
    return fetchTable(body?.dataset.companyDetailTableUrl || "", { ...options, table });
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function fallbackProductAreaShortLabel(areaName) {
    const words = String(areaName || "").trim().split(/\s+/).filter(Boolean);

    if (words.length > 1) {
      return words.map((word) => word[0]).join("").slice(0, 6).toUpperCase();
    }

    const label = words[0] || "";
    return label.length > 7 ? `${label.slice(0, 6)}.` : label;
  }

  function syncProductAreaMatrixHeadings() {
    const areas = bundle.productAreas || productAreaNames();
    const normalizedAreas = areas.map((area, index) => ({
      name: typeof area === "string" ? area : area.name,
      shortName: typeof area === "string" ? fallbackProductAreaShortLabel(area) : area.shortName || area.short_name || fallbackProductAreaShortLabel(area.name),
      originalIndex: index
    })).filter((area) => area.name);
    const orderedAreas = normalizedAreas.sort((a, b) => {
      const aSecondary = secondaryAreaNamePattern.test(a.name) ? 1 : 0;
      const bSecondary = secondaryAreaNamePattern.test(b.name) ? 1 : 0;

      return aSecondary - bSecondary ||
        a.originalIndex - b.originalIndex ||
        String(a.name).localeCompare(String(b.name));
    });
    const areaCount = Math.max(orderedAreas.length, 1);
    const matrixWidthRem = areaCount * 2.5 + Math.max(areaCount - 1, 0) * 0.25;
    const areaUsageWidthRem = Math.max(10, matrixWidthRem + 1.75);

    document.documentElement.style.setProperty("--companies-product-area-count", String(areaCount));
    document.documentElement.style.setProperty("--company-users-area-matrix-width", `${matrixWidthRem.toFixed(2)}rem`);
    document.documentElement.style.setProperty("--company-users-area-usage-width", `${areaUsageWidthRem.toFixed(2)}rem`);
    document.querySelectorAll(".companies-matrix-heading").forEach((heading, headingIndex) => {
      heading.innerHTML = orderedAreas.map((area, areaIndex) => {
        const tooltipId = `company-detail-area-heading-${headingIndex}-${areaIndex}`;
        return `
          <span class="metric-header-tooltip" tabindex="0" aria-describedby="${tooltipId}">
            ${escapeHtml(area.shortName)}
            <span id="${tooltipId}" class="metric-header-tooltip__content" role="tooltip">${escapeHtml(area.name)}</span>
          </span>
        `;
      }).join("");
    });
  }

  globalScope.HymetryCompaniesDemoData = {
    PERIOD_OPTIONS,
    DEFAULT_PERIOD,
    productAreas: productAreaNames(),
    productAreaOptions: bundle.productAreas || [],
    getCompaniesDemoData,
    getCompanyDetailsData,
    companyDetailHref,
    userDetailHref,
    companiesOverviewHref,
    pageDetailHref,
    searchCompanies,
    loadCompanyDetailTable,
    coercePeriodKey,
    isPeriodNavigationPending,
    isPayloadPending
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", syncProductAreaMatrixHeadings, { once: true });
  } else {
    syncProductAreaMatrixHeadings();
  }
})(window);
