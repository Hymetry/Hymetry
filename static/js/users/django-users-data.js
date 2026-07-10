(function mountDjangoUsersData(globalScope) {
  const dataElement = document.getElementById("users-overview-data");
  const dataUrl = document.body?.dataset.usersDataUrl || "";
  const body = document.body || {};
  let payload = {};
  let deferredPayloadPromise = null;

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

  function optionsUrl(baseUrl, query, periodValue, limit = 20) {
    const nextUrl = new URL(baseUrl, globalScope.location.origin);
    const period = coercePeriodKey(periodValue || DEFAULT_PERIOD);
    const range = rangeByPeriod[period] || rangeByPeriod[DEFAULT_PERIOD] || "last_30_days";

    nextUrl.searchParams.set("range", range);
    nextUrl.searchParams.set("limit", String(limit));

    if (String(query || "").trim()) {
      nextUrl.searchParams.set("q", String(query || "").trim());
    } else {
      nextUrl.searchParams.delete("q");
    }

    return `${nextUrl.pathname}${nextUrl.search}`;
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

    (payload.users || []).forEach((user) => {
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
      secondary: kpi.secondary || "",
      sparkline: Array.isArray(kpi.sparkline) ? kpi.sparkline : [],
      sparklineLabels: payload.dailyActiveTrend?.labels || []
    }));
  }

  function buildData(periodValue) {
    const requestedPeriod = coercePeriodKey(periodValue);
    navigateToPeriod(requestedPeriod);

    const users = Array.isArray(payload.users) ? payload.users : [];
    const scatter = Array.isArray(payload.scatter) && payload.scatter.length ? payload.scatter : users;

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
      statusMixByDate: payload.statusMixByDate || [],
      insights: payload.insights || [],
      users,
      scatter,
      scatterMeta: payload.scatterMeta || {},
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

  function payloadNeedsDeferredUsers() {
    return Boolean(payload.usersDeferred?.isPartial && dataUrl && globalScope.fetch);
  }

  function applyDeferredUsersPayload(deferredPayload) {
    if (!deferredPayload || deferredPayload.pending) {
      return null;
    }

    payload = {
      ...payload,
      users: Array.isArray(deferredPayload.users) ? deferredPayload.users : payload.users,
      scatter: Array.isArray(deferredPayload.scatter) ? deferredPayload.scatter : payload.scatter,
      scatterMeta: deferredPayload.scatterMeta || payload.scatterMeta || {},
      usersDeferred: {
        ...(payload.usersDeferred || {}),
        ...(deferredPayload.usersDeferred || {}),
        isPartial: false
      }
    };

    return buildData(DEFAULT_PERIOD);
  }

  function loadDeferredUsersData() {
    if (!payloadNeedsDeferredUsers()) {
      return Promise.resolve(null);
    }

    if (deferredPayloadPromise) {
      return deferredPayloadPromise;
    }

    deferredPayloadPromise = globalScope.fetch(dataUrl, {
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
      .then(applyDeferredUsersPayload)
      .catch(() => null);

    return deferredPayloadPromise;
  }

  function searchUsers(query = "", options = {}) {
    const baseUrl = body.dataset?.userOptionsUrl || "";

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
    loadDeferredUsersData,
    searchUsers,
    coercePeriodKey
  };
})(window);
