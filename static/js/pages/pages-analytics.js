(function mountHymetryPagesAnalytics(globalScope) {
  const provider = globalScope.HymetryPagesAnalyticsData;
  const bodyElement = globalScope.document?.body;
  const pageDetailsHelpers = globalScope.HymetryPageDetailsHelpers || {};
  const metricDynamicsHelpers = globalScope.HymetryMetricDynamics || {};
  const pageDetailsPeriodOptions = pageDetailsHelpers.PERIOD_OPTIONS || [7, 30, 90, 180];
  const defaultPageDetailsPeriod = pageDetailsHelpers.DEFAULT_PERIOD_DAYS || 30;
  const coercePageDetailPeriod = pageDetailsHelpers.coercePageDetailPeriod || ((value) => (pageDetailsPeriodOptions.includes(Number(value)) ? Number(value) : defaultPageDetailsPeriod));
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
  const shouldShowRelatedPages = pageDetailsHelpers.shouldShowRelatedPages || ((rows, currentId) => Array.isArray(rows) && rows.some((row) => row.pageId !== currentId && row.page_rule_id !== currentId));
  const numberFormatter = new Intl.NumberFormat("en-US");
  const averageUsersFormatter = new Intl.NumberFormat("en-US", {
    maximumFractionDigits: 2
  });
  const overviewHref = bodyElement?.dataset.pagesOverviewUrl || "index.html";
  const detailBaseUrl = bodyElement?.dataset.pagesDetailBaseUrl || "detail.html";
  const companyDetailBaseUrl = bodyElement?.dataset.companyDetailBaseUrl || "";
  const userDetailBaseUrl = bodyElement?.dataset.userDetailBaseUrl || "";
  const overviewRangeKey = bodyElement?.dataset.pagesRangeKey || "";
  const tailwindColorFallbacks = {
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
    "sky-50": "#f0f9ff",
    "sky-600": "#0284c7",
    "slate-50": "#f8fafc",
    "slate-200": "#e2e8f0",
    "slate-300": "#cbd5e1",
    "slate-400": "#94a3b8",
    "slate-500": "#64748b",
    "slate-600": "#475569",
    "slate-700": "#334155",
    "slate-900": "#0f172a",
    "gray-800": "#1f2937",
    white: "#ffffff"
  };

  if (!provider) {
    return;
  }

  const pageSearchDebounceMs = 220;
  const recentPagesStorageKey = "hymetry:recent-pages";
  let currentOverviewData = null;
  let currentDetailOverviewData = null;
  let currentPageDetailsData = null;
  const pageMetricsPageSize = 10;
  const pageCompaniesPageSize = 20;
  const pageChampionsPageSize = 20;
  const pageCompaniesState = {
    page: 1,
    sortKey: "engaged",
    sortDirection: "desc",
    isLoading: false,
    loadingToken: 0
  };
  const pageChampionsState = {
    page: 1,
    sortKey: "engaged",
    sortDirection: "desc",
    isLoading: false,
    loadingToken: 0
  };
  const pageMetricsState = {
    page: 1,
    sortKey: "companies",
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
  const pageMetricDynamicsState = {
    showPeers: false,
    isLoading: false,
    loadingToken: 0
  };
  let overviewPageSearchMounted = false;
  let productAreaFilterMounted = false;
  let overviewPageSearchDebounceId = 0;
  let detailPageSelectorMounted = false;
  let pageMetricsSortMounted = false;
  let detailPaginatedTableSortMounted = false;
  const overviewPageSearchState = {
    activeIndex: -1,
    isOpen: false,
    query: "",
    results: []
  };
  const detailPageSelectorState = {
    activeIndex: -1,
    isOpen: false,
    query: "",
    results: []
  };

  function escapeHtml(value) {
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function formatNumber(value) {
    const numericValue = Number(value);
    const normalizedValue = Object.is(numericValue, -0) ? 0 : numericValue;
    const formattedValue = numberFormatter.format(normalizedValue);

    return formattedValue === "-0" ? "0" : formattedValue;
  }

  function formatAverageUsers(value) {
    const numericValue = Number(value) || 0;

    return averageUsersFormatter.format(Math.round(numericValue * 100) / 100);
  }

  function formatTrendDateLabel(value) {
    const rawValue = String(value || "").trim();

    if (!rawValue) {
      return "";
    }

    const monthDayMatch = rawValue.match(/^([A-Za-z]{3,})\s+0?(\d{1,2})/);

    if (monthDayMatch) {
      return `${monthDayMatch[1].slice(0, 3)} ${Number(monthDayMatch[2])}`;
    }

    const date = new Date(rawValue);

    if (!Number.isNaN(date.getTime())) {
      return new Intl.DateTimeFormat("en-US", {
        month: "short",
        day: "numeric"
      }).format(date);
    }

    return rawValue;
  }

  function alignTrendLabels(labels, length) {
    const count = Math.max(0, Number(length) || 0);
    const source = Array.isArray(labels) ? labels.map(formatTrendDateLabel).filter(Boolean) : [];

    if (!count) {
      return [];
    }

    if (source.length >= count) {
      return source.slice(source.length - count);
    }

    return Array.from({ length: count }, (_, index) => source[index] || String(index + 1));
  }

  function getOverviewTrendLabels(data) {
    return (
      data?.trend_labels ||
      data?.top_pages_by_visits_over_time?.labels ||
      data?.top_pages_by_engaged_time_over_time?.labels ||
      []
    );
  }

  function formatDurationShort(totalSeconds) {
    const seconds = Math.max(0, Math.round(Number(totalSeconds) || 0));
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.round((seconds % 3600) / 60);

    if (hours > 0) {
      return minutes > 0 ? `${hours}h ${minutes}m` : `${hours}h`;
    }

    return `${minutes}m`;
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
      return tailwindColorFallbacks[name];
    }

    return value;
  }

  function tailwindColor(name) {
    return readTailwindColor(name) || tailwindColorFallbacks[name] || name;
  }

  function rgbaFromHex(hex, opacity) {
    const normalized = String(hex || "").trim().replace("#", "");
    const value = normalized.length === 3
      ? normalized.split("").map((character) => character + character).join("")
      : normalized;

    if (!/^[0-9a-f]{6}$/i.test(value)) {
      return null;
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
    const slateColor = tailwindColor("slate-900");

    return mixHexColors(color, slateColor, brightness > 0.58 ? 0.36 : 0.24);
  }

  function tailwindAlpha(name, opacity) {
    return (
      rgbaFromHex(readTailwindColor(name), opacity) ||
      rgbaFromHex(tailwindColorFallbacks[name], opacity) ||
      `rgba(0, 0, 0, ${opacity})`
    );
  }

  function readCssCustomProperty(element, propertyName) {
    const target = element || globalScope.document?.documentElement;
    const style = globalScope.getComputedStyle && target ? globalScope.getComputedStyle(target) : null;

    return style?.getPropertyValue(propertyName).trim() || "";
  }

  function parseTailwindColorToken(value) {
    const normalized = String(value || "").trim().replace(/^["']|["']$/g, "");
    const variableMatch = normalized.match(/^var\(\s*--color-([a-z0-9-]+)\s*(?:,[^)]+)?\)$/i);

    return variableMatch?.[1] || normalized;
  }

  function scopedTailwindColorToken(element, propertyName, fallbackName) {
    return parseTailwindColorToken(readCssCustomProperty(element, propertyName)) || fallbackName;
  }

  function scopedNumber(element, propertyName, fallbackValue) {
    const value = Number(readCssCustomProperty(element, propertyName));

    return Number.isFinite(value) ? value : fallbackValue;
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

  function createScopedTrendTheme(element, prefix, fallbackColorName, fallbackFillOpacity) {
    const colorName = scopedTailwindColorToken(element, `${prefix}-color`, fallbackColorName);
    const fillColorName = scopedTailwindColorToken(element, `${prefix}-fill-color`, "");
    const axisColorName = scopedTailwindColorToken(element, `${prefix}-axis-color`, "slate-300");
    const fillOpacity = scopedNumber(element, `${prefix}-fill-opacity`, fallbackFillOpacity);

    return {
      line: tailwindColor(colorName),
      axis: tailwindColor(axisColorName),
      fill: fillColorName ? tailwindColor(fillColorName) : tailwindAlpha(colorName, fillOpacity)
    };
  }

  function createPageMetricsLineTrendTheme() {
    const scope =
      globalScope.document?.getElementById("pages-change-table-body")?.closest("section") ||
      globalScope.document?.documentElement;
    const colorName = scopedTailwindColorToken(scope, "--page-metrics-trend-color", "");
    const fillColorName = scopedTailwindColorToken(scope, "--page-metrics-trend-fill-color", "");
    const positiveColorName = colorName || scopedTailwindColorToken(scope, "--page-metrics-trend-positive-color", "green-700");
    const negativeColorName = colorName || scopedTailwindColorToken(scope, "--page-metrics-trend-negative-color", "red-600");
    const neutralColorName = scopedTailwindColorToken(scope, "--page-metrics-trend-neutral-color", "slate-500");
    const axisColorName = scopedTailwindColorToken(scope, "--page-metrics-trend-axis-color", "slate-200");
    const fillOpacity = scopedNumber(scope, "--page-metrics-trend-fill-opacity", 0.14);
    const fillColor = fillColorName ? tailwindColor(fillColorName) : null;

    return {
      positive: tailwindColor(positiveColorName),
      negative: tailwindColor(negativeColorName),
      neutral: tailwindColor(neutralColorName),
      axis: tailwindColor(axisColorName),
      positiveFill: fillColor || tailwindAlpha(positiveColorName, fillOpacity),
      negativeFill: fillColor || tailwindAlpha(negativeColorName, fillOpacity)
    };
  }

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

  const chartTheme = {
    colors: {
      primary: visitsCircleColors[0],
      secondary: visitsCircleColors[1],
      warning: visitsCircleColors[1],
      danger: visitsCircleColors[2],
      positive: visitsCircleColors[4],
      accent: visitsCircleColors[6],
      rose: visitsCircleColors[5],
      lightBlue: visitsCircleColors[7],
      brown: visitsCircleColors[8],
      white: tailwindColor("white"),
      text: tailwindColor("slate-700"),
      mutedText: tailwindColor("slate-500"),
      labelText: tailwindColor("gray-800"),
      axis: tailwindColor("slate-300"),
      grid: tailwindColor("slate-200"),
      softFill: tailwindColor("sky-50")
    },
    series: chartSeriesColors
  };

  let productAreaColorByName = new Map();
  const productAreaColorResolver = globalScope.HymetryProductAreaColors?.createResolver({
    resolveColor: tailwindColor,
    palette: chartTheme.series
  }) || null;

  function productAreaName(area) {
    if (area && typeof area === "object") {
      return String(
        area.product_area_name ||
        area.productAreaName ||
        area.product_area ||
        area.productArea ||
        area.page_group ||
        area.pageGroup ||
        area.name ||
        area.product_area_key ||
        area.productAreaKey ||
        area.key ||
        ""
      ).trim() || "Unassigned";
    }

    return String(area || "").trim() || "Unassigned";
  }

  function productAreaExplicitColor(area, explicitColor = "") {
    if (explicitColor) {
      return String(explicitColor).trim();
    }

    if (!area || typeof area !== "object") {
      return "";
    }

    return String(
      area.color ||
      area.product_area_color ||
      area.productAreaColor ||
      area.page_group_color ||
      area.pageGroupColor ||
      ""
    ).trim();
  }

  function sankeyNodeProductAreaName(node) {
    return String(
      node?.product_area_name ||
      node?.productAreaName ||
      node?.product_area ||
      node?.productArea ||
      node?.product_area_key ||
      node?.productAreaKey ||
      node?.page_group ||
      node?.pageGroup ||
      node?.name ||
      ""
    ).trim() || "Unassigned";
  }

  function syncProductAreaPalette(data) {
    const names = [];
    productAreaColorByName = new Map();
    productAreaColorResolver?.reset();

    const add = (area, explicitColor = "") => {
      const name = productAreaName(area);
      const color = productAreaExplicitColor(area, explicitColor);

      if (!names.includes(name)) {
        names.push(name);
      }

      productAreaColorResolver?.add(name, color);
      if (color && !productAreaColorByName.has(name)) {
        productAreaColorByName.set(name, color);
      }
    };
    const addMany = (areas) => (Array.isArray(areas) ? areas : []).forEach((area) => add(area));
    const addColorLookup = (lookup) => {
      if (!lookup || Array.isArray(lookup) || typeof lookup !== "object") {
        return;
      }

      Object.entries(lookup).forEach(([name, color]) => add(name, color));
    };

    addMany(data?.product_area_options);
    addMany(data?.productAreaOptions);
    addMany(data?.product_areas);
    addMany(data?.productAreas);
    addColorLookup(data?.product_area_colors);
    addColorLookup(data?.productAreaColors);
    addMany(data?.product_area_summary);
    addMany(data?.rows);
    addMany(data?.change_aware_rows);

    (data?.engaged_time_treemap?.nodes || []).forEach((node) => {
      add(node);
      (node.children || []).forEach((child) => add(productAreaName(child), productAreaExplicitColor(child) || productAreaExplicitColor(node)));
    });

    (data?.company_engagement_by_page_group || []).forEach((group) => add(group));

    (data?.sankey?.nodes || []).forEach((node) => add(sankeyNodeProductAreaName(node), productAreaExplicitColor(node)));
    (data?.sankey?.links || []).forEach((link) => {
      add(
        link.source_product_area_name || link.sourceProductAreaName || link.source_product_area || link.sourceProductArea,
        link.source_product_area_color || link.sourceProductAreaColor || link.source_color || link.sourceColor
      );
      add(
        link.target_product_area_name || link.targetProductAreaName || link.target_product_area || link.targetProductArea,
        link.target_product_area_color || link.targetProductAreaColor || link.target_color || link.targetColor
      );
    });

    if (productAreaColorResolver) {
      productAreaColorResolver.finalize();
      names.forEach((name) => productAreaColorByName.set(name, productAreaColorResolver.color(name)));
      return;
    }

    names.forEach((name, index) => {
      if (!productAreaColorByName.has(name)) {
        productAreaColorByName.set(name, chartTheme.series[index % chartTheme.series.length] || chartTheme.colors.primary);
      }
    });
  }

  function productAreaColor(area, explicitColor = "") {
    const name = productAreaName(area);
    const color = productAreaExplicitColor(area, explicitColor);

    if (productAreaColorResolver) {
      return productAreaColorResolver.color(name, color);
    }

    if (color) {
      productAreaColorByName.set(name, tailwindColor(color));
    } else if (!productAreaColorByName.has(name)) {
      productAreaColorByName.set(
        name,
        chartTheme.series[productAreaColorByName.size % chartTheme.series.length] || chartTheme.colors.primary
      );
    }

    return productAreaColorByName.get(name);
  }

  function formatSignedPercent(value) {
    const pct = Math.round(Number(value) || 0);
    return `${pct > 0 ? "+" : ""}${pct}%`;
  }

  function detailHref(pageRuleId, periodDays = null) {
    const params = new URLSearchParams();
    let baseUrl = detailBaseUrl || "detail.html";

    if (periodDays) {
      params.set("period", String(periodDays));
    } else if (overviewRangeKey) {
      params.set("range", overviewRangeKey);
    }

    if (baseUrl.includes("__PAGE_RULE_ID__")) {
      baseUrl = baseUrl.replace("__PAGE_RULE_ID__", encodeURIComponent(pageRuleId));
    } else if (baseUrl.endsWith("/")) {
      baseUrl = `${baseUrl}${encodeURIComponent(pageRuleId)}/`;
    } else {
      params.set("page_rule_id", pageRuleId);
    }

    const query = params.toString();
    return query ? `${baseUrl}?${query}` : baseUrl;
  }

  function detailEntityHref(baseUrl, detailId, queryKey, fallbackUrl) {
    const id = String(detailId || "").trim();
    const params = new URLSearchParams();

    if (!id) {
      return "";
    }

    if (!baseUrl) {
      params.set(queryKey, id);
      if (overviewRangeKey) {
        params.set("range", overviewRangeKey);
      }
      return `${fallbackUrl}?${params.toString()}`;
    }

    let href = baseUrl;
    if (href.includes("__DETAIL_ID__")) {
      href = href.replace("__DETAIL_ID__", encodeURIComponent(id));
    } else if (/detail(?=\/|$)/.test(href)) {
      href = href.replace(/detail(?=\/|$)/, encodeURIComponent(id));
    } else if (href.endsWith("/")) {
      href = `${href}${encodeURIComponent(id)}/`;
    } else {
      params.set(queryKey, id);
    }

    const entityUrl = new URL(href, globalScope.location.origin);
    params.forEach((value, key) => entityUrl.searchParams.set(key, value));
    if (overviewRangeKey) {
      entityUrl.searchParams.set("range", overviewRangeKey);
    }

    return `${entityUrl.pathname}${entityUrl.search}`;
  }

  function userDetailId(row) {
    return String(row?.userId || row?.user_id || row?.id || "").trim();
  }

  function companyDetailId(row) {
    return String(row?.companyId || row?.company_id || "").trim();
  }

  function userDetailHref(row) {
    return detailEntityHref(userDetailBaseUrl, userDetailId(row), "user_id", "../users/detail.html");
  }

  function companyDetailHref(row) {
    return detailEntityHref(companyDetailBaseUrl, companyDetailId(row), "company_id", "../companies/detail.html");
  }

  function detailEntityLink(label, href, className = "font-medium text-sky-800 underline-offset-2 hover:underline") {
    const safeLabel = escapeHtml(label || "-");

    if (!href) {
      return `<span class="font-medium text-slate-900">${safeLabel}</span>`;
    }

    return `<a href="${escapeHtml(href)}" class="${className}">${safeLabel}</a>`;
  }

  function userDetailLink(row, label) {
    return detailEntityLink(label, userDetailHref(row));
  }

  function companyDetailLink(row, label) {
    return detailEntityLink(label, companyDetailHref(row));
  }

  function overviewPageSearchElements() {
    return {
      root: document.getElementById("page-search"),
      input: document.getElementById("pages-global-search"),
      listbox: document.getElementById("page-search-results")
    };
  }

  function productAreaFilterElements() {
    return {
      root: document.getElementById("product-area-filter"),
      button: document.getElementById("product-area-filter-button"),
      label: document.getElementById("product-area-filter-label"),
      reset: document.getElementById("product-area-filter-reset"),
      dropdown: document.getElementById("product-area-filter-dropdown"),
      apply: document.getElementById("product-area-filter-apply"),
      checkboxes: Array.from(document.querySelectorAll("#product-area-filter-options .product-area-filter__checkbox"))
    };
  }

  function detailPageSelectorElements() {
    return {
      root: document.getElementById("page-detail-page-selector"),
      button: document.getElementById("page-detail-page-selector-button"),
      dropdown: document.getElementById("page-detail-page-selector-results"),
      input: document.getElementById("page-detail-page-selector-input"),
      listbox: document.getElementById("page-detail-page-selector-listbox")
    };
  }

  function normalizePageSearchValue(value) {
    return String(value ?? "").trim().toLowerCase();
  }

  function pageRuleId(row) {
    const value = row?.page_rule_id || row?.pageRuleId || row?.pageId || row?.id || "";

    return value === null || value === undefined ? "" : String(value);
  }

  function pageSearchName(row) {
    return row?.page_name || row?.displayName || row?.pageName || pageRuleId(row) || "Page";
  }

  function pageSearchArea(row) {
    return row?.page_group || row?.productAreaName || row?.product_area || row?.product_area_name || "Unassigned";
  }

  function getPageSearchRows(data = null) {
    const sourceRows = [
      ...(Array.isArray(data?.rows) ? data.rows : []),
      ...(Array.isArray(data?.change_aware_rows) ? data.change_aware_rows : []),
      ...(Array.isArray(currentDetailOverviewData?.rows) ? currentDetailOverviewData.rows : []),
      ...(Array.isArray(currentDetailOverviewData?.change_aware_rows) ? currentDetailOverviewData.change_aware_rows : []),
      ...(Array.isArray(currentOverviewData?.rows) ? currentOverviewData.rows : []),
      ...(Array.isArray(currentOverviewData?.change_aware_rows) ? currentOverviewData.change_aware_rows : [])
    ];
    const rowsById = new Map();

    sourceRows.forEach((row) => {
      const id = pageRuleId(row);

      if (id && !rowsById.has(id)) {
        rowsById.set(id, row);
      }
    });

    return Array.from(rowsById.values());
  }

  function readRecentPageIds() {
    try {
      const value = globalScope.localStorage?.getItem(recentPagesStorageKey);
      const parsed = JSON.parse(value || "[]");

      return Array.isArray(parsed) ? parsed.filter((id) => typeof id === "string") : [];
    } catch {
      return [];
    }
  }

  function writeRecentPageIds(pageIds) {
    try {
      globalScope.localStorage?.setItem(recentPagesStorageKey, JSON.stringify(pageIds.slice(0, 8)));
    } catch {
      // localStorage may be unavailable in private or embedded browsing contexts.
    }
  }

  function rememberRecentPage(row) {
    const id = pageRuleId(row);

    if (!id) {
      return;
    }

    const pageIds = readRecentPageIds();
    writeRecentPageIds([id, ...pageIds.filter((pageId) => pageId !== id)]);
  }

  function pageSearchMetadata(row) {
    const metadata = [
      pageSearchArea(row),
      `${formatNumber(Number(row?.companies_count) || 0)} companies`,
      row?.engaged_seconds ? `${formatDurationShort(row.engaged_seconds)} engaged` : ""
    ].filter(Boolean);

    return metadata.join(" \u00b7 ");
  }

  function sortPageSearchRows(rows, preferredArea = "") {
    return rows.slice().sort((a, b) => {
      const aAreaMatch = preferredArea && pageSearchArea(a) === preferredArea ? 1 : 0;
      const bAreaMatch = preferredArea && pageSearchArea(b) === preferredArea ? 1 : 0;

      return (
        bAreaMatch - aAreaMatch ||
        (Number(b.companies_count) || 0) - (Number(a.companies_count) || 0) ||
        (Number(b.visits_count) || 0) - (Number(a.visits_count) || 0) ||
        pageSearchName(a).localeCompare(pageSearchName(b))
      );
    });
  }

  function getInitialPageSearchResults(rows, options = {}) {
    const excludedId = options.excludePageRuleId || "";
    const rowsById = new Map(rows.map((row) => [pageRuleId(row), row]));
    const recentPageIds = readRecentPageIds();
    const recentPages = recentPageIds
      .map((id) => rowsById.get(id))
      .filter((row) => row && pageRuleId(row) !== excludedId);
    const fallbackPages = sortPageSearchRows(rows, options.preferredArea)
      .filter((row) => pageRuleId(row) !== excludedId && !recentPageIds.includes(pageRuleId(row)));

    return [...recentPages, ...fallbackPages].slice(0, 8);
  }

  function getPageSearchMatches(rows, query, options = {}) {
    const normalizedQuery = normalizePageSearchValue(query);
    const excludedId = options.excludePageRuleId || "";

    if (normalizedQuery.length < 1) {
      return getInitialPageSearchResults(rows, options);
    }

    return sortPageSearchRows(rows, options.preferredArea)
      .filter((row) => {
        if (pageRuleId(row) === excludedId) {
          return false;
        }

        const searchableText = `${pageSearchName(row)} ${pageSearchArea(row)} ${pageRuleId(row)}`.toLowerCase();

        return searchableText.includes(normalizedQuery);
      })
      .slice(0, 8);
  }

  function renderPageSearchOptions(rows, idPrefix, dataAttribute, hrefForRow) {
    return rows
      .map((row, index) => {
        const href = hrefForRow(row);

        return `
        <a
          id="${idPrefix}-${index}"
          href="${escapeHtml(href)}"
          class="page-search__option"
          role="option"
          ${dataAttribute}="${index}"
          data-active="${String(index === 0)}"
          aria-selected="${String(index === 0)}">
          <span class="min-w-0">
            <span class="page-search__name">${escapeHtml(pageSearchName(row))}</span>
            <span class="page-search__meta">${escapeHtml(pageSearchMetadata(row))}</span>
          </span>
          <span class="page-search__open">Open &rarr;</span>
        </a>
      `;
      })
      .join("");
  }

  function closeOverviewPageSearchDropdown() {
    const { input, listbox } = overviewPageSearchElements();

    if (overviewPageSearchDebounceId) {
      globalScope.clearTimeout(overviewPageSearchDebounceId);
      overviewPageSearchDebounceId = 0;
    }

    overviewPageSearchState.isOpen = false;
    overviewPageSearchState.activeIndex = -1;

    if (input) {
      input.setAttribute("aria-expanded", "false");
      input.removeAttribute("aria-activedescendant");
    }

    if (listbox) {
      listbox.hidden = true;
      listbox.innerHTML = "";
    }
  }

  function setOverviewPageSearchActiveIndex(nextIndex) {
    const { input, listbox } = overviewPageSearchElements();

    if (!listbox || !overviewPageSearchState.results.length) {
      overviewPageSearchState.activeIndex = -1;
      input?.removeAttribute("aria-activedescendant");
      return;
    }

    const resultCount = overviewPageSearchState.results.length;
    overviewPageSearchState.activeIndex = (nextIndex + resultCount) % resultCount;

    listbox.querySelectorAll("[data-page-search-index]").forEach((option) => {
      const index = Number(option.getAttribute("data-page-search-index"));
      const isActive = index === overviewPageSearchState.activeIndex;

      option.dataset.active = String(isActive);
      option.setAttribute("aria-selected", String(isActive));
    });

    const activeOptionId = `page-search-option-${overviewPageSearchState.activeIndex}`;
    input?.setAttribute("aria-activedescendant", activeOptionId);
    document.getElementById(activeOptionId)?.scrollIntoView({ block: "nearest" });
  }

  function openOverviewPageDetail(row) {
    if (!row) {
      return;
    }

    rememberRecentPage(row);
    globalScope.location.href = detailHref(pageRuleId(row));
  }

  function renderOverviewPageSearchDropdown() {
    const { input, listbox } = overviewPageSearchElements();

    if (!input || !listbox) {
      return;
    }

    overviewPageSearchState.isOpen = true;
    input.setAttribute("aria-expanded", "true");
    listbox.hidden = false;

    if (!overviewPageSearchState.results.length) {
      overviewPageSearchState.activeIndex = -1;
      input.removeAttribute("aria-activedescendant");
      listbox.innerHTML = `<div class="page-search__empty" role="status">No pages found</div>`;
      return;
    }

    listbox.innerHTML = renderPageSearchOptions(
      overviewPageSearchState.results,
      "page-search-option",
      "data-page-search-index",
      (row) => detailHref(pageRuleId(row))
    );

    setOverviewPageSearchActiveIndex(overviewPageSearchState.activeIndex);

    listbox.querySelectorAll("[data-page-search-index]").forEach((option) => {
      const index = Number(option.getAttribute("data-page-search-index"));

      option.addEventListener("mouseenter", () => {
        setOverviewPageSearchActiveIndex(index);
      });

      option.addEventListener("click", () => {
        rememberRecentPage(overviewPageSearchState.results[index]);
      });

      option.addEventListener("auxclick", (event) => {
        if (event.button === 1) {
          rememberRecentPage(overviewPageSearchState.results[index]);
        }
      });
    });
  }

  function updateOverviewPageSearch(query) {
    if (overviewPageSearchDebounceId) {
      globalScope.clearTimeout(overviewPageSearchDebounceId);
      overviewPageSearchDebounceId = 0;
    }

    overviewPageSearchState.query = query;
    overviewPageSearchState.results = getPageSearchMatches(getPageSearchRows(currentOverviewData), query);
    overviewPageSearchState.activeIndex = overviewPageSearchState.results.length ? 0 : -1;
    renderOverviewPageSearchDropdown();
  }

  function scheduleOverviewPageSearchUpdate(query) {
    overviewPageSearchState.query = query;

    if (overviewPageSearchDebounceId) {
      globalScope.clearTimeout(overviewPageSearchDebounceId);
    }

    overviewPageSearchDebounceId = globalScope.setTimeout(() => {
      updateOverviewPageSearch(query);
    }, pageSearchDebounceMs);
  }

  function mountOverviewPageSearch() {
    const { root, input } = overviewPageSearchElements();

    if (!root || !input || overviewPageSearchMounted) {
      return;
    }

    overviewPageSearchMounted = true;

    input.addEventListener("input", () => {
      scheduleOverviewPageSearchUpdate(input.value);
    });

    input.addEventListener("focus", () => {
      updateOverviewPageSearch(input.value);
    });

    input.addEventListener("click", () => {
      updateOverviewPageSearch(input.value);
    });

    input.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        closeOverviewPageSearchDropdown();
        return;
      }

      if ((event.key === "ArrowDown" || event.key === "ArrowUp" || event.key === "Enter") && overviewPageSearchDebounceId) {
        updateOverviewPageSearch(input.value);
      }

      if ((event.key === "ArrowDown" || event.key === "ArrowUp") && !overviewPageSearchState.isOpen) {
        event.preventDefault();
        updateOverviewPageSearch(input.value);
        return;
      }

      if (!overviewPageSearchState.isOpen || !overviewPageSearchState.results.length) {
        return;
      }

      if (event.key === "ArrowDown") {
        event.preventDefault();
        setOverviewPageSearchActiveIndex(overviewPageSearchState.activeIndex + 1);
        return;
      }

      if (event.key === "ArrowUp") {
        event.preventDefault();
        setOverviewPageSearchActiveIndex(overviewPageSearchState.activeIndex - 1);
        return;
      }

      if (event.key === "Enter" && overviewPageSearchState.activeIndex >= 0) {
        event.preventDefault();
        openOverviewPageDetail(overviewPageSearchState.results[overviewPageSearchState.activeIndex]);
      }
    });

    document.addEventListener("pointerdown", (event) => {
      if (!root.contains(event.target)) {
        closeOverviewPageSearchDropdown();
      }
    });
  }

  function closeProductAreaFilterDropdown() {
    const { button, dropdown } = productAreaFilterElements();

    button?.setAttribute("aria-expanded", "false");
    if (dropdown) {
      dropdown.hidden = true;
    }
  }

  function openProductAreaFilterDropdown() {
    const { button, dropdown } = productAreaFilterElements();

    button?.setAttribute("aria-expanded", "true");
    if (dropdown) {
      dropdown.hidden = false;
    }
  }

  function selectedProductAreaFilterOptions() {
    const { checkboxes } = productAreaFilterElements();

    return checkboxes
      .filter((checkbox) => checkbox.checked)
      .map((checkbox) => ({
        key: checkbox.value,
        label: checkbox.closest(".product-area-filter__option")?.querySelector(".product-area-filter__option-label")?.textContent?.trim() || checkbox.value
      }))
      .filter((option) => option.key);
  }

  function updateProductAreaFilterLabel() {
    const { button, label, reset } = productAreaFilterElements();
    const selectedOptions = selectedProductAreaFilterOptions();
    const selectedCount = selectedOptions.length;

    if (!label || !button) {
      return;
    }

    if (selectedCount === 0) {
      label.textContent = "Filter product area...";
      label.title = "";
      label.dataset.placeholder = "true";
      button.dataset.hasSelection = "false";
      if (reset) {
        reset.hidden = true;
      }
      return;
    }

    const displayLabel = selectedOptions.map((option) => option.label).join(", ");
    label.textContent = displayLabel;
    label.title = displayLabel;
    label.removeAttribute("data-placeholder");
    button.dataset.hasSelection = "true";
    if (reset) {
      reset.hidden = false;
    }
  }

  function updateProductAreaFilterQuery(selectedKeys) {
    const url = new URL(globalScope.location.href);

    url.searchParams.delete("product_area");
    selectedKeys.forEach((key) => {
      url.searchParams.append("product_area", key);
    });
    globalScope.location.href = `${url.pathname}${url.search}${url.hash}`;
  }

  function mountProductAreaFilter() {
    const { root, button, reset, apply, checkboxes } = productAreaFilterElements();

    if (!root || !button || productAreaFilterMounted) {
      return;
    }

    productAreaFilterMounted = true;

    button.addEventListener("click", () => {
      const isExpanded = button.getAttribute("aria-expanded") === "true";
      if (isExpanded) {
        closeProductAreaFilterDropdown();
      } else {
        openProductAreaFilterDropdown();
      }
    });

    // Checkbox changes remain draft-only; the control reflects them after Apply reloads the page.
    apply?.addEventListener("click", () => {
      updateProductAreaFilterQuery(selectedProductAreaFilterOptions().map((option) => option.key));
    });

    reset?.addEventListener("click", (event) => {
      event.stopPropagation();
      checkboxes.forEach((checkbox) => {
        checkbox.checked = false;
      });
      updateProductAreaFilterLabel();
      updateProductAreaFilterQuery([]);
    });

    root.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        closeProductAreaFilterDropdown();
        button.focus();
      }
    });

    document.addEventListener("pointerdown", (event) => {
      if (!root.contains(event.target)) {
        closeProductAreaFilterDropdown();
      }
    });

    updateProductAreaFilterLabel();
  }

  function closeDetailPageSelectorDropdown() {
    const { button, dropdown, input, listbox } = detailPageSelectorElements();

    detailPageSelectorState.isOpen = false;
    detailPageSelectorState.activeIndex = -1;
    detailPageSelectorState.query = "";

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

  function setDetailPageSelectorActiveIndex(nextIndex) {
    const { button, input, listbox } = detailPageSelectorElements();

    if (!listbox || !detailPageSelectorState.results.length) {
      detailPageSelectorState.activeIndex = -1;
      button?.removeAttribute("aria-activedescendant");
      input?.removeAttribute("aria-activedescendant");
      return;
    }

    const resultCount = detailPageSelectorState.results.length;
    detailPageSelectorState.activeIndex = (nextIndex + resultCount) % resultCount;

    listbox.querySelectorAll("[data-page-selector-index]").forEach((option) => {
      const index = Number(option.getAttribute("data-page-selector-index"));
      const isActive = index === detailPageSelectorState.activeIndex;

      option.dataset.active = String(isActive);
      option.setAttribute("aria-selected", String(isActive));
    });

    const activeOptionId = `page-detail-page-selector-option-${detailPageSelectorState.activeIndex}`;
    button?.setAttribute("aria-activedescendant", activeOptionId);
    input?.setAttribute("aria-activedescendant", activeOptionId);
    document.getElementById(activeOptionId)?.scrollIntoView({ block: "nearest" });
  }

  function detailPageSelectorOptions() {
    const currentPage = currentPageDetailsData?.page || {};
    const currentPageRuleId = currentPage.pageRuleId || currentPage.id || getRequestedPageRuleId();

    return {
      excludePageRuleId: currentPageRuleId,
      preferredArea: currentPage.productAreaName || ""
    };
  }

  function getDetailPageSelectorResults() {
    return getPageSearchMatches(
      getPageSearchRows(currentDetailOverviewData || currentOverviewData),
      detailPageSelectorState.query,
      detailPageSelectorOptions()
    );
  }

  function openDetailPageSelectorPage(row) {
    if (!row) {
      return;
    }

    rememberRecentPage(row);
    globalScope.location.href = detailHref(pageRuleId(row), currentPageDetailsData?.period?.days || getRequestedPeriodDays());
  }

  function renderDetailPageSelectorDropdown({ focusInput = false } = {}) {
    const { button, dropdown, input, listbox } = detailPageSelectorElements();

    if (!button || !dropdown || !input || !listbox) {
      return;
    }

    detailPageSelectorState.results = getDetailPageSelectorResults();
    detailPageSelectorState.activeIndex = detailPageSelectorState.results.length ? 0 : -1;
    detailPageSelectorState.isOpen = true;
    button.setAttribute("aria-expanded", "true");
    input.setAttribute("aria-expanded", "true");
    dropdown.hidden = false;

    if (!detailPageSelectorState.results.length) {
      listbox.innerHTML = `<span class="page-search__empty" role="status">No pages found</span>`;
      if (focusInput) {
        input.focus();
      }
      return;
    }

    listbox.innerHTML = renderPageSearchOptions(
      detailPageSelectorState.results,
      "page-detail-page-selector-option",
      "data-page-selector-index",
      (row) => detailHref(pageRuleId(row), currentPageDetailsData?.period?.days || getRequestedPeriodDays())
    );

    setDetailPageSelectorActiveIndex(detailPageSelectorState.activeIndex);

    listbox.querySelectorAll("[data-page-selector-index]").forEach((option) => {
      const index = Number(option.getAttribute("data-page-selector-index"));

      option.addEventListener("mouseenter", () => {
        setDetailPageSelectorActiveIndex(index);
      });

      option.addEventListener("click", () => {
        rememberRecentPage(detailPageSelectorState.results[index]);
      });

      option.addEventListener("auxclick", (event) => {
        if (event.button === 1) {
          rememberRecentPage(detailPageSelectorState.results[index]);
        }
      });
    });

    if (focusInput) {
      input.focus();
    }
  }

  function mountDetailPageSelector() {
    const { root, button, input } = detailPageSelectorElements();

    if (!root || !button || !input || detailPageSelectorMounted) {
      return;
    }

    detailPageSelectorMounted = true;

    button.addEventListener("click", () => {
      if (detailPageSelectorState.isOpen) {
        closeDetailPageSelectorDropdown();
      } else {
        renderDetailPageSelectorDropdown({ focusInput: true });
      }
    });

    button.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        closeDetailPageSelectorDropdown();
        return;
      }

      if ((event.key === "ArrowDown" || event.key === "ArrowUp") && !detailPageSelectorState.isOpen) {
        event.preventDefault();
        renderDetailPageSelectorDropdown({ focusInput: true });
        return;
      }

      if (!detailPageSelectorState.isOpen || !detailPageSelectorState.results.length) {
        return;
      }

      if (event.key === "ArrowDown") {
        event.preventDefault();
        setDetailPageSelectorActiveIndex(detailPageSelectorState.activeIndex + 1);
        return;
      }

      if (event.key === "ArrowUp") {
        event.preventDefault();
        setDetailPageSelectorActiveIndex(detailPageSelectorState.activeIndex - 1);
        return;
      }

      if (event.key === "Enter" && detailPageSelectorState.activeIndex >= 0) {
        event.preventDefault();
        openDetailPageSelectorPage(detailPageSelectorState.results[detailPageSelectorState.activeIndex]);
      }
    });

    input.addEventListener("input", () => {
      detailPageSelectorState.query = input.value;
      renderDetailPageSelectorDropdown();
    });

    input.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        closeDetailPageSelectorDropdown();
        button.focus();
        return;
      }

      if (!detailPageSelectorState.isOpen) {
        return;
      }

      if (event.key === "ArrowDown") {
        event.preventDefault();
        setDetailPageSelectorActiveIndex(detailPageSelectorState.activeIndex + 1);
        return;
      }

      if (event.key === "ArrowUp") {
        event.preventDefault();
        setDetailPageSelectorActiveIndex(detailPageSelectorState.activeIndex - 1);
        return;
      }

      if (event.key === "Enter" && detailPageSelectorState.activeIndex >= 0) {
        event.preventDefault();
        openDetailPageSelectorPage(detailPageSelectorState.results[detailPageSelectorState.activeIndex]);
      }
    });

    document.addEventListener("pointerdown", (event) => {
      if (!root.contains(event.target)) {
        closeDetailPageSelectorDropdown();
      }
    });
  }

  function progressCell(valueLabel, pct, barClass) {
    return `
      <div class="min-w-[92px]">
        <div class="font-medium text-slate-900">${valueLabel}</div>
        <div class="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
          <div class="h-full rounded-full ${barClass || "bg-sky-500"}" style="width: ${clampPct(pct)}%"></div>
        </div>
      </div>
    `;
  }

  function createKpiTrendOption(values, scopeElement = null, labels = []) {
    const series = Array.isArray(values) ? values.map((value) => Number(value) || 0) : [];
    const trendLabels = alignTrendLabels(labels, series.length);
    const trendTheme = createScopedTrendTheme(scopeElement, "--pages-kpi-trend", "blue-400", 0.14);

    return {
      animation: false,
      tooltip: {
        trigger: "axis",
        confine: true,
        axisPointer: {
          type: "line",
          lineStyle: {
            color: trendTheme.axis,
            width: 1
          }
        },
        valueFormatter: (value) => formatNumber(value)
      },
      grid: {
        left: 0,
        right: 0,
        top: 2,
        bottom: 0
      },
      xAxis: {
        type: "category",
        show: false,
        boundaryGap: false,
        data: trendLabels.length ? trendLabels : series.map((_, index) => index + 1)
      },
      yAxis: {
        type: "value",
        show: false,
        min: "dataMin",
        max: compactAxisMax(series)
      },
      series: [
        {
          type: "line",
          data: series,
          smooth: true,
          symbol: "none",
          lineStyle: {
            color: trendTheme.line,
            width: 2
          },
          areaStyle: {
            color: trendTheme.fill
          },
          emphasis: {
            disabled: true
          }
        }
      ]
    };
  }

  function mountKpiTrendCharts(container, kpis, labels = []) {
    container.querySelectorAll("[data-kpi-trend-index]").forEach((element) => {
      const index = Number(element.getAttribute("data-kpi-trend-index"));
      const kpi = kpis[index];

      if (!kpi?.trend_values?.length) {
        return;
      }

      mountChart(element, createKpiTrendOption(kpi.trend_values, element, kpi.trend_labels || labels));
    });
  }

  function renderKpiCards(data) {
    const container = document.getElementById("pages-kpis");

    if (!container) {
      return;
    }

    const grid = container.querySelector("[data-pages-kpis-grid]");
    const template = document.getElementById("pages-kpi-card-template");

    if (!grid || !template) {
      return;
    }

    const kpis = data.kpis || [];
    grid.innerHTML = "";

    if (!kpis.length) {
      grid.innerHTML = `<div class="col-span-full py-8 text-center text-slate-500">No page metrics found for this period.</div>`;
      return;
    }

    kpis.forEach((kpi, index) => {
      const fragment = template.content.cloneNode(true);
      const labelElement = fragment.querySelector("[data-pages-kpi-label]");
      const valueElement = fragment.querySelector("[data-pages-kpi-value]");
      const deltaElement = fragment.querySelector("[data-pages-kpi-delta]");
      const trendElement = fragment.querySelector("[data-pages-kpi-trend]");

      if (labelElement) {
        labelElement.textContent = kpi.label;
      }

      if (valueElement) {
        valueElement.textContent = kpi.value;
      }

      if (deltaElement) {
        deltaElement.textContent = kpi.delta;
        deltaElement.setAttribute("data-delta-direction", deltaDirection(kpi.delta_value));
      }

      if (trendElement) {
        trendElement.setAttribute("data-kpi-trend-index", index);
      }

      grid.appendChild(fragment);
    });

    mountKpiTrendCharts(container, kpis, getOverviewTrendLabels(data));
  }

  let productAreaTrendPayloads = [];

  function formatProductAreaTrendValue(value, metricKey) {
    if (metricKey === "adoption") {
      return `${formatNumber(Math.round(Number(value) || 0))}%`;
    }

    if (metricKey === "engaged") {
      return formatDurationShort(value);
    }

    return formatNumber(Math.round(Number(value) || 0));
  }

  function createProductAreaTrendOption(values, config = {}, scopeElement = null) {
    const series = Array.isArray(values) ? values.map((value) => Number(value) || 0) : [];
    const trendLabels = alignTrendLabels(config.trendLabels || config.trend_labels || [], series.length);
    const trendTheme = createScopedTrendTheme(scopeElement, "--product-area-trend", "blue-400", 0.1);

    return {
      animation: false,
      tooltip: {
        trigger: "axis",
        confine: true,
        axisPointer: {
          type: "line",
          lineStyle: {
            color: trendTheme.axis,
            width: 1
          }
        },
        valueFormatter: (value) => formatProductAreaTrendValue(value, config.metricKey)
      },
      grid: {
        left: 0,
        right: 0,
        top: 2,
        bottom: 0
      },
      xAxis: {
        type: "category",
        show: false,
        boundaryGap: false,
        data: trendLabels.length ? trendLabels : series.map((_, index) => index + 1)
      },
      yAxis: {
        type: "value",
        show: false,
        min: "dataMin",
        max: compactAxisMax(series)
      },
      series: [
        {
          type: "line",
          data: series,
          smooth: true,
          symbol: "none",
          lineStyle: {
            color: trendTheme.line,
            width: 2
          },
          areaStyle: {
            color: trendTheme.fill
          },
          emphasis: {
            disabled: true
          }
        }
      ]
    };
  }

  function registerProductAreaTrendPayload({ areaName, metricLabel, metricKey, trendValues }) {
    const index = productAreaTrendPayloads.length;

    productAreaTrendPayloads.push({
      label: `${areaName} ${metricLabel}`,
      metricKey,
      values: trendValues
    });

    return index;
  }

  function mountProductAreaTrendCharts(container, labels = []) {
    container.querySelectorAll("[data-product-area-trend-index]").forEach((element) => {
      const index = Number(element.getAttribute("data-product-area-trend-index"));
      const payload = productAreaTrendPayloads[index];

      if (!payload?.values?.length) {
        return;
      }

      mountChart(element, createProductAreaTrendOption(payload.values, { ...payload, trend_labels: labels }, element));
    });
  }

  function productAreaSummaryTrend(row, metricKey) {
    const trends = row?.trends || {};
    const values = Array.isArray(trends[metricKey]) ? trends[metricKey] : [];

    if (values.length) {
      return values.map((value) => Number(value) || 0);
    }

    return [];
  }

  function productAreaSummaryDelta(row, fieldName, metricKey) {
    const directValue = row?.[fieldName];

    if (directValue !== null && directValue !== undefined) {
      return Number(directValue) || 0;
    }

    return Number(row?.deltas?.[metricKey]?.value) || 0;
  }

  function finalizeProductAreaSummaryRows(summaries) {
    const maxCompanies = Math.max(...summaries.map((row) => row.companies_count), 1);
    const maxUsers = Math.max(...summaries.map((row) => row.users_count), 1);
    const maxEngaged = Math.max(...summaries.map((row) => row.engaged_seconds), 1);

    return summaries
      .map((summary) => ({
        ...summary,
        companies_bar_value: Math.round((summary.companies_count / maxCompanies) * 100),
        adoption_bar_value: summary.adoption_pct,
        users_bar_value: Math.round((summary.users_count / maxUsers) * 100),
        engaged_bar_value: Math.round((summary.engaged_seconds / maxEngaged) * 100)
      }))
      .sort((a, b) => b.engaged_seconds - a.engaged_seconds || b.companies_count - a.companies_count);
  }

  function buildProductAreaSummaryRows(data) {
    const explicitRows = Array.isArray(data.product_area_summary) ? data.product_area_summary : [];

    return finalizeProductAreaSummaryRows(explicitRows.map((row) => ({
      product_area: row.product_area || row.product_area_name || row.page_group || "Unassigned",
      page_count: Number(row.page_count) || 0,
      companies_count: Number(row.companies_count) || 0,
      companies_change_pct: productAreaSummaryDelta(row, "companies_change_pct", "companies"),
      adoption_pct: Number(row.adoption_pct) || 0,
      adoption_change_pp: productAreaSummaryDelta(row, "adoption_change_pp", "adoption"),
      users_count: Number(row.users_count) || 0,
      users_change_pct: productAreaSummaryDelta(row, "users_change_pct", "users"),
      engaged_seconds: Number(row.engaged_seconds) || 0,
      engaged_change_pct: productAreaSummaryDelta(row, "engaged_change_pct", "engaged"),
      comparison_available: row.comparison_available !== false && row.comparisonAvailable !== false,
      trends: {
        companies: productAreaSummaryTrend(row, "companies"),
        adoption: productAreaSummaryTrend(row, "adoption"),
        users: productAreaSummaryTrend(row, "users"),
        engaged: productAreaSummaryTrend(row, "engaged")
      }
    })));
  }

  const productAreaSummaryMetrics = [
    { key: "companies", label: "Companies" },
    { key: "adoption", label: "Adoption" },
    { key: "users", label: "Users" },
    { key: "engaged", label: "Engaged" }
  ];

  function getProductAreaMetricDisplay(row, metricKey) {
    const comparisonAvailable = row.comparison_available !== false && row.comparisonAvailable !== false;

    switch (metricKey) {
      case "companies":
        return { valueLabel: formatNumber(row.companies_count), currentValue: row.companies_count, deltaValue: comparisonAvailable ? row.companies_change_pct : 0, deltaUnit: "%", barValue: row.companies_bar_value, comparisonAvailable };
      case "adoption":
        return { valueLabel: `${row.adoption_pct}%`, currentValue: row.adoption_pct, deltaValue: comparisonAvailable ? row.adoption_change_pp : 0, deltaUnit: "pp", barValue: row.adoption_bar_value, comparisonAvailable };
      case "users":
        return { valueLabel: formatNumber(row.users_count), currentValue: row.users_count, deltaValue: comparisonAvailable ? row.users_change_pct : 0, deltaUnit: "%", barValue: row.users_bar_value, comparisonAvailable };
      case "engaged":
        return { valueLabel: formatDurationShort(row.engaged_seconds), currentValue: row.engaged_seconds, deltaValue: comparisonAvailable ? row.engaged_change_pct : 0, deltaUnit: "%", barValue: row.engaged_bar_value, comparisonAvailable };
      default:
        return null;
    }
  }

  function getProductAreaChangeScaleByMetric(rows) {
    return productAreaSummaryMetrics.reduce((lookup, metric) => {
      lookup[metric.key] = Math.max(
        ...rows.map((row) => {
          const display = getProductAreaMetricDisplay(row, metric.key);
          return Math.abs(Number(display?.deltaValue) || 0);
        }),
        1
      );
      return lookup;
    }, {});
  }

  function renderProductAreaPagesCell(row) {
    return `
      <td class="product-area-pages-cell py-3.5 align-middle">
        <span class="pages-value-bar__label">${escapeHtml(formatNumber(Number(row.page_count) || 0))}</span>
      </td>
    `;
  }

  function renderProductAreaSplitChangeDeltaCell(display, metric, maxAbsDelta) {
    if (display.comparisonAvailable === false) {
      const tooltip = renderPeriodChangeTooltip(display, metric);

      return `
        <div class="pages-change-delta metric-header-tooltip" data-change-direction="neutral" style="--pages-change-bar-width: 6px;" tabindex="0" aria-label="${escapeHtml(`${metric.label}. ${tooltip.tooltipText}`)}" aria-describedby="${tooltip.tooltipId}">
          <span class="pages-change-delta__plot">
            <span class="pages-change-delta__bar pages-change-delta__bar--neutral"></span>
          </span>
          <span class="pages-change-delta__label text-slate-500">n/a</span>
          <span id="${tooltip.tooltipId}" class="metric-header-tooltip__content" role="tooltip">${tooltip.tooltipHtml}</span>
        </div>
      `;
    }

    const deltaValue = Number(display.deltaValue) || 0;
    const roundedDelta = roundedDeltaValue(deltaValue);
    const direction = deltaDirection(deltaValue);
    const trackWidth = direction === "negative" ? 17 : 36;
    const barWidth = roundedDelta === 0 ? 6 : Math.max(4, Math.round((Math.abs(deltaValue) / Math.max(maxAbsDelta, 1)) * trackWidth));
    const formattedDelta = formatDelta(deltaValue, display.deltaUnit);
    const tooltip = renderPeriodChangeTooltip(display, metric);

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

  function renderProductAreaMetricCell({ areaName, row, metric, trendValues, maxAbsDelta }) {
    const display = getProductAreaMetricDisplay(row, metric.key);

    if (!display) {
      return "";
    }

    const trendIndex = registerProductAreaTrendPayload({ areaName, metricLabel: metric.label, metricKey: metric.key, trendValues });

    return `
      <td class="product-area-metric-cell pages-split-change-cell py-3.5 align-middle" data-split-metric="${escapeHtml(metric.key)}">
        <div class="product-area-metric-layout">
          <div class="pages-split-change-group">
            <div class="pages-metric-value">
              ${renderMetricBarValue(display, metric)}
            </div>
            ${renderProductAreaSplitChangeDeltaCell(display, metric, maxAbsDelta)}
          </div>
          <span class="product-area-metric__trend" data-product-area-trend-index="${trendIndex}"></span>
        </div>
      </td>
    `;
  }

  function renderProductAreaSummary(data) {
    const tbody = document.getElementById("product-area-summary-body");

    if (!tbody) {
      return;
    }

    const rows = buildProductAreaSummaryRows(data);
    productAreaTrendPayloads = [];
    const changeScaleByMetric = getProductAreaChangeScaleByMetric(rows);

    if (!rows.length) {
      tbody.innerHTML = `<tr><td colspan="6" class="px-6 py-10 text-center text-slate-500">No product area data found for this period.</td></tr>`;
      return;
    }

    tbody.innerHTML = rows
      .map((row) => {
        const areaName = row.product_area;

        return `
          <tr class="align-middle hover:bg-slate-50">
            <td class="py-3.5 pl-0 font-medium text-slate-900">${escapeHtml(areaName)}</td>
            ${renderProductAreaPagesCell(row)}
            ${renderProductAreaMetricCell({
              areaName,
              row,
              metric: productAreaSummaryMetrics[0],
              trendValues: row.trends.companies,
              maxAbsDelta: changeScaleByMetric.companies
            })}
            ${renderProductAreaMetricCell({
              areaName,
              row,
              metric: productAreaSummaryMetrics[1],
              trendValues: row.trends.adoption,
              maxAbsDelta: changeScaleByMetric.adoption
            })}
            ${renderProductAreaMetricCell({
              areaName,
              row,
              metric: productAreaSummaryMetrics[2],
              trendValues: row.trends.users,
              maxAbsDelta: changeScaleByMetric.users
            })}
            ${renderProductAreaMetricCell({
              areaName,
              row,
              metric: productAreaSummaryMetrics[3],
              trendValues: row.trends.engaged,
              maxAbsDelta: changeScaleByMetric.engaged
            })}
          </tr>
        `;
      })
      .join("");

    syncSplitChangeValueWidths(tbody);
    mountProductAreaTrendCharts(tbody, getOverviewTrendLabels(data));
  }

  const changeTableMetrics = {
    companies: {
      value: (row) => row.companies_count,
      delta: (row) => row.companies_change_pct,
      deltaUnit: "%"
    },
    adoption: {
      value: (row) => row.adoption_pct,
      delta: (row) => row.adoption_change_pp,
      deltaUnit: "pp"
    },
    users: {
      value: (row) => row.users_count,
      delta: (row) => row.users_change_pct,
      deltaUnit: "%"
    },
    penetration: {
      value: (row) => row.penetration_pct,
      delta: (row) => row.penetration_change_pp,
      deltaUnit: "pp"
    },
    visits: {
      value: (row) => row.visits_count,
      delta: (row) => row.visits_change_pct,
      deltaUnit: "%"
    },
    engaged: {
      value: (row) => row.engaged_seconds,
      delta: (row) => row.engaged_change_pct,
      deltaUnit: "%"
    },
    avg_visit: {
      value: (row) => row.avg_visit_seconds,
      delta: (row) => row.avg_visit_change_pct,
      deltaUnit: "%"
    },
    interaction: {
      value: (row) => row.interaction_pct,
      delta: (row) => row.interaction_change_pp,
      deltaUnit: "pp"
    },
    clicks_per_visit: {
      value: (row) => row.clicks_per_visit,
      delta: (row) => row.clicks_per_visit_change_pct,
      deltaUnit: "%"
    }
  };

  const pageDynamicsMetrics = [
    { key: "companies", label: "Companies" },
    { key: "adoption", label: "Adoption" },
    { key: "users", label: "Users" },
    { key: "penetration", label: "Penetration" },
    { key: "visits", label: "Visits" },
    { key: "engaged", label: "Engaged" },
    { key: "avg_visit", label: "Avg / visit" },
    { key: "interaction", label: "Interaction" },
    { key: "clicks_per_visit", label: "Clicks / visit" }
  ];

  const combinedTestMetricsWithoutDynamics = new Set(["penetration", "avg_visit", "clicks_per_visit"]);
  const combinedTestColumnCount = 1 + pageDynamicsMetrics.length;
  const pageMetricsDefaultSortDirections = {
    page: "asc",
    companies: "desc",
    adoption: "desc",
    users: "desc",
    penetration: "desc",
    visits: "desc",
    engaged: "desc",
    avg_visit: "desc",
    interaction: "desc",
    clicks_per_visit: "desc"
  };

  function getChangeTableSort() {
    return pageMetricsState.sortKey;
  }

  function getOverviewSearch() {
    return (document.getElementById("pages-global-search")?.value || "").trim().toLowerCase();
  }

  function sortChangeRows(rows, sortKey) {
    const metric = changeTableMetrics[sortKey] || changeTableMetrics.companies;

    const direction = pageMetricsState.sortDirection === "asc" ? 1 : -1;

    return rows.slice().sort((a, b) => {
      if (sortKey === "page") {
        return String(a.page_name || "").localeCompare(String(b.page_name || "")) * direction;
      }

      return (metric.value(a) - metric.value(b)) * direction ||
        String(a.page_name || "").localeCompare(String(b.page_name || ""));
    });
  }

  function roundedDeltaValue(deltaValue) {
    return Math.round(Number(deltaValue) || 0);
  }

  function deltaDirection(deltaValue) {
    const rounded = roundedDeltaValue(deltaValue);

    if (rounded > 0) {
      return "positive";
    }

    if (rounded < 0) {
      return "negative";
    }

    return "neutral";
  }

  function deltaTextClass(deltaValue) {
    const direction = deltaDirection(deltaValue);

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

  function comparisonAvailable(row) {
    return row?.comparison_available !== false && row?.comparisonAvailable !== false;
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

  function formatCountMetricValue(value, singular, plural = `${singular}s`) {
    const rounded = Math.round(Number(value) || 0);
    const unit = Math.abs(rounded) === 1 ? singular : plural;

    return `${formatNumber(rounded)} ${unit}`;
  }

  function formatPeriodMetricValue(value, metricKey) {
    const numericValue = Number(value) || 0;

    switch (metricKey) {
      case "companies":
        return formatCountMetricValue(numericValue, "company", "companies");
      case "users":
        return formatCountMetricValue(numericValue, "user");
      case "visits":
        return formatCountMetricValue(numericValue, "visit");
      case "adoption":
      case "penetration":
      case "interaction":
        return `${formatNumber(Math.round(numericValue))}%`;
      case "engaged":
      case "avg_visit":
        return formatDurationShort(numericValue);
      case "clicks_per_visit":
        return `${numericValue.toFixed(1)} clicks / visit`;
      default:
        return formatNumber(Math.round(numericValue));
    }
  }

  function buildPeriodChangeTooltip(display, metric) {
    const currentValue = Number(display.currentValue) || 0;

    if (display.comparisonAvailable === false) {
      return [
        `Current period: ${formatPeriodMetricValue(currentValue, metric.key)}`,
        "Previous period: no data",
        "Change: n/a"
      ].join("\n");
    }

    const deltaValue = Number(display.deltaValue) || 0;
    const previousValue = previousPeriodValue(currentValue, deltaValue, display.deltaUnit);

    return [
      `Current period: ${formatPeriodMetricValue(currentValue, metric.key)}`,
      `Previous period: ${formatPeriodMetricValue(previousValue, metric.key)}`,
      `Change: ${formatDelta(deltaValue, display.deltaUnit)}`
    ].join("\n");
  }

  let periodChangeTooltipId = 0;

  function renderPeriodChangeTooltip(display, metric) {
    const tooltip = buildPeriodChangeTooltip(display, metric);
    const tooltipId = `period-change-tooltip-${periodChangeTooltipId}`;

    periodChangeTooltipId += 1;

    return {
      tooltipId,
      tooltipText: tooltip.replace(/\s+/g, " "),
      tooltipHtml: tooltip
        .split("\n")
        .map((line) => `<span class="pages-change-delta__tooltip-row">${escapeHtml(line)}</span>`)
        .join("")
    };
  }

  function changeMetricCell(valueLabel, deltaValue, unit) {
    return `
      <div class="flex w-full min-w-[116px] items-center justify-between gap-3">
        <span class="min-w-0 flex-1 whitespace-nowrap font-medium leading-tight text-slate-900">${escapeHtml(valueLabel)}</span>
        <span class="min-w-[48px] flex-none whitespace-nowrap text-right text-xs font-medium leading-tight ${deltaTextClass(deltaValue)}">${escapeHtml(formatDelta(deltaValue, unit))}</span>
      </div>
    `;
  }

  function changeMetricBarCell(valueLabel, deltaValue, unit, barValue, barClass) {
    return `
      <div class="w-full min-w-[116px]">
        ${changeMetricCell(valueLabel, deltaValue, unit)}
        <div class="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
          <div class="h-full rounded-full ${barClass}" style="width: ${clampPct(barValue)}%"></div>
        </div>
      </div>
    `;
  }

  function getPageMetricDisplay(row, metricKey) {
    const hasComparison = comparisonAvailable(row);

    switch (metricKey) {
      case "companies":
        return { valueLabel: formatNumber(row.companies_count), currentValue: row.companies_count, deltaValue: hasComparison ? row.companies_change_pct : 0, deltaUnit: "%", barValue: row.companies_bar_value, barClass: "bg-c-blue", comparisonAvailable: hasComparison };
      case "adoption":
        return { valueLabel: `${row.adoption_pct}%`, currentValue: row.adoption_pct, deltaValue: hasComparison ? row.adoption_change_pp : 0, deltaUnit: "pp", barValue: row.adoption_bar_value, barClass: "bg-c-teal", comparisonAvailable: hasComparison };
      case "users":
        return { valueLabel: formatNumber(row.users_count), currentValue: row.users_count, deltaValue: hasComparison ? row.users_change_pct : 0, deltaUnit: "%", barValue: row.users_bar_value, barClass: "bg-c-green", comparisonAvailable: hasComparison };
      case "penetration":
        return { valueLabel: `${row.penetration_pct}%`, currentValue: row.penetration_pct, deltaValue: hasComparison ? row.penetration_change_pp : 0, deltaUnit: "pp", barValue: row.penetration_bar_value, barClass: "bg-c-light-blue", comparisonAvailable: hasComparison };
      case "visits":
        return { valueLabel: formatNumber(row.visits_count), currentValue: row.visits_count, deltaValue: hasComparison ? row.visits_change_pct : 0, deltaUnit: "%", barValue: row.visits_bar_value, barClass: "bg-c-purple", comparisonAvailable: hasComparison };
      case "engaged":
        return { valueLabel: row.engaged_label, currentValue: row.engaged_seconds, deltaValue: hasComparison ? row.engaged_change_pct : 0, deltaUnit: "%", barValue: row.engaged_bar_value, barClass: "bg-c-orange", comparisonAvailable: hasComparison };
      case "avg_visit":
        return { valueLabel: row.avg_visit_label, currentValue: row.avg_visit_seconds, deltaValue: hasComparison ? row.avg_visit_change_pct : 0, deltaUnit: "%", barValue: row.avg_visit_bar_value, barClass: "bg-c-rose", comparisonAvailable: hasComparison };
      case "interaction":
        return { valueLabel: `${row.interaction_pct}%`, currentValue: row.interaction_pct, deltaValue: hasComparison ? row.interaction_change_pp : 0, deltaUnit: "pp", barValue: row.interaction_bar_value, barClass: "bg-c-red", comparisonAvailable: hasComparison };
      case "clicks_per_visit":
        return { valueLabel: row.clicks_per_visit.toFixed(1), currentValue: row.clicks_per_visit, deltaValue: hasComparison ? row.clicks_per_visit_change_pct : 0, deltaUnit: "%", barValue: row.clicks_per_visit_bar_value, barClass: "bg-c-brown", comparisonAvailable: hasComparison };
      default:
        return null;
    }
  }

  function renderPageMetricCell(row, metricKey) {
    const metric = getPageMetricDisplay(row, metricKey);

    if (!metric) {
      return "";
    }

    return changeMetricBarCell(metric.valueLabel, metric.deltaValue, metric.deltaUnit, metric.barValue, metric.barClass);
  }

  function actionMetricBarCell(valueLabel, deltaValue, unit, barValue, barClass) {
    return `
      <div class="w-full">
        <div class="flex w-full items-center justify-between gap-3">
          <span class="min-w-0 flex-1 whitespace-nowrap text-left font-medium leading-tight text-slate-900">${escapeHtml(valueLabel)}</span>
          <span class="flex-none whitespace-nowrap text-right font-medium leading-tight ${deltaTextClass(deltaValue)}" style="min-width: 44px;">${escapeHtml(formatDelta(deltaValue, unit))}</span>
        </div>
        <div class="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
          <div class="h-full rounded-full ${barClass}" style="width: ${clampPct(barValue)}%"></div>
        </div>
      </div>
    `;
  }

  function renderRelativeChangeTrend(values, options = {}) {
    const deltas = Array.isArray(values) ? values.map((value) => Number(value) || 0) : [];

    if (!deltas.length) {
      return "";
    }

    const width = options.width || 120;
    const height = options.height || 24;
    const baseline = height / 2;
    const gap = options.gap ?? (deltas.length > 18 ? 1 : 2);
    const barWidth = Math.max(1, Math.floor((width - gap * (deltas.length - 1)) / deltas.length));
    const maxAbsDelta = Math.max(...deltas.map((delta) => Math.abs(delta)), 1);
    const maxBarHeight = Math.max(2, baseline - 2);
    const svgWidth = options.svgWidth || "100%";
    const svgHeight = options.svgHeight || "24";
    const style = options.style || "";
    const className = options.className || "block";
    const bars = deltas
      .map((delta, index) => {
        const magnitude = Math.max(1, Math.round((Math.abs(delta) / maxAbsDelta) * maxBarHeight));
        const isNegative = delta < 0;
        const x = index * (barWidth + gap);
        const y = isNegative ? baseline : baseline - magnitude;
        const fill = delta > 0 ? chartTheme.colors.positive : delta < 0 ? chartTheme.colors.danger : chartTheme.colors.mutedText;

        return `<rect x="${x}" y="${y}" width="${barWidth}" height="${magnitude}" rx="1" fill="${fill}"></rect>`;
      })
      .join("");

    return `<svg class="${className}" width="${svgWidth}" height="${svgHeight}" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-hidden="true"${style ? ` style="${style}"` : ""}>${bars}</svg>`;
  }

  let relativeChangeLineTrendId = 0;

  function renderRelativeChangeLineTrend(values, options = {}) {
    const deltas = Array.isArray(values) ? values.map((value) => Number(value) || 0) : [];

    if (!deltas.length) {
      return "";
    }

    const width = options.width || 52;
    const height = options.height || 22;
    const baseline = height / 2;
    const maxAbsDelta = Math.max(...deltas.map((delta) => Math.abs(delta)), 1);
    const maxLineHeight = Math.max(2, baseline - 2);
    const trendTheme = options.theme || createPageMetricsLineTrendTheme();
    const points = deltas.map((delta, index) => {
      const x = deltas.length === 1 ? width / 2 : (index / (deltas.length - 1)) * width;
      const y = Math.min(height - 1, Math.max(1, baseline - (delta / maxAbsDelta) * maxLineHeight));

      return { x: Number(x.toFixed(2)), y: Number(y.toFixed(2)) };
    });
    const linePath = points.map((point, index) => `${index === 0 ? "M" : "L"} ${point.x} ${point.y}`).join(" ");
    const areaPath = `M ${points[0].x} ${baseline} ${points
      .map((point) => `L ${point.x} ${point.y}`)
      .join(" ")} L ${points[points.length - 1].x} ${baseline} Z`;
    const clipId = `relative-change-line-${relativeChangeLineTrendId}`;

    relativeChangeLineTrendId += 1;

    return `
      <svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-hidden="true" style="display: block; width: ${width}px; height: ${height}px;">
        <defs>
          <clipPath id="${clipId}-positive"><rect x="0" y="0" width="${width}" height="${baseline}"></rect></clipPath>
          <clipPath id="${clipId}-negative"><rect x="0" y="${baseline}" width="${width}" height="${height - baseline}"></rect></clipPath>
        </defs>
        <path d="${areaPath}" fill="${trendTheme.positiveFill}" clip-path="url(#${clipId}-positive)"></path>
        <path d="${areaPath}" fill="${trendTheme.negativeFill}" clip-path="url(#${clipId}-negative)"></path>
        <line x1="0" y1="${baseline}" x2="${width}" y2="${baseline}" stroke="${trendTheme.axis}" stroke-width="1"></line>
        <path d="${linePath}" fill="none" stroke="${trendTheme.positive}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" clip-path="url(#${clipId}-positive)"></path>
        <path d="${linePath}" fill="none" stroke="${trendTheme.negative}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" clip-path="url(#${clipId}-negative)"></path>
      </svg>
    `;
  }

  function renderPageDynamicsTrendCell(row, metric, pageName, options = {}) {
    const values = row.relative_change_series?.[metric.key] || [];
    const metricConfig = changeTableMetrics[metric.key] || changeTableMetrics.companies;
    const label = `${pageName} ${metric.label} relative daily change vs previous period`;
    const isCompact = options.compact === true;
    const compactWidth = options.width || 52;
    const compactHeight = options.height || 22;

    return `
      <div
        class="${isCompact ? "" : "w-full"}"
        style="${isCompact ? `width: ${compactWidth}px; height: ${compactHeight}px;` : "min-width: 108px;"}"
        aria-label="${escapeHtml(label)}"
        title="${escapeHtml(`${metric.label}: daily ${metricConfig.deltaUnit} change vs previous period`)}">
        ${isCompact ? renderRelativeChangeLineTrend(values, { width: compactWidth, height: compactHeight }) : renderRelativeChangeTrend(values)}
      </div>
    `;
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

  function renderMetricValueBarCell(row, metric) {
    const display = getPageMetricDisplay(row, metric.key);

    if (!display) {
      return "";
    }

    return `
      <div class="pages-metric-value">
        ${renderMetricBarValue(display, metric)}
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
    syncSplitChangeValueWidths(document.getElementById("product-area-summary-body"));
    syncSplitChangeValueWidths(document.getElementById("pages-change-table-body"));
    syncSplitChangeValueWidths(document.getElementById("related-pages-table-body"));
    syncSplitChangeValueWidths(document.getElementById("page-champions-table-body"));
    syncSplitChangeValueWidths(document.getElementById("companies-table-body"));
    syncSplitChangeValueWidths(document.getElementById("page-actions-table-body"));
  }

  let splitChangeValueWidthSyncFrame = 0;

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

  let splitChangeValueWidthSyncMounted = false;

  function mountSplitChangeValueWidthSync() {
    if (splitChangeValueWidthSyncMounted) {
      return;
    }

    splitChangeValueWidthSyncMounted = true;
    globalScope.addEventListener("resize", scheduleSplitChangeValueWidthSync);
    document.fonts?.ready?.then(scheduleSplitChangeValueWidthSync);
  }

  function getVisibleChangeRows(rows) {
    const sortMetric = getChangeTableSort();
    const search = getOverviewSearch();
    const filteredRows = rows.filter((row) => {
      if (!search) {
        return true;
      }

      return String(row.page_name || "").toLowerCase().includes(search);
    });

    return sortChangeRows(filteredRows, sortMetric);
  }

  function getPageMetricsPageCount(rows) {
    return tablePageCount(currentOverviewData, "pageMetrics", rows, pageMetricsPageSize);
  }

  function pageMetricsPaginationIcon(direction) {
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

  function renderPageMetricsPagination(totalPages) {
    const container = document.querySelector("[data-page-metrics-pagination]");

    if (!container) {
      return;
    }

    if (totalPages <= 1) {
      container.hidden = true;
      container.innerHTML = "";
      return;
    }

    const currentPage = Math.min(totalPages, Math.max(1, pageMetricsState.page));
    const disabledAttr = pageMetricsState.isLoading ? " disabled" : "";

    container.hidden = false;
    container.innerHTML = `
      ${
        currentPage > 2
          ? `<button type="button" class="font-medium text-sky-700 hover:text-sky-800" data-page-metrics-page-action="first"${disabledAttr}>Go to first page</button>`
          : `<span aria-hidden="true"></span>`
      }
      <div class="flex items-center justify-between gap-6 sm:justify-end">
        ${
          currentPage > 1
            ? `<button type="button" class="inline-flex h-8 w-8 items-center justify-center text-sky-700 hover:text-sky-800" data-page-metrics-page-action="previous" aria-label="Back to previous page"${disabledAttr}>${pageMetricsPaginationIcon("previous")}</button>`
            : `<span class="invisible h-8 w-8" aria-hidden="true"></span>`
        }
        <span class="text-slate-700">Page ${currentPage}/${totalPages}</span>
        ${
          currentPage < totalPages
            ? `<button type="button" class="inline-flex items-center gap-2 rounded-md border border-slate-200 bg-transparent px-4 py-3 font-medium text-sky-700 duration-150 hover:bg-slate-100" data-page-metrics-page-action="next"${disabledAttr}>Continue to next page ${pageMetricsPaginationIcon("next")}</button>`
            : ""
        }
      </div>
    `;

    container.querySelectorAll("[data-page-metrics-page-action]").forEach((button) => {
      button.addEventListener("click", () => {
        const action = button.getAttribute("data-page-metrics-page-action");
        const targetPage =
          action === "first"
            ? 1
            : action === "previous"
              ? Math.max(1, pageMetricsState.page - 1)
              : Math.min(totalPages, pageMetricsState.page + 1);

        requestPageMetricsPage(targetPage);
      });
    });
  }

  function setPageMetricsLoading(isLoading) {
    const overlay = document.querySelector("[data-page-metrics-table-loading]");
    const tableShell = document.querySelector("[data-page-metrics-scroll]");
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

  function isPageMetricsHeaderVisible() {
    const tableHead = document.querySelector("[data-page-metrics-scroll] thead");

    if (!tableHead) {
      return true;
    }

    const stickyTop = document.querySelector("body > nav")?.getBoundingClientRect().height || 48;
    const rect = tableHead.getBoundingClientRect();

    return rect.top >= stickyTop && rect.bottom <= globalScope.innerHeight;
  }

  function scrollPageMetricsHeaderIntoView() {
    const tableHead = document.querySelector("[data-page-metrics-scroll] thead");

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

  function simulatePageMetricsLoad(onComplete) {
    if (pageMetricsState.isLoading) {
      return;
    }

    pageMetricsState.isLoading = true;
    pageMetricsState.loadingToken += 1;

    const token = pageMetricsState.loadingToken;
    const rows = currentOverviewData ? getVisibleChangeRows(currentOverviewData.change_aware_rows) : [];

    setPageMetricsLoading(true);
    renderPageMetricsPagination(getPageMetricsPageCount(rows));

    if (!isPageMetricsHeaderVisible()) {
      scrollPageMetricsHeaderIntoView();
    }

    globalScope.setTimeout(() => {
      if (token !== pageMetricsState.loadingToken) {
        return;
      }

      onComplete();
      pageMetricsState.isLoading = false;
      setPageMetricsLoading(false);
      renderPageMetricsPagination(getPageMetricsPageCount(currentOverviewData ? getVisibleChangeRows(currentOverviewData.change_aware_rows) : []));
    }, 350);
  }

  function loadPageMetricsTablePage(targetPage) {
    if (typeof provider.loadPagesOverviewTable !== "function" || !currentOverviewData || pageMetricsState.isLoading) {
      return false;
    }

    pageMetricsState.isLoading = true;
    pageMetricsState.loadingToken += 1;

    const token = pageMetricsState.loadingToken;

    setPageMetricsLoading(true);
    renderPageMetricsPagination(getPageMetricsPageCount(currentOverviewData ? getVisibleChangeRows(currentOverviewData.change_aware_rows) : []));

    if (!isPageMetricsHeaderVisible()) {
      scrollPageMetricsHeaderIntoView();
    }

    provider.loadPagesOverviewTable({
      page: targetPage,
      page_size: pageMetricsPageSize,
      sort: pageMetricsState.sortKey,
      direction: pageMetricsState.sortDirection,
      q: getOverviewSearch()
    }).then((payload) => {
      if (token !== pageMetricsState.loadingToken) {
        return;
      }

      if (applyTablePayload(currentOverviewData, "pageMetrics", "change_aware_rows", payload, pageMetricsState)) {
        renderChangeAwareRows(currentOverviewData.change_aware_rows);
      }
    }).finally(() => {
      if (token !== pageMetricsState.loadingToken) {
        return;
      }

      pageMetricsState.isLoading = false;
      setPageMetricsLoading(false);
      renderPageMetricsPagination(getPageMetricsPageCount(currentOverviewData ? getVisibleChangeRows(currentOverviewData.change_aware_rows) : []));
    });

    return true;
  }

  function requestPageMetricsPage(targetPage) {
    if (!currentOverviewData || pageMetricsState.isLoading || targetPage === pageMetricsState.page) {
      return;
    }

    if (loadPageMetricsTablePage(targetPage)) {
      return;
    }

    simulatePageMetricsLoad(() => {
      pageMetricsState.page = targetPage;
      renderChangeAwareRows(currentOverviewData.change_aware_rows);
    });
  }

  function updatePageMetricsSortButtons() {
    document.querySelectorAll("[data-page-metrics-sort]").forEach((button) => {
      const isActive = button.getAttribute("data-page-metrics-sort") === pageMetricsState.sortKey;

      button.setAttribute("data-sort-direction", isActive ? pageMetricsState.sortDirection : "");
      button.setAttribute("aria-pressed", String(isActive));
    });
    mountPageMetricsStickyHeader();
  }

  function mountPageMetricsSort() {
    if (pageMetricsSortMounted) {
      return;
    }

    pageMetricsSortMounted = true;

    document.querySelectorAll("[data-page-metrics-sort]").forEach((button) => {
      button.addEventListener("click", () => {
        const sortKey = button.getAttribute("data-page-metrics-sort") || "companies";

        if (!currentOverviewData || pageMetricsState.isLoading) {
          return;
        }

        if (pageMetricsState.sortKey === sortKey) {
          pageMetricsState.sortDirection = pageMetricsState.sortDirection === "asc" ? "desc" : "asc";
        } else {
          pageMetricsState.sortKey = sortKey;
          pageMetricsState.sortDirection = pageMetricsDefaultSortDirections[sortKey] || "desc";
        }

        pageMetricsState.page = 1;
        updatePageMetricsSortButtons();
        if (loadPageMetricsTablePage(1)) {
          return;
        }

        simulatePageMetricsLoad(() => {
          renderChangeAwareRows(currentOverviewData.change_aware_rows);
        });
      });
    });
  }

  function getSplitChangeScaleByMetric(rows) {
    return pageDynamicsMetrics.reduce((lookup, metric) => {
      if (combinedTestMetricsWithoutDynamics.has(metric.key)) {
        return lookup;
      }

      const maxAbsDelta = Math.max(
        ...rows.map((row) => {
          const display = getPageMetricDisplay(row, metric.key);
          return Math.abs(Number(display?.deltaValue) || 0);
        }),
        1
      );

      lookup[metric.key] = maxAbsDelta;
      return lookup;
    }, {});
  }

  function renderSplitChangeDeltaCell(row, metric, maxAbsDelta) {
    const display = getPageMetricDisplay(row, metric.key);

    if (!display) {
      return "";
    }

    if (display.comparisonAvailable === false) {
      const tooltip = renderPeriodChangeTooltip(display, metric);

      return `
        <div class="pages-change-delta metric-header-tooltip" data-change-direction="neutral" style="--pages-change-bar-width: 6px;" tabindex="0" aria-label="${escapeHtml(`${metric.label}. ${tooltip.tooltipText}`)}" aria-describedby="${tooltip.tooltipId}">
          <span class="pages-change-delta__plot">
            <span class="pages-change-delta__bar pages-change-delta__bar--neutral"></span>
          </span>
          <span class="pages-change-delta__label text-slate-500">n/a</span>
          <span id="${tooltip.tooltipId}" class="metric-header-tooltip__content" role="tooltip">${tooltip.tooltipHtml}</span>
        </div>
      `;
    }

    const deltaValue = Number(display.deltaValue) || 0;
    const roundedDelta = roundedDeltaValue(deltaValue);
    const direction = deltaDirection(deltaValue);
    const trackWidth = direction === "negative" ? 17 : 36;
    const barWidth = roundedDelta === 0 ? 6 : Math.max(4, Math.round((Math.abs(deltaValue) / Math.max(maxAbsDelta, 1)) * trackWidth));
    const formattedDelta = formatDelta(deltaValue, display.deltaUnit);
    const tooltip = renderPeriodChangeTooltip(display, metric);

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

  function renderSplitMetricChangeGroup(row, metric, maxAbsDelta) {
    return `
      <td class="pages-split-change-cell py-3.5 pr-6 align-middle" data-split-metric="${escapeHtml(metric.key)}">
        <div class="pages-split-change-group">
          ${renderMetricValueBarCell(row, metric)}
          ${renderSplitChangeDeltaCell(row, metric, maxAbsDelta)}
        </div>
      </td>
    `;
  }

  function mountPageRowNavigation(tbody) {
    tbody.querySelectorAll("[data-page-detail-href]").forEach((row) => {
      const href = row.getAttribute("data-page-detail-href");

      if (!href) {
        return;
      }

      row.addEventListener("click", (event) => {
        if (event.target.closest("a, button, input, select, textarea")) {
          return;
        }

        globalScope.location.href = href;
      });
      row.addEventListener("keydown", (event) => {
        if (event.key !== "Enter" && event.key !== " ") {
          return;
        }

        event.preventDefault();
        globalScope.location.href = href;
      });
    });
  }

  function renderPageMetrics2Rows(sortedRows) {
    const tbody = document.getElementById("pages-change-table-body");

    if (!tbody) {
      return;
    }

    const totalPages = getPageMetricsPageCount(sortedRows);

    pageMetricsState.page = Math.min(totalPages, Math.max(1, pageMetricsState.page));
    updatePageMetricsSortButtons();
    renderPageMetricsPagination(totalPages);

    if (!sortedRows.length) {
      tbody.innerHTML = `
        <tr>
          <td colspan="${combinedTestColumnCount}" class="px-6 py-10 text-center text-slate-500">No page metrics found for this period.</td>
        </tr>
      `;
      renderPageMetricsPagination(1);
      return;
    }

    const pageRows = tableRowsForRender(currentOverviewData, "pageMetrics", sortedRows, pageMetricsState, pageMetricsPageSize);
    const changeScaleByMetric = getSplitChangeScaleByMetric(sortedRows);

    tbody.innerHTML = pageRows
      .map((row) => {
        const pageName = escapeHtml(row.page_name);
        const link = detailHref(row.page_rule_id);

        return `
          <tr class="group cursor-pointer align-middle hover:bg-slate-50" data-page-detail-href="${link}" tabindex="0">
            <td class="sticky left-0 z-[1] bg-white py-3.5 pl-0 pr-6 font-medium group-hover:bg-slate-50">
              <a class="text-sky-800 underline-offset-2 hover:underline" href="${link}">${pageName}</a>
            </td>
            ${pageDynamicsMetrics
              .map((metric) => {
                if (combinedTestMetricsWithoutDynamics.has(metric.key)) {
                  return `<td class="py-3.5 pr-6 align-middle" data-split-metric="${escapeHtml(metric.key)}">${renderMetricValueBarCell(row, metric)}</td>`;
                }

                return renderSplitMetricChangeGroup(row, metric, changeScaleByMetric[metric.key]);
              })
              .join("")}
          </tr>
        `;
      })
      .join("");

    syncSplitChangeValueWidths(tbody);
    mountPageRowNavigation(tbody);
  }

  function renderChangeAwareRows(rows) {
    const sortedRows = getVisibleChangeRows(rows);

    renderPageMetrics2Rows(sortedRows);
  }

  function mountStickyTableHeader(table) {
    const tableHead = table?.querySelector("thead");
    const scrollContainer = table?.closest("[data-page-metrics-scroll], [data-sticky-table-header]");

    if (!table || !tableHead || !scrollContainer) {
      return;
    }

    if (table.__hymetryStickyTableHeaderRefresh) {
      table.__hymetryStickyTableHeaderRefresh();
      return;
    }

    const stickyHeader = document.createElement("div");
    const stickyHeaderId = scrollContainer.getAttribute("data-sticky-table-header-id");

    if (stickyHeaderId) {
      stickyHeader.id = stickyHeaderId;
    } else if (scrollContainer.hasAttribute("data-page-metrics-scroll")) {
      stickyHeader.id = "page-metrics-sticky-header";
    }

    stickyHeader.className = "page-metrics-sticky-header";
    stickyHeader.setAttribute("aria-hidden", "true");
    document.body.appendChild(stickyHeader);

    const cloneTable = table.cloneNode(false);
    let cloneHead = null;

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

    refreshCloneHead();
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

      stickyHeader.style.setProperty("--page-metrics-sticky-top", `${stickyTop}px`);
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

  function mountStickyTableHeaders(selector) {
    document.querySelectorAll(selector).forEach(mountStickyTableHeader);
  }

  function mountPageMetricsStickyHeader() {
    mountStickyTableHeaders("[data-page-metrics-scroll] table");
  }

  function mountDetailStickyTableHeaders() {
    mountStickyTableHeaders("[data-sticky-table-header] table");
  }

  let floatingDeltaTooltipsMounted = false;

  function mountFloatingDeltaTooltips() {
    if (floatingDeltaTooltipsMounted || !document.body) {
      return;
    }

    floatingDeltaTooltipsMounted = true;
    document.documentElement.classList.add("metric-floating-tooltips-enabled");

    const floatingTooltip = document.createElement("div");
    floatingTooltip.className = "metric-header-tooltip__content metric-floating-tooltip";
    floatingTooltip.dataset.tooltipKind = "delta";
    floatingTooltip.dataset.visible = "false";
    floatingTooltip.setAttribute("aria-hidden", "true");
    floatingTooltip.setAttribute("role", "tooltip");
    document.body.appendChild(floatingTooltip);

    const viewportPadding = 8;
    const verticalGap = 8;
    let activeTrigger = null;
    let positionAnimationFrame = 0;

    const getTooltipTrigger = (target) => {
      if (!target || typeof target.closest !== "function") {
        return null;
      }

      return target.closest(".pages-change-delta.metric-header-tooltip");
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

      if (
        triggerRect.bottom < 0 ||
        triggerRect.top > viewportHeight ||
        triggerRect.right < 0 ||
        triggerRect.left > viewportWidth
      ) {
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

  function renderOverviewTopActionsByPageGroup(data) {
    const container = document.getElementById("overview-top-actions-grid");

    if (!container) {
      return;
    }

    const groups = (data.top_actions_by_page_group || []).slice(0, 8);

    if (!groups.length) {
      container.innerHTML = `<div class="col-span-full py-8 text-center text-slate-500">No page group actions found for this period.</div>`;
      return;
    }

    container.innerHTML = groups
      .map((group) => {
        const actions = (group.actions || [])
          .slice()
          .sort((a, b) => b.clicks - a.clicks)
          .slice(0, 5);
        const maxClicks = Math.max(...actions.map((action) => action.clicks), 1);

        return `
          <article class="min-w-0 rounded-lg border border-slate-200 bg-white p-4">
            <h3 class="text-sm font-semibold text-slate-900">${escapeHtml(group.page_group)}</h3>
            <table class="mt-3 w-full text-left text-sm" style="table-layout: fixed;">
              <colgroup>
                <col />
                <col style="width: 124px;" />
                <col style="width: 116px;" />
              </colgroup>
              <thead class="border-b border-gray-300 text-slate-600">
                <tr>
                  <th class="py-3 pr-6 font-normal">Top actions</th>
                  <th class="py-3 pr-6 text-left font-normal">Clicks</th>
                  <th class="py-3 text-left font-normal">% visits</th>
                </tr>
              </thead>
              <tbody class="text-slate-700">
                ${actions
                  .map(
                    (action) => `
                      <tr>
                        <td class="py-3.5 pr-6">
                          <span class="block truncate font-medium leading-6 text-slate-900" title="${escapeHtml(action.element_key)}">${escapeHtml(action.element_key)}</span>
                        </td>
                        <td class="py-3.5 pr-6 tabular-nums">${actionMetricBarCell(formatNumber(action.clicks), action.clicks_change_pct, "%", (action.clicks / maxClicks) * 100, "bg-c-orange")}</td>
                        <td class="py-3.5 tabular-nums">${actionMetricBarCell(`${action.visits_pct}%`, action.visits_change_pp, "pp", action.visits_pct, "bg-c-purple")}</td>
                      </tr>
                    `
                  )
                  .join("")}
              </tbody>
            </table>
          </article>
        `;
      })
      .join("");
  }

  function createCompanyEngagementScatterSpec(group, config) {
    const pointColor = productAreaColor(group);
    const points = (group.points || []).map((point) => {
      const activeUsers = Number(point.active_users) || 0;

      return {
        company_name: point.company_name,
        active_users: activeUsers,
        active_users_label: point.active_users_label || formatAverageUsers(activeUsers),
        avg_engaged_seconds_per_user: Number(point.avg_engaged_seconds_per_user) || 0,
        avg_engaged_label: point.avg_engaged_label,
        total_engaged_label: point.total_engaged_label,
        visits: Number(point.visits) || 0
      };
    });
    const xMax = Math.max(...points.map((point) => point.active_users), 1);
    const yMax = Math.max(...points.map((point) => point.avg_engaged_seconds_per_user), 60);
    const xDomainMax = compactAxisMax(xMax, { headroom: 0.1, minPadding: 1 });
    const yDomainMax = compactAxisMax(yMax, { headroom: 0.1, minPadding: 30 });

    return {
      $schema: "https://vega.github.io/schema/vega/v5.json",
      width: config.width,
      height: 300,
      padding: {
        top: 24,
        right: 72,
        bottom: 44,
        left: 40
      },
      background: chartTheme.colors.white,
      config: {
        font: "Inter, ui-sans-serif, system-ui, sans-serif",
        axis: {
          domainColor: chartTheme.colors.axis,
          gridColor: chartTheme.colors.grid,
          gridOpacity: 1,
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
        {
          name: "hoveredCompany",
          value: null,
          on: [
            { events: "@companyPoints:mouseover", update: "datum.company_name" },
            { events: "@companyPoints:mouseout", update: "null" }
          ]
        }
      ],
      data: [
        {
          name: "points",
          values: points
        }
      ],
      scales: [
        {
          name: "xScale",
          type: "linear",
          domain: [0, xDomainMax],
          nice: false,
          range: "width"
        },
        {
          name: "yScale",
          type: "linear",
          domain: [0, yDomainMax],
          nice: false,
          range: "height"
        }
      ],
      axes: [
        {
          orient: "bottom",
          scale: "xScale",
          title: "Avg active users",
          grid: false,
          tickCount: 5,
          labelFlush: true,
          labelFlushOffset: 4
        },
        {
          orient: "left",
          scale: "yScale",
          title: "Avg engaged time / user",
          grid: false,
          tickCount: 5,
          titleAngle: 0,
          titleAnchor: "end",
          titleAlign: "left",
          titleX: -58,
          titleY: -16,
          labelExpr: "datum.value >= 3600 ? floor(datum.value / 3600) + 'h' : floor(datum.value / 60) + 'm'"
        }
      ],
      marks: [
        {
          name: "companyPoints",
          type: "symbol",
          from: { data: "points" },
          encode: {
            enter: {
              x: { scale: "xScale", field: "active_users" },
              y: { scale: "yScale", field: "avg_engaged_seconds_per_user" },
              shape: { value: "circle" },
              stroke: { value: chartTheme.colors.white },
              strokeWidth: { value: 1.5 }
            },
            update: {
              cursor: { value: "pointer" },
              fill: [
                { test: "hoveredCompany === datum.company_name", value: chartTheme.colors.rose },
                { value: pointColor }
              ],
              opacity: [
                { test: "hoveredCompany === datum.company_name", value: 1 },
                { value: 0.72 }
              ],
              size: [
                { test: "hoveredCompany === datum.company_name", value: 170 },
                { value: 86 }
              ],
              zindex: [
                { test: "hoveredCompany === datum.company_name", value: 1 },
                { value: 0 }
              ],
              tooltip: {
                signal:
                  "{'Company name': datum.company_name, 'Avg active users': datum.active_users_label, 'Avg engaged time / user': datum.avg_engaged_label, 'Total engaged time': datum.total_engaged_label, 'Visits': format(datum.visits, ',')}"
              }
            }
          }
        },
        {
          type: "text",
          interactive: false,
          from: { data: "companyPoints" },
          encode: {
            enter: {
              text: { field: "datum.company_name" },
              font: { value: "Inter, ui-sans-serif, system-ui, sans-serif" },
              fontSize: { value: 12 },
              fill: { value: chartTheme.colors.labelText },
              opacity: { value: 1 },
              fontWeight: { value: 400 }
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

  function mountCompanyEngagementScatterChart(element, group, index) {
    if (!element) {
      return null;
    }

    if (!globalScope.vegaEmbed) {
      chartUnavailable(element);
      return null;
    }

    let renderToken = 0;
    let isFontReady = !globalScope.document?.fonts?.load;
    let isFontRenderQueued = false;
    const fontReadyPromise = isFontReady
      ? Promise.resolve()
      : Promise.all([
        globalScope.document.fonts.load('400 12px "Inter"'),
        globalScope.document.fonts.load('500 12px "Inter"'),
        globalScope.document.fonts.ready
      ]);

    const render = () => {
      const width = Math.max(220, Math.round(element.clientWidth - 112));

      if (element.__hymetryVegaWidth === width) {
        return;
      }

      element.__hymetryVegaWidth = width;
      renderToken += 1;
      const token = renderToken;
      element.__hymetryVegaRenderToken = token;

      if (element.__hymetryVegaView) {
        element.__hymetryVegaView.finalize();
        element.__hymetryVegaView = null;
      }

      globalScope
        .vegaEmbed(element, createCompanyEngagementScatterSpec(group, { index, width }), {
          actions: false,
          renderer: "canvas"
        })
        .then((result) => {
          if (token !== element.__hymetryVegaRenderToken) {
            result.view.finalize();
            return;
          }

          element.__hymetryVegaView = result.view;
        })
        .catch(() => {
          if (token === element.__hymetryVegaRenderToken) {
            chartUnavailable(element);
          }
        });
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
      element.__hymetryResizeObserver = observer;
    }

    return null;
  }

  function renderCompanyEngagementByPageGroup(data) {
    const container = document.getElementById("company-engagement-page-group-grid");

    if (!container) {
      return;
    }

    const groups = (data.company_engagement_by_page_group || []).slice(0, 8);

    if (!groups.length) {
      container.innerHTML = `<div class="py-8 text-center text-slate-500">No company engagement data found for this period.</div>`;
      return;
    }

    container.innerHTML = groups
      .map(
        (group, index) => `
          <article class="company-engagement-card rounded-lg border border-slate-200 bg-white p-4">
            <h3 class="text-sm font-semibold text-slate-900">${escapeHtml(group.page_group)}</h3>
            <div id="company-engagement-page-group-chart-${index}" class="mt-4 w-full" style="height: 400px;"></div>
          </article>
        `
      )
      .join("");

    groups.forEach((group, index) => {
      mountCompanyEngagementScatterChart(document.getElementById(`company-engagement-page-group-chart-${index}`), group, index);
    });
  }

  function initOverviewPage() {
    const body = document.body;

    if (body.dataset.pagesView !== "overview") {
      return;
    }

    const projectId = body.dataset.projectId || "35590318";
    const data = provider.getMockPagesOverviewData(projectId) || {};
    currentOverviewData = data;
    syncProductAreaPalette(data);

    renderKpiCards(data);
    renderProductAreaSummary(data);
    renderChangeAwareRows(data.change_aware_rows);
    mountOverviewPageSearch();
    mountProductAreaFilter();
    mountPageMetricsSort();
    mountSplitChangeValueWidthSync();
    mountFloatingDeltaTooltips();
    mountPageMetricsStickyHeader();
    renderOverviewTopActionsByPageGroup(data);
    renderCompanyEngagementByPageGroup(data);
    mountOverviewCharts(data);

    document.getElementById("pages-global-search")?.addEventListener("input", () => {
      pageMetricsState.page = 1;
      if (loadPageMetricsTablePage(1)) {
        return;
      }

      renderChangeAwareRows(data.change_aware_rows);
    });
  }

  function getRequestedPageRuleId() {
    const params = new URLSearchParams(globalScope.location.search);
    const queryValue = params.get("page_rule_id");

    if (queryValue) {
      return queryValue;
    }

    const pathSegments = globalScope.location.pathname.split("/").filter(Boolean);
    const pagesIndex = pathSegments.lastIndexOf("pages");

    if (pagesIndex >= 0 && pathSegments[pagesIndex + 1]) {
      return pathSegments[pagesIndex + 1];
    }

    return document.body.dataset.pageRuleId || "";
  }

  function setText(id, value) {
    const element = document.getElementById(id);

    if (element) {
      element.textContent = value;
    }
  }

  function renderSummaryCards(data) {
    const container = document.getElementById("page-summary-cards");

    if (!container) {
      return;
    }

    const cards = [
      { label: "Companies", value: formatNumber(data.companies_count), sub: `${data.adoption_pct}% adopted` },
      { label: "Users", value: formatNumber(data.users_count), sub: `${data.penetration_pct}% penet.` },
      { label: "Visits", value: formatNumber(data.visits_count), sub: "+12%" },
      { label: "Engaged time", value: data.engaged_label, sub: "+8%" },
      { label: "Interaction", value: `${data.interaction_pct}%`, sub: "+5 pp" }
    ];

    container.innerHTML = cards
      .map(
        (card) => `
          <article class="rounded-xl border border-slate-200 bg-white px-5 py-4 shadow-sm">
            <div class="text-sm font-medium text-slate-500">${escapeHtml(card.label)}</div>
            <div class="mt-2 text-2xl font-semibold text-slate-900">${escapeHtml(card.value)}</div>
            <div class="mt-1 text-sm text-slate-500">${escapeHtml(card.sub)}</div>
          </article>
        `
      )
      .join("");
  }

  function renderAdoption(data) {
    const container = document.getElementById("page-adoption");

    if (!container) {
      return;
    }

    container.innerHTML = `
      <div>
        <div class="flex items-center justify-between gap-4">
          <div>
            <div class="font-medium text-slate-900">Companies using this page</div>
            <div class="mt-1 text-sm text-slate-500">${formatNumber(data.companies_count)} of ${formatNumber(data.active_companies_total)} active companies</div>
          </div>
          <div class="text-2xl font-semibold text-slate-900">${data.adoption_pct}%</div>
        </div>
        <div class="mt-3 h-2.5 overflow-hidden rounded-full bg-slate-100">
          <div class="h-full rounded-full bg-sky-500" style="width: ${clampPct(data.adoption_pct)}%"></div>
        </div>
      </div>
      <div class="mt-7">
        <div class="flex items-center justify-between gap-4">
          <div>
            <div class="font-medium text-slate-900">Users in adopted companies</div>
            <div class="mt-1 text-sm text-slate-500">${formatNumber(data.users_count)} of ${formatNumber(data.active_users_in_adopted_companies)} active users</div>
          </div>
          <div class="text-2xl font-semibold text-slate-900">${data.penetration_pct}%</div>
        </div>
        <div class="mt-3 h-2.5 overflow-hidden rounded-full bg-slate-100">
          <div class="h-full rounded-full bg-c-teal" style="width: ${clampPct(data.penetration_pct)}%"></div>
        </div>
      </div>
    `;
  }

  function renderChampions(data) {
    const companies = document.getElementById("champion-companies");
    const users = document.getElementById("champion-users");

    if (companies) {
      companies.innerHTML = data.champions.top_companies
        .map(
          (row, index) => `
            <li class="grid grid-cols-[28px_1fr_auto_auto] items-center gap-3 py-2">
              <span class="text-slate-400">${index + 1}</span>
              <span class="font-medium text-slate-900">${escapeHtml(row.company)}</span>
              <span class="text-slate-600">${escapeHtml(row.engaged)}</span>
              <span class="text-slate-500">${formatNumber(row.visits)} visits</span>
            </li>
          `
        )
        .join("");
    }

    if (users) {
      users.innerHTML = data.champions.top_users
        .map(
          (row, index) => `
            <li class="grid grid-cols-[28px_1fr_110px_auto] items-center gap-3 py-2">
              <span class="text-slate-400">${index + 1}</span>
              <span class="font-medium text-slate-900">${escapeHtml(row.user)}</span>
              <span class="text-slate-500">${escapeHtml(row.company)}</span>
              <span class="text-slate-600">${escapeHtml(row.engaged)}</span>
            </li>
          `
        )
        .join("");
    }
  }

  function renderInteractionSummary(data) {
    const container = document.getElementById("interaction-summary");

    if (!container) {
      return;
    }

    const rows = [
      ["Interaction rate", `${data.interaction_pct}%`],
      ["Clicks per visit", data.clicks_per_visit.toFixed(1)],
      ["Unique elements", formatNumber(data.unique_elements_count)],
      ["Hover activity", `${data.hover_activity_pct}%`],
      ["Mouse activity", `${data.mouse_activity_pct}%`]
    ];

    container.innerHTML = `
      <dl class="space-y-3">
        ${rows
          .map(
            ([label, value]) => `
              <div class="flex items-center justify-between gap-6">
                <dt class="text-slate-500">${escapeHtml(label)}</dt>
                <dd class="font-semibold text-slate-900">${escapeHtml(value)}</dd>
              </div>
            `
          )
          .join("")}
      </dl>
      <div class="mt-6 border-t border-slate-200 pt-4">
        <div class="text-sm font-medium text-slate-500">Most clicked element</div>
        <div class="mt-2 font-semibold text-slate-900">${escapeHtml(data.top_clicked_element)}</div>
        <div class="mt-1 text-sm text-slate-500">${formatNumber(data.top_clicked_element_clicks)} clicks</div>
      </div>
    `;
  }

  function renderClickedElementsTable(data) {
    const tbody = document.getElementById("clicked-elements-table-body");

    if (!tbody) {
      return;
    }

    tbody.innerHTML = data.top_clicked_elements
      .map(
        (row) => `
          <tr>
            <td class="py-3 pl-6 pr-6 font-medium text-slate-900">${escapeHtml(row.element)}</td>
            <td class="py-3 pr-6 text-slate-700">${formatNumber(row.clicks)}</td>
            <td class="py-3 pr-6 text-slate-700">${formatNumber(row.users)}</td>
            <td class="py-3 pr-6 text-slate-700">${formatNumber(row.companies)}</td>
            <td class="py-3 pr-6 text-slate-700">${row.visits_pct}%</td>
          </tr>
        `
      )
      .join("");
  }

  function renderCompaniesTable(data) {
    const tbody = document.getElementById("companies-table-body");

    if (!tbody) {
      return;
    }

    tbody.innerHTML = data.companies
      .map(
        (row) => `
          <tr>
            <td class="py-3 pl-6 pr-6 font-medium text-slate-900">${escapeHtml(row.company)}</td>
            <td class="py-3 pr-6 text-slate-700">${formatNumber(row.users)}</td>
            <td class="py-3 pr-6 text-slate-700">${formatNumber(row.visits)}</td>
            <td class="py-3 pr-6 text-slate-700">${escapeHtml(row.engaged)}</td>
            <td class="py-3 pr-6 text-slate-700">${escapeHtml(row.avg_visit)}</td>
            <td class="py-3 pr-6">${progressCell(`${row.interaction_pct}%`, row.interaction_pct, "bg-c-orange")}</td>
            <td class="py-3 pr-6 text-slate-500 whitespace-nowrap">${escapeHtml(row.last_seen)}</td>
          </tr>
        `
      )
      .join("");
  }

  function renderUsersTable(data) {
    const tbody = document.getElementById("users-table-body");

    if (!tbody) {
      return;
    }

    tbody.innerHTML = data.users
      .map(
        (row) => `
          <tr>
            <td class="py-3 pl-6 pr-6 font-medium text-slate-900">${escapeHtml(row.user)}</td>
            <td class="py-3 pr-6 text-slate-700">${escapeHtml(row.company)}</td>
            <td class="py-3 pr-6 text-slate-700">${formatNumber(row.visits)}</td>
            <td class="py-3 pr-6 text-slate-700">${escapeHtml(row.engaged)}</td>
            <td class="py-3 pr-6 text-slate-700">${formatNumber(row.clicks)}</td>
            <td class="py-3 pr-6 text-slate-500 whitespace-nowrap">${escapeHtml(row.last_seen)}</td>
          </tr>
        `
      )
      .join("");
  }

  function getRequestedPeriodDays() {
    const params = new URLSearchParams(globalScope.location.search);
    const rangeDays = {
      last_7_days: 7,
      last_30_days: 30,
      last_90_days: 90,
      last_180_days: 180
    };
    const rangeKey = params.get("range") || overviewRangeKey;

    return coercePageDetailPeriod(params.get("period") || params.get("days") || rangeDays[rangeKey]);
  }

  function updateDetailPeriodQuery(pageRuleId, periodDays) {
    const params = new URLSearchParams(globalScope.location.search);

    if (globalScope.location.pathname.split("/").filter(Boolean).lastIndexOf("pages") < 0) {
      params.set("page_rule_id", pageRuleId);
    } else {
      params.delete("page_rule_id");
    }
    params.delete("range");
    params.set("period", String(periodDays));
    globalScope.history?.replaceState({}, "", `${globalScope.location.pathname}?${params.toString()}`);
  }

  function detailDeltaClassFromDirection(direction) {
    if (direction === "positive") {
      return "text-green-700";
    }

    if (direction === "negative") {
      return "text-red-600";
    }

    return "text-slate-700";
  }

  function formatDetailDate(value) {
    const date = new Date(value);

    if (Number.isNaN(date.getTime())) {
      return value || "";
    }

    return new Intl.DateTimeFormat("en-US", {
      month: "short",
      day: "numeric"
    }).format(date);
  }

  function formatDetailValueByType(value, valueType) {
    if (value === null || value === undefined || value === "") {
      return "-";
    }

    const numericValue = Number(value) || 0;

    if (valueType === "percent") {
      return `${Math.round(numericValue)}%`;
    }

    if (valueType === "duration") {
      return formatDurationShort(numericValue);
    }

    if (valueType === "ratio") {
      return numericValue.toFixed(1);
    }

    return formatNumber(Math.round(numericValue));
  }

  function renderPeriodSelector(data, onSelectPeriod) {
    const container = document.getElementById("page-period-selector");

    if (!container) {
      return;
    }

    container.innerHTML = pageDetailsPeriodOptions
      .map((days) => {
        const isActive = days === data.period.days;

        return `
          <button
            type="button"
            data-page-period="${days}"
            aria-pressed="${String(isActive)}"
            class="px-3 py-1.5 text-sm font-medium duration-150 ${isActive ? "bg-slate-900 text-white" : "bg-white text-slate-700 hover:bg-slate-50"}">
            ${days}d
          </button>
        `;
      })
      .join("");

    container.querySelectorAll("[data-page-period]").forEach((button) => {
      button.addEventListener("click", () => {
        const periodDays = coercePageDetailPeriod(button.getAttribute("data-page-period"));

        onSelectPeriod(periodDays, { allowRedirect: true });
      });
    });
  }

  function renderPageDetailsHeader(data) {
    const page = data.page || {};
    const title = page.displayName || page.pageName || page.pageRuleId || page.route || "Page";
    const titleNameElement = document.getElementById("detail-title-page-name");
    const selectorButton = document.getElementById("page-detail-page-selector-button");

    if (titleNameElement) {
      titleNameElement.textContent = title;
      selectorButton?.setAttribute("aria-label", `Switch page from ${title}`);
    } else {
      setText("detail-title", title);
    }
    setText("detail-subtitle", "See how this page is used over time and how it compares with related pages.");

    document.title = `${title} - Page details`;
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

    return formatDetailValueByType(value, valueType);
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

  function pageMetricDynamicsShowPeers() {
    const section = document.querySelector("[data-page-metric-dynamics-section]");
    if (section?.dataset.pageMetricDynamicsShowPeers !== undefined) {
      return section.dataset.pageMetricDynamicsShowPeers === "true";
    }

    return pageMetricDynamicsState.showPeers;
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
      currentEntityId: metric.pageId || metric.pageRuleId || metric.id,
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
              <div style="font-weight:600;margin-bottom:6px;">${escapeHtml(formatDetailDate(dates[index]))}</div>
              ${metricTooltipRow("Actual", actualValue, metric.valueType, { color: chartTheme.colors.primary })}
              ${Number.isFinite(trendValue) ? metricTooltipRow("Current trend", trendValue, metric.valueType, { color: chartTheme.colors.primary, dashed: true }) : ""}
              ${Number.isFinite(benchmarkValue) ? metricTooltipRow("Other pages trend", benchmarkValue, metric.valueType, { color: chartTheme.colors.warning, dashed: true }) : ""}
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
          name: "Other pages trend",
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

  function createCombinedInteractionClicksOption(combinedMetric, options = {}) {
    const interaction = combinedMetric.interaction || {};

    return createMiniMetricChartOption({
      ...interaction,
      key: interaction.key || "interaction",
      label: interaction.label || "Interaction",
      valueType: interaction.valueType || "percent"
    }, options);
  }

  const pageMetricDynamicsDescriptions = {
    companies: "Number of companies that used this page during the selected period",
    adoption: "Share of active companies that used this page during the selected period",
    users: "Number of users who used this page during the selected period",
    penetration: "Share of active users from adopted companies who used this page",
    visits: "Number of page visits during the selected period",
    engaged: "Total active time spent on this page",
    avg_visit: "Average active time per page visit",
    interaction: "Share of visits with at least one click",
    clicks_per_visit: "Average number of clicks per page visit"
  };

  function metricDynamicsTooltipId(scope, key, index) {
    return `${scope}-metric-dynamics-title-${String(key || index).replace(/[^a-z0-9_-]+/gi, "-").toLowerCase()}`;
  }

  function metricDynamicsTitleMarkup(metric, scope, index, fallbackKey = "") {
    const key = metric?.key || fallbackKey || index;
    const label = metric?.label || "Metric";
    const description = pageMetricDynamicsDescriptions[key] || pageMetricDynamicsDescriptions[fallbackKey] || "Metric value during the selected period";
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
          <div class="min-w-0 text-sm font-medium uppercase text-slate-500">${metricDynamicsTitleMarkup(metric, "page", index)}</div>
          <div class="flex shrink-0 items-center gap-2 text-right font-medium">
            <div class="whitespace-nowrap text-base font-semibold text-slate-900">${escapeHtml(metric.formattedValue)}</div>
            <div class="whitespace-nowrap text-sm font-medium ${detailDeltaClassFromDirection(metric.deltaDirection)}">${escapeHtml(metric.formattedDelta)}</div>
          </div>
        </div>
        <div data-page-metric-chart-index="${index}" class="mt-3 h-[92px] w-full"></div>
      </article>
    `;
  }

  function combinedMetricPanelMarkup(combinedMetric, index) {
    const interaction = combinedMetric.interaction || {};
    const clicksPerVisit = combinedMetric.clicksPerVisit || {};

    return `
      <article class="min-h-[164px] bg-white px-5 py-4">
        <div class="flex items-center justify-between gap-3">
          <div class="min-w-0 text-sm font-medium uppercase text-slate-500">${metricDynamicsTitleMarkup({ ...interaction, label: "Interaction", key: "interaction" }, "page-combined", index, "interaction")}</div>
          <div class="flex shrink-0 items-center gap-2 text-right font-medium">
            <span class="whitespace-nowrap text-base font-semibold text-slate-900">${escapeHtml(interaction.formattedValue || "-")}</span>
            <span class="whitespace-nowrap text-sm text-slate-700">${escapeHtml(interaction.formattedDelta || "-")}</span>
          </div>
        </div>
        <div data-page-combined-metric-chart-index="${index}" class="mt-3 h-[92px] w-full"></div>
      </article>
    `;
  }

  function pageMetricDynamicsElements() {
    const grid = document.getElementById("page-metric-dynamics-grid");

    return {
      shell: document.querySelector("[data-page-metric-dynamics-shell]"),
      grid,
      overlay: document.querySelector("[data-page-metric-dynamics-loading]"),
      toggle: document.querySelector("[data-page-metric-dynamics-show-peers]")
    };
  }

  function setPageMetricDynamicsLoading(isLoading) {
    pageMetricDynamicsState.isLoading = Boolean(isLoading);
    setMetricDynamicsLoadingState(pageMetricDynamicsElements(), pageMetricDynamicsState.isLoading);
  }

  function mountPageMetricDynamicsToggle() {
    const { toggle } = pageMetricDynamicsElements();

    if (!toggle) {
      return;
    }

    pageMetricDynamicsState.showPeers = pageMetricDynamicsShowPeers();
    toggle.checked = pageMetricDynamicsState.showPeers;
    toggle.disabled = pageMetricDynamicsState.isLoading;

    if (toggle.dataset.metricDynamicsMounted === "true") {
      return;
    }

    toggle.dataset.metricDynamicsMounted = "true";
    toggle.addEventListener("change", () => {
      const nextShowPeers = toggle.checked;
      pageMetricDynamicsState.showPeers = nextShowPeers;

      try {
        globalScope.localStorage?.setItem("hymetry.page_details.show_peers", nextShowPeers ? "1" : "0");
      } catch (error) {
        // Local storage is optional; the server-rendered HTMX state remains authoritative.
      }

      if (globalScope.htmx) {
        return;
      }

      const token = pageMetricDynamicsState.loadingToken + 1;
      const section = document.querySelector("[data-page-metric-dynamics-section]");
      pageMetricDynamicsState.loadingToken = token;
      if (section?.dataset) {
        section.dataset.pageMetricDynamicsShowPeers = String(nextShowPeers);
      }

      setPageMetricDynamicsLoading(true);

      globalScope.setTimeout(() => {
        if (token !== pageMetricDynamicsState.loadingToken) {
          return;
        }

        setPageMetricDynamicsLoading(false);

        if (currentPageDetailsData) {
          renderPageMetricDynamics(currentPageDetailsData);
        }
      }, 380);
    });
  }

  function renderPageMetricDynamics(data) {
    const container = document.getElementById("page-metric-dynamics-grid");

    if (!container) {
      return;
    }

    mountPageMetricDynamicsToggle();

    const metrics = Array.isArray(data.metrics) ? data.metrics : [];
    const chartOptions = {
      selectedPeriodDays: data.period?.days,
      showPeers: pageMetricDynamicsShowPeers()
    };

    if (!metrics.length) {
      container.innerHTML = `<div class="col-span-full bg-white px-6 py-10 text-center text-slate-500">No page metrics found for this period.</div>`;
      return;
    }

    container.innerHTML = metrics.map(metricPanelMarkup).join("") + combinedMetricPanelMarkup(data.combinedInteractionClicksMetric || {}, 0);

    metrics.forEach((metric, index) => {
      mountChart(container.querySelector(`[data-page-metric-chart-index="${index}"]`), createMiniMetricChartOption(metric, chartOptions));
    });

    mountChart(container.querySelector("[data-page-combined-metric-chart-index]"), createCombinedInteractionClicksOption(data.combinedInteractionClicksMetric || {}, chartOptions));
  }

  function emptyTableRow(colspan, message) {
    return `
      <tr>
        <td colspan="${colspan}" class="px-6 py-10 text-center text-slate-500">${escapeHtml(message)}</td>
      </tr>
    `;
  }

  const detailMetricsWithoutDelta = new Set(["avg_visit", "clicks_per_visit"]);

  const relatedPagesMetrics = [
    { key: "companies", label: "Companies", valueType: "count", deltaUnit: "%", value: (row) => row.companies, delta: (row) => row.companiesChange },
    { key: "adoption", label: "Adoption", valueType: "percent", deltaUnit: "pp", value: (row) => row.adoption, delta: (row) => row.adoptionChange, barMode: "percent" },
    { key: "users", label: "Users", valueType: "count", deltaUnit: "%", value: (row) => row.users, delta: (row) => row.usersChange },
    { key: "visits", label: "Visits", valueType: "count", deltaUnit: "%", value: (row) => row.visits, delta: (row) => row.visitsChange },
    { key: "engaged", label: "Engaged", valueType: "duration", deltaUnit: "%", value: (row) => row.engaged, delta: (row) => row.engagedChange, displayLabel: (row) => row.engagedLabel },
    { key: "interaction", label: "Interaction", valueType: "percent", deltaUnit: "pp", value: (row) => row.interaction, delta: (row) => row.interactionChange, barMode: "percent" }
  ];

  const pageChampionMetrics = [
    { key: "engaged", label: "Engaged", valueType: "duration", deltaUnit: "%", value: (row) => row.engagedSeconds, delta: (row) => row.engagedChange, displayLabel: (row) => row.engaged },
    { key: "visits", label: "Visits", valueType: "count", deltaUnit: "%", value: (row) => row.visits, delta: (row) => row.visitsChange },
    { key: "avg_visit", label: "Avg / visit", valueType: "duration", showDelta: false, value: (row) => row.engagedSeconds / Math.max(Number(row.visits) || 1, 1), displayLabel: (row) => row.avgVisit },
    { key: "clicks", label: "Clicks", valueType: "count", deltaUnit: "%", value: (row) => row.clicks, delta: (row) => row.clicksChange }
  ];

  const pageCompanyMetrics = [
    { key: "users", label: "Users", valueType: "count", deltaUnit: "%", value: (row) => row.users, delta: (row) => row.usersChange },
    { key: "page_penetration", label: "Page penetration", valueType: "percent", deltaUnit: "pp", value: (row) => row.pagePenetration, delta: (row) => row.pagePenetrationChange, barMode: "percent" },
    { key: "visits", label: "Visits", valueType: "count", deltaUnit: "%", value: (row) => row.visits, delta: (row) => row.visitsChange },
    { key: "engaged", label: "Engaged", valueType: "duration", deltaUnit: "%", value: (row) => row.engagedSeconds, delta: (row) => row.engagedChange, displayLabel: (row) => row.engaged },
    { key: "avg_user", label: "Avg / user", valueType: "duration", deltaUnit: "%", value: (row) => row.engagedSeconds / Math.max(Number(row.users) || 1, 1), delta: (row) => row.avgUserChange, displayLabel: (row) => row.avgUser },
    { key: "interaction", label: "Interaction", valueType: "percent", deltaUnit: "pp", value: (row) => row.interaction, delta: (row) => row.interactionChange, barMode: "percent" }
  ];

  const pageCompaniesDefaultSortDirections = {
    company: "asc",
    users: "desc",
    page_penetration: "desc",
    visits: "desc",
    engaged: "desc",
    avg_user: "desc",
    interaction: "desc"
  };

  const pageChampionsDefaultSortDirections = {
    user: "asc",
    company: "asc",
    engaged: "desc",
    visits: "desc",
    avg_visit: "desc",
    clicks: "desc"
  };

  const pageActionMetrics = [
    { key: "clicks", label: "Clicks", valueType: "count", deltaUnit: "%", value: (row) => row.clicks, delta: (row) => row.clicksChange },
    { key: "visits_pct", label: "% visits", valueType: "percent", deltaUnit: "pp", value: (row) => row.visitsPct, delta: (row) => row.visitsPctChange, barMode: "percent" },
    { key: "users", label: "Users", valueType: "count", deltaUnit: "%", value: (row) => row.users, delta: (row) => row.usersChange },
    { key: "companies", label: "Companies", valueType: "count", deltaUnit: "%", value: (row) => row.companies, delta: (row) => row.companiesChange }
  ];

  function shouldShowDetailMetricDelta(metric) {
    return metric.showDelta !== false && !detailMetricsWithoutDelta.has(metric.key);
  }

  function getDetailTableMetricScales(rows, metrics) {
    return metrics.reduce((lookup, metric) => {
      const values = rows.map((row) => Math.abs(Number(metric.value(row)) || 0));

      lookup[metric.key] = Math.max(...values, 1);
      return lookup;
    }, {});
  }

  function getDetailTableDeltaScales(rows, metrics) {
    return metrics.reduce((lookup, metric) => {
      if (!shouldShowDetailMetricDelta(metric)) {
        return lookup;
      }

      const values = rows.map((row) => comparisonAvailable(row) ? Math.abs(Number(metric.delta?.(row)) || 0) : 0);

      lookup[metric.key] = Math.max(...values, 1);
      return lookup;
    }, {});
  }

  function getDetailMetricDisplay(row, metric, maxValue) {
    const currentValue = Number(metric.value(row)) || 0;
    const barValue = metric.barMode === "percent" ? currentValue : (currentValue / Math.max(maxValue, 1)) * 100;
    const valueLabel = metric.displayLabel ? metric.displayLabel(row, currentValue) : formatDetailValueByType(currentValue, metric.valueType);
    const hasComparison = comparisonAvailable(row);

    return {
      valueLabel,
      currentValue,
      deltaValue: shouldShowDetailMetricDelta(metric) ? (hasComparison ? Number(metric.delta?.(row)) || 0 : 0) : null,
      deltaUnit: metric.deltaUnit || "%",
      barValue,
      comparisonAvailable: hasComparison
    };
  }

  function renderDetailMetricValue(display, metric) {
    return `
      <div class="pages-metric-value">
        ${renderMetricBarValue(display, metric)}
      </div>
    `;
  }

  function formatDetailTooltipValue(value, valueType) {
    return formatDetailValueByType(value, valueType);
  }

  function renderDetailDelta(display, metric, maxAbsDelta) {
    if (display.deltaValue === null || display.deltaValue === undefined) {
      return "";
    }

    if (display.comparisonAvailable === false) {
      const tooltipId = `detail-period-change-tooltip-${periodChangeTooltipId}`;
      const tooltipRows = [
        `Current period: ${display.valueLabel}`,
        "Previous period: no data",
        "Change: n/a"
      ];

      periodChangeTooltipId += 1;

      return `
        <div class="pages-change-delta metric-header-tooltip" data-change-direction="neutral" style="--pages-change-bar-width: 6px;" tabindex="0" aria-label="${escapeHtml(`${metric.label}. ${tooltipRows.join(" ")}`)}" aria-describedby="${tooltipId}">
          <span class="pages-change-delta__plot">
            <span class="pages-change-delta__bar pages-change-delta__bar--neutral"></span>
          </span>
          <span class="pages-change-delta__label text-slate-500">n/a</span>
          <span id="${tooltipId}" class="metric-header-tooltip__content" role="tooltip">${tooltipRows.map((line) => `<span class="pages-change-delta__tooltip-row">${escapeHtml(line)}</span>`).join("")}</span>
        </div>
      `;
    }

    const deltaValue = Number(display.deltaValue) || 0;
    const roundedDelta = roundedDeltaValue(deltaValue);
    const direction = deltaDirection(deltaValue);
    const trackWidth = direction === "negative" ? 17 : 36;
    const barWidth = roundedDelta === 0 ? 6 : Math.max(4, Math.round((Math.abs(deltaValue) / Math.max(maxAbsDelta, 1)) * trackWidth));
    const formattedDelta = formatDelta(deltaValue, display.deltaUnit);
    const previousValue = previousPeriodValue(display.currentValue, deltaValue, display.deltaUnit);
    const tooltipId = `detail-period-change-tooltip-${periodChangeTooltipId}`;
    const tooltipRows = [
      `Current period: ${display.valueLabel}`,
      `Previous period: ${formatDetailTooltipValue(previousValue, metric.valueType)}`,
      `Change: ${formattedDelta}`
    ];

    periodChangeTooltipId += 1;

    return `
      <div class="pages-change-delta metric-header-tooltip" data-change-direction="${direction}" style="--pages-change-bar-width: ${barWidth}px;" tabindex="0" aria-label="${escapeHtml(`${metric.label}. ${tooltipRows.join(" ")}`)}" aria-describedby="${tooltipId}">
        <span class="pages-change-delta__plot">
          <span class="pages-change-delta__bar pages-change-delta__bar--${direction}"></span>
        </span>
        <span class="pages-change-delta__label ${deltaTextClass(deltaValue)}">${escapeHtml(formattedDelta)}</span>
        <span id="${tooltipId}" class="metric-header-tooltip__content" role="tooltip">${tooltipRows.map((line) => `<span class="pages-change-delta__tooltip-row">${escapeHtml(line)}</span>`).join("")}</span>
      </div>
    `;
  }

  function renderDetailMetricCell(row, metric, maxValue, maxAbsDelta) {
    const display = getDetailMetricDisplay(row, metric, maxValue);

    if (!shouldShowDetailMetricDelta(metric)) {
      return `
        <td class="cursor-default py-3.5 align-middle" data-split-metric="${escapeHtml(metric.key)}">
          ${renderDetailMetricValue(display, metric)}
        </td>
      `;
    }

    return `
      <td class="pages-split-change-cell cursor-default py-3.5 align-middle" data-split-metric="${escapeHtml(metric.key)}">
        <div class="pages-split-change-group">
          ${renderDetailMetricValue(display, metric)}
          ${renderDetailDelta(display, metric, maxAbsDelta)}
        </div>
      </td>
    `;
  }

  function renderDetailMetricCells(row, metrics, metricScales, deltaScales) {
    return metrics
      .map((metric) => renderDetailMetricCell(row, metric, metricScales[metric.key], deltaScales[metric.key]))
      .join("");
  }

  function renderRelatedPagesCard(data) {
    const card = document.getElementById("related-pages-card");
    const tbody = document.getElementById("related-pages-table-body");
    const rows = Array.isArray(data.relatedPages) ? data.relatedPages : [];

    if (!card || !tbody) {
      return;
    }

    if (!shouldShowRelatedPages(rows, data.page?.id)) {
      card.classList.add("hidden");
      tbody.innerHTML = "";
      return;
    }

    const metricScales = getDetailTableMetricScales(rows, relatedPagesMetrics);
    const deltaScales = getDetailTableDeltaScales(rows, relatedPagesMetrics);

    card.classList.remove("hidden");
    tbody.innerHTML = rows
      .map((row) => {
        const href = detailHref(row.pageId || row.page_rule_id, data.period.days);
        const rowClass = row.isCurrent ? "bg-sky-50 text-slate-900" : "hover:bg-slate-50";

        return `
          <tr class="group align-middle ${rowClass}">
            <td class="py-3 pl-0 pr-6 font-medium">
              <a href="${href}" class="text-sky-800 underline-offset-2 hover:underline"${row.isCurrent ? ' aria-current="page"' : ""}>${escapeHtml(row.pageName || row.route)}</a>
            </td>
            ${renderDetailMetricCells(row, relatedPagesMetrics, metricScales, deltaScales)}
          </tr>
        `;
      })
      .join("");

    syncSplitChangeValueWidths(tbody);
  }

  function pageDetailDefaultSortDirection(sortKey, defaultDirections) {
    return defaultDirections[sortKey] || "desc";
  }

  function comparePageDetailTableRows(a, b, sortKey, sortDirection, metrics, textValueByKey, fallbackKey) {
    const textValue = textValueByKey[sortKey];
    const direction = sortDirection === "asc" ? 1 : -1;
    let comparison = 0;

    if (textValue) {
      comparison = String(textValue(a) || "").localeCompare(String(textValue(b) || ""));
    } else {
      const metric = metrics.find((item) => item.key === sortKey);

      if (metric) {
        comparison = (Number(metric.value(a)) || 0) - (Number(metric.value(b)) || 0);
      }
    }

    return comparison * direction || String(a[fallbackKey] || "").localeCompare(String(b[fallbackKey] || ""));
  }

  function comparePageChampionsByCurrentSort(a, b) {
    return comparePageDetailTableRows(
      a,
      b,
      pageChampionsState.sortKey,
      pageChampionsState.sortDirection,
      pageChampionMetrics,
      {
        user: (row) => row.user,
        company: (row) => row.company
      },
      "user"
    );
  }

  function comparePageCompaniesByCurrentSort(a, b) {
    return comparePageDetailTableRows(
      a,
      b,
      pageCompaniesState.sortKey,
      pageCompaniesState.sortDirection,
      pageCompanyMetrics,
      {
        company: (row) => row.company
      },
      "company"
    );
  }

  function pageChampionsRows(data) {
    return (Array.isArray(data?.champions) ? data.champions : []).slice().sort(comparePageChampionsByCurrentSort);
  }

  function pageCompaniesRows(data) {
    return (Array.isArray(data?.companies) ? data.companies : []).slice().sort(comparePageCompaniesByCurrentSort);
  }

  function updatePageDetailSortButtons(selector, sortKeyAttribute, state) {
    document.querySelectorAll(selector).forEach((button) => {
      const isActive = button.getAttribute(sortKeyAttribute) === state.sortKey;

      button.setAttribute("data-sort-direction", isActive ? state.sortDirection : "");
      button.setAttribute("aria-pressed", String(isActive));
    });
    mountDetailStickyTableHeaders();
  }

  function updatePageChampionsSortButtons() {
    updatePageDetailSortButtons("[data-page-champions-sort]", "data-page-champions-sort", pageChampionsState);
  }

  function updatePageCompaniesSortButtons() {
    updatePageDetailSortButtons("[data-page-companies-sort]", "data-page-companies-sort", pageCompaniesState);
  }

  function mountPageDetailPaginatedTableSort() {
    if (detailPaginatedTableSortMounted) {
      return;
    }

    detailPaginatedTableSortMounted = true;

    document.querySelectorAll("[data-page-champions-sort]").forEach((button) => {
      button.addEventListener("click", () => {
        const sortKey = button.getAttribute("data-page-champions-sort") || "engaged";

        if (!currentPageDetailsData || pageChampionsState.isLoading) {
          return;
        }

        if (pageChampionsState.sortKey === sortKey) {
          pageChampionsState.sortDirection = pageChampionsState.sortDirection === "asc" ? "desc" : "asc";
        } else {
          pageChampionsState.sortKey = sortKey;
          pageChampionsState.sortDirection = pageDetailDefaultSortDirection(sortKey, pageChampionsDefaultSortDirections);
        }

        pageChampionsState.page = 1;
        updatePageChampionsSortButtons();
        if (loadPageChampionsTablePage(1)) {
          return;
        }

        simulatePageChampionsLoad(() => {
          renderPageChampionsTable(currentPageDetailsData);
        });
      });
    });

    document.querySelectorAll("[data-page-companies-sort]").forEach((button) => {
      button.addEventListener("click", () => {
        const sortKey = button.getAttribute("data-page-companies-sort") || "engaged";

        if (!currentPageDetailsData || pageCompaniesState.isLoading) {
          return;
        }

        if (pageCompaniesState.sortKey === sortKey) {
          pageCompaniesState.sortDirection = pageCompaniesState.sortDirection === "asc" ? "desc" : "asc";
        } else {
          pageCompaniesState.sortKey = sortKey;
          pageCompaniesState.sortDirection = pageDetailDefaultSortDirection(sortKey, pageCompaniesDefaultSortDirections);
        }

        pageCompaniesState.page = 1;
        updatePageCompaniesSortButtons();
        if (loadPageCompaniesTablePage(1)) {
          return;
        }

        simulatePageCompaniesLoad(() => {
          renderPageCompaniesTable(currentPageDetailsData);
        });
      });
    });
  }

  function getPageChampionsPageCount(rows) {
    return tablePageCount(currentPageDetailsData, "champions", rows, pageChampionsPageSize);
  }

  function pageDetailPaginationIcon(direction) {
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

  function renderPageChampionsPagination(totalPages) {
    const container = document.querySelector("[data-page-champions-pagination]");

    if (!container) {
      return;
    }

    if (totalPages <= 1) {
      container.hidden = true;
      container.innerHTML = "";
      return;
    }

    const currentPage = Math.min(totalPages, Math.max(1, pageChampionsState.page));
    const disabledAttr = pageChampionsState.isLoading ? " disabled" : "";

    container.hidden = false;
    container.innerHTML = `
      ${
        currentPage > 2
          ? `<button type="button" class="font-medium text-sky-700 hover:text-sky-800" data-page-champions-page-action="first"${disabledAttr}>Go to first page</button>`
          : `<span aria-hidden="true"></span>`
      }
      <div class="flex items-center justify-between gap-6 sm:justify-end">
        ${
          currentPage > 1
            ? `<button type="button" class="inline-flex h-8 w-8 items-center justify-center text-sky-700 hover:text-sky-800" data-page-champions-page-action="previous" aria-label="Back to previous page"${disabledAttr}>${pageDetailPaginationIcon("previous")}</button>`
            : `<span class="invisible h-8 w-8" aria-hidden="true"></span>`
        }
        <span class="text-slate-700">Page ${currentPage}/${totalPages}</span>
        ${
          currentPage < totalPages
            ? `<button type="button" class="inline-flex items-center gap-2 rounded-md border border-slate-200 bg-transparent px-4 py-3 font-medium text-sky-700 duration-150 hover:bg-slate-100" data-page-champions-page-action="next"${disabledAttr}>Continue to next page ${pageDetailPaginationIcon("next")}</button>`
            : ""
        }
      </div>
    `;

    container.querySelectorAll("[data-page-champions-page-action]").forEach((button) => {
      button.addEventListener("click", () => {
        const action = button.getAttribute("data-page-champions-page-action");
        const targetPage =
          action === "first"
            ? 1
            : action === "previous"
              ? Math.max(1, pageChampionsState.page - 1)
              : Math.min(totalPages, pageChampionsState.page + 1);

        requestPageChampionsPage(targetPage);
      });
    });
  }

  function setPageDetailTableLoading(selector, tableSelector, isLoading) {
    const overlay = document.querySelector(selector);
    const tableShell = document.querySelector(tableSelector);
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

  function isPageDetailTableHeaderVisible(tableSelector) {
    const tableHead = document.querySelector(`${tableSelector} thead`);

    if (!tableHead) {
      return true;
    }

    const stickyTop = document.querySelector("body > nav")?.getBoundingClientRect().height || 48;
    const rect = tableHead.getBoundingClientRect();

    return rect.top >= stickyTop && rect.bottom <= globalScope.innerHeight;
  }

  function scrollPageDetailTableHeaderIntoView(tableSelector) {
    const tableHead = document.querySelector(`${tableSelector} thead`);

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

  function simulatePageChampionsLoad(onComplete) {
    if (pageChampionsState.isLoading) {
      return;
    }

    pageChampionsState.isLoading = true;
    pageChampionsState.loadingToken += 1;

    const token = pageChampionsState.loadingToken;
    const rows = currentPageDetailsData ? pageChampionsRows(currentPageDetailsData) : [];

    setPageDetailTableLoading("[data-page-champions-table-loading]", "[data-page-champions-table-scroll]", true);
    renderPageChampionsPagination(getPageChampionsPageCount(rows));

    if (!isPageDetailTableHeaderVisible("[data-page-champions-table-scroll]")) {
      scrollPageDetailTableHeaderIntoView("[data-page-champions-table-scroll]");
    }

    globalScope.setTimeout(() => {
      if (token !== pageChampionsState.loadingToken) {
        return;
      }

      onComplete();
      pageChampionsState.isLoading = false;
      setPageDetailTableLoading("[data-page-champions-table-loading]", "[data-page-champions-table-scroll]", false);
      renderPageChampionsPagination(getPageChampionsPageCount(currentPageDetailsData ? pageChampionsRows(currentPageDetailsData) : []));
    }, 350);
  }

  function loadPageChampionsTablePage(targetPage) {
    if (typeof provider.loadPageDetailTable !== "function" || !currentPageDetailsData || pageChampionsState.isLoading) {
      return false;
    }

    pageChampionsState.isLoading = true;
    pageChampionsState.loadingToken += 1;

    const token = pageChampionsState.loadingToken;

    setPageDetailTableLoading("[data-page-champions-table-loading]", "[data-page-champions-table-scroll]", true);
    renderPageChampionsPagination(getPageChampionsPageCount(currentPageDetailsData ? pageChampionsRows(currentPageDetailsData) : []));

    if (!isPageDetailTableHeaderVisible("[data-page-champions-table-scroll]")) {
      scrollPageDetailTableHeaderIntoView("[data-page-champions-table-scroll]");
    }

    provider.loadPageDetailTable("champions", {
      page: targetPage,
      page_size: pageChampionsPageSize,
      sort: pageChampionsState.sortKey,
      direction: pageChampionsState.sortDirection
    }).then((payload) => {
      if (token !== pageChampionsState.loadingToken) {
        return;
      }

      if (applyTablePayload(currentPageDetailsData, "champions", "champions", payload, pageChampionsState)) {
        renderPageChampionsTable(currentPageDetailsData);
      }
    }).finally(() => {
      if (token !== pageChampionsState.loadingToken) {
        return;
      }

      pageChampionsState.isLoading = false;
      setPageDetailTableLoading("[data-page-champions-table-loading]", "[data-page-champions-table-scroll]", false);
      renderPageChampionsPagination(getPageChampionsPageCount(currentPageDetailsData ? pageChampionsRows(currentPageDetailsData) : []));
    });

    return true;
  }

  function requestPageChampionsPage(targetPage) {
    if (!currentPageDetailsData || pageChampionsState.isLoading || targetPage === pageChampionsState.page) {
      return;
    }

    if (loadPageChampionsTablePage(targetPage)) {
      return;
    }

    simulatePageChampionsLoad(() => {
      pageChampionsState.page = targetPage;
      renderPageChampionsTable(currentPageDetailsData);
    });
  }

  function renderPageChampionsTable(data) {
    const tbody = document.getElementById("page-champions-table-body");
    const rows = pageChampionsRows(data);

    if (!tbody) {
      return;
    }

    const totalPages = getPageChampionsPageCount(rows);

    pageChampionsState.page = Math.min(totalPages, Math.max(1, pageChampionsState.page));
    updatePageChampionsSortButtons();
    renderPageChampionsPagination(totalPages);

    if (!rows.length) {
      tbody.innerHTML = emptyTableRow(6, "No users visited this page during this period.");
      renderPageChampionsPagination(1);
      return;
    }

    const pageRows = tableRowsForRender(data, "champions", rows, pageChampionsState, pageChampionsPageSize);
    const metricScales = getDetailTableMetricScales(rows, pageChampionMetrics);
    const deltaScales = getDetailTableDeltaScales(rows, pageChampionMetrics);

    tbody.innerHTML = pageRows
      .map((row) => `
        <tr class="align-middle hover:bg-slate-50">
          <td class="py-3 pl-0 pr-6">${userDetailLink(row, row.user || `User ${String(row.id || "").slice(-6)}`)}</td>
          <td class="py-3 pr-6 text-slate-700">${companyDetailLink(row, row.company || "-")}</td>
          ${renderDetailMetricCells(row, pageChampionMetrics, metricScales, deltaScales)}
        </tr>
      `)
      .join("");

    syncSplitChangeValueWidths(tbody);
  }

  function getPageCompaniesPageCount(rows) {
    return tablePageCount(currentPageDetailsData, "companies", rows, pageCompaniesPageSize);
  }

  function renderPageCompaniesPagination(totalPages) {
    const container = document.querySelector("[data-page-companies-pagination]");

    if (!container) {
      return;
    }

    if (totalPages <= 1) {
      container.hidden = true;
      container.innerHTML = "";
      return;
    }

    const currentPage = Math.min(totalPages, Math.max(1, pageCompaniesState.page));
    const disabledAttr = pageCompaniesState.isLoading ? " disabled" : "";

    container.hidden = false;
    container.innerHTML = `
      ${
        currentPage > 2
          ? `<button type="button" class="font-medium text-sky-700 hover:text-sky-800" data-page-companies-page-action="first"${disabledAttr}>Go to first page</button>`
          : `<span aria-hidden="true"></span>`
      }
      <div class="flex items-center justify-between gap-6 sm:justify-end">
        ${
          currentPage > 1
            ? `<button type="button" class="inline-flex h-8 w-8 items-center justify-center text-sky-700 hover:text-sky-800" data-page-companies-page-action="previous" aria-label="Back to previous page"${disabledAttr}>${pageDetailPaginationIcon("previous")}</button>`
            : `<span class="invisible h-8 w-8" aria-hidden="true"></span>`
        }
        <span class="text-slate-700">Page ${currentPage}/${totalPages}</span>
        ${
          currentPage < totalPages
            ? `<button type="button" class="inline-flex items-center gap-2 rounded-md border border-slate-200 bg-transparent px-4 py-3 font-medium text-sky-700 duration-150 hover:bg-slate-100" data-page-companies-page-action="next"${disabledAttr}>Continue to next page ${pageDetailPaginationIcon("next")}</button>`
            : ""
        }
      </div>
    `;

    container.querySelectorAll("[data-page-companies-page-action]").forEach((button) => {
      button.addEventListener("click", () => {
        const action = button.getAttribute("data-page-companies-page-action");
        const targetPage =
          action === "first"
            ? 1
            : action === "previous"
              ? Math.max(1, pageCompaniesState.page - 1)
              : Math.min(totalPages, pageCompaniesState.page + 1);

        requestPageCompaniesPage(targetPage);
      });
    });
  }

  function simulatePageCompaniesLoad(onComplete) {
    if (pageCompaniesState.isLoading) {
      return;
    }

    pageCompaniesState.isLoading = true;
    pageCompaniesState.loadingToken += 1;

    const token = pageCompaniesState.loadingToken;
    const rows = currentPageDetailsData ? pageCompaniesRows(currentPageDetailsData) : [];

    setPageDetailTableLoading("[data-page-companies-table-loading]", "[data-page-companies-table-scroll]", true);
    renderPageCompaniesPagination(getPageCompaniesPageCount(rows));

    if (!isPageDetailTableHeaderVisible("[data-page-companies-table-scroll]")) {
      scrollPageDetailTableHeaderIntoView("[data-page-companies-table-scroll]");
    }

    globalScope.setTimeout(() => {
      if (token !== pageCompaniesState.loadingToken) {
        return;
      }

      onComplete();
      pageCompaniesState.isLoading = false;
      setPageDetailTableLoading("[data-page-companies-table-loading]", "[data-page-companies-table-scroll]", false);
      renderPageCompaniesPagination(getPageCompaniesPageCount(currentPageDetailsData ? pageCompaniesRows(currentPageDetailsData) : []));
    }, 350);
  }

  function loadPageCompaniesTablePage(targetPage) {
    if (typeof provider.loadPageDetailTable !== "function" || !currentPageDetailsData || pageCompaniesState.isLoading) {
      return false;
    }

    pageCompaniesState.isLoading = true;
    pageCompaniesState.loadingToken += 1;

    const token = pageCompaniesState.loadingToken;

    setPageDetailTableLoading("[data-page-companies-table-loading]", "[data-page-companies-table-scroll]", true);
    renderPageCompaniesPagination(getPageCompaniesPageCount(currentPageDetailsData ? pageCompaniesRows(currentPageDetailsData) : []));

    if (!isPageDetailTableHeaderVisible("[data-page-companies-table-scroll]")) {
      scrollPageDetailTableHeaderIntoView("[data-page-companies-table-scroll]");
    }

    provider.loadPageDetailTable("companies", {
      page: targetPage,
      page_size: pageCompaniesPageSize,
      sort: pageCompaniesState.sortKey,
      direction: pageCompaniesState.sortDirection
    }).then((payload) => {
      if (token !== pageCompaniesState.loadingToken) {
        return;
      }

      if (applyTablePayload(currentPageDetailsData, "companies", "companies", payload, pageCompaniesState)) {
        renderPageCompaniesTable(currentPageDetailsData);
      }
    }).finally(() => {
      if (token !== pageCompaniesState.loadingToken) {
        return;
      }

      pageCompaniesState.isLoading = false;
      setPageDetailTableLoading("[data-page-companies-table-loading]", "[data-page-companies-table-scroll]", false);
      renderPageCompaniesPagination(getPageCompaniesPageCount(currentPageDetailsData ? pageCompaniesRows(currentPageDetailsData) : []));
    });

    return true;
  }

  function requestPageCompaniesPage(targetPage) {
    if (!currentPageDetailsData || pageCompaniesState.isLoading || targetPage === pageCompaniesState.page) {
      return;
    }

    if (loadPageCompaniesTablePage(targetPage)) {
      return;
    }

    simulatePageCompaniesLoad(() => {
      pageCompaniesState.page = targetPage;
      renderPageCompaniesTable(currentPageDetailsData);
    });
  }

  function renderPageCompaniesTable(data) {
    const tbody = document.getElementById("companies-table-body");
    const rows = pageCompaniesRows(data);

    if (!tbody) {
      return;
    }

    const totalPages = getPageCompaniesPageCount(rows);

    pageCompaniesState.page = Math.min(totalPages, Math.max(1, pageCompaniesState.page));
    updatePageCompaniesSortButtons();
    renderPageCompaniesPagination(totalPages);

    if (!rows.length) {
      tbody.innerHTML = emptyTableRow(7, "No companies used this page during this period.");
      renderPageCompaniesPagination(1);
      return;
    }

    const pageRows = tableRowsForRender(data, "companies", rows, pageCompaniesState, pageCompaniesPageSize);
    const metricScales = getDetailTableMetricScales(rows, pageCompanyMetrics);
    const deltaScales = getDetailTableDeltaScales(rows, pageCompanyMetrics);

    tbody.innerHTML = pageRows
      .map((row) => `
        <tr class="align-middle hover:bg-slate-50">
          <td class="py-3 pl-0 pr-6">${companyDetailLink(row, row.company)}</td>
          ${renderDetailMetricCells(row, pageCompanyMetrics, metricScales, deltaScales)}
        </tr>
      `)
      .join("");

    syncSplitChangeValueWidths(tbody);
  }

  function renderSparkline(values, options = {}) {
    const numericValues = Array.isArray(values) ? values.map((value) => Number(value) || 0) : [];

    if (!numericValues.length) {
      return "";
    }

    const width = options.width || 92;
    const height = options.height || 26;
    const min = Math.min(...numericValues);
    const max = Math.max(...numericValues);
    const range = Math.max(max - min, 1);
    const points = numericValues.map((value, index) => {
      const x = numericValues.length === 1 ? width / 2 : (index / (numericValues.length - 1)) * width;
      const y = height - 2 - ((value - min) / range) * (height - 4);

      return `${Number(x.toFixed(2))},${Number(y.toFixed(2))}`;
    });

    return `
      <svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" aria-hidden="true" class="block">
        <polyline points="${points.join(" ")}" fill="none" stroke="${chartTheme.colors.primary}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></polyline>
      </svg>
    `;
  }

  function renderPageActionsTable(data) {
    const tbody = document.getElementById("page-actions-table-body");
    const rows = Array.isArray(data.actions) ? data.actions : [];

    if (!tbody) {
      return;
    }

    if (!rows.length) {
      tbody.innerHTML = emptyTableRow(5, "No actions recorded on this page during this period.");
      return;
    }

    const metricScales = getDetailTableMetricScales(rows, pageActionMetrics);
    const deltaScales = getDetailTableDeltaScales(rows, pageActionMetrics);

    tbody.innerHTML = rows
      .map((row) => `
        <tr class="align-middle hover:bg-slate-50">
          <td class="py-3 pl-0 pr-6 font-medium text-slate-900">${escapeHtml(row.action)}</td>
          ${renderDetailMetricCells(row, pageActionMetrics, metricScales, deltaScales)}
        </tr>
      `)
      .join("");

    syncSplitChangeValueWidths(tbody);
  }

  function getDetailMetricValue(data, metricKey) {
    const metric = (data.metrics || []).find((item) => item.key === metricKey);
    return Number(metric?.value) || 0;
  }

  function normalizeFlowPage(page, fallbackName) {
    const pageName = String(page?.pageName || page?.name || fallbackName || "").trim();

    return {
      pageName,
      visits: Math.max(0, Math.round(Number(page?.visits) || Number(page?.value) || 0)),
      route: page?.route || ""
    };
  }

  function aggregateFlowPages(pages) {
    const byPageName = new Map();

    (pages || []).forEach((page) => {
      const normalizedPage = normalizeFlowPage(page);

      if (!normalizedPage.pageName || normalizedPage.visits <= 0) {
        return;
      }

      const existingPage = byPageName.get(normalizedPage.pageName) || { ...normalizedPage, visits: 0 };
      existingPage.visits += normalizedPage.visits;
      existingPage.route = existingPage.route || normalizedPage.route;
      byPageName.set(normalizedPage.pageName, existingPage);
    });

    return Array.from(byPageName.values())
      .sort((a, b) => b.visits - a.visits)
      .slice(0, 6);
  }

  function createDetailPageFlowOption(data) {
    const flow = data.flow || {};
    const currentPageName = data.page?.displayName || data.page?.pageName || data.page?.id || "Current page";
    const currentVisits = Math.max(
      getDetailMetricValue(data, "visits"),
      ...((flow.previousPages || []).map((page) => Number(page.visits) || 0)),
      ...((flow.nextPages || []).map((page) => Number(page.visits) || 0)),
      0
    );
    const previousPages = aggregateFlowPages(flow.previousPages);
    const nextPages = aggregateFlowPages(flow.nextPages);
    const nodes = [{
      name: "current-page",
      label: currentPageName,
      role: "current",
      value: currentVisits
    }];
    const links = [];

    const addNode = (name, label, role, value) => {
      nodes.push({ name, label, role, value });
    };

    const addLink = (source, target, value, sourceLabel, targetLabel) => {
      const safeValue = Math.max(1, Math.round(Number(value) || 0));
      links.push({ source, target, value: safeValue, sourceLabel, targetLabel });
    };

    previousPages.forEach((page, index) => {
      const nodeName = `previous-${index}`;
      addNode(nodeName, page.pageName, "previous", page.visits);
      addLink(nodeName, "current-page", page.visits, page.pageName, currentPageName);
    });

    nextPages.forEach((page, index) => {
      const nodeName = `next-${index}`;
      addNode(nodeName, page.pageName, "next", page.visits);
      addLink("current-page", nodeName, page.visits, currentPageName, page.pageName);
    });

    const directEntryVisits = currentVisits > 0 ? Math.round(currentVisits * (Number(flow.entryRate) || 0) / 100) : 0;
    if (directEntryVisits > 0) {
      addNode("direct-entry", "Direct entry", "previous", directEntryVisits);
      addLink("direct-entry", "current-page", directEntryVisits, "Direct entry", currentPageName);
    }

    const exitVisits = currentVisits > 0 ? Math.round(currentVisits * (Number(flow.exitRate) || 0) / 100) : 0;
    if (exitVisits > 0) {
      addNode("page-exit", "Exit", "next", exitVisits);
      addLink("current-page", "page-exit", exitVisits, currentPageName, "Exit");
    }

    if (!links.length) {
      return null;
    }

    return {
      tooltip: {
        trigger: "item",
        formatter: (params) => {
          if (params.dataType === "edge") {
            return `${escapeHtml(params.data.sourceLabel || params.data.source)} to ${escapeHtml(params.data.targetLabel || params.data.target)}<br />${formatNumber(params.data.value)} visits`;
          }

          const value = Number(params.data?.value) || 0;
          return `${escapeHtml(params.data?.label || params.name)}<br />${formatNumber(value)} visits`;
        }
      },
      series: [
        {
          type: "sankey",
          data: nodes,
          links,
          nodeAlign: "justify",
          nodeWidth: 18,
          nodeGap: 18,
          draggable: false,
          emphasis: {
            focus: "adjacency"
          },
          label: {
            color: chartTheme.colors.text,
            fontSize: 12,
            lineHeight: 16,
            formatter: (params) => params.data?.label || params.name
          },
          labelLayout: {
            hideOverlap: true
          },
          lineStyle: {
            color: "gradient",
            curveness: 0.5,
            opacity: 0.34
          },
          itemStyle: {
            borderColor: chartTheme.colors.white,
            borderWidth: 1
          },
          levels: [
            { depth: 0, itemStyle: { color: chartTheme.colors.mutedText } },
            { depth: 1, itemStyle: { color: chartTheme.series[0] } },
            { depth: 2, itemStyle: { color: chartTheme.series[1] } }
          ]
        }
      ]
    };
  }

  function renderPageFlow(data) {
    const summary = document.getElementById("page-flow-summary");
    const chartElement = document.getElementById("page-flow-chart");
    const flow = data.flow || {};

    if (summary) {
      const items = [
        ["Entry rate", `${formatNumber(flow.entryRate || 0)}%`],
        ["Exit rate", `${formatNumber(flow.exitRate || 0)}%`],
        ["Most common previous", flow.mostCommonPreviousPage || "-"],
        ["Most common next", flow.mostCommonNextPage || "-"]
      ];

      summary.innerHTML = items
        .map(([label, value]) => `
          <article class="bg-white px-5 py-4">
            <div class="text-sm font-medium uppercase text-slate-500">${escapeHtml(label)}</div>
            <div class="mt-2 truncate text-xl font-semibold text-slate-900">${escapeHtml(value)}</div>
          </article>
        `)
        .join("");
    }

    if (!chartElement) {
      return;
    }

    chartElement.innerHTML = "";
    const pageFlowOption = createDetailPageFlowOption(data);

    if (!pageFlowOption) {
      chartElement.innerHTML = '<div class="flex h-full items-center justify-center rounded-lg bg-slate-50 text-sm text-slate-500">No page flow data found for this period.</div>';
      return;
    }

    try {
      mountChart(chartElement, pageFlowOption);
    } catch (error) {
      console.error("Unable to render page flow chart", error);
      chartElement.innerHTML = '<div class="flex h-full items-center justify-center rounded-lg bg-slate-50 text-sm text-slate-500">Unable to render page flow for this period.</div>';
    }
  }

  function renderPageDetails(data, onSelectPeriod) {
    currentPageDetailsData = data;
    pageCompaniesState.page = 1;
    pageCompaniesState.isLoading = false;
    pageCompaniesState.loadingToken += 1;
    setPageDetailTableLoading("[data-page-companies-table-loading]", "[data-page-companies-table-scroll]", false);
    pageChampionsState.page = 1;
    pageChampionsState.isLoading = false;
    pageChampionsState.loadingToken += 1;
    setPageDetailTableLoading("[data-page-champions-table-loading]", "[data-page-champions-table-scroll]", false);
    renderPageDetailsHeader(data);
    mountDetailPageSelector();
    mountPageDetailPaginatedTableSort();
    renderPeriodSelector(data, onSelectPeriod);
    renderPageMetricDynamics(data);
    renderRelatedPagesCard(data);
    renderPageChampionsTable(data);
    renderPageCompaniesTable(data);
    renderPageActionsTable(data);
    renderPageFlow(data);
  }

  function createHorizontalBarOption(rows, config) {
    const topRows = rows
      .slice()
      .sort((a, b) => config.value(b) - config.value(a))
      .slice(0, config.limit || 6);
    const topValues = topRows.map((row) => config.value(row));

    return {
      color: [config.color || chartTheme.colors.primary],
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "shadow" },
        valueFormatter: (value) => `${formatNumber(value)}${config.suffix || ""}`
      },
      grid: {
        left: 112,
        right: 28,
        top: 12,
        bottom: 28
      },
      xAxis: {
        type: "value",
        max: compactAxisMax(topValues, { headroom: 0.12 }),
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: {
          color: chartTheme.colors.mutedText,
          formatter: `{value}${config.suffix || ""}`
        },
        splitLine: { show: false }
      },
      yAxis: {
        type: "category",
        inverse: true,
        data: topRows.map((row) => row.page_name),
        axisTick: { show: false },
        axisLine: { show: false },
        axisLabel: { color: chartTheme.colors.text }
      },
      series: [
        {
          name: config.name,
          type: "bar",
          barMaxWidth: 16,
          data: topRows.map((row) => config.value(row)),
          itemStyle: {
            borderRadius: [0, 5, 5, 0]
          },
          label: {
            show: true,
            position: "right",
            color: chartTheme.colors.mutedText,
            formatter: (params) => `${formatNumber(params.value)}${config.suffix || ""}`
          }
        }
      ]
    };
  }

  function createEngagedTimeTreemapOption(data) {
    const treemapData = data.engaged_time_treemap || { total_engaged_seconds: 0, nodes: [] };
    const totalEngagedSeconds = treemapData.total_engaged_seconds || 1;
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
      const groupColor = productAreaColor(groupNode);

      return {
        ...groupNode,
        ...treemapNodeStyle(groupColor),
        children: (groupNode.children || []).map((childNode) => ({
          ...childNode,
          ...treemapNodeStyle(groupColor)
        }))
      };
    });

    return {
      tooltip: {
        trigger: "item",
        confine: true,
        formatter: (params) => {
          const node = params.data || {};
          const isGroup = Boolean(node.is_group || node.children?.length);
          const pageGroup = node.page_group || node.name || "Unassigned";
          const share = ((node.engaged_seconds || 0) / totalEngagedSeconds) * 100;

          return `
            <div>
              <div style="font-weight:600;margin-bottom:6px;">${escapeHtml(node.name || params.name)}</div>
              ${
                isGroup
                  ? `<div>Product area / page group: <strong>${escapeHtml(pageGroup)}</strong></div><div>Pages: <strong>${formatNumber(node.page_count || node.children?.length || 0)}</strong></div>`
                  : `<div>Product area / page group: <strong>${escapeHtml(pageGroup)}</strong></div>`
              }
              <div>Engaged time: <strong>${escapeHtml(formatDurationShort(node.engaged_seconds))}</strong></div>
              <div>Visits: <strong>${formatNumber(node.visits_count || 0)}</strong></div>
              <div>Companies: <strong>${formatNumber(node.companies_count || 0)}</strong></div>
              <div>Adoption: <strong>${formatNumber(node.adoption_pct || 0)}%</strong></div>
              <div>Share of time: <strong>${share.toFixed(1)}%</strong></div>
              <div>Change vs previous period: <strong>${escapeHtml(formatSignedPercent(node.engaged_change_pct))}</strong></div>
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
              const share = ((node.engaged_seconds || 0) / totalEngagedSeconds) * 100;

              if (node.is_group || node.children?.length || share < labelMinShare) {
                return "";
              }

              return `${params.name}\n${formatDurationShort(node.engaged_seconds)}`;
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

  function getTopPagesTimeValueExtent(seriesRows) {
    const values = seriesRows
      .flatMap((row) => (Array.isArray(row.values) ? row.values : []))
      .map((value) => Number(value))
      .filter(Number.isFinite);
    const max = Math.max(...values, 1);

    return {
      min: 0,
      max: compactAxisMax(max)
    };
  }

  function layoutTopPagesEndLabels(seriesRows, valueExtent, layout = {}) {
    const valueRange = Math.max(valueExtent.max - valueExtent.min, 1);
    const plotHeight = layout.plotHeight || 254;
    const labelPadding = layout.labelPadding || 8;
    const desiredLabelGap = layout.labelGap || 18;
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
      const clusterGap = labelGap;
      const packedHeight = clusterGap * (cluster.length - 1);
      const idealCenter = cluster.reduce((sum, label) => sum + label.idealY, 0) / cluster.length;
      const startBoundary = hasBoundaryRoom ? topBoundary : labelPadding;
      const endBoundary = hasBoundaryRoom ? bottomBoundary : plotHeight - labelPadding;
      const startY = Math.min(endBoundary - packedHeight, Math.max(startBoundary, idealCenter - packedHeight / 2));

      cluster.forEach((label, index) => {
        label.y = startY + index * clusterGap;
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

  function createTopPagesTimeOption(timeData, config) {
    const data = timeData || { labels: [], series: [], granularity: "day" };
    const seriesRows = Array.isArray(data.series) ? data.series : [];
    const labelSpacerCategory = "";
    const xAxisLabels = (Array.isArray(data.labels) ? data.labels : []).concat(labelSpacerCategory);
    const formatValue = config.formatValue || formatNumber;
    const labelSeriesSuffix = " label connector";
    const valueExtent = getTopPagesTimeValueExtent(seriesRows);
    const labelValuesBySeriesIndex = layoutTopPagesEndLabels(seriesRows, valueExtent, {
      plotHeight: 254,
      labelGap: 18,
      labelPadding: 8
    });
    const lineSeries = seriesRows.map((row, index) => {
      const color = chartTheme.series[index % chartTheme.series.length];

      return {
        name: row.page_name,
        type: "line",
        smooth: true,
        showSymbol: false,
        symbol: "circle",
        symbolSize: 5,
        data: (Array.isArray(row.values) ? row.values : []).concat(null),
        emphasis: {
          focus: "series"
        },
        lineStyle: {
          color,
          width: 2
        }
      };
    });
    const connectorSeries = seriesRows.map((row, index) => {
      const color = chartTheme.series[index % chartTheme.series.length];
      const labelColor = readableSeriesLabelColor(color);
      const lastValue = getLastNumericValue(row.values);
      const labelValue = labelValuesBySeriesIndex[index] ?? lastValue;
      const connectorData = Array.from({ length: xAxisLabels.length }, () => null);

      connectorData[Math.max(xAxisLabels.length - 2, 0)] = lastValue;
      connectorData[Math.max(xAxisLabels.length - 1, 0)] = labelValue;

      return {
        name: `${row.page_name}${labelSeriesSuffix}`,
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
          color: labelColor,
          fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif",
          fontSize: 12,
          fontWeight: "500",
          width: 92,
          overflow: "truncate",
          formatter: () => row.page_name
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
      color: chartTheme.series,
      tooltip: {
        trigger: "axis",
        confine: true,
        axisPointer: {
          type: "line"
        },
        formatter: (params) => {
          const items = (Array.isArray(params) ? params : [params]).filter((item) => !String(item.seriesName || "").endsWith(labelSeriesSuffix));
          const heading = items[0]?.axisValueLabel || "";

          if (!items.length) {
            return "";
          }

          const rows = items
            .map(
              (item) => `
                <div style="display:flex;gap:16px;justify-content:space-between;min-width:180px;">
                  <span>${item.marker}${escapeHtml(item.seriesName)}</span>
                  <strong>${escapeHtml(formatValue(item.value))}</strong>
                </div>
              `
            )
            .join("");

          return `<div><div style="margin-bottom:6px;font-weight:600;">${escapeHtml(heading)}</div>${rows}</div>`;
        }
      },
      grid: {
        left: 56,
        right: 112,
        top: 24,
        bottom: 42
      },
      xAxis: {
        type: "category",
        boundaryGap: false,
        data: xAxisLabels,
        axisLine: { lineStyle: { color: chartTheme.colors.axis } },
        axisLabel: {
          color: chartTheme.colors.mutedText,
          hideOverlap: true,
          formatter: (value) => value
        }
      },
      yAxis: {
        type: "value",
        name: config.yAxisName,
        min: valueExtent.min,
        max: valueExtent.max,
        nameTextStyle: { color: chartTheme.colors.mutedText },
        axisLine: { show: true, lineStyle: { color: chartTheme.colors.axis } },
        axisTick: { show: false },
        axisLabel: {
          color: chartTheme.colors.mutedText,
          formatter: (value) => formatValue(value)
        },
        splitLine: { show: false }
      },
      series: lineSeries.concat(connectorSeries)
    };
  }

  function mountOverviewCharts(data) {
    mountChart(
      document.getElementById("top-pages-visits-time-chart"),
      createTopPagesTimeOption(data.top_pages_by_visits_over_time, {
        yAxisName: "Visits",
        formatValue: formatNumber
      })
    );
    mountChart(
      document.getElementById("top-pages-engaged-time-chart"),
      createTopPagesTimeOption(data.top_pages_by_engaged_time_over_time, {
        yAxisName: "Time spent",
        formatValue: formatDurationShort
      })
    );
    mountChart(document.getElementById("engaged-time-treemap-chart"), createEngagedTimeTreemapOption(data));
    mountChart(document.getElementById("overview-flow-chart"), createSankeyOption(data));
  }

  function chartUnavailable(element) {
    if (!element) {
      return;
    }

    element.innerHTML = '<div class="flex h-full items-center justify-center rounded-lg bg-slate-50 text-sm text-slate-500">Chart library unavailable.</div>';
  }

  function mountChart(element, option) {
    if (!element) {
      return null;
    }

    if (!globalScope.echarts) {
      chartUnavailable(element);
      return null;
    }

    const chart = globalScope.echarts.init(element, null, { renderer: "canvas" });
    chart.setOption(option);

    const resize = () => chart.resize();
    globalScope.addEventListener("resize", resize);

    if (globalScope.ResizeObserver) {
      const observer = new ResizeObserver(resize);
      observer.observe(element);
      chart.__hymetryResizeObserver = observer;
    }

    return chart;
  }

  function createTrendOption(data, metric) {
    const metricLabels = {
      companies: "Companies",
      users: "Users",
      visits: "Visits",
      engaged_time: "Engaged time"
    };
    const trendValues = data.trend_series[metric] || [];

    return {
      color: [chartTheme.colors.primary],
      tooltip: {
        trigger: "axis",
        valueFormatter: (value) => (metric === "engaged_time" ? `${value}h` : formatNumber(value))
      },
      grid: {
        left: 48,
        right: 20,
        top: 24,
        bottom: 42
      },
      xAxis: {
        type: "category",
        boundaryGap: false,
        data: data.trend_series.labels,
        axisLine: { lineStyle: { color: chartTheme.colors.axis } },
        axisLabel: { color: chartTheme.colors.mutedText }
      },
      yAxis: {
        type: "value",
        max: compactAxisMax(trendValues),
        axisLine: { show: true, lineStyle: { color: chartTheme.colors.axis } },
        axisTick: { show: false },
        axisLabel: { color: chartTheme.colors.mutedText },
        splitLine: { show: false }
      },
      series: [
        {
          name: metricLabels[metric],
          type: "line",
          smooth: true,
          symbol: "circle",
          symbolSize: 5,
          areaStyle: { color: rgbaFromHex(chartTheme.series[0], 0.12) },
          lineStyle: { width: 3 },
          data: trendValues
        }
      ]
    };
  }

  function mountTrendChart(data, elementId = "page-trend-chart", buttonSelector = "[data-trend-metric]") {
    const element = document.getElementById(elementId);
    let activeMetric = "companies";
    const chart = mountChart(element, createTrendOption(data, activeMetric));

    document.querySelectorAll(buttonSelector).forEach((button) => {
      button.addEventListener("click", () => {
        activeMetric = button.getAttribute("data-trend-metric");

        document.querySelectorAll(buttonSelector).forEach((metricButton) => {
          const isActive = metricButton === button;
          metricButton.classList.toggle("border-slate-900", isActive);
          metricButton.classList.toggle("bg-slate-900", isActive);
          metricButton.classList.toggle("text-white", isActive);
          metricButton.classList.toggle("border-slate-200", !isActive);
          metricButton.classList.toggle("bg-white", !isActive);
          metricButton.classList.toggle("text-slate-700", !isActive);
          metricButton.setAttribute("aria-pressed", String(isActive));
        });

        if (chart) {
          chart.setOption(createTrendOption(data, activeMetric), true);
        }
      });
    });
  }

  const overviewSankeyMaxLinks = 18;

  function wouldCreateSankeyCycle(adjacency, source, target) {
    if (source === target) {
      return true;
    }

    const visited = new Set();
    const stack = [target];

    while (stack.length) {
      const node = stack.pop();

      if (node === source) {
        return true;
      }

      if (visited.has(node)) {
        continue;
      }

      visited.add(node);
      (adjacency.get(node) || []).forEach((nextNode) => stack.push(nextNode));
    }

    return false;
  }

  function createOverviewSankeyData(sankey) {
    const links = Array.isArray(sankey?.links) ? sankey.links : [];
    const sourceNodes = Array.isArray(sankey?.nodes) ? sankey.nodes : [];
    const nodesByName = new Map();

    sourceNodes.forEach((node) => {
      const cleanLabel = String(node?.name || node?.label || "").trim();

      if (!cleanLabel) {
        return;
      }

      nodesByName.set(cleanLabel, {
        ...node,
        name: cleanLabel,
        label: node?.label || cleanLabel
      });
    });

    const ensureNode = (label, productArea = {}) => {
      const cleanLabel = String(label || "Unassigned").trim() || "Unassigned";

      if (!nodesByName.has(cleanLabel)) {
        nodesByName.set(cleanLabel, {
          name: cleanLabel,
          label: cleanLabel,
          ...productArea
        });
      } else {
        const node = nodesByName.get(cleanLabel);

        Object.entries(productArea).forEach(([key, value]) => {
          if (value && !node[key]) {
            node[key] = value;
          }
        });
      }

      return cleanLabel;
    };

    const candidates = links
      .map((link) => {
        const sourceLabel = String(link?.source || "").trim();
        const targetLabel = String(link?.target || "").trim();
        const value = Number(link?.value) || 0;

        return {
          ...link,
          source: sourceLabel,
          target: targetLabel,
          sourceLabel,
          targetLabel,
          value
        };
      })
      .filter((link) => link.sourceLabel && link.targetLabel && link.value > 0)
      .sort((a, b) => b.value - a.value);

    const adjacency = new Map();
    const normalizedLinks = [];

    candidates.forEach((link) => {
      if (normalizedLinks.length >= overviewSankeyMaxLinks) {
        return;
      }

      if (wouldCreateSankeyCycle(adjacency, link.sourceLabel, link.targetLabel)) {
        return;
      }

      const source = ensureNode(link.sourceLabel, {
        product_area_key: link.source_product_area_key || link.sourceProductAreaKey,
        product_area_name: link.source_product_area_name || link.sourceProductAreaName || link.source_product_area || link.sourceProductArea,
        color: link.source_product_area_color || link.sourceProductAreaColor || link.source_color || link.sourceColor
      });
      const target = ensureNode(link.targetLabel, {
        product_area_key: link.target_product_area_key || link.targetProductAreaKey,
        product_area_name: link.target_product_area_name || link.targetProductAreaName || link.target_product_area || link.targetProductArea,
        color: link.target_product_area_color || link.targetProductAreaColor || link.target_color || link.targetColor
      });
      const value = Number(link?.value) || 0;

      normalizedLinks.push({
        ...link,
        source,
        target,
        value
      });

      if (!adjacency.has(source)) {
        adjacency.set(source, new Set());
      }
      adjacency.get(source).add(target);
    });

    const usedNodeNames = new Set();
    normalizedLinks.forEach((link) => {
      usedNodeNames.add(link.source);
      usedNodeNames.add(link.target);
    });

    return {
      nodes: Array.from(nodesByName.values()).filter((node) => usedNodeNames.has(node.name)),
      links: normalizedLinks
    };
  }

  function createSankeyOption(data) {
    const sankeyData = createOverviewSankeyData(data?.sankey);
    const nodes = sankeyData.nodes.map((node) => ({
      ...node,
      itemStyle: {
        ...(node.itemStyle || {}),
        borderColor: chartTheme.colors.white,
        borderWidth: 1,
        color: productAreaColor(sankeyNodeProductAreaName(node), productAreaExplicitColor(node))
      }
    }));

    return {
      tooltip: {
        trigger: "item",
        formatter: (params) => {
          if (params.dataType === "edge") {
            return `${escapeHtml(params.data.sourceLabel || params.data.source)} to ${escapeHtml(params.data.targetLabel || params.data.target)}<br />${formatNumber(params.data.value)} transitions`;
          }

          return escapeHtml(params.data?.label || params.name);
        }
      },
      series: [
        {
          type: "sankey",
          data: nodes,
          links: sankeyData.links,
          nodeWidth: 14,
          nodeGap: 18,
          draggable: false,
          emphasis: {
            focus: "adjacency"
          },
          label: {
            color: chartTheme.colors.text,
            fontSize: 12,
            formatter: (params) => params.data?.label || params.name
          },
          lineStyle: {
            color: "gradient",
            curveness: 0.52,
            opacity: 0.28
          },
          itemStyle: {
            borderColor: chartTheme.colors.white,
            borderWidth: 1
          }
        }
      ]
    };
  }

  function initDetailPage() {
    const body = document.body;

    if (body.dataset.pagesView !== "detail") {
      return;
    }

    const projectId = body.dataset.projectId || "35590318";
    const pageRuleId = getRequestedPageRuleId();
    const notFound = document.getElementById("page-not-found");
    const content = document.getElementById("page-detail-content");
    currentDetailOverviewData = provider.getMockPagesOverviewData(projectId) || {};

    document.querySelectorAll("[data-back-to-pages]").forEach((link) => {
      link.setAttribute("href", overviewHref);
    });

    const loadDetails = (periodDays, options = {}) => {
      const selectedDays = coercePageDetailPeriod(periodDays);
      updateDetailPeriodQuery(pageRuleId, selectedDays);
      const data = provider.getMockPageDetailsData(projectId, pageRuleId, selectedDays);

      if (!data) {
        if (options.allowRedirect) {
          globalScope.location.href = detailHref(pageRuleId, selectedDays);
          return;
        }

        currentPageDetailsData = null;
        notFound?.classList.remove("hidden");
        content?.classList.add("hidden");
        return;
      }

      notFound?.classList.add("hidden");
      content?.classList.remove("hidden");
      renderPageDetails(data, loadDetails);
      mountSplitChangeValueWidthSync();
      mountFloatingDeltaTooltips();
      mountDetailStickyTableHeaders();
    };

    loadDetails(getRequestedPeriodDays());
  }

  document.addEventListener("DOMContentLoaded", () => {
    initOverviewPage();
    initDetailPage();
  });

  document.addEventListener("htmx:beforeRequest", (event) => {
    if (event.target?.matches?.("[data-page-metric-dynamics-show-peers]")) {
      setPageMetricDynamicsLoading(true);
    }
  });

  document.addEventListener("htmx:afterRequest", (event) => {
    if (event.target?.matches?.("[data-page-metric-dynamics-show-peers]")) {
      setPageMetricDynamicsLoading(false);
    }
  });

  document.addEventListener("htmx:afterSwap", (event) => {
    if (event.detail?.target?.id === "page-metric-dynamics-section" && currentPageDetailsData) {
      pageMetricDynamicsState.showPeers = pageMetricDynamicsShowPeers();
      renderPageMetricDynamics(currentPageDetailsData);
    }
  });
})(window);
