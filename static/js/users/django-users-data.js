(function mountDjangoUsersData(globalScope) {
  const dataElement = document.getElementById("users-overview-data");
  const body = document.body || {};
  let payload = {};

  try {
    payload = JSON.parse(dataElement?.textContent || "{}");
  } catch {
    payload = {};
  }

  const embeddedUsers = Array.isArray(payload.users) ? payload.users : [];
  const stableScatter = (Array.isArray(payload.scatter) && payload.scatter.length ? payload.scatter : embeddedUsers)
    .slice(0, 300);

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
    params.delete("days");
    params.set("range", range);
    globalScope.location.assign(`${globalScope.location.pathname}?${params.toString()}`);
  }

  function optionsUrl(baseUrl, query, periodValue, limit = 20, alphabetical = false) {
    const nextUrl = new URL(baseUrl, globalScope.location.origin);
    const period = coercePeriodKey(periodValue || DEFAULT_PERIOD);
    const range = rangeByPeriod[period] || rangeByPeriod[DEFAULT_PERIOD] || "last_30_days";

    nextUrl.searchParams.set("range", range);
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
    const period = coercePeriodKey(options.period || options.periodValue || DEFAULT_PERIOD);
    const range = body.dataset?.usersRangeKey || rangeByPeriod[period] || rangeByPeriod[DEFAULT_PERIOD];

    if (range) {
      nextUrl.searchParams.set("range", range);
    }

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

  function normalizeProductAreaOption(area) {
    if (!area || typeof area !== "object") {
      return {
        key: String(area || ""),
        name: String(area || ""),
        shortName: String(area || "").slice(0, 8),
        color: ""
      };
    }

    return {
      key: String(area.key || area.product_area_key || area.name || ""),
      name: String(area.name || area.productAreaName || area.product_area_name || "Unassigned"),
      shortName: String(area.shortName || area.short_name || area.name || "Area").slice(0, 8),
      color: String(area.color || "")
    };
  }

  function productAreaOptions() {
    const options = [];
    const seen = new Set();

    (payload.productAreas || []).forEach((area) => {
      const option = normalizeProductAreaOption(area);

      if (!option.name || seen.has(option.name)) {
        return;
      }

      seen.add(option.name);
      options.push(option);
    });

    embeddedUsers.concat(stableScatter).forEach((user) => {
      (user.pageGroups || []).forEach((group) => {
        const name = String(group.name || group.productArea || "").trim();

        if (!name || seen.has(name)) {
          return;
        }

        seen.add(name);
        options.push({ key: name, name, shortName: name.slice(0, 8), color: "" });
      });
    });

    return options.slice(0, 9);
  }

  function productAreaNames() {
    return productAreaOptions().map((area) => area.name);
  }

  function mapKpis() {
    return (payload.kpis || []).map((kpi) => ({
      key: kpi.key,
      label: kpi.label,
      value: kpi.value,
      delta: Number(kpi.delta) || 0,
      deltaLabel: kpi.deltaLabel || kpi.delta?.label || "",
      deltaType: kpi.deltaType || kpi.delta?.direction || "neutral",
      sparkline: Array.isArray(kpi.sparkline) ? kpi.sparkline : [],
      sparklineLabels: payload.dailyActiveTrend?.labels || [],
      sparklineScope: kpi.sparklineScope || "period_to_date",
      sparklineValueType: kpi.sparklineValueType || "",
      sparklineRender: kpi.sparklineRender || "area",
      sparklineLabel: kpi.sparklineLabel || kpi.label || "Value"
    }));
  }

  function buildData(periodValue) {
    const requestedPeriod = coercePeriodKey(periodValue);
    navigateToPeriod(requestedPeriod);

    const users = embeddedUsers;

    return {
      period: DEFAULT_PERIOD,
      periodOptions: PERIOD_OPTIONS,
      pageGroups: productAreaNames(),
      productAreas: productAreaNames(),
      productAreaOptions: productAreaOptions(),
      featureColumns: (payload.pageFeatures || []).map((feature) => feature.label || feature.value || feature),
      pageFeatures: payload.pageFeatures || [],
      featureProductAreas: payload.featureProductAreas || {},
      kpis: mapKpis(),
      dailyActiveTrend: payload.dailyActiveTrend || { labels: [] },
      engagementBuckets: payload.engagementBuckets || [],
      statusDistribution: payload.statusDistribution || [],
      previousStatusDistribution: payload.previousStatusDistribution || [],
      insights: payload.insights || [],
      users,
      scatter: stableScatter,
      scatterMeta: payload.scatterMeta || {},
      tableData: payload.tableData || {},
      tableFilters: payload.tableFilters || payload.filters || {},
      featureHeatmap: payload.featureHeatmap || [],
      topUsers: users.slice().sort((a, b) => (Number(b.engagedSeconds) || 0) - (Number(a.engagedSeconds) || 0)).slice(0, 10),
      usersNeedingAttention: payload.usersNeedingAttention || [],
      usersGainingMomentum: payload.usersGainingMomentum || [],
      usersByCompany: payload.usersByCompany || [],
      emptyState: payload.emptyState || {
        title: "No users found",
        text: "Try changing filters or date range."
      }
    };
  }

  function loadUsersTable(options = {}) {
    return fetchTable(body.dataset?.usersTableUrl || "", options)
      .then((data) => (data && Array.isArray(data.rows) ? data : null));
  }

  function searchUsers(query = "", options = {}) {
    const baseUrl = body.dataset?.userOptionsUrl || "";

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
      .then((data) => (Array.isArray(data?.users) ? data.users : Array.isArray(data?.results) ? data.results : []))
      .catch(() => []);
  }

  globalScope.HymetryUsersDemoData = {
    PERIOD_OPTIONS,
    DEFAULT_PERIOD,
    productAreas: productAreaNames(),
    productAreaOptions: productAreaOptions(),
    featureProductAreas: payload.featureProductAreas || {},
    pageFeatures: payload.pageFeatures || [],
    getUsersAnalyticsData: buildData,
    loadUsersTable,
    searchUsers,
    coercePeriodKey
  };
})(window);
