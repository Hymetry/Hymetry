(function mountHymetryCompaniesAnalytics(globalScope) {
  const provider = globalScope.HymetryCompaniesDemoData;
  const analyticsTooltips = globalScope.HymetryAnalyticsTooltips;
  const metricDynamicsHelpers = globalScope.HymetryMetricDynamics || {};

  if (!provider || !analyticsTooltips) {
    return;
  }

  const buildStraightTrendLine = metricDynamicsHelpers.buildStraightTrendLine || (() => []);
  const bindLineTrendHover = metricDynamicsHelpers.bindLineTrendHover || ((chart) => chart);
  const numberFormatter = new Intl.NumberFormat("en-US");
  const averageUsersFormatter = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 });

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
    "green-50": "#f0fdf4",
    "green-700": "#15803d",
    "orange-50": "#fff7ed",
    "orange-600": "#ea580c",
    "red-50": "#fef2f2",
    "red-600": "#dc2626",
    "sky-50": "#f0f9ff",
    "sky-600": "#0284c7",
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

  const statusRegistry = globalScope.HymetryAnalyticsStatusColors || {};
  const fallbackCompanyStatusOrder = ["power", "healthy", "activated", "new", "reactivated", "at_risk", "dormant"];
  const fallbackCompanyStatusMeta = {
    new: { label: "New", color: "c-light-blue", badge: "companies-badge--light-blue", definition: "First seen in the selected period." },
    activated: { label: "Activated", color: "c-teal", badge: "companies-badge--teal", definition: "Recently reached activation criteria." },
    reactivated: { label: "Reactivated", color: "c-blue", badge: "companies-badge--blue", definition: "Returned after a quiet period." },
    healthy: { label: "Healthy", color: "c-blue", badge: "companies-badge--blue", definition: "Consistent account-level engagement." },
    power: { label: "Power", color: "c-green", badge: "companies-badge--green", definition: "High breadth and depth of adoption." },
    at_risk: { label: "At risk", color: "c-orange", badge: "companies-badge--orange", definition: "Meaningful usage drop or stale activity." },
    dormant: { label: "Dormant", color: "c-red", badge: "companies-badge--red", definition: "Little or no activity in this period." }
  };
  const companyStatusOrder = statusRegistry.companyStatusOrder || fallbackCompanyStatusOrder;
  const normalizeCompanyStatus = statusRegistry.normalizeCompanyStatus || ((status) => {
    const key = String(status || "").trim().replace(/\s+/g, "_").replace(/-/g, "_").toLowerCase();
    return { active: "activated", risk: "at_risk", atrisk: "at_risk", dropped: "dormant" }[key] || key;
  });
  const getCompanyStatusMeta = statusRegistry.getCompanyStatusMeta || ((status) => {
    const key = normalizeCompanyStatus(status);
    const meta = fallbackCompanyStatusMeta[key];

    return meta
      ? { ...meta, key, sort: companyStatusOrder.indexOf(key) }
      : { key, label: String(status || "Unknown"), color: "slate-400", badge: "companies-badge--gray", sort: 99, definition: "" };
  });
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
  const userHealthSegments = statusRegistry.userHealthSegments || [
    ["power", "Power", "c-green"],
    ["healthy", "Healthy", "c-blue"],
    ["light", "Light", "c-orange"],
    ["passive", "Passive", "c-brown"],
    ["dropped", "Dropped", "c-red"]
  ];

  const expansionPriorityLabels = {
    high: "High potential",
    medium: "Medium potential",
    low: "Low potential"
  };

  const expansionPriorityBadgeClasses = {
    high: "companies-badge--green",
    medium: "companies-badge--orange",
    low: "companies-badge--slate"
  };

  const activationLabels = {
    not_activated: "Not activated",
    partially_activated: "Partially activated",
    activated: "Activated"
  };

  const chartTheme = {
    colors: {
      primary: visitsCircleColors[0],
      text: tailwindColor("slate-900"),
      mutedText: tailwindColor("slate-500"),
      labelText: tailwindColor("slate-700"),
      axis: tailwindColor("slate-300"),
      grid: tailwindColor("slate-200"),
      white: tailwindColor("white")
    },
    series: chartSeriesColors
  };

  const companyTableSplitMetrics = [
    { key: "activeUsers", label: "Active users" },
    { key: "visits", label: "Visits" },
    { key: "engagedSeconds", label: "Engaged" },
    { key: "interactionPct", label: "Interaction" }
  ];
  const topCompaniesPageSize = 20;
  const companyTableNumericSortKeys = new Set([
    "activeUsers",
    "pagesUsed",
    "visits",
    "engagedSeconds",
    "avgEngagedSecondsPerUser",
    "interactionPct"
  ]);
  const companyTableDefaultSortDirections = {
    name: "asc",
    status: "asc",
    activeUsers: "desc",
    pagesUsed: "desc",
    visits: "desc",
    engagedSeconds: "desc",
    avgEngagedSecondsPerUser: "desc",
    interactionPct: "desc"
  };
  const companyTableStatusSort = companyStatusOrder.reduce((lookup, key, index) => {
    lookup[key] = index + 1;
    return lookup;
  }, {});
  const atRiskPageSize = 20;
  const atRiskNumericSortKeys = new Set([
    "riskScore",
    "activeUsers",
    "engagedSeconds",
    "productAreasUsed"
  ]);
  const atRiskTextSortKeys = new Set([
    "name",
    "suggestedAction"
  ]);
  const atRiskDefaultSortDirections = {
    name: "asc",
    riskScore: "desc",
    activeUsers: "desc",
    engagedSeconds: "desc",
    productAreasUsed: "desc",
    suggestedAction: "asc"
  };
  const newReactivatedPageSize = 20;
  const activationStageOrder = { not_activated: 0, partially_activated: 1, activated: 2 };
  const newReactivatedNumericSortKeys = new Set([
    "daysSinceStart",
    "activeUsers",
    "engagedSeconds",
    "productAreasUsed"
  ]);
  const newReactivatedDefaultSortDirections = {
    name: "asc",
    activationStage: "asc",
    daysSinceStart: "desc",
    activeUsers: "desc",
    engagedSeconds: "desc",
    productAreasUsed: "desc"
  };
  const expansionPageSize = 20;
  const expansionNumericSortKeys = new Set([
    "potentialScore",
    "activeUsers",
    "avgEngagedSecondsPerUser",
    "interactionPct",
    "productAreasUsed"
  ]);
  const expansionTextSortKeys = new Set(["name", "reason", "suggestedAction"]);
  const expansionDefaultSortDirections = {
    name: "asc",
    potentialScore: "desc",
    reason: "asc",
    activeUsers: "desc",
    avgEngagedSecondsPerUser: "desc",
    interactionPct: "desc",
    productAreasUsed: "desc",
    suggestedAction: "asc"
  };
  const lineEndLabelSeriesSuffix = " label connector";
  const lineHoverTrendSeriesSuffix = " hover trend";
  const companySearchDebounceMs = 220;
  const companySearchRecentStorageKey = `hymetry:recent-companies:${document.body?.dataset.projectId || "unknown-project"}`;

  let currentData = null;
  let periodChangeTooltipId = 0;
  let productAreaMixTooltipId = 0;
  let userHealthMixTooltipId = 0;
  let adoptionCellTooltipId = 0;
  let activationStageTooltipId = 0;
  let suggestedStepTooltipId = 0;
  let companySearchMounted = false;
  let companySearchDebounceId = 0;
  let scatterFiltersMounted = false;
  let productAreaColorByName = new Map();
  const productAreaColorResolver = globalScope.HymetryProductAreaColors?.createResolver({
    resolveColor: tailwindColor,
    palette: productAreaPalette
  }) || null;
  const companyTableState = {
    page: 1,
    sortKey: "engagedSeconds",
    sortDirection: "desc",
    isLoading: false,
    loadingToken: 0
  };
  const atRiskTableState = {
    page: 1,
    sortKey: "riskScore",
    sortDirection: "desc",
    isLoading: false,
    loadingToken: 0
  };
  const newReactivatedTableState = {
    page: 1,
    sortKey: "activationStage",
    sortDirection: "asc",
    isLoading: false,
    loadingToken: 0
  };
  const expansionTableState = {
    page: 1,
    sortKey: "potentialScore",
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
  const scatterFilterState = {
    status: "all",
    productArea: "all",
    minActiveUsers: "",
    search: ""
  };
  const companySearchState = {
    activeIndex: -1,
    isOpen: false,
    isLoading: false,
    query: "",
    remoteQuery: null,
    remoteResults: [],
    requestToken: 0,
    results: []
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

  function formatAverageUsers(value) {
    const numericValue = Number(value) || 0;
    return averageUsersFormatter.format(Math.round(numericValue * 100) / 100);
  }

  function formatPercent(value) {
    return `${Math.round(Number(value) || 0)}%`;
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
    let hours = Math.floor(seconds / 3600);
    let minutes = Math.round((seconds % 3600) / 60);

    if (minutes === 60) {
      hours += 1;
      minutes = 0;
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

  function chartUnavailable(element, message = "Chart library unavailable.") {
    if (!element) {
      return;
    }

    element.innerHTML = `<div class="flex h-full items-center justify-center rounded-lg bg-slate-50 text-sm text-slate-500">${escapeHtml(message)}</div>`;
  }

  function mountChart(element, option) {
    if (!element) {
      return null;
    }

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
    chart.setOption(option);
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

  function roundedDeltaValue(deltaValue) {
    return Math.round(Number(deltaValue) || 0);
  }

  function deltaDirection(deltaValue, invert = false) {
    const value = roundedDeltaValue(deltaValue);

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

  function formatDelta(deltaValue, unit) {
    const rounded = roundedDeltaValue(deltaValue);
    const prefix = rounded > 0 ? "+" : "";

    return unit === "pp" ? `${prefix}${rounded} pp` : `${prefix}${rounded}%`;
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

  function formatPeriodMetricValue(value, valueType, fallbackLabel = "") {
    const numericValue = Number(value) || 0;

    if (valueType === "percent") {
      return `${numericValue.toFixed(1)}%`;
    }

    if (valueType === "duration") {
      return fallbackLabel || formatDurationShort(numericValue);
    }

    return formatNumber(Math.round(numericValue));
  }

  function formatPeriodDelta(deltaValue, unit) {
    const numericValue = Number(deltaValue) || 0;
    const prefix = numericValue > 0 ? "+" : "";

    if (unit === "pp") {
      return `${prefix}${numericValue.toFixed(1)} pp`;
    }

    const rounded = Math.round(numericValue * 10) / 10;
    return `${prefix}${new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 }).format(rounded)}%`;
  }

  function buildPeriodChangeTooltip(display) {
    const currentLabel = formatPeriodMetricValue(display.currentValue, display.valueType, display.valueLabel);

    if (display.comparisonAvailable === false) {
      return {
        rows: [
          { label: "Current period", value: currentLabel },
          { label: "Previous period", value: "No data" },
          { label: "Change", value: "n/a" }
        ]
      };
    }

    const deltaValue = Number(display.deltaValue) || 0;
    const previousValue = display.deltaLabel === "New"
      ? 0
      : previousPeriodValue(display.currentValue, deltaValue, display.deltaUnit);
    const previousLabel = formatPeriodMetricValue(previousValue, display.valueType);
    const isNew = previousValue === 0 && Number(display.currentValue) > 0;

    return {
      rows: [
        { label: "Current period", value: currentLabel },
        { label: "Previous period", value: previousLabel },
        { label: "Change", value: isNew ? "New" : formatPeriodDelta(deltaValue, display.deltaUnit) }
      ]
    };
  }

  function renderPeriodChangeTooltip(display) {
    const tooltip = buildPeriodChangeTooltip(display);
    const tooltipId = `companies-period-change-tooltip-${periodChangeTooltipId}`;

    periodChangeTooltipId += 1;

    return {
      tooltipId,
      tooltipText: analyticsTooltips.text(tooltip.rows),
      tooltipHtml: analyticsTooltips.render({ rows: tooltip.rows })
    };
  }

  function getCompaniesTableMaxValues(rows) {
    return {
      activeUsers: Math.max(...rows.map((row) => row.activeUsers), 1),
      visits: Math.max(...rows.map((row) => row.visits), 1),
      engagedSeconds: Math.max(...rows.map((row) => row.engagedSeconds), 1)
    };
  }

  function getCompanyMetricDisplay(row, metricKey, maxValues) {
    switch (metricKey) {
      case "activeUsers":
        return {
          valueLabel: formatNumber(row.activeUsers),
          valueType: "count",
          currentValue: row.activeUsers,
          deltaValue: row.activeUsersDeltaPct,
          deltaLabel: row.activeUsersDeltaLabel,
          deltaUnit: "%",
          comparisonAvailable: row.comparisonAvailable !== false,
          barValue: (row.activeUsers / Math.max(maxValues.activeUsers, 1)) * 100
        };
      case "visits":
        return {
          valueLabel: formatNumber(row.visits),
          valueType: "count",
          currentValue: row.visits,
          deltaValue: row.visitsDeltaPct,
          deltaLabel: row.visitsDeltaLabel,
          deltaUnit: "%",
          comparisonAvailable: row.comparisonAvailable !== false,
          barValue: (row.visits / Math.max(maxValues.visits, 1)) * 100
        };
      case "engagedSeconds":
        return {
          valueLabel: formatDurationShort(row.engagedSeconds),
          valueType: "duration",
          currentValue: row.engagedSeconds,
          deltaValue: row.engagedDeltaPct,
          deltaLabel: row.engagedDeltaLabel,
          deltaUnit: "%",
          comparisonAvailable: row.comparisonAvailable !== false,
          barValue: (row.engagedSeconds / Math.max(maxValues.engagedSeconds, 1)) * 100
        };
      case "interactionPct":
        return {
          valueLabel: formatPercent(row.interactionPct),
          valueType: "percent",
          currentValue: row.interactionPct,
          deltaValue: row.interactionDeltaPp,
          deltaLabel: row.interactionDeltaLabel,
          deltaUnit: "pp",
          comparisonAvailable: row.comparisonAvailable !== false,
          barValue: row.interactionPct
        };
      default:
        return null;
    }
  }

  function renderMetricBarValue(display, metric) {
    const barWidth = Math.max(4, Math.round((clampPct(display.barValue) / 100) * 72));
    const valueLabel = escapeHtml(display.valueLabel);

    return `
      <div class="pages-value-bar" style="--pages-value-bar-width: ${barWidth}px;" aria-label="${escapeHtml(`${metric.label} ${display.valueLabel}`)}">
        <span class="pages-value-bar__bar bg-c-light-blue"></span>
        <span class="pages-value-bar__label">${valueLabel}</span>
      </div>
    `;
  }

  function renderCompanyMetricValueBarCell(row, metric, maxValues) {
    const display = getCompanyMetricDisplay(row, metric.key, maxValues);

    if (!display) {
      return "";
    }

    return `
      <div class="pages-metric-value">
        ${renderMetricBarValue(display, metric)}
      </div>
    `;
  }

  function getCompanySplitChangeScaleByMetric(rows, maxValues) {
    return companyTableSplitMetrics.reduce((lookup, metric) => {
      const maxAbsDelta = Math.max(
        ...rows.map((row) => {
          const display = getCompanyMetricDisplay(row, metric.key, maxValues);
          return Math.abs(Number(display?.deltaValue) || 0);
        }),
        1
      );

      lookup[metric.key] = maxAbsDelta;
      return lookup;
    }, {});
  }

  function renderCompanySplitChangeDeltaCell(row, metric, maxAbsDelta, maxValues) {
    const display = getCompanyMetricDisplay(row, metric.key, maxValues);

    if (!display) {
      return "";
    }

    const deltaValue = Number(display.deltaValue) || 0;
    const roundedDelta = roundedDeltaValue(deltaValue);
    const direction = deltaDirection(deltaValue);
    const trackWidth = direction === "negative" ? 17 : 36;
    const barWidth = roundedDelta === 0 ? 6 : Math.max(4, Math.round((Math.abs(deltaValue) / Math.max(maxAbsDelta, 1)) * trackWidth));
    const formattedDelta = formatDelta(deltaValue, display.deltaUnit);
    const tooltip = renderPeriodChangeTooltip(display);

    return `
      <div class="pages-change-delta metric-header-tooltip" data-change-direction="${direction}" style="--pages-change-bar-width: ${barWidth}px;" tabindex="0" aria-label="${escapeHtml(`${metric.label}. ${tooltip.tooltipText}`)}" aria-describedby="${tooltip.tooltipId}">
        <span class="pages-change-delta__plot">
          <span class="pages-change-delta__bar pages-change-delta__bar--${direction}"></span>
        </span>
        <span class="pages-change-delta__label ${deltaTextClass(deltaValue)}">${escapeHtml(formattedDelta)}</span>
        <span id="${tooltip.tooltipId}" class="metric-header-tooltip__content" role="tooltip">${tooltip.tooltipHtml}</span>
      </div>
    `;
  }

  function renderCompanySplitMetricChangeGroup(row, metric, maxAbsDelta, maxValues) {
    return `
      <td class="pages-split-change-cell py-3.5 pr-6 align-middle" data-split-metric="${escapeHtml(metric.key)}">
        <div class="pages-split-change-group">
          ${renderCompanyMetricValueBarCell(row, metric, maxValues)}
          ${renderCompanySplitChangeDeltaCell(row, metric, maxAbsDelta, maxValues)}
        </div>
      </td>
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

    mountCompaniesTableStickyHeader();
  }

  function mountStickyTableHeader(table) {
    const tableHead = table?.querySelector("thead");
    const scrollContainer = table?.closest("[data-companies-table-scroll]");

    if (!table || !tableHead || !scrollContainer) {
      return;
    }

    if (table.__hymetryStickyTableHeaderSync) {
      table.__hymetryStickyTableHeaderSync();
      return;
    }

    const stickyHeader = document.createElement("div");

    stickyHeader.id = "companies-table-sticky-header";
    stickyHeader.className = "companies-table-sticky-header";
    stickyHeader.setAttribute("aria-hidden", "true");
    document.body.appendChild(stickyHeader);

    const cloneTable = table.cloneNode(false);
    const cloneHead = tableHead.cloneNode(true);

    cloneHead.querySelectorAll("[id]").forEach((element) => element.removeAttribute("id"));
    cloneHead.querySelectorAll("[tabindex]").forEach((element) => element.removeAttribute("tabindex"));
    cloneTable.appendChild(cloneHead);
    stickyHeader.replaceChildren(cloneTable);

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
        const cloneCell = cloneHead.querySelectorAll("th")[index];
        const width = cell.getBoundingClientRect().width;

        if (cloneCell && width) {
          cloneCell.style.width = `${width}px`;
          cloneCell.style.minWidth = `${width}px`;
          cloneCell.style.maxWidth = `${width}px`;
        }
      });
      stickyHeader.scrollLeft = scrollContainer.scrollLeft;
    };

    syncStickyHeader();
    globalScope.addEventListener("scroll", syncStickyHeader, { passive: true });
    globalScope.addEventListener("resize", syncStickyHeader);
    scrollContainer.addEventListener("scroll", syncStickyHeader, { passive: true });
    table.__hymetryStickyTableHeaderSync = syncStickyHeader;
  }

  function mountCompaniesTableStickyHeader() {
    const table = document.querySelector("[data-companies-table-scroll] table");

    if (table) {
      mountStickyTableHeader(table);
    }
  }

  let splitChangeValueWidthSyncFrame = 0;

  function scheduleSplitChangeValueWidthSync() {
    if (splitChangeValueWidthSyncFrame) {
      return;
    }

    const requestFrame = globalScope.requestAnimationFrame || ((callback) => globalScope.setTimeout(callback, 0));

    splitChangeValueWidthSyncFrame = requestFrame(() => {
      splitChangeValueWidthSyncFrame = 0;
      syncSplitChangeValueWidths(document.getElementById("companies-table-body"));
    });
  }

  let splitChangeValueWidthSyncMounted = false;

  function mountSplitChangeValueWidthSync() {
    if (splitChangeValueWidthSyncMounted) {
      return;
    }

    splitChangeValueWidthSyncMounted = true;
    globalScope.addEventListener("resize", scheduleSplitChangeValueWidthSync);
    document.fonts?.ready?.then(scheduleSplitChangeValueWidthSync);
  }

  function statusBadge(status) {
    const meta = getCompanyStatusMeta(status);

    return `<span class="companies-badge ${meta.badge}">${escapeHtml(meta.label)}</span>`;
  }

  function typeBadge(type) {
    return statusBadge(type === "new" ? "new" : "reactivated");
  }

  function activationBadge(status) {
    const classes = {
      activated: "companies-badge--teal",
      partially_activated: "companies-badge--blue",
      not_activated: "companies-badge--gray"
    };
    const tooltipText = {
      activated: "Activated: multiple users, broad usage, and meaningful engagement.",
      partially_activated: "Partially activated: good early usage, but still missing broader adoption.",
      not_activated: "Not activated: no repeat usage or key workflow completed yet."
    };
    const tooltipId = `companies-activation-stage-tooltip-${activationStageTooltipId}`;

    activationStageTooltipId += 1;

    return `
      <span class="companies-activation-stage metric-header-tooltip" data-tooltip-kind="activation-stage" tabindex="0" aria-describedby="${tooltipId}">
        <span class="companies-badge ${classes[status] || "companies-badge--gray"}">${escapeHtml(activationLabels[status] || status)}</span>
        <span id="${tooltipId}" class="metric-header-tooltip__content" role="tooltip">${escapeHtml(tooltipText[status] || "Activation progress based on users, breadth, pages, and engaged time.")}</span>
      </span>
    `;
  }

  function riskBadge(reason) {
    const isSevere = /-7|-8|No activity|Users -60|Only 1/.test(reason);
    const badgeClass = isSevere ? "companies-badge--red" : "companies-badge--orange";

    return `<span class="companies-badge ${badgeClass}">${escapeHtml(reason)}</span>`;
  }

  function expansionPriorityBadge(priority) {
    const badgeClass = expansionPriorityBadgeClasses[priority] || "companies-badge--gray";

    return `<span class="companies-badge ${badgeClass}">${escapeHtml(expansionPriorityLabels[priority] || priority)}</span>`;
  }

  function normalizeProductAreaName(area) {
    if (area && typeof area === "object") {
      return String(area.name || area.productArea || area.product_area_name || area.product_area || area.key || "").trim() || "Unassigned";
    }

    return String(area || "").trim() || "Unassigned";
  }

  function collectProductAreaNames(data) {
    const names = [];
    const add = (area) => {
      const normalized = normalizeProductAreaName(area);

      if (normalized && !names.includes(normalized)) {
        names.push(normalized);
      }
    };

    (provider.productAreas || []).forEach(add);
    (data?.productAreas || []).forEach(add);
    (data?.companies || []).forEach((company) => {
      (company.productAreas || []).forEach(add);
      (company.productAreaDistribution || []).forEach((item) => add(item.productArea));
      (company.productAreaAdoption || []).forEach((cell) => add(cell.productArea));
      add(company.topProductArea);
    });

    return names;
  }

  function syncProductAreaPalette(data) {
    productAreaColorByName = new Map();
    productAreaColorResolver?.reset();
    const names = [];
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
    const addAdoptionCells = (cells) => {
      (cells || []).forEach((cell) => add(cell.productArea || cell.product_area_name || cell.name, cell.color));
    };
    const assignFallbackColors = () => {
      if (productAreaColorResolver) {
        productAreaColorResolver.finalize();
        names.forEach((area) => productAreaColorByName.set(area, productAreaColorResolver.color(area)));
        return;
      }

      names.forEach((area, index) => {
        if (productAreaColorByName.has(area)) {
          return;
        }

        productAreaColorByName.set(area, productAreaPalette[index % productAreaPalette.length]);
      });
    };

    (provider.productAreaOptions || []).forEach((area) => add(area));
    (provider.productAreas || []).forEach((area) => add(area));
    (data?.productAreaOptions || []).forEach((area) => add(area));
    (data?.productAreas || []).forEach((area) => add(area));
    (data?.companies || []).forEach((company) => {
      (company.productAreas || []).forEach((area) => add(area));
      addDistribution(company.productAreaDistribution);
      addAdoptionCells(company.productAreaAdoption);
      add(company.topProductArea);
    });
    (data?.newReactivatedCompanies || []).forEach((company) => {
      addDistribution(company.productAreaDistribution);
      addAdoptionCells(company.productAreaAdoption);
      add(company.topProductArea);
    });
    (data?.productAreaAdoption || []).forEach((row) => add(row.name || row.productArea));
    (data?.atRiskCompanies || []).forEach((company) => {
      addDistribution(company.productAreaDistribution);
      addAdoptionCells(company.productAreaAdoption);
    });
    (data?.expansionOpportunities || []).forEach((company) => {
      addDistribution(company.productAreaDistribution);
      addAdoptionCells(company.productAreaAdoption);
    });
    collectProductAreaNames(data).forEach((area) => add(area));
    assignFallbackColors();
  }

  function productAreaColor(area) {
    const areaName = normalizeProductAreaName(area);

    if (productAreaColorResolver) {
      return productAreaColorResolver.color(area);
    }

    if (!productAreaColorByName.has(areaName)) {
      productAreaColorByName.set(areaName, productAreaPalette[productAreaColorByName.size % productAreaPalette.length] || visitsCircleColors[0]);
    }

    return productAreaColorByName.get(areaName);
  }

  function productAreaDot(area) {
    return `<span class="companies-product-dot" style="background:${productAreaColor(area)}"></span>`;
  }

  function productAreaCell(area) {
    return `<span class="inline-flex items-center gap-2 whitespace-nowrap">${productAreaDot(area)}<span>${escapeHtml(area)}</span></span>`;
  }

  function userHealthColor(key) {
    const segment = userHealthSegments.find(([segmentKey]) => segmentKey === key);

    return tailwindColor(segment?.[2] || "slate-500");
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

  function productAreaUsageCell(row, scaleMax) {
    const usageItems = productAreaUsageItems(row);
    const totalUsageSeconds = usageItems.reduce((sum, item) => sum + item.engagedSeconds, 0);
    const safeScaleMax = Math.max(Number(scaleMax) || 0, totalUsageSeconds, 1);
    const barWidthPct = totalUsageSeconds ? Math.min((totalUsageSeconds / safeScaleMax) * 100, 100) : 0;
    const name = row.name || row.companyName || "Company";
    const tooltipId = `companies-area-mix-tooltip-${productAreaMixTooltipId}`;

    productAreaMixTooltipId += 1;

    const tooltipRows = usageItems.map((item) => {
      const area = item.productArea || "Unknown";
      const share = totalUsageSeconds ? (item.engagedSeconds / totalUsageSeconds) * 100 : 0;
      const visits = Math.max(0, Math.round(Number(item.visits) || 0));

      return {
        label: area,
        value: `${formatDurationShort(item.engagedSeconds)} · ${formatPercent(share)} · ${formatNumber(visits)} ${visits === 1 ? "visit" : "visits"}`,
        marker: productAreaColor(area)
      };
    });
    const summaryRows = [
      { label: "Total", value: formatDurationShort(totalUsageSeconds) },
      { label: "Areas used", value: formatNumber(usageItems.length) }
    ];
    const renderedTooltipRows = tooltipRows.length
      ? tooltipRows
      : [{ label: "Usage", value: "No usage" }];
    const segments = usageItems
      .map((item) => {
        const area = item.productArea || "Unknown";
        const percent = totalUsageSeconds ? (item.engagedSeconds / totalUsageSeconds) * 100 : 0;

        return `<span class="companies-area-mix__segment" style="--area-color:${productAreaColor(area)}; flex: 0 0 ${percent}%"></span>`;
      })
      .join("");
    const ariaLabel = `${name}. ${analyticsTooltips.text(renderedTooltipRows.concat(summaryRows))}`;
    const tooltipHtml = analyticsTooltips.render({
      title: name,
      sections: [{ rows: renderedTooltipRows }, { rows: summaryRows }]
    });

    return `
      <div class="companies-area-mix companies-area-usage metric-header-tooltip" data-tooltip-kind="area-mix" data-has-usage="${totalUsageSeconds > 0}" style="--area-usage-width:${barWidthPct}%;" tabindex="0" aria-label="${escapeHtml(ariaLabel)}" aria-describedby="${tooltipId}">
        <span class="companies-area-usage__bar">${segments}</span>
        <span id="${tooltipId}" class="metric-header-tooltip__content" role="tooltip">${tooltipHtml}</span>
      </div>
    `;
  }

  function formatUserCount(value) {
    const count = Math.max(0, Math.round(Number(value) || 0));

    return `${formatNumber(count)} ${count === 1 ? "user" : "users"}`;
  }

  function userHealthMixCell(row) {
    const mix = row.userHealthMix || {};
    const totalUsers = userHealthSegments.reduce((sum, [key]) => sum + Math.max(0, Math.round(Number(mix[key]) || 0)), 0);
    const denominator = totalUsers || Math.max(0, Math.round(Number(row.activeUsers) || 0));
    const tooltipId = `companies-user-health-tooltip-${userHealthMixTooltipId}`;

    userHealthMixTooltipId += 1;

    if (!denominator) {
      return `<span class="text-sm text-slate-400">No active users</span>`;
    }

    const tooltipRows = userHealthSegments.map(([key, label]) => {
      const count = Math.max(0, Math.round(Number(mix[key]) || 0));
      const percent = denominator ? count / denominator * 100 : 0;

      return {
        label,
        value: `${formatUserCount(count)} · ${formatPercent(percent)}`,
        marker: userHealthColor(key)
      };
    });
    const summaryRows = [
      { label: "Active users", value: formatNumber(row.activeUsers) },
      { label: "Top user share", value: formatPercent(row.topUserSharePct) },
      { label: "Median features / user", value: formatNumber(row.medianFeaturesPerUser) }
    ];
    const segments = userHealthSegments
      .map(([key]) => {
        const count = Math.max(0, Math.round(Number(mix[key]) || 0));
        const percent = denominator ? count / denominator * 100 : 0;

        if (!count) {
          return "";
        }

        return `<span class="companies-area-mix__segment" style="--area-color:${userHealthColor(key)}; flex: 0 0 ${percent}%"></span>`;
      })
      .join("");
    const companyName = row.name || row.companyName || "Company";
    const ariaLabel = `${companyName}. ${analyticsTooltips.text(tooltipRows.concat(summaryRows))}`;
    const tooltipHtml = analyticsTooltips.render({
      title: companyName,
      sections: [{ rows: tooltipRows }, { rows: summaryRows }]
    });

    return `
      <div class="companies-area-mix companies-user-health-mix metric-header-tooltip" data-tooltip-kind="area-mix" tabindex="0" aria-label="${escapeHtml(ariaLabel)}" aria-describedby="${tooltipId}">
        ${segments}
        <span id="${tooltipId}" class="metric-header-tooltip__content" role="tooltip">${tooltipHtml}</span>
      </div>
    `;
  }

  function formatRelativeDays(days) {
    const rounded = Math.max(0, Math.round(Number(days) || 0));

    if (rounded === 0) {
      return "Today";
    }

    return `${rounded}d ago`;
  }

  function cohortCompanyCell(row) {
    const companyName = row.companyName || row.name || row.companyId || row.id || "Unknown company";
    const href = companyDetailHref(row);

    if (!href) {
      return `<span class="whitespace-nowrap font-medium text-slate-800">${escapeHtml(companyName)}</span>`;
    }
    return `
      <a href="${escapeHtml(href)}" class="whitespace-nowrap font-medium text-sky-800 underline-offset-2 hover:underline">${escapeHtml(companyName)}</a>
    `;
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
    const tooltipId = `companies-adoption-cell-tooltip-${adoptionCellTooltipId}`;
    const relativeActivityPct = adoptionCellRelativeActivityPct(cell, maxEngagedSeconds);
    const usageLabel = cell.used && relativeActivityPct <= 0 ? adoptionCellIntensityGrade(1).label : adoptionCellUsageLabel(relativeActivityPct);
    const relativeActivityLabel = formatPercent(relativeActivityPct);

    adoptionCellTooltipId += 1;

    const rows = [
      { label: "Product area", value: cell.productArea },
      { label: "Relative activity", value: relativeActivityLabel },
      { label: "Usage intensity", value: usageLabel }
    ];

    if (cell.used) {
      rows.push(
        { label: "Engaged time", value: formatDurationShort(cell.engagedSeconds) },
        { label: "Visits", value: formatNumber(cell.visits) },
        { label: "Active users", value: formatNumber(cell.activeUsers) },
        { label: "Pages/features", value: formatNumber(cell.pagesUsed) }
      );
    }

    return {
      tooltipId,
      tooltipText: `${row.companyName}. ${analyticsTooltips.text(rows)}`,
      tooltipHtml: analyticsTooltips.render({ title: row.companyName, rows })
    };
  }

  function adoptionMatrixCell(cell, row, maxEngagedSeconds) {
    const color = productAreaColor(cell.productArea);
    const tooltip = adoptionCellTooltip(cell, row, maxEngagedSeconds);

    if (!cell.used) {
      return `
        <span class="companies-adoption-cell metric-header-tooltip" data-tooltip-kind="adoption-cell" data-used="false" tabindex="0" aria-label="${escapeHtml(tooltip.tooltipText)}" aria-describedby="${tooltip.tooltipId}">
          <span id="${tooltip.tooltipId}" class="metric-header-tooltip__content" role="tooltip">${tooltip.tooltipHtml}</span>
        </span>
      `;
    }

    const intensity = adoptionCellColorOpacity(adoptionCellRelativeActivityPct(cell, maxEngagedSeconds));

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
    const areas = provider.productAreas || [];

    return `
      <div class="companies-adoption-matrix" aria-label="${escapeHtml(`${row.companyName} product area adoption`)}">
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

  function newReactivatedMetricBarCell(row, metric, maxValue) {
    const value = Number(row[metric.key]) || 0;
    const display = {
      valueLabel: metric.formatValue(value),
      barValue: (value / Math.max(maxValue, 1)) * 100
    };

    return `
      <td class="py-3.5 pr-6 align-middle" data-split-metric="${escapeHtml(metric.key)}">
        <div class="pages-metric-value">
          ${renderMetricBarValue(display, metric)}
        </div>
      </td>
    `;
  }

  function suggestedNextStepCell(row) {
    const tooltipId = `companies-suggested-step-tooltip-${suggestedStepTooltipId}`;
    const step = row.suggestedNextStep || "";
    const suggestedArea = step
      .replace(/^Introduce\s+/i, "")
      .replace(/^Expand into\s+/i, "")
      .replace(/^Guide first workflow in\s+/i, "");
    const tooltipText = /^Guide first workflow/i.test(step)
      ? `${row.productAreasUsed} areas used. Focus this account on completing a first repeatable workflow before expanding adoption.`
      : `${row.productAreasUsed} areas used, but ${suggestedArea || "the next product area"} is missing and is a common next area for similar accounts.`;

    suggestedStepTooltipId += 1;

    return `
      <span class="companies-suggested-step metric-header-tooltip" data-tooltip-kind="suggested-step" tabindex="0" aria-describedby="${tooltipId}">
        ${escapeHtml(step)}
        <span id="${tooltipId}" class="metric-header-tooltip__content" role="tooltip">${escapeHtml(tooltipText)}</span>
      </span>
    `;
  }

  function companyCell(row) {
    const initials = row.name
      .split(/\s+/)
      .map((part) => part[0])
      .join("")
      .slice(0, 2)
      .toUpperCase();

    return `
      <div class="flex min-w-0 items-center gap-3">
        <span class="companies-avatar">${escapeHtml(initials)}</span>
        <span class="min-w-0">
          <span class="block truncate font-medium text-slate-900">${escapeHtml(row.name)}</span>
          <span class="block truncate text-xs text-slate-500">${escapeHtml(row.domain || "")}</span>
        </span>
      </div>
    `;
  }

  function renderSparkline(values, status) {
    const series = Array.isArray(values) ? values.map((value) => Number(value) || 0) : [];

    if (series.length < 2) {
      return "";
    }

    const width = 86;
    const height = 28;
    const min = Math.min(...series);
    const max = Math.max(...series);
    const range = Math.max(max - min, 1);
    const points = series.map((value, index) => {
      const x = (index / (series.length - 1)) * width;
      const y = height - ((value - min) / range) * (height - 4) - 2;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    });
    const color = tailwindColor(getCompanyStatusMeta(status).color || "c-blue");

    return `
      <svg class="companies-row-trend" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" aria-hidden="true">
        <polyline points="${points.join(" ")}" fill="none" stroke="${color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></polyline>
      </svg>
    `;
  }

  function renderKpiCards(data) {
    const container = document.getElementById("companies-kpis");
    const grid = container?.querySelector("[data-pages-kpis-grid]");
    const template = document.getElementById("companies-kpi-card-template");

    if (!container || !grid || !template) {
      return;
    }

    const kpis = [
      data.kpis.activeCompanies,
      data.kpis.newReactivatedCompanies,
      data.kpis.medianAdoptionBreadth,
      data.kpis.atRiskCompanies
    ];

    grid.innerHTML = "";

    if (!kpis.length) {
      grid.innerHTML = `<div class="col-span-full py-8 text-center text-slate-500">No company activity detected for this period.</div>`;
      return;
    }

    kpis.forEach((kpi, index) => {
      const fragment = template.content.cloneNode(true);
      const labelElement = fragment.querySelector("[data-pages-kpi-label]");
      const valueElement = fragment.querySelector("[data-pages-kpi-value]");
      const secondaryElement = fragment.querySelector("[data-pages-kpi-secondary]");
      const deltaElement = fragment.querySelector("[data-pages-kpi-delta]");
      const trendElement = fragment.querySelector("[data-pages-kpi-trend]");

      if (labelElement) {
        labelElement.textContent = kpi.label;
      }

      if (valueElement) {
        valueElement.textContent = kpi.value;
      }

      if (secondaryElement) {
        secondaryElement.textContent = kpi.secondary || "";
        secondaryElement.hidden = !kpi.secondary;
      }

      if (deltaElement) {
        deltaElement.textContent = kpi.delta || "";
        deltaElement.setAttribute("data-delta-direction", kpi.deltaType || "neutral");
      }

      if (trendElement) {
        trendElement.setAttribute("data-company-kpi-index", String(index));
        trendElement.hidden = !kpi?.sparkline?.length;
      }

      grid.appendChild(fragment);
    });

    container.querySelectorAll("[data-company-kpi-index]").forEach((element) => {
      const index = Number(element.getAttribute("data-company-kpi-index"));
      const kpi = kpis[index];

      if (!kpi?.sparkline?.length) {
        return;
      }

      mountChart(element, createKpiTrendOption(
        kpi.sparkline,
        element,
        kpi.deltaType,
        kpi.sparklineLabels,
        kpi.sparklineLabel || kpi.label,
        kpi.sparklineValueType,
        kpi.sparklineScope,
        kpi.sparklineRender
      ));
    });
  }

  function alignKpiTrendLabels(labels, length) {
    const count = Math.max(0, Number(length) || 0);
    const source = Array.isArray(labels) ? labels.filter(Boolean) : [];

    if (!count) {
      return [];
    }

    if (source.length >= count) {
      return source.slice(source.length - count);
    }

    return Array.from({ length: count }, (_, index) => source[index] || String(index + 1));
  }

  // "columns" reads each point as an independent daily count; "step" holds a
  // level between dates, which is what an end-of-day state looks like. Whether
  // the line is curved stays a question about the scope, not the render mode:
  // a daily observation is a real point and must not be smoothed away.
  function kpiTrendSeries(series, render, { lineColor, fillColor, smooth }) {
    if (render === "columns") {
      return {
        type: "bar",
        data: series,
        itemStyle: {
          color: lineColor,
          borderRadius: [2, 2, 0, 0]
        }
      };
    }

    return {
      type: "line",
      data: series,
      step: render === "step" ? "end" : false,
      smooth: render === "step" ? false : smooth,
      symbol: "none",
      lineStyle: {
        color: lineColor,
        width: 2
      },
      ...(render === "area" ? { areaStyle: { color: fillColor } } : {})
    };
  }

  function createKpiTrendOption(
    values,
    scopeElement,
    deltaType,
    labels = [],
    metricLabel = "Value",
    valueType = "number",
    trendScope = "period_to_date",
    render = ""
  ) {
    const lineColor = tailwindColor("blue-400");
    const fillColor = tailwindColor("blue-50");
    const series = values.map((value) => Number(value) || 0);
    const trendLabels = alignKpiTrendLabels(labels, series.length);
    // A filled line stays the default. Only the cards that asked for a
    // different reading declare one, so the rest are untouched.
    const seriesRender = render || "area";

    return {
      animation: false,
      tooltip: analyticsTooltips.echarts({
        trigger: "axis",
        appendTo: "body",
        confine: false,
        formatter: (params) => {
          const item = (Array.isArray(params) ? params : [params])[0];

          if (!item) {
            return "";
          }

          const dateLabel = item.axisValueLabel || item.axisValue || "";
          const title = trendScope === "daily"
            ? dateLabel
            : `${trendScope === "as_of" ? "As of" : "Through"} ${dateLabel}`.trim();

          return analyticsTooltips.render({
            title,
            rows: [{
              label: metricLabel,
              value: valueType === "areas"
                ? `${formatAverageUsers(item.value)} areas`
                : formatNumber(item.value)
            }]
          });
        }
      }),
      grid: {
        left: 0,
        right: 0,
        top: 4,
        bottom: 0
      },
      xAxis: {
        type: "category",
        show: false,
        boundaryGap: seriesRender === "columns",
        data: trendLabels.length ? trendLabels : series.map((_, index) => index + 1)
      },
      yAxis: {
        type: "value",
        show: false,
        // Columns are read against zero; a level or a curve is read against the
        // rest of its own series.
        min: seriesRender === "columns" ? 0 : "dataMin",
        max: compactAxisMax(series)
      },
      series: [
        {
          ...kpiTrendSeries(series, seriesRender, {
            lineColor,
            fillColor,
            smooth: !["daily", "as_of"].includes(trendScope)
          }),
          // Hovering a sparkline shows its tooltip without restyling the mark,
          // whichever shape the card chose.
          emphasis: {
            disabled: true
          }
        }
      ]
    };
  }

  function createHealthDistributionOption(data) {
    const rows = data.healthDistribution || [];
    const total = rows.reduce((sum, row) => sum + row.count, 0) || 1;

    return {
      animation: false,
      tooltip: analyticsTooltips.echarts({
        trigger: "item",
        confine: true,
        formatter: (params) => {
          const item = rows[params.seriesIndex] || {};
          const meta = getCompanyStatusMeta(item.status);

          return analyticsTooltips.render({
            title: item.label,
            rows: [
              { label: "Companies", value: formatNumber(item.count) },
              { label: "Share", value: `${item.pct}%` },
              { label: "Definition", value: meta.definition || "—" }
            ]
          });
        }
      }),
      legend: {
        show: false
      },
      grid: {
        left: 0,
        right: 0,
        top: 6,
        bottom: 0,
        containLabel: false
      },
      xAxis: {
        type: "value",
        max: total,
        show: false
      },
      yAxis: {
        type: "category",
        data: [""],
        show: false
      },
      series: rows.map((item) => {
        const meta = getCompanyStatusMeta(item.status);

        return {
          name: item.label,
          type: "bar",
          stack: "health",
          barWidth: 58,
          data: [item.count],
          itemStyle: {
            color: tailwindColor(meta.color || "slate-400"),
            borderColor: chartTheme.colors.white,
            borderWidth: 2,
            borderRadius: 4
          },
          label: {
            show: true,
            position: "inside",
            color: chartTheme.colors.white,
            fontSize: 11,
            fontWeight: 600,
            lineHeight: 14,
            textBorderColor: tailwindAlpha("slate-900", 0.22),
            textBorderWidth: 2,
            formatter: () => `${item.label}\n${formatNumber(item.count)}`
          },
          emphasis: {
            disabled: false,
            itemStyle: {
              shadowBlur: 8,
              shadowColor: tailwindAlpha("slate-900", 0.14)
            }
          },
          blur: {
            itemStyle: {
              opacity: 1
            },
            label: {
              opacity: 1
            }
          }
        };
      })
    };
  }

  function buildHealthDistributionSegments(rows, width) {
    const total = rows.reduce((sum, item) => sum + item.count, 0) || 1;
    const plotWidth = Math.max(320, Number(width) || 320);
    const minSegmentWidth = plotWidth < 640 ? 42 : 52;
    const rawSegments = rows.map((item) => {
      const rawWidth = (item.count / total) * plotWidth;

      return {
        item,
        rawWidth,
        isSmall: rawWidth < minSegmentWidth
      };
    });
    const smallSegments = rawSegments.filter((segment) => segment.isSmall);
    const regularSegments = rawSegments.filter((segment) => !segment.isSmall);
    const smallWidthTotal = Math.min(plotWidth * 0.44, smallSegments.length * minSegmentWidth);
    const adjustedMinWidth = smallSegments.length ? smallWidthTotal / smallSegments.length : 0;
    const regularRawTotal = regularSegments.reduce((sum, segment) => sum + segment.rawWidth, 0) || 1;
    const regularWidthTotal = Math.max(0, plotWidth - smallWidthTotal);
    let cursor = 0;

    return rawSegments.map((segment) => {
      const { item } = segment;
      const status = normalizeCompanyStatus(item.status);
      const meta = getCompanyStatusMeta(status);
      const widthPx = segment.isSmall
        ? adjustedMinWidth
        : (segment.rawWidth / regularRawTotal) * regularWidthTotal;
      const x0 = cursor;
      const x1 = cursor + widthPx;
      const shortLabels = {
        activated: "Activated",
        reactivated: "React.",
        at_risk: "Risk"
      };
      const label = widthPx < 48
        ? formatNumber(item.count)
        : `${shortLabels[status] || item.label}\n${formatNumber(item.count)}`;

      cursor = x1;

      return {
        status,
        label: item.label,
        count: item.count,
        countLabel: formatNumber(item.count),
        pct: item.pct,
        pctLabel: `${item.pct}%`,
        definition: meta.definition,
        color: tailwindColor(meta.color || "slate-400"),
        x0,
        x1,
        widthPx,
        labelText: label
      };
    });
  }

  function createHealthDistributionVegaSpec(rows, config) {
    const width = Math.max(320, Number(config.width) || 320);
    const segments = buildHealthDistributionSegments(rows, width);

    return {
      $schema: "https://vega.github.io/schema/vega/v5.json",
      width,
      height: 96,
      padding: {
        top: 8,
        right: 0,
        bottom: 8,
        left: 0
      },
      background: chartTheme.colors.white,
      config: {
        font: "Inter, ui-sans-serif, system-ui, sans-serif"
      },
      data: [
        {
          name: "segments",
          values: segments
        }
      ],
      marks: [
        {
          name: "healthSegments",
          type: "rect",
          from: { data: "segments" },
          encode: {
            enter: {
              x: { field: "x0" },
              x2: { field: "x1" },
              y: { value: 16 },
              y2: { value: 80 },
              fill: { field: "color" },
              fillOpacity: { value: 0.66 },
              stroke: { value: chartTheme.colors.white },
              strokeWidth: { value: 2 },
              cornerRadius: { value: 5 },
              tooltip: {
                signal:
                  "{'Status': datum.label, 'Companies': format(datum.count, ','), 'Share': datum.pctLabel, 'Definition': datum.definition}"
              }
            },
            hover: {
              fillOpacity: { value: 0.9 },
              strokeWidth: { value: 3 }
            }
          }
        },
        {
          name: "healthSegmentLabels",
          type: "text",
          from: { data: "segments" },
          encode: {
            enter: {
              x: { signal: "(datum.x0 + datum.x1) / 2" },
              y: { value: 48 },
              align: { value: "center" },
              baseline: { value: "middle" },
              text: { field: "labelText" },
              lineBreak: { value: "\n" },
              lineHeight: { value: 15 },
              fill: { value: "#000000" },
              fontSize: [
                { test: "datum.widthPx < 48", value: 11 },
                { value: 12 }
              ],
              fontWeight: { value: 500 },
              limit: { signal: "max(datum.widthPx - 8, 8)" },
              ellipsis: { value: "" },
              tooltip: {
                signal:
                  "{'Status': datum.label, 'Companies': format(datum.count, ','), 'Share': datum.pctLabel, 'Definition': datum.definition}"
              }
            }
          }
        }
      ]
    };
  }

  function mountHealthDistributionVega(element, rows) {
    if (!element) {
      return;
    }

    disposeVega(element);

    if (element.__hymetryHealthResizeObserver) {
      element.__hymetryHealthResizeObserver.disconnect();
      element.__hymetryHealthResizeObserver = null;
    }

    if (!globalScope.vegaEmbed) {
      chartUnavailable(element, "Vega is unavailable.");
      return;
    }

    let isFontReady = !globalScope.document?.fonts?.load;
    let isFontRenderQueued = false;
    const fontReadyPromise = isFontReady
      ? Promise.resolve()
      : Promise.all([
        globalScope.document.fonts.load('500 12px "Inter"'),
        globalScope.document.fonts.ready
      ]);

    const render = () => {
      const width = Math.max(320, Math.round(element.clientWidth || 0));
      const token = `${Date.now()}-${Math.random()}`;

      element.__hymetryVegaRenderToken = token;
      disposeVega(element);

      globalScope.vegaEmbed(element, createHealthDistributionVegaSpec(rows, { width }), {
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
        .catch(() => chartUnavailable(element, "Unable to render company health distribution."));
    };

    const renderWhenFontReady = () => {
      if (isFontReady) {
        render();
        return;
      }

      if (isFontRenderQueued) {
        return;
      }

      isFontRenderQueued = true;
      fontReadyPromise
        .then(() => {
          isFontReady = true;
          isFontRenderQueued = false;
          render();
        })
        .catch(() => {
          isFontReady = true;
          isFontRenderQueued = false;
          render();
        });
    };

    renderWhenFontReady();

    if (globalScope.ResizeObserver) {
      let animationFrame = null;
      const observer = new ResizeObserver(() => {
        if (animationFrame) {
          globalScope.cancelAnimationFrame(animationFrame);
        }

        animationFrame = globalScope.requestAnimationFrame(renderWhenFontReady);
      });

      observer.observe(element);
      element.__hymetryHealthResizeObserver = observer;
    }
  }

  function renderHealthDistribution(data) {
    const container = document.getElementById("company-health-distribution-chart");
    const rows = data.healthDistribution || [];

    if (!container) {
      return;
    }

    if (!rows.length) {
      container.innerHTML = `<div class="flex h-full w-full items-center justify-center text-center text-slate-500">No company activity detected for this period.</div>`;
      return;
    }

    mountHealthDistributionVega(container, rows);
  }

  function buildHealthDistributionEchartsSegments(rows) {
    const total = rows.reduce((sum, item) => sum + item.count, 0) || 1;
    const minPct = 4.5;
    const rawSegments = rows.map((item) => {
      const rawPct = (item.count / total) * 100;

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
      const status = normalizeCompanyStatus(item.status);
      const meta = getCompanyStatusMeta(status);
      const widthPct = segment.isSmall ? smallPct : (segment.rawPct / regularRawTotal) * regularPctTotal;
      const x0 = cursor;
      const x1 = cursor + widthPct;
      const shortLabels = {
        activated: "Activated",
        reactivated: "React.",
        at_risk: "Risk"
      };
      const labelText = widthPct < 5.5
        ? formatNumber(item.count)
        : `${shortLabels[status] || item.label}\n${formatNumber(item.count)}`;

      cursor = x1;

      return {
        status,
        label: item.label,
        count: item.count,
        pct: item.pct,
        pctLabel: `${item.pct}%`,
        definition: meta.definition,
        color: tailwindColor(meta.color || "slate-400"),
        x0,
        x1,
        widthPct,
        labelText,
        value: [x0, x1, 0]
      };
    });
  }

  function createHealthDistributionEchartsOption(data) {
    const rows = data.healthDistribution || [];
    const segments = buildHealthDistributionEchartsSegments(rows);

    return {
      animation: false,
      tooltip: analyticsTooltips.echarts({
        trigger: "item",
        confine: true,
        formatter: (params) => {
          const item = params.data || {};

          return analyticsTooltips.render({
            title: item.label,
            rows: [
              { label: "Companies", value: formatNumber(item.count || 0) },
              { label: "Share", value: item.pctLabel || "0%" },
              { label: "Definition", value: item.definition || "—" }
            ]
          });
        }
      }),
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

  function renderHealthDistributionEcharts(data) {
    const element = document.getElementById("company-health-distribution-echarts");

    if (!element) {
      return;
    }

    if (!data.healthDistribution?.length) {
      element.innerHTML = `<div class="flex h-full w-full items-center justify-center text-center text-slate-500">No company activity detected for this period.</div>`;
      return;
    }

    mountChart(element, createHealthDistributionEchartsOption(data));
  }

  function compareCompaniesByCurrentSort(a, b) {
    const sortKey = companyTableState.sortKey;
    const direction = companyTableState.sortDirection === "asc" ? 1 : -1;
    let comparison = 0;

    if (sortKey === "name") {
      comparison = String(a.name || "").localeCompare(String(b.name || ""));
    } else if (sortKey === "status") {
      const leftStatus = normalizeCompanyStatus(a.status);
      const rightStatus = normalizeCompanyStatus(b.status);
      comparison = (companyTableStatusSort[leftStatus] || 99) - (companyTableStatusSort[rightStatus] || 99);
    } else if (companyTableNumericSortKeys.has(sortKey)) {
      comparison = (Number(a[sortKey]) || 0) - (Number(b[sortKey]) || 0);
    }

    return comparison * direction || String(a.name || "").localeCompare(String(b.name || ""));
  }

  function topCompanyRows(data) {
    return (data.companies || []).slice().sort(compareCompaniesByCurrentSort);
  }

  function compareAtRiskByCurrentSort(a, b) {
    const sortKey = atRiskTableState.sortKey;
    const direction = atRiskTableState.sortDirection === "asc" ? 1 : -1;
    let comparison = 0;

    if (atRiskTextSortKeys.has(sortKey)) {
      comparison = String(a[sortKey] || "").localeCompare(String(b[sortKey] || ""));
    } else if (atRiskNumericSortKeys.has(sortKey)) {
      comparison = (Number(a[sortKey]) || 0) - (Number(b[sortKey]) || 0);
    }

    return comparison * direction || String(a.name || "").localeCompare(String(b.name || ""));
  }

  function atRiskTableRows(data) {
    return (data.atRiskCompanies || []).slice().sort(compareAtRiskByCurrentSort);
  }

  function compareNewReactivatedByCurrentSort(a, b) {
    const sortKey = newReactivatedTableState.sortKey;
    const direction = newReactivatedTableState.sortDirection === "asc" ? 1 : -1;
    let comparison = 0;

    if (sortKey === "name") {
      comparison = String(a.name || "").localeCompare(String(b.name || ""));
    } else if (sortKey === "activationStage") {
      comparison = (activationStageOrder[a.activationStage] ?? 0) - (activationStageOrder[b.activationStage] ?? 0);
    } else if (newReactivatedNumericSortKeys.has(sortKey)) {
      comparison = (Number(a[sortKey]) || 0) - (Number(b[sortKey]) || 0);
    }

    return comparison * direction || String(a.name || "").localeCompare(String(b.name || ""));
  }

  function newReactivatedTableRows(data) {
    return (data.newReactivatedCompanies || []).slice().sort(compareNewReactivatedByCurrentSort);
  }

  function compareExpansionByCurrentSort(a, b) {
    const sortKey = expansionTableState.sortKey;
    const direction = expansionTableState.sortDirection === "asc" ? 1 : -1;
    let comparison = 0;

    if (expansionTextSortKeys.has(sortKey)) {
      comparison = String(a[sortKey] || "").localeCompare(String(b[sortKey] || ""));
    } else if (expansionNumericSortKeys.has(sortKey)) {
      comparison = (Number(a[sortKey]) || 0) - (Number(b[sortKey]) || 0);
    }

    return comparison * direction || String(a.name || "").localeCompare(String(b.name || ""));
  }

  function expansionTableRows(data) {
    return (data.expansionOpportunities || []).slice().sort(compareExpansionByCurrentSort);
  }

  function companyPaginationIcon(direction) {
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

  /**
   * Shared paging and sorting behaviour for one overview table.
   *
   * Both overview tables page the same way: a server page when the provider can
   * fetch one, an in-memory slice otherwise, with the same loading overlay,
   * header scroll-back, and stale-response guard around either path.
   */
  function createTablePaginationController(config) {
    const {
      state,
      pageSize,
      tableKey,
      rowKey,
      scrollSelector,
      loadingSelector,
      paginationSelector,
      pageActionAttribute,
      sortAttribute,
      defaultSortKey,
      defaultSortDirections,
      sortedRows,
      render,
      requestRows,
      afterSortButtonsUpdate
    } = config;

    let sortMounted = false;

    function pageCount(rows) {
      return tablePageCount(currentData, tableKey, rows, pageSize);
    }

    function currentPageCount() {
      return pageCount(currentData ? sortedRows(currentData) : []);
    }

    function tableHead() {
      return document.querySelector(`${scrollSelector} thead`);
    }

    function stickyHeaderOffset() {
      return document.querySelector("body > nav")?.getBoundingClientRect().height || 48;
    }

    function isHeaderVisible() {
      const head = tableHead();

      if (!head) {
        return true;
      }

      const rect = head.getBoundingClientRect();

      return rect.top >= stickyHeaderOffset() && rect.bottom <= globalScope.innerHeight;
    }

    function scrollHeaderIntoView() {
      const head = tableHead();

      if (!head) {
        return;
      }

      globalScope.scrollTo({
        top: Math.max(0, globalScope.scrollY + head.getBoundingClientRect().top - stickyHeaderOffset() - 12),
        behavior: "smooth"
      });
    }

    function setLoading(isLoading) {
      const overlay = document.querySelector(loadingSelector);
      const requestFrame = globalScope.requestAnimationFrame || ((callback) => globalScope.setTimeout(callback, 0));

      document.querySelector(scrollSelector)?.setAttribute("aria-busy", String(isLoading));

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

    function updateSortButtons() {
      document.querySelectorAll(`[${sortAttribute}]`).forEach((button) => {
        const isActive = button.getAttribute(sortAttribute) === state.sortKey;

        button.setAttribute("data-sort-direction", isActive ? state.sortDirection : "");
        button.setAttribute("aria-pressed", String(isActive));
      });

      afterSortButtonsUpdate?.();
    }

    function renderPagination(totalPages) {
      const container = document.querySelector(paginationSelector);

      if (!container) {
        return;
      }

      if (totalPages <= 1) {
        container.hidden = true;
        container.innerHTML = "";
        return;
      }

      const currentPage = Math.min(totalPages, Math.max(1, state.page));
      const disabledAttr = state.isLoading ? " disabled" : "";

      container.hidden = false;
      container.innerHTML = `
        ${
          currentPage > 2
            ? `<button type="button" class="font-medium text-sky-700 hover:text-sky-800" ${pageActionAttribute}="first"${disabledAttr}>Go to first page</button>`
            : `<span aria-hidden="true"></span>`
        }
        <div class="flex items-center justify-between gap-6 sm:justify-end">
          ${
            currentPage > 1
              ? `<button type="button" class="inline-flex h-8 w-8 items-center justify-center text-sky-700 hover:text-sky-800" ${pageActionAttribute}="previous" aria-label="Back to previous page"${disabledAttr}>${companyPaginationIcon("previous")}</button>`
              : `<span class="invisible h-8 w-8" aria-hidden="true"></span>`
          }
          <span class="text-slate-700">Page ${currentPage}/${totalPages}</span>
          ${
            currentPage < totalPages
              ? `<button type="button" class="inline-flex items-center gap-2 rounded-md border border-slate-200 bg-transparent px-4 py-3 font-medium text-sky-700 duration-150 hover:bg-slate-100" ${pageActionAttribute}="next"${disabledAttr}>Continue to next page ${companyPaginationIcon("next")}</button>`
              : ""
          }
        </div>
      `;

      container.querySelectorAll(`[${pageActionAttribute}]`).forEach((button) => {
        button.addEventListener("click", () => {
          const action = button.getAttribute(pageActionAttribute);
          const targetPage =
            action === "first"
              ? 1
              : action === "previous"
                ? Math.max(1, state.page - 1)
                : Math.min(totalPages, state.page + 1);

          requestPage(targetPage);
        });
      });
    }

    function beginLoading() {
      state.isLoading = true;
      state.loadingToken += 1;

      setLoading(true);
      renderPagination(currentPageCount());

      if (!isHeaderVisible()) {
        scrollHeaderIntoView();
      }

      return state.loadingToken;
    }

    function finishLoading() {
      state.isLoading = false;
      setLoading(false);
      renderPagination(currentPageCount());
    }

    function simulateLoad(onComplete) {
      if (state.isLoading) {
        return;
      }

      const token = beginLoading();

      globalScope.setTimeout(() => {
        if (token !== state.loadingToken) {
          return;
        }

        onComplete();
        finishLoading();
      }, 350);
    }

    function loadServerPage(targetPage) {
      if (!currentData || state.isLoading) {
        return false;
      }

      const request = requestRows(targetPage);

      if (!request) {
        return false;
      }

      const token = beginLoading();

      request.then((payload) => {
        if (token !== state.loadingToken) {
          return;
        }

        if (applyTablePayload(currentData, tableKey, rowKey, payload, state)) {
          render(currentData);
        }
      }).finally(() => {
        if (token !== state.loadingToken) {
          return;
        }

        finishLoading();
      });

      return true;
    }

    function requestPage(targetPage) {
      if (!currentData || state.isLoading || targetPage === state.page) {
        return;
      }

      if (loadServerPage(targetPage)) {
        return;
      }

      simulateLoad(() => {
        state.page = targetPage;
        render(currentData);
      });
    }

    function mountSort() {
      if (sortMounted) {
        return;
      }

      sortMounted = true;

      document.querySelectorAll(`[${sortAttribute}]`).forEach((button) => {
        button.addEventListener("click", () => {
          const sortKey = button.getAttribute(sortAttribute) || defaultSortKey;

          if (!currentData || state.isLoading) {
            return;
          }

          if (state.sortKey === sortKey) {
            state.sortDirection = state.sortDirection === "asc" ? "desc" : "asc";
          } else {
            state.sortKey = sortKey;
            state.sortDirection = defaultSortDirections[sortKey] || "desc";
          }

          state.page = 1;
          updateSortButtons();
          if (loadServerPage(1)) {
            return;
          }

          simulateLoad(() => {
            render(currentData);
          });
        });
      });
    }

    return { pageCount, renderPagination, updateSortButtons, mountSort };
  }

  const companyTableController = createTablePaginationController({
    state: companyTableState,
    pageSize: topCompaniesPageSize,
    tableKey: "companies",
    rowKey: "companies",
    scrollSelector: "[data-companies-table-scroll]",
    loadingSelector: "[data-companies-table-loading]",
    paginationSelector: "[data-companies-pagination]",
    pageActionAttribute: "data-companies-page-action",
    sortAttribute: "data-company-sort",
    defaultSortKey: "engagedSeconds",
    defaultSortDirections: companyTableDefaultSortDirections,
    sortedRows: topCompanyRows,
    render: (data) => renderCompaniesTable(data),
    requestRows: (targetPage) => (
      typeof provider.loadCompaniesTable === "function"
        ? provider.loadCompaniesTable({
            page: targetPage,
            page_size: topCompaniesPageSize,
            sort: companyTableState.sortKey,
            direction: companyTableState.sortDirection,
            period: currentData.period || provider.DEFAULT_PERIOD
          })
        : null
    ),
    afterSortButtonsUpdate: () => mountCompaniesTableStickyHeader()
  });

  const atRiskTableController = createTablePaginationController({
    state: atRiskTableState,
    pageSize: atRiskPageSize,
    tableKey: "atRisk",
    rowKey: "atRiskCompanies",
    scrollSelector: "[data-at-risk-table-scroll]",
    loadingSelector: "[data-at-risk-table-loading]",
    paginationSelector: "[data-at-risk-pagination]",
    pageActionAttribute: "data-at-risk-page-action",
    sortAttribute: "data-at-risk-sort",
    defaultSortKey: "riskScore",
    defaultSortDirections: atRiskDefaultSortDirections,
    sortedRows: atRiskTableRows,
    render: (data) => renderAtRiskTable(data),
    requestRows: (targetPage) => (
      typeof provider.loadAtRiskTable === "function"
        ? provider.loadAtRiskTable({
            page: targetPage,
            page_size: atRiskPageSize,
            sort: atRiskTableState.sortKey,
            direction: atRiskTableState.sortDirection,
            period: currentData.period || provider.DEFAULT_PERIOD
          })
        : null
    )
  });

  const newReactivatedTableController = createTablePaginationController({
    state: newReactivatedTableState,
    pageSize: newReactivatedPageSize,
    tableKey: "newReactivated",
    rowKey: "newReactivatedCompanies",
    scrollSelector: "[data-new-reactivated-table-scroll]",
    loadingSelector: "[data-new-reactivated-table-loading]",
    paginationSelector: "[data-new-reactivated-pagination]",
    pageActionAttribute: "data-new-reactivated-page-action",
    sortAttribute: "data-new-reactivated-sort",
    defaultSortKey: "activationStage",
    defaultSortDirections: newReactivatedDefaultSortDirections,
    sortedRows: newReactivatedTableRows,
    render: (data) => renderNewReactivatedTable(data),
    requestRows: (targetPage) => (
      typeof provider.loadNewReactivatedTable === "function"
        ? provider.loadNewReactivatedTable({
            page: targetPage,
            page_size: newReactivatedPageSize,
            sort: newReactivatedTableState.sortKey,
            direction: newReactivatedTableState.sortDirection,
            period: currentData.period || provider.DEFAULT_PERIOD
          })
        : null
    )
  });

  const expansionTableController = createTablePaginationController({
    state: expansionTableState,
    pageSize: expansionPageSize,
    tableKey: "expansion",
    rowKey: "expansionOpportunities",
    scrollSelector: "[data-expansion-table-scroll]",
    loadingSelector: "[data-expansion-table-loading]",
    paginationSelector: "[data-expansion-pagination]",
    pageActionAttribute: "data-expansion-page-action",
    sortAttribute: "data-expansion-sort",
    defaultSortKey: "potentialScore",
    defaultSortDirections: expansionDefaultSortDirections,
    sortedRows: expansionTableRows,
    render: (data) => renderExpansionTable(data),
    requestRows: (targetPage) => (
      typeof provider.loadExpansionTable === "function"
        ? provider.loadExpansionTable({
            page: targetPage,
            page_size: expansionPageSize,
            sort: expansionTableState.sortKey,
            direction: expansionTableState.sortDirection,
            period: currentData.period || provider.DEFAULT_PERIOD
          })
        : null
    )
  });

  function topCompanyPageCount(rows) {
    return companyTableController.pageCount(rows);
  }

  function updateCompanySortButtons() {
    companyTableController.updateSortButtons();
  }

  function renderCompaniesPagination(totalPages) {
    companyTableController.renderPagination(totalPages);
  }

  function mountCompanyTableSort() {
    companyTableController.mountSort();
  }

  function renderCompaniesTable(data) {
    const tbody = document.getElementById("companies-table-body");

    if (!tbody) {
      return;
    }

    const sortedRows = topCompanyRows(data);
    const totalPages = topCompanyPageCount(sortedRows);

    companyTableState.page = Math.min(totalPages, Math.max(1, companyTableState.page));
    updateCompanySortButtons();
    renderCompaniesPagination(totalPages);

    if (!sortedRows.length) {
      tbody.innerHTML = `<tr><td colspan="10" class="px-6 py-10 text-center text-slate-500">No company activity detected for this period.</td></tr>`;
      renderCompaniesPagination(1);
      return;
    }

    const rows = tableRowsForRender(data, "companies", sortedRows, companyTableState, topCompaniesPageSize);
    const maxValues = getCompaniesTableMaxValues(data.companies || rows);
    const changeScaleByMetric = getCompanySplitChangeScaleByMetric(rows, maxValues);
    const areaUsageScaleMax = productAreaUsageScaleMax(sortedRows);

    tbody.innerHTML = rows
      .map((row) => {
        const href = companyDetailHref(row);
        const companyCell = href
          ? `<a class="text-sky-800 hover:text-sky-900" href="${escapeHtml(href)}">${escapeHtml(row.name)}</a>`
          : `<span class="text-slate-800">${escapeHtml(row.name)}</span>`;

        return `
        <tr class="group${href ? " cursor-pointer" : ""} hover:bg-slate-50"${href ? ` data-company-detail-href="${escapeHtml(href)}" tabindex="0"` : ""}>
          <td class="sticky left-0 z-[1] bg-white py-3.5 pl-0 pr-6 align-middle font-medium text-slate-900 group-hover:bg-slate-50">
            ${companyCell}
          </td>
          <td class="py-3.5 pr-6 align-middle">${statusBadge(row.status)}</td>
          ${renderCompanySplitMetricChangeGroup(row, companyTableSplitMetrics[0], changeScaleByMetric.activeUsers, maxValues)}
          <td class="py-3.5 pr-6 align-middle">${userHealthMixCell(row)}</td>
          <td class="py-3.5 pr-6 align-middle tabular-nums font-medium text-slate-900">${formatNumber(row.pagesUsed)}</td>
          ${renderCompanySplitMetricChangeGroup(row, companyTableSplitMetrics[1], changeScaleByMetric.visits, maxValues)}
          ${renderCompanySplitMetricChangeGroup(row, companyTableSplitMetrics[2], changeScaleByMetric.engagedSeconds, maxValues)}
          <td class="py-3.5 pr-6 align-middle tabular-nums font-medium text-slate-900">${formatDurationShort(row.avgEngagedSecondsPerUser)}</td>
          ${renderCompanySplitMetricChangeGroup(row, companyTableSplitMetrics[3], changeScaleByMetric.interactionPct, maxValues)}
          <td class="py-3.5 pr-6 align-middle">${productAreaUsageCell(row, areaUsageScaleMax)}</td>
        </tr>
      `;
      })
      .join("");

    tbody.querySelectorAll("[data-company-detail-href]").forEach((row) => {
      const href = row.getAttribute("data-company-detail-href");

      row.addEventListener("click", (event) => {
        if (!href || event.target.closest("a, button, input, select, textarea, .metric-header-tooltip")) {
          return;
        }

        globalScope.location.href = href;
      });

      row.addEventListener("keydown", (event) => {
        if (!href || (event.key !== "Enter" && event.key !== " ")) {
          return;
        }

        event.preventDefault();
        globalScope.location.href = href;
      });
    });

    syncSplitChangeValueWidths(tbody);
  }

  function renderNewReactivatedTable(data) {
    const tbody = document.getElementById("new-reactivated-table-body");

    if (!tbody) {
      return;
    }

    const allRows = newReactivatedTableRows(data);
    const totalPages = newReactivatedTableController.pageCount(allRows);

    newReactivatedTableState.page = Math.min(totalPages, Math.max(1, newReactivatedTableState.page));
    newReactivatedTableController.updateSortButtons();
    newReactivatedTableController.renderPagination(totalPages);

    if (!allRows.length) {
      tbody.innerHTML = `<tr><td colspan="6" class="px-6 py-10 text-center text-slate-500">No new or reactivated companies in this period.</td></tr>`;
      newReactivatedTableController.renderPagination(1);
      return;
    }

    const rows = tableRowsForRender(data, "newReactivated", allRows, newReactivatedTableState, newReactivatedPageSize);
    const sortedRows = rows;
    const maxMatrixEngaged = Math.max(
      ...rows.flatMap((row) => (row.productAreaAdoption || []).map((cell) => cell.engagedSeconds || 0)),
      1
    );
    const metricMaxValues = {
      activeUsers: Math.max(...rows.map((row) => row.activeUsers || 0), 1),
      engagedSeconds: Math.max(...rows.map((row) => row.engagedSeconds || 0), 1)
    };
    const metrics = {
      activeUsers: { key: "activeUsers", label: "Active users", formatValue: formatNumber },
      engagedSeconds: { key: "engagedSeconds", label: "Engaged", formatValue: formatDurationShort }
    };

    tbody.innerHTML = sortedRows
      .map((row) => `
        <tr class="hover:bg-slate-50">
          <td class="py-3.5 pl-0 pr-6">${cohortCompanyCell(row)}</td>
          <td class="py-3.5 pr-6">${activationBadge(row.activationStage)}</td>
          <td class="py-3.5 pr-6 whitespace-nowrap text-slate-700">${escapeHtml(formatRelativeDays(row.daysSinceStart))}</td>
          ${newReactivatedMetricBarCell(row, metrics.activeUsers, metricMaxValues.activeUsers)}
          ${newReactivatedMetricBarCell(row, metrics.engagedSeconds, metricMaxValues.engagedSeconds)}
          <td class="py-3.5 pr-6">${adoptionMatrixCellGroup(row, maxMatrixEngaged)}</td>
        </tr>
      `)
      .join("");
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

  function layoutLineEndLabels(seriesRows, valueExtent, layout = {}) {
    const valueRange = Math.max(valueExtent.max - valueExtent.min, 1);
    const plotHeight = layout.plotHeight || 296;
    const labelPadding = layout.labelPadding || 8;
    const desiredLabelGap = layout.labelGap || 20;
    const valueToY = (value) => ((valueExtent.max - value) / valueRange) * plotHeight;
    const yToValue = (y) => valueExtent.max - (y / plotHeight) * valueRange;
    const labels = seriesRows
      .map((row, index) => ({
        index,
        idealY: valueToY(getLastNumericValue(row.values)),
        y: valueToY(getLastNumericValue(row.values))
      }))
      .sort((a, b) => a.idealY - b.idealY);
    const maxLabelGap = labels.length > 1 ? (plotHeight - labelPadding * 2) / (labels.length - 1) : desiredLabelGap;
    const labelGap = Math.max(12, Math.min(desiredLabelGap, maxLabelGap));
    const clusterBreakGap = labelGap * 1.8;
    const clusters = [];

    labels.forEach((label, index) => {
      const previous = labels[index - 1];

      if (!previous || label.idealY - previous.idealY > clusterBreakGap) {
        clusters.push([label]);
      } else {
        clusters[clusters.length - 1].push(label);
      }
    });

    clusters.forEach((cluster) => {
      if (cluster.length === 1) {
        cluster[0].y = Math.min(plotHeight - labelPadding, Math.max(labelPadding, cluster[0].idealY));
        return;
      }

      const firstLabelIndex = labels.indexOf(cluster[0]);
      const lastLabelIndex = labels.indexOf(cluster[cluster.length - 1]);
      const previous = labels[firstLabelIndex - 1];
      const next = labels[lastLabelIndex + 1];
      const topBoundary = previous
        ? Math.min(cluster[0].idealY, previous.idealY + labelGap)
        : labelPadding;
      const bottomBoundary = next
        ? Math.max(cluster[cluster.length - 1].idealY, next.idealY - labelGap)
        : plotHeight - labelPadding;
      const hasBoundaryRoom = bottomBoundary - topBoundary >= labelGap * (cluster.length - 1);
      const packedHeight = labelGap * (cluster.length - 1);
      const idealCenter = cluster.reduce((sum, label) => sum + label.idealY, 0) / cluster.length;
      const startBoundary = hasBoundaryRoom ? topBoundary : labelPadding;
      const endBoundary = hasBoundaryRoom ? bottomBoundary : plotHeight - labelPadding;
      const startY = Math.min(endBoundary - packedHeight, Math.max(startBoundary, idealCenter - packedHeight / 2));

      cluster.forEach((label, index) => {
        label.y = startY + index * labelGap;
      });
    });

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

  function createLineEndLabelConnectorSeries(seriesRows, xAxisLabels, valueExtent, options = {}) {
    const labelValuesBySeriesIndex = layoutLineEndLabels(seriesRows, valueExtent, {
      plotHeight: options.plotHeight || 296,
      labelGap: options.labelGap || 20,
      labelPadding: options.labelPadding || 8
    });

    return seriesRows.map((row, index) => {
      const color = productAreaColor(row.name);
      const lastValue = getLastNumericValue(row.values);
      const labelValue = labelValuesBySeriesIndex[index] ?? lastValue;
      const connectorData = Array.from({ length: xAxisLabels.length }, () => null);

      connectorData[Math.max(xAxisLabels.length - 2, 0)] = lastValue;
      connectorData[Math.max(xAxisLabels.length - 1, 0)] = labelValue;

      return {
        name: `${row.name}${lineEndLabelSeriesSuffix}`,
        type: "line",
        animation: false,
        silent: false,
        triggerLineEvent: true,
        cursor: "default",
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
          width: options.labelWidth || 116,
          overflow: "truncate",
          formatter: () => row.name
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
  }

  function currentStraightTrendLineStyle(color) {
    return {
      color,
      type: [6, 4],
      opacity: 0.58,
      width: 2
    };
  }

  function createLineHoverTrendSeries(seriesRows, xAxisLabels, selectedPeriodDays) {
    return seriesRows.map((row) => {
      const color = productAreaColor(row.name);
      const trendValues = buildStraightTrendLine(row.values, selectedPeriodDays);
      const visibleLineStyle = currentStraightTrendLineStyle(color);

      return {
        name: `${row.name}${lineHoverTrendSeriesSuffix}`,
        type: "line",
        animation: false,
        silent: true,
        smooth: false,
        symbol: "none",
        data: trendValues.length
          ? trendValues.concat(null)
          : Array.from({ length: xAxisLabels.length }, () => null),
        tooltip: {
          show: false
        },
        lineStyle: {
          ...visibleLineStyle,
          opacity: 0
        },
        emphasis: {
          lineStyle: visibleLineStyle
        },
        blur: {
          lineStyle: {
            opacity: 0
          }
        },
        z: 4
      };
    });
  }

  function createProductAreaAdoptionOption(points) {
    const areas = Array.from(new Set(points.map((point) => point.productArea)));
    const dates = Array.from(new Set(points.map((point) => point.date)));
    const labelSpacerCategory = "";
    const xAxisLabels = dates.concat(labelSpacerCategory);
    const pointLookup = new Map(points.map((point) => [`${point.productArea}|${point.date}`, point]));
    const valueExtent = { min: 0, max: 100 };
    const seriesRows = areas.map((area) => ({
      name: area,
      values: dates.map((date) => pointLookup.get(`${area}|${date}`)?.adoptionPct || 0)
    }));
    const lineSeries = seriesRows.map((row) => {
      const color = productAreaColor(row.name);

      return {
        name: row.name,
        type: "line",
        cursor: "default",
        triggerLineEvent: true,
        smooth: true,
        showSymbol: false,
        symbol: "circle",
        symbolSize: 5,
        data: row.values.concat(null),
        lineStyle: { color, width: 2.5 },
        emphasis: { focus: "series" },
        z: 5
      };
    });
    const connectorSeries = createLineEndLabelConnectorSeries(seriesRows, xAxisLabels, valueExtent, {
      labelWidth: 116,
      plotHeight: 296
    });
    const trendSeries = createLineHoverTrendSeries(seriesRows, xAxisLabels, dates.length);

    return {
      color: chartTheme.series,
      animation: false,
      tooltip: analyticsTooltips.echarts({
        trigger: "axis",
        confine: true,
        formatter: (params) => {
          const items = (Array.isArray(params) ? params : [params]).filter((item) =>
            !String(item.seriesName || "").endsWith(lineEndLabelSeriesSuffix) &&
            !String(item.seriesName || "").endsWith(lineHoverTrendSeriesSuffix) &&
            item.axisValue !== labelSpacerCategory &&
            item.value !== null &&
            item.value !== undefined
          );
          const date = items[0]?.axisValue || "";

          if (!items.length) {
            return "";
          }

          const rows = items.map((item) => {
            const point = pointLookup.get(`${item.seriesName}|${date}`);

            return {
              label: item.seriesName,
              value: formatPercent(point?.adoptionPct ?? item.value),
              marker: productAreaColor(item.seriesName)
            };
          });

          return analyticsTooltips.render({ title: formatDateShort(date), rows });
        }
      }),
      grid: {
        left: 48,
        right: 136,
        top: 24,
        bottom: 40
      },
      xAxis: {
        type: "category",
        boundaryGap: false,
        data: xAxisLabels,
        axisLine: { lineStyle: { color: chartTheme.colors.axis } },
        axisLabel: {
          color: chartTheme.colors.mutedText,
          formatter: (value) => formatDateShort(value),
          hideOverlap: true
        }
      },
      yAxis: {
        type: "value",
        min: 0,
        max: 100,
        axisTick: { show: false },
        axisLine: { show: true, lineStyle: { color: chartTheme.colors.axis } },
        axisLabel: {
          color: chartTheme.colors.mutedText,
          formatter: "{value}%"
        },
        splitLine: { show: false }
      },
      series: lineSeries.concat(connectorSeries, trendSeries)
    };
  }

  function createAdoptionRampOption(points) {
    const areas = Array.from(new Set(points.map((point) => point.productArea)));
    const days = Array.from(new Set(points.map((point) => point.dayOffset))).sort((a, b) => a - b);
    const labelSpacerCategory = "";
    const xAxisLabels = days.concat(labelSpacerCategory);
    const pointLookup = new Map(points.map((point) => [`${point.productArea}|${point.dayOffset}`, point]));
    const valueExtent = { min: 0, max: 100 };
    const seriesRows = areas.map((area) => ({
      name: area,
      values: days.map((day) => pointLookup.get(`${area}|${day}`)?.adoptionPct || 0)
    }));
    const lineSeries = seriesRows.map((row) => {
      const color = productAreaColor(row.name);

      return {
        name: row.name,
        type: "line",
        cursor: "default",
        triggerLineEvent: true,
        smooth: true,
        showSymbol: false,
        symbol: "circle",
        symbolSize: 5,
        data: row.values.concat(null),
        lineStyle: { color, width: 2.5 },
        emphasis: { focus: "series" },
        z: 5
      };
    });
    const connectorSeries = createLineEndLabelConnectorSeries(seriesRows, xAxisLabels, valueExtent, {
      labelWidth: 116,
      plotHeight: 296
    });
    const trendSeries = createLineHoverTrendSeries(seriesRows, xAxisLabels, days.length);

    return {
      color: chartTheme.series,
      animation: false,
      tooltip: analyticsTooltips.echarts({
        trigger: "axis",
        confine: true,
        formatter: (params) => {
          const items = (Array.isArray(params) ? params : [params]).filter((item) =>
            !String(item.seriesName || "").endsWith(lineEndLabelSeriesSuffix) &&
            !String(item.seriesName || "").endsWith(lineHoverTrendSeriesSuffix) &&
            item.axisValue !== labelSpacerCategory &&
            item.value !== null &&
            item.value !== undefined
          );
          const day = Number(items[0]?.axisValue) || 0;

          if (!items.length) {
            return "";
          }

          const rows = items.map((item) => {
            const point = pointLookup.get(`${item.seriesName}|${day}`);

            return {
              label: item.seriesName,
              value: formatPercent(point?.adoptionPct ?? item.value),
              marker: productAreaColor(item.seriesName)
            };
          });

          return analyticsTooltips.render({ title: `Day ${day}`, rows });
        }
      }),
      grid: {
        left: 48,
        right: 136,
        top: 24,
        bottom: 40
      },
      xAxis: {
        type: "category",
        boundaryGap: false,
        data: xAxisLabels,
        axisLine: { lineStyle: { color: chartTheme.colors.axis } },
        axisLabel: {
          color: chartTheme.colors.mutedText,
          formatter: (value) => value === labelSpacerCategory ? "" : `${value}d`
        }
      },
      yAxis: {
        type: "value",
        min: 0,
        max: 100,
        axisTick: { show: false },
        axisLine: { show: true, lineStyle: { color: chartTheme.colors.axis } },
        axisLabel: {
          color: chartTheme.colors.mutedText,
          formatter: "{value}%"
        },
        splitLine: { show: false }
      },
      series: lineSeries.concat(connectorSeries, trendSeries)
    };
  }

  function mountLineHoverTrendChart(element, option, lineSeriesCount) {
    const chart = mountChart(element, option);

    return bindLineTrendHover(chart, lineSeriesCount, element);
  }

  function renderProductAreaAdoptionCharts(data) {
    const adoptionPoints = data.productAreaAdoption || [];
    const adoptionSeriesCount = new Set(adoptionPoints.map((point) => point.productArea)).size;

    mountLineHoverTrendChart(
      document.getElementById("product-area-adoption-chart"),
      createProductAreaAdoptionOption(adoptionPoints),
      adoptionSeriesCount
    );

    const rampElement = document.getElementById("new-company-adoption-ramp-chart");

    if (!data.newCompanyAdoptionRamp?.length) {
      chartUnavailable(rampElement, "No new or reactivated companies in this period.");
      return;
    }

    const rampSeriesCount = new Set(data.newCompanyAdoptionRamp.map((point) => point.productArea)).size;

    mountLineHoverTrendChart(
      rampElement,
      createAdoptionRampOption(data.newCompanyAdoptionRamp),
      rampSeriesCount
    );
  }

  function median(values) {
    const sorted = values.map((value) => Number(value) || 0).sort((a, b) => a - b);
    const middle = Math.floor(sorted.length / 2);

    if (!sorted.length) {
      return 0;
    }

    return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
  }

  function scatterStatusGroup(point) {
    const status = normalizeCompanyStatus(point.status);

    if (status === "at_risk") {
      return "at_risk";
    }

    if (status === "new" || status === "reactivated" || point.isNew || point.isReactivated) {
      return "new_reactivated";
    }

    return "regular";
  }

  function scatterHasCurrentActivity(point) {
    return scatterActiveUsers(point) > 0 || Number(point.visits) > 0 || Number(point.engagedSeconds) > 0;
  }

  function scatterCompanyId(point) {
    return String(point.companyId || point.id || point.companyName || point.name || "");
  }

  function scatterChangeMagnitude(point) {
    return Math.max(
      Math.abs(Number(point.activeUsersDeltaPct) || 0),
      Math.abs(Number(point.visitsDeltaPct) || 0),
      Math.abs(Number(point.engagedDeltaPct) || 0),
      Math.abs(Number(point.interactionDeltaPp) || 0)
    );
  }

  function scatterActiveUsers(point) {
    return Number(point.averageActiveUsers ?? point.avgActiveUsers ?? point.activeUsers) || 0;
  }

  function selectRelevantScatterPoints(points, limit) {
    const visibleLimit = Math.max(1, Number(limit) || 500);
    const rows = Array.isArray(points) ? points.filter(scatterHasCurrentActivity) : [];

    if (rows.length <= visibleLimit) {
      return rows;
    }

    const scores = new Map();
    const rowCount = rows.length;
    const addScore = (point, score) => {
      const id = scatterCompanyId(point);
      scores.set(id, (scores.get(id) || 0) + score);
    };
    const addRankedScore = (valueFn, weight) => {
      rows
        .slice()
        .sort((a, b) => valueFn(b) - valueFn(a))
        .forEach((point, index) => {
          addScore(point, weight * ((rowCount - index) / rowCount));
        });
    };

    rows.forEach((point) => {
      const group = scatterStatusGroup(point);

      if (group === "at_risk") {
        addScore(point, 10000000);
      } else if (group === "new_reactivated") {
        addScore(point, 9000000);
      }
    });

    const addTopOutlierScore = (valueFn, weight) => {
      const topRows = rows
        .slice()
        .sort((a, b) => valueFn(b) - valueFn(a))
        .filter((point) => valueFn(point) > 0)
        .slice(0, Math.min(50, Math.max(5, Math.floor(visibleLimit / 10))));

      topRows.forEach((point, index) => {
        addScore(point, weight * ((topRows.length - index) / topRows.length));
      });
    };

    addTopOutlierScore((point) => Number(point.engagedSeconds) || 0, 4000000);
    addTopOutlierScore(scatterActiveUsers, 3200000);
    addTopOutlierScore((point) => Number(point.avgEngagedSecondsPerUser) || 0, 2400000);
    addTopOutlierScore(scatterChangeMagnitude, 1600000);

    addRankedScore((point) => Number(point.engagedSeconds) || 0, 420);
    addRankedScore(scatterActiveUsers, 280);
    addRankedScore((point) => Number(point.avgEngagedSecondsPerUser) || 0, 180);
    addRankedScore(scatterChangeMagnitude, 140);

    return rows
      .slice()
      .sort((a, b) => (scores.get(scatterCompanyId(b)) || 0) - (scores.get(scatterCompanyId(a)) || 0) || String(a.companyName || a.name || "").localeCompare(String(b.companyName || b.name || "")))
      .slice(0, visibleLimit);
  }

  function pointProductAreaNames(point) {
    const names = new Set();

    (point.productAreas || []).forEach((area) => names.add(normalizeProductAreaName(area)));
    (point.productAreaDistribution || []).forEach((area) => names.add(normalizeProductAreaName(area.productArea || area.product_area_name || area.name)));
    (point.productAreaAdoption || [])
      .filter((cell) => cell.used)
      .forEach((cell) => names.add(normalizeProductAreaName(cell.productArea)));

    return names;
  }

  function hasActiveScatterFilters() {
    return scatterFilterState.status !== "all" ||
      scatterFilterState.productArea !== "all" ||
      Number(scatterFilterState.minActiveUsers || 0) > 0 ||
      scatterFilterState.search.trim().length > 0;
  }

  function scatterPointMatchesFilters(point) {
    if (scatterFilterState.status !== "all" && scatterStatusGroup(point) !== scatterFilterState.status) {
      return false;
    }

    if (scatterFilterState.productArea !== "all" && !pointProductAreaNames(point).has(scatterFilterState.productArea)) {
      return false;
    }

    const minActiveUsers = Math.max(0, Number(scatterFilterState.minActiveUsers) || 0);
    if (minActiveUsers > 0 && scatterActiveUsers(point) < minActiveUsers) {
      return false;
    }

    const search = scatterFilterState.search.trim().toLowerCase();
    if (search) {
      const searchable = `${point.companyName || point.name || ""} ${point.domain || ""}`.toLowerCase();
      if (!searchable.includes(search)) {
        return false;
      }
    }

    return true;
  }

  function getScatterSelection(data) {
    const meta = data.scatterMeta || {};
    const visibleLimit = Number(meta.visibleLimit) || 500;
    const source = (data.scatter || []).filter((point) => normalizeCompanyStatus(point.status) !== "dormant" || scatterHasCurrentActivity(point));
    const filtered = source.filter(scatterPointMatchesFilters);
    const selected = selectRelevantScatterPoints(filtered, visibleLimit);
    const totalActive = Math.max(Number(meta.totalActiveCompanies) || 0, source.length);
    const filtersActive = hasActiveScatterFilters();

    return {
      points: selected,
      totalActive,
      matchingCount: filtered.length,
      visibleLimit,
      filtersActive,
      isLimited: filtered.length > selected.length || (!filtersActive && totalActive > selected.length)
    };
  }

  function scatterFilterElements() {
    return {
      root: document.getElementById("company-engagement-scatter-filters"),
      status: document.getElementById("scatter-status-filter"),
      productArea: document.getElementById("scatter-product-area-filter"),
      minActiveUsers: document.getElementById("scatter-min-active-users"),
      search: document.getElementById("scatter-company-search"),
      note: document.getElementById("company-engagement-scatter-note")
    };
  }

  function renderScatterProductAreaOptions(data) {
    const { productArea } = scatterFilterElements();

    if (!productArea) {
      return;
    }

    const previousValue = scatterFilterState.productArea;
    const areaNames = (data.productAreaOptions || []).map((area) => normalizeProductAreaName(area)).filter(Boolean);
    const uniqueAreas = Array.from(new Set(areaNames));

    productArea.innerHTML = [
      `<option value="all">All product areas</option>`,
      ...uniqueAreas.map((area) => `<option value="${escapeHtml(area)}">${escapeHtml(area)}</option>`)
    ].join("");

    scatterFilterState.productArea = uniqueAreas.includes(previousValue) ? previousValue : "all";
    productArea.value = scatterFilterState.productArea;
  }

  function mountScatterFilters(data) {
    const elements = scatterFilterElements();

    if (!elements.root) {
      return;
    }

    renderScatterProductAreaOptions(data);

    if (elements.status) {
      elements.status.value = scatterFilterState.status;
    }
    if (elements.minActiveUsers) {
      elements.minActiveUsers.value = scatterFilterState.minActiveUsers;
    }
    if (elements.search) {
      elements.search.value = scatterFilterState.search;
    }

    if (scatterFiltersMounted) {
      return;
    }

    scatterFiltersMounted = true;

    elements.status?.addEventListener("change", () => {
      scatterFilterState.status = elements.status.value || "all";
      renderScatter(currentData);
    });

    elements.productArea?.addEventListener("change", () => {
      scatterFilterState.productArea = elements.productArea.value || "all";
      renderScatter(currentData);
    });

    elements.minActiveUsers?.addEventListener("input", () => {
      scatterFilterState.minActiveUsers = elements.minActiveUsers.value || "";
      renderScatter(currentData);
    });

    elements.search?.addEventListener("input", () => {
      scatterFilterState.search = elements.search.value || "";
      renderScatter(currentData);
    });
  }

  function renderScatterLimitNote(selection) {
    const note = scatterFilterElements().note;

    if (!note) {
      return;
    }

    if (!selection.isLimited) {
      note.hidden = true;
      note.textContent = "";
      return;
    }

    note.hidden = false;
    if (selection.filtersActive) {
      note.textContent = `Showing ${formatNumber(selection.points.length)} most relevant matching companies out of ${formatNumber(selection.matchingCount)} matches.`;
      return;
    }

    note.textContent = `Showing ${formatNumber(selection.points.length)} most relevant companies out of ${formatNumber(selection.totalActive)}.`;
  }

  function createCompanyEngagementScatterSpec(points, config) {
    const values = points
      .filter((point) => {
        const hasCurrentActivity = scatterActiveUsers(point) > 0 || Number(point.visits) > 0 || Number(point.engagedSeconds) > 0;

        return normalizeCompanyStatus(point.status) !== "dormant" || hasCurrentActivity;
      })
      .map((point) => {
        const status = normalizeCompanyStatus(point.status);
        const isNewOrReactivated = status === "new" || status === "reactivated" || point.isNew || point.isReactivated;
        const isAtRisk = status === "at_risk";
        const activeUsers = scatterActiveUsers(point);

        return {
          ...point,
          scatterActiveUsers: activeUsers,
          scatterActiveUsersLabel: formatAverageUsers(activeUsers),
          statusLabel: getCompanyStatusMeta(status).label || point.status,
          scatterState: isAtRisk ? "At risk" : isNewOrReactivated ? "New / reactivated" : "Regular",
          avgEngagedLabel: formatDurationShort(point.avgEngagedSecondsPerUser),
          engagedLabel: formatDurationShort(point.engagedSeconds),
          visitsLabel: formatNumber(point.visits),
          productAreasLabel: `${formatNumber(point.productAreasUsed)} areas`
        };
      });

    const xMedian = median(values.map((point) => point.scatterActiveUsers));
    const yMedian = median(values.map((point) => point.avgEngagedSecondsPerUser));
    const xMax = Math.max(...values.map((point) => point.scatterActiveUsers), 1);
    const yMax = Math.max(...values.map((point) => point.avgEngagedSecondsPerUser), 60);
    const xDomainMax = compactAxisMax(xMax, { headroom: 0.1, minPadding: 1 });
    const yDomainMax = compactAxisMax(yMax, { headroom: 0.1, minPadding: 30 });
    const scatterStateLabels = ["Regular", "New / reactivated", "At risk"];
    const scatterStateColors = [
      tailwindColor("slate-400"),
      tailwindColor(getCompanyStatusMeta("reactivated").color),
      tailwindColor(getCompanyStatusMeta("at_risk").color)
    ];

    return {
      $schema: "https://vega.github.io/schema/vega/v5.json",
      width: config.width,
      height: 410,
      padding: { top: 32, right: 72, bottom: 52, left: 54 },
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
          titleFontWeight: 500,
          titlePadding: 14
        }
      },
      signals: [
        { name: "xMedian", value: xMedian },
        { name: "yMedian", value: yMedian }
      ],
      data: [
        { name: "points", values }
      ],
      scales: [
        { name: "xScale", type: "linear", domain: [0, xDomainMax], nice: false, range: "width" },
        { name: "yScale", type: "linear", domain: [0, yDomainMax], nice: false, range: "height" },
        { name: "colorScale", type: "ordinal", domain: scatterStateLabels, range: scatterStateColors }
      ],
      axes: [
        {
          orient: "bottom",
          scale: "xScale",
          title: "Avg active users",
          grid: false,
          tickCount: 6,
          labelFlush: true,
          labelFlushOffset: 4
        },
        {
          orient: "left",
          scale: "yScale",
          title: "Avg engaged time / user",
          grid: false,
          tickCount: 6,
          titleAngle: 0,
          titleAnchor: "end",
          titleAlign: "left",
          titleX: -58,
          titleY: -16,
          labelExpr: "datum.value >= 3600 ? floor(datum.value / 3600) + 'h' : floor(datum.value / 60) + 'm'"
        }
      ],
      legends: [
        {
          fill: "colorScale",
          orient: "top-right",
          direction: "horizontal",
          columns: scatterStateLabels.length,
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
        quadrantText("Power accounts", xDomainMax * 0.76, yDomainMax * 0.92, "end"),
        quadrantText("Broad but shallow", xDomainMax * 0.76, yDomainMax * 0.12, "end"),
        quadrantText("Champion-led", xDomainMax * 0.08, yDomainMax * 0.92, "start"),
        quadrantText("Weak adoption", xDomainMax * 0.08, yDomainMax * 0.12, "start"),
        {
          name: "companyPoints",
          type: "symbol",
          from: { data: "points" },
          encode: {
            enter: {
              x: { scale: "xScale", field: "scatterActiveUsers" },
              y: { scale: "yScale", field: "avgEngagedSecondsPerUser" },
              shape: { value: "circle" },
              tooltip: {
                signal:
                  "{'title': datum.companyName, 'Avg active users': datum.scatterActiveUsersLabel, 'Avg engaged time / user': datum.avgEngagedLabel, 'Total engaged time': datum.engagedLabel, 'Visits': datum.visitsLabel, 'Status': datum.statusLabel, 'Product areas used': datum.productAreasLabel, 'Last seen': datum.lastSeen}"
              }
            },
            update: {
              cursor: { value: "default" },
              fill: { scale: "colorScale", field: "scatterState" },
              opacity: { value: 0.86 },
              size: { value: 100 },
              stroke: { value: chartTheme.colors.white },
              strokeWidth: { value: 1.4 },
              zindex: { value: 0 }
            },
            hover: {
              opacity: { value: 1 },
              size: { value: 150 },
              strokeWidth: { value: 1.4 },
              zindex: { value: 1 }
            }
          }
        },
        {
          type: "text",
          interactive: false,
          from: { data: "companyPoints" },
          encode: {
            enter: {
              text: { field: "datum.companyName" },
              fill: { value: chartTheme.colors.labelText },
              font: { value: "Inter, ui-sans-serif, system-ui, sans-serif" },
              fontSize: { value: 12 },
              fontWeight: { value: 400 },
              opacity: { value: 1 },
              limit: { value: 120 }
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

  function quadrantText(text, xValue, yValue, align) {
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

  function mountCompanyEngagementScatter(element, points) {
    if (!element) {
      return;
    }

    disposeVega(element);

    if (!globalScope.vegaEmbed) {
      chartUnavailable(element, "Vega is unavailable.");
      return;
    }

    const render = () => {
      const width = Math.max(640, Math.round(element.clientWidth - 126));
      const token = `${Date.now()}-${Math.random()}`;
      element.__hymetryVegaRenderToken = token;

      disposeVega(element);

      globalScope.vegaEmbed(element, createCompanyEngagementScatterSpec(points, { width }), {
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

  function renderScatter(data) {
    if (!data) {
      return;
    }

    mountScatterFilters(data);

    const element = document.getElementById("company-engagement-scatter");
    const selection = getScatterSelection(data);

    renderScatterLimitNote(selection);

    if (!selection.points.length) {
      chartUnavailable(element, "No companies match these filters.");
      return;
    }

    mountCompanyEngagementScatter(element, selection.points);
  }

  function renderAtRiskTable(data) {
    const tbody = document.getElementById("at-risk-table-body");

    if (!tbody) {
      return;
    }

    const sortedRows = atRiskTableRows(data);
    const totalPages = atRiskTableController.pageCount(sortedRows);

    atRiskTableState.page = Math.min(totalPages, Math.max(1, atRiskTableState.page));
    atRiskTableController.updateSortButtons();
    atRiskTableController.renderPagination(totalPages);

    if (!sortedRows.length) {
      tbody.innerHTML = `<tr><td colspan="6" class="px-6 py-10 text-center text-slate-500">No at-risk companies detected.</td></tr>`;
      atRiskTableController.renderPagination(1);
      return;
    }

    const rows = tableRowsForRender(data, "atRisk", sortedRows, atRiskTableState, atRiskPageSize);
    const maxValues = {
      activeUsers: Math.max(...rows.map((row) => row.activeUsers || 0), 1),
      visits: 1,
      engagedSeconds: Math.max(...rows.map((row) => row.engagedSeconds || 0), 1)
    };
    const changeScaleByMetric = getCompanySplitChangeScaleByMetric(rows, maxValues);
    const maxMatrixEngaged = Math.max(
      ...rows.flatMap((row) => (row.productAreaAdoption || []).map((cell) => cell.engagedSeconds || 0)),
      1
    );

    tbody.innerHTML = rows
      .map((row) => `
        <tr class="hover:bg-slate-50">
          <td class="py-3.5 pl-0 pr-6">${cohortCompanyCell(row)}</td>
          <td class="py-3.5 pr-6">${riskBadge(row.riskReason)}</td>
          ${renderCompanySplitMetricChangeGroup(row, companyTableSplitMetrics[0], changeScaleByMetric.activeUsers, maxValues)}
          ${renderCompanySplitMetricChangeGroup(row, companyTableSplitMetrics[2], changeScaleByMetric.engagedSeconds, maxValues)}
          <td class="py-3.5 pr-6">${adoptionMatrixCellGroup(row, maxMatrixEngaged)}</td>
          <td class="py-3.5 text-slate-700">${escapeHtml(row.suggestedAction)}</td>
        </tr>
      `)
      .join("");

    syncSplitChangeValueWidths(tbody);
  }

  function renderExpansionTable(data) {
    const tbody = document.getElementById("expansion-table-body");

    if (!tbody) {
      return;
    }

    const allRows = expansionTableRows(data);
    const totalPages = expansionTableController.pageCount(allRows);

    expansionTableState.page = Math.min(totalPages, Math.max(1, expansionTableState.page));
    expansionTableController.updateSortButtons();
    expansionTableController.renderPagination(totalPages);

    if (!allRows.length) {
      tbody.innerHTML = `<tr><td colspan="8" class="px-6 py-10 text-center text-slate-500">No expansion opportunities detected.</td></tr>`;
      expansionTableController.renderPagination(1);
      return;
    }

    const rows = tableRowsForRender(data, "expansion", allRows, expansionTableState, expansionPageSize);
    const maxMatrixEngaged = Math.max(
      ...rows.flatMap((row) => (row.productAreaAdoption || []).map((cell) => cell.engagedSeconds || 0)),
      1
    );

    tbody.innerHTML = rows
      .map((row) => `
        <tr class="hover:bg-slate-50">
          <td class="py-3.5 pl-0 pr-6">${cohortCompanyCell(row)}</td>
          <td class="py-3.5 pr-6">${expansionPriorityBadge(row.expansionPriority)}</td>
          <td class="py-3.5 pr-6 text-slate-700">${escapeHtml(row.reason)}</td>
          <td class="py-3.5 pr-6 tabular-nums text-slate-700">${formatNumber(row.activeUsers)}</td>
          <td class="py-3.5 pr-6 tabular-nums text-slate-700">${formatDurationShort(row.avgEngagedSecondsPerUser)}</td>
          <td class="py-3.5 pr-6 tabular-nums text-slate-700">${formatPercent(row.interactionPct)}</td>
          <td class="py-3.5 pr-6">${adoptionMatrixCellGroup(row, maxMatrixEngaged)}</td>
          <td class="py-3.5 text-slate-700">${escapeHtml(row.suggestedAction)}</td>
        </tr>
      `)
      .join("");
  }

  function companySearchElements() {
    return {
      root: document.getElementById("company-search"),
      input: document.getElementById("company-search-input"),
      listbox: document.getElementById("company-search-results")
    };
  }

  function normalizeCompanySearchValue(value) {
    return String(value ?? "").trim().toLowerCase();
  }

  function normalizeCompanySearchCompany(company) {
    const id = String(company?.id || company?.companyId || "").trim();
    const name = company?.name || company?.companyName || id;

    return {
      ...(company || {}),
      id,
      companyId: id,
      name,
      companyName: company?.companyName || name,
      domain: company?.domain || "",
      activeUsers: Number(company?.activeUsers || company?.active_users || 0),
      productAreasUsed: Number(company?.productAreasUsed || company?.product_areas_used || 0),
      lastSeen: company?.lastSeen || "",
      lastSeenDate: company?.lastSeenDate || "",
      lastSeenDays: Number(company?.lastSeenDays || 0)
    };
  }

  function companySearchUsesRemote() {
    return typeof provider.searchCompanies === "function" && Boolean(document.body?.dataset.companyOptionsUrl);
  }

  function readRecentCompanyEntries() {
    try {
      const value = globalScope.localStorage?.getItem(companySearchRecentStorageKey);
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

  function readRecentCompanies() {
    const companies = currentData?.companies || [];
    const companiesById = new Map(companies.map((company) => [company.id, company]));

    return readRecentCompanyEntries()
      .map((company) => {
        if (typeof company === "string") {
          return companiesById.get(company) || null;
        }

        const normalized = normalizeCompanySearchCompany(company);
        return companiesById.get(normalized.id) || normalized;
      })
      .filter((company) => company?.id);
  }

  function writeRecentCompanies(companies) {
    try {
      globalScope.localStorage?.setItem(
        companySearchRecentStorageKey,
        JSON.stringify(companies
          .map(normalizeCompanySearchCompany)
          .filter((company) => company.id)
          .slice(0, 8)
          .map((company) => ({
            id: company.id,
            name: company.name,
            domain: company.domain
          })))
      );
    } catch {
      // localStorage may be unavailable in private or embedded browsing contexts.
    }
  }

  function rememberRecentCompany(company) {
    const normalized = normalizeCompanySearchCompany(company);

    if (!normalized.id) {
      return;
    }

    const companies = readRecentCompanies();
    writeRecentCompanies([normalized, ...companies.filter((item) => item.id !== normalized.id)]);
  }

  function companyDetailHref(company) {
    const detailBaseUrl = document.body?.dataset.companyDetailBaseUrl || "";
    const companyId = String(company?.id || company?.companyId || company?.company_id || "").trim();

    if (!companyId) {
      return "";
    }
    if (detailBaseUrl) {
      const companyUrl = new URL(detailBaseUrl, globalScope.location.origin);
      companyUrl.pathname = companyUrl.pathname.replace(/detail(?=\/|$)/, encodeURIComponent(companyId));
      companyUrl.searchParams.delete("company_id");
      companyUrl.searchParams.set("period", currentData?.period || getRequestedPeriod());
      return `${companyUrl.pathname}${companyUrl.search}`;
    }

    return `detail.html?company_id=${encodeURIComponent(companyId)}&period=${encodeURIComponent(currentData?.period || getRequestedPeriod())}`;
  }

  function companySearchMetadata(company) {
    const areaCount = provider.productAreas?.length || currentData?.productAreas?.length || 0;
    const metadata = [
      `${formatNumber(company.activeUsers)} users`,
      areaCount ? `${formatNumber(company.productAreasUsed)}/${areaCount} area adoption` : "",
      company.lastSeen ? `last active ${company.lastSeen}` : ""
    ].filter(Boolean);

    return metadata.join(" \u00b7 ");
  }

  function dedupeCompanySearchResults(companies) {
    const seen = new Set();

    return companies.filter((company) => {
      const domain = normalizeCompanySearchValue(company?.domain);
      const name = normalizeCompanySearchValue(company?.name || company?.companyName);
      const key = domain ? `domain:${domain}` : `name:${name}`;

      if (!name || seen.has(key)) {
        return false;
      }

      seen.add(key);
      return true;
    });
  }

  function getInitialCompanySearchResults() {
    const companies = currentData?.companies || [];
    const companiesById = new Map(companies.map((company) => [company.id, company]));
    const recentCompanyIds = readRecentCompanyIds();
    const recentCompanies = readRecentCompanies()
      .map((company) => companiesById.get(company.id) || company)
      .filter(Boolean);
    const fallbackCompanies = companies
      .slice()
      .sort((a, b) => a.name.localeCompare(b.name))
      .filter((company) => !recentCompanyIds.includes(company.id));

    return dedupeCompanySearchResults([...recentCompanies, ...fallbackCompanies]).slice(0, 8);
  }

  function getCompanySearchMatches(query) {
    const normalizedQuery = normalizeCompanySearchValue(query);

    if (companySearchUsesRemote() && !normalizedQuery) {
      const recentCompanies = dedupeCompanySearchResults(readRecentCompanies());
      return (recentCompanies.length
        ? recentCompanies
        : (companySearchState.remoteQuery === normalizedQuery
          ? dedupeCompanySearchResults(companySearchState.remoteResults)
          : [])
      ).slice(0, 8);
    }

    if (companySearchUsesRemote()) {
      return companySearchState.remoteQuery === normalizedQuery
        ? dedupeCompanySearchResults(companySearchState.remoteResults).slice(0, 8)
        : [];
    }

    if (normalizedQuery.length < 1) {
      return getInitialCompanySearchResults();
    }

    return dedupeCompanySearchResults((currentData?.companies || [])
      .filter((company) => {
        const searchableText = `${company.name || ""} ${company.domain || ""}`.toLowerCase();

        return searchableText.includes(normalizedQuery);
      }))
      .slice(0, 8);
  }

  function closeCompanySearchDropdown() {
    const { input, listbox } = companySearchElements();

    if (companySearchDebounceId) {
      globalScope.clearTimeout(companySearchDebounceId);
      companySearchDebounceId = 0;
    }

    companySearchState.isOpen = false;
    companySearchState.isLoading = false;
    companySearchState.activeIndex = -1;
    companySearchState.requestToken += 1;

    if (input) {
      input.setAttribute("aria-expanded", "false");
      input.removeAttribute("aria-activedescendant");
    }

    if (listbox) {
      listbox.hidden = true;
      listbox.innerHTML = "";
    }
  }

  function setCompanySearchActiveIndex(nextIndex) {
    const { input, listbox } = companySearchElements();

    if (!listbox || !companySearchState.results.length) {
      companySearchState.activeIndex = -1;
      input?.removeAttribute("aria-activedescendant");
      return;
    }

    const resultCount = companySearchState.results.length;
    companySearchState.activeIndex = (nextIndex + resultCount) % resultCount;

    listbox.querySelectorAll("[data-company-search-index]").forEach((option) => {
      const index = Number(option.getAttribute("data-company-search-index"));
      const isActive = index === companySearchState.activeIndex;

      option.dataset.active = String(isActive);
      option.setAttribute("aria-selected", String(isActive));
    });

    const activeOptionId = `company-search-option-${companySearchState.activeIndex}`;
    input?.setAttribute("aria-activedescendant", activeOptionId);
    document.getElementById(activeOptionId)?.scrollIntoView({ block: "nearest" });
  }

  function openCompanyDetail(company) {
    if (!company) {
      return;
    }

    rememberRecentCompany(company);
    globalScope.location.href = companyDetailHref(company);
  }

  function renderCompanySearchDropdown() {
    const { input, listbox } = companySearchElements();

    if (!input || !listbox) {
      return;
    }

    companySearchState.isOpen = true;
    input.setAttribute("aria-expanded", "true");
    listbox.hidden = false;

    if (!companySearchState.results.length) {
      companySearchState.activeIndex = -1;
      input.removeAttribute("aria-activedescendant");
      listbox.innerHTML = `<div class="company-search__empty" role="status">${companySearchState.isLoading ? "Loading companies..." : "No companies found"}</div>`;
      return;
    }

    listbox.innerHTML = companySearchState.results
      .map((company, index) => {
        const href = companyDetailHref(company);

        return `
        <a
          id="company-search-option-${index}"
          href="${escapeHtml(href)}"
          class="company-search__option"
          role="option"
          data-company-search-index="${index}"
          data-active="${String(index === companySearchState.activeIndex)}"
          aria-selected="${String(index === companySearchState.activeIndex)}">
          <span class="min-w-0">
            <span class="company-search__name">${escapeHtml(company.name)}</span>
            <span class="company-search__meta">${escapeHtml(companySearchMetadata(company))}</span>
          </span>
          <span class="company-search__open">Open \u2192</span>
        </a>
      `;
      })
      .join("");

    setCompanySearchActiveIndex(companySearchState.activeIndex);

    listbox.querySelectorAll("[data-company-search-index]").forEach((option) => {
      const index = Number(option.getAttribute("data-company-search-index"));

      option.addEventListener("mouseenter", () => {
        setCompanySearchActiveIndex(index);
      });

      option.addEventListener("click", () => {
        rememberRecentCompany(companySearchState.results[index]);
      });

      option.addEventListener("auxclick", (event) => {
        if (event.button === 1) {
          rememberRecentCompany(companySearchState.results[index]);
        }
      });
    });
  }

  function updateCompanySearch(query) {
    if (companySearchDebounceId) {
      globalScope.clearTimeout(companySearchDebounceId);
      companySearchDebounceId = 0;
    }

    const normalizedQuery = normalizeCompanySearchValue(query);
    const usesRemote = companySearchUsesRemote();
    const shouldLoadFallback = usesRemote && !normalizedQuery && !readRecentCompanies().length;
    const shouldFetchRemote = usesRemote && (Boolean(normalizedQuery) || shouldLoadFallback) && companySearchState.remoteQuery !== normalizedQuery;
    companySearchState.query = query;

    if (shouldFetchRemote) {
      companySearchState.remoteResults = [];
    }

    companySearchState.results = getCompanySearchMatches(query);
    companySearchState.activeIndex = companySearchState.results.length ? 0 : -1;
    companySearchState.isLoading = shouldFetchRemote;
    renderCompanySearchDropdown();

    if (!shouldFetchRemote) {
      return;
    }

    const requestToken = companySearchState.requestToken + 1;
    companySearchState.requestToken = requestToken;

    provider.searchCompanies(query, {
      period: currentData?.period || getRequestedPeriod(),
      limit: 20,
      alphabetical: shouldLoadFallback
    })
      .then((remoteCompanies) => {
        if (
          requestToken !== companySearchState.requestToken ||
          !companySearchState.isOpen ||
          normalizeCompanySearchValue(companySearchState.query) !== normalizedQuery
        ) {
          return;
        }

        companySearchState.remoteQuery = normalizedQuery;
        companySearchState.remoteResults = Array.isArray(remoteCompanies)
          ? remoteCompanies.map(normalizeCompanySearchCompany).filter((company) => company.id)
          : [];
        companySearchState.isLoading = false;
        companySearchState.results = getCompanySearchMatches(query);
        companySearchState.activeIndex = companySearchState.results.length ? 0 : -1;
        renderCompanySearchDropdown();
      })
      .catch(() => {
        if (requestToken !== companySearchState.requestToken) {
          return;
        }

        companySearchState.remoteQuery = normalizedQuery;
        companySearchState.remoteResults = [];
        companySearchState.isLoading = false;
        companySearchState.results = [];
        companySearchState.activeIndex = -1;
        renderCompanySearchDropdown();
      });
  }

  function scheduleCompanySearchUpdate(query) {
    companySearchState.query = query;

    if (companySearchDebounceId) {
      globalScope.clearTimeout(companySearchDebounceId);
    }

    companySearchDebounceId = globalScope.setTimeout(() => {
      updateCompanySearch(query);
    }, companySearchDebounceMs);
  }

  function refreshCompanySearchResults() {
    const { input } = companySearchElements();

    if (!companySearchMounted || !input) {
      return;
    }

    if (document.activeElement === input || companySearchState.isOpen) {
      updateCompanySearch(input.value);
    }
  }

  function mountCompanySearch() {
    const { root, input } = companySearchElements();

    if (!root || !input || companySearchMounted) {
      return;
    }

    companySearchMounted = true;

    root.addEventListener("overview-quick-jumper:close", closeCompanySearchDropdown);

    input.addEventListener("input", () => {
      scheduleCompanySearchUpdate(input.value);
    });

    input.addEventListener("focus", () => {
      updateCompanySearch(input.value);
    });

    input.addEventListener("click", () => {
      updateCompanySearch(input.value);
    });

    input.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        closeCompanySearchDropdown();
        return;
      }

      if ((event.key === "ArrowDown" || event.key === "ArrowUp" || event.key === "Enter") && companySearchDebounceId) {
        updateCompanySearch(input.value);
      }

      if ((event.key === "ArrowDown" || event.key === "ArrowUp") && !companySearchState.isOpen) {
        event.preventDefault();
        updateCompanySearch(input.value);
        return;
      }

      if (!companySearchState.isOpen || !companySearchState.results.length) {
        return;
      }

      if (event.key === "ArrowDown") {
        event.preventDefault();
        setCompanySearchActiveIndex(companySearchState.activeIndex + 1);
        return;
      }

      if (event.key === "ArrowUp") {
        event.preventDefault();
        setCompanySearchActiveIndex(companySearchState.activeIndex - 1);
        return;
      }

      if (event.key === "Enter" && companySearchState.activeIndex >= 0) {
        event.preventDefault();
        openCompanyDetail(companySearchState.results[companySearchState.activeIndex]);
      }
    });

    document.addEventListener("pointerdown", (event) => {
      if (!root.contains(event.target)) {
        closeCompanySearchDropdown();
      }
    });
  }

  function renderAll(data) {
    currentData = data;
    syncProductAreaPalette(data);
    periodChangeTooltipId = 0;
    productAreaMixTooltipId = 0;
    userHealthMixTooltipId = 0;
    adoptionCellTooltipId = 0;
    activationStageTooltipId = 0;
    suggestedStepTooltipId = 0;

    mountCompanySearch();
    refreshCompanySearchResults();
    renderKpiCards(data);
    renderHealthDistributionEcharts(data);
    renderCompaniesTable(data);
    renderScatter(data);
    renderNewReactivatedTable(data);
    renderProductAreaAdoptionCharts(data);
    renderAtRiskTable(data);
    renderExpansionTable(data);
  }

  function loadPeriod(period) {
    const data = provider.getCompaniesDemoData(period);
    companyTableState.page = 1;
    atRiskTableState.page = 1;
    newReactivatedTableState.page = 1;
    expansionTableState.page = 1;
    renderAll(data);
  }

  function getRequestedPeriod() {
    const params = new URLSearchParams(globalScope.location.search);
    return provider.coercePeriodKey(params.get("period") || params.get("days") || provider.DEFAULT_PERIOD);
  }

  function initCompaniesPage() {
    if (document.body.dataset.companiesView !== "overview") {
      return;
    }

    mountSplitChangeValueWidthSync();
    mountCompanyTableSort();
    atRiskTableController.mountSort();
    newReactivatedTableController.mountSort();
    expansionTableController.mountSort();
    loadPeriod(getRequestedPeriod());
  }

  if (globalScope.__HymetryExposeTestHooks) {
    globalScope.HymetryCompaniesAnalyticsTesting = {
      createAdoptionRampOption,
      createKpiTrendOption,
      createProductAreaAdoptionOption,
      mountLineHoverTrendChart
    };
  }

  document.addEventListener("DOMContentLoaded", initCompaniesPage);
})(window);
