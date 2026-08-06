(function mountHymetryUserDetail(globalScope) {
  const provider = globalScope.HymetryUserDetailsData || globalScope.HymetryUserDetailsMock;
  const helpers = globalScope.HymetryUserDetailsHelpers;
  const metricDynamicsHelpers = globalScope.HymetryMetricDynamics || {};

  if (!provider || !helpers) {
    return;
  }

  const analyticsTooltips = globalScope.HymetryAnalyticsTooltips;
  const colorFallbacks = {
    "c-blue": "#4269D0",
    "c-orange": "#EFB118",
    "c-red": "#FF725C",
    "c-teal": "#6CC5B0",
    "c-green": "#3CA951",
    "c-rose": "#FF8AB7",
    "c-purple": "#A463F2",
    "c-light-blue": "#97BBF5",
    "c-brown": "#9C6B4E",
    "slate-50": "#f8fafc",
    "slate-100": "#f1f5f9",
    "slate-200": "#e2e8f0",
    "slate-300": "#cbd5e1",
    "slate-400": "#94a3b8",
    "slate-500": "#64748b",
    "slate-600": "#475569",
    "slate-700": "#334155",
    "slate-900": "#0f172a",
    "green-700": "#15803d",
    "red-600": "#dc2626",
    white: "#ffffff"
  };

  const visitsCircleColors = [
    "#4269D0",
    "#EFB118",
    "#FF725C",
    "#6CC5B0",
    "#3CA951",
    "#FF8AB7",
    "#A463F2",
    "#97BBF5",
    "#9C6B4E",
    "#E5E7EB"
  ];

  const peerComparisonRowLimit = 10;
  const peerTraceLimit = 10;
  const peerComparisonMetrics = [
    { key: "visits", label: "Visits", valueType: "number", deltaKey: "visitsDeltaPct", deltaUnit: "%", previousKey: "previousVisits", deltaLabelKey: "visitsDeltaLabel" },
    { key: "engagedSeconds", label: "Engaged", valueType: "duration", deltaKey: "engagedDeltaPct", deltaUnit: "%", previousKey: "previousEngagedSeconds", deltaLabelKey: "engagedDeltaLabel" }
  ];
  const userPagesMetrics = [
    { key: "visits", label: "Visits", valueType: "number", deltaKey: "visitsDeltaPct", deltaUnit: "%", previousKey: "previousVisits", deltaLabelKey: "visitsDeltaLabel" },
    { key: "engagedSeconds", label: "Engaged", valueType: "duration", deltaKey: "engagedDeltaPct", deltaUnit: "%", previousKey: "previousEngagedSeconds", deltaLabelKey: "engagedDeltaLabel" },
    { key: "avgVisitSeconds", label: "Avg / visit", valueType: "duration", deltaKey: "avgVisitDeltaPct", deltaUnit: "%", previousKey: "previousAvgVisitSeconds", deltaLabelKey: "avgVisitDeltaLabel" },
    { key: "interactionPct", label: "Interaction", valueType: "percent", deltaKey: "interactionDeltaPp", deltaUnit: "pp", previousKey: "previousInteractionPct", deltaLabelKey: "interactionDeltaLabel", barMode: "percent" }
  ];
  const userPagesDefaultSortDirections = {
    pageName: "asc",
    productArea: "asc",
    visits: "desc",
    shareOfUserTimePct: "desc",
    engagedSeconds: "desc",
    avgVisitSeconds: "desc",
    interactionPct: "desc",
    peerUsagePct: "desc",
    lastUsedAt: "desc"
  };
  const userPagesPageSize = 15;
  const statusDistributionColorNames = {
    Power: "c-green",
    Healthy: "c-blue",
    Light: "c-orange",
    Passive: "c-brown",
    Dropped: "c-red"
  };
  const areaUsedEngagedSecondsThreshold = 60;
  const areaUsedVisitsThreshold = 2;
  const buildMetricDynamicsSeries = metricDynamicsHelpers.buildMetricDynamicsSeries || ((options = {}) => {
    const current = Array.isArray(options.currentSeries)
      ? options.currentSeries.map((point) => Number(point?.value ?? point) || 0)
      : [];

    return {
      actualSeries: current,
      current,
      currentStraightTrendSeries: [],
      currentTrend: [],
      benchmarkStraightTrendSeries: [],
      benchmark: [],
      benchmarkUnavailableReason: "",
      peerSeriesList: [],
      peerTraces: [],
      hiddenPeerTraceCount: 0
    };
  });
  const getMetricDynamicsShape = metricDynamicsHelpers.getMetricDynamicsShape
    || (() => ({ name: "cumulative_total", step: false, filled: true, selfTrend: false }));
  const setMetricDynamicsLoadingState = metricDynamicsHelpers.setMetricDynamicsLoadingState || (() => false);
  const getMetricDynamicsAxisBounds = metricDynamicsHelpers.getMetricDynamicsAxisBounds || (() => ({ min: "dataMin", max: "dataMax" }));

  const state = {
    userId: provider.DEFAULT_USER_ID,
    periodDays: helpers.DEFAULT_PERIOD_DAYS,
    productAreaId: "",
    peerGroup: provider.DEFAULT_PEER_GROUP,
    companyId: "",
    pageSearch: ""
  };

  let currentData = null;
  let userSearchActiveIndex = -1;
  let userSearchQuery = "";
  let userSearchDebounceId = 0;
  const userSearchRecentStorageKey = `hymetry:recent-users:${document.body?.dataset.projectId || "unknown-project"}`;
  let userSearchRequestToken = 0;
  let userSearchResults = [];
  let userPagesSortMounted = false;
  let peerComparisonAdoptionCellTooltipId = 0;
  let peerComparisonPeriodChangeTooltipId = 0;
  let splitChangeValueWidthSyncFrame = 0;
  const userPagesTableState = {
    sortKey: "engagedSeconds",
    sortDirection: "desc",
    page: 1,
    isLoading: false,
    loadingToken: 0
  };

  function tablePagination(data, tableKey) {
    return data?.tableData?.[tableKey]?.pagination || null;
  }

  function hasServerTable(data, tableKey) {
    return Boolean(tablePagination(data, tableKey));
  }

  function tablePageCount(data, tableKey, rows, pageSize) {
    const pagination = tablePagination(data, tableKey);
    const totalPages = Number(pagination?.totalPages);

    if (Number.isFinite(totalPages) && totalPages > 0) {
      return Math.max(1, Math.ceil(totalPages));
    }

    return Math.max(1, Math.ceil(rows.length / pageSize));
  }

  function tableRowsForRender(data, tableKey, rows, tableState, pageSize) {
    if (hasServerTable(data, tableKey)) {
      return rows;
    }

    const pageStart = (tableState.page - 1) * pageSize;
    return rows.slice(pageStart, pageStart + pageSize);
  }

  function applyTablePayload(target, tableKey, rowKey, payload, tableState) {
    if (!target || !payload || !Array.isArray(payload.rows)) {
      return false;
    }

    target[rowKey] = payload.rows;
    target.tableData = {
      ...(target.tableData || {}),
      [tableKey]: payload
    };

    const page = Number(payload.pagination?.page);
    if (Number.isFinite(page) && page > 0) {
      tableState.page = Math.round(page);
    }

    return true;
  }
  const userMetricDynamicsState = {
    showPeers: false,
    isLoading: false,
    loadingToken: 0
  };

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function tableHeaderTooltip(label, description, tooltipId, options = {}) {
    const alignmentClass = options.align === "end" ? " metric-header-tooltip--end" : "";

    return `
      <span class="metric-header-tooltip${alignmentClass}" tabindex="0" aria-describedby="${escapeHtml(tooltipId)}">
        ${escapeHtml(label)}
        <span id="${escapeHtml(tooltipId)}" class="metric-header-tooltip__content" role="tooltip">${escapeHtml(description)}</span>
      </span>
    `;
  }

  function readTailwindColor(name) {
    const style = globalScope.getComputedStyle && globalScope.document?.documentElement
      ? globalScope.getComputedStyle(globalScope.document.documentElement)
      : null;
    const value = style?.getPropertyValue(`--color-${name}`).trim();

    if (!value || value.startsWith("oklch(")) {
      return colorFallbacks[name];
    }

    return value;
  }

  function tailwindColor(name) {
    return readTailwindColor(name) || colorFallbacks[name] || name;
  }

  function rgbaFromHex(hex, opacity) {
    const normalized = String(hex || "").trim().replace("#", "");
    const value = normalized.length === 3
      ? normalized.split("").map((character) => character + character).join("")
      : normalized;

    if (!/^[0-9a-f]{6}$/i.test(value)) {
      return `rgba(66, 105, 208, ${opacity})`;
    }

    const red = parseInt(value.slice(0, 2), 16);
    const green = parseInt(value.slice(2, 4), 16);
    const blue = parseInt(value.slice(4, 6), 16);

    return `rgba(${red}, ${green}, ${blue}, ${opacity})`;
  }

  function rgbFromHex(hex) {
    const normalized = String(hex || "").trim().replace("#", "");
    const value = normalized.length === 3
      ? normalized.split("").map((character) => character + character).join("")
      : normalized;

    if (!/^[0-9a-f]{6}$/i.test(value)) {
      return null;
    }

    return {
      red: parseInt(value.slice(0, 2), 16),
      green: parseInt(value.slice(2, 4), 16),
      blue: parseInt(value.slice(4, 6), 16)
    };
  }

  function hexFromRgb({ red, green, blue }) {
    return `#${[red, green, blue].map((value) => Math.round(Math.max(0, Math.min(255, value))).toString(16).padStart(2, "0")).join("")}`;
  }

  function mixHexColors(sourceColor, targetColor, targetWeight) {
    const source = rgbFromHex(sourceColor);
    const target = rgbFromHex(targetColor);

    if (!source || !target) {
      return sourceColor;
    }

    return hexFromRgb({
      red: source.red + (target.red - source.red) * targetWeight,
      green: source.green + (target.green - source.green) * targetWeight,
      blue: source.blue + (target.blue - source.blue) * targetWeight
    });
  }

  function readableSeriesLabelColor(color) {
    const rgb = rgbFromHex(color);

    if (!rgb) {
      return color;
    }

    const brightness = (rgb.red * 0.299 + rgb.green * 0.587 + rgb.blue * 0.114) / 255;

    return mixHexColors(color, tailwindColor("slate-900"), brightness > 0.58 ? 0.36 : 0.24);
  }

  function tailwindAlpha(name, opacity) {
    return rgbaFromHex(tailwindColor(name), opacity);
  }

  const chartTheme = {
    colors: {
      text: tailwindColor("slate-900"),
      primary: tailwindColor("c-blue"),
      warning: tailwindColor("c-orange"),
      mutedText: tailwindColor("slate-500"),
      labelText: tailwindColor("slate-700"),
      axis: tailwindColor("slate-300"),
      grid: tailwindColor("slate-200"),
      white: tailwindColor("white")
    }
  };
  const productAreaColorResolver = globalScope.HymetryProductAreaColors?.createResolver({
    resolveColor: tailwindColor,
    palette: visitsCircleColors
  }) || null;

  function syncProductAreaPalette() {
    if (!productAreaColorResolver) {
      return;
    }

    productAreaColorResolver.reset();
    (provider.PRODUCT_AREAS || []).forEach((area) => productAreaColorResolver.add(area));
    (currentData?.productAreas || []).forEach((area) => productAreaColorResolver.add(area));
    (currentData?.dailyUsage || []).forEach((row) => productAreaColorResolver.add(row.productAreaName || row.productAreaId, row.productAreaColor));
    (currentData?.productAreaMix || []).forEach((row) => productAreaColorResolver.add(row.productAreaName || row.productAreaId, row.productAreaColor));
    (currentData?.pagesUsed || []).forEach((row) => productAreaColorResolver.add(row.productAreaName || row.productAreaId, row.productAreaColor));
    (currentData?.underusedPages || []).forEach((row) => productAreaColorResolver.add(row.productAreaName || row.productAreaId, row.productAreaColor));
    (currentData?.peerComparison || []).forEach((row) => {
      (row.productAreaAdoption || []).forEach((cell) => productAreaColorResolver.add(cell.productAreaName || cell.productAreaId, cell.productAreaColor));
      productAreaColorResolver.add(row.topArea, row.topAreaColor);
    });
    productAreaColorResolver.finalize();
  }

  function areaColor(areaId, explicitColor = "") {
    const area = (currentData?.productAreas || provider.PRODUCT_AREAS).find((row) => row.id === areaId || row.name === areaId);

    if (productAreaColorResolver) {
      return productAreaColorResolver.color(area || areaId, explicitColor || area?.color || "");
    }

    return tailwindColor(explicitColor || area?.color || "c-blue");
  }

  function parseDisplayDate(value) {
    const dateOnlyMatch = String(value || "").match(/^(\d{4})-(\d{2})-(\d{2})$/);

    if (dateOnlyMatch) {
      return new Date(Number(dateOnlyMatch[1]), Number(dateOnlyMatch[2]) - 1, Number(dateOnlyMatch[3]));
    }

    return new Date(value);
  }

  function formatDate(value) {
    const date = parseDisplayDate(value);

    if (Number.isNaN(date.getTime())) {
      return String(value || "-");
    }

    return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric" }).format(date);
  }

  function formatDateTime(value) {
    const date = parseDisplayDate(value);

    if (Number.isNaN(date.getTime())) {
      return String(value || "-");
    }

    const relativeDate = formatRelativeDateLabel(date);
    const dateLabel = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric" }).format(date);
    const timeLabel = new Intl.DateTimeFormat("en-US", {
      hour: "numeric",
      minute: "2-digit"
    }).format(date);

    return `${relativeDate} (${dateLabel}), ${timeLabel}`;
  }

  function formatRelativeDate(value) {
    const date = parseDisplayDate(value);

    if (Number.isNaN(date.getTime())) {
      return String(value || "-");
    }

    return formatRelativeDateLabel(date);
  }

  function recencyReferenceDate() {
    const source = provider.AS_OF_DATE || null;
    const date = source
      ? new Date(`${String(source).slice(0, 10)}T00:00:00`)
      : new Date();

    return Number.isNaN(date.getTime()) ? new Date() : date;
  }

  function localDateStart(date) {
    return new Date(date.getFullYear(), date.getMonth(), date.getDate());
  }

  function formatRelativeDateLabel(date) {
    const dayInMilliseconds = 24 * 60 * 60 * 1000;
    const elapsedDays = Math.round((localDateStart(recencyReferenceDate()) - localDateStart(date)) / dayInMilliseconds);

    if (elapsedDays === 0) {
      return "Today";
    }

    if (elapsedDays > 0) {
      return `${elapsedDays} ${elapsedDays === 1 ? "day" : "days"} ago`;
    }

    const futureDays = Math.abs(elapsedDays);

    return `In ${futureDays} ${futureDays === 1 ? "day" : "days"}`;
  }

  function metricFormatter(metric, value) {
    if (metric === "engagedSeconds" || metric === "intensitySecondsPerActiveDay") {
      return helpers.formatDuration(value);
    }

    if (metric === "consistency" || metric === "interaction" || metric === "interactionRate") {
      return helpers.formatPercent(value);
    }

    return helpers.formatNumber(value);
  }

  function chartUnavailable(element, message) {
    if (!element) {
      return;
    }

    element.innerHTML = `<div class="flex h-full items-center justify-center rounded-lg bg-slate-50 text-sm text-slate-500">${escapeHtml(message || "Chart library unavailable.")}</div>`;
  }

  function mountChart(element, option) {
    if (!element) {
      return null;
    }

    disposeVega(element);

    if (element.__hymetryChart) {
      element.__hymetryChart.dispose();
      element.__hymetryChart = null;
    }

    if (element.__hymetryChartResize) {
      globalScope.removeEventListener("resize", element.__hymetryChartResize);
      element.__hymetryChartResize = null;
    }

    if (!globalScope.echarts) {
      chartUnavailable(element);
      return null;
    }

    const chart = globalScope.echarts.init(element, null, { renderer: "canvas" });
    chart.setOption(option, true);
    element.__hymetryChart = chart;

    const resize = () => chart.resize();
    globalScope.addEventListener("resize", resize);
    element.__hymetryChartResize = resize;

    if (globalScope.ResizeObserver) {
      if (element.__hymetryResizeObserver) {
        element.__hymetryResizeObserver.disconnect();
      }

      const observer = new ResizeObserver(resize);
      observer.observe(element);
      element.__hymetryResizeObserver = observer;
    }

    return chart;
  }

  function disposeVega(element) {
    if (element?.__hymetryVegaView) {
      element.__hymetryVegaView.finalize();
      element.__hymetryVegaView = null;
    }
  }

  function statusBadge(status) {
    return `<span class="users-badge ${helpers.getStatusBadgeVariant(status)}">${escapeHtml(helpers.getStatusLabel(status))}</span>`;
  }

  function emailTag(email) {
    const value = String(email || "").trim();

    if (!value) {
      return "";
    }

    return `
      <a class="user-detail-meta__item user-detail-meta__link" href="mailto:${escapeHtml(value)}" aria-label="${escapeHtml(`Email ${value}`)}">
        <span class="user-detail-meta__label">Email</span>
        <span>${escapeHtml(value)}</span>
      </a>
    `;
  }

  function priorityBadge(priority) {
    const label = String(priority || "low");
    return `<span class="users-badge ${helpers.getPriorityBadgeVariant(label)}">${escapeHtml(label.charAt(0).toUpperCase() + label.slice(1))}</span>`;
  }

  function recommendedActionTypeBadge(type) {
    const label = helpers.getRecommendedActionTypeLabel
      ? helpers.getRecommendedActionTypeLabel(type)
      : String(type || "activation_gap").replace(/_/g, " ");
    const variant = helpers.getRecommendedActionTypeBadgeVariant
      ? helpers.getRecommendedActionTypeBadgeVariant(type)
      : "users-badge--slate";

    return `<span class="users-badge ${variant}">${escapeHtml(label)}</span>`;
  }

  function lightbulbIconMarkup() {
    return `
<svg class="user-detail-health-summary__icon" width="18" height="18" viewBox="0 0 18 18" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                                <path d="M9.00043 16.5016C9.83502 16.5016 10.5116 16.1026 10.5116 15.6104C10.5116 15.1182 9.83502 14.7192 9.00043 14.7192C8.16583 14.7192 7.48926 15.1182 7.48926 15.6104C7.48926 16.1026 8.16583 16.5016 9.00043 16.5016Z" fill="#424242" />
                                <path d="M9.00064 1.49988C6.36531 1.49988 4.22754 3.45887 4.22754 5.87418C4.22754 6.50426 4.41756 7.17809 4.69635 7.77192C5.08765 8.60702 5.51395 9.2246 5.63897 9.45213C5.98651 10.0847 5.9365 10.751 6.03276 11.1686C6.21404 11.9487 6.75661 12.2312 8.99939 12.2312C11.2422 12.2312 11.7247 11.9624 11.926 11.2436C12.0635 10.7548 11.9298 10.221 12.276 9.58964C12.4011 9.36212 12.9099 8.60827 13.3024 7.77192C13.5812 7.17809 13.7712 6.50426 13.7712 5.87418C13.7737 3.45887 11.636 1.49988 9.00064 1.49988Z" fill="#FFD600" />
                                <path d="M9.00066 12.3249C10.5155 12.3249 11.7435 12.0753 11.7435 11.7674C11.7435 11.4595 10.5155 11.21 9.00066 11.21C7.48582 11.21 6.25781 11.4595 6.25781 11.7674C6.25781 12.0753 7.48582 12.3249 9.00066 12.3249Z" fill="#B26500" />
                                <path d="M9.0006 12.0251C10.1044 12.0251 10.9992 11.9098 10.9992 11.7676C10.9992 11.6254 10.1044 11.5101 9.0006 11.5101C7.89678 11.5101 7.00195 11.6254 7.00195 11.7676C7.00195 11.9098 7.89678 12.0251 9.0006 12.0251Z" fill="#FFA000" />
                                <path fill-rule="evenodd" clip-rule="evenodd" d="M7.51073 8.13831C7.52504 8.10459 7.53768 8.07481 7.54723 8.05078L7.77954 8.14311C7.76639 8.17618 7.75125 8.21184 7.73526 8.24948C7.69907 8.33468 7.65857 8.43004 7.62718 8.5286C7.60511 8.5979 7.59042 8.66084 7.58619 8.71339C7.58181 8.76771 7.58979 8.79677 7.59761 8.81017C7.69072 8.97015 7.84003 9.08567 8.00016 9.20951C8.02349 9.22755 8.04704 9.24577 8.07069 9.26434C8.23973 9.39701 8.43959 9.56575 8.43959 9.82686C8.43959 10.1353 8.32963 10.7713 8.22355 11.3166C8.16993 11.5922 8.11633 11.8493 8.07615 12.0375C8.05605 12.1315 8.0393 12.2084 8.02757 12.2619C8.0217 12.2886 8.01709 12.3094 8.01394 12.3236L8.0091 12.3453C8.00909 12.3453 8.00908 12.3454 7.88712 12.318C7.76516 12.2906 7.76516 12.2906 7.76517 12.2906L7.7699 12.2693C7.77301 12.2553 7.77758 12.2347 7.78341 12.2082C7.79505 12.1552 7.8117 12.0788 7.83168 11.9852C7.87165 11.7981 7.92492 11.5426 7.97816 11.2688C8.08583 10.7154 8.1896 10.1059 8.1896 9.82686C8.1896 9.70298 8.09885 9.60423 7.91635 9.46098C7.89543 9.44457 7.87345 9.42768 7.85073 9.41022C7.69366 9.28951 7.50137 9.14175 7.38163 8.93606C7.33701 8.85949 7.33076 8.77092 7.337 8.69333C7.3434 8.61394 7.36417 8.53063 7.38898 8.45275C7.42408 8.34251 7.47318 8.22682 7.51073 8.13831Z" fill="#B26500" />
                                <path fill-rule="evenodd" clip-rule="evenodd" d="M10.1414 8.07976C10.1414 8.07978 10.1414 8.07979 10.2547 8.02694C10.368 7.97408 10.368 7.9741 10.368 7.97412L10.3681 7.97434L10.3683 7.97481L10.369 7.97642L10.3716 7.98213C10.3739 7.98704 10.377 7.99408 10.381 8.00305C10.3888 8.02096 10.3998 8.04659 10.4125 8.0781C10.4378 8.14093 10.4706 8.22806 10.4995 8.32455C10.5284 8.42046 10.5545 8.52901 10.5652 8.6339C10.5756 8.736 10.5729 8.84963 10.5303 8.94616L10.5302 8.94634C10.4971 9.02096 10.4307 9.09307 10.3653 9.15398C10.2967 9.21789 10.2151 9.28188 10.1368 9.33937C10.058 9.39713 9.98036 9.4499 9.9188 9.49113C9.90164 9.50262 9.8863 9.51285 9.87278 9.52187C9.83542 9.54679 9.81195 9.56245 9.80236 9.56982C9.80219 9.57009 9.79623 9.57616 9.78779 9.59535C9.77826 9.61701 9.7687 9.64824 9.7603 9.69041C9.74348 9.77481 9.73412 9.88834 9.73163 10.0245C9.72666 10.2959 9.7492 10.6384 9.7821 10.9772C9.81491 11.3151 9.85766 11.6457 9.89226 11.8921C9.90955 12.0152 9.92478 12.1171 9.93567 12.1882C9.94112 12.2237 9.94549 12.2515 9.94848 12.2704L9.95191 12.2919L9.95306 12.299C9.95306 12.299 9.95307 12.2991 9.82971 12.3192C9.70635 12.3393 9.70634 12.3393 9.70634 12.3393L9.7051 12.3316L9.70158 12.3096C9.69852 12.2903 9.69409 12.262 9.68858 12.2261C9.67754 12.1541 9.66216 12.0511 9.6447 11.9269C9.60981 11.6784 9.56655 11.344 9.53328 11.0014C9.50009 10.6595 9.47645 10.3058 9.48168 10.0199C9.48429 9.87744 9.49411 9.74705 9.51513 9.64156C9.52565 9.58878 9.53966 9.53857 9.55895 9.49472C9.57778 9.45191 9.6053 9.40666 9.64758 9.37351L9.64773 9.37339C9.665 9.35989 9.70165 9.33546 9.74394 9.30728C9.75552 9.29956 9.76753 9.29156 9.77968 9.28342C9.8403 9.24282 9.91449 9.19239 9.98888 9.13781C10.0636 9.08297 10.1365 9.02548 10.195 8.971C10.2567 8.91358 10.2903 8.87043 10.3016 8.84504C10.3183 8.8072 10.3252 8.74508 10.3165 8.65916C10.308 8.57598 10.2865 8.48415 10.2601 8.39648C10.234 8.30938 10.2041 8.22972 10.1807 8.17166C10.169 8.14272 10.159 8.11938 10.152 8.10344C10.1485 8.09547 10.1458 8.08936 10.144 8.08534L10.1419 8.08091L10.1415 8.07993L10.1414 8.07976Z" fill="#B26500" />
                                <path fill-rule="evenodd" clip-rule="evenodd" d="M8.59513 5.47554C8.66988 5.3545 8.78667 5.2748 8.94338 5.27664C9.08657 5.27833 9.20299 5.33697 9.28742 5.43772C9.36803 5.53391 9.41436 5.66195 9.43934 5.79934C9.4893 6.07405 9.46177 6.4311 9.39223 6.78752C9.3273 7.12035 9.22365 7.4631 9.10193 7.755C9.14094 7.84228 9.18135 7.9221 9.22235 7.99204C9.29571 8.11717 9.36444 8.19926 9.42144 8.23985C9.44886 8.25937 9.46774 8.26509 9.47855 8.26625C9.48698 8.26715 9.496 8.26613 9.50929 8.25758C9.54553 8.23422 9.60152 8.17678 9.67193 8.07852C9.74006 7.98343 9.81452 7.86041 9.88992 7.71818C9.92321 7.65537 9.95649 7.58919 9.9893 7.52049C9.93326 7.29201 9.87216 7.01412 9.82823 6.73539C9.7762 6.40523 9.7463 6.06248 9.78324 5.79766C9.80164 5.66576 9.83829 5.53978 9.90851 5.44407C9.98343 5.34195 10.0927 5.28038 10.2318 5.28038C10.3809 5.28038 10.502 5.3369 10.5843 5.4444C10.6618 5.54553 10.695 5.6789 10.7044 5.81776C10.7231 6.09572 10.6497 6.45584 10.5378 6.81142C10.4593 7.0609 10.3597 7.31464 10.2533 7.54617C10.2567 7.55962 10.2601 7.57286 10.2634 7.58587C10.2947 7.70751 10.3227 7.80882 10.3428 7.87961C10.3529 7.915 10.361 7.94274 10.3666 7.96155C10.368 7.96628 10.3693 7.97044 10.3703 7.97402C10.3714 7.97756 10.3723 7.98053 10.373 7.98291L10.3746 7.98826L10.375 7.98955L10.3751 7.98984C10.3751 7.98985 10.3751 7.9899 10.2556 8.02649C10.1361 8.06308 10.1361 8.06306 10.1361 8.06302L10.1354 8.06092L10.1336 8.05504C10.1321 8.0499 10.1298 8.04235 10.1269 8.03256C10.1211 8.01297 10.1128 7.9844 10.1024 7.94812C10.097 7.92893 10.0909 7.90759 10.0845 7.88427C10.0141 8.01334 9.94316 8.12918 9.87514 8.22412C9.80094 8.32767 9.72236 8.41772 9.64454 8.46782C9.58565 8.50568 9.51984 8.52209 9.45194 8.51482C9.38644 8.50781 9.32743 8.47979 9.27643 8.44348C9.1766 8.37238 9.08633 8.25433 9.00669 8.11847C8.9929 8.09494 8.97922 8.07053 8.96569 8.04531C8.93049 8.11144 8.89427 8.17296 8.85734 8.22859C8.78281 8.34085 8.69971 8.43794 8.60921 8.49726C8.48423 8.57918 8.35009 8.55018 8.24237 8.48189C8.13852 8.41606 8.04048 8.30467 7.9515 8.1743C7.91536 8.12135 7.87961 8.06363 7.84458 8.00199C7.82203 8.05506 7.79874 8.10552 7.77476 8.15291L7.5517 8.04006C7.60166 7.94129 7.64896 7.82626 7.6925 7.70056C7.61287 7.52387 7.54047 7.33119 7.48006 7.13562C7.35868 6.74269 7.28153 6.32465 7.29686 5.9881C7.3045 5.82024 7.33554 5.66219 7.40438 5.53646C7.47572 5.40617 7.58826 5.31085 7.74599 5.28238C7.72415 2.1702 8.23538 2.23019 8.58536 2.65517C8.6841 2.77516 8.76035 2.91766 8.77785 3.07265C8.81285 3.37138 8.62786 3.65387 8.40787 3.86136C7.7804 4.45383 6.8892 4.74131 6.48422 5.55877C6.38922 5.75001 6.31423 5.95625 6.16924 6.11249C6.02424 6.26873 5.78301 6.36373 5.59427 6.26373C5.49427 6.21123 5.42552 6.11249 5.36928 6.01375C5.0143 5.38128 5.04055 4.57507 5.35303 3.9201C5.69676 3.20264 6.45047 2.48268 7.23543 2.29019Z" fill="#FFFF8D" />
                                <path d="M11.7374 11.8839C11.7374 11.8839 11.0173 12.2314 9.0008 12.2314C6.9843 12.2314 6.26421 11.8839 6.26421 11.8839C6.26421 11.8839 6.2192 12.5264 6.36797 12.8176C6.54674 13.1676 6.68426 13.2888 6.68426 13.2888L6.75927 13.6451L6.72927 13.7388C6.69051 13.8613 6.71801 13.9963 6.80428 14.0925L6.86928 14.165L6.94179 14.5075L6.91679 14.5763C6.86928 14.7075 6.90179 14.8538 6.9993 14.9538L7.04681 15.0025L7.10556 15.2825C7.10556 15.2825 7.4031 15.9175 9.0008 15.9175C10.5985 15.9175 10.896 15.2825 10.896 15.2825L10.901 15.2587L10.9335 15.2262C10.9985 15.1625 11.0198 15.0675 10.9885 14.9825L10.9698 14.9338L11.0473 14.5638L11.1836 14.42C11.2511 14.3488 11.2661 14.2438 11.2223 14.1563L11.1598 14.0325L11.2386 13.6613L11.2886 13.6226C11.3623 13.5413 11.3636 13.4188 11.3311 13.3351C11.3061 13.2688 11.3261 13.1938 11.3773 13.1451C11.4561 13.0701 11.5574 12.9564 11.6324 12.8151C11.7861 12.5289 11.7374 11.8839 11.7374 11.8839Z" fill="#82AEC0" />
                                <path d="M6.68408 13.2889L6.75158 13.6476C7.47904 13.6439 8.45024 13.6801 10.3139 13.3839C10.6501 13.3076 11.0539 13.1564 10.6076 13.2189C10.6076 13.2176 8.89647 13.3814 6.68408 13.2889Z" fill="#2F7889" />
                                <path d="M6.93382 14.5101C7.73878 14.4963 9.38369 14.4163 11.1511 14.0326L11.2298 13.6614C9.38119 14.0814 7.64254 14.1564 6.86133 14.1664L6.93382 14.5101Z" fill="#2F7889" />
                                <path d="M11.039 14.563C9.40284 14.918 7.87168 15.0092 7.04297 15.0292L7.09672 15.2842C7.09672 15.2842 7.12296 16.0754 8.99162 16.0754C10.8603 16.0754 10.8865 15.2842 10.8865 15.2842C10.8865 15.2842 10.0891 15.5117 9.10786 15.4004C9.00787 15.3892 9.00661 15.2555 9.10661 15.243C9.69283 15.1655 10.3928 15.0505 10.9615 14.933L11.039 14.563Z" fill="#2F7889" />
                                <path fill-rule="evenodd" clip-rule="evenodd" d="M11.9587 11.7866C12.0124 11.9136 11.9529 12.0602 11.8258 12.1139L11.7285 11.8838C11.8258 12.1139 11.8257 12.1139 11.8256 12.114L11.8254 12.1141L11.8249 12.1143L11.8237 12.1148L11.8204 12.1161C11.8177 12.1172 11.8143 12.1186 11.81 12.1203C11.8015 12.1236 11.7897 12.1281 11.7746 12.1336C11.7443 12.1446 11.7005 12.1595 11.6429 12.177C11.5276 12.2121 11.3567 12.2576 11.1261 12.3027C10.6647 12.3928 9.96477 12.4811 8.9932 12.4811C8.02165 12.4811 7.32534 12.3928 6.86746 12.3026C6.63854 12.2575 6.46935 12.212 6.35527 12.1768C6.29824 12.1592 6.25501 12.1442 6.225 12.1331C6.20999 12.1276 6.1983 12.1231 6.18984 12.1197C6.18561 12.118 6.18219 12.1166 6.17957 12.1155L6.17624 12.1142L6.17502 12.1136L6.17452 12.1134L6.1743 12.1133C6.1742 12.1133 6.1741 12.1132 6.27286 11.8838L6.1741 12.1132C6.04735 12.0587 5.98882 11.9118 6.04336 11.785C6.09778 11.6586 6.24419 11.6001 6.37073 11.6539C6.37066 11.6539 6.37062 11.6539 6.37062 11.6539L6.37068 11.6539L6.37091 11.654L6.371 11.6541L6.37128 11.6542C6.37146 11.6542 6.37281 11.6548 6.37496 11.6557C6.37927 11.6574 6.38679 11.6603 6.3976 11.6643C6.41923 11.6722 6.45403 11.6844 6.5026 11.6994C6.59972 11.7293 6.75197 11.7707 6.96405 11.8124C7.38816 11.896 8.05202 11.9815 8.9932 11.9815C9.93437 11.9815 10.6021 11.896 11.0302 11.8124C11.2443 11.7705 11.3986 11.7292 11.4973 11.6991C11.5467 11.6841 11.5822 11.6719 11.6044 11.6638C11.6154 11.6598 11.6232 11.6569 11.6276 11.6551C11.6299 11.6542 11.6313 11.6537 11.6319 11.6534C11.7591 11.6002 11.9051 11.6598 11.9587 11.7866Z" fill="#82AEC0" />
                                <path d="M7.23543 2.29019C7.72415 2.1702 8.23538 2.23019 8.58536 2.65517C8.6841 2.77516 8.76035 2.91766 8.77785 3.07265C8.81285 3.37138 8.62786 3.65387 8.40787 3.86136C7.7804 4.45383 6.8892 4.74131 6.48422 5.55877C6.38922 5.75001 6.31423 5.95625 6.16924 6.11249C6.02424 6.26873 5.78301 6.36373 5.59427 6.26373C5.49427 6.21123 5.42552 6.11249 5.36928 6.01375C5.0143 5.38128 5.04055 4.57507 5.35303 3.9201C5.69676 3.20264 6.45047 2.48268 7.23543 2.29019Z" fill="#FFFF8D" />
                                <path d="M6.80681 12.4927C6.69682 12.4427 6.74056 12.2777 6.86056 12.2865C7.26304 12.3177 7.948 12.3565 8.8542 12.3565C9.80915 12.3565 10.6491 12.2852 11.1391 12.2327C11.2603 12.2202 11.3066 12.3865 11.1953 12.4377C10.8178 12.6152 10.1266 12.8177 8.9417 12.8177C7.78551 12.8177 7.14804 12.6465 6.80681 12.4927Z" fill="#FFD600" />
                                <path d="M7.49277 13.7552C7.40902 13.7852 7.32278 13.8265 7.28028 13.9039C7.26528 13.9327 7.25653 13.9652 7.26278 13.9977C7.27278 14.0452 7.31653 14.0789 7.36028 14.1002C7.44777 14.1427 7.54652 14.1539 7.64276 14.1552C7.8415 14.1577 8.03899 14.1202 8.23523 14.0827C8.29398 14.0714 8.35397 14.0602 8.40647 14.0314C8.45897 14.0027 8.50397 13.9539 8.51272 13.8952C8.52522 13.8165 8.46897 13.7402 8.40022 13.7027C8.16274 13.5715 7.73276 13.669 7.49277 13.7552Z" fill="#94D1E0" />
                                <path d="M7.67929 14.5791C7.59555 14.6091 7.5093 14.6503 7.46681 14.7278C7.45181 14.7565 7.44306 14.789 7.44931 14.8215C7.45931 14.869 7.50305 14.9028 7.5468 14.924C7.6343 14.9665 7.73304 14.9778 7.82929 14.979C8.02803 14.9815 8.22551 14.944 8.42175 14.9065C8.4805 14.8953 8.5405 14.884 8.593 14.8553C8.64549 14.8265 8.69049 14.7778 8.69924 14.719C8.71174 14.6403 8.65549 14.5641 8.58675 14.5266C8.34926 14.3966 7.91803 14.4941 7.67929 14.5791Z" fill="#94D1E0" />
                                <path d="M7.25188 11.5261C7.36562 11.5373 7.48562 11.5273 7.58186 11.4661C7.67811 11.4048 7.73935 11.2798 7.7006 11.1724C7.6806 11.1161 7.63686 11.0711 7.59436 11.0286C7.50061 10.9361 7.40687 10.8436 7.31437 10.7511C7.21063 10.6474 7.10689 10.5449 6.99439 10.4511C6.82065 10.3061 6.58691 10.1699 6.35817 10.2762C6.16318 10.3661 6.11694 10.5436 6.20318 10.7299C6.38692 11.1211 6.8144 11.4811 7.25188 11.5261Z" fill="#FFFF8D" />
                            </svg>
    `;
  }

  function companyDetailHref(user) {
    if (provider.companyDetailHref) {
      return provider.companyDetailHref(user.companyId, state.periodDays);
    }

    const params = new URLSearchParams();
    params.set("company_id", user.companyId);
    params.set("period", `${state.periodDays}d`);

    return `../Companies/detail.html?${params.toString()}`;
  }

  function userDetailHref(user) {
    const userId = String(user?.userId || user?.id || user?.user_id || "").trim();

    if (provider.userDetailHref) {
      return provider.userDetailHref(userId, state.periodDays);
    }

    const params = new URLSearchParams();
    params.set("user_id", userId);
    params.set("period", `${state.periodDays}d`);

    return `../users/detail.html?${params.toString()}`;
  }

  function pageDetailHref(pageRuleId) {
    if (provider.pageDetailHref) {
      return provider.pageDetailHref(pageRuleId, state.periodDays);
    }

    const params = new URLSearchParams();
    params.set("page_rule_id", pageRuleId);
    params.set("period", String(state.periodDays || helpers.DEFAULT_PERIOD_DAYS));

    return `../Pages/detail.html?${params.toString()}`;
  }

  function userInsightSummary() {
    const insights = Array.isArray(currentData?.insights) ? currentData.insights.filter(Boolean) : [];

    if (!insights.length) {
      return "Not enough activity in this period to generate a reliable user insight.";
    }

    return insights.slice(0, 2).join(" ");
  }

  function deltaClass(value) {
    const number = Number(value) || 0;

    if (number > 0) {
      return "text-green-700";
    }

    if (number < 0) {
      return "text-red-600";
    }

    return "text-slate-700";
  }

  function productAreaTooltipMarkup(title, rows) {
    return analyticsTooltips.render({ title, rows });
  }

  function productAreaTooltipText(rows) {
    return analyticsTooltips.text(rows);
  }

  function setHidden(id, hidden) {
    document.getElementById(id)?.classList.toggle("hidden", hidden);
  }

  function readUrlState() {
    const params = new URLSearchParams(globalScope.location.search);
    state.userId = params.get("userId") || params.get("id") || provider.DEFAULT_USER_ID;
    const rangePeriod = provider.periodDaysFromRange ? provider.periodDaysFromRange(params.get("range")) : "";
    state.periodDays = helpers.coercePeriodDays(params.get("period") || params.get("days") || rangePeriod || provider.DEFAULT_PERIOD_DAYS);
    state.peerGroup = provider.DEFAULT_PEER_GROUP;
    state.productAreaId = "";
  }

  function updateUrl() {
    if (provider.userDetailHref) {
      globalScope.history?.replaceState({}, "", provider.userDetailHref(state.userId, state.periodDays));
      return;
    }

    const params = new URLSearchParams();
    params.set("userId", state.userId);

    if (state.periodDays !== helpers.DEFAULT_PERIOD_DAYS) {
      params.set("period", `${state.periodDays}d`);
    }

    globalScope.history?.replaceState({}, "", `${globalScope.location.pathname}?${params.toString()}`);
  }

  function loadCurrentData() {
    currentData = provider.getUserDetailsData({
      userId: state.userId,
      periodDays: state.periodDays,
      productAreaId: state.productAreaId,
      peerGroup: state.peerGroup
    });
    state.userId = currentData.selectedUser.id;
    state.companyId = currentData.selectedUser.companyId;
    syncProductAreaPalette();
  }

  function normalizeSearchUser(user) {
    const id = String(user?.id || user?.userId || "");

    return {
      ...(user || {}),
      id,
      userId: id,
      name: user?.name || id || "User",
      email: user?.email || "",
      companyId: user?.companyId || user?.company_id || "",
      companyName: user?.companyName || user?.company || user?.company_name || "",
      role: user?.role || "",
      seatType: user?.seatType || user?.seat_type || ""
    };
  }

  function filteredUsersForSearch(query) {
    const normalizedQuery = String(query || "").trim().toLowerCase();
    const selectedUserId = currentData?.selectedUser?.id || "";

    return (currentData?.users || [])
      .map(normalizeSearchUser)
      .filter((user) => {
        if (user.id === selectedUserId) {
          return false;
        }

        if (!normalizedQuery) {
          return true;
        }

        return [user.name, user.email, user.companyName, user.role, user.seatType]
          .filter(Boolean)
          .join(" ")
          .toLowerCase()
          .includes(normalizedQuery);
      })
      .sort((a, b) => a.name.localeCompare(b.name))
      .slice(0, 20);
  }

  function readRecentUsers() {
    try {
      const value = globalScope.localStorage?.getItem(userSearchRecentStorageKey);
      const parsed = JSON.parse(value || "[]");
      const selectedUserId = currentData?.selectedUser?.id || "";

      return Array.isArray(parsed)
        ? parsed
          .map(normalizeSearchUser)
          .filter((user) => user.id && user.id !== selectedUserId)
        : [];
    } catch {
      return [];
    }
  }

  function writeRecentUsers(users) {
    try {
      globalScope.localStorage?.setItem(
        userSearchRecentStorageKey,
        JSON.stringify(users
          .map(normalizeSearchUser)
          .filter((user) => user.id)
          .slice(0, 8)
          .map((user) => ({
            id: user.id,
            name: user.name,
            email: user.email,
            companyId: user.companyId,
            companyName: user.companyName,
            role: user.role
          })))
      );
    } catch {
      // localStorage may be unavailable in private or embedded browsing contexts.
    }
  }

  function rememberRecentUser(user) {
    const normalized = normalizeSearchUser(user);

    if (!normalized.id) {
      return;
    }

    const users = readRecentUsers();
    writeRecentUsers([normalized, ...users.filter((item) => item.id !== normalized.id)]);
  }

  function currentUserSearchResults(query) {
    const normalizedQuery = String(query || "");

    if (typeof provider.searchUsers === "function" && !normalizedQuery.trim()) {
      const recentUsers = readRecentUsers();
      if (recentUsers.length) {
        return recentUsers;
      }

      if (userSearchQuery !== normalizedQuery) {
        return [];
      }

      const selectedUserId = currentData?.selectedUser?.id || "";
      const fallbackAlternatives = userSearchResults.filter((user) => user.id !== selectedUserId);
      return fallbackAlternatives.length ? fallbackAlternatives : userSearchResults;
    }

    if (typeof provider.searchUsers === "function") {
      return userSearchQuery === normalizedQuery ? userSearchResults : [];
    }

    if (userSearchQuery === normalizedQuery && userSearchResults.length) {
      return userSearchResults;
    }

    return filteredUsersForSearch(normalizedQuery);
  }

  function closeUserSearch() {
    const input = document.getElementById("user-detail-user-search");
    const results = document.getElementById("user-detail-user-results");
    const button = document.getElementById("user-detail-user-selector-button");

    if (userSearchDebounceId) {
      globalScope.clearTimeout(userSearchDebounceId);
      userSearchDebounceId = 0;
    }

    if (results) {
      results.hidden = true;
    }

    if (input) {
      input.setAttribute("aria-expanded", "false");
    }

    if (button) {
      button.setAttribute("aria-expanded", "false");
    }

    userSearchActiveIndex = -1;
    userSearchRequestToken += 1;
  }

  function renderUserSearch(query, options = {}) {
    const input = document.getElementById("user-detail-user-search");
    const results = document.getElementById("user-detail-user-results");
    const listbox = document.getElementById("user-detail-user-listbox");
    const button = document.getElementById("user-detail-user-selector-button");
    const refresh = options.refresh !== false;
    const normalizedQuery = String(query || "");

    if (!input || !results || !listbox) {
      return;
    }

    if (userSearchQuery !== normalizedQuery) {
      userSearchResults = [];
    }

    const users = currentUserSearchResults(normalizedQuery);
    userSearchQuery = normalizedQuery;
    userSearchActiveIndex = Math.min(Math.max(userSearchActiveIndex, -1), users.length - 1);
    results.hidden = false;
    input.setAttribute("aria-expanded", "true");
    button?.setAttribute("aria-expanded", "true");

    if (!users.length) {
      listbox.innerHTML = `<span class="company-search__empty">${refresh && typeof provider.searchUsers === "function" ? "Loading users..." : "No users found."}</span>`;
    } else {
      listbox.innerHTML = users.map((user, index) => `
        <button
          type="button"
          class="company-search__option"
          role="option"
          data-user-search-id="${escapeHtml(user.id)}"
          data-active="${String(index === userSearchActiveIndex)}"
          aria-selected="${String(index === userSearchActiveIndex)}">
          <span class="min-w-0">
            <span class="company-search__name">${escapeHtml(user.name)}</span>
            <span class="company-search__meta">${escapeHtml([user.email, user.companyName, user.role].filter(Boolean).join(" - "))}</span>
          </span>
          <span class="company-search__open">Open \u2192</span>
        </button>
      `).join("");

      listbox.querySelectorAll("[data-user-search-id]").forEach((option) => {
        option.addEventListener("click", () => {
          const selectedUser = users.find((user) => user.id === option.getAttribute("data-user-search-id"));
          rememberRecentUser(selectedUser);
          state.userId = option.getAttribute("data-user-search-id") || state.userId;
          input.value = "";
          closeUserSearch();
          updateUrl();
          renderAll();
        });
      });
    }

    const shouldLoadFallback = !normalizedQuery.trim() && !readRecentUsers().length;

    if (refresh && (normalizedQuery.trim() || shouldLoadFallback) && typeof provider.searchUsers === "function") {
      const requestToken = userSearchRequestToken + 1;
      userSearchRequestToken = requestToken;
      provider.searchUsers(normalizedQuery, {
        periodDays: state.periodDays,
        limit: 20,
        alphabetical: shouldLoadFallback
      }).then((remoteUsers) => {
        if (requestToken !== userSearchRequestToken || input.value !== normalizedQuery) {
          return;
        }

        userSearchResults = (remoteUsers || [])
          .map(normalizeSearchUser)
          .filter((user) => user.id);
        userSearchQuery = normalizedQuery;
        renderUserSearch(normalizedQuery, { refresh: false });
      });
    }
  }

  function mountUserSearch() {
    const input = document.getElementById("user-detail-user-search");
    const root = document.getElementById("user-detail-user-search-root");
    const button = document.getElementById("user-detail-user-selector-button");

    if (!input || !root || !button || input.__hymetryMounted) {
      return;
    }

    input.__hymetryMounted = true;
    button.addEventListener("click", () => {
      const results = document.getElementById("user-detail-user-results");

      if (results && !results.hidden) {
        closeUserSearch();
        return;
      }

      renderUserSearch(input.value);
      input.focus();
    });
    button.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        closeUserSearch();
        return;
      }

      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        renderUserSearch(input.value);
        input.focus();
      }
    });
    input.addEventListener("input", () => {
      userSearchActiveIndex = -1;

      if (userSearchDebounceId) {
        globalScope.clearTimeout(userSearchDebounceId);
      }

      userSearchDebounceId = globalScope.setTimeout(() => {
        userSearchDebounceId = 0;
        renderUserSearch(input.value);
      }, 220);
    });
    input.addEventListener("focus", () => renderUserSearch(input.value));
    input.addEventListener("click", () => renderUserSearch(input.value));
    input.addEventListener("keydown", (event) => {
      const users = currentUserSearchResults(input.value);

      if (event.key === "Escape") {
        closeUserSearch();
        return;
      }

      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        const direction = event.key === "ArrowDown" ? 1 : -1;
        userSearchActiveIndex = Math.max(0, Math.min(users.length - 1, userSearchActiveIndex + direction));
        renderUserSearch(input.value, { refresh: false });
        return;
      }

      if (event.key === "Enter" && users[userSearchActiveIndex]) {
        event.preventDefault();
        rememberRecentUser(users[userSearchActiveIndex]);
        state.userId = users[userSearchActiveIndex].id;
        input.value = "";
        closeUserSearch();
        updateUrl();
        renderAll();
      }
    });

    document.addEventListener("click", (event) => {
      if (!root.contains(event.target)) {
        closeUserSearch();
      }
    });
  }

  function renderHeader() {
    const user = currentData.selectedUser;
    const titleUserName = document.getElementById("user-detail-title-user-name");
    const companyLink = document.getElementById("user-detail-company-link");
    const company = document.getElementById("user-detail-company");
    const meta = document.getElementById("user-detail-meta");

    document.title = `${user.name}, ${user.companyName}`;

    if (titleUserName) {
      titleUserName.textContent = user.name;
    }

    if (companyLink) {
      companyLink.textContent = user.companyName;
      companyLink.href = companyDetailHref(user);
      companyLink.setAttribute("aria-label", `Open ${user.companyName} company details`);
    }

    if (company) {
      company.innerHTML = `${lightbulbIconMarkup()}<span>${escapeHtml(userInsightSummary())}</span>`;
    }

    if (meta) {
      const tags = [
        ["First seen", formatDate(user.firstSeenAt)],
        ["Last active", formatDateTime(user.lastActiveAt)]
      ];

      meta.innerHTML = [
        statusBadge(user.status),
        emailTag(user.email),
        ...tags.map(([label, value]) => `
        <span class="user-detail-meta__item">
          <span class="user-detail-meta__label">${escapeHtml(label)}</span>
          <span>${escapeHtml(value)}</span>
        </span>
      `)
      ].join("");
    }
  }

  function formatDateShort(value) {
    const date = new Date(`${String(value || "").slice(0, 10)}T00:00:00Z`);

    if (Number.isNaN(date.getTime())) {
      return value || "";
    }

    return new Intl.DateTimeFormat("en-US", {
      month: "short",
      day: "numeric"
    }).format(date);
  }

  function formatDurationWithSeconds(totalSeconds) {
    const seconds = Math.max(0, Math.round(Number(totalSeconds) || 0));

    if (seconds >= 3600) {
      return helpers.formatDuration(seconds);
    }

    const minutes = Math.floor(seconds / 60);
    const remainingSeconds = seconds % 60;

    if (minutes > 0) {
      return `${minutes}m ${String(remainingSeconds).padStart(2, "0")}s`;
    }

    return `${remainingSeconds}s`;
  }

  function formatValueByType(value, valueType) {
    if (valueType === "duration") {
      return formatDurationWithSeconds(value);
    }

    if (valueType === "percent") {
      return helpers.formatPercent(value);
    }

    return helpers.formatNumber(value);
  }

  function formatMetricTooltipValueByType(value, valueType) {
    if (valueType === "duration") {
      return formatDurationWithSeconds(value);
    }

    if (valueType === "percent") {
      const numericValue = Number(value) || 0;
      const decimals = Math.abs(numericValue) < 10 && numericValue % 1 !== 0 ? 1 : 0;
      const factor = 10 ** decimals;
      const roundedValue = Math.round((numericValue + Number.EPSILON) * factor) / factor;

      return `${roundedValue.toFixed(decimals)}%`;
    }

    return formatValueByType(value, valueType);
  }

  function metricTooltipRow(label, value, valueType, options = {}) {
    const displayValue = Number.isFinite(value) ? formatMetricTooltipValueByType(value, valueType) : "-";

    return {
      label,
      value: displayValue,
      marker: options.color ? {
        color: options.color,
        type: "line",
        dashed: Boolean(options.dashed)
      } : undefined
    };
  }

  function metricTooltipPeerRows(peerSeriesList, index, valueType) {
    if (!peerSeriesList.length) {
      return [];
    }

    const peerRows = peerSeriesList
      .map((peer) => ({
        name: peer.name,
        value: Number(peer.data?.[index])
      }))
      .sort((a, b) => {
        const aFinite = Number.isFinite(a.value);
        const bFinite = Number.isFinite(b.value);

        if (aFinite && bFinite) {
          return b.value - a.value;
        }

        if (aFinite) {
          return -1;
        }

        if (bFinite) {
          return 1;
        }

        return String(a.name || "").localeCompare(String(b.name || ""));
      })
      .map((peer) => metricTooltipRow(peer.name || "Peer", peer.value, valueType, { color: tailwindAlpha("slate-400", 0.55) }));

    return peerRows;
  }

  function seriesActualValues(dailySeries) {
    return Array.isArray(dailySeries) ? dailySeries.map((point) => Number(point.value) || 0) : [];
  }

  function seriesDates(dailySeries) {
    return Array.isArray(dailySeries) ? dailySeries.map((point) => point.date) : [];
  }

  function metricSeriesPointCount(periodDays) {
    const days = Number(periodDays) || helpers.DEFAULT_PERIOD_DAYS;

    return Math.max(7, Math.min(30, days));
  }

  function metricTrendDates(pointCount, periodDays) {
    const count = Math.max(1, Number(pointCount) || 1);
    const days = Math.max(count, Number(periodDays) || count);
    const endDate = new Date(`${provider.END_DATE || new Date().toISOString().slice(0, 10)}T00:00:00Z`);

    return Array.from({ length: count }, (_, index) => {
      const offset = count === 1 ? 0 : Math.round((days - 1) - (index * (days - 1)) / (count - 1));
      const date = new Date(endDate.getTime());
      date.setUTCDate(date.getUTCDate() - offset);

      return date.toISOString().slice(0, 10);
    });
  }

  function resampleValues(values, targetLength) {
    const source = (Array.isArray(values) ? values : []).map((value) => Number(value) || 0);
    const length = Math.max(1, Number(targetLength) || source.length || 1);

    if (!source.length) {
      return Array.from({ length }, () => 0);
    }

    if (source.length === 1) {
      return Array.from({ length }, () => source[0]);
    }

    if (source.length === length) {
      return source;
    }

    return Array.from({ length }, (_, index) => {
      const position = length === 1 ? 0 : (index * (source.length - 1)) / (length - 1);
      const leftIndex = Math.floor(position);
      const rightIndex = Math.min(source.length - 1, Math.ceil(position));
      const progress = position - leftIndex;

      return source[leftIndex] + (source[rightIndex] - source[leftIndex]) * progress;
    });
  }

  function seriesFromValues(values, periodDays) {
    const pointCount = metricSeriesPointCount(periodDays);
    const dates = metricTrendDates(pointCount, periodDays);
    const resampledValues = resampleValues(values, pointCount);

    return dates.map((date, index) => ({
      date,
      value: resampledValues[index]
    }));
  }

  function isMetricPercent(card) {
    return card?.id === "interaction_rate";
  }

  function buildOtherUserMetricSeries(card, dates) {
    const peerSeries = Array.isArray(card?.peerSeries) ? card.peerSeries : [];

    return peerSeries
      .filter((peer) => Array.isArray(peer?.dailySeries))
      .slice(0, peerTraceLimit)
      .map((peer) => {
        const valuesByDate = new Map(
          peer.dailySeries.map((point) => [point?.date, point?.value])
        );

        return {
          userId: peer.userId || peer.id,
          userName: peer.userName || peer.name,
          dailySeries: dates.map((date) => ({
            date,
            value: valuesByDate.has(date) ? valuesByDate.get(date) : null
          }))
        };
      });
  }

  function valueTypeForMetric(card) {
    if (card?.id === "engaged_time" || card?.id === "intensity" || card?.id === "avg_visit") {
      return "duration";
    }

    if (isMetricPercent(card)) {
      return "percent";
    }

    return "number";
  }

  function metricTypeForDynamics(card) {
    if (card?.id === "interaction_rate") {
      return "interaction";
    }

    return card?.id || "";
  }

  function createUserMetricChartOption(card, options = {}) {
    const dailySeries = Array.isArray(card.dailySeries) ? card.dailySeries : seriesFromValues(card.trend, options.selectedPeriodDays);
    const dates = seriesDates(dailySeries);
    const currentValues = seriesActualValues(dailySeries);
    const valueType = valueTypeForMetric(card);
    const dynamics = buildMetricDynamicsSeries({
      currentSeries: dailySeries,
      peerSeriesList: buildOtherUserMetricSeries(card, dates),
      metricType: metricTypeForDynamics(card),
      selectedPeriodDays: options.selectedPeriodDays,
      showPeers: options.showPeers,
      currentEntityId: currentData?.selectedUser?.id
    });
    const actualSeries = dynamics.actualSeries || dynamics.current || currentValues;
    const shape = dynamics.shape || getMetricDynamicsShape(metricTypeForDynamics(card));
    // A running total can only climb, so a fitted line through it restates the
    // shape already on screen. Emptying the series here also keeps it out of the
    // tooltip and the axis bounds.
    const currentTrendSeries = shape.selfTrend
      ? (dynamics.currentStraightTrendSeries || dynamics.currentTrend || [])
      : [];
    const benchmarkTrendSeries = dynamics.benchmarkStraightTrendSeries || dynamics.benchmark || [];
    const peerSeriesList = dynamics.peerSeriesList || dynamics.peerTraces || [];
    const yAxisBounds = getMetricDynamicsAxisBounds([
      actualSeries,
      currentTrendSeries,
      benchmarkTrendSeries,
      ...peerSeriesList.map((peer) => peer.data)
    ]);

    return {
      animation: false,
      tooltip: analyticsTooltips.echarts({
        trigger: "axis",
        appendTo: "body",
        confine: false,
        extraCssText: "max-height:min(360px, calc(100vh - 32px));overflow-y:auto;",
        axisPointer: {
          type: "line",
          lineStyle: {
            color: chartTheme.colors.axis,
            width: 1
          }
        },
        formatter: (params) => {
          const items = Array.isArray(params) ? params : [params];
          const index = items[0]?.dataIndex || 0;
          const actualValue = currentValues[index] ?? 0;
          const trendValue = currentTrendSeries[index];
          const benchmarkValue = benchmarkTrendSeries[index];
          const rows = [
            metricTooltipRow("Period to date", actualValue, valueType, { color: chartTheme.colors.primary })
          ];

          if (Number.isFinite(trendValue)) {
            rows.push(metricTooltipRow("Current trend", trendValue, valueType, { color: chartTheme.colors.primary, dashed: true }));
          }

          if (Number.isFinite(benchmarkValue)) {
            rows.push(metricTooltipRow("Other users trend", benchmarkValue, valueType, { color: chartTheme.colors.warning, dashed: true }));
          }

          const peerRows = metricTooltipPeerRows(peerSeriesList, index, valueType);
          const dateLabel = formatDateShort(dates[index]);

          return analyticsTooltips.render({
            title: dateLabel ? `Through ${dateLabel}` : "Period to date",
            sections: peerRows.length ? [{ rows }, { rows: peerRows }] : [{ rows }]
          });
        }
      }),
      grid: {
        left: 0,
        right: 0,
        top: 6,
        bottom: 0
      },
      xAxis: {
        type: "category",
        show: false,
        boundaryGap: false,
        data: dates
      },
      yAxis: {
        type: "value",
        show: false,
        min: yAxisBounds.min,
        max: yAxisBounds.max
      },
      series: peerSeriesList
        .map((peer) => ({
          name: peer.name,
          type: "line",
          data: peer.data,
          smooth: false,
          symbol: "none",
          lineStyle: {
            color: chartTheme.colors.mutedText,
            opacity: 0.18,
            width: 1
          },
          emphasis: {
            disabled: true
          },
          z: 1
        }))
        .concat(benchmarkTrendSeries.length ? [{
          name: "Other users trend",
          type: "line",
          data: benchmarkTrendSeries,
          smooth: false,
          symbol: "none",
          lineStyle: {
            color: chartTheme.colors.warning,
            type: [6, 4],
            width: 2,
            opacity: 0.9
          },
          emphasis: {
            disabled: true
          },
          z: 3
        }] : [])
        .concat([
          currentTrendSeries.length ? {
            name: "Current trend",
            type: "line",
            data: currentTrendSeries,
            smooth: false,
            symbol: "none",
            lineStyle: {
              color: chartTheme.colors.primary,
              type: [6, 4],
              opacity: 0.58,
              width: 2
            },
            emphasis: {
              disabled: true
            },
            z: 4
          } : null,
          {
            name: "Period to date",
            type: "line",
            data: actualSeries,
            step: shape.step ? "end" : false,
            smooth: !shape.step,
            symbol: "none",
            lineStyle: {
              color: chartTheme.colors.primary,
              width: 2.5
            },
            ...(shape.filled ? { areaStyle: { color: tailwindAlpha("c-blue", 0.08) } } : {}),
            emphasis: {
              disabled: true
            },
            z: 5
          }
        ].filter(Boolean))
    };
  }

  const userMetricDynamicsDescriptions = {
    engaged_time: "Total active time spent by this user during the selected period",
    active_days: "Dates with at least one valid visit or activity, out of the selected period's days. Each strip cell is one date.",
    intensity: "Average active time per active day",
    visits: "Number of page visits by this user during the selected period",
    avg_visit: "Average active time per page visit",
    pages_used: "Number of pages or features used by this user",
    areas_used: "Number of distinct product areas this user used during the selected period",
    interaction_rate: "Share of visits with at least one click"
  };

  function metricDynamicsTooltipId(scope, key, index) {
    return `${scope}-metric-dynamics-title-${String(key || index).replace(/[^a-z0-9_-]+/gi, "-").toLowerCase()}`;
  }

  function metricDynamicsPeriodTooltipId(scope, key, index) {
    return `${scope}-metric-dynamics-period-change-${String(key || index).replace(/[^a-z0-9_-]+/gi, "-").toLowerCase()}`;
  }

  function metricDynamicsTitleMarkup(card, scope, index) {
    const key = card?.id || index;
    const label = card?.label || "Metric";
    const description = userMetricDynamicsDescriptions[key] || "Metric value during the selected period";
    const tooltipId = metricDynamicsTooltipId(scope, key, index);

    return `
      <span class="metric-header-tooltip metric-dynamics-title-tooltip" tabindex="0" aria-describedby="${escapeHtml(tooltipId)}">
        ${escapeHtml(label)}
        <span id="${escapeHtml(tooltipId)}" class="metric-header-tooltip__content" role="tooltip">${escapeHtml(description)}</span>
      </span>
    `;
  }

  function clampNumber(value, minValue, maxValue) {
    return Math.max(minValue, Math.min(maxValue, value));
  }

  function previousUserMetricValue(card) {
    const explicitPrevious = Number(card?.previousValue);

    if (Number.isFinite(explicitPrevious)) {
      return explicitPrevious;
    }

    const currentValue = Number(card?.rawValue);
    const deltaValue = Number(card?.deltaValue);

    if (!Number.isFinite(currentValue) || !Number.isFinite(deltaValue)) {
      return currentValue || 0;
    }

    if (card?.deltaType === "pp") {
      const previousValue = valueTypeForMetric(card) === "percent"
        ? currentValue - deltaValue / 100
        : currentValue - deltaValue;

      return valueTypeForMetric(card) === "percent" ? clampNumber(previousValue, 0, 1) : Math.max(0, previousValue);
    }

    if (card?.deltaType === "absolute") {
      return Math.max(0, currentValue - deltaValue);
    }

    const divisor = 1 + deltaValue / 100;

    return divisor > 0 ? currentValue / divisor : 0;
  }

  function metricDynamicsPeriodDeltaMarkup(card, index) {
    const key = card?.id || index;
    const label = card?.label || "Metric";
    const formattedDelta = card?.deltaLabel || helpers.formatDelta(card?.deltaValue, card?.deltaType);
    // The strip card's value already reads "X of N days", so its comparison row
    // has to match rather than showing a bare count next to it.
    const currentLabel = isActivityStripCard(card)
      ? `${card.value} (${card.consistencyLabel})`
      : (card?.value || formatValueByType(card?.rawValue, valueTypeForMetric(card)));
    // A card whose headline carries a unit sends the previous period's wording
    // with it, so the two rows are read against each other rather than a bare
    // number against a phrase.
    const previousLabel = isActivityStripCard(card)
      ? `${helpers.formatNumber(previousUserMetricValue(card))} of ${helpers.formatNumber(card.periodDays)} days`
      : (card?.previousValueLabel || formatValueByType(previousUserMetricValue(card), valueTypeForMetric(card)));
    const tooltipId = metricDynamicsPeriodTooltipId("user", key, index);
    const deltaClassName = card?.deltaDirection === "positive"
      ? "text-green-700"
      : card?.deltaDirection === "negative"
        ? "text-red-600"
        : deltaClass(card?.deltaValue);
    const tooltipRows = [
      { label: "Current period", value: currentLabel },
      { label: "Previous period", value: previousLabel },
      { label: "Change", value: formattedDelta }
    ];

    return `
      <span class="metric-dynamics-period-delta metric-header-tooltip whitespace-nowrap text-sm font-medium ${deltaClassName}" data-tooltip-kind="delta" tabindex="0" aria-label="${escapeHtml(`${label}. ${analyticsTooltips.text(tooltipRows)}`)}" aria-describedby="${escapeHtml(tooltipId)}">
        ${escapeHtml(formattedDelta)}
        <span id="${escapeHtml(tooltipId)}" class="metric-header-tooltip__content" role="tooltip">${analyticsTooltips.render({ rows: tooltipRows })}</span>
      </span>
    `;
  }

  function isActivityStripCard(card) {
    return card?.render === "activity_strip" && Array.isArray(card?.activityStrip);
  }

  function activityStripCellMarkup(day) {
    const tooltipRows = [
      { label: "Engaged", value: formatDurationWithSeconds(day.engagedSeconds) },
      { label: "Visits", value: helpers.formatNumber(day.visits) }
    ];

    // No tabindex per cell: a 180-day period would put 180 stops in the tab
    // order for detail the card already states in words above the strip.
    return `
      <span class="user-activity-strip__cell metric-header-tooltip" data-active="${day.active ? "true" : "false"}">
        <span class="metric-header-tooltip__content" role="tooltip">${analyticsTooltips.render({
          title: formatDateShort(day.date),
          rows: tooltipRows
        })}</span>
      </span>
    `;
  }

  // The card is one column wide like every other KPI, so a period longer than a
  // month wraps into a calendar-style block instead of squeezing its dates into
  // slivers. A single row keeps the taller cells the short periods already had.
  const activityStripSingleRowLimit = 31;
  const activityStripWrappedColumns = 30;

  function activityStripLayout(cellCount) {
    const columns = cellCount <= activityStripSingleRowLimit
      ? Math.max(1, cellCount)
      : activityStripWrappedColumns;

    return {
      columns,
      cellHeight: cellCount <= columns ? "2.25rem" : "0.5rem"
    };
  }

  function activityStripMarkup(card) {
    const days = card.activityStrip || [];
    const summary = `${card.activeDays} of ${card.periodDays} days active, ${card.consistencyLabel}`;
    const layout = activityStripLayout(days.length);

    return `
      <div class="user-activity-strip" role="img" aria-label="${escapeHtml(summary)}" style="--user-activity-strip-columns: ${layout.columns}; --user-activity-strip-cell-height: ${layout.cellHeight};">
        ${days.map(activityStripCellMarkup).join("")}
      </div>
    `;
  }

  function activityStripPanelMarkup(card, index) {
    return `
      <article class="px-5 py-4">
        <div class="flex items-start justify-between gap-3">
          <div class="min-w-0">
            <div class="text-sm font-medium uppercase text-slate-500">${metricDynamicsTitleMarkup(card, "user", index)}</div>
            <div class="mt-2 flex flex-wrap items-baseline gap-2">
              <span class="text-base font-semibold text-slate-900">${escapeHtml(card.value)}</span>
              <span class="text-sm text-slate-500">${escapeHtml(card.consistencyLabel || "")}</span>
            </div>
          </div>
          <div class="shrink-0 text-right font-medium">
            ${metricDynamicsPeriodDeltaMarkup(card, index)}
          </div>
        </div>
        ${activityStripMarkup(card)}
      </article>
    `;
  }

  function metricPanelMarkup(card, index) {
    if (isActivityStripCard(card)) {
      return activityStripPanelMarkup(card, index);
    }

    return `
      <article class="px-5 py-4">
        <div class="flex items-start justify-between gap-3">
          <div class="min-w-0">
            <div class="text-sm font-medium uppercase text-slate-500">${metricDynamicsTitleMarkup(card, "user", index)}</div>
          </div>
          <div class="flex shrink-0 items-center gap-2 text-right font-medium">
            <div class="whitespace-nowrap text-base font-semibold text-slate-900">${escapeHtml(card.value)}</div>
            ${metricDynamicsPeriodDeltaMarkup(card, index)}
          </div>
        </div>
        <div data-user-metric-chart-index="${index}" class="mt-3 h-[92px] w-full"></div>
      </article>
    `;
  }

  function userMetricDynamicsElements() {
    const grid = document.getElementById("user-detail-kpi-grid");

    return {
      shell: document.querySelector("[data-user-metric-dynamics-shell]"),
      grid,
      overlay: document.querySelector("[data-user-metric-dynamics-loading]"),
      toggle: document.querySelector("[data-user-metric-dynamics-show-peers]")
    };
  }

  function setUserMetricDynamicsLoading(isLoading) {
    userMetricDynamicsState.isLoading = Boolean(isLoading);
    setMetricDynamicsLoadingState(userMetricDynamicsElements(), userMetricDynamicsState.isLoading);
  }

  function metricCardsHavePeerSeries(metrics) {
    return metrics.some((card) => (
      Array.isArray(card?.peerSeries)
      && card.peerSeries.some((peer) => Array.isArray(peer?.dailySeries) && peer.dailySeries.length)
    ));
  }

  function updateUserMetricDynamicsExplanation(hasPeerSeries) {
    const explanation = document.querySelector("#user-detail-kpis .metric-dynamics-section-header p");

    if (!explanation) {
      return;
    }

    explanation.textContent = hasPeerSeries
      ? "Each point recomputes the metric from the selected period's start through that date. Rates and averages add a fitted trend; dashed lines compare it with observed peer histories."
      : "Each point recomputes the metric from the selected period's start through that date. Rates and averages add a dashed fitted trend for this user.";
  }

  function mountUserMetricDynamicsToggle(hasPeerSeries) {
    const { toggle } = userMetricDynamicsElements();

    if (!toggle) {
      return;
    }

    const toggleLabel = toggle.closest(".metric-dynamics-toggle");
    if (toggleLabel) {
      toggleLabel.hidden = !hasPeerSeries;
    }
    updateUserMetricDynamicsExplanation(hasPeerSeries);

    if (!hasPeerSeries) {
      userMetricDynamicsState.showPeers = false;
      toggle.checked = false;
      toggle.disabled = true;
      return;
    }

    toggle.checked = userMetricDynamicsState.showPeers;
    toggle.disabled = userMetricDynamicsState.isLoading;

    if (toggle.dataset.metricDynamicsMounted === "true") {
      return;
    }

    toggle.dataset.metricDynamicsMounted = "true";
    toggle.addEventListener("change", () => {
      const nextShowPeers = toggle.checked;
      const token = userMetricDynamicsState.loadingToken + 1;
      userMetricDynamicsState.loadingToken = token;

      setUserMetricDynamicsLoading(true);

      globalScope.setTimeout(() => {
        if (token !== userMetricDynamicsState.loadingToken) {
          return;
        }

        userMetricDynamicsState.showPeers = nextShowPeers;
        setUserMetricDynamicsLoading(false);

        if (currentData) {
          renderKpis();
        }
      }, 380);
    });
  }

  function renderKpis() {
    const container = document.getElementById("user-detail-kpi-grid");

    if (!container) {
      return;
    }

    const metrics = Array.isArray(currentData.metricCards) ? currentData.metricCards.slice(0, 8) : [];
    const hasPeerSeries = metricCardsHavePeerSeries(metrics);
    mountUserMetricDynamicsToggle(hasPeerSeries);
    const chartOptions = {
      selectedPeriodDays: currentData.periodDays,
      showPeers: hasPeerSeries && userMetricDynamicsState.showPeers
    };

    if (!metrics.length) {
      container.innerHTML = `<div class="col-span-full bg-white px-6 py-10 text-center text-slate-500">No user metrics found for this period.</div>`;
      return;
    }

    container.innerHTML = metrics.map(metricPanelMarkup).join("");
    metrics.forEach((card, index) => {
      if (isActivityStripCard(card)) {
        return;
      }

      mountChart(container.querySelector(`[data-user-metric-chart-index="${index}"]`), createUserMetricChartOption(card, chartOptions));
    });
  }

  function filteredDailyUsage() {
    return currentData.dailyUsage.filter((row) => !state.productAreaId || row.productAreaId === state.productAreaId);
  }

  function mountDailyActivityChart(element, option) {
    const chart = mountChart(element, option);

    if (!chart) {
      return null;
    }

    let activeSeriesIndex = null;
    const clearActiveSeries = () => {
      if (activeSeriesIndex === null) {
        return;
      }

      chart.dispatchAction({ type: "downplay", seriesIndex: activeSeriesIndex });
      activeSeriesIndex = null;
    };

    chart.on("mouseover", (params) => {
      const seriesIndex = params.seriesType === "custom"
        ? Number(params.data?.seriesIndex ?? params.value?.[3])
        : params.seriesIndex;

      if ((params.seriesType !== "bar" && params.seriesType !== "custom") || !Number.isFinite(seriesIndex)) {
        return;
      }

      if (activeSeriesIndex === seriesIndex) {
        return;
      }

      clearActiveSeries();
      activeSeriesIndex = seriesIndex;
      chart.dispatchAction({ type: "highlight", seriesIndex: activeSeriesIndex });
    });

    chart.getZr()?.on("globalout", clearActiveSeries);

    return chart;
  }

  function niceCeilValue(value, splitCount = 5) {
    const numericValue = Math.max(Number(value) || 0, 1);
    const rawStep = numericValue / splitCount;
    const stepPower = 10 ** Math.floor(Math.log10(rawStep));
    const normalizedStep = rawStep / stepPower;
    const niceStep = normalizedStep <= 1 ? 1 : normalizedStep <= 2 ? 2 : normalizedStep <= 5 ? 5 : 10;
    const step = niceStep * stepPower;

    return Math.ceil(numericValue / step) * step;
  }

  function layoutDailyActivityEndLabels(labelRows, valueExtent, layout = {}) {
    const valueRange = Math.max(valueExtent.max - valueExtent.min, 1);
    const minValue = valueExtent.min + valueRange * 0.05;
    const maxValue = valueExtent.max - valueRange * 0.05;
    const minGap = valueRange * (layout.minGapRatio || 0.08);
    const sorted = labelRows
      .map((row, index) => ({
        index,
        value: Math.max(minValue, Math.min(maxValue, Number(row.midpoint) || 0))
      }))
      .sort((a, b) => a.value - b.value);
    let previousValue = minValue - minGap;

    sorted.forEach((item) => {
      item.value = Math.max(item.value, previousValue + minGap);
      previousValue = item.value;
    });

    const overflow = Math.max(0, previousValue - maxValue);

    if (overflow) {
      sorted.forEach((item) => {
        item.value -= overflow;
      });
    }

    const underflow = Math.max(0, minValue - (sorted[0]?.value || minValue));

    if (underflow) {
      sorted.forEach((item) => {
        item.value += underflow;
      });
    }

    return sorted.reduce((lookup, item) => {
      lookup[item.index] = Math.max(minValue, Math.min(maxValue, item.value));
      return lookup;
    }, {});
  }

  function dailyActivityColumnLayout(dateCount) {
    const count = Math.max(1, Number(dateCount) || 1);

    if (count <= 10) {
      return { widthRatio: 0.44, maxWidth: 30, minWidth: 1 };
    }

    if (count <= 45) {
      return { widthRatio: 0.62, maxWidth: 24, minWidth: 1 };
    }

    if (count <= 100) {
      return { widthRatio: 0.72, maxWidth: 10, minWidth: 1 };
    }

    return { widthRatio: 0.86, maxWidth: 5, minWidth: 1 };
  }

  function dailyActivityLabelWidth(labelRows) {
    const longestLabelLength = Math.max(...(labelRows || []).map((row) => String(row.name || "").length), 0);

    return Math.min(280, Math.max(132, longestLabelLength * 7 + 12));
  }

  function createDailyActivityConnectorSeries(labelRows, labelDateIndex, valueExtent, columnLayout = {}) {
    const labelValuesByIndex = layoutDailyActivityEndLabels(labelRows, valueExtent);
    const widthRatio = Number(columnLayout.widthRatio) || 0.62;
    const maxWidth = Number(columnLayout.maxWidth) || 24;
    const minWidth = Number(columnLayout.minWidth) || 1;
    const labelWidth = Number(columnLayout.labelWidth) || dailyActivityLabelWidth(labelRows);

    return {
      name: "Product area labels",
      type: "custom",
      coordinateSystem: "cartesian2d",
      animation: false,
      silent: false,
      clip: false,
      tooltip: { show: false },
      data: labelRows.map((row, index) => ({
        name: row.name,
        seriesIndex: row.seriesIndex,
        value: [labelDateIndex, row.midpoint, labelValuesByIndex[index] ?? row.midpoint, row.seriesIndex]
      })),
      renderItem: (params, api) => {
        const row = labelRows[params.dataIndex] || {};
        const barPoint = api.coord([api.value(0), api.value(1)]);
        const labelPoint = api.coord([api.value(0), api.value(2)]);
        const categoryWidth = Math.max(0, Number(api.size([1, 0])?.[0]) || 0);
        const columnWidth = categoryWidth ? Math.max(minWidth, Math.min(maxWidth, categoryWidth * widthRatio)) : maxWidth;
        const barRightX = barPoint[0] + columnWidth / 2;
        const elbowX = barRightX + 14;
        const labelX = barRightX + 28;
        const labelY = labelPoint[1];
        const lineColor = rgbaFromHex(row.color, 0.72);

        return {
          type: "group",
          children: [
            {
              type: "line",
              shape: {
                x1: barRightX,
                y1: barPoint[1],
                x2: elbowX,
                y2: labelY
              },
              style: {
                stroke: lineColor,
                lineWidth: 1.5,
                lineDash: [2, 3]
              }
            },
            {
              type: "line",
              shape: {
                x1: elbowX,
                y1: labelY,
                x2: labelX,
                y2: labelY
              },
              style: {
                stroke: lineColor,
                lineWidth: 1.5,
                lineDash: [2, 3]
              }
            },
            {
              type: "text",
              style: {
                x: labelX + 8,
                y: labelY,
                text: row.name || "",
                fill: readableSeriesLabelColor(row.color),
                font: "500 12px Inter, ui-sans-serif, system-ui, sans-serif",
                align: "left",
                verticalAlign: "middle",
                width: labelWidth
              }
            }
          ]
        };
      },
      z: 6
    };
  }

  function renderDailyChart() {
    const element = document.getElementById("daily-product-area-chart");
    const summary = document.getElementById("daily-activity-summary");
    const rows = filteredDailyUsage();
    const metric = "engagedSeconds";
    const areas = currentData.productAreas.filter((area) => !state.productAreaId || area.id === state.productAreaId);
    const dates = Array.from(new Set(rows.map((row) => row.date))).sort();
    const valuesByAreaDate = new Map();

    rows.forEach((row) => {
      const key = `${row.productAreaId}|${row.date}`;
      valuesByAreaDate.set(key, (valuesByAreaDate.get(key) || 0) + (Number(row[metric]) || 0));
    });

    const valueForAreaDate = (areaId, date) => valuesByAreaDate.get(`${areaId}|${date}`) || 0;
    const totalsByDate = new Map(dates.map((date) => [date, areas.reduce((sum, area) => sum + valueForAreaDate(area.id, date), 0)]));
    const maxDailyTotal = Math.max(...Array.from(totalsByDate.values()), 1);
    const valueExtent = { min: 0, max: niceCeilValue(maxDailyTotal) };
    const labelDateIndex = Math.max(0, dates.reduce((lastIndex, date, index) => (
      (totalsByDate.get(date) || 0) > 0 ? index : lastIndex
    ), -1));
    const columnLayout = dailyActivityColumnLayout(dates.length);

    if (summary) {
      summary.textContent = `Engaged time over ${currentData.periodDays} days, grouped by product area.`;
    }

    if (!rows.some((row) => Number(row[metric]) > 0)) {
      chartUnavailable(element, "No daily activity matches the selected filters.");
      return;
    }

    let labelStackCursor = 0;
    const labelRows = areas
      .map((area, seriesIndex) => {
        const value = valueForAreaDate(area.id, dates[labelDateIndex]);
        const midpoint = labelStackCursor + value / 2;
        labelStackCursor += value;

        if (value <= 0) {
          return null;
        }

        return {
          id: area.id,
          name: area.name,
          color: areaColor(area.id),
          seriesIndex,
          midpoint,
          value
        };
      })
      .filter(Boolean);
    const labelWidth = dailyActivityLabelWidth(labelRows);
    const gridRight = labelRows.length ? Math.min(340, labelWidth + 72) : 28;

    const series = areas.map((area) => ({
      name: area.name,
      type: "bar",
      stack: "activity",
      barWidth: `${Math.round(columnLayout.widthRatio * 100)}%`,
      barMaxWidth: columnLayout.maxWidth,
      barMinWidth: columnLayout.minWidth,
      emphasis: {
        itemStyle: { opacity: 1 }
      },
      itemStyle: {
        color: areaColor(area.id),
        opacity: 0.74
      },
      data: dates.map((date) => {
        return valueForAreaDate(area.id, date);
      })
    }));

    mountDailyActivityChart(element, {
      color: areas.map((area) => areaColor(area.id)),
      animation: false,
      stateAnimation: {
        duration: 260,
        easing: "cubicOut"
      },
      tooltip: analyticsTooltips.echarts({
        trigger: "item",
        confine: true,
        transitionDuration: 0.18,
        formatter(params) {
          const item = Array.isArray(params) ? params[0] : params;

          if (!item || item.seriesType === "custom" || item.value === null || item.value === undefined) {
            return "";
          }

          const date = item.axisValue || dates[item.dataIndex] || "";
          const dayRows = rows.filter((row) => row.date === date);
          const total = totalsByDate.get(date) || 0;
          const topPages = Array.from(new Set(dayRows.flatMap((row) => row.topPages || []))).slice(0, 3);
          const value = metricFormatter(metric, item.value);
          const tooltipRows = [
            { label: item.seriesName, value },
            { label: "Daily total", value: metricFormatter(metric, total) }
          ];

          if (topPages.length) {
            tooltipRows.push({ label: "Top pages", value: topPages.join(", ") });
          }

          return productAreaTooltipMarkup(formatDate(date), tooltipRows);
        }
      }),
      legend: { show: false },
      grid: { top: 8, right: gridRight, bottom: 34, left: 58 },
      xAxis: {
        type: "category",
        data: dates,
        axisTick: { show: false },
        axisLabel: {
          color: tailwindColor("slate-500"),
          hideOverlap: true,
          formatter(value) {
            const date = new Date(`${value}T00:00:00Z`);
            return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric" }).format(date);
          }
        },
        axisLine: { show: true, lineStyle: { color: tailwindColor("slate-300") } },
        splitLine: { show: false }
      },
      yAxis: {
        type: "value",
        min: valueExtent.min,
        max: valueExtent.max,
        axisTick: { show: false },
        axisLabel: {
          color: tailwindColor("slate-500"),
          formatter(value) {
            return helpers.formatDuration(value);
          }
        },
        axisLine: { show: true, lineStyle: { color: tailwindColor("slate-300") } },
        splitLine: { show: false }
      },
      series: series.concat(createDailyActivityConnectorSeries(labelRows, labelDateIndex, valueExtent, { ...columnLayout, labelWidth }))
    });
  }

  function productAreaMixDates() {
    const dates = Array.from(new Set((currentData.dailyUsage || []).map((row) => row.date).filter(Boolean))).sort();

    if (dates.length) {
      return dates;
    }

    return metricTrendDates(metricSeriesPointCount(currentData.periodDays), currentData.periodDays);
  }

  function productAreaDailySeries(areaId, dates) {
    const valuesByDate = new Map();

    (currentData.dailyUsage || []).forEach((row) => {
      if (row.productAreaId !== areaId) {
        return;
      }

      valuesByDate.set(row.date, (valuesByDate.get(row.date) || 0) + (Number(row.engagedSeconds) || 0));
    });

    return dates.map((date) => ({
      date,
      value: valuesByDate.get(date) || 0
    }));
  }

  function buildOtherProductAreaSeries(area, mixRow, dates) {
    const peerSeries = Array.isArray(mixRow?.peerSeries) ? mixRow.peerSeries : [];

    return peerSeries
      .filter((peer) => Array.isArray(peer?.dailySeries))
      .map((peer) => {
        const valuesByDate = new Map(
          peer.dailySeries.map((point) => [point?.date, point?.value])
        );

        return {
          userId: peer.userId || peer.id,
          userName: peer.userName || peer.name,
          dailySeries: dates.map((date) => ({
            date,
            value: valuesByDate.has(date) ? valuesByDate.get(date) : null
          }))
        };
      });
  }

  function createProductAreaMixChartOption(area, mixRow, dates) {
    const dailySeries = productAreaDailySeries(area.id, dates);
    const currentValues = seriesActualValues(dailySeries);
    const peerSeries = buildOtherProductAreaSeries(area, mixRow, dates);
    const dynamics = buildMetricDynamicsSeries({
      currentSeries: dailySeries,
      peerSeriesList: peerSeries,
      metricType: "engaged_time",
      selectedPeriodDays: currentData.periodDays,
      minPeerCount: 5,
      showPeers: false,
      currentEntityId: currentData?.selectedUser?.id
    });
    const currentTrendSeries = dynamics.currentStraightTrendSeries || dynamics.currentTrend || [];
    const approximatedActualSeries = currentTrendSeries.length
      ? currentTrendSeries
      : dynamics.actualSeries || dynamics.current || currentValues;
    const benchmarkTrendSeries = dynamics.benchmarkStraightTrendSeries || dynamics.benchmark || [];
    const currentLineColor = chartTheme.colors.primary;
    const benchmarkLineColor = chartTheme.colors.warning;
    const yAxisBounds = getMetricDynamicsAxisBounds([
      approximatedActualSeries,
      benchmarkTrendSeries
    ], { paddingRatio: 0.14 });

    return {
      animation: false,
      tooltip: analyticsTooltips.echarts({
        trigger: "axis",
        appendTo: "body",
        confine: false,
        axisPointer: {
          type: "none"
        },
        formatter() {
          const deltaValue = Math.round(Number(mixRow?.deltaPct) || 0);
          const tooltipRows = [
            { label: "This user total", value: helpers.formatDuration(Number(mixRow?.userEngagedSeconds) || 0), marker: { color: currentLineColor, type: "line" } },
            { label: "Peer median total", value: helpers.formatDuration(Number(mixRow?.peerMedianEngagedSeconds) || 0) },
            { label: "Difference vs others", value: helpers.formatDelta(deltaValue, "percent") }
          ];

          return productAreaTooltipMarkup(area.name, tooltipRows);
        }
      }),
      grid: {
        left: 0,
        right: 0,
        top: 6,
        bottom: 0
      },
      xAxis: {
        type: "category",
        show: false,
        boundaryGap: false,
        data: dates
      },
      yAxis: {
        type: "value",
        show: false,
        min: yAxisBounds.min,
        max: yAxisBounds.max
      },
      series: []
        .concat(benchmarkTrendSeries.length ? [{
          name: "Other users trend",
          type: "line",
          cursor: "default",
          data: benchmarkTrendSeries,
          smooth: false,
          symbol: "none",
          lineStyle: {
            color: benchmarkLineColor,
            type: [6, 4],
            width: 1.7,
            opacity: 0.9
          },
          emphasis: {
            disabled: true
          },
          z: 3
        }] : [])
        .concat([
          {
            name: "This user trend",
            type: "line",
            cursor: "default",
            data: approximatedActualSeries,
            smooth: true,
            symbol: "none",
            lineStyle: {
              color: currentLineColor,
              width: 2.1
            },
            areaStyle: {
              color: rgbaFromHex(currentLineColor, 0.1)
            },
            emphasis: {
              disabled: true
            },
            z: 5
          }
        ])
    };
  }

  function mountProductAreaMixChart(element, option) {
    const chart = mountChart(element, option);

    if (!chart || typeof chart.getZr !== "function") {
      return chart;
    }

    const zr = chart.getZr();
    const resetCursor = () => zr.setCursorStyle("default");

    zr.on("mousemove", resetCursor);
    zr.on("mouseover", resetCursor);
    chart.on("mouseover", resetCursor);

    return chart;
  }

  function renderProductAreaMix() {
    const container = document.getElementById("product-area-mix");

    if (!container) {
      return;
    }

    const rowsByArea = new Map((currentData.productAreaMix || []).map((row) => [row.productAreaId, row]));
    const areas = (currentData.productAreas || [])
      .map((area, index) => ({
        ...area,
        __order: index,
        __hasUsage: (Number(rowsByArea.get(area.id)?.userEngagedSeconds ?? rowsByArea.get(area.id)?.userSharePct) || 0) > 0
      }))
      .sort((a, b) => Number(b.__hasUsage) - Number(a.__hasUsage) || a.__order - b.__order);

    if (!areas.length) {
      container.innerHTML = `<div class="user-detail-empty">No product area mix data matches the selected filter.</div>`;
      return;
    }

    const dates = productAreaMixDates();
    const renderProductAreaMixDelta = (row, area) => {
      const deltaValue = Math.round(Number(row.deltaPct) || 0);
      const formattedDelta = helpers.formatDelta(deltaValue, "percent");
      const tooltipId = `product-area-mix-delta-tooltip-${String(area.id || area.name || "").replace(/[^a-z0-9_-]+/gi, "-").toLowerCase()}`;
      const tooltipRows = [
        { label: "This user total", value: helpers.formatDuration(row.userEngagedSeconds) },
        { label: "Other users median", value: helpers.formatDuration(row.peerMedianEngagedSeconds) },
        { label: "Difference vs others", value: formattedDelta }
      ];

      return `
        <span class="product-area-mix-cell__delta metric-header-tooltip ${deltaClass(deltaValue)}" data-tooltip-kind="product-area" tabindex="0" aria-label="${escapeHtml(`${area.name}. ${productAreaTooltipText(tooltipRows)}`)}" aria-describedby="${escapeHtml(tooltipId)}">
          ${escapeHtml(formattedDelta)} vs others
          <span id="${escapeHtml(tooltipId)}" class="metric-header-tooltip__content" role="tooltip">${productAreaTooltipMarkup(area.name, tooltipRows)}</span>
        </span>
      `;
    };

    container.innerHTML = `
      <div class="overflow-x-auto">
        <table class="product-area-mix-table w-full text-left" style="--product-area-count:${areas.length};">
          <thead class="border-b border-gray-300 bg-white text-slate-600">
            <tr>
              ${areas.map((area, index) => `
                <th scope="col" class="py-3 ${index === 0 ? "pl-0" : "pl-3"} pr-3 align-bottom text-[14px] font-semibold leading-tight text-slate-600">
                  ${tableHeaderTooltip(area.name, `Daily engaged time in ${area.name}, with this user's difference from other users.`, `product-area-mix-tooltip-${domIdFragment(area.id || area.name || index)}`, index === areas.length - 1 ? { align: "end" } : {})}
                </th>
              `).join("")}
            </tr>
          </thead>
          <tbody class="text-slate-700">
            <tr>
              ${areas.map((area, index) => {
                const row = rowsByArea.get(area.id) || {
                  productAreaId: area.id,
                  productAreaName: area.name,
                  userEngagedSeconds: 0,
                  peerMedianEngagedSeconds: 0,
                  deltaPct: 0,
                  userSharePct: 0,
                  peerMedianSharePct: 0,
                  deltaPp: 0
                };

                return `
                  <td class="border-b border-slate-100 py-3 ${index === 0 ? "pl-0" : "pl-3"} pr-3 align-top">
                      <div class="product-area-mix-cell">
                        <div class="product-area-mix-cell__legend">
                          <strong>${escapeHtml(helpers.formatDuration(row.userEngagedSeconds))}</strong>
                          ${renderProductAreaMixDelta(row, area)}
                        </div>
                      <div
                        class="product-area-mix-cell__chart"
                        data-product-area-mix-chart-index="${index}"
                        role="img"
                        aria-label="${escapeHtml(`${area.name} daily engaged time and trend`)}"></div>
                    </div>
                  </td>
                `;
              }).join("")}
            </tr>
          </tbody>
        </table>
      </div>
    `;

    areas.forEach((area, index) => {
      const row = rowsByArea.get(area.id) || {
        productAreaId: area.id,
        productAreaName: area.name,
        userEngagedSeconds: 0,
        peerMedianEngagedSeconds: 0,
        deltaPct: 0,
        userSharePct: 0,
        peerMedianSharePct: 0,
        deltaPp: 0
      };

      mountProductAreaMixChart(
        container.querySelector(`[data-product-area-mix-chart-index="${index}"]`),
        createProductAreaMixChartOption(area, row, dates)
      );
    });
  }

  function createProductAreaMix2DailyChartOption(area, dates) {
    const values = productAreaDailySeries(area.id, dates).map((point) => Math.max(0, Number(point.value) || 0));
    const maxValue = Math.max(...values, 1);
    const color = areaColor(area.id);

    return {
      animation: false,
      grid: {
        left: 0,
        right: 0,
        top: 2,
        bottom: 2
      },
      tooltip: analyticsTooltips.echarts({
        trigger: "axis",
        appendTo: "body",
        confine: false,
        axisPointer: {
          type: "none"
        },
        formatter(params) {
          const point = Array.isArray(params) ? params[0] : params;
          const value = Number(point?.value) || 0;
          const date = point?.axisValueLabel || point?.name || "";
          const tooltipRows = [
            { label: area.name, value: helpers.formatDuration(value) }
          ];

          return productAreaTooltipMarkup(formatDate(date), tooltipRows);
        }
      }),
      xAxis: {
        type: "category",
        show: true,
        boundaryGap: true,
        data: dates,
        axisLabel: { show: false },
        axisTick: { show: false },
        axisLine: {
          show: true,
          lineStyle: {
            color: tailwindColor("slate-200"),
            width: 1
          }
        },
        splitLine: { show: false }
      },
      yAxis: {
        type: "value",
        show: false,
        min: 0,
        max: maxValue * 1.08
      },
      series: [{
        name: area.name,
        type: "bar",
        data: values,
        barCategoryGap: "18%",
        barMaxWidth: 9,
        barMinWidth: 2,
        clip: true,
        itemStyle: {
          color,
          borderRadius: [2, 2, 0, 0],
          opacity: 0.78
        },
        emphasis: {
          disabled: true
        }
      }]
    };
  }

  function productAreaMix2ShareDeltaValue(row) {
    const sharePct = clampPct(Number(row.userSharePct) || 0);
    const peerMedianSharePct = clampPct(Number(row.peerMedianSharePct) || 0);
    const rawDeltaPp = Number(row.deltaPp);

    return Number.isFinite(rawDeltaPp) ? rawDeltaPp : sharePct - peerMedianSharePct;
  }

  function productAreaMix2ShareCell(row, area) {
    const sharePct = clampPct(Number(row.userSharePct) || 0);
    const shareLabel = `${Math.round(sharePct)}%`;
    const peerMedianSharePct = clampPct(Number(row.peerMedianSharePct) || 0);
    const peerMedianShareLabel = `${Math.round(peerMedianSharePct)}%`;
    const roundedDeltaPp = Math.round(productAreaMix2ShareDeltaValue(row));
    const formattedDelta = helpers.formatDelta(roundedDeltaPp, "pp");
    const tooltipId = `product-area-mix-2-share-tooltip-${String(area.id || area.name || "").replace(/[^a-z0-9_-]+/gi, "-").toLowerCase()}`;
    const tooltipRows = [
      { label: "Share of user time", value: shareLabel },
      { label: "Peer median share", value: peerMedianShareLabel },
      { label: "Difference vs peer median", value: formattedDelta },
      { label: "Engaged time", value: helpers.formatDuration(row.userEngagedSeconds) }
    ];

    return `
      <span
        class="product-area-mix-2-share metric-header-tooltip"
        data-tooltip-kind="product-area"
        style="--product-area-mix-2-color:${areaColor(area.id)};--product-area-mix-2-user-width:${sharePct.toFixed(2)}%;--product-area-mix-2-median-left:${peerMedianSharePct.toFixed(2)}%;"
        tabindex="0"
        aria-label="${escapeHtml(`${area.name}. ${productAreaTooltipText(tooltipRows)}`)}"
        aria-describedby="${escapeHtml(tooltipId)}">
        <span class="product-area-mix-2-share__value">${escapeHtml(shareLabel)}</span>
        <span class="product-area-mix-2-bar" aria-hidden="true">
          <span class="product-area-mix-2-bar__fill"></span>
          <span class="product-area-mix-2-bar__median"></span>
        </span>
        <span id="${escapeHtml(tooltipId)}" class="metric-header-tooltip__content" role="tooltip">
          ${productAreaTooltipMarkup(area.name, tooltipRows)}
        </span>
      </span>
    `;
  }

  function productAreaMix2DeltaMarkup(area, deltaValue, unit, maxAbsDelta, tooltipIdPrefix, tooltipRows) {
    const roundedDelta = Math.round(Number(deltaValue) || 0);
    const direction = deltaDirection(roundedDelta);
    const barWidth = roundedDelta === 0 ? 6 : Math.max(4, Math.round((Math.abs(roundedDelta) / Math.max(maxAbsDelta, 1)) * 48));
    const formattedDelta = helpers.formatDelta(roundedDelta, unit);
    const tooltipId = `${tooltipIdPrefix}-${String(area.id || area.name || "").replace(/[^a-z0-9_-]+/gi, "-").toLowerCase()}`;

    return `
      <div
        class="product-area-mix-2-delta metric-header-tooltip"
        data-change-direction="${direction}"
        data-tooltip-kind="product-area"
        style="--product-area-mix-2-delta-bar-width:${barWidth}px;"
        tabindex="0"
        aria-label="${escapeHtml(`${area.name}. ${productAreaTooltipText(tooltipRows)}`)}"
        aria-describedby="${escapeHtml(tooltipId)}">
        <span class="product-area-mix-2-delta__plot">
          <span class="product-area-mix-2-delta__bar product-area-mix-2-delta__bar--${direction}"></span>
        </span>
        <span class="product-area-mix-2-delta__label ${deltaTextClass(roundedDelta)}">${escapeHtml(formattedDelta)}</span>
        <span id="${escapeHtml(tooltipId)}" class="metric-header-tooltip__content" role="tooltip">
          ${productAreaTooltipMarkup(area.name, tooltipRows)}
        </span>
      </div>
    `;
  }

  function productAreaMix2ShareDelta(row, area, maxAbsDelta) {
    const sharePct = clampPct(Number(row.userSharePct) || 0);
    const peerMedianSharePct = clampPct(Number(row.peerMedianSharePct) || 0);
    const deltaValue = Math.round(productAreaMix2ShareDeltaValue(row));
    const formattedDelta = helpers.formatDelta(deltaValue, "pp");
    const tooltipRows = [
      { label: "This user share", value: `${Math.round(sharePct)}%` },
      { label: "Peer median share", value: `${Math.round(peerMedianSharePct)}%` },
      { label: "Difference vs peer median", value: formattedDelta }
    ];

    return productAreaMix2DeltaMarkup(area, deltaValue, "pp", maxAbsDelta, "product-area-mix-2-share-delta-tooltip", tooltipRows);
  }

  function productAreaMix2TotalCell(row, area, maxEngagedSeconds) {
    const total = Math.max(0, Number(row.userEngagedSeconds) || 0);
    const median = Math.max(0, Number(row.peerMedianEngagedSeconds) || 0);
    const userWidth = clampPct((total / Math.max(maxEngagedSeconds, 1)) * 100);
    const medianLeft = clampPct((median / Math.max(maxEngagedSeconds, 1)) * 100);
    const tooltipId = `product-area-mix-2-total-tooltip-${String(area.id || area.name || "").replace(/[^a-z0-9_-]+/gi, "-").toLowerCase()}`;
    const tooltipRows = [
      { label: "This user", value: helpers.formatDuration(total) },
      { label: "Peer median", value: helpers.formatDuration(median) }
    ];

    return `
      <div class="product-area-mix-2-value">
        <span class="product-area-mix-2-value__label">${escapeHtml(helpers.formatDuration(total))}</span>
        <span
          class="product-area-mix-2-bar metric-header-tooltip"
          data-tooltip-kind="product-area"
          style="--product-area-mix-2-color:${areaColor(area.id)};--product-area-mix-2-user-width:${userWidth.toFixed(2)}%;--product-area-mix-2-median-left:${medianLeft.toFixed(2)}%;"
          tabindex="0"
          aria-label="${escapeHtml(`${area.name}. ${productAreaTooltipText(tooltipRows)}`)}"
          aria-describedby="${escapeHtml(tooltipId)}">
          <span class="product-area-mix-2-bar__fill"></span>
          <span class="product-area-mix-2-bar__median" aria-hidden="true"></span>
          <span id="${escapeHtml(tooltipId)}" class="metric-header-tooltip__content" role="tooltip">
            ${productAreaTooltipMarkup(area.name, tooltipRows)}
          </span>
        </span>
      </div>
    `;
  }

  function productAreaMix2Delta(row, area, maxAbsDelta) {
    const deltaValue = Math.round(Number(row.deltaPct) || 0);
    const formattedDelta = helpers.formatDelta(deltaValue, "percent");
    const tooltipRows = [
      { label: "This user total", value: helpers.formatDuration(row.userEngagedSeconds) },
      { label: "Peer median", value: helpers.formatDuration(row.peerMedianEngagedSeconds) },
      { label: "Difference vs peer median", value: formattedDelta }
    ];

    return productAreaMix2DeltaMarkup(area, deltaValue, "percent", maxAbsDelta, "product-area-mix-2-delta-tooltip", tooltipRows);
  }

  function renderProductAreaMix2() {
    const container = document.getElementById("product-area-mix-2");

    if (!container) {
      return;
    }

    const rowsByArea = new Map((currentData.productAreaMix || []).map((row) => [row.productAreaId, row]));
    const rows = (currentData.productAreas || [])
      .map((area, index) => ({
        area,
        row: rowsByArea.get(area.id) || {
          productAreaId: area.id,
          productAreaName: area.name,
          userEngagedSeconds: 0,
          peerMedianEngagedSeconds: 0,
          deltaPct: 0,
          userSharePct: 0,
          peerMedianSharePct: 0,
          deltaPp: 0
        },
        __order: index
      }))
      .sort((a, b) => (Number(b.row.userEngagedSeconds) || 0) - (Number(a.row.userEngagedSeconds) || 0) || a.__order - b.__order);

    if (!rows.length) {
      container.innerHTML = `<div class="user-detail-empty">No product area mix data matches the selected filter.</div>`;
      return;
    }

    const dates = productAreaMixDates();
    const maxEngagedSeconds = Math.max(
      ...rows.flatMap(({ row }) => [
        Number(row.userEngagedSeconds) || 0,
        Number(row.peerMedianEngagedSeconds) || 0
      ]),
      1
    );
    const maxAbsDelta = Math.max(...rows.map(({ row }) => Math.abs(Number(row.deltaPct) || 0)), 1);
    const maxAbsShareDelta = Math.max(...rows.map(({ row }) => Math.abs(Math.round(productAreaMix2ShareDeltaValue(row)))), 1);

    container.innerHTML = `
      <div class="overflow-x-auto">
        <table class="product-area-mix-2-table w-full text-left">
          <thead class="border-b border-gray-300 bg-white text-slate-600">
            <tr>
              <th scope="col" class="w-[16%] py-3 pl-0 pr-5 font-normal">${tableHeaderTooltip("Product area", "Product area included in this user's activity comparison.", "product-area-mix-2-tooltip-area")}</th>
              <th scope="col" class="w-[20%] py-3 pr-5 font-normal">${tableHeaderTooltip("Share of user time", "Share of this user's engaged time spent in the product area.", "product-area-mix-2-tooltip-share")}</th>
              <th scope="col" class="w-[14%] py-3 pr-5 font-normal">${tableHeaderTooltip("Share vs peer median", "Difference between this user's area time share and the peer median.", "product-area-mix-2-tooltip-share-peer")}</th>
              <th scope="col" class="w-[20%] py-3 pr-5 font-normal">${tableHeaderTooltip("Total engaged time", "Total active time this user spent in the product area.", "product-area-mix-2-tooltip-engaged")}</th>
              <th scope="col" class="w-[14%] py-3 pr-5 font-normal">${tableHeaderTooltip("Time vs peer median", "Difference between this user's engaged time and the peer median for the area.", "product-area-mix-2-tooltip-time-peer")}</th>
              <th scope="col" class="w-[16%] py-3 pr-0 font-normal">${tableHeaderTooltip("Daily usage", "Daily engaged time trend for this user in the product area.", "product-area-mix-2-tooltip-daily", { align: "end" })}</th>
            </tr>
          </thead>
          <tbody class="text-slate-700">
            ${rows.map(({ area, row }, index) => `
              <tr class="hover:bg-slate-50">
                <td class="py-3.5 pl-0 pr-5 align-middle">
                  <span class="product-area-mix-2-name">
                    <span class="companies-product-dot" style="background:${areaColor(area.id)}"></span>
                    <span>${escapeHtml(area.name)}</span>
                  </span>
                </td>
                <td class="py-3.5 pr-5 align-middle">${productAreaMix2ShareCell(row, area)}</td>
                <td class="product-area-mix-2-delta-cell py-3.5 pr-5 align-middle">${productAreaMix2ShareDelta(row, area, maxAbsShareDelta)}</td>
                <td class="py-3.5 pr-5 align-middle">${productAreaMix2TotalCell(row, area, maxEngagedSeconds)}</td>
                <td class="product-area-mix-2-delta-cell py-3.5 pr-5 align-middle">${productAreaMix2Delta(row, area, maxAbsDelta)}</td>
                <td class="py-2.5 pr-0 align-middle">
                  <div
                    class="product-area-mix-2-daily-chart"
                    data-product-area-mix-2-chart-index="${index}"
                    role="img"
                    aria-label="${escapeHtml(`${area.name} daily engaged time`)}"></div>
                </td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      </div>
    `;

    rows.forEach(({ area }, index) => {
      mountChart(
        container.querySelector(`[data-product-area-mix-2-chart-index="${index}"]`),
        createProductAreaMix2DailyChartOption(area, dates)
      );
    });
  }

  function medianPeerRow(rows) {
    return {
      userId: "company_median",
      name: "Company median",
      email: "",
      role: "-",
      status: "healthy",
      engagedSeconds: helpers.median(rows.map((row) => row.engagedSeconds)),
      activeDays: Math.round(helpers.median(rows.map((row) => row.activeDays))),
      consistency: helpers.median(rows.map((row) => row.consistency)),
      intensitySecondsPerActiveDay: helpers.median(rows.map((row) => row.intensitySecondsPerActiveDay)),
      pagesUsed: Math.round(helpers.median(rows.map((row) => row.pagesUsed))),
      topArea: "Median",
      interactionRate: helpers.median(rows.map((row) => row.interactionRate)),
      rank: null,
      isMedian: true
    };
  }

  function clampPct(value) {
    return Math.max(0, Math.min(100, Number(value) || 0));
  }

  function formatValueByType(value, valueType) {
    if (valueType === "duration") {
      return helpers.formatDuration(value);
    }

    if (valueType === "percent") {
      return helpers.formatPercent(value);
    }

    return helpers.formatNumber(value);
  }

  function metricBarValue(valueLabel, barValue, label) {
    const barWidth = Math.max(4, Math.round((clampPct(barValue) / 100) * 72));

    return `
      <div class="pages-value-bar" style="--pages-value-bar-width: ${barWidth}px;" aria-label="${escapeHtml(`${label} ${valueLabel}`)}">
        <span class="pages-value-bar__bar"></span>
        <span class="pages-value-bar__label">${escapeHtml(valueLabel)}</span>
      </div>
    `;
  }

  function deltaDirection(deltaValue, invert = false) {
    const value = Number(deltaValue) || 0;

    if (value === 0) {
      return "neutral";
    }

    const isPositive = invert ? value < 0 : value > 0;

    return isPositive ? "positive" : "negative";
  }

  function deltaTextClass(deltaValue, invert = false) {
    const direction = deltaDirection(deltaValue, invert);

    if (direction === "positive") {
      return "text-green-700";
    }

    if (direction === "negative") {
      return "text-red-600";
    }

    return "text-slate-700";
  }

  function previousPeriodValue(currentValue, deltaValue, unit) {
    const current = Number(currentValue) || 0;
    const delta = Number(deltaValue) || 0;

    if (unit === "pp") {
      return current - delta;
    }

    const divisor = 1 + delta / 100;
    return divisor > 0 ? current / divisor : 0;
  }

  function formatPeriodMetricValue(value, valueType) {
    const numericValue = Number(value) || 0;

    if (valueType === "percent") {
      return `${numericValue.toFixed(1)}%`;
    }

    if (valueType === "duration") {
      return helpers.formatDuration(numericValue);
    }

    return helpers.formatNumber(Math.round(numericValue));
  }

  function formatPeriodDelta(deltaValue, unit) {
    const numericValue = Number(deltaValue) || 0;
    const prefix = numericValue > 0 ? "+" : "";

    if (unit === "pp") {
      return `${prefix}${numericValue.toFixed(1)} pp`;
    }

    const rounded = Math.round(numericValue * 10) / 10;
    return `${prefix}${rounded}%`;
  }

  function renderSplitChangeDelta(currentValue, valueType, deltaValue, unit, maxAbsDelta, label, previousValue, deltaLabel = "", comparisonAvailable = true, invert = false) {
    const isNew = comparisonAvailable !== false && deltaLabel === "New";
    const direction = isNew ? (invert ? "negative" : "positive") : deltaDirection(deltaValue, invert);
    const trackWidth = direction === "negative" ? 17 : 36;
    const barWidth = isNew
      ? trackWidth
      : Number(deltaValue) === 0
        ? 6
        : Math.max(4, Math.round((Math.abs(Number(deltaValue) || 0) / Math.max(maxAbsDelta, 1)) * trackWidth));
    const formattedDelta = helpers.formatDelta(deltaValue, unit === "pp" ? "pp" : "percent");
    const tooltipId = `peer-comparison-period-change-tooltip-${peerComparisonPeriodChangeTooltipId}`;
    const hasExplicitPrevious = previousValue !== null && previousValue !== undefined && Number.isFinite(Number(previousValue));
    const resolvedPreviousValue = hasExplicitPrevious
      ? Number(previousValue)
      : deltaLabel === "New"
        ? 0
        : previousPeriodValue(currentValue, deltaValue, unit);
    const changeLabel = resolvedPreviousValue === 0 && Number(currentValue) > 0 ? "New" : formatPeriodDelta(deltaValue, unit);
    const visibleDelta = comparisonAvailable === false ? "n/a" : isNew ? "New" : formattedDelta;
    const tooltipRows = comparisonAvailable === false
      ? [
        { label: "Current period", value: formatPeriodMetricValue(currentValue, valueType) },
        { label: "Previous period", value: "No data" },
        { label: "Change", value: "n/a" }
      ]
      : [
        { label: "Current period", value: formatPeriodMetricValue(currentValue, valueType) },
        { label: "Previous period", value: formatPeriodMetricValue(resolvedPreviousValue, valueType) },
        { label: "Change", value: changeLabel }
      ];

    peerComparisonPeriodChangeTooltipId += 1;

    return `
      <div class="pages-change-delta metric-header-tooltip" data-change-direction="${direction}" style="--pages-change-bar-width: ${barWidth}px;" tabindex="0" aria-label="${escapeHtml(`${label}. ${analyticsTooltips.text(tooltipRows)}`)}" aria-describedby="${escapeHtml(tooltipId)}">
        <span class="pages-change-delta__plot">
          <span class="pages-change-delta__bar pages-change-delta__bar--${direction}"></span>
        </span>
        <span class="pages-change-delta__label ${direction === "positive" ? "text-green-700" : direction === "negative" ? "text-red-600" : "text-slate-700"}">${escapeHtml(visibleDelta)}</span>
        <span id="${escapeHtml(tooltipId)}" class="metric-header-tooltip__content" role="tooltip">
          ${analyticsTooltips.render({ rows: tooltipRows })}
        </span>
      </div>
    `;
  }

  function renderMetricCell(row, metric, maxValues, maxAbsDelta) {
    const value = Number(row[metric.key]) || 0;
    const maxValue = Math.max(maxValues[metric.key] || 1, 1);
    const valueLabel = formatValueByType(value, metric.valueType);
    const barValue = metric.barMode === "percent" ? value : (value / maxValue) * 100;
    const deltaValue = Number(row[metric.deltaKey]) || 0;

    return `
      <td class="pages-split-change-cell py-3.5 pr-6 align-middle" data-split-metric="${escapeHtml(metric.key)}">
        <div class="pages-split-change-group">
          <div class="pages-metric-value">${metricBarValue(valueLabel, barValue, metric.label)}</div>
          ${renderSplitChangeDelta(value, metric.valueType, deltaValue, metric.deltaUnit, maxAbsDelta, metric.label, row[metric.previousKey], row[metric.deltaLabelKey], row.comparisonAvailable !== false && row.comparison_available !== false)}
        </div>
      </td>
    `;
  }

  function tableMaxValues(rows, metrics) {
    return metrics.reduce((lookup, metric) => {
      lookup[metric.key] = Math.max(...rows.map((row) => Number(row[metric.key]) || 0), 1);
      return lookup;
    }, {});
  }

  function tableDeltaMaxValues(rows, metrics) {
    return metrics.reduce((lookup, metric) => {
      lookup[metric.key] = Math.max(...rows.map((row) => Math.abs(Number(row[metric.deltaKey]) || 0)), 1);
      return lookup;
    }, {});
  }

  function productAreaByName(areaName) {
    return (currentData?.productAreas || []).find((area) => area.name === areaName || area.id === areaName) || null;
  }

  function productAreaDot(areaName, explicitColor = "") {
    const area = productAreaByName(areaName);

    return `<span class="companies-product-dot" style="background:${escapeHtml(areaColor(area?.id || areaName, explicitColor))}"></span>`;
  }

  function productAreaCell(areaName, explicitColor = "") {
    return `<span class="inline-flex items-center gap-2 whitespace-nowrap">${productAreaDot(areaName, explicitColor)}<span>${escapeHtml(areaName || "-")}</span></span>`;
  }

  function recommendedActionRelatedCell(row) {
    const areaName = row.relatedProductAreaName || "";
    const label = row.relatedLabel || (row.relatedPageName && areaName ? `${row.relatedPageName} \u00b7 ${areaName}` : row.relatedPageName || areaName || "Overall");

    if (!areaName) {
      return `<span class="whitespace-nowrap text-slate-600">${escapeHtml(label)}</span>`;
    }

    const area = productAreaByName(areaName);
    const color = row.relatedProductAreaColor ? tailwindColor(row.relatedProductAreaColor) : areaColor(area?.id || areaName);

    return `
      <span class="inline-flex items-center gap-2 whitespace-nowrap text-slate-600">
        <span class="companies-product-dot" style="background:${escapeHtml(color)}"></span>
        <span>${escapeHtml(label)}</span>
      </span>
    `;
  }

  function recommendedActionMatchesProductArea(row) {
    if (!state.productAreaId || !row.relatedProductAreaName) {
      return true;
    }

    const selectedArea = productAreaByName(state.productAreaId);

    return row.relatedProductAreaName === selectedArea?.name || row.relatedProductAreaName === selectedArea?.id;
  }

  function areaCoverageCellUsed(cell) {
    return (Number(cell.engagedSeconds) || 0) >= areaUsedEngagedSecondsThreshold ||
      (Number(cell.visits) || 0) >= areaUsedVisitsThreshold;
  }

  function adoptionCellRelativeActivityPct(cell, maxEngagedSeconds) {
    const engagedSeconds = Math.max(0, Number(cell.engagedSeconds) || 0);
    const relativePct = Math.round((engagedSeconds / Math.max(Number(maxEngagedSeconds) || 1, 1)) * 100);

    return engagedSeconds > 0 ? Math.max(1, relativePct) : 0;
  }

  const adoptionCellIntensityGrades = [
    { maxPct: 20, label: "Very low", opacity: 0.24 },
    { maxPct: 40, label: "Low", opacity: 0.36 },
    { maxPct: 60, label: "Moderate", opacity: 0.5 },
    { maxPct: 80, label: "High", opacity: 0.63 },
    { maxPct: Infinity, label: "Very high", opacity: 0.76 }
  ];

  function adoptionCellIntensityGrade(relativeActivityPct) {
    const activityPct = clampPct(relativeActivityPct);

    return adoptionCellIntensityGrades.find((grade) => activityPct <= grade.maxPct) ||
      adoptionCellIntensityGrades[adoptionCellIntensityGrades.length - 1];
  }

  function adoptionCellUsageLabel(relativeActivityPct) {
    const activityPct = clampPct(relativeActivityPct);

    return activityPct <= 0 ? "None" : adoptionCellIntensityGrade(activityPct).label;
  }

  function adoptionCellColorOpacity(relativeActivityPct) {
    return adoptionCellIntensityGrade(relativeActivityPct).opacity;
  }

  function adoptionCellTooltip(cell, row, maxEngagedSeconds) {
    const tooltipId = `peer-comparison-adoption-cell-tooltip-${peerComparisonAdoptionCellTooltipId}`;
    const name = row.name || "User";
    const areaName = cell.productAreaName || cell.productAreaId || "Area";
    const used = areaCoverageCellUsed(cell);
    const relativeActivityPct = adoptionCellRelativeActivityPct(cell, maxEngagedSeconds);
    const usageLabel = used && relativeActivityPct <= 0 ? adoptionCellIntensityGrade(1).label : adoptionCellUsageLabel(relativeActivityPct);
    const relativeActivityLabel = helpers.formatPercent(relativeActivityPct);
    const tooltipRows = [
      { label: "Area", value: areaName },
      { label: "Relative activity", value: relativeActivityLabel },
      { label: "Usage intensity", value: usageLabel },
      { label: "Engaged time", value: helpers.formatDuration(cell.engagedSeconds) },
      { label: "Visits", value: helpers.formatNumber(cell.visits) },
      { label: "Pages/features", value: helpers.formatNumber(cell.pagesUsed) }
    ];

    peerComparisonAdoptionCellTooltipId += 1;

    return {
      tooltipId,
      tooltipText: `${name}. ${used ? "Used during selected period." : "Not used yet."} ${analyticsTooltips.text(tooltipRows)}`,
      tooltipHtml: analyticsTooltips.render({ title: name, rows: tooltipRows })
    };
  }

  function adoptionMatrixCell(cell, row, maxEngagedSeconds) {
    const tooltip = adoptionCellTooltip(cell, row, maxEngagedSeconds);
    const used = areaCoverageCellUsed(cell);
    const intensity = adoptionCellColorOpacity(adoptionCellRelativeActivityPct(cell, maxEngagedSeconds));

    return `
      <span
        class="companies-adoption-cell metric-header-tooltip"
        data-tooltip-kind="adoption-cell"
        data-used="${String(used)}"
        ${used ? `style="--area-bg-color:${rgbaFromHex(areaColor(cell.productAreaId), intensity)};"` : ""}
        tabindex="0"
        aria-label="${escapeHtml(tooltip.tooltipText)}"
        aria-describedby="${escapeHtml(tooltip.tooltipId)}">
        <span id="${escapeHtml(tooltip.tooltipId)}" class="metric-header-tooltip__content" role="tooltip">${tooltip.tooltipHtml}</span>
      </span>
    `;
  }

  function adoptionMatrixCellGroup(row, maxEngagedSeconds) {
    const areas = currentData?.productAreas || [];
    const cellsByArea = new Map((row.productAreaAdoption || []).map((cell) => [cell.productAreaId || cell.productAreaName, cell]));

    return `
      <div class="companies-adoption-matrix" style="--company-users-area-count: ${areas.length || 1};" aria-label="${escapeHtml(`${row.name || "User"} areas used`)}">
        ${areas
          .map((area) => adoptionMatrixCell(cellsByArea.get(area.id) || cellsByArea.get(area.name) || {
            productAreaId: area.id,
            productAreaName: area.name,
            engagedSeconds: 0,
            visits: 0,
            pagesUsed: 0
          }, row, maxEngagedSeconds))
          .join("")}
      </div>
    `;
  }

  function syncSplitChangeValueWidths(root) {
    if (!root) {
      return;
    }

    const cells = Array.from(root.querySelectorAll("[data-split-metric]"));
    const maxWidthByMetric = new Map();

    cells.forEach((cell) => {
      cell.style.removeProperty("--pages-split-value-width");
    });

    cells.forEach((cell) => {
      const metricKey = cell.dataset.splitMetric;
      const valueElement = cell.querySelector(".pages-metric-value");

      if (!metricKey || !valueElement) {
        return;
      }

      const width = Math.ceil(valueElement.getBoundingClientRect().width);
      const currentWidth = maxWidthByMetric.get(metricKey) || 0;

      maxWidthByMetric.set(metricKey, Math.max(currentWidth, width));
    });

    cells.forEach((cell) => {
      const metricKey = cell.dataset.splitMetric;
      const width = maxWidthByMetric.get(metricKey);

      if (width) {
        cell.style.setProperty("--pages-split-value-width", `${width}px`);
      }
    });
  }

  function syncAllSplitChangeValueWidths() {
    syncSplitChangeValueWidths(document.getElementById("peer-comparison-body"));
    syncSplitChangeValueWidths(document.getElementById("pages-used-body"));
  }

  function scheduleSplitChangeValueWidthSync() {
    if (splitChangeValueWidthSyncFrame) {
      return;
    }

    const requestFrame = globalScope.requestAnimationFrame || ((callback) => globalScope.setTimeout(callback, 0));

    splitChangeValueWidthSyncFrame = requestFrame(() => {
      splitChangeValueWidthSyncFrame = 0;
      syncAllSplitChangeValueWidths();
    });
  }

  function mountStickyTableHeader(table) {
    const tableHead = table?.querySelector("thead");
    const scrollContainer = table?.closest("[data-user-pages-table-scroll]");

    if (!table || !tableHead || !scrollContainer) {
      return;
    }

    if (table.__hymetryStickyTableHeaderRefresh) {
      table.__hymetryStickyTableHeaderRefresh();
      return;
    }

    const stickyHeader = document.createElement("div");
    const cloneTable = table.cloneNode(false);
    const stickyHeaderId = scrollContainer.getAttribute("data-sticky-table-header-id") || "user-pages-sticky-header";
    let cloneHead = null;

    stickyHeader.id = stickyHeaderId;
    stickyHeader.className = "companies-table-sticky-header";
    stickyHeader.setAttribute("aria-hidden", "true");
    document.body.appendChild(stickyHeader);
    stickyHeader.replaceChildren(cloneTable);

    const refreshCloneHead = () => {
      cloneHead = tableHead.cloneNode(true);
      cloneHead.querySelectorAll("[id]").forEach((element) => element.removeAttribute("id"));
      cloneHead.querySelectorAll("[tabindex]").forEach((element) => element.removeAttribute("tabindex"));
      cloneHead.querySelectorAll("a, button, input, select, textarea").forEach((element) => element.setAttribute("tabindex", "-1"));
      cloneTable.replaceChildren(cloneHead);
    };
    const relayStickyHeaderClick = (event) => {
      const cloneControl = event.target.closest("button");

      if (!cloneControl || !cloneHead?.contains(cloneControl)) {
        return;
      }

      const cloneButtons = Array.from(cloneHead.querySelectorAll("button"));
      const sourceButton = tableHead.querySelectorAll("button")[cloneButtons.indexOf(cloneControl)];

      if (!sourceButton || sourceButton.disabled) {
        return;
      }

      event.preventDefault();
      event.stopPropagation();
      sourceButton.click();
    };
    const getStickyTop = () => document.querySelector("body > nav")?.getBoundingClientRect().height || 48;
    const syncStickyHeader = () => {
      const stickyTop = getStickyTop();
      const tableRect = table.getBoundingClientRect();
      const scrollRect = scrollContainer.getBoundingClientRect();
      const scrollStyle = globalScope.getComputedStyle(scrollContainer);
      const scrollPaddingLeft = parseFloat(scrollStyle.paddingLeft) || 0;
      const scrollPaddingRight = parseFloat(scrollStyle.paddingRight) || 0;
      const headHeight = tableHead.getBoundingClientRect().height;
      const isVisible = tableRect.top < stickyTop && tableRect.bottom > stickyTop + headHeight;

      stickyHeader.dataset.visible = String(isVisible);

      if (!isVisible) {
        return;
      }

      stickyHeader.style.setProperty("--companies-table-sticky-top", `${stickyTop}px`);
      stickyHeader.style.left = `${scrollRect.left + scrollPaddingLeft}px`;
      stickyHeader.style.width = `${Math.max(0, scrollRect.width - scrollPaddingLeft - scrollPaddingRight)}px`;
      stickyHeader.style.height = `${headHeight}px`;
      cloneTable.style.width = `${table.getBoundingClientRect().width}px`;
      tableHead.querySelectorAll("th").forEach((cell, index) => {
        const cloneCell = cloneHead?.querySelectorAll("th")[index];
        const width = cell.getBoundingClientRect().width;

        if (cloneCell && width) {
          cloneCell.style.width = `${width}px`;
          cloneCell.style.minWidth = `${width}px`;
          cloneCell.style.maxWidth = `${width}px`;
        }
      });
      stickyHeader.scrollLeft = scrollContainer.scrollLeft;
    };

    refreshCloneHead();
    stickyHeader.addEventListener("click", relayStickyHeaderClick);
    table.__hymetryStickyTableHeaderRefresh = () => {
      refreshCloneHead();
      syncStickyHeader();
    };
    table.__hymetryStickyTableHeaderSync = syncStickyHeader;

    syncStickyHeader();
    document.addEventListener("scroll", syncStickyHeader, { passive: true, capture: true });
    globalScope.addEventListener("scroll", syncStickyHeader, { passive: true });
    globalScope.addEventListener("resize", syncStickyHeader);
    scrollContainer.addEventListener("scroll", syncStickyHeader, { passive: true });
    table.__hymetryStickyTableHeaderInterval = globalScope.setInterval(() => {
      if (!table.isConnected) {
        globalScope.clearInterval(table.__hymetryStickyTableHeaderInterval);
        stickyHeader.remove();
        return;
      }

      syncStickyHeader();
    }, 180);
  }

  function mountUserPagesTableStickyHeader() {
    const table = document.querySelector("[data-user-pages-table-scroll] table");

    if (table) {
      mountStickyTableHeader(table);
    }
  }

  function domIdFragment(value) {
    return String(value ?? "").replace(/[^a-zA-Z0-9_-]+/g, "-") || "item";
  }

  function peerComparisonUserName(row) {
    const userId = String(row.userId || row.id || row.user_id || "").trim();
    const user = { ...row, id: userId, userId };
    const name = row.name || userId || "Unknown user";

    if (row.isCurrentUser) {
      return `<span class="company-user-name font-semibold text-slate-950">${escapeHtml(name)}</span>`;
    }

    if (!userId) {
      return `<span class="company-user-name font-medium text-slate-900">${escapeHtml(name)}</span>`;
    }

    if (!row.email) {
      return `<a href="${escapeHtml(userDetailHref(user))}" class="company-user-name font-medium text-sky-800 underline-offset-2 hover:underline">${escapeHtml(name)}</a>`;
    }

    const tooltipId = `peer-comparison-user-email-${domIdFragment(userId || row.email || name)}`;

    return `
      <a href="${escapeHtml(userDetailHref(user))}" class="company-user-name metric-header-tooltip font-medium text-sky-800 underline-offset-2 hover:underline" aria-describedby="${escapeHtml(tooltipId)}">
        ${escapeHtml(name)}
        <span id="${escapeHtml(tooltipId)}" class="metric-header-tooltip__content" role="tooltip">${escapeHtml(row.email)}</span>
      </a>
    `;
  }

  function peerComparisonStatusBadge(status) {
    const variant = helpers.getStatusBadgeVariant(status).replace("users-badge", "companies-badge");

    return `<span class="companies-badge ${variant}">${escapeHtml(helpers.getStatusLabel(status))}</span>`;
  }

  function peerComparisonRankCell(row, rankByUserId, totalRows) {
    const rank = Number(row.rank) || rankByUserId.get(row.userId);

    if (!rank || !totalRows) {
      return `<span class="text-slate-400">-</span>`;
    }

    return `<span class="tabular-nums font-medium text-slate-900">#${escapeHtml(helpers.formatNumber(rank))} of ${escapeHtml(helpers.formatNumber(totalRows))}</span>`;
  }

  function renderPeerComparison() {
    const tbody = document.getElementById("peer-comparison-body");

    if (!tbody) {
      return;
    }

    const rankedRows = currentData.peerComparison || [];
    const currentRow = rankedRows.find((row) => row.isCurrentUser);
    let rows = helpers.getPeersAroundCurrentUser(rankedRows, currentData.selectedUser.id, "engagedSeconds", 5)
      .slice(0, peerComparisonRowLimit);

    if (currentRow && !rows.some((row) => row.userId === currentRow.userId)) {
      rows = [currentRow, ...rows.filter((row) => row.userId !== currentRow.userId).slice(0, peerComparisonRowLimit - 1)];
    }

    if (!rows.length) {
      tbody.innerHTML = `<tr><td colspan="8" class="py-10 text-center text-slate-500">${escapeHtml(currentData.emptyState.peers)}</td></tr>`;
      return;
    }

    peerComparisonAdoptionCellTooltipId = 0;
    peerComparisonPeriodChangeTooltipId = 0;

    const maxValues = tableMaxValues(rankedRows, peerComparisonMetrics);
    const maxDeltaValues = tableDeltaMaxValues(rankedRows, peerComparisonMetrics);
    const maxMatrixEngaged = Math.max(
      ...rankedRows.flatMap((row) => (row.productAreaAdoption || []).map((cell) => Number(cell.engagedSeconds) || 0)),
      1
    );
    const rankByUserId = new Map(
      rankedRows
        .slice()
        .sort((a, b) => (Number(b.engagedSeconds) || 0) - (Number(a.engagedSeconds) || 0) || String(a.name || "").localeCompare(String(b.name || "")))
        .map((row, index) => [row.userId, index + 1])
    );
    const totalRankedRows = rankedRows.length;

    tbody.innerHTML = rows.map((row) => `
      <tr class="${row.isCurrentUser ? "bg-sky-50/60" : "hover:bg-slate-50"}">
        <td class="py-3.5 pl-0 pr-6 align-middle">
          <div class="min-w-0">${peerComparisonUserName(row)}</div>
        </td>
        <td class="py-3.5 pr-6 align-middle">${peerComparisonStatusBadge(row.status)}</td>
        <td class="py-3.5 pr-6 align-middle tabular-nums font-medium text-slate-900">${escapeHtml(helpers.formatNumber(row.activeDays))}</td>
        ${renderMetricCell(row, peerComparisonMetrics[0], maxValues, maxDeltaValues.visits)}
        ${renderMetricCell(row, peerComparisonMetrics[1], maxValues, maxDeltaValues.engagedSeconds)}
        <td class="py-3.5 pr-6 align-middle">${adoptionMatrixCellGroup(row, maxMatrixEngaged)}</td>
        <td class="py-3.5 pr-6 align-middle">${row.topArea ? productAreaCell(row.topArea, row.topAreaColor) : `<span class="text-slate-400">-</span>`}</td>
        <td class="py-3.5 align-middle">${peerComparisonRankCell(row, rankByUserId, totalRankedRows)}</td>
      </tr>
    `).join("");

    syncSplitChangeValueWidths(tbody);
  }

  function formatDecimal(value, maxFractionDigits = 1) {
    return new Intl.NumberFormat("en-US", {
      minimumFractionDigits: 0,
      maximumFractionDigits: maxFractionDigits
    }).format(Number(value) || 0);
  }

  function deriveConsistencyStatus(metrics) {
    const sessionsPerWeek = Number(metrics.sessionsPerWeek) || 0;
    const avgEngagedPerSession = Number(metrics.avgEngagedPerSession) || 0;
    const totalEngagedSeconds = Number(metrics.totalEngagedSeconds) || 0;

    if (totalEngagedSeconds <= 0) {
      return "Dropped";
    }

    if (sessionsPerWeek < 0.75 && avgEngagedPerSession < 180) {
      return "Passive";
    }

    if (sessionsPerWeek >= 3 && avgEngagedPerSession >= 600) {
      return "Power";
    }

    if (sessionsPerWeek >= 1.25 && avgEngagedPerSession >= 300) {
      return "Healthy";
    }

    return "Light";
  }

  function companyConsistencySourceRows() {
    const selectedCompanyId = currentData?.selectedUser?.companyId || "";
    const sourceRows = Array.isArray(currentData?.companyPeerComparison) && currentData.companyPeerComparison.length
      ? currentData.companyPeerComparison
      : currentData?.peerComparison || [];
    const rows = sourceRows.filter((row) => !selectedCompanyId || row.companyId === selectedCompanyId);
    const selectedUserId = currentData?.selectedUser?.id || "";

    if (rows.some((row) => row.userId === selectedUserId)) {
      return rows.slice(0, 300);
    }

    const currentRow = (currentData?.peerComparison || []).find((row) => row.userId === selectedUserId);

    return [currentRow, ...rows].filter(Boolean).slice(0, 300);
  }

  function consistencyAreaUsageLabel(row) {
    const segments = (row.productAreaAdoption || [])
      .map((cell) => ({
        area: cell.productAreaName || cell.productAreaId || "Area",
        value: Number(cell.engagedSeconds) || Number(cell.visits) || Number(cell.pagesUsed) || 0,
        engagedSeconds: Number(cell.engagedSeconds) || 0
      }))
      .filter((cell) => cell.value > 0)
      .sort((a, b) => b.value - a.value)
      .slice(0, 4);

    if (!segments.length) {
      return "No usage detected";
    }

    return segments
      .map((segment) => `${segment.area} ${helpers.formatDuration(segment.engagedSeconds || segment.value)}`)
      .join(" - ");
  }

  function consistencySessionCount(row) {
    const explicitSessionCount = [
      row.sessionsCount,
      row.sessionCount,
      row.distinctSessions
    ].map((value) => Number(value)).find((value) => Number.isFinite(value) && value > 0);

    if (explicitSessionCount) {
      return Math.max(1, Math.round(explicitSessionCount));
    }

    if (Array.isArray(row.recentSessions) && row.recentSessions.length) {
      return row.recentSessions.length;
    }

    return Math.max(1, Math.round((Number(row.visits) || 0) / 3));
  }

  function buildConsistencyIntensityRows() {
    const periodDays = Math.max(1, Number(currentData?.periodDays) || helpers.DEFAULT_PERIOD_DAYS);
    const sourceRows = companyConsistencySourceRows();
    const companyEngagedSeconds = helpers.sum(sourceRows, (row) => row.engagedSeconds) || 1;
    const selectedUserId = currentData?.selectedUser?.id || "";

    return sourceRows
      .map((row) => {
        const sessions = consistencySessionCount(row);
        const totalEngagedSeconds = Number(row.engagedSeconds) || 0;
        const sessionsPerWeek = (sessions / periodDays) * 7;
        const avgEngagedPerSession = helpers.safeDivide(totalEngagedSeconds, sessions);
        const isCurrentUser = row.isCurrentUser || row.userId === selectedUserId;
        const metrics = {
          sessionCount: sessions,
          sessionsPerWeek,
          totalEngagedSeconds,
          avgEngagedPerSession
        };

        return {
          userId: row.userId,
          userName: row.name || "User",
          company: row.companyName || currentData.selectedUser.companyName || "Unknown company",
          status: deriveConsistencyStatus(metrics),
          sessions,
          sessionsPerWeek,
          avgEngagedPerSession,
          totalEngagedSeconds,
          sessionsPerWeekLabel: formatDecimal(sessionsPerWeek),
          totalEngagedLabel: helpers.formatDuration(totalEngagedSeconds),
          avgEngagedLabel: helpers.formatDuration(avgEngagedPerSession),
          companyShareLabel: helpers.formatPercent((totalEngagedSeconds / companyEngagedSeconds) * 100),
          areaUsageLabel: consistencyAreaUsageLabel(row),
          isCurrentUser,
          pointSize: isCurrentUser ? 230 : 100,
          hoverPointSize: isCurrentUser ? 290 : 150,
          pointStrokeColor: chartTheme.colors.white,
          pointStrokeWidth: isCurrentUser ? 0 : 1.3,
          pointZIndex: isCurrentUser ? 2 : 0,
          labelColor: isCurrentUser ? chartTheme.colors.text : chartTheme.colors.labelText,
          labelFontWeight: isCurrentUser ? 700 : 400,
          labelZIndex: isCurrentUser ? 3 : 1
        };
      })
      .filter((row) => row.sessions > 0 && row.status !== "Dropped");
  }

  function userQuadrantText(text, xValue, yValue, align) {
    return {
      type: "text",
      interactive: false,
      encode: {
        enter: {
          x: { scale: "xScale", value: xValue },
          y: { scale: "yScale", value: yValue },
          text: { value: text },
          align: { value: align },
          baseline: { value: "middle" },
          fill: { value: chartTheme.colors.mutedText },
          fillOpacity: { value: 0.58 },
          fontSize: { value: 12 },
          fontWeight: { value: 500 }
        }
      }
    };
  }

  function createUserConsistencyScatterSpec(rows, config) {
    const xMedian = helpers.median(rows.map((row) => row.sessionsPerWeek));
    const yMedian = helpers.median(rows.map((row) => row.avgEngagedPerSession));
    const xMax = Math.max(...rows.map((row) => row.sessionsPerWeek), 1);
    const yMax = Math.max(...rows.map((row) => row.avgEngagedPerSession), 60);
    const xDomainMax = Math.ceil(xMax + Math.max(0.75, xMax * 0.16));
    const yDomainMax = Math.ceil(yMax + Math.max(180, yMax * 0.16));
    const statuses = Object.keys(statusDistributionColorNames).filter((status) => status !== "Dropped");
    const statusColors = statuses.map((status) => tailwindColor(statusDistributionColorNames[status]));

    return {
      $schema: "https://vega.github.io/schema/vega/v5.json",
      width: config.width,
      height: 410,
      padding: { top: 34, right: 96, bottom: 56, left: 72 },
      background: chartTheme.colors.white,
      config: {
        font: "Inter, ui-sans-serif, system-ui, sans-serif",
        axis: {
          domainColor: chartTheme.colors.axis,
          gridColor: chartTheme.colors.grid,
          labelColor: chartTheme.colors.mutedText,
          labelFont: "Inter, ui-sans-serif, system-ui, sans-serif",
          labelFontSize: 11,
          labelPadding: 7,
          tickColor: chartTheme.colors.axis,
          titleColor: chartTheme.colors.mutedText,
          titleFont: "Inter, ui-sans-serif, system-ui, sans-serif",
          titleFontSize: 12,
          titleFontWeight: 600,
          titlePadding: 14
        }
      },
      signals: [
        { name: "xMedian", value: xMedian },
        { name: "yMedian", value: yMedian }
      ],
      data: [
        { name: "points", values: rows }
      ],
      scales: [
        { name: "xScale", type: "linear", domain: [0, xDomainMax], nice: true, range: "width" },
        { name: "yScale", type: "linear", domain: [0, yDomainMax], nice: true, range: "height" },
        { name: "colorScale", type: "ordinal", domain: statuses, range: statusColors }
      ],
      axes: [
        {
          orient: "bottom",
          scale: "xScale",
          title: "Sessions / week",
          grid: false,
          tickCount: 6,
          labelFlush: true,
          labelFlushOffset: 4,
          labelExpr: "format(datum.value, '.1f')"
        },
        {
          orient: "left",
          scale: "yScale",
          title: "Avg engaged / session",
          grid: false,
          tickCount: 6,
          titleAngle: 0,
          titleAnchor: "end",
          titleAlign: "left",
          titleX: -74,
          titleY: -16,
          labelExpr: "datum.value >= 3600 ? floor(datum.value / 3600) + 'h' : datum.value >= 60 ? floor(datum.value / 60) + 'm' : floor(datum.value) + 's'"
        }
      ],
      legends: [
        {
          fill: "colorScale",
          orient: "top-right",
          direction: "horizontal",
          columns: statuses.length,
          offset: 0,
          columnPadding: 12,
          symbolType: "circle",
          symbolSize: 72,
          labelColor: chartTheme.colors.labelText,
          labelFont: "Inter, ui-sans-serif, system-ui, sans-serif",
          labelFontSize: 11
        }
      ],
      marks: [
        {
          type: "rule",
          interactive: false,
          encode: {
            enter: {
              x: { scale: "xScale", signal: "xMedian" },
              y: { value: 0 },
              y2: { signal: "height" },
              stroke: { value: chartTheme.colors.axis },
              strokeDash: { value: [4, 4] },
              strokeWidth: { value: 1 }
            }
          }
        },
        {
          type: "rule",
          interactive: false,
          encode: {
            enter: {
              x: { value: 0 },
              x2: { signal: "width" },
              y: { scale: "yScale", signal: "yMedian" },
              stroke: { value: chartTheme.colors.axis },
              strokeDash: { value: [4, 4] },
              strokeWidth: { value: 1 }
            }
          }
        },
        userQuadrantText("Power users", xDomainMax * 0.82, yDomainMax * 0.92, "end"),
        userQuadrantText("Frequent shallow", xDomainMax * 0.82, yDomainMax * 0.12, "end"),
        userQuadrantText("Deep infrequent", xDomainMax * 0.08, yDomainMax * 0.92, "start"),
        userQuadrantText("Passive / weak", xDomainMax * 0.08, yDomainMax * 0.12, "start"),
        {
          name: "userPoints",
          type: "symbol",
          from: { data: "points" },
          encode: {
            enter: {
              x: { scale: "xScale", field: "sessionsPerWeek" },
              y: { scale: "yScale", field: "avgEngagedPerSession" },
              shape: { value: "circle" },
              tooltip: {
                signal:
                  "{'User': datum.userName, 'Company': datum.company, 'Status': datum.status, 'Sessions': format(datum.sessions, ','), 'Sessions/week': datum.sessionsPerWeekLabel, 'Total engaged time': datum.totalEngagedLabel, 'Avg engaged/session': datum.avgEngagedLabel, 'Company share': datum.companyShareLabel, 'Area usage': datum.areaUsageLabel}"
              }
            },
            update: {
              cursor: { value: "default" },
              fill: { scale: "colorScale", field: "status" },
              opacity: { value: 0.84 },
              size: { field: "pointSize" },
              stroke: { field: "pointStrokeColor" },
              strokeWidth: { field: "pointStrokeWidth" },
              zindex: { field: "pointZIndex" }
            },
            hover: {
              opacity: { value: 1 },
              size: { field: "hoverPointSize" },
              strokeWidth: { value: 2.6 },
              zindex: { value: 3 }
            }
          }
        },
        {
          type: "text",
          interactive: false,
          from: { data: "userPoints" },
          encode: {
            enter: {
              text: { field: "datum.userName" },
              fill: { field: "datum.labelColor" },
              font: { value: "Inter, ui-sans-serif, system-ui, sans-serif" },
              fontSize: { value: 12 },
              fontWeight: { field: "datum.labelFontWeight" },
              opacity: { value: 1 },
              limit: { value: 118 },
              zindex: { field: "datum.labelZIndex" }
            }
          },
          transform: [
            {
              type: "label",
              anchor: ["right", "top", "bottom", "left", "top-right", "bottom-right", "top-left", "bottom-left"],
              offset: [3],
              size: [{ signal: "width" }, { signal: "height" }]
            }
          ]
        }
      ]
    };
  }

  function renderScatter() {
    const element = document.getElementById("consistency-intensity-scatter");

    if (!element) {
      return;
    }

    if (element.__hymetryChart) {
      element.__hymetryChart.dispose();
      element.__hymetryChart = null;
    }

    if (element.__hymetryChartResize) {
      globalScope.removeEventListener("resize", element.__hymetryChartResize);
      element.__hymetryChartResize = null;
    }

    if (element.__hymetryResizeObserver) {
      element.__hymetryResizeObserver.disconnect();
      element.__hymetryResizeObserver = null;
    }

    if (element.__hymetryVegaResizeObserver) {
      element.__hymetryVegaResizeObserver.disconnect();
      element.__hymetryVegaResizeObserver = null;
    }

    disposeVega(element);

    const rows = buildConsistencyIntensityRows();

    if (!rows.length) {
      chartUnavailable(element, currentData.emptyState.peers);
      return;
    }

    if (!globalScope.vegaEmbed) {
      chartUnavailable(element, "Vega is unavailable.");
      return;
    }

    const render = () => {
      const width = Math.max(640, Math.round(element.clientWidth - 168));
      const token = `${Date.now()}-${Math.random()}`;
      element.__hymetryVegaRenderToken = token;

      disposeVega(element);

      globalScope.vegaEmbed(element, createUserConsistencyScatterSpec(rows, { width }), {
        actions: false,
        renderer: "canvas"
      })
        .then((result) => {
          if (element.__hymetryVegaRenderToken !== token) {
            result.view.finalize();
            return;
          }

          element.__hymetryVegaView = result.view;
        })
        .catch(() => chartUnavailable(element, "Unable to render Vega scatter plot."));
    };

    render();

    if (globalScope.ResizeObserver) {
      if (element.__hymetryVegaResizeObserver) {
        element.__hymetryVegaResizeObserver.disconnect();
      }

      let animationFrame = null;
      const observer = new ResizeObserver(() => {
        if (animationFrame) {
          globalScope.cancelAnimationFrame(animationFrame);
        }

        animationFrame = globalScope.requestAnimationFrame(render);
      });
      observer.observe(element);
      element.__hymetryVegaResizeObserver = observer;
    }
  }

  function normalizeUserPageRow(row) {
    const interactionValue = Number(row.interactionPct ?? row.interactionRate) || 0;
    const interactionPct = Math.abs(interactionValue) <= 1 ? interactionValue * 100 : interactionValue;

    return {
      ...row,
      productArea: row.productArea || row.productAreaName || "",
      interactionPct,
      shareOfUserTimePct: Number(row.shareOfUserTimePct) || 0,
      peerUsagePct: Number(row.peerUsagePct) || 0,
      visitsDeltaPct: Number(row.visitsDeltaPct) || 0,
      engagedDeltaPct: Number(row.engagedDeltaPct) || 0,
      avgVisitDeltaPct: Number(row.avgVisitDeltaPct) || 0,
      interactionDeltaPp: Number(row.interactionDeltaPp) || 0
    };
  }

  function compareUserPagesByCurrentSort(a, b) {
    const sortKey = userPagesTableState.sortKey;
    const direction = userPagesTableState.sortDirection === "asc" ? 1 : -1;
    let comparison = 0;

    if (sortKey === "pageName" || sortKey === "productArea" || sortKey === "lastUsedAt") {
      comparison = String(a[sortKey] || "").localeCompare(String(b[sortKey] || ""));
    } else {
      comparison = (Number(a[sortKey]) || 0) - (Number(b[sortKey]) || 0);
    }

    return comparison * direction || String(a.pageName || "").localeCompare(String(b.pageName || ""));
  }

  function userPagesPaginationIcon(direction) {
    if (direction === "previous") {
      return `
        <svg xmlns="http://www.w3.org/2000/svg" height="20px" viewBox="0 -960 960 960" width="20px" fill="currentColor" aria-hidden="true">
          <path d="m456-480 184 184-42 42-226-226 226-226 42 42-184 184Z" />
        </svg>
      `;
    }

    return `
      <svg xmlns="http://www.w3.org/2000/svg" height="20px" viewBox="0 -960 960 960" width="20px" fill="currentColor" aria-hidden="true">
        <path d="m504-480-184-184 42-42 226 226-226 226-42-42 184-184Z" />
      </svg>
    `;
  }

  function getUserPagesPageCount(rows) {
    return tablePageCount(currentData, "pagesUsed", rows, userPagesPageSize);
  }

  function renderUserPagesPagination(totalPages) {
    const container = document.querySelector("[data-user-pages-pagination]");

    if (!container) {
      return;
    }

    if (totalPages <= 1) {
      container.hidden = true;
      container.innerHTML = "";
      return;
    }

    const currentPage = Math.min(totalPages, Math.max(1, userPagesTableState.page));
    const disabledAttr = userPagesTableState.isLoading ? " disabled" : "";

    container.hidden = false;
    container.innerHTML = `
      ${
        currentPage > 2
          ? `<button type="button" class="font-medium text-sky-700 hover:text-sky-800" data-user-pages-page-action="first"${disabledAttr}>Go to first page</button>`
          : `<span aria-hidden="true"></span>`
      }
      <div class="flex items-center justify-between gap-6 sm:justify-end">
        ${
          currentPage > 1
            ? `<button type="button" class="inline-flex h-8 w-8 items-center justify-center text-sky-700 hover:text-sky-800" data-user-pages-page-action="previous" aria-label="Back to previous page"${disabledAttr}>${userPagesPaginationIcon("previous")}</button>`
            : `<span class="invisible h-8 w-8" aria-hidden="true"></span>`
        }
        <span class="text-slate-700">Page ${currentPage}/${totalPages}</span>
        ${
          currentPage < totalPages
            ? `<button type="button" class="inline-flex items-center gap-2 rounded-md border border-slate-200 bg-transparent px-4 py-3 font-medium text-sky-700 duration-150 hover:bg-slate-100" data-user-pages-page-action="next"${disabledAttr}>Continue to next page ${userPagesPaginationIcon("next")}</button>`
            : ""
        }
      </div>
    `;

    container.querySelectorAll("[data-user-pages-page-action]").forEach((button) => {
      button.addEventListener("click", () => {
        const action = button.getAttribute("data-user-pages-page-action");
        const targetPage =
          action === "first"
            ? 1
            : action === "previous"
              ? Math.max(1, userPagesTableState.page - 1)
              : Math.min(totalPages, userPagesTableState.page + 1);

        requestUserPagesPage(targetPage);
      });
    });
  }

  function setUserPagesTableLoading(isLoading) {
    const overlay = document.querySelector("[data-user-pages-table-loading]");
    const tableShell = document.querySelector("[data-user-pages-table-scroll]");

    tableShell?.setAttribute("aria-busy", String(isLoading));

    if (!overlay) {
      return;
    }

    if (isLoading) {
      overlay.hidden = false;
      overlay.dataset.visible = "false";
      overlay.style.transition = "none";
      overlay.style.opacity = "0";
      overlay.style.pointerEvents = "none";
      overlay.offsetHeight;
      overlay.dataset.visible = "true";
      overlay.style.opacity = "1";
      overlay.style.pointerEvents = "auto";
      return;
    }

    overlay.dataset.visible = "false";
    overlay.style.transition = "opacity 220ms ease";
    overlay.style.opacity = "0";
    overlay.style.pointerEvents = "none";
    globalScope.setTimeout(() => {
      if (overlay.dataset.visible !== "true") {
        overlay.hidden = true;
      }
    }, 240);
  }

  function isUserPagesHeaderVisible() {
    const tableHead = document.querySelector("[data-user-pages-table-scroll] thead");

    if (!tableHead) {
      return true;
    }

    const stickyTop = document.querySelector("body > nav")?.getBoundingClientRect().height || 48;
    const rect = tableHead.getBoundingClientRect();

    return rect.top >= stickyTop && rect.bottom <= globalScope.innerHeight;
  }

  function scrollUserPagesHeaderIntoView() {
    const tableHead = document.querySelector("[data-user-pages-table-scroll] thead");

    if (!tableHead) {
      return;
    }

    const stickyTop = document.querySelector("body > nav")?.getBoundingClientRect().height || 48;
    const targetTop = Math.max(0, globalScope.scrollY + tableHead.getBoundingClientRect().top - stickyTop - 12);

    globalScope.scrollTo({
      top: targetTop,
      behavior: "smooth"
    });
  }

  function updateUserPagesSortButtons() {
    document.querySelectorAll("[data-user-pages-sort]").forEach((button) => {
      const isActive = button.getAttribute("data-user-pages-sort") === userPagesTableState.sortKey;

      button.setAttribute("data-sort-direction", isActive ? userPagesTableState.sortDirection : "");
      button.setAttribute("aria-pressed", String(isActive));
    });
    mountUserPagesTableStickyHeader();
  }

  function simulateUserPagesLoad(onComplete) {
    if (userPagesTableState.isLoading) {
      return;
    }

    userPagesTableState.isLoading = true;
    userPagesTableState.loadingToken += 1;

    const token = userPagesTableState.loadingToken;
    const rows = filteredPagesUsed();

    setUserPagesTableLoading(true);
    renderUserPagesPagination(getUserPagesPageCount(rows));

    if (!isUserPagesHeaderVisible()) {
      scrollUserPagesHeaderIntoView();
    }

    globalScope.setTimeout(() => {
      if (token !== userPagesTableState.loadingToken) {
        return;
      }

      onComplete();
      userPagesTableState.isLoading = false;
      setUserPagesTableLoading(false);
      renderUserPagesPagination(getUserPagesPageCount(filteredPagesUsed()));
    }, 1000);
  }

  function loadUserPagesTablePage(targetPage) {
    if (typeof provider.loadUserDetailTable !== "function" || !currentData || userPagesTableState.isLoading) {
      return false;
    }

    userPagesTableState.isLoading = true;
    userPagesTableState.loadingToken += 1;

    const token = userPagesTableState.loadingToken;

    setUserPagesTableLoading(true);
    renderUserPagesPagination(getUserPagesPageCount(filteredPagesUsed()));

    if (!isUserPagesHeaderVisible()) {
      scrollUserPagesHeaderIntoView();
    }

    provider.loadUserDetailTable("pagesUsed", {
      page: targetPage,
      page_size: userPagesPageSize,
      sort: userPagesTableState.sortKey,
      direction: userPagesTableState.sortDirection,
      periodDays: state.periodDays,
      q: state.pageSearch,
      product_area_id: state.productAreaId
    }).then((payload) => {
      if (token !== userPagesTableState.loadingToken) {
        return;
      }

      if (applyTablePayload(currentData, "pagesUsed", "pagesUsed", payload, userPagesTableState)) {
        renderPagesUsed();
      }
    }).finally(() => {
      if (token !== userPagesTableState.loadingToken) {
        return;
      }

      userPagesTableState.isLoading = false;
      setUserPagesTableLoading(false);
      renderUserPagesPagination(getUserPagesPageCount(filteredPagesUsed()));
    });

    return true;
  }

  function requestUserPagesPage(targetPage) {
    if (!currentData || userPagesTableState.isLoading || targetPage === userPagesTableState.page) {
      return;
    }

    if (loadUserPagesTablePage(targetPage)) {
      return;
    }

    simulateUserPagesLoad(() => {
      userPagesTableState.page = targetPage;
      renderPagesUsed();
    });
  }

  function mountUserPagesSort() {
    if (userPagesSortMounted) {
      return;
    }

    userPagesSortMounted = true;

    document.querySelectorAll("[data-user-pages-sort]").forEach((button) => {
      button.addEventListener("click", () => {
        const sortKey = button.getAttribute("data-user-pages-sort") || "engagedSeconds";

        if (!currentData || userPagesTableState.isLoading) {
          return;
        }

        if (userPagesTableState.sortKey === sortKey) {
          userPagesTableState.sortDirection = userPagesTableState.sortDirection === "asc" ? "desc" : "asc";
        } else {
          userPagesTableState.sortKey = sortKey;
          userPagesTableState.sortDirection = userPagesDefaultSortDirections[sortKey] || "desc";
        }

        userPagesTableState.page = 1;
        updateUserPagesSortButtons();
        if (loadUserPagesTablePage(1)) {
          return;
        }

        simulateUserPagesLoad(renderPagesUsed);
      });
    });
  }

  function filteredPagesUsed() {
    const query = String(state.pageSearch || "").trim().toLowerCase();
    const sourceRows = currentData.pagesUsed || [];

    return sourceRows
      .map(normalizeUserPageRow)
      .filter((page) => !state.productAreaId || page.productAreaId === state.productAreaId)
      .filter((page) => !query || [page.pageName, page.productArea, page.productAreaName].join(" ").toLowerCase().includes(query))
      .sort(compareUserPagesByCurrentSort);
  }

  function renderPagesUsed() {
    const tbody = document.getElementById("pages-used-body");

    if (!tbody) {
      return;
    }

    const rows = filteredPagesUsed();
    const totalPages = getUserPagesPageCount(rows);

    userPagesTableState.page = Math.min(totalPages, Math.max(1, userPagesTableState.page));
    updateUserPagesSortButtons();
    renderUserPagesPagination(totalPages);

    if (!rows.length) {
      tbody.innerHTML = `<tr><td colspan="9" class="py-10 text-center text-slate-500">${escapeHtml(currentData.emptyState.pages)}</td></tr>`;
      renderUserPagesPagination(1);
      mountUserPagesTableStickyHeader();
      return;
    }

    const pageRows = tableRowsForRender(currentData, "pagesUsed", rows, userPagesTableState, userPagesPageSize);
    const maxValues = tableMaxValues(rows, userPagesMetrics);
    const maxDeltaValues = tableDeltaMaxValues(rows, userPagesMetrics);

    tbody.innerHTML = pageRows.map((row, rowIndex) => `
        <tr class="hover:bg-slate-50">
          <td class="py-3.5 pl-0 pr-6 align-middle font-medium text-slate-900">
            <a class="text-sky-800 hover:text-sky-900" href="${escapeHtml(pageDetailHref(row.pageRuleId))}">${escapeHtml(row.pageName)}</a>
          </td>
          <td class="py-3.5 pr-6 align-middle">${productAreaCell(row.productArea, row.productAreaColor)}</td>
          ${renderMetricCell(row, userPagesMetrics[0], maxValues, maxDeltaValues[userPagesMetrics[0].key])}
          <td class="py-3.5 pr-6 align-middle tabular-nums font-medium text-slate-900">${escapeHtml(helpers.formatPercent(row.shareOfUserTimePct))}</td>
          ${userPagesMetrics.slice(1).map((metric) => renderMetricCell(row, metric, maxValues, maxDeltaValues[metric.key])).join("")}
          <td class="py-3.5 pr-6 align-middle whitespace-nowrap tabular-nums text-slate-700">${escapeHtml(`${helpers.formatPercent(row.peerUsagePct)} of peers`)}</td>
          <td class="py-3.5 align-middle whitespace-nowrap text-slate-700">
            <span class="metric-header-tooltip" data-tooltip-kind="last-used" tabindex="0" aria-describedby="user-page-last-used-tooltip-${rowIndex}">
              ${escapeHtml(formatRelativeDate(row.lastUsedAt))}
              <span id="user-page-last-used-tooltip-${rowIndex}" class="metric-header-tooltip__content" role="tooltip">${analyticsTooltips.render({ rows: [{ label: "Last used", value: formatDate(row.lastUsedAt) }] })}</span>
            </span>
          </td>
        </tr>
      `).join("");

    syncSplitChangeValueWidths(tbody);
    mountUserPagesTableStickyHeader();
  }

  function renderRecommendedActions() {
    const container = document.getElementById("recommended-next-steps");
    const allRows = currentData.recommendedActions || [];
    const rows = allRows.filter(recommendedActionMatchesProductArea);

    if (!container) {
      return;
    }

    if (!rows.length) {
      const message = allRows.length
        ? "No recommended next steps match the selected product area."
        : currentData.emptyState.actions;

      container.innerHTML = `
        <div class="user-detail-empty">
          <div class="font-semibold text-slate-700">No recommended next steps</div>
          <div class="mt-1">${escapeHtml(message)}</div>
        </div>
      `;
      return;
    }

    container.innerHTML = `
      <div class="overflow-x-auto">
        <table class="recommended-next-steps-table w-full table-auto text-left">
          <thead class="border-b border-gray-300 bg-white text-slate-600">
            <tr>
              <th scope="col" class="py-3 pl-0 pr-4 font-normal">${tableHeaderTooltip("Priority", "Relative importance of the recommended next step.", "recommended-next-steps-tooltip-priority")}</th>
              <th scope="col" class="py-3 pr-4 font-normal">${tableHeaderTooltip("Type", "Signal category that produced this recommendation.", "recommended-next-steps-tooltip-type")}</th>
              <th scope="col" class="recommended-next-steps-table__action py-3 pr-4 font-normal">${tableHeaderTooltip("Recommended action", "Suggested next step based on this user's recent activity.", "recommended-next-steps-tooltip-action")}</th>
              <th scope="col" class="recommended-next-steps-table__reason py-3 pr-4 font-normal">${tableHeaderTooltip("Reason", "Usage pattern that led to the recommendation.", "recommended-next-steps-tooltip-reason")}</th>
              <th scope="col" class="recommended-next-steps-table__evidence py-3 pr-4 font-normal">${tableHeaderTooltip("Evidence", "Specific signal supporting the recommended action.", "recommended-next-steps-tooltip-evidence")}</th>
              <th scope="col" class="recommended-next-steps-table__related py-3 pr-4 font-normal">${tableHeaderTooltip("Related area / page", "Product area or page connected to the recommendation.", "recommended-next-steps-tooltip-related")}</th>
              <th scope="col" class="recommended-next-steps-table__owner py-3 pr-4 font-normal">${tableHeaderTooltip("Owner", "Suggested team or role to follow up.", "recommended-next-steps-tooltip-owner")}</th>
            </tr>
          </thead>
          <tbody class="text-slate-700">
            ${rows.map((row) => `
              <tr class="border-b border-slate-100 last:border-0">
                <td class="py-3 pl-0 pr-4">${priorityBadge(row.priority)}</td>
                <td class="py-3 pr-4">${recommendedActionTypeBadge(row.type)}</td>
                <td class="recommended-next-steps-table__action py-3 pr-4 font-semibold text-slate-900">${escapeHtml(row.action)}</td>
                <td class="recommended-next-steps-table__reason py-3 pr-4">${escapeHtml(row.reason)}</td>
                <td class="recommended-next-steps-table__evidence py-3 pr-4 tabular-nums">${escapeHtml(row.evidence)}</td>
                <td class="recommended-next-steps-table__related py-3 pr-4">${recommendedActionRelatedCell(row)}</td>
                <td class="recommended-next-steps-table__owner py-3 pr-4">${escapeHtml(row.owner)}</td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      </div>
    `;
  }

  function renderAll() {
    loadCurrentData();
    updateUrl();
    userPagesTableState.page = 1;
    userPagesTableState.isLoading = false;
    userPagesTableState.loadingToken += 1;
    setUserPagesTableLoading(false);
    setHidden("user-detail-loading", true);
    setHidden("user-detail-error", true);
    setHidden("user-detail-content", false);
    mountUserSearch();
    mountUserPagesSort();
    renderHeader();
    renderKpis();
    renderDailyChart();
    renderProductAreaMix();
    renderProductAreaMix2();
    renderPeerComparison();
    renderScatter();
    renderPagesUsed();
    renderRecommendedActions();
    rememberRecentUser(currentData.selectedUser);
    scheduleSplitChangeValueWidthSync();
  }

  function initUserDetail() {
    if (document.body.dataset.usersView !== "detail") {
      return;
    }

    readUrlState();
    globalScope.setTimeout(renderAll, 120);
  }

  document.addEventListener("DOMContentLoaded", initUserDetail);
})(window);
