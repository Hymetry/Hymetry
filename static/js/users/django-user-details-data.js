(function mountDjangoUserDetailsData(globalScope) {
  const dataElement = document.getElementById("user-details-data");
  let payload = {};

  try {
    payload = JSON.parse(dataElement?.textContent || "{}");
  } catch {
    payload = {};
  }

  const periodByRange = {
    last_7_days: 7,
    last_30_days: 30,
    last_90_days: 90,
    last_180_days: 180
  };
  const rangeByPeriod = {
    7: "last_7_days",
    30: "last_30_days",
    90: "last_90_days",
    180: "last_180_days"
  };
  const periodOptions = [7, 30, 90, 180];
  const selectedUser = payload.selectedUser || {};
  const urls = payload.urls || {};
  const body = document.body || {};
  const defaultPeriodDays = Number(payload.periodDays || payload.period?.days) || 30;
  const defaultUserId = String(selectedUser.id || body.dataset?.userId || "");

  function coercePeriodDays(value) {
    const digits = Number(String(value || defaultPeriodDays).replace(/[^0-9.]/g, ""));
    return periodOptions.includes(digits) ? digits : defaultPeriodDays;
  }

  function periodDaysFromRange(rangeKey) {
    return periodByRange[String(rangeKey || "")] || "";
  }

  function replacePlaceholder(baseUrl, value) {
    const encoded = encodeURIComponent(String(value || ""));
    if (!baseUrl) {
      return encoded;
    }
    return String(baseUrl).replace(/detail(?=\/|$)/, encoded);
  }

  function withPeriod(url, periodDays) {
    const nextUrl = new URL(url, globalScope.location.origin);
    const rangeKey = rangeByPeriod[Number(periodDays) || defaultPeriodDays] || rangeByPeriod[defaultPeriodDays] || "last_30_days";
    nextUrl.searchParams.delete("period");
    nextUrl.searchParams.delete("days");
    nextUrl.searchParams.set("range", rangeKey);
    return `${nextUrl.pathname}${nextUrl.search}`;
  }

  function optionsUrl(baseUrl, query, periodDays, limit = 20, alphabetical = false) {
    const nextUrl = new URL(baseUrl, globalScope.location.origin);
    const rangeKey = rangeByPeriod[Number(periodDays) || defaultPeriodDays] || rangeByPeriod[defaultPeriodDays] || "last_30_days";

    nextUrl.searchParams.set("range", rangeKey);
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

    return `${nextUrl.pathname}${nextUrl.search}`;
  }

  function tableRequestUrl(baseUrl, options = {}) {
    const nextUrl = new URL(baseUrl, globalScope.location.origin);
    const requestedPeriodDays = coercePeriodDays(options.periodDays || options.period || defaultPeriodDays);
    const rangeKey = rangeByPeriod[requestedPeriodDays] || rangeByPeriod[defaultPeriodDays] || "last_30_days";

    nextUrl.searchParams.set("range", rangeKey);

    Object.entries(options).forEach(([key, value]) => {
      if (key === "period" || key === "periodDays" || value === undefined || value === null || value === "") {
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

  function userDetailHref(userId, periodDays) {
    return withPeriod(replacePlaceholder(urls.userDetailBaseUrl || body.dataset?.userDetailBaseUrl || globalScope.location.pathname, userId), periodDays);
  }

  function companyDetailHref(companyId, periodDays) {
    return withPeriod(replacePlaceholder(urls.companyDetailBaseUrl || "", companyId), periodDays);
  }

  function pageDetailHref(pageRuleId, periodDays) {
    return withPeriod(replacePlaceholder(urls.pageDetailBaseUrl || "", pageRuleId), periodDays);
  }

  function navigateToDetail(userId, periodDays) {
    const target = userDetailHref(userId, periodDays);
    const current = `${globalScope.location.pathname}${globalScope.location.search}`;
    if (target === current) {
      globalScope.location.reload();
      return;
    }
    globalScope.location.assign(target);
  }

  function getUserDetailsData(options = {}) {
    const requestedUserId = String(options.userId || defaultUserId);
    const requestedPeriodDays = coercePeriodDays(options.periodDays);
    const selectedId = String(payload.selectedUser?.id || defaultUserId);
    const selectedPeriodDays = Number(payload.periodDays || payload.period?.days || defaultPeriodDays);

    if (requestedUserId && selectedId && requestedUserId !== selectedId) {
      navigateToDetail(requestedUserId, requestedPeriodDays);
      return payload;
    }

    if (requestedPeriodDays !== selectedPeriodDays) {
      navigateToDetail(selectedId, requestedPeriodDays);
      return payload;
    }

    return payload;
  }

  function searchUsers(query = "", options = {}) {
    const baseUrl = urls.userOptionsUrl || body.dataset?.userOptionsUrl || "";

    if (!baseUrl || !globalScope.fetch) {
      return Promise.resolve([]);
    }

    return globalScope.fetch(optionsUrl(baseUrl, query, options.periodDays, options.limit || 20, options.alphabetical), {
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

  function loadUserDetailTable(table, options = {}) {
    return fetchTable(body.dataset?.userDetailTableUrl || "", { ...options, table });
  }

  globalScope.HymetryUserDetailsData = {
    AS_OF_DATE: payload.period?.end_date || "",
    END_DATE: payload.period?.end_date || "",
    DEFAULT_USER_ID: defaultUserId,
    DEFAULT_PEER_GROUP: payload.peerGroup || "company",
    DEFAULT_PERIOD_DAYS: defaultPeriodDays,
    PERIOD_OPTIONS: periodOptions,
    PRODUCT_AREAS: payload.productAreas || [],
    periodDaysFromRange,
    userDetailHref,
    companyDetailHref,
    pageDetailHref,
    searchUsers,
    loadUserDetailTable,
    getUserDetailsData
  };
})(window);
