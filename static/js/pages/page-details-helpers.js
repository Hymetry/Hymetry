(function registerHymetryPageDetailsHelpers(root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
    return;
  }

  root.HymetryPageDetailsHelpers = factory();
})(typeof globalThis !== "undefined" ? globalThis : window, function createHymetryPageDetailsHelpers() {
  const PERIOD_OPTIONS = [7, 30, 90, 180];
  const DEFAULT_PERIOD_DAYS = 30;

  function coercePageDetailPeriod(value) {
    const numericValue = Number(value);

    return PERIOD_OPTIONS.includes(numericValue) ? numericValue : DEFAULT_PERIOD_DAYS;
  }

  function toUtcDate(value) {
    if (value instanceof Date && !Number.isNaN(value.getTime())) {
      return new Date(Date.UTC(value.getUTCFullYear(), value.getUTCMonth(), value.getUTCDate()));
    }

    const parsed = value ? new Date(value) : new Date();

    if (Number.isNaN(parsed.getTime())) {
      return new Date();
    }

    return new Date(Date.UTC(parsed.getUTCFullYear(), parsed.getUTCMonth(), parsed.getUTCDate()));
  }

  function addDays(date, days) {
    const nextDate = new Date(date.getTime());
    nextDate.setUTCDate(nextDate.getUTCDate() + days);

    return nextDate;
  }

  function formatIsoDate(date) {
    return date.toISOString().slice(0, 10);
  }

  function calculatePageDetailsPeriod(days, endDateValue) {
    const selectedDays = coercePageDetailPeriod(days);
    const currentEndDate = toUtcDate(endDateValue || "2026-05-06");
    const currentStartDate = addDays(currentEndDate, -(selectedDays - 1));
    const previousEndDate = addDays(currentStartDate, -1);
    const previousStartDate = addDays(previousEndDate, -(selectedDays - 1));

    return {
      days: selectedDays,
      currentStart: formatIsoDate(currentStartDate),
      currentEnd: formatIsoDate(currentEndDate),
      previousStart: formatIsoDate(previousStartDate),
      previousEnd: formatIsoDate(previousEndDate)
    };
  }

  function normalizeIndexedSeries(values) {
    const numericValues = Array.isArray(values) ? values.map((value) => Number(value) || 0) : [];
    const firstNonZero = numericValues.find((value) => value !== 0);

    if (!numericValues.length) {
      return [];
    }

    if (!firstNonZero) {
      return numericValues.map(() => 0);
    }

    return numericValues.map((value) => (value / firstNonZero) * 100);
  }

  function formatSignedNumber(value, suffix) {
    const rounded = Math.round(Number(value) || 0);
    const prefix = rounded > 0 ? "+" : "";

    return `${prefix}${rounded}${suffix}`;
  }

  function calculateMetricDelta(currentValue, previousValue, deltaType) {
    const current = Number(currentValue);
    const previous = Number(previousValue);

    if (!Number.isFinite(current) || !Number.isFinite(previous)) {
      return {
        value: null,
        label: "-",
        direction: "neutral"
      };
    }

    if (deltaType === "percentage_point") {
      const delta = current - previous;

      return {
        value: delta,
        label: formatSignedNumber(delta, " pp"),
        direction: delta > 0 ? "positive" : delta < 0 ? "negative" : "neutral"
      };
    }

    if (previous === 0) {
      if (current > 0) {
        return {
          value: null,
          label: "new",
          direction: "positive"
        };
      }

      return {
        value: 0,
        label: "0%",
        direction: "neutral"
      };
    }

    const delta = ((current - previous) / Math.abs(previous)) * 100;

    return {
      value: delta,
      label: formatSignedNumber(delta, "%"),
      direction: delta > 0 ? "positive" : delta < 0 ? "negative" : "neutral"
    };
  }

  function getPageArea(row) {
    return row?.productAreaName || row?.product_area_name || row?.page_group || "";
  }

  function getPageId(row) {
    return row?.pageId || row?.page_id || row?.page_rule_id || row?.id || "";
  }

  function getVisits(row) {
    return Number(row?.visits_count ?? row?.visits ?? row?.metrics?.visits ?? 0) || 0;
  }

  function sortPagesByVisitsDesc(rows) {
    return rows.slice().sort((a, b) => getVisits(b) - getVisits(a));
  }

  function selectPeerPages(rows, currentPageId, limit) {
    const peerLimit = Math.max(0, Number(limit) || 10);
    const currentId = String(currentPageId || "");
    const currentPage = rows.find((row) => String(getPageId(row)) === currentId);
    const currentArea = getPageArea(currentPage);
    const selected = [];
    const selectedIds = new Set([currentId]);
    const addPage = (page) => {
      const pageId = String(getPageId(page));

      if (!pageId || selectedIds.has(pageId) || selected.length >= peerLimit) {
        return;
      }

      selected.push(page);
      selectedIds.add(pageId);
    };

    sortPagesByVisitsDesc(rows.filter((row) => getPageArea(row) === currentArea && String(getPageId(row)) !== currentId)).forEach(addPage);
    sortPagesByVisitsDesc(rows.filter((row) => String(getPageId(row)) !== currentId)).forEach(addPage);

    return selected.slice(0, peerLimit);
  }

  function buildRelatedPages(rows, currentPageId) {
    const currentId = String(currentPageId || "");
    const currentPage = rows.find((row) => String(getPageId(row)) === currentId);
    const currentArea = getPageArea(currentPage);

    return sortPagesByVisitsDesc(rows.filter((row) => getPageArea(row) === currentArea)).map((row) => ({
      ...row,
      isCurrent: String(getPageId(row)) === currentId
    }));
  }

  function shouldShowRelatedPages(relatedPages, currentPageId) {
    const currentId = String(currentPageId || "");

    return Array.isArray(relatedPages) && relatedPages.some((row) => String(getPageId(row)) !== currentId);
  }

  return {
    PERIOD_OPTIONS,
    DEFAULT_PERIOD_DAYS,
    coercePageDetailPeriod,
    calculatePageDetailsPeriod,
    normalizeIndexedSeries,
    calculateMetricDelta,
    selectPeerPages,
    buildRelatedPages,
    shouldShowRelatedPages
  };
});
