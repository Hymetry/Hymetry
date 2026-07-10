(function registerDjangoPagesData(globalScope) {
  const payloadElement = document.getElementById("pages-overview-data");
  const overviewPayload = payloadElement ? JSON.parse(payloadElement.textContent || "null") : null;
  const detailPayloadElement = document.getElementById("pages-detail-data");
  const detailPayload = detailPayloadElement ? JSON.parse(detailPayloadElement.textContent || "null") : null;
  const body = document.body || {};
  const detailPageSelectorRows = detailPayload?.page_selector_rows || detailPayload?.pageSelectorRows || [];

  function tableRequestUrl(baseUrl, params = {}) {
    const nextUrl = new URL(baseUrl, globalScope.location.origin);
    const currentParams = new URLSearchParams(globalScope.location.search);

    if (body.dataset?.pagesRangeKey) {
      nextUrl.searchParams.set("range", body.dataset.pagesRangeKey);
    }

    currentParams.getAll("product_area").forEach((value) => {
      nextUrl.searchParams.append("product_area", value);
    });

    Object.entries(params).forEach(([key, value]) => {
      if (value === undefined || value === null || value === "") {
        return;
      }
      nextUrl.searchParams.set(key, String(value));
    });

    return `${nextUrl.pathname}${nextUrl.search}`;
  }

  function fetchTable(baseUrl, params = {}) {
    if (!baseUrl || !globalScope.fetch) {
      return Promise.resolve(null);
    }

    return globalScope.fetch(tableRequestUrl(baseUrl, params), {
      credentials: "same-origin",
      headers: { Accept: "application/json" }
    })
      .then((response) => (response.ok ? response.json() : null))
      .catch(() => null);
  }

  globalScope.HymetryPagesAnalyticsData = {
    getMockPagesOverviewData() {
      if (overviewPayload) {
        return overviewPayload;
      }

      if (detailPageSelectorRows.length) {
        return {
          rows: detailPageSelectorRows,
          change_aware_rows: detailPageSelectorRows
        };
      }

      return {};
    },

    getMockPageDetailsData(projectId, pageRuleId, days) {
      if (!detailPayload) {
        return null;
      }

      const periodPayloads = detailPayload.period_payloads || {};
      const numericDays = Number(days);

      if (Number.isFinite(numericDays) && numericDays > 0) {
        const requestedDays = String(numericDays);
        const selectedPayload = detailPayload.payload || null;
        const selectedPayloadDays = String(selectedPayload?.period?.days || "");

        return periodPayloads[requestedDays] || (selectedPayloadDays === requestedDays ? selectedPayload : null);
      }

      const selectedDays = String(detailPayload.selected_period_days || "");
      return periodPayloads[selectedDays] || detailPayload.payload || null;
    },

    loadPagesOverviewTable(options = {}) {
      return fetchTable(body.dataset?.pagesOverviewTableUrl || "", options);
    },

    loadPageDetailTable(table, options = {}) {
      return fetchTable(body.dataset?.pageDetailTableUrl || "", { ...options, table });
    }
  };
})(window);
