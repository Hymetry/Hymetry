(function mountDjangoCompaniesData(globalScope) {
  const dataElement = document.getElementById("companies-overview-data");
  const body = document.body || {};
  let payload = {};

  try {
    payload = JSON.parse(dataElement?.textContent || "{}");
  } catch {
    payload = {};
  }

  const PERIOD_OPTIONS = [7, 30, 90, 180];
  const periodDays = Number(payload.period?.days) || 30;
  const DEFAULT_PERIOD = `${periodDays}d`;
  const rangeByPeriod = {
    "7d": "last_7_days",
    "30d": "last_30_days",
    "90d": "last_90_days",
    "180d": "last_180_days"
  };

  function coercePeriodKey(value) {
    const normalized = String(value || DEFAULT_PERIOD).trim().toLowerCase();
    const digits = normalized.replace(/[^0-9]/g, "");
    const period = `${digits || periodDays}d`;

    return PERIOD_OPTIONS.includes(Number(digits)) ? period : DEFAULT_PERIOD;
  }

  function appendCompanyAttributeParams(nextUrl) {
    const currentParams = new URLSearchParams(globalScope.location.search);
    const existingKeys = Array.from(nextUrl.searchParams.keys())
      .filter((key) => key.startsWith("ca."));

    existingKeys.forEach((key) => nextUrl.searchParams.delete(key));
    currentParams.forEach((value, key) => {
      if (key.startsWith("ca.")) {
        nextUrl.searchParams.append(key, value);
      }
    });
    return nextUrl;
  }

  function navigateToPeriod(period) {
    const range = rangeByPeriod[period];

    if (!range || period === DEFAULT_PERIOD) {
      return;
    }

    const params = new URLSearchParams(globalScope.location.search);
    params.delete("period");
    params.set("range", range);
    globalScope.location.assign(`${globalScope.location.pathname}?${params.toString()}`);
  }

  function optionsUrl(baseUrl, query, periodValue, limit = 20, alphabetical = false) {
    const nextUrl = new URL(baseUrl, globalScope.location.origin);

    nextUrl.searchParams.set("period", coercePeriodKey(periodValue || DEFAULT_PERIOD));
    nextUrl.searchParams.set("limit", String(limit));
    if (alphabetical) {
      nextUrl.searchParams.set("sort", "alphabetical");
    } else {
      nextUrl.searchParams.delete("sort");
    }

    if (String(query || "").trim()) {
      nextUrl.searchParams.set("q", String(query || "").trim());
    } else {
      nextUrl.searchParams.delete("q");
    }

    appendCompanyAttributeParams(nextUrl);
    return `${nextUrl.pathname}${nextUrl.search}`;
  }

  function tableRequestUrl(baseUrl, options = {}) {
    const nextUrl = new URL(baseUrl, globalScope.location.origin);

    nextUrl.searchParams.set("period", coercePeriodKey(options.period || options.periodValue || DEFAULT_PERIOD));

    Object.entries(options).forEach(([key, value]) => {
      if (key === "period" || key === "periodValue" || value === undefined || value === null || value === "") {
        return;
      }
      nextUrl.searchParams.set(key, String(value));
    });

    appendCompanyAttributeParams(nextUrl);
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

  function formatRelativeDate(value) {
    if (!value || !payload.period?.end_date) {
      return "-";
    }

    const endDate = new Date(`${payload.period.end_date}T00:00:00Z`);
    const date = new Date(`${value}T00:00:00Z`);
    const days = Math.max(0, Math.round((endDate - date) / 86400000));

    if (days <= 0) {
      return "Today";
    }

    return `${days}d ago`;
  }

  function daysSince(value) {
    if (!value || !payload.period?.end_date) {
      return 0;
    }

    const endDate = new Date(`${payload.period.end_date}T00:00:00Z`);
    const date = new Date(`${value}T00:00:00Z`);
    return Math.max(0, Math.round((endDate - date) / 86400000));
  }

  function fallbackProductAreaShortLabel(areaName) {
    const labelText = String(areaName || "").trim();
    const words = labelText.split(/\s+/).filter(Boolean);
    if (words.length > 1) {
      return words.map((word) => word[0]).join("").slice(0, 6).toUpperCase();
    }

    const label = words[0] || "";
    return label.length > 7 ? `${label.slice(0, 6)}.` : label;
  }

  function normalizeProductAreaShortLabel(areaName, shortName = "") {
    const normalizedName = String(areaName || "").trim();
    const normalizedShortName = String(shortName || "").trim();

    if (!normalizedShortName || normalizedShortName === normalizedName || normalizedShortName.length > 8) {
      return fallbackProductAreaShortLabel(normalizedShortName || normalizedName);
    }

    return normalizedShortName;
  }

  function productAreaOptions() {
    const options = [];
    const add = (name, shortName = "", color = "") => {
      const normalizedName = String(name || "").trim();

      if (!normalizedName || options.some((option) => option.name === normalizedName)) {
        return;
      }

      options.push({
        name: normalizedName,
        shortName: normalizeProductAreaShortLabel(normalizedName, shortName),
        color: String(color || "").trim()
      });
    };

    (payload.productAreas || []).forEach((area) => {
      if (area && typeof area === "object") {
        add(area.name, area.shortName || area.short_name, area.color);
        return;
      }

      add(area);
    });

    const fromCompanies = (payload.companies || []).flatMap((company) => company.productAreas || []);
    fromCompanies.forEach((areaName) => add(areaName));

    return options;
  }

  function productAreaNames() {
    return productAreaOptions().map((area) => area.name);
  }

  function formatTrendDateLabel(date) {
    if (!(date instanceof Date) || Number.isNaN(date.getTime())) {
      return "";
    }

    return new Intl.DateTimeFormat("en-US", {
      month: "short",
      day: "numeric",
      timeZone: "UTC"
    }).format(date);
  }

  function trendDateLabels(length) {
    const count = Math.max(0, Number(length) || 0);
    const endDate = new Date(`${payload.period?.end_date || ""}T00:00:00Z`);

    if (!count || Number.isNaN(endDate.getTime())) {
      return [];
    }

    const firstDate = new Date(endDate);
    firstDate.setUTCDate(firstDate.getUTCDate() - count + 1);

    return Array.from({ length: count }, (_, index) => {
      const date = new Date(firstDate);
      date.setUTCDate(firstDate.getUTCDate() + index);
      return formatTrendDateLabel(date);
    });
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function syncProductAreaMatrixHeadings() {
    const areas = productAreaOptions();
    globalScope.document.documentElement.style.setProperty("--companies-product-area-count", String(Math.max(areas.length, 1)));

    globalScope.document.querySelectorAll(".companies-matrix-heading").forEach((heading, headingIndex) => {
      heading.innerHTML = areas.map((area, areaIndex) => {
        const tooltipId = `companies-dynamic-area-tooltip-${headingIndex}-${areaIndex}`;
        return `
          <span class="metric-header-tooltip" tabindex="0" aria-describedby="${tooltipId}">
            ${escapeHtml(area.shortName)}
            <span id="${tooltipId}" class="metric-header-tooltip__content" role="tooltip">${escapeHtml(area.name)}</span>
          </span>
        `;
      }).join("");
    });
  }

  function mapAreaDistribution(row) {
    return (row.productAreaDistribution || []).map((area) => ({
      productArea: area.product_area_name || area.productArea || area.name || "Unassigned",
      percent: Number(area.percent) || 0,
      engagedSeconds: Number(area.engaged_seconds || area.engagedSeconds || 0),
      visits: Number(area.visits) || 0
    }));
  }

  function areaAdoption(row) {
    const distributions = row.productAreaDistribution || [];
    const byName = new Map(distributions.map((area) => [area.product_area_name || area.productArea, area]));
    return productAreaNames().map((areaName) => {
      const area = byName.get(areaName);
      const engagedSeconds = Number(area?.engaged_seconds || area?.engagedSeconds || 0);
      return {
        productArea: areaName,
        used: engagedSeconds > 0 || (row.productAreas || []).includes(areaName),
        engagedSeconds,
        visits: Number(area?.visits) || 0,
        // Counted per area by _company_area_usage. These are shown to the reader
        // as measurements, so they are never derived from the company totals.
        activeUsers: Number(area?.active_users ?? area?.activeUsers) || 0,
        pagesUsed: Number(area?.pages_used ?? area?.pagesUsed) || 0
      };
    });
  }

  function normalizeCompanyStatus(row) {
    const status = String(row.status || "").trim();

    if (row.isNew || status === "new") {
      return "new";
    }
    if (row.isReactivated || status === "reactivated") {
      return "reactivated";
    }

    return status;
  }

  function mapCompany(row) {
    const topArea = row.productAreas?.[0] || row.productAreaDistribution?.[0]?.product_area_name || "";
    const status = normalizeCompanyStatus(row);
    const companyId = row.companyId || row.id || "";
    const companyName = row.companyName || row.name || companyId;
    return {
      id: companyId,
      companyId,
      name: companyName,
      companyName,
      domain: row.domain || "",
      status,
      originalStatus: row.status || status,
      isNew: Boolean(row.isNew),
      isReactivated: Boolean(row.isReactivated),
      comparisonAvailable: row.comparisonAvailable !== false && row.comparison_available !== false,
      activeUsers: Number(row.activeUsers) || 0,
      averageActiveUsers: Number(row.averageActiveUsers ?? row.avgActiveUsers ?? row.activeUsers) || 0,
      activeUsersDeltaPct: Number(row.activeUsersDeltaPct) || 0,
      activeUsersDeltaLabel: row.activeUsersDeltaLabel || "",
      productAreasUsed: Number(row.productAreasUsed) || 0,
      productAreasDelta: Number(row.productAreasDelta) || 0,
      pagesUsed: Number(row.pagesUsed) || 0,
      visits: Number(row.visits) || 0,
      visitsDeltaPct: Number(row.visitsDeltaPct) || 0,
      visitsDeltaLabel: row.visitsDeltaLabel || "",
      engagedSeconds: Number(row.engagedSeconds) || 0,
      engagedDeltaPct: Number(row.engagedDeltaPct) || 0,
      engagedDeltaLabel: row.engagedDeltaLabel || "",
      avgEngagedSecondsPerUser: Number(row.avgEngagedSecondsPerUser) || 0,
      interactionPct: Number(row.interactionPct) || 0,
      interactionDeltaPp: Number(row.interactionDeltaPp) || 0,
      interactionDeltaLabel: row.interactionDeltaLabel || "",
      lastSeen: row.lastSeen || formatRelativeDate(row.lastSeenDate),
      lastSeenDays: Number(row.lastSeenDays) || daysSince(row.lastSeenDate),
      firstSeenDate: row.firstSeenDate,
      topProductArea: topArea,
      productAreas: row.productAreas || [],
      productAreaDistribution: mapAreaDistribution(row),
      userHealthMix: row.userHealthMix || row.user_health_mix || {},
      productAreaAdoption: areaAdoption(row)
    };
  }

  function expansionText(row) {
    // _expansion_reason_and_action pairs these on the server and always fills
    // both, so the browser renders what was stored rather than keeping a second
    // copy of the scoring rules that would have to track every change to it.
    return {
      reason: String(row.reason || "").trim() || "Strong usage footprint",
      suggestedAction: String(row.suggestedAction || "").trim() || "Validate expansion fit"
    };
  }

  function atRiskSuggestedAction(row) {
    // The server computes this in _suggested_action and never stores it empty,
    // so the stored wording is what the cell shows and what the at-risk table
    // sorts on. The default only guards a malformed row, and matches the
    // server's own final fallback.
    return String(row.suggestedAction || "").trim() || "Review account health";
  }

  function mapAtRiskCompany(row) {
    const company = mapCompany(row);

    return {
      ...company,
      companyId: row.companyId,
      companyName: row.companyName,
      riskReason: row.riskReason || row.riskReasons?.[0] || "At risk",
      riskScore: Number(row.riskScore) || 0,
      suggestedAction: atRiskSuggestedAction(row),
      productAreaAdoption: areaAdoption(row)
    };
  }

  function atRiskCompanyRows(rows) {
    return (rows || [])
      .filter((row) => !row.isNew && !row.isReactivated && row.status !== "new" && row.status !== "reactivated")
      .map(mapAtRiskCompany);
  }

  function normalizedHealthDistribution(rows, companies) {
    const labels = {
      new: "New",
      activated: "Activated",
      reactivated: "Reactivated",
      healthy: "Healthy",
      power: "Power",
      at_risk: "Risk",
      dormant: "Dormant"
    };
    const order = ["new", "activated", "reactivated", "healthy", "power", "at_risk", "dormant"];
    const counts = new Map((rows || []).map((row) => [row.status, Number(row.count) || 0]));

    if (!(rows || []).length) {
      companies.forEach((company) => {
        counts.set(company.status, (counts.get(company.status) || 0) + 1);
      });
    } else {
      companies.forEach((company) => {
        if (!company.originalStatus || company.originalStatus === company.status) {
          return;
        }

        counts.set(company.originalStatus, Math.max(0, (counts.get(company.originalStatus) || 0) - 1));
        counts.set(company.status, (counts.get(company.status) || 0) + 1);
      });
    }

    const total = order.reduce((sum, status) => sum + (counts.get(status) || 0), 0) || 1;
    return order
      .map((status) => ({
        status,
        label: labels[status] || status,
        count: counts.get(status) || 0,
        pct: Math.round(((counts.get(status) || 0) / total) * 1000) / 10
      }))
      .filter((row) => row.count > 0);
  }

  function mapNewReactivatedCompany(row) {
    const company = mapCompany(row);

    return {
      ...company,
      companyId: row.companyId,
      companyName: row.companyName,
      // _activation_stage and the elapsed-day count are computed server-side, so
      // the table can be ordered and paged there like every other one.
      activationStage: row.activationStage || "not_activated",
      daysSinceStart: Number(row.daysSinceStart) || 1
    };
  }

  function newReactivatedRows(rows) {
    return (rows || []).map(mapNewReactivatedCompany);
  }

  function mapExpansionCompany(row) {
    const company = mapCompany(row);
    const recommendation = expansionText(row);

    return {
      ...company,
      companyId: row.companyId,
      companyName: row.companyName,
      expansionPriority: row.expansionPriority || "medium",
      potentialScore: Number(row.potentialScore) || 0,
      reason: recommendation.reason,
      suggestedAction: recommendation.suggestedAction
    };
  }

  function expansionCompanyRows(rows) {
    return (rows || []).map(mapExpansionCompany);
  }

  function buildAdoptionRamp(newRows) {
    if (!newRows.length) {
      return [];
    }

    const areas = productAreaNames().slice(0, 5);
    const offsets = [0, 1, 3, 7, 14, 30, 60, 90].filter((offset) => offset <= periodDays);
    const cohortSize = newRows.length;

    return offsets.flatMap((dayOffset, dayIndex) => {
      const progress = Math.min(1, (dayIndex + 1) / Math.max(offsets.length, 1));
      return areas.map((area) => {
        const adopters = newRows.filter((row) => row.productAreaAdoption?.some((cell) => cell.productArea === area && cell.used)).length;
        const targetPct = Math.round((adopters / Math.max(cohortSize, 1)) * 100);
        const adoptionPct = Math.round(targetPct * progress);
        return {
          dayOffset,
          productArea: area,
          adoptionPct,
          companiesAdopted: Math.round((adoptionPct / 100) * cohortSize),
          cohortSize
        };
      });
    });
  }

  function mapKpis() {
    const byLabel = new Map((payload.kpis || []).map((kpi) => [kpi.label, kpi]));
    const active = byLabel.get("Avg daily active companies") || byLabel.get("Active companies") || {};
    const newReactivated = byLabel.get("Avg daily new / reactivated") || byLabel.get("New / reactivated") || {};
    const median = byLabel.get("Avg daily adoption breadth") || byLabel.get("Median adoption breadth") || {};
    const atRisk = byLabel.get("At-risk companies") || {};
    const activeTrend = active.trend || [];
    const newReactivatedTrend = newReactivated.trend || [];
    const medianTrend = median.trend || [];
    const atRiskTrend = atRisk.trend || [];

    return {
      activeCompanies: {
        label: active.label || "Avg daily active companies",
        value: String(active.value ?? 0),
        secondary: "",
        delta: active.delta?.label || "",
        deltaType: active.delta?.direction || "neutral",
        sparkline: activeTrend,
        sparklineLabels: active.trend_labels || trendDateLabels(activeTrend.length),
        sparklineScope: active.trend_scope || (active.trend_grain === "day" ? "daily" : "period_to_date"),
        sparklineLabel: active.trend_label || "Daily active companies"
      },
      newReactivatedCompanies: {
        label: newReactivated.label || "Avg daily new / reactivated",
        value: String(newReactivated.value ?? 0),
        secondary: newReactivated.secondary || newReactivated.delta?.label || "",
        delta: newReactivated.delta?.label || "",
        deltaType: newReactivated.delta?.direction || "neutral",
        sparkline: newReactivatedTrend,
        sparklineLabels: newReactivated.trend_labels || trendDateLabels(newReactivatedTrend.length),
        sparklineScope: newReactivated.trend_scope || (newReactivated.trend_grain === "day" ? "daily" : "period_to_date"),
        // Each date stands on its own here, so columns rather than a line that
        // implies companies activated somewhere between two dates.
        sparklineRender: "columns",
        sparklineLabel: newReactivated.trend_label || "Daily new / reactivated"
      },
      medianAdoptionBreadth: {
        label: median.label || "Avg daily adoption breadth",
        value: `${median.value ?? 0} areas`,
        secondary: "",
        delta: median.delta?.label || "",
        deltaType: median.delta?.direction || "neutral",
        sparkline: medianTrend,
        sparklineLabels: median.trend_labels || trendDateLabels(medianTrend.length),
        sparklineValueType: "areas",
        sparklineScope: median.trend_scope || (median.trend_grain === "day" ? "daily" : "period_to_date"),
        sparklineLabel: median.trend_label || "Daily adoption breadth"
      },
      atRiskCompanies: {
        label: "At-risk companies",
        value: String(atRisk.value ?? 0),
        secondary: "",
        delta: atRisk.delta?.label || "",
        deltaType: atRisk.delta?.direction || "neutral",
        sparkline: atRiskTrend,
        sparklineLabels: atRisk.trend_labels || trendDateLabels(atRiskTrend.length),
        sparklineScope: atRisk.trend_scope || "as_of",
        // An end-of-day cohort size holds until the next date reclassifies it,
        // so the line steps rather than sloping between counts.
        sparklineRender: "step",
        sparklineLabel: atRisk.trend_label || "At-risk companies"
      }
    };
  }

  function buildData(periodValue) {
    const requestedPeriod = coercePeriodKey(periodValue);
    navigateToPeriod(requestedPeriod);

    const companies = (payload.companies || []).map(mapCompany);
    const scatterPayload = payload.scatter || {};
    const scatterFallback = (scatterPayload.points || []).map(mapCompany);
    const scatterSource = scatterFallback.length ? scatterFallback : companies;
    const newRows = newReactivatedRows(payload.newReactivatedCompanies);
    const atRiskRows = atRiskCompanyRows(payload.atRiskCompanies);
    const expansionRows = expansionCompanyRows(payload.expansionOpportunities);

    return {
      period: DEFAULT_PERIOD,
      productAreas: productAreaNames(),
      productAreaOptions: productAreaOptions(),
      pageFeatures: [],
      kpis: mapKpis(),
      healthDistribution: normalizedHealthDistribution(payload.healthDistribution || [], companies),
      companies,
      tableData: payload.tableData || {},
      scatter: scatterSource,
      scatterMeta: {
        visibleLimit: Number(scatterPayload.visibleLimit) || 500,
        totalActiveCompanies: Number(scatterPayload.totalActiveCompanies) || scatterSource.length,
        shownCompanies: Number(scatterPayload.shownCompanies) || scatterFallback.length || scatterSource.length,
        isLimited: Boolean(scatterPayload.isLimited),
        futureDensityMode: scatterPayload.futureDensityMode || null
      },
      newReactivatedCompanies: newRows,
      productAreaAdoption: payload.productAreaAdoption || [],
      newCompanyAdoptionRamp: payload.newCompanyAdoptionRamp?.length ? payload.newCompanyAdoptionRamp : buildAdoptionRamp(newRows),
      heatmap: [],
      atRiskCompanies: atRiskRows,
      expansionOpportunities: expansionRows
    };
  }

  function searchCompanies(query = "", options = {}) {
    const baseUrl = body.dataset?.companyOptionsUrl || "";

    if (!baseUrl || !globalScope.fetch) {
      return Promise.resolve([]);
    }

    return globalScope.fetch(optionsUrl(baseUrl, query, options.period || options.periodValue, options.limit || 20, options.alphabetical), {
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
      .then((rows) => rows.map(mapCompany).filter((company) => company.id))
      .catch(() => []);
  }

  function loadOverviewTable(table, options, mapRows) {
    return fetchTable(body.dataset?.companiesTableUrl || "", { ...options, table })
      .then((data) => {
        if (!data || !Array.isArray(data.rows)) {
          return null;
        }

        return { ...data, rows: mapRows(data.rows) };
      });
  }

  function loadCompaniesTable(options = {}) {
    return fetchTable(body.dataset?.companiesTableUrl || "", options)
      .then((data) => {
        if (!data || !Array.isArray(data.rows)) {
          return null;
        }

        return {
          ...data,
          rows: data.rows.map(mapCompany).filter((company) => company.id)
        };
      });
  }

  function loadAtRiskTable(options = {}) {
    return loadOverviewTable("atRisk", options, atRiskCompanyRows);
  }

  function loadNewReactivatedTable(options = {}) {
    return loadOverviewTable("newReactivated", options, newReactivatedRows);
  }

  function loadExpansionTable(options = {}) {
    return loadOverviewTable("expansion", options, expansionCompanyRows);
  }

  globalScope.HymetryCompaniesDemoData = {
    PERIOD_OPTIONS,
    DEFAULT_PERIOD,
    productAreas: productAreaNames(),
    productAreaOptions: productAreaOptions(),
    pageFeatures: [],
    getCompaniesDemoData: buildData,
    searchCompanies,
    loadCompaniesTable,
    loadAtRiskTable,
    loadNewReactivatedTable,
    loadExpansionTable,
    coercePeriodKey
  };

  if (globalScope.document.readyState === "loading") {
    globalScope.document.addEventListener("DOMContentLoaded", syncProductAreaMatrixHeadings, { once: true });
  } else {
    syncProductAreaMatrixHeadings();
  }
})(window);
