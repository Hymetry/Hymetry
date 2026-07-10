(function mountHymetryCompanyDetail(globalScope) {
  const provider = globalScope.HymetryCompaniesDemoData;
  const detailHelpers = globalScope.HymetryCompanyDetailHelpers;
  const metricDynamicsHelpers = globalScope.HymetryMetricDynamics || {};

  if (!provider || !detailHelpers) {
    return;
  }

  /**
   * @typedef {ReturnType<detailHelpers.buildCompanyDetailsData>} CompanyDetailsData
   */

  const numberFormatter = new Intl.NumberFormat("en-US");
  const recentCompaniesStorageKey = "hymetry:recent-companies";
  const buildMetricDynamicsSeries = metricDynamicsHelpers.buildMetricDynamicsSeries || ((options = {}) => {
    const current = Array.isArray(options.currentSeries)
      ? options.currentSeries.map((point) => {
          if (point?.value === null || point?.value === undefined || point?.value === "") {
            return null;
          }

          const numericValue = Number(point?.value ?? point);
          return Number.isFinite(numericValue) ? numericValue : null;
        })
      : [];

    return {
      actualSeries: current,
      current,
      currentStraightTrendSeries: current,
      currentTrend: current,
      benchmarkStraightTrendSeries: [],
      benchmark: [],
      benchmarkUnavailableReason: "Benchmark unavailable: not enough comparable data.",
      peerSeriesList: [],
      peerTraces: [],
      hiddenPeerTraceCount: 0
    };
  });
  const setMetricDynamicsLoadingState = metricDynamicsHelpers.setMetricDynamicsLoadingState || (() => false);
  const getMetricDynamicsAxisBounds = metricDynamicsHelpers.getMetricDynamicsAxisBounds || (() => ({ min: "dataMin", max: "dataMax" }));
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
    "blue-50": "#eff6ff",
    "blue-400": "#60a5fa",
    "green-700": "#15803d",
    "red-600": "#dc2626",
    "slate-50": "#f8fafc",
    "slate-100": "#f1f5f9",
    "slate-200": "#e2e8f0",
    "slate-300": "#cbd5e1",
    "slate-400": "#94a3b8",
    "slate-500": "#64748b",
    "slate-600": "#475569",
    "slate-700": "#334155",
    "slate-900": "#0f172a",
    "gray-300": "#d1d5db",
    "gray-600": "#4b5563",
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
  const echartsDefaultSeriesColors = [
    "#5470C6",
    "#91CC75",
    "#FAC858",
    "#EE6666",
    "#73C0DE",
    "#3BA272",
    "#FC8452",
    "#9A60B4",
    "#EA7CCC"
  ];
  const chartSeriesColors = visitsCircleColors.concat(echartsDefaultSeriesColors);
  const productAreaPalette = chartSeriesColors;
  const secondaryAreaNamePattern = /admin|setting|permission|support|setup|technical/i;

  const statusRegistry = globalScope.HymetryAnalyticsStatusColors || {};
  const fallbackCompanyStatusOrder = ["power", "healthy", "activated", "new", "reactivated", "at_risk", "dormant"];
  const fallbackUserStatusOrder = ["power", "healthy", "light", "passive", "dropped"];
  const fallbackCompanyStatusMeta = {
    new: { label: "New", color: "c-light-blue", badge: "companies-badge--light-blue", definition: "First seen in the selected period." },
    activated: { label: "Activated", color: "c-teal", badge: "companies-badge--teal", definition: "Recently reached activation criteria." },
    reactivated: { label: "Reactivated", color: "c-blue", badge: "companies-badge--blue", definition: "Returned after a quiet period." },
    healthy: { label: "Healthy", color: "c-blue", badge: "companies-badge--blue", definition: "Shows consistent engagement." },
    power: { label: "Power", color: "c-green", badge: "companies-badge--green", definition: "High breadth and depth of adoption." },
    at_risk: { label: "At risk", color: "c-orange", badge: "companies-badge--orange", definition: "Shows a meaningful usage drop or stale activity." },
    dormant: { label: "Dormant", color: "c-red", badge: "companies-badge--red", definition: "Has little or no activity in this period." }
  };
  const fallbackUserStatusMeta = {
    power: { label: "Power", color: "c-green", badge: "companies-badge--green", definition: "High engagement, repeated usage, and broad product-area usage." },
    healthy: { label: "Healthy", color: "c-blue", badge: "companies-badge--blue", definition: "Regular usage with meaningful engagement." },
    light: { label: "Light", color: "c-orange", badge: "companies-badge--orange", definition: "Some usage, but limited depth or frequency." },
    passive: { label: "Passive", color: "c-brown", badge: "companies-badge--brown", definition: "Very low interaction or recent decline." },
    dropped: { label: "Dropped", color: "c-red", badge: "companies-badge--red", definition: "Previously known user with no or almost no recent activity." }
  };
  const companyStatusOrder = statusRegistry.companyStatusOrder || fallbackCompanyStatusOrder;
  const userStatusOrder = statusRegistry.userStatusOrder || fallbackUserStatusOrder;
  const normalizeCompanyStatus = statusRegistry.normalizeCompanyStatus || ((status) => {
    const key = String(status || "").trim().replace(/\s+/g, "_").replace(/-/g, "_").toLowerCase();
    return { active: "activated", risk: "at_risk", atrisk: "at_risk", dropped: "dormant" }[key] || key;
  });
  const normalizeUserStatus = statusRegistry.normalizeUserStatus || ((status) => {
    const key = String(status || "").trim().replace(/\s+/g, "_").replace(/-/g, "_").toLowerCase();
    return { active: "healthy", risk: "light", at_risk: "light", atrisk: "light" }[key] || key;
  });
  const getCompanyStatusMeta = statusRegistry.getCompanyStatusMeta || ((status) => {
    const key = normalizeCompanyStatus(status);
    const meta = fallbackCompanyStatusMeta[key];

    return meta
      ? { ...meta, key, sort: companyStatusOrder.indexOf(key) }
      : { key, label: String(status || "Unknown"), color: "slate-400", badge: "companies-badge--gray", sort: 99, definition: "" };
  });
  const getUserStatusMeta = statusRegistry.getUserStatusMeta || ((status) => {
    const key = normalizeUserStatus(status);
    const meta = fallbackUserStatusMeta[key];

    return meta
      ? { ...meta, key, sort: userStatusOrder.indexOf(key) }
      : { key, label: String(status || "Unknown"), color: "slate-400", badge: "companies-badge--gray", sort: 99, definition: "" };
  });
  const userHealthSegments = statusRegistry.userHealthSegments || userStatusOrder.map((key) => [
    key,
    fallbackUserStatusMeta[key]?.label || key,
    fallbackUserStatusMeta[key]?.color || "slate-500"
  ]);
  const userStatusMeta = userStatusOrder.reduce((lookup, key) => {
    lookup[key] = getUserStatusMeta(key, "companies");
    return lookup;
  }, {});
  const companyUsersScatterStatusOrder = ["power", "healthy", "light", "passive"];

  const chartTheme = {
    colors: {
      primary: visitsCircleColors[0],
      warning: visitsCircleColors[1],
      text: tailwindColor("slate-900"),
      mutedText: tailwindColor("slate-500"),
      labelText: tailwindColor("slate-700"),
      axis: tailwindColor("slate-300"),
      grid: tailwindColor("slate-200"),
      white: tailwindColor("white")
    },
    series: chartSeriesColors
  };

  const topPageMetrics = [
    { key: "users", label: "Users", valueType: "number", deltaKey: "usersDeltaPct", deltaUnit: "%" },
    { key: "visits", label: "Visits", valueType: "number", deltaKey: "visitsDeltaPct", deltaUnit: "%" },
    { key: "engagedSeconds", label: "Engaged", valueType: "duration", deltaKey: "engagedDeltaPct", deltaUnit: "%" },
    { key: "avgVisitSeconds", label: "Avg / visit", valueType: "duration", deltaKey: "avgVisitDeltaPct", deltaUnit: "%" },
    { key: "interactionPct", label: "Interaction", valueType: "percent", deltaKey: "interactionDeltaPp", deltaUnit: "pp", barMode: "percent" }
  ];
  const topPagesPageSize = 15;
  const topPagesDefaultSortDirections = {
    pageName: "asc",
    productArea: "asc",
    users: "desc",
    visits: "desc",
    engagedSeconds: "desc",
    avgVisitSeconds: "desc",
    interactionPct: "desc"
  };
  const userTableMetrics = [
    { key: "visits", label: "Visits", valueType: "number", deltaKey: "visitsDeltaPct", deltaUnit: "%" },
    { key: "engagedSeconds", label: "Engaged", valueType: "duration", deltaKey: "engagedDeltaPct", deltaUnit: "%" }
  ];
  const peerComparisonMetrics = [
    { key: "avgEngagedSecondsPerUser", label: "Engaged / user", valueType: "duration", deltaKey: "avgEngagedSecondsPerUserDeltaPct", deltaUnit: "%" }
  ];

  const userNumericSortKeys = new Set(["lastActiveDays", "activeDays", "engagedSeconds", "visits", "interactionPct"]);
  const areaUsedEngagedSecondsThreshold = 60;
  const areaUsedVisitsThreshold = 2;
  const userStatusSort = userStatusOrder.reduce((lookup, key, index) => {
    lookup[key] = index;
    return lookup;
  }, {});
  const usersPageSize = 20;
  const userDefaultSortDirections = {
    name: "asc",
    status: "asc",
    lastActiveDays: "asc",
    activeDays: "desc",
    visits: "desc",
    engagedSeconds: "desc",
    interactionPct: "desc",
    topArea: "asc"
  };
  const peerTrendMagnitudeRatioLimit = 10;

  let currentDetailData = null;
  let currentOverviewData = null;
  let productAreaColorByName = new Map();
  const productAreaColorResolver = globalScope.HymetryProductAreaColors?.createResolver({
    resolveColor: tailwindColor,
    palette: productAreaPalette
  }) || null;
  let productAreaMixTooltipId = 0;
  let adoptionCellTooltipId = 0;
  let periodChangeTooltipId = 0;
  let areaMixFloatingTooltipMounted = false;
  let companySelectorMounted = false;
  let companySelectorDebounceId = 0;
  let userSortMounted = false;
  let topPagesSortMounted = false;
  let splitChangeValueWidthSyncFrame = 0;
  const companySelectorState = {
    isOpen: false,
    activeIndex: -1,
    query: "",
    results: [],
    remoteQuery: "",
    remoteResults: [],
    requestToken: 0
  };
  const userTableState = {
    sortKey: "engagedSeconds",
    sortDirection: "desc",
    page: 1,
    isLoading: false,
    loadingToken: 0
  };
  const topPagesTableState = {
    page: 1,
    sortKey: "engagedSeconds",
    sortDirection: "desc",
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

  function tableRowsForRender(data, tableKey, rows, state, pageSize) {
    if (hasServerTable(data, tableKey)) {
      return rows;
    }

    const pageStart = (state.page - 1) * pageSize;
    return rows.slice(pageStart, pageStart + pageSize);
  }

  function applyTablePayload(target, tableKey, rowKey, payload, state) {
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
      state.page = Math.round(page);
    }

    return true;
  }
  const companyMetricDynamicsState = {
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

  function formatNumber(value) {
    return numberFormatter.format(Math.round(Number(value) || 0));
  }

  function formatPercent(value) {
    return `${Math.round(Number(value) || 0)}%`;
  }

  function formatDecimal(value, maxFractionDigits = 1) {
    return new Intl.NumberFormat("en-US", {
      minimumFractionDigits: 0,
      maximumFractionDigits: maxFractionDigits
    }).format(Number(value) || 0);
  }

  function formatSignedPercent(value) {
    const rounded = Math.round(Number(value) || 0);
    const prefix = rounded > 0 ? "+" : "";

    return `${prefix}${rounded}%`;
  }

  function formatSignedPp(value) {
    const rounded = Math.round(Number(value) || 0);
    const prefix = rounded > 0 ? "+" : "";

    return `${prefix}${rounded} pp`;
  }

  function formatDurationShort(totalSeconds) {
    const seconds = Math.max(0, Math.round(Number(totalSeconds) || 0));
    let days = Math.floor(seconds / 86400);
    let hours = Math.floor((seconds % 86400) / 3600);
    let minutes = Math.round((seconds % 3600) / 60);

    if (minutes === 60) {
      hours += 1;
      minutes = 0;
    }

    if (hours === 24) {
      days += 1;
      hours = 0;
    }

    if (days > 0) {
      return hours > 0 ? `${days}d ${hours}h` : `${days}d`;
    }

    if (hours > 0) {
      return minutes > 0 ? `${hours}h ${String(minutes).padStart(2, "0")}m` : `${hours}h`;
    }

    return `${minutes}m`;
  }

  function formatDateShort(value) {
    const date = new Date(`${value}T00:00:00Z`);

    if (Number.isNaN(date.getTime())) {
      return value || "";
    }

    return new Intl.DateTimeFormat("en-US", {
      month: "short",
      day: "numeric"
    }).format(date);
  }

  function clampPct(value) {
    return Math.max(0, Math.min(100, Number(value) || 0));
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

  function normalizeProductAreaName(area) {
    if (area && typeof area === "object") {
      return String(
        area.name ||
        area.productArea ||
        area.product_area_name ||
        area.product_area ||
        area.key ||
        area.slug ||
        ""
      ).trim() || "Unassigned";
    }

    return String(area || "").trim() || "Unassigned";
  }

  function syncProductAreaPalette(data) {
    const names = [];
    productAreaColorByName = new Map();
    productAreaColorResolver?.reset();
    const add = (area, color = "") => {
      const name = normalizeProductAreaName(area);

      if (!names.includes(name)) {
        names.push(name);
      }

      productAreaColorResolver?.add(area, color);
    };
    const addDistribution = (distribution) => {
      (distribution || []).forEach((item) => add(item.productArea || item.product_area_name || item.name, item.color));
    };
    const assignFallbackColors = () => {
      if (productAreaColorResolver) {
        productAreaColorResolver.finalize();
        names.forEach((name) => productAreaColorByName.set(name, productAreaColorResolver.color(name)));
        return;
      }

      names.forEach((name, index) => {
        if (productAreaColorByName.has(name)) {
          return;
        }

        productAreaColorByName.set(name, productAreaPalette[index % productAreaPalette.length]);
      });
    };

    (provider.productAreaOptions || []).forEach((area) => add(area));
    (provider.productAreas || []).forEach((area) => add(area));
    (currentOverviewData?.productAreaOptions || []).forEach((area) => add(area));
    (currentOverviewData?.productAreas || []).forEach((area) => add(area));
    assignFallbackColors();
    (data?.productAreas || []).forEach((area) => add(area));
    addDistribution(data?.company?.productAreaDistribution);
    (data?.companyOptions || []).forEach((company) => {
      (company.productAreas || []).forEach((area) => add(area));
      addDistribution(company.productAreaDistribution);
      (company.productAreaAdoption || []).forEach((cell) => add(cell.productArea, cell.color));
      add(company.topProductArea);
    });
    (data?.areaTreemap?.nodes || []).forEach((node) => {
      add(node.productArea || node.name, node.color);
      (node.children || []).forEach((child) => add(child.productArea || child.page_group || child.name, child.color || node.color));
    });
    (data?.adoptionBreadthSeries?.series || []).forEach((row) => add(row.productArea, row.color));
    (data?.topPages || []).forEach((row) => add(row.productArea, row.color));
    (data?.peerComparison?.rows || []).forEach((row) => {
      addDistribution(row.productAreaDistribution);
      (row.productAreaAdoption || []).forEach((cell) => add(cell.productArea, cell.color));
      add(row.topProductArea);
    });
    (data?.users || []).forEach((row) => {
      (row.productAreaAdoption || []).forEach((cell) => add(cell.productArea, cell.color));
      add(row.topArea);
    });

    assignFallbackColors();
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

  function tailwindAlpha(name, opacity) {
    return rgbaFromHex(tailwindColor(name), opacity);
  }

  function finiteNumericValues(values) {
    const output = [];
    const collect = (value) => {
      if (Array.isArray(value)) {
        value.forEach(collect);
        return;
      }

      const numericValue = Number(value);
      if (Number.isFinite(numericValue)) {
        output.push(numericValue);
      }
    };

    collect(values);
    return output;
  }

  function compactCeilAxisMax(value) {
    const numericValue = Math.max(Number(value) || 0, 1);
    const precisionPower = Math.floor(Math.log10(numericValue)) - 1;
    const precision = 10 ** precisionPower;

    return Math.ceil(numericValue / precision) * precision;
  }

  function compactAxisMax(values, options = {}) {
    const numbers = finiteNumericValues(values);
    const maxValue = Math.max(...numbers, Number(options.minimum) || 1);
    const headroom = Number.isFinite(Number(options.headroom)) ? Number(options.headroom) : 0.06;
    const minPadding = Number(options.minPadding) || 0;

    return compactCeilAxisMax(maxValue + Math.max(minPadding, maxValue * headroom));
  }

  function seriesMagnitude(values) {
    const numbers = finiteNumericValues(values).map((value) => Math.abs(value));

    return numbers.length ? Math.max(...numbers) : 0;
  }

  function isComparablePeerTrend(currentValues, peerValues) {
    const currentMagnitude = seriesMagnitude(currentValues);
    const peerMagnitude = seriesMagnitude(peerValues);

    if (!peerMagnitude) {
      return !currentMagnitude;
    }

    if (!currentMagnitude) {
      return false;
    }

    const ratio = peerMagnitude / currentMagnitude;

    return ratio >= 1 / peerTrendMagnitudeRatioLimit && ratio <= peerTrendMagnitudeRatioLimit;
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

  function chartUnavailable(element, message = "Chart library unavailable.") {
    if (!element) {
      return;
    }

    element.innerHTML = `<div class="company-detail-empty-chart">${escapeHtml(message)}</div>`;
  }

  function disposeMountedChart(element) {
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
  }

  function disposeVega(element) {
    if (element?.__hymetryVegaView) {
      element.__hymetryVegaView.finalize();
      element.__hymetryVegaView = null;
    }
  }

  function mountChart(element, option) {
    if (!element) {
      return null;
    }

    disposeMountedChart(element);
    disposeVega(element);

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
      const observer = new ResizeObserver(resize);
      observer.observe(element);
      element.__hymetryResizeObserver = observer;
    }

    return chart;
  }

  function setText(id, value) {
    const element = document.getElementById(id);

    if (element) {
      element.textContent = value;
    }
  }

  function statusBadge(status) {
    const rawKey = String(status || "").trim().replace(/\s+/g, "_").replace(/-/g, "_").toLowerCase();
    const companyKey = normalizeCompanyStatus(status);
    const userKey = normalizeUserStatus(status);
    const companyOnly = ["active", "activated", "new", "reactivated", "at_risk", "risk", "dormant"].includes(rawKey) ||
      (rawKey !== "dropped" && ["activated", "new", "reactivated", "at_risk", "dormant"].includes(companyKey));
    const meta = companyOnly ? getCompanyStatusMeta(status) : userStatusMeta[userKey] || getCompanyStatusMeta(status);

    return `<span class="companies-badge ${meta.badge}">${escapeHtml(meta.label)}</span>`;
  }

  function userHealthColor(status) {
    const segment = userHealthSegments.find(([segmentKey]) => segmentKey === status);

    return tailwindColor(segment?.[2] || "slate-500");
  }

  function productAreaColor(area, color = "") {
    const areaName = normalizeProductAreaName(area);

    if (productAreaColorResolver) {
      return productAreaColorResolver.color(area, color);
    }

    if (productAreaColorByName.has(areaName)) {
      return productAreaColorByName.get(areaName);
    }

    productAreaColorByName.set(areaName, productAreaPalette[productAreaColorByName.size % productAreaPalette.length] || visitsCircleColors[0]);
    return productAreaColorByName.get(areaName);
  }

  function productAreaDot(area, color = "") {
    return `<span class="companies-product-dot" style="background:${productAreaColor(area, color)}"></span>`;
  }

  function productAreaCell(area, color = "") {
    return `<span class="inline-flex items-center gap-2 whitespace-nowrap">${productAreaDot(area, color)}<span>${escapeHtml(area || "-")}</span></span>`;
  }

  function orderedAreaNames(areas) {
    const providerAreas = Array.isArray(provider.productAreas) ? provider.productAreas : [];
    const order = new Map(providerAreas.map((area, index) => [normalizeProductAreaName(area), index]));

    return Array.from(new Set((areas || []).map(normalizeProductAreaName).filter(Boolean))).sort((a, b) => {
      const aSecondary = secondaryAreaNamePattern.test(a) ? 1 : 0;
      const bSecondary = secondaryAreaNamePattern.test(b) ? 1 : 0;

      return aSecondary - bSecondary ||
        (order.get(a) ?? 999) - (order.get(b) ?? 999) ||
        String(a).localeCompare(String(b));
    });
  }

  function percentile(values, percentileValue) {
    const sorted = values
      .map((value) => Number(value) || 0)
      .filter((value) => value > 0)
      .sort((a, b) => a - b);

    if (!sorted.length) {
      return 0;
    }

    const index = (sorted.length - 1) * percentileValue;
    const lower = Math.floor(index);
    const upper = Math.ceil(index);

    if (lower === upper) {
      return sorted[lower];
    }

    return sorted[lower] + (sorted[upper] - sorted[lower]) * (index - lower);
  }

  function median(values) {
    const sorted = values
      .map((value) => Number(value))
      .filter(Number.isFinite)
      .sort((a, b) => a - b);
    const middle = Math.floor(sorted.length / 2);

    if (!sorted.length) {
      return 0;
    }

    return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
  }

  function productAreaUsageItems(row) {
    const sourceItems = Array.isArray(row.productAreaDistribution) && row.productAreaDistribution.length
      ? row.productAreaDistribution
      : [{ productArea: row.topProductArea || "Unknown", percent: 100 }];
    const totalEngagedSeconds = Math.max(0, Number(row.engagedSeconds) || 0);
    const totalVisits = Math.max(0, Number(row.visits) || 0);
    const itemsByArea = new Map();

    sourceItems.forEach((item) => {
      const area = normalizeProductAreaName(item.productArea || item.product_area_name || item.area || "Unknown");
      const percent = clampPct(item.percent);
      const engagedSeconds = Math.max(0, Number(item.engagedSeconds ?? item.engaged_seconds) || (totalEngagedSeconds * percent) / 100);
      const visitsValue = item.visits ?? item.visits_count;
      const visits = visitsValue == null ? Math.round((totalVisits * percent) / 100) : Math.max(0, Math.round(Number(visitsValue) || 0));
      const existing = itemsByArea.get(area) || { productArea: area, engagedSeconds: 0, visits: 0 };

      existing.engagedSeconds += engagedSeconds;
      existing.visits += visits;
      itemsByArea.set(area, existing);
    });

    return orderedAreaNames(Array.from(itemsByArea.keys()))
      .map((area) => itemsByArea.get(area))
      .filter((item) => item && item.engagedSeconds > 0);
  }

  function productAreaUsageTotal(row) {
    return productAreaUsageItems(row).reduce((sum, item) => sum + (Number(item.engagedSeconds) || 0), 0);
  }

  function productAreaUsageScaleMax(rows) {
    return Math.max(percentile((rows || []).map(productAreaUsageTotal), 0.95), 1);
  }

  function productAreaTooltipLabelWidthCh(usageItems) {
    const maxLabelLength = (usageItems || []).reduce((max, item) => {
      const label = String(item?.productArea || "Unknown");

      return Math.max(max, label.length);
    }, 0);

    return Math.min(Math.max(maxLabelLength + 1, 14), 28);
  }

  function productAreaUsageCell(row, scaleMax) {
    const usageItems = productAreaUsageItems(row);
    const totalUsageSeconds = usageItems.reduce((sum, item) => sum + item.engagedSeconds, 0);
    const safeScaleMax = Math.max(Number(scaleMax) || 0, totalUsageSeconds, 1);
    const barWidthPct = totalUsageSeconds ? Math.min((totalUsageSeconds / safeScaleMax) * 100, 100) : 0;
    const name = row.name || row.companyName || "Company";
    const tooltipId = `company-detail-area-mix-tooltip-${productAreaMixTooltipId}`;
    const maxAreaEngagedSeconds = Math.max(...usageItems.map((item) => Number(item.engagedSeconds) || 0), 1);
    const areaLabelWidthCh = productAreaTooltipLabelWidthCh(usageItems);

    productAreaMixTooltipId += 1;

    const tooltipRows = usageItems
      .map((item) => {
        const area = item.productArea || "Unknown";
        const share = totalUsageSeconds ? (item.engagedSeconds / totalUsageSeconds) * 100 : 0;
        const visits = Math.max(0, Math.round(Number(item.visits) || 0));
        const engagedBarWidth = item.engagedSeconds > 0
          ? Math.max(4, Math.round((item.engagedSeconds / maxAreaEngagedSeconds) * 56))
          : 0;

        return `
          <span class="companies-area-mix-tooltip__row companies-area-mix-tooltip__row--usage" style="--area-color:${productAreaColor(area)}; --area-engaged-width:${engagedBarWidth}px;">
            <span class="companies-area-mix-tooltip__dot"></span>
            <span class="companies-area-mix-tooltip__label">${escapeHtml(area)}</span>
            <span class="companies-area-mix-tooltip__metric companies-area-mix-tooltip__metric--engaged">
              <span class="companies-area-mix-tooltip__engaged-bar" aria-hidden="true"></span>
              <span>${escapeHtml(formatDurationShort(item.engagedSeconds))}</span>
            </span>
            <span class="companies-area-mix-tooltip__metric">${formatPercent(share)}</span>
            <span class="companies-area-mix-tooltip__metric">${formatNumber(visits)} ${visits === 1 ? "visit" : "visits"}</span>
          </span>
        `;
      })
      .join("");
    const segments = usageItems
      .map((item) => {
        const area = item.productArea || "Unknown";
        const percent = totalUsageSeconds ? (item.engagedSeconds / totalUsageSeconds) * 100 : 0;

        return `<span class="companies-area-mix__segment" style="--area-color:${productAreaColor(area)}; flex: 0 0 ${percent}%"></span>`;
      })
      .join("");
    const ariaLabel = `${name} area usage. ${usageItems
      .map((item) => `${item.productArea} ${formatDurationShort(item.engagedSeconds)} ${formatPercent(totalUsageSeconds ? (item.engagedSeconds / totalUsageSeconds) * 100 : 0)}`)
      .join(", ")}. Total ${formatDurationShort(totalUsageSeconds)}. Areas used ${usageItems.length}.`;

    return `
      <div class="companies-area-mix companies-area-usage metric-header-tooltip" data-tooltip-kind="area-mix" data-has-usage="${totalUsageSeconds > 0}" style="--area-usage-width:${barWidthPct}%; --area-tooltip-label-width:${areaLabelWidthCh}ch;" tabindex="0" aria-label="${escapeHtml(ariaLabel)}" aria-describedby="${tooltipId}">
        <span class="companies-area-usage__bar">${segments}</span>
        <span id="${tooltipId}" class="metric-header-tooltip__content" role="tooltip">
          <span class="companies-area-mix-tooltip__title">${escapeHtml(name)}</span>
          ${tooltipRows || `<span class="companies-area-mix-tooltip__row"><span></span><span class="companies-area-mix-tooltip__label">No usage</span><span class="companies-area-mix-tooltip__value">0m</span></span>`}
          <span class="companies-area-mix-tooltip__summary">
            <span class="companies-area-mix-tooltip__summary-row"><span>Total</span><strong>${escapeHtml(formatDurationShort(totalUsageSeconds))}</strong></span>
            <span class="companies-area-mix-tooltip__summary-row"><span>Areas used</span><strong>${formatNumber(usageItems.length)}</strong></span>
          </span>
        </span>
      </div>
    `;
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
    const tooltipId = `company-detail-adoption-cell-tooltip-${adoptionCellTooltipId}`;
    const name = row.name || row.companyName || row.userName || row.name || "User";
    const areaName = cell.productArea || "Area";
    const used = areaCoverageCellUsed(cell);
    const relativeActivityPct = adoptionCellRelativeActivityPct(cell, maxEngagedSeconds);
    const usageLabel = used && relativeActivityPct <= 0 ? adoptionCellIntensityGrade(1).label : adoptionCellUsageLabel(relativeActivityPct);
    const relativeActivityLabel = formatPercent(relativeActivityPct);

    adoptionCellTooltipId += 1;

    if (!used) {
      return {
        tooltipId,
        tooltipText: `${name}. ${areaName}. Not used yet. Relative activity ${relativeActivityLabel}. ${usageLabel}.`,
        tooltipHtml: `
          <span class="companies-adoption-cell-tooltip__title">${escapeHtml(name)}</span>
          <span class="companies-adoption-cell-tooltip__row"><span>Area</span><strong>${escapeHtml(areaName)}</strong></span>
          <span class="companies-adoption-cell-tooltip__row"><span>Relative activity</span><strong>${escapeHtml(relativeActivityLabel)}</strong></span>
          <span class="companies-adoption-cell-tooltip__row"><span>Usage intensity</span><strong>${escapeHtml(usageLabel)}</strong></span>
          <span class="companies-adoption-cell-tooltip__row"><span>Engaged time</span><strong>${escapeHtml(formatDurationShort(cell.engagedSeconds))}</strong></span>
          <span class="companies-adoption-cell-tooltip__row"><span>Visits</span><strong>${formatNumber(cell.visits)}</strong></span>
          <span class="companies-adoption-cell-tooltip__row"><span>Pages/features</span><strong>${formatNumber(cell.pagesUsed)}</strong></span>
        `
      };
    }

    return {
      tooltipId,
      tooltipText: `${name}. ${areaName}. Used during selected period. Relative activity ${relativeActivityLabel}. ${usageLabel}.`,
      tooltipHtml: `
        <span class="companies-adoption-cell-tooltip__title">${escapeHtml(name)}</span>
        <span class="companies-adoption-cell-tooltip__row"><span>Area</span><strong>${escapeHtml(areaName)}</strong></span>
        <span class="companies-adoption-cell-tooltip__row"><span>Relative activity</span><strong>${escapeHtml(relativeActivityLabel)}</strong></span>
        <span class="companies-adoption-cell-tooltip__row"><span>Usage intensity</span><strong>${escapeHtml(usageLabel)}</strong></span>
        <span class="companies-adoption-cell-tooltip__row"><span>Engaged time</span><strong>${escapeHtml(formatDurationShort(cell.engagedSeconds))}</strong></span>
        <span class="companies-adoption-cell-tooltip__row"><span>Visits</span><strong>${formatNumber(cell.visits)}</strong></span>
        <span class="companies-adoption-cell-tooltip__row"><span>Pages/features</span><strong>${formatNumber(cell.pagesUsed)}</strong></span>
      `
    };
  }

  function adoptionMatrixCell(cell, row, maxEngagedSeconds) {
    const tooltip = adoptionCellTooltip(cell, row, maxEngagedSeconds);
    const used = areaCoverageCellUsed(cell);

    if (!used) {
      return `
        <span class="companies-adoption-cell metric-header-tooltip" data-tooltip-kind="adoption-cell" data-used="false" tabindex="0" aria-label="${escapeHtml(tooltip.tooltipText)}" aria-describedby="${tooltip.tooltipId}">
          <span id="${tooltip.tooltipId}" class="metric-header-tooltip__content" role="tooltip">${tooltip.tooltipHtml}</span>
        </span>
      `;
    }

    const intensity = adoptionCellColorOpacity(adoptionCellRelativeActivityPct(cell, maxEngagedSeconds));
    const color = productAreaColor(cell.productArea, cell.color);

    return `
      <span
        class="companies-adoption-cell metric-header-tooltip"
        data-tooltip-kind="adoption-cell"
        data-used="true"
        style="--area-bg-color:${rgbaFromHex(color, intensity)};"
        tabindex="0"
        aria-label="${escapeHtml(tooltip.tooltipText)}"
        aria-describedby="${tooltip.tooltipId}">
        <span id="${tooltip.tooltipId}" class="metric-header-tooltip__content" role="tooltip">${tooltip.tooltipHtml}</span>
      </span>
    `;
  }

  function adoptionMatrixCellGroup(row, maxEngagedSeconds) {
    const cellsByArea = new Map((row.productAreaAdoption || []).map((cell) => [cell.productArea, cell]));
    const areas = orderedAreaNames(provider.productAreas || []);

    return `
      <div class="companies-adoption-matrix" aria-label="${escapeHtml(`${row.name || row.companyName || "Row"} areas used`)}">
        ${areas
          .map((area) => adoptionMatrixCell(cellsByArea.get(area) || {
            productArea: area,
            used: false,
            engagedSeconds: 0,
            visits: 0,
            activeUsers: 0,
            pagesUsed: 0
          }, row, maxEngagedSeconds))
          .join("")}
      </div>
    `;
  }

  function formatValueByType(value, valueType) {
    if (valueType === "duration") {
      return formatDurationShort(value);
    }

    if (valueType === "percent") {
      return formatPercent(value);
    }

    if (valueType === "ratio") {
      return Number(value || 0).toFixed(1);
    }

    return formatNumber(value);
  }

  function metricDeltaClass(direction) {
    if (direction === "positive") {
      return "text-green-700";
    }

    if (direction === "negative") {
      return "text-red-600";
    }

    return "text-slate-700";
  }

  function seriesActualValues(dailySeries) {
    return Array.isArray(dailySeries)
      ? dailySeries.map((point) => {
          if (point?.value === null || point?.value === undefined || point?.value === "") {
            return null;
          }

          const numericValue = Number(point.value);
          return Number.isFinite(numericValue) ? numericValue : null;
        })
      : [];
  }

  function seriesDates(dailySeries) {
    return Array.isArray(dailySeries) ? dailySeries.map((point) => point.date) : [];
  }

  function metricTooltipLineSample(color, dashed = false) {
    const background = dashed
      ? `repeating-linear-gradient(to right, ${color} 0 6px, transparent 6px 10px)`
      : color;

    return `<span style="display:inline-block;width:22px;height:2px;border-radius:999px;background:${background};flex:0 0 22px;"></span>`;
  }

  function formatDurationWithSeconds(totalSeconds) {
    const seconds = Math.max(0, Math.round(Number(totalSeconds) || 0));

    if (seconds >= 3600) {
      return formatDurationShort(seconds);
    }

    const minutes = Math.floor(seconds / 60);
    const remainingSeconds = seconds % 60;

    if (minutes > 0) {
      return `${minutes}m ${String(remainingSeconds).padStart(2, "0")}s`;
    }

    return `${remainingSeconds}s`;
  }

  function formatMetricTooltipValueByType(value, valueType) {
    if (valueType === "duration") {
      return formatDurationWithSeconds(value);
    }

    return formatValueByType(value, valueType);
  }

  function metricTooltipRow(label, value, valueType, options = {}) {
    const lineSample = options.color
      ? metricTooltipLineSample(options.color, Boolean(options.dashed))
      : "";
    const displayValue = Number.isFinite(value) ? formatMetricTooltipValueByType(value, valueType) : "-";

    return `
      <div style="display:flex;gap:16px;justify-content:space-between;min-width:220px;">
        <span style="display:inline-flex;align-items:center;gap:8px;min-width:0;">
          ${lineSample}
          <span>${escapeHtml(label)}</span>
        </span>
        <strong>${escapeHtml(displayValue)}</strong>
      </div>
    `;
  }

  function metricTooltipPeerRows(peerSeriesList, index, valueType) {
    if (!peerSeriesList.length) {
      return "";
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
      .map((peer) => metricTooltipRow(peer.name || "Peer", peer.value, valueType, { color: tailwindAlpha("slate-400", 0.55) }))
      .join("");

    return `<div style="margin-top:6px;padding-top:2px;">${peerRows}</div>`;
  }

  function companyMetricDynamicsShowPeers() {
    const section = document.querySelector("[data-company-metric-dynamics-section]");
    if (section?.dataset.companyMetricDynamicsShowPeers !== undefined) {
      return section.dataset.companyMetricDynamicsShowPeers === "true";
    }

    return companyMetricDynamicsState.showPeers;
  }

  function createMiniMetricChartOption(metric, options = {}) {
    const dates = seriesDates(metric.dailySeries);
    const currentValues = seriesActualValues(metric.dailySeries);
    const dynamics = buildMetricDynamicsSeries({
      currentSeries: metric.dailySeries,
      benchmarkSeries: metric.benchmarkSeries,
      benchmarkEligiblePeerCount: metric.benchmarkEligiblePeerCount,
      peerSeriesList: metric.peerSeries,
      metricType: metric.key || metric.valueType,
      selectedPeriodDays: options.selectedPeriodDays,
      showPeers: options.showPeers,
      currentEntityId: metric.companyId || metric.id,
      minPeerCount: 3
    });
    const actualSeries = dynamics.actualSeries || dynamics.current || currentValues;
    const currentTrendSeries = dynamics.currentStraightTrendSeries || dynamics.currentTrend || [];
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
      tooltip: {
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
          const actualValue = currentValues[index];
          const trendValue = currentTrendSeries[index];
          const benchmarkValue = benchmarkTrendSeries[index];

          return `
            <div>
              <div style="font-weight:600;margin-bottom:6px;">${escapeHtml(formatDateShort(dates[index]))}</div>
              ${metricTooltipRow("Actual", actualValue, metric.valueType, { color: chartTheme.colors.primary })}
              ${Number.isFinite(trendValue) ? metricTooltipRow("Current trend", trendValue, metric.valueType, { color: chartTheme.colors.primary, dashed: true }) : ""}
              ${Number.isFinite(benchmarkValue) ? metricTooltipRow("Other companies trend", benchmarkValue, metric.valueType, { color: chartTheme.colors.warning, dashed: true }) : ""}
              ${metricTooltipPeerRows(peerSeriesList, index, metric.valueType)}
              ${!benchmarkTrendSeries.length && dynamics.benchmarkUnavailableReason ? `<div style="margin-top:6px;color:${chartTheme.colors.mutedText};">${escapeHtml(dynamics.benchmarkUnavailableReason)}</div>` : ""}
            </div>
          `;
        }
      },
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
          name: "Other companies trend",
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
            name: "Actual",
            type: "line",
            data: actualSeries,
            smooth: true,
            symbol: "none",
            lineStyle: {
              color: chartTheme.colors.primary,
              width: 2.5
            },
            areaStyle: {
              color: tailwindAlpha("c-blue", 0.08)
            },
            emphasis: {
              disabled: true
            },
            z: 5
          }
        ].filter(Boolean))
    };
  }

  const companyMetricDynamicsDescriptions = {
    activeUsers: "Number of users active in this company during the selected period",
    newReactivatedUsers: "Users who are new or reactivated during the selected period",
    visits: "Number of page visits by this company during the selected period",
    engaged: "Total active time spent by this company's users",
    avgPerUser: "Average active time per active user",
    interaction: "Share of visits with at least one click",
    adoptionBreadth: "Number of product areas and pages used by this company",
    atRiskUsers: "Users showing reduced or at-risk engagement signals"
  };

  function metricDynamicsTooltipId(scope, key, index) {
    return `${scope}-metric-dynamics-title-${String(key || index).replace(/[^a-z0-9_-]+/gi, "-").toLowerCase()}`;
  }

  function metricDynamicsTitleMarkup(metric, scope, index) {
    const key = metric?.key || index;
    const label = metric?.label || "Metric";
    const description = companyMetricDynamicsDescriptions[key] || "Metric value during the selected period";
    const tooltipId = metricDynamicsTooltipId(scope, key, index);

    return `
      <span class="metric-header-tooltip metric-dynamics-title-tooltip" tabindex="0" aria-describedby="${escapeHtml(tooltipId)}">
        ${escapeHtml(label)}
        <span id="${escapeHtml(tooltipId)}" class="metric-header-tooltip__content" role="tooltip">${escapeHtml(description)}</span>
      </span>
    `;
  }

  function metricPanelMarkup(metric, index) {
    return `
      <article class="min-h-[164px] bg-white px-5 py-4">
        <div class="flex items-center justify-between gap-3">
          <div class="min-w-0 text-sm font-medium uppercase text-slate-500">${metricDynamicsTitleMarkup(metric, "company", index)}</div>
          <div class="flex shrink-0 items-center gap-2 text-right font-medium">
            <div class="whitespace-nowrap text-base font-semibold text-slate-900">${escapeHtml(formatValueByType(metric.value, metric.valueType))}</div>
            <div class="whitespace-nowrap text-sm font-medium ${metricDeltaClass(metric.deltaDirection)}">${escapeHtml(metric.formattedDelta || "-")}</div>
          </div>
        </div>
        <div data-company-metric-chart-index="${index}" class="mt-3 h-[92px] w-full"></div>
      </article>
    `;
  }

  function companyMetricDynamicsElements() {
    const grid = document.getElementById("company-metric-dynamics-grid");

    return {
      shell: document.querySelector("[data-company-metric-dynamics-shell]"),
      grid,
      overlay: document.querySelector("[data-company-metric-dynamics-loading]"),
      toggle: document.querySelector("[data-company-metric-dynamics-show-peers]")
    };
  }

  function setCompanyMetricDynamicsLoading(isLoading) {
    companyMetricDynamicsState.isLoading = Boolean(isLoading);
    setMetricDynamicsLoadingState(companyMetricDynamicsElements(), companyMetricDynamicsState.isLoading);
  }

  function mountCompanyMetricDynamicsToggle() {
    const { toggle } = companyMetricDynamicsElements();

    if (!toggle) {
      return;
    }

    companyMetricDynamicsState.showPeers = companyMetricDynamicsShowPeers();
    toggle.checked = companyMetricDynamicsState.showPeers;
    toggle.disabled = companyMetricDynamicsState.isLoading;

    if (toggle.dataset.metricDynamicsMounted === "true") {
      return;
    }

    toggle.dataset.metricDynamicsMounted = "true";
    toggle.addEventListener("change", () => {
      const nextShowPeers = toggle.checked;
      companyMetricDynamicsState.showPeers = nextShowPeers;

      try {
        globalScope.localStorage?.setItem("hymetry.company_details.show_peers", nextShowPeers ? "1" : "0");
      } catch (error) {
        // Local storage is optional; the server-rendered HTMX state remains authoritative.
      }

      if (globalScope.htmx) {
        return;
      }

      const token = companyMetricDynamicsState.loadingToken + 1;
      const section = document.querySelector("[data-company-metric-dynamics-section]");
      companyMetricDynamicsState.loadingToken = token;
      if (section?.dataset) {
        section.dataset.companyMetricDynamicsShowPeers = String(nextShowPeers);
      }

      setCompanyMetricDynamicsLoading(true);

      globalScope.setTimeout(() => {
        if (token !== companyMetricDynamicsState.loadingToken) {
          return;
        }

        setCompanyMetricDynamicsLoading(false);

        if (currentDetailData) {
          renderMetricDynamics(currentDetailData);
        }
      }, 380);
    });
  }

  function renderMetricDynamics(data) {
    const container = document.getElementById("company-metric-dynamics-grid");

    if (!container) {
      return;
    }

    mountCompanyMetricDynamicsToggle();

    const metrics = Array.isArray(data.metricCards) ? data.metricCards.slice(0, 8) : [];
    const chartOptions = {
      selectedPeriodDays: data.period?.days,
      showPeers: companyMetricDynamicsShowPeers()
    };

    if (metrics.length !== 8) {
      container.innerHTML = `<div class="col-span-full bg-white px-6 py-10 text-center text-slate-500">No company metrics found for this period.</div>`;
      return;
    }

    container.innerHTML = metrics.map(metricPanelMarkup).join("");
    metrics.forEach((metric, index) => {
      mountChart(container.querySelector(`[data-company-metric-chart-index="${index}"]`), createMiniMetricChartOption(metric, chartOptions));
    });
  }

  function createAreaTreemapOption(data) {
    const treemapData = data.areaTreemap || { totalEngagedSeconds: 0, nodes: [] };
    const totalEngagedSeconds = treemapData.totalEngagedSeconds || 1;
    const labelMinShare = 1.6;
    const hoverTintWeight = 0.04;
    const treemapNodeStyle = (color) => ({
      itemStyle: {
        color
      },
      emphasis: {
        itemStyle: {
          color: mixHexColors(color, chartTheme.colors.white, hoverTintWeight),
          borderColor: chartTheme.colors.white,
          shadowBlur: 0,
          shadowColor: "transparent"
        }
      }
    });
    const treemapNodes = (treemapData.nodes || []).map((groupNode) => {
      const groupColor = productAreaColor(groupNode.productArea || groupNode.name, groupNode.color);

      return {
        ...groupNode,
        ...treemapNodeStyle(groupColor),
        children: (groupNode.children || []).map((childNode) => {
          const childColor = productAreaColor(childNode.productArea || childNode.page_group || groupNode.productArea || groupNode.name, childNode.color || groupNode.color);

          return {
            ...childNode,
            ...treemapNodeStyle(childColor)
          };
        })
      };
    });

    return {
      tooltip: {
        trigger: "item",
        confine: true,
        formatter: (params) => {
          const node = params.data || {};
          const isGroup = Boolean(node.isGroup || node.children?.length);
          const productArea = node.productArea || node.page_group || node.name || "Unassigned";
          const share = ((node.engagedSeconds || 0) / totalEngagedSeconds) * 100;

          return `
            <div>
              <div style="font-weight:600;margin-bottom:6px;">${escapeHtml(node.name || params.name)}</div>
              <div>Product area: <strong>${escapeHtml(productArea)}</strong></div>
              ${isGroup ? `<div>Pages: <strong>${formatNumber(node.pageCount || node.children?.length || 0)}</strong></div>` : ""}
              <div>Engaged time: <strong>${escapeHtml(formatDurationShort(node.engagedSeconds))}</strong></div>
              <div>Visits: <strong>${formatNumber(node.visits || 0)}</strong></div>
              <div>Active users: <strong>${formatNumber(node.activeUsers || 0)}</strong></div>
              <div>Share of company time: <strong>${share.toFixed(1)}%</strong></div>
            </div>
          `;
        }
      },
      series: [
        {
          type: "treemap",
          animation: false,
          roam: false,
          nodeClick: false,
          breadcrumb: {
            show: false
          },
          top: 8,
          right: 8,
          bottom: 8,
          left: 8,
          visibleMin: 80,
          childrenVisibleMin: 18,
          squareRatio: 1.25,
          data: treemapNodes,
          label: {
            show: true,
            color: chartTheme.colors.white,
            fontSize: 11,
            lineHeight: 15,
            textBorderColor: tailwindAlpha("slate-900", 0.24),
            textBorderWidth: 2,
            overflow: "truncate",
            formatter: (params) => {
              const node = params.data || {};
              const share = ((node.engagedSeconds || 0) / totalEngagedSeconds) * 100;

              if (node.isGroup || node.children?.length || share < labelMinShare) {
                return "";
              }

              return `${params.name}\n${formatDurationShort(node.engagedSeconds)}`;
            }
          },
          upperLabel: {
            show: true,
            height: 28,
            color: chartTheme.colors.white,
            fontSize: 12,
            fontWeight: 600,
            overflow: "truncate",
            formatter: (params) => params.name
          },
          itemStyle: {
            borderColor: chartTheme.colors.white,
            borderWidth: 2,
            gapWidth: 2
          },
          emphasis: {
            focus: "none",
            itemStyle: {
              borderColor: chartTheme.colors.white,
              shadowBlur: 0,
              shadowColor: "transparent"
            }
          },
          blur: {
            itemStyle: {
              opacity: 1
            },
            label: {
              opacity: 1
            },
            upperLabel: {
              opacity: 1
            }
          },
          levels: [
            {
              itemStyle: {
                borderColor: chartTheme.colors.white,
                borderWidth: 2,
                gapWidth: 2
              },
              upperLabel: {
                show: false
              }
            },
            {
              itemStyle: {
                borderColor: chartTheme.colors.white,
                borderWidth: 3,
                gapWidth: 3
              },
              upperLabel: {
                show: true
              },
              label: {
                show: false
              }
            },
            {
              itemStyle: {
                borderColor: chartTheme.colors.white,
                borderWidth: 1,
                gapWidth: 1
              }
            }
          ]
        }
      ]
    };
  }

  function getLastNumericValue(values) {
    if (!Array.isArray(values)) {
      return 0;
    }

    for (let index = values.length - 1; index >= 0; index -= 1) {
      const value = Number(values[index]);

      if (Number.isFinite(value)) {
        return value;
      }
    }

    return 0;
  }

  function getAdoptionBreadthValueExtent(seriesRows) {
    const maxValue = Math.max(
      ...seriesRows.flatMap((row) => (Array.isArray(row.values) ? row.values.map((value) => Number(value) || 0) : [])),
      1
    );

    return {
      min: 0,
      max: compactAxisMax(maxValue)
    };
  }

  function layoutAdoptionEndLabels(labelRows, valueExtent, layout = {}) {
    const valueRange = Math.max(valueExtent.max - valueExtent.min, 1);
    const plotHeight = layout.plotHeight || 338;
    const labelPadding = layout.labelPadding || 8;
    const desiredLabelGap = layout.labelGap || 18;
    const valueToY = (value) => ((valueExtent.max - value) / valueRange) * plotHeight;
    const yToValue = (y) => valueExtent.max - (y / plotHeight) * valueRange;
    const labels = labelRows
      .map((row, index) => ({
        index,
        idealY: valueToY(getLastNumericValue(row.values)),
        y: valueToY(getLastNumericValue(row.values))
      }))
      .sort((a, b) => a.idealY - b.idealY);
    const maxLabelGap = labels.length > 1 ? (plotHeight - labelPadding * 2) / (labels.length - 1) : desiredLabelGap;
    const labelGap = Math.max(12, Math.min(desiredLabelGap, maxLabelGap));

    labels.forEach((label, index) => {
      if (index === 0) {
        label.y = Math.max(labelPadding, label.y);
        return;
      }

      label.y = Math.max(label.y, labels[index - 1].y + labelGap);
    });

    const overflow = labels.length ? labels[labels.length - 1].y - (plotHeight - labelPadding) : 0;

    if (overflow > 0) {
      labels.forEach((label) => {
        label.y -= overflow;
      });

      for (let index = labels.length - 2; index >= 0; index -= 1) {
        labels[index].y = Math.min(labels[index].y, labels[index + 1].y - labelGap);
      }
    }

    const underflow = labels.length ? labelPadding - labels[0].y : 0;

    if (underflow > 0) {
      labels.forEach((label) => {
        label.y += underflow;
      });
    }

    return labels.reduce((lookup, label) => {
      lookup[label.index] = yToValue(label.y);
      return lookup;
    }, {});
  }

  function createAdoptionBreadthOption(data) {
    const adoption = data.adoptionBreadthSeries || { dates: [], series: [] };
    const dates = adoption.dates || [];
    const seriesRows = adoption.series || [];
    const labelSpacerCategory = "";
    const xAxisLabels = dates.concat(labelSpacerCategory);
    const labelSeriesSuffix = " label connector";
    const valueExtent = getAdoptionBreadthValueExtent(seriesRows);
    const labelValuesBySeriesIndex = layoutAdoptionEndLabels(seriesRows, valueExtent);
    const lineSeries = seriesRows.map((row) => {
      const color = productAreaColor(row.productArea, row.color);
      const values = Array.isArray(row.values) ? row.values : [];

      return {
        name: row.productArea,
        type: "line",
        smooth: true,
        showSymbol: false,
        symbol: "circle",
        symbolSize: 5,
        lineStyle: {
          color,
          width: 2
        },
        itemStyle: {
          color
        },
        emphasis: {
          focus: "series"
        },
        data: values.concat(null)
      };
    });
    const connectorSeries = seriesRows.map((row, index) => {
      const color = productAreaColor(row.productArea, row.color);
      const lastValue = getLastNumericValue(row.values);
      const labelValue = labelValuesBySeriesIndex[index] ?? lastValue;
      const connectorData = Array.from({ length: xAxisLabels.length }, () => null);

      connectorData[Math.max(xAxisLabels.length - 2, 0)] = lastValue;
      connectorData[Math.max(xAxisLabels.length - 1, 0)] = labelValue;

      return {
        name: `${row.productArea}${labelSeriesSuffix}`,
        type: "line",
        animation: false,
        silent: true,
        showSymbol: false,
        connectNulls: false,
        data: connectorData,
        tooltip: {
          show: false
        },
        endLabel: {
          show: true,
          distance: 8,
          color: readableSeriesLabelColor(color),
          fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif",
          fontSize: 12,
          fontWeight: "500",
          width: 116,
          overflow: "truncate",
          formatter: () => row.productArea
        },
        lineStyle: {
          color,
          type: "dotted",
          opacity: 0.72,
          width: 1.5
        },
        emphasis: {
          disabled: true
        },
        z: 6
      };
    });

    return {
      color: seriesRows.map((row) => productAreaColor(row.productArea, row.color)),
      tooltip: {
        trigger: "axis",
        confine: true,
        axisPointer: {
          type: "line"
        },
        formatter: (params) => {
          const items = (Array.isArray(params) ? params : [params]).filter((item) => !String(item.seriesName || "").endsWith(labelSeriesSuffix));
          const index = items[0]?.dataIndex || 0;
          const rows = items
            .filter((item) => Number(item.value) > 0)
            .sort((a, b) => (Number(b.value) || 0) - (Number(a.value) || 0))
            .map((item) => {
              return `<div style="display:flex;gap:16px;justify-content:space-between;min-width:210px;"><span>${item.marker}${escapeHtml(item.seriesName)}</span><strong>${escapeHtml(formatDurationShort(item.value))}</strong></div>`;
            })
            .join("");

          return `
            <div>
              <div style="font-weight:600;margin-bottom:6px;">${escapeHtml(formatDateShort(dates[index]))}</div>
              ${rows || "<div>No engaged time yet</div>"}
            </div>
          `;
        }
      },
      grid: {
        left: 56,
        right: 138,
        top: 20,
        bottom: 42
      },
      xAxis: {
        type: "category",
        boundaryGap: false,
        data: xAxisLabels,
        axisLine: { lineStyle: { color: chartTheme.colors.axis } },
        axisLabel: {
          color: chartTheme.colors.mutedText,
          formatter: (value) => formatDateShort(value)
        }
      },
      yAxis: {
        type: "value",
        name: "Total engaged time",
        min: valueExtent.min,
        max: valueExtent.max,
        nameTextStyle: { color: chartTheme.colors.mutedText },
        axisLine: { show: true, lineStyle: { color: chartTheme.colors.axis } },
        axisTick: { show: false },
        axisLabel: {
          color: chartTheme.colors.mutedText,
          formatter: (value) => formatDurationShort(value)
        },
        splitLine: { show: false }
      },
      series: lineSeries.concat(connectorSeries)
    };
  }

  function renderProductAreaCharts(data) {
    const treemapElement = document.getElementById("company-area-treemap-chart");
    const adoptionElement = document.getElementById("company-adoption-breadth-chart");

    if (treemapElement) {
      if (!data.areaTreemap?.nodes?.length) {
        treemapElement.innerHTML = `<div class="company-detail-empty-chart">No page usage in this period.</div>`;
      } else {
        mountChart(treemapElement, createAreaTreemapOption(data));
      }
    }

    if (adoptionElement) {
      if (!data.adoptionBreadthSeries?.series?.length) {
        adoptionElement.innerHTML = `<div class="company-detail-empty-chart">No product area usage in this period.</div>`;
      } else {
        mountChart(adoptionElement, createAdoptionBreadthOption(data));
      }
    }
  }

  function buildCompanyHealthDistributionSegments(rows) {
    const total = rows.reduce((sum, item) => sum + Math.max(0, Number(item.count) || 0), 0) || 1;
    const minPct = 4.5;
    const rawSegments = rows.map((item) => {
      const rawPct = (Math.max(0, Number(item.count) || 0) / total) * 100;

      return {
        item,
        rawPct,
        isSmall: rawPct < minPct
      };
    });
    const smallSegments = rawSegments.filter((segment) => segment.isSmall);
    const regularSegments = rawSegments.filter((segment) => !segment.isSmall);
    const smallPctTotal = Math.min(42, smallSegments.length * minPct);
    const regularRawTotal = regularSegments.reduce((sum, segment) => sum + segment.rawPct, 0) || 1;
    const regularPctTotal = Math.max(0, 100 - smallPctTotal);
    const smallPct = smallSegments.length ? smallPctTotal / smallSegments.length : 0;
    let cursor = 0;

    return rawSegments.map((segment) => {
      const { item } = segment;
      const status = normalizeUserStatus(item.status || "healthy");
      const meta = userStatusMeta[status] || userStatusMeta.healthy;
      const widthPct = segment.isSmall ? smallPct : (segment.rawPct / regularRawTotal) * regularPctTotal;
      const x0 = cursor;
      const x1 = cursor + widthPct;
      const label = item.label || meta.label || status;
      const labelText = widthPct < 5.5
        ? formatNumber(item.count)
        : `${label}\n${formatNumber(item.count)}`;

      cursor = x1;

      return {
        status,
        label,
        count: Math.max(0, Math.round(Number(item.count) || 0)),
        pct: Number(item.pct) || 0,
        pctLabel: `${Number(item.pct) || 0}%`,
        definition: meta.definition,
        color: userHealthColor(status),
        x0,
        x1,
        widthPct,
        labelText,
        value: [x0, x1, 0]
      };
    });
  }

  function createCompanyHealthDistributionOption(data) {
    const rows = data.companyHealthDistribution || [];
    const segments = buildCompanyHealthDistributionSegments(rows);

    return {
      animation: false,
      tooltip: {
        trigger: "item",
        confine: true,
        backgroundColor: chartTheme.colors.white,
        borderColor: tailwindColor("slate-200"),
        borderWidth: 1,
        padding: [8, 12],
        textStyle: {
          color: chartTheme.colors.text,
          fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif",
          fontSize: 12
        },
        extraCssText: [
          "border-radius:6px",
          "box-shadow:0 4px 6px -1px rgba(15,23,42,0.10),0 2px 4px -1px rgba(15,23,42,0.06)"
        ].join(";"),
        formatter: (params) => {
          const item = params.data || {};

          return `
            <table style="border-collapse:collapse;margin:0;font-family:Inter,ui-sans-serif,system-ui,sans-serif;font-size:12px;line-height:1.35;">
              <tbody>
                <tr>
                  <td style="padding:2px 6px 2px 0;text-align:right;color:${chartTheme.colors.mutedText};white-space:nowrap;">User status</td>
                  <td style="padding:2px 0;color:${chartTheme.colors.text};font-weight:500;">${escapeHtml(item.label || "")}</td>
                </tr>
                <tr>
                  <td style="padding:2px 6px 2px 0;text-align:right;color:${chartTheme.colors.mutedText};white-space:nowrap;">Users</td>
                  <td style="padding:2px 0;color:${chartTheme.colors.text};font-weight:600;">${formatNumber(item.count || 0)}</td>
                </tr>
                <tr>
                  <td style="padding:2px 6px 2px 0;text-align:right;color:${chartTheme.colors.mutedText};white-space:nowrap;">Share</td>
                  <td style="padding:2px 0;color:${chartTheme.colors.text};font-weight:600;">${escapeHtml(item.pctLabel || "0%")}</td>
                </tr>
                <tr>
                  <td style="padding:2px 6px 2px 0;text-align:right;color:${chartTheme.colors.mutedText};white-space:nowrap;vertical-align:top;">Definition</td>
                  <td style="padding:2px 0;color:${chartTheme.colors.text};max-width:260px;white-space:normal;">${escapeHtml(item.definition || "")}</td>
                </tr>
              </tbody>
            </table>
          `;
        }
      },
      grid: {
        left: 0,
        right: 0,
        top: 8,
        bottom: 8
      },
      xAxis: {
        type: "value",
        min: 0,
        max: 100,
        show: false
      },
      yAxis: {
        type: "category",
        data: [""],
        show: false
      },
      series: [
        {
          type: "custom",
          data: segments,
          renderItem: (params, api) => {
            const item = segments[params.dataIndex] || {};
            const start = api.coord([api.value(0), 0]);
            const end = api.coord([api.value(1), 0]);
            const x = start[0];
            const width = Math.max(1, end[0] - start[0]);
            const height = 64;
            const y = start[1] - height / 2;
            const fontSize = width < 48 ? 11 : 12;

            return {
              type: "group",
              children: [
                {
                  type: "rect",
                  shape: {
                    x,
                    y,
                    width,
                    height,
                    r: 5
                  },
                  style: {
                    fill: item.color,
                    opacity: 0.66,
                    stroke: chartTheme.colors.white,
                    lineWidth: 2
                  },
                  emphasis: {
                    style: {
                      opacity: 0.78,
                      lineWidth: 3
                    }
                  }
                },
                {
                  type: "text",
                  silent: true,
                  style: {
                    x: x + width / 2,
                    y: y + height / 2,
                    text: item.labelText,
                    fill: "#000000",
                    font: `500 ${fontSize}px Inter, ui-sans-serif, system-ui, sans-serif`,
                    lineHeight: 15,
                    align: "center",
                    textAlign: "center",
                    verticalAlign: "middle",
                    textVerticalAlign: "middle",
                    width: Math.max(8, width - 8),
                    overflow: "truncate"
                  }
                }
              ]
            };
          }
        }
      ]
    };
  }

  function renderCompanyHealthDistribution(data) {
    const element = document.getElementById("company-health-distribution-echarts");

    if (!element) {
      return;
    }

    if (!data.companyHealthDistribution?.length) {
      if (element.__hymetryChart) {
        element.__hymetryChart.dispose();
        element.__hymetryChart = null;
      }
      element.innerHTML = `<div class="flex h-full w-full items-center justify-center text-center text-slate-500">No user activity detected for this period.</div>`;
      return;
    }

    mountChart(element, createCompanyHealthDistributionOption(data));
  }

  function companyUserSessionsCount(user) {
    const explicitCount = Number(
      user.sessionsCount ??
      user.sessionCount ??
      user.sessions ??
      user.distinctSessions
    );

    if (Number.isFinite(explicitCount) && explicitCount > 0) {
      return Math.max(1, Math.round(explicitCount));
    }

    const visits = Math.max(0, Number(user.visits) || Number(user.visitsCount) || 0);
    const engagedSeconds = Math.max(0, Number(user.engagedSeconds) || 0);

    if (visits > 0) {
      return Math.max(1, Math.min(visits, Math.round(visits / 3) || 1));
    }

    return engagedSeconds > 0 ? 1 : 0;
  }

  function companyUserAreaUsageSegments(user) {
    const cells = Array.isArray(user.productAreaAdoption) ? user.productAreaAdoption : [];
    const segments = cells
      .map((cell) => ({
        area: cell.productArea || "Unknown",
        engagedSeconds: Number(cell.engagedSeconds) || 0,
        visits: Number(cell.visits) || 0,
        value: Number(cell.engagedSeconds) || Number(cell.visits) || 0
      }))
      .filter((cell) => cell.value > 0)
      .sort((a, b) => b.value - a.value);
    const topSegments = segments.slice(0, 5);
    const otherValue = segments.slice(5).reduce((sum, cell) => sum + cell.value, 0);

    if (otherValue > 0) {
      topSegments.push({
        area: "Other",
        engagedSeconds: segments.slice(5).reduce((sum, cell) => sum + cell.engagedSeconds, 0),
        visits: segments.slice(5).reduce((sum, cell) => sum + cell.visits, 0),
        value: otherValue
      });
    }

    return topSegments;
  }

  function companyUserAreaUsageLabel(user) {
    const segments = companyUserAreaUsageSegments(user);

    if (!segments.length) {
      return "No usage detected";
    }

    return segments
      .slice(0, 4)
      .map((segment) => `${segment.area} ${formatDurationShort(segment.engagedSeconds || segment.value)}`)
      .join(", ");
  }

  function buildCompanyUsersConsistencyIntensityRows(data) {
    const periodDays = Math.max(1, Number(data.period?.days) || Number(String(data.period?.key || "").replace("d", "")) || 30);
    const sourceRows = Array.isArray(data.usersScatter) ? data.usersScatter : Array.isArray(data.users) ? data.users : [];
    const rows = sourceRows
      .map((user) => {
        const statusKey = normalizeUserStatus(user.status || "healthy");
        const sessions = companyUserSessionsCount(user);
        const totalEngagedSeconds = Number(user.engagedSeconds) || 0;
        const avgEngagedPerSession = sessions > 0 ? totalEngagedSeconds / sessions : 0;
        const sessionsPerWeek = (sessions / periodDays) * 7;
        const meta = userStatusMeta[statusKey] || getUserStatusMeta(statusKey);

        return {
          userId: user.id,
          userName: user.name || "User",
          email: user.email || "",
          statusKey,
          statusLabel: meta.label || statusKey,
          sessions,
          sessionsPerWeek,
          avgEngagedPerSession,
          totalEngagedSeconds,
          sessionsPerWeekLabel: formatDecimal(sessionsPerWeek),
          avgEngagedLabel: formatDurationShort(avgEngagedPerSession),
          totalEngagedLabel: formatDurationShort(totalEngagedSeconds),
          activeDaysLabel: formatNumber(user.activeDays || 0),
          areaUsageLabel: companyUserAreaUsageLabel(user)
        };
      })
      .filter((row) => row.statusKey !== "dropped" && row.sessions > 0 && row.totalEngagedSeconds > 0);

    return rows.map((row) => ({
      ...row,
      pointSize: 100,
      hoverPointSize: 150
    }));
  }

  function companyUserQuadrantText(text, xValue, yValue, align) {
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

  function createCompanyUsersConsistencyIntensitySpec(rows, config) {
    const xMedian = median(rows.map((row) => row.sessionsPerWeek));
    const yMedian = median(rows.map((row) => row.avgEngagedPerSession));
    const xMax = Math.max(...rows.map((row) => row.sessionsPerWeek), 1);
    const yMax = Math.max(...rows.map((row) => row.avgEngagedPerSession), 60);
    const xDomainMax = compactAxisMax(xMax, { headroom: 0.1, minPadding: 0.15 });
    const yDomainMax = compactAxisMax(yMax, { headroom: 0.1, minPadding: 30 });
    const statusKeys = companyUsersScatterStatusOrder
      .concat(Array.from(new Set(rows.map((row) => row.statusKey))).filter((status) => !companyUsersScatterStatusOrder.includes(status)).sort())
      .filter((status, index, statuses) => statuses.indexOf(status) === index && rows.some((row) => row.statusKey === status));
    const statusLabels = statusKeys.map((statusKey) => userStatusMeta[statusKey]?.label || getUserStatusMeta(statusKey).label || statusKey);
    const statusColors = statusKeys.map((statusKey) => tailwindColor(userStatusMeta[statusKey]?.color || getUserStatusMeta(statusKey).color || "c-blue"));

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
        { name: "xScale", type: "linear", domain: [0, xDomainMax], nice: false, range: "width" },
        { name: "yScale", type: "linear", domain: [0, yDomainMax], nice: false, range: "height" },
        { name: "colorScale", type: "ordinal", domain: statusLabels, range: statusColors }
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
          columns: statusLabels.length,
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
        companyUserQuadrantText("Power users", xDomainMax * 0.82, yDomainMax * 0.92, "end"),
        companyUserQuadrantText("Frequent shallow", xDomainMax * 0.82, yDomainMax * 0.12, "end"),
        companyUserQuadrantText("Deep infrequent", xDomainMax * 0.08, yDomainMax * 0.92, "start"),
        companyUserQuadrantText("Passive / weak", xDomainMax * 0.08, yDomainMax * 0.12, "start"),
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
                  "{'User': datum.userName, 'Status': datum.statusLabel, 'Sessions': format(datum.sessions, ','), 'Sessions/week': datum.sessionsPerWeekLabel, 'Active days': datum.activeDaysLabel, 'Total engaged time': datum.totalEngagedLabel, 'Avg engaged/session': datum.avgEngagedLabel, 'Area usage': datum.areaUsageLabel}"
              }
            },
            update: {
              cursor: { value: "default" },
              fill: { scale: "colorScale", field: "statusLabel" },
              opacity: { value: 0.84 },
              size: { field: "pointSize" },
              stroke: { value: chartTheme.colors.white },
              strokeWidth: { value: 1.3 },
              zindex: { value: 0 }
            },
            hover: {
              opacity: { value: 1 },
              size: { field: "hoverPointSize" },
              strokeWidth: { value: 1.5 },
              zindex: { value: 1 }
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
              fill: { value: chartTheme.colors.labelText },
              font: { value: "Inter, ui-sans-serif, system-ui, sans-serif" },
              fontSize: { value: 12 },
              fontWeight: { value: 400 },
              opacity: { value: 1 },
              limit: { value: 118 }
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

  function mountCompanyUsersConsistencyIntensityScatter(element, rows) {
    if (!element) {
      return;
    }

    disposeMountedChart(element);

    if (element.__hymetryVegaResizeObserver) {
      element.__hymetryVegaResizeObserver.disconnect();
      element.__hymetryVegaResizeObserver = null;
    }

    if (!rows.length) {
      disposeVega(element);
      element.innerHTML = `<div class="company-detail-empty-chart">No non-dropped user activity detected for this period.</div>`;
      return;
    }

    disposeVega(element);

    if (!globalScope.vegaEmbed) {
      chartUnavailable(element, "Vega is unavailable.");
      return;
    }

    const render = () => {
      const width = Math.max(640, Math.round(element.clientWidth - 168));
      const token = `${Date.now()}-${Math.random()}`;
      element.__hymetryVegaRenderToken = token;

      disposeVega(element);

      globalScope.vegaEmbed(element, createCompanyUsersConsistencyIntensitySpec(rows, { width }), {
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
      let animationFrame = null;
      const observer = new globalScope.ResizeObserver(() => {
        if (animationFrame) {
          globalScope.cancelAnimationFrame(animationFrame);
        }

        animationFrame = globalScope.requestAnimationFrame(render);
      });
      observer.observe(element);
      element.__hymetryVegaResizeObserver = observer;
    }
  }

  function renderCompanyUsersConsistencyIntensityScatter(data) {
    mountCompanyUsersConsistencyIntensityScatter(
      document.getElementById("company-users-consistency-intensity-scatter"),
      buildCompanyUsersConsistencyIntensityRows(data)
    );
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

  function renderSplitChangeDelta(deltaValue, unit, maxAbsDelta, label, invert = false) {
    const direction = deltaDirection(deltaValue, invert);
    const trackWidth = direction === "negative" ? 17 : 36;
    const barWidth = Number(deltaValue) === 0 ? 6 : Math.max(4, Math.round((Math.abs(Number(deltaValue) || 0) / Math.max(maxAbsDelta, 1)) * trackWidth));
    const formattedDelta = unit === "pp" ? formatSignedPp(deltaValue) : formatSignedPercent(deltaValue);
    const tooltipId = `company-detail-period-change-tooltip-${periodChangeTooltipId}`;

    periodChangeTooltipId += 1;

    return `
      <div class="pages-change-delta metric-header-tooltip" data-change-direction="${direction}" style="--pages-change-bar-width: ${barWidth}px;" tabindex="0" aria-label="${escapeHtml(`${label}. Change ${formattedDelta}`)}" aria-describedby="${tooltipId}">
        <span class="pages-change-delta__plot">
          <span class="pages-change-delta__bar pages-change-delta__bar--${direction}"></span>
        </span>
        <span class="pages-change-delta__label ${deltaTextClass(deltaValue, invert)}">${escapeHtml(formattedDelta)}</span>
        <span id="${tooltipId}" class="metric-header-tooltip__content" role="tooltip">
          <span class="pages-change-delta__tooltip-row">Change vs previous period: ${escapeHtml(formattedDelta)}</span>
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
          ${renderSplitChangeDelta(deltaValue, metric.deltaUnit, maxAbsDelta, metric.label)}
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

  function pageDetailHref(pageRuleId, periodKey) {
    if (typeof provider.pageDetailHref === "function") {
      return provider.pageDetailHref(pageRuleId, periodKey);
    }

    const params = new URLSearchParams();
    params.set("page_rule_id", pageRuleId);
    params.set("period", String(periodKey || provider.DEFAULT_PERIOD || "30d").replace("d", ""));

    return `../Pages/detail.html?${params.toString()}`;
  }

  function getTopPagesPageCount(rows) {
    return tablePageCount(currentDetailData, "topPages", rows, topPagesPageSize);
  }

  function topPagesPaginationIcon(direction) {
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

  function renderTopPagesPagination(totalPages) {
    const container = document.querySelector("[data-company-top-pages-pagination]");

    if (!container) {
      return;
    }

    if (totalPages <= 1) {
      container.hidden = true;
      container.innerHTML = "";
      return;
    }

    const currentPage = Math.min(totalPages, Math.max(1, topPagesTableState.page));
    const disabledAttr = topPagesTableState.isLoading ? " disabled" : "";

    container.hidden = false;
    container.innerHTML = `
      ${
        currentPage > 2
          ? `<button type="button" class="font-medium text-sky-700 hover:text-sky-800" data-company-top-pages-page-action="first"${disabledAttr}>Go to first page</button>`
          : `<span aria-hidden="true"></span>`
      }
      <div class="flex items-center justify-between gap-6 sm:justify-end">
        ${
          currentPage > 1
            ? `<button type="button" class="inline-flex h-8 w-8 items-center justify-center text-sky-700 hover:text-sky-800" data-company-top-pages-page-action="previous" aria-label="Back to previous page"${disabledAttr}>${topPagesPaginationIcon("previous")}</button>`
            : `<span class="invisible h-8 w-8" aria-hidden="true"></span>`
        }
        <span class="text-slate-700">Page ${currentPage}/${totalPages}</span>
        ${
          currentPage < totalPages
            ? `<button type="button" class="inline-flex items-center gap-2 rounded-md border border-slate-200 bg-transparent px-4 py-3 font-medium text-sky-700 duration-150 hover:bg-slate-100" data-company-top-pages-page-action="next"${disabledAttr}>Continue to next page ${topPagesPaginationIcon("next")}</button>`
            : ""
        }
      </div>
    `;

    container.querySelectorAll("[data-company-top-pages-page-action]").forEach((button) => {
      button.addEventListener("click", () => {
        const action = button.getAttribute("data-company-top-pages-page-action");
        const targetPage =
          action === "first"
            ? 1
            : action === "previous"
              ? Math.max(1, topPagesTableState.page - 1)
              : Math.min(totalPages, topPagesTableState.page + 1);

        requestTopPagesPage(targetPage);
      });
    });
  }

  function setTopPagesTableLoading(isLoading) {
    const overlay = document.querySelector("[data-company-top-pages-table-loading]");
    const tableShell = document.querySelector("[data-company-top-pages-table-scroll]");
    const requestFrame = globalScope.requestAnimationFrame || ((callback) => globalScope.setTimeout(callback, 0));

    tableShell?.setAttribute("aria-busy", String(isLoading));

    if (!overlay) {
      return;
    }

    if (isLoading) {
      overlay.hidden = false;
      requestFrame(() => {
        overlay.dataset.visible = "true";
      });
      return;
    }

    overlay.dataset.visible = "false";
    globalScope.setTimeout(() => {
      if (overlay.dataset.visible !== "true") {
        overlay.hidden = true;
      }
    }, 240);
  }

  function isTopPagesHeaderVisible() {
    const tableHead = document.querySelector("[data-company-top-pages-table-scroll] thead");

    if (!tableHead) {
      return true;
    }

    const stickyTop = document.querySelector("body > nav")?.getBoundingClientRect().height || 48;
    const rect = tableHead.getBoundingClientRect();

    return rect.top >= stickyTop && rect.bottom <= globalScope.innerHeight;
  }

  function scrollTopPagesHeaderIntoView() {
    const tableHead = document.querySelector("[data-company-top-pages-table-scroll] thead");

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

  function compareTopPagesByCurrentSort(a, b) {
    const sortKey = topPagesTableState.sortKey;
    const direction = topPagesTableState.sortDirection === "asc" ? 1 : -1;
    let comparison = 0;

    if (sortKey === "pageName" || sortKey === "productArea") {
      comparison = String(a[sortKey] || "").localeCompare(String(b[sortKey] || ""));
    } else {
      comparison = (Number(a[sortKey]) || 0) - (Number(b[sortKey]) || 0);
    }

    return comparison * direction || String(a.pageName || "").localeCompare(String(b.pageName || ""));
  }

  function topPageRows(data) {
    const rows = Array.isArray(data.allTopPages) && data.allTopPages.length ? data.allTopPages : data.topPages || [];

    return rows.slice().sort(compareTopPagesByCurrentSort);
  }

  function updateTopPagesSortButtons() {
    document.querySelectorAll("[data-company-top-pages-sort]").forEach((button) => {
      const isActive = button.getAttribute("data-company-top-pages-sort") === topPagesTableState.sortKey;

      button.setAttribute("data-sort-direction", isActive ? topPagesTableState.sortDirection : "");
      button.setAttribute("aria-pressed", String(isActive));
    });
    mountTopPagesTableStickyHeader();
  }

  function simulateTopPagesLoad(onComplete) {
    if (topPagesTableState.isLoading) {
      return;
    }

    topPagesTableState.isLoading = true;
    topPagesTableState.loadingToken += 1;

    const token = topPagesTableState.loadingToken;
    const rows = currentDetailData ? topPageRows(currentDetailData) : [];

    setTopPagesTableLoading(true);
    renderTopPagesPagination(getTopPagesPageCount(rows));

    if (!isTopPagesHeaderVisible()) {
      scrollTopPagesHeaderIntoView();
    }

    globalScope.setTimeout(() => {
      if (token !== topPagesTableState.loadingToken) {
        return;
      }

      onComplete();
      topPagesTableState.isLoading = false;
      setTopPagesTableLoading(false);
      renderTopPagesPagination(getTopPagesPageCount(currentDetailData ? topPageRows(currentDetailData) : []));
    }, 350);
  }

  function loadTopPagesTablePage(targetPage) {
    if (typeof provider.loadCompanyDetailTable !== "function" || !currentDetailData || topPagesTableState.isLoading) {
      return false;
    }

    topPagesTableState.isLoading = true;
    topPagesTableState.loadingToken += 1;

    const token = topPagesTableState.loadingToken;

    setTopPagesTableLoading(true);
    renderTopPagesPagination(getTopPagesPageCount(currentDetailData ? topPageRows(currentDetailData) : []));

    if (!isTopPagesHeaderVisible()) {
      scrollTopPagesHeaderIntoView();
    }

    provider.loadCompanyDetailTable("topPages", {
      page: targetPage,
      page_size: topPagesPageSize,
      sort: topPagesTableState.sortKey,
      direction: topPagesTableState.sortDirection,
      period: currentDetailData.period?.key || getRequestedPeriod()
    }).then((payload) => {
      if (token !== topPagesTableState.loadingToken) {
        return;
      }

      if (applyTablePayload(currentDetailData, "topPages", "topPages", payload, topPagesTableState)) {
        renderTopPages(currentDetailData);
      }
    }).finally(() => {
      if (token !== topPagesTableState.loadingToken) {
        return;
      }

      topPagesTableState.isLoading = false;
      setTopPagesTableLoading(false);
      renderTopPagesPagination(getTopPagesPageCount(currentDetailData ? topPageRows(currentDetailData) : []));
    });

    return true;
  }

  function requestTopPagesPage(targetPage) {
    if (!currentDetailData || topPagesTableState.isLoading || targetPage === topPagesTableState.page) {
      return;
    }

    if (loadTopPagesTablePage(targetPage)) {
      return;
    }

    simulateTopPagesLoad(() => {
      topPagesTableState.page = targetPage;
      renderTopPages(currentDetailData);
    });
  }

  function renderTopPages(data) {
    const tbody = document.getElementById("company-top-pages-table-body");

    if (!tbody) {
      return;
    }

    const rows = topPageRows(data);
    const totalPages = getTopPagesPageCount(rows);

    topPagesTableState.page = Math.min(totalPages, Math.max(1, topPagesTableState.page));
    updateTopPagesSortButtons();
    renderTopPagesPagination(totalPages);

    if (!rows.length) {
      tbody.innerHTML = `<tr><td colspan="7" class="px-6 py-10 text-center text-slate-500">No page usage in this period.</td></tr>`;
      renderTopPagesPagination(1);
      mountTopPagesTableStickyHeader();
      return;
    }

    const pageRows = tableRowsForRender(data, "topPages", rows, topPagesTableState, topPagesPageSize);
    const maxValues = tableMaxValues(rows, topPageMetrics);
    const maxDeltaValues = tableDeltaMaxValues(rows, topPageMetrics);

    tbody.innerHTML = pageRows
      .map(
        (row) => `
        <tr class="hover:bg-slate-50">
          <td class="py-3.5 pl-0 pr-6 align-middle font-medium text-slate-900">
            <a class="text-sky-800 hover:text-sky-900" href="${escapeHtml(pageDetailHref(row.pageRuleId, data.period.key))}">${escapeHtml(row.pageName)}</a>
          </td>
          <td class="py-3.5 pr-6 align-middle">${productAreaCell(row.productArea, row.color)}</td>
          ${topPageMetrics.map((metric) => renderMetricCell(row, metric, maxValues, maxDeltaValues[metric.key])).join("")}
        </tr>
      `
      )
      .join("");

    syncSplitChangeValueWidths(tbody);
    mountTopPagesTableStickyHeader();
  }

  function renderPeerComparison(data) {
    const insightContainer = document.getElementById("company-peer-insights");
    const tbody = document.getElementById("company-peer-table-body");

    if (insightContainer) {
      const insights = data.peerComparison?.insights || [];

      insightContainer.innerHTML = insights.length
        ? insights.map((insight) => `<span class="companies-badge companies-badge--blue company-peer-insight">${escapeHtml(insight)}</span>`).join("")
        : "";
    }

    if (!tbody) {
      return;
    }

    const rows = data.peerComparison?.rows || [];

    if (rows.length <= 1) {
      tbody.innerHTML = `<tr><td colspan="8" class="px-6 py-10 text-center text-slate-500">Not enough similar companies for comparison.</td></tr>`;
      return;
    }

    const maxValues = tableMaxValues(rows, peerComparisonMetrics);
    const maxDeltaValues = tableDeltaMaxValues(rows, peerComparisonMetrics);
    const areaUsageScaleMax = productAreaUsageScaleMax(rows);

    tbody.innerHTML = rows
      .map((row) => `
        <tr class="${row.rowType === "current" ? "bg-sky-50/60" : "hover:bg-slate-50"}">
          <td class="py-3.5 pl-0 pr-6 align-middle">
            ${renderPeerCompanyName(row)}
          </td>
          <td class="py-3.5 pr-6 align-middle">${row.rowType === "median" ? `<span class="companies-badge companies-badge--slate">Peer median</span>` : statusBadge(row.status)}</td>
          <td class="py-3.5 pr-6 align-middle tabular-nums font-medium text-slate-900">${formatNumber(row.activeUsers)}</td>
          ${renderMetricCell(row, peerComparisonMetrics[0], maxValues, maxDeltaValues.avgEngagedSecondsPerUser)}
          <td class="py-3.5 pr-6 align-middle whitespace-nowrap text-slate-700">${formatNumber(row.productAreasUsed)} areas &middot; ${formatNumber(row.pagesUsed)} pages</td>
          <td class="py-3.5 pr-6 align-middle tabular-nums font-medium text-slate-900">${formatPercent(row.interactionPct)}</td>
          <td class="py-3.5 pr-6 align-middle">${productAreaUsageCell(row, areaUsageScaleMax)}</td>
          <td class="py-3.5 align-middle text-slate-700">${escapeHtml(row.keyDifference)}</td>
        </tr>
      `)
      .join("");

    syncSplitChangeValueWidths(tbody);
  }

  function renderPeerCompanyName(row) {
    const companyId = String(row.id || row.companyId || row.company_id || "").trim();
    const company = { ...row, id: companyId, companyId };
    const name = row.name || row.companyName || companyId || "Unknown company";

    if (row.rowType === "median" || !companyId) {
      return `<div class="font-medium text-slate-900">${escapeHtml(name)}</div>`;
    }

    return `
      <a href="${escapeHtml(companySelectorHref(company))}" class="font-medium text-sky-800 underline-offset-2 hover:underline">
        ${escapeHtml(name)}
      </a>
    `;
  }

  function visibleUsers(data) {
    const sortKey = userTableState.sortKey;
    const direction = userTableState.sortDirection === "asc" ? 1 : -1;

    return (data.users || [])
      .slice()
      .sort((a, b) => {
        if (sortKey === "status") {
          return ((userStatusSort[normalizeUserStatus(a.status)] ?? 99) - (userStatusSort[normalizeUserStatus(b.status)] ?? 99)) * direction ||
            a.name.localeCompare(b.name);
        }

        if (userNumericSortKeys.has(sortKey)) {
          return ((Number(a[sortKey]) || 0) - (Number(b[sortKey]) || 0)) * direction || a.name.localeCompare(b.name);
        }

        const aValue = String(a[sortKey] || "");
        const bValue = String(b[sortKey] || "");

        if (!aValue && bValue) {
          return 1;
        }

        if (aValue && !bValue) {
          return -1;
        }

        return aValue.localeCompare(bValue) * direction || a.name.localeCompare(b.name);
      });
  }

  function getUsersPageCount(rows) {
    return tablePageCount(currentDetailData, "users", rows, usersPageSize);
  }

  function usersPaginationIcon(direction) {
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

  function renderUsersPagination(totalPages) {
    const container = document.querySelector("[data-company-users-pagination]");

    if (!container) {
      return;
    }

    if (totalPages <= 1) {
      container.hidden = true;
      container.innerHTML = "";
      return;
    }

    const currentPage = Math.min(totalPages, Math.max(1, userTableState.page));
    const disabledAttr = userTableState.isLoading ? " disabled" : "";

    container.hidden = false;
    container.innerHTML = `
      ${
        currentPage > 2
          ? `<button type="button" class="font-medium text-sky-700 hover:text-sky-800" data-company-users-page-action="first"${disabledAttr}>Go to first page</button>`
          : `<span aria-hidden="true"></span>`
      }
      <div class="flex items-center justify-between gap-6 sm:justify-end">
        ${
          currentPage > 1
            ? `<button type="button" class="inline-flex h-8 w-8 items-center justify-center text-sky-700 hover:text-sky-800" data-company-users-page-action="previous" aria-label="Back to previous page"${disabledAttr}>${usersPaginationIcon("previous")}</button>`
            : `<span class="invisible h-8 w-8" aria-hidden="true"></span>`
        }
        <span class="text-slate-700">Page ${currentPage}/${totalPages}</span>
        ${
          currentPage < totalPages
            ? `<button type="button" class="inline-flex items-center gap-2 rounded-md border border-slate-200 bg-transparent px-4 py-3 font-medium text-sky-700 duration-150 hover:bg-slate-100" data-company-users-page-action="next"${disabledAttr}>Continue to next page ${usersPaginationIcon("next")}</button>`
            : ""
        }
      </div>
    `;

    container.querySelectorAll("[data-company-users-page-action]").forEach((button) => {
      button.addEventListener("click", () => {
        const action = button.getAttribute("data-company-users-page-action");
        const targetPage =
          action === "first"
            ? 1
            : action === "previous"
              ? Math.max(1, userTableState.page - 1)
              : Math.min(totalPages, userTableState.page + 1);

        requestUsersPage(targetPage);
      });
    });
  }

  function setUsersTableLoading(isLoading) {
    const overlay = document.querySelector("[data-company-users-table-loading]");
    const tableShell = document.querySelector("[data-company-users-table-scroll]");
    const requestFrame = globalScope.requestAnimationFrame || ((callback) => globalScope.setTimeout(callback, 0));

    tableShell?.setAttribute("aria-busy", String(isLoading));

    if (!overlay) {
      return;
    }

    if (isLoading) {
      overlay.hidden = false;
      requestFrame(() => {
        overlay.dataset.visible = "true";
      });
      return;
    }

    overlay.dataset.visible = "false";
    globalScope.setTimeout(() => {
      if (overlay.dataset.visible !== "true") {
        overlay.hidden = true;
      }
    }, 240);
  }

  function isUsersHeaderVisible() {
    const tableHead = document.querySelector("[data-company-users-table-scroll] thead");

    if (!tableHead) {
      return true;
    }

    const stickyTop = document.querySelector("body > nav")?.getBoundingClientRect().height || 48;
    const rect = tableHead.getBoundingClientRect();

    return rect.top >= stickyTop && rect.bottom <= globalScope.innerHeight;
  }

  function scrollUsersHeaderIntoView() {
    const tableHead = document.querySelector("[data-company-users-table-scroll] thead");

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

  function simulateUsersLoad(onComplete) {
    if (userTableState.isLoading) {
      return;
    }

    userTableState.isLoading = true;
    userTableState.loadingToken += 1;

    const token = userTableState.loadingToken;
    const rows = currentDetailData ? visibleUsers(currentDetailData) : [];

    setUsersTableLoading(true);
    renderUsersPagination(getUsersPageCount(rows));

    if (!isUsersHeaderVisible()) {
      scrollUsersHeaderIntoView();
    }

    globalScope.setTimeout(() => {
      if (token !== userTableState.loadingToken) {
        return;
      }

      onComplete();
      userTableState.isLoading = false;
      setUsersTableLoading(false);
      renderUsersPagination(getUsersPageCount(currentDetailData ? visibleUsers(currentDetailData) : []));
    }, 350);
  }

  function loadUsersTablePage(targetPage) {
    if (typeof provider.loadCompanyDetailTable !== "function" || !currentDetailData || userTableState.isLoading) {
      return false;
    }

    userTableState.isLoading = true;
    userTableState.loadingToken += 1;

    const token = userTableState.loadingToken;

    setUsersTableLoading(true);
    renderUsersPagination(getUsersPageCount(currentDetailData ? visibleUsers(currentDetailData) : []));

    if (!isUsersHeaderVisible()) {
      scrollUsersHeaderIntoView();
    }

    provider.loadCompanyDetailTable("users", {
      page: targetPage,
      page_size: usersPageSize,
      sort: userTableState.sortKey,
      direction: userTableState.sortDirection,
      period: currentDetailData.period?.key || getRequestedPeriod()
    }).then((payload) => {
      if (token !== userTableState.loadingToken) {
        return;
      }

      if (applyTablePayload(currentDetailData, "users", "users", payload, userTableState)) {
        renderUsersTable(currentDetailData);
      }
    }).finally(() => {
      if (token !== userTableState.loadingToken) {
        return;
      }

      userTableState.isLoading = false;
      setUsersTableLoading(false);
      renderUsersPagination(getUsersPageCount(currentDetailData ? visibleUsers(currentDetailData) : []));
    });

    return true;
  }

  function requestUsersPage(targetPage) {
    if (!currentDetailData || userTableState.isLoading || targetPage === userTableState.page) {
      return;
    }

    if (loadUsersTablePage(targetPage)) {
      return;
    }

    simulateUsersLoad(() => {
      userTableState.page = targetPage;
      renderUsersTable(currentDetailData);
    });
  }

  function updateUserSortButtons() {
    document.querySelectorAll("[data-user-sort]").forEach((button) => {
      const isActive = button.getAttribute("data-user-sort") === userTableState.sortKey;

      button.setAttribute("data-sort-direction", isActive ? userTableState.sortDirection : "");
      button.setAttribute("aria-pressed", String(isActive));
    });
    mountUsersTableStickyHeader();
  }

  function renderCompanyUserName(row) {
    const userId = String(row.id || row.userId || row.user_id || "").trim();
    const user = { ...row, id: userId, userId };
    const name = row.name || userId || "Unknown user";
    const tooltipId = `company-user-email-${escapeHtml(userId || name)}`;

    if (!userId) {
      return `
        <span class="company-user-name metric-header-tooltip font-medium text-slate-900" tabindex="0" aria-describedby="${tooltipId}">
          ${escapeHtml(name)}
          <span id="${tooltipId}" class="metric-header-tooltip__content" role="tooltip">${escapeHtml(row.email || "")}</span>
        </span>
      `;
    }

    return `
      <a href="${escapeHtml(userDetailHref(user))}" class="company-user-name metric-header-tooltip font-medium text-sky-800 underline-offset-2 hover:underline" aria-describedby="${tooltipId}">
        ${escapeHtml(name)}
        <span id="${tooltipId}" class="metric-header-tooltip__content" role="tooltip">${escapeHtml(row.email || "")}</span>
      </a>
    `;
  }

  function renderUsersTable(data) {
    const tbody = document.getElementById("company-users-table-body");

    if (!tbody) {
      return;
    }

    const rows = visibleUsers(data);
    const totalPages = getUsersPageCount(rows);

    userTableState.page = Math.min(totalPages, Math.max(1, userTableState.page));
    updateUserSortButtons();
    renderUsersPagination(totalPages);

    if (!rows.length) {
      tbody.innerHTML = `<tr><td colspan="9" class="px-6 py-10 text-center text-slate-500">No users found for this company.</td></tr>`;
      renderUsersPagination(1);
      mountUsersTableStickyHeader();
      return;
    }

    const pageRows = tableRowsForRender(data, "users", rows, userTableState, usersPageSize);
    const maxValues = tableMaxValues(rows, userTableMetrics);
    const maxDeltaValues = tableDeltaMaxValues(rows, userTableMetrics);
    const maxMatrixEngaged = Math.max(
      ...rows.flatMap((row) => (row.productAreaAdoption || []).map((cell) => Number(cell.engagedSeconds) || 0)),
      1
    );

    tbody.innerHTML = pageRows
      .map((row) => `
        <tr class="hover:bg-slate-50">
          <td class="py-3.5 pl-0 pr-6 align-middle">
            ${renderCompanyUserName(row)}
          </td>
          <td class="py-3.5 pr-6 align-middle">${statusBadge(row.status)}</td>
          <td class="py-3.5 pr-6 align-middle whitespace-nowrap text-slate-700">${escapeHtml(row.lastActive)}</td>
          <td class="py-3.5 pr-6 align-middle tabular-nums font-medium text-slate-900">${formatNumber(row.activeDays)}</td>
          ${renderMetricCell(row, userTableMetrics[0], maxValues, maxDeltaValues.visits)}
          ${renderMetricCell(row, userTableMetrics[1], maxValues, maxDeltaValues.engagedSeconds)}
          <td class="py-3.5 pr-6 align-middle tabular-nums font-medium text-slate-900">${formatPercent(row.interactionPct)}</td>
          <td class="py-3.5 pr-6 align-middle">${adoptionMatrixCellGroup(row, maxMatrixEngaged)}</td>
          <td class="py-3.5 align-middle">${row.topArea ? productAreaCell(row.topArea) : `<span class="text-slate-400">-</span>`}</td>
        </tr>
      `)
      .join("");

    syncSplitChangeValueWidths(tbody);
    mountUsersTableStickyHeader();
  }

  function actionTargetHref(action) {
    const target = String(action.targetAnchor || "").replace(/^#/, "");

    return target ? `#${encodeURIComponent(target)}` : "";
  }

  function actionSignals(action) {
    const explicitSignals = Array.isArray(action.signals) ? action.signals : [];
    const supportingMetrics = Array.isArray(action.supportingMetrics) ? action.supportingMetrics : [];
    const metricLabel = action.metricLabel || action.metric || "";
    const signals = metricLabel ? [metricLabel, ...explicitSignals, ...supportingMetrics] : [...explicitSignals, ...supportingMetrics];

    return Array.from(new Set(signals.filter(Boolean))).slice(0, 2);
  }

  function renderRecommendedActionRow(action) {
    const signals = actionSignals(action);
    const targetHref = actionTargetHref(action);

    return `
      <tr class="hover:bg-slate-50">
        <td class="py-3.5 pl-0 pr-6 align-top">
          <span class="companies-badge company-action-type">${escapeHtml(action.category || action.type || "Recommendation")}</span>
        </td>
        <td class="py-3.5 pr-6 align-top">
          <div class="company-action-title">${escapeHtml(action.title)}</div>
        </td>
        <td class="py-3.5 pr-6 align-top">
          <div class="company-action-reason">${escapeHtml(action.reason)}</div>
        </td>
        <td class="py-3.5 pr-6 align-top">
          <div class="company-action-signals">
            ${signals.length ? `<span class="company-action-signal">${signals.map((signal) => escapeHtml(signal)).join(" &middot; ")}</span>` : `<span class="text-slate-400">-</span>`}
          </div>
        </td>
        <td class="py-3.5 align-top">
          ${targetHref && action.ctaLabel ? `<a class="company-action-next" href="${escapeHtml(targetHref)}">${escapeHtml(action.ctaLabel)}</a>` : `<span class="text-slate-400">-</span>`}
        </td>
      </tr>
    `;
  }

  function renderRecommendedActions(data) {
    const container = document.getElementById("company-recommended-actions");

    if (!container) {
      return;
    }

    const actions = data.recommendedActions || [];

    if (!actions.length) {
      container.innerHTML = `<tr><td colspan="5" class="px-6 py-8 text-center text-slate-500">No recommended actions for this period.</td></tr>`;
      return;
    }

    container.innerHTML = actions.map(renderRecommendedActionRow).join("");
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
    syncSplitChangeValueWidths(document.getElementById("company-top-pages-table-body"));
    syncSplitChangeValueWidths(document.getElementById("company-peer-table-body"));
    syncSplitChangeValueWidths(document.getElementById("company-users-table-body"));
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

  function renderMeta(data) {
    const container = document.getElementById("company-detail-meta");
    const company = data.company;

    if (!container) {
      return;
    }

    const metaItems = [
      statusBadge(company.status),
      `<span class="company-detail-meta__item"><span class="company-detail-meta__label">Active users</span>${formatNumber(company.activeUsers)}</span>`,
      `<span class="company-detail-meta__item"><span class="company-detail-meta__label">Known users</span>${formatNumber(company.totalKnownUsers)}</span>`,
      `<span class="company-detail-meta__item"><span class="company-detail-meta__label">Last active</span>${escapeHtml(company.lastActiveAt || "-")}</span>`
    ].filter(Boolean);

    container.innerHTML = metaItems.join("");
  }

  function renderHeader(data) {
    setText("company-detail-title-company-name", data.company.name);
    setText("company-detail-health-summary", data.healthSummary || "Not enough activity in this period to generate a reliable company insight.");
    document.getElementById("company-detail-company-selector-button")?.setAttribute("aria-label", `Switch company from ${data.company.name}`);
    document.title = `${data.company.name} - Company details`;
    renderMeta(data);
  }

  function renderPeriodSelector(data) {
    const container = document.getElementById("company-detail-period-selector");

    if (!container) {
      return;
    }

    container.innerHTML = detailHelpers.PERIOD_OPTIONS
      .map((days) => {
        const period = `${days}d`;
        const isActive = period === data.period.key;

        return `
          <button
            type="button"
            data-company-detail-period="${period}"
            aria-pressed="${String(isActive)}"
            class="px-3 py-1.5 text-sm font-medium duration-150 ${isActive ? "bg-slate-900 text-white" : "bg-white text-slate-700 hover:bg-slate-50"}">
            ${period}
          </button>
        `;
      })
      .join("");

    container.querySelectorAll("[data-company-detail-period]").forEach((button) => {
      button.addEventListener("click", () => {
        const period = provider.coercePeriodKey(button.getAttribute("data-company-detail-period"));
        loadCompanyDetail(data.company.id, period);
      });
    });
  }

  function updateDetailQuery(companyId, period) {
    const params = new URLSearchParams(globalScope.location.search);

    params.set("company_id", companyId);
    params.set("period", period);
    globalScope.history?.replaceState({}, "", `${globalScope.location.pathname}?${params.toString()}`);
  }

  function backHref(period) {
    if (typeof provider.companiesOverviewHref === "function") {
      return provider.companiesOverviewHref(period);
    }

    const params = new URLSearchParams();
    params.set("period", period);

    return `index.html?${params.toString()}`;
  }

  function readRecentCompanyEntries() {
    try {
      const value = globalScope.localStorage?.getItem(recentCompaniesStorageKey);
      const parsed = JSON.parse(value || "[]");

      return Array.isArray(parsed) ? parsed : [];
    } catch {
      return [];
    }
  }

  function readRecentCompanyIds() {
    return readRecentCompanyEntries()
      .map((company) => (typeof company === "string" ? company : company?.id || company?.companyId || ""))
      .filter((id) => typeof id === "string" && id);
  }

  function companySelectorElements() {
    return {
      root: document.getElementById("company-detail-company-selector"),
      button: document.getElementById("company-detail-company-selector-button"),
      dropdown: document.getElementById("company-detail-company-selector-results"),
      input: document.getElementById("company-detail-company-selector-input"),
      listbox: document.getElementById("company-detail-company-selector-listbox")
    };
  }

  function normalizeCompanySelectorQuery(value) {
    return String(value ?? "").trim().toLowerCase();
  }

  function companySelectorHref(company) {
    if (typeof provider.companyDetailHref === "function") {
      return provider.companyDetailHref(company, currentDetailData?.period?.key || getRequestedPeriod());
    }

    const params = new URLSearchParams();

    params.set("company_id", company.id);
    params.set("period", currentDetailData?.period?.key || getRequestedPeriod());

    return `detail.html?${params.toString()}`;
  }

  function userDetailHref(user) {
    const period = currentDetailData?.period?.key || getRequestedPeriod();

    if (typeof provider.userDetailHref === "function") {
      return provider.userDetailHref(user, period);
    }

    const userId = String(user?.id || user?.userId || user?.user_id || "").trim();
    const params = new URLSearchParams();
    const detailBaseUrl = document.body?.dataset.userDetailBaseUrl || "../users/detail.html";

    params.set("user_id", userId);
    params.set("period", period);

    return `${detailBaseUrl}${detailBaseUrl.includes("?") ? "&" : "?"}${params.toString()}`;
  }

  function companySelectorMetadata(company) {
    const areaCount = currentOverviewData?.productAreas?.length || provider.productAreas?.length || 0;
    const metadata = [
      `${formatNumber(company.activeUsers)} users`,
      areaCount ? `${formatNumber(company.productAreasUsed)}/${areaCount} area adoption` : "",
      company.lastSeen ? `last active ${company.lastSeen}` : ""
    ].filter(Boolean);

    return metadata.join(" \u00b7 ");
  }

  function normalizeCompanySelectorCompany(company) {
    const id = String(company?.id || company?.companyId || "");

    return {
      ...(company || {}),
      id,
      companyId: id,
      name: company?.name || company?.companyName || id,
      companyName: company?.companyName || company?.name || id,
      domain: company?.domain || "",
      activeUsers: Number(company?.activeUsers || company?.active_users || 0),
      productAreasUsed: Number(company?.productAreasUsed || company?.product_areas_used || 0),
      pagesUsed: Number(company?.pagesUsed || company?.pages_used || 0),
      lastSeen: company?.lastSeen || company?.lastActiveAt || "",
      lastSeenDate: company?.lastSeenDate || "",
      lastSeenDays: Number(company?.lastSeenDays || 0)
    };
  }

  function readRecentCompanies() {
    const companies = (currentOverviewData?.companies || []).map(normalizeCompanySelectorCompany);
    const companiesById = new Map(companies.map((company) => [company.id, company]));

    return readRecentCompanyEntries()
      .map((company) => {
        if (typeof company === "string") {
          return companiesById.get(company) || null;
        }

        const normalized = normalizeCompanySelectorCompany(company);
        return companiesById.get(normalized.id) || normalized;
      })
      .filter((company) => company?.id);
  }

  function writeRecentCompanies(companies) {
    try {
      globalScope.localStorage?.setItem(
        recentCompaniesStorageKey,
        JSON.stringify(companies.map(normalizeCompanySelectorCompany).filter((company) => company.id).slice(0, 8))
      );
    } catch {
      // localStorage may be unavailable in private or embedded browsing contexts.
    }
  }

  function rememberRecentCompany(company) {
    const normalized = normalizeCompanySelectorCompany(company);

    if (!normalized.id) {
      return;
    }

    const companies = readRecentCompanies();
    writeRecentCompanies([normalized, ...companies.filter((item) => item.id !== normalized.id)]);
  }

  function getCompanySelectorResults(query = companySelectorState.query) {
    const normalizedQuery = normalizeCompanySelectorQuery(query);
    const usesRemoteOptions = typeof provider.searchCompanies === "function";
    const remoteResults = companySelectorState.remoteQuery === normalizedQuery
      ? companySelectorState.remoteResults
      : [];
    const currentCompanyId = currentDetailData?.company?.id || "";

    if (usesRemoteOptions && !normalizedQuery) {
      return readRecentCompanies()
        .filter((company) => company.id !== currentCompanyId)
        .slice(0, 8);
    }

    if (usesRemoteOptions) {
      return remoteResults
        .filter((company) => company.id !== currentCompanyId)
        .slice(0, 8);
    }

    const companies = (currentOverviewData?.companies || []).map(normalizeCompanySelectorCompany);

    if (normalizedQuery) {
      return companies
        .filter((company) => company.id !== currentCompanyId)
        .filter((company) => `${company.name || ""} ${company.domain || ""}`.toLowerCase().includes(normalizedQuery))
        .slice(0, 8);
    }

    const companiesById = new Map(companies.map((company) => [company.id, company]));
    const recentCompanies = readRecentCompanyIds()
      .map((id) => companiesById.get(id))
      .filter((company) => company && company.id !== currentCompanyId);
    const fallbackCompanies = companies
      .slice()
      .sort((a, b) => (a.lastSeenDays || 0) - (b.lastSeenDays || 0) || (b.activeUsers || 0) - (a.activeUsers || 0))
      .filter((company) => company.id !== currentCompanyId && !recentCompanies.some((recentCompany) => recentCompany.id === company.id));

    return [...recentCompanies, ...fallbackCompanies].slice(0, 8);
  }

  function closeCompanySelectorDropdown() {
    const { button, dropdown, input, listbox } = companySelectorElements();

    if (companySelectorDebounceId) {
      globalScope.clearTimeout(companySelectorDebounceId);
      companySelectorDebounceId = 0;
    }

    companySelectorState.isOpen = false;
    companySelectorState.activeIndex = -1;
    companySelectorState.query = "";

    button?.setAttribute("aria-expanded", "false");
    button?.removeAttribute("aria-activedescendant");
    input?.setAttribute("aria-expanded", "false");
    input?.removeAttribute("aria-activedescendant");

    if (input) {
      input.value = "";
    }

    if (dropdown) {
      dropdown.hidden = true;
    }

    if (listbox) {
      listbox.innerHTML = "";
    }
  }

  function setCompanySelectorActiveIndex(nextIndex) {
    const { button, input, listbox } = companySelectorElements();

    if (!listbox || !companySelectorState.results.length) {
      companySelectorState.activeIndex = -1;
      button?.removeAttribute("aria-activedescendant");
      input?.removeAttribute("aria-activedescendant");
      return;
    }

    const resultCount = companySelectorState.results.length;
    companySelectorState.activeIndex = (nextIndex + resultCount) % resultCount;

    listbox.querySelectorAll("[data-company-selector-index]").forEach((option) => {
      const index = Number(option.getAttribute("data-company-selector-index"));
      const isActive = index === companySelectorState.activeIndex;

      option.dataset.active = String(isActive);
      option.setAttribute("aria-selected", String(isActive));
    });

    const activeOptionId = `company-detail-company-selector-option-${companySelectorState.activeIndex}`;
    button?.setAttribute("aria-activedescendant", activeOptionId);
    input?.setAttribute("aria-activedescendant", activeOptionId);
    document.getElementById(activeOptionId)?.scrollIntoView({ block: "nearest" });
  }

  function openCompanySelectorCompany(company) {
    if (!company) {
      return;
    }

    rememberRecentCompany(company);
    globalScope.location.href = companySelectorHref(company);
  }

  function renderCompanySelectorDropdown({ focusInput = false, refresh = true } = {}) {
    const { button, dropdown, input, listbox } = companySelectorElements();

    if (!button || !dropdown || !input || !listbox) {
      return;
    }

    const query = companySelectorState.query;
    const normalizedQuery = normalizeCompanySelectorQuery(query);
    companySelectorState.results = getCompanySelectorResults();
    companySelectorState.activeIndex = companySelectorState.results.length ? 0 : -1;
    companySelectorState.isOpen = true;
    button.setAttribute("aria-expanded", "true");
    input.setAttribute("aria-expanded", "true");
    dropdown.hidden = false;

    if (!companySelectorState.results.length) {
      listbox.innerHTML = `<span class="company-search__empty" role="status">${refresh && typeof provider.searchCompanies === "function" ? "Loading companies..." : "No companies found"}</span>`;
      if (focusInput) {
        input.focus();
      }
    } else {
      listbox.innerHTML = companySelectorState.results
        .map((company, index) => `
          <a
            id="company-detail-company-selector-option-${index}"
            href="${escapeHtml(companySelectorHref(company))}"
            class="company-search__option"
            role="option"
            data-company-selector-index="${index}"
            data-active="${String(index === companySelectorState.activeIndex)}"
            aria-selected="${String(index === companySelectorState.activeIndex)}">
            <span class="min-w-0">
              <span class="company-search__name">${escapeHtml(company.name)}</span>
              <span class="company-search__meta">${escapeHtml(companySelectorMetadata(company))}</span>
            </span>
            <span class="company-search__open">Open \u2192</span>
          </a>
        `)
        .join("");

      setCompanySelectorActiveIndex(companySelectorState.activeIndex);

      listbox.querySelectorAll("[data-company-selector-index]").forEach((option) => {
        const index = Number(option.getAttribute("data-company-selector-index"));

        option.addEventListener("mouseenter", () => {
          setCompanySelectorActiveIndex(index);
        });

        option.addEventListener("click", () => {
          rememberRecentCompany(companySelectorState.results[index]);
        });

        option.addEventListener("auxclick", (event) => {
          if (event.button === 1) {
            rememberRecentCompany(companySelectorState.results[index]);
          }
        });
      });
    }

    if (focusInput) {
      input.focus();
    }

    if (refresh && normalizedQuery && typeof provider.searchCompanies === "function") {
      const requestToken = companySelectorState.requestToken + 1;
      companySelectorState.requestToken = requestToken;
      provider.searchCompanies(query, {
        period: currentDetailData?.period?.key || getRequestedPeriod(),
        limit: 20
      }).then((remoteCompanies) => {
        if (
          requestToken !== companySelectorState.requestToken ||
          !companySelectorState.isOpen ||
          normalizeCompanySelectorQuery(input.value) !== normalizedQuery
        ) {
          return;
        }

        const currentCompanyId = currentDetailData?.company?.id || "";
        companySelectorState.remoteQuery = normalizedQuery;
        companySelectorState.remoteResults = (remoteCompanies || [])
          .map(normalizeCompanySelectorCompany)
          .filter((company) => company.id && company.id !== currentCompanyId);
        renderCompanySelectorDropdown({ refresh: false });
      });
    }
  }

  function mountCompanySelector() {
    const { root, button, input } = companySelectorElements();

    if (!root || !button || !input || companySelectorMounted) {
      return;
    }

    companySelectorMounted = true;

    button.addEventListener("click", () => {
      if (companySelectorState.isOpen) {
        closeCompanySelectorDropdown();
      } else {
        renderCompanySelectorDropdown({ focusInput: true });
      }
    });

    button.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        closeCompanySelectorDropdown();
        return;
      }

      if ((event.key === "ArrowDown" || event.key === "ArrowUp") && !companySelectorState.isOpen) {
        event.preventDefault();
        renderCompanySelectorDropdown({ focusInput: true });
        return;
      }

      if (!companySelectorState.isOpen || !companySelectorState.results.length) {
        return;
      }

      if (event.key === "ArrowDown") {
        event.preventDefault();
        setCompanySelectorActiveIndex(companySelectorState.activeIndex + 1);
        return;
      }

      if (event.key === "ArrowUp") {
        event.preventDefault();
        setCompanySelectorActiveIndex(companySelectorState.activeIndex - 1);
        return;
      }

      if (event.key === "Enter" && companySelectorState.activeIndex >= 0) {
        event.preventDefault();
        openCompanySelectorCompany(companySelectorState.results[companySelectorState.activeIndex]);
      }
    });

    input.addEventListener("input", () => {
      companySelectorState.query = input.value;

      if (companySelectorDebounceId) {
        globalScope.clearTimeout(companySelectorDebounceId);
      }

      companySelectorDebounceId = globalScope.setTimeout(() => {
        companySelectorDebounceId = 0;
        renderCompanySelectorDropdown();
      }, 220);
    });

    input.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        closeCompanySelectorDropdown();
        button.focus();
        return;
      }

      if (!companySelectorState.isOpen) {
        return;
      }

      if (event.key === "ArrowDown") {
        event.preventDefault();
        setCompanySelectorActiveIndex(companySelectorState.activeIndex + 1);
        return;
      }

      if (event.key === "ArrowUp") {
        event.preventDefault();
        setCompanySelectorActiveIndex(companySelectorState.activeIndex - 1);
        return;
      }

      if (event.key === "Enter" && companySelectorState.activeIndex >= 0) {
        event.preventDefault();
        openCompanySelectorCompany(companySelectorState.results[companySelectorState.activeIndex]);
      }
    });

    document.addEventListener("pointerdown", (event) => {
      if (!root.contains(event.target)) {
        closeCompanySelectorDropdown();
      }
    });
  }

  function mountStickyTableHeader(table) {
    const tableHead = table?.querySelector("thead");
    const scrollContainer = table?.closest("[data-company-users-table-scroll], [data-company-top-pages-table-scroll]");

    if (!table || !tableHead || !scrollContainer) {
      return;
    }

    if (table.__hymetryStickyTableHeaderRefresh) {
      table.__hymetryStickyTableHeaderRefresh();
      return;
    }

    const stickyHeader = document.createElement("div");
    const cloneTable = table.cloneNode(false);
    const stickyHeaderId =
      scrollContainer.getAttribute("data-sticky-table-header-id") ||
      (scrollContainer.hasAttribute("data-company-top-pages-table-scroll")
        ? "company-top-pages-table-sticky-header"
        : "company-users-table-sticky-header");
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
    globalScope.addEventListener("scroll", syncStickyHeader, { passive: true });
    globalScope.addEventListener("resize", syncStickyHeader);
    scrollContainer.addEventListener("scroll", syncStickyHeader, { passive: true });
  }

  function mountUsersTableStickyHeader() {
    const table = document.querySelector("[data-company-users-table-scroll] table");

    if (table) {
      mountStickyTableHeader(table);
    }
  }

  function mountTopPagesTableStickyHeader() {
    const table = document.querySelector("[data-company-top-pages-table-scroll] table");

    if (table) {
      mountStickyTableHeader(table);
    }
  }

  function mountAreaMixFloatingTooltip() {
    if (areaMixFloatingTooltipMounted) {
      return;
    }

    areaMixFloatingTooltipMounted = true;
    document.documentElement.classList.add("metric-floating-tooltips-enabled");

    const floatingTooltip = document.createElement("div");
    let activeTrigger = null;
    let positionAnimationFrame = 0;
    const verticalGap = 8;
    const viewportPadding = 8;

    floatingTooltip.className = "metric-header-tooltip__content metric-floating-tooltip";
    floatingTooltip.dataset.tooltipKind = "area-mix";
    floatingTooltip.dataset.visible = "false";
    floatingTooltip.setAttribute("aria-hidden", "true");
    floatingTooltip.setAttribute("role", "tooltip");
    document.body.appendChild(floatingTooltip);

    const getTooltipTrigger = (target) => {
      if (!target || typeof target.closest !== "function") {
        return null;
      }

      return target.closest(".pages-change-delta.metric-header-tooltip, .companies-area-mix.metric-header-tooltip");
    };
    const setTooltipVisible = (isVisible) => {
      floatingTooltip.dataset.visible = String(isVisible);
      floatingTooltip.setAttribute("aria-hidden", String(!isVisible));
    };
    const hideTooltip = (trigger = activeTrigger) => {
      if (trigger && activeTrigger && trigger !== activeTrigger) {
        return;
      }

      activeTrigger = null;
      setTooltipVisible(false);
    };
    const updateTooltipPosition = () => {
      if (!activeTrigger) {
        return;
      }

      if (!activeTrigger.isConnected) {
        hideTooltip();
        return;
      }

      const triggerRect = activeTrigger.getBoundingClientRect();
      const viewportWidth = document.documentElement.clientWidth || globalScope.innerWidth || 0;
      const viewportHeight = document.documentElement.clientHeight || globalScope.innerHeight || 0;

      if (triggerRect.bottom < 0 || triggerRect.top > viewportHeight || triggerRect.right < 0 || triggerRect.left > viewportWidth) {
        hideTooltip();
        return;
      }

      const tooltipRect = floatingTooltip.getBoundingClientRect();
      const shouldPlaceAbove =
        triggerRect.bottom + verticalGap + tooltipRect.height > viewportHeight - viewportPadding &&
        triggerRect.top - verticalGap - tooltipRect.height >= viewportPadding;
      const desiredLeft = triggerRect.left + triggerRect.width / 2 - tooltipRect.width / 2;
      const desiredTop = shouldPlaceAbove
        ? triggerRect.top - verticalGap - tooltipRect.height
        : triggerRect.bottom + verticalGap;
      const maxLeft = Math.max(viewportPadding, viewportWidth - tooltipRect.width - viewportPadding);
      const maxTop = Math.max(viewportPadding, viewportHeight - tooltipRect.height - viewportPadding);
      const left = Math.min(Math.max(desiredLeft, viewportPadding), maxLeft);
      const top = Math.min(Math.max(desiredTop, viewportPadding), maxTop);

      floatingTooltip.dataset.placement = shouldPlaceAbove ? "top" : "bottom";
      floatingTooltip.style.left = `${Math.round(left)}px`;
      floatingTooltip.style.top = `${Math.round(top)}px`;
    };
    const schedulePositionUpdate = () => {
      if (!activeTrigger || positionAnimationFrame) {
        return;
      }

      positionAnimationFrame = globalScope.requestAnimationFrame(() => {
        positionAnimationFrame = 0;
        updateTooltipPosition();
      });
    };
    const showTooltip = (trigger) => {
      const sourceTooltip = trigger.querySelector(".metric-header-tooltip__content");

      if (!sourceTooltip) {
        return;
      }

      activeTrigger = trigger;
      floatingTooltip.innerHTML = sourceTooltip.innerHTML;
      floatingTooltip.dataset.tooltipKind = trigger.classList.contains("pages-change-delta") ? "delta" : "area-mix";
      const areaTooltipLabelWidth = trigger.style.getPropertyValue("--area-tooltip-label-width");
      if (areaTooltipLabelWidth) {
        floatingTooltip.style.setProperty("--area-tooltip-label-width", areaTooltipLabelWidth);
      } else {
        floatingTooltip.style.removeProperty("--area-tooltip-label-width");
      }
      floatingTooltip.style.left = "0px";
      floatingTooltip.style.top = "0px";
      setTooltipVisible(false);
      updateTooltipPosition();
      setTooltipVisible(true);
    };

    document.addEventListener("pointerover", (event) => {
      const trigger = getTooltipTrigger(event.target);

      if (!trigger || trigger === activeTrigger) {
        return;
      }

      showTooltip(trigger);
    });
    document.addEventListener("pointerout", (event) => {
      const trigger = getTooltipTrigger(event.target);
      const relatedTarget = event.relatedTarget;

      if (!trigger || (relatedTarget && trigger.contains(relatedTarget))) {
        return;
      }

      hideTooltip(trigger);
    });
    document.addEventListener("focusin", (event) => {
      const trigger = getTooltipTrigger(event.target);

      if (trigger) {
        showTooltip(trigger);
      }
    });
    document.addEventListener("focusout", (event) => {
      const trigger = getTooltipTrigger(event.target);
      const relatedTarget = event.relatedTarget;

      if (!trigger || (relatedTarget && trigger.contains(relatedTarget))) {
        return;
      }

      hideTooltip(trigger);
    });
    document.addEventListener("scroll", schedulePositionUpdate, true);
    globalScope.addEventListener("resize", schedulePositionUpdate);
    globalScope.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        hideTooltip();
      }
    });
  }

  function mountUserTableSort() {
    if (userSortMounted) {
      return;
    }

    userSortMounted = true;

    document.querySelectorAll("[data-user-sort]").forEach((button) => {
      button.addEventListener("click", () => {
        const sortKey = button.getAttribute("data-user-sort") || "engagedSeconds";

        if (!currentDetailData || userTableState.isLoading) {
          return;
        }

        if (userTableState.sortKey === sortKey) {
          userTableState.sortDirection = userTableState.sortDirection === "asc" ? "desc" : "asc";
        } else {
          userTableState.sortKey = sortKey;
          userTableState.sortDirection = userDefaultSortDirections[sortKey] || "desc";
        }

        userTableState.page = 1;
        updateUserSortButtons();
        if (loadUsersTablePage(1)) {
          return;
        }

        simulateUsersLoad(() => {
          renderUsersTable(currentDetailData);
        });
      });
    });
  }

  function mountTopPagesSort() {
    if (topPagesSortMounted) {
      return;
    }

    topPagesSortMounted = true;

    document.querySelectorAll("[data-company-top-pages-sort]").forEach((button) => {
      button.addEventListener("click", () => {
        const sortKey = button.getAttribute("data-company-top-pages-sort") || "engagedSeconds";

        if (!currentDetailData || topPagesTableState.isLoading) {
          return;
        }

        if (topPagesTableState.sortKey === sortKey) {
          topPagesTableState.sortDirection = topPagesTableState.sortDirection === "asc" ? "desc" : "asc";
        } else {
          topPagesTableState.sortKey = sortKey;
          topPagesTableState.sortDirection = topPagesDefaultSortDirections[sortKey] || "desc";
        }

        topPagesTableState.page = 1;
        updateTopPagesSortButtons();
        if (loadTopPagesTablePage(1)) {
          return;
        }

        simulateTopPagesLoad(() => {
          renderTopPages(currentDetailData);
        });
      });
    });
  }

  function renderAll(data) {
    currentDetailData = data;
    syncProductAreaPalette(data);
    productAreaMixTooltipId = 0;
    adoptionCellTooltipId = 0;
    periodChangeTooltipId = 0;
    userTableState.page = 1;
    userTableState.isLoading = false;
    userTableState.loadingToken += 1;
    setUsersTableLoading(false);
    topPagesTableState.page = 1;
    topPagesTableState.isLoading = false;
    topPagesTableState.loadingToken += 1;
    setTopPagesTableLoading(false);

    document.getElementById("company-detail-loading")?.classList.add("hidden");
    document.getElementById("company-detail-preparing")?.classList.add("hidden");
    document.getElementById("company-detail-not-found")?.classList.add("hidden");
    document.getElementById("company-detail-content")?.classList.remove("hidden");

    document.getElementById("company-detail-preparing-back")?.setAttribute("href", backHref(data.period.key));
    document.getElementById("company-detail-not-found-back")?.setAttribute("href", backHref(data.period.key));

    renderHeader(data);
    renderPeriodSelector(data);
    mountAreaMixFloatingTooltip();
    mountCompanySelector();
    mountUserTableSort();
    mountTopPagesSort();
    renderMetricDynamics(data);
    renderProductAreaCharts(data);
    renderTopPages(data);
    renderPeerComparison(data);
    renderCompanyHealthDistribution(data);
    renderCompanyUsersConsistencyIntensityScatter(data);
    renderUsersTable(data);
    renderRecommendedActions(data);
    rememberRecentCompany(data.company);
    updateDetailQuery(data.company.id, data.period.key);
    scheduleSplitChangeValueWidthSync();
  }

  function renderNotFound(period) {
    document.getElementById("company-detail-loading")?.classList.add("hidden");
    document.getElementById("company-detail-preparing")?.classList.add("hidden");
    document.getElementById("company-detail-content")?.classList.add("hidden");
    document.getElementById("company-detail-not-found")?.classList.remove("hidden");
    document.getElementById("company-detail-not-found-back")?.setAttribute("href", backHref(period));
  }

  function renderPreparing(period) {
    document.getElementById("company-detail-loading")?.classList.add("hidden");
    document.getElementById("company-detail-not-found")?.classList.add("hidden");
    document.getElementById("company-detail-content")?.classList.add("hidden");
    document.getElementById("company-detail-preparing")?.classList.remove("hidden");
    document.getElementById("company-detail-preparing-back")?.setAttribute("href", backHref(period));
  }

  function loadCompanyDetail(companyId, periodValue) {
    const period = provider.coercePeriodKey(periodValue || provider.DEFAULT_PERIOD);
    const overviewData = provider.getCompaniesDemoData(period);
    const detailData = typeof provider.getCompanyDetailsData === "function"
      ? provider.getCompanyDetailsData(companyId, period)
      : detailHelpers.buildCompanyDetailsData(overviewData, companyId);

    currentOverviewData = overviewData;

    if (!detailData) {
      if (provider.isPeriodNavigationPending?.()) {
        return;
      }

      if (provider.isPayloadPending?.()) {
        renderPreparing(period);
        return;
      }

      renderNotFound(period);
      return;
    }

    renderAll(detailData);
  }

  function getRequestedCompanyId() {
    const params = new URLSearchParams(globalScope.location.search);
    const queryValue = params.get("company_id") || params.get("company") || params.get("id");

    if (queryValue) {
      return queryValue;
    }

    const bodyValue = document.body?.dataset.companyId;

    if (bodyValue) {
      return bodyValue;
    }

    const pathParts = globalScope.location.pathname.split("/").filter(Boolean);
    const lastPart = pathParts[pathParts.length - 1] || "";

    if (lastPart && lastPart !== "detail" && lastPart !== "detail.html") {
      return lastPart.replace(/\.html$/, "");
    }

    return "";
  }

  function getRequestedPeriod() {
    const params = new URLSearchParams(globalScope.location.search);

    return provider.coercePeriodKey(params.get("period") || params.get("days") || provider.DEFAULT_PERIOD);
  }

  function initCompanyDetail() {
    if (document.body.dataset.companiesView !== "detail") {
      return;
    }

    globalScope.addEventListener("resize", scheduleSplitChangeValueWidthSync);
    document.fonts?.ready?.then(scheduleSplitChangeValueWidthSync);
    loadCompanyDetail(getRequestedCompanyId(), getRequestedPeriod());
  }

  document.addEventListener("DOMContentLoaded", initCompanyDetail);

  document.addEventListener("htmx:beforeRequest", (event) => {
    if (event.target?.matches?.("[data-company-metric-dynamics-show-peers]")) {
      setCompanyMetricDynamicsLoading(true);
    }
  });

  document.addEventListener("htmx:afterRequest", (event) => {
    if (event.target?.matches?.("[data-company-metric-dynamics-show-peers]")) {
      setCompanyMetricDynamicsLoading(false);
    }
  });

  document.addEventListener("htmx:afterSwap", (event) => {
    if (event.detail?.target?.id === "company-metric-dynamics-section" && currentDetailData) {
      companyMetricDynamicsState.showPeers = companyMetricDynamicsShowPeers();
      renderMetricDynamics(currentDetailData);
    }
  });
})(window);
