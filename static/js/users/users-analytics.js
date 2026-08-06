(function mountHymetryUsersAnalytics(globalScope) {
  const provider = globalScope.HymetryUsersDemoData;

  if (!provider) {
    return;
  }

  const analyticsTooltips = globalScope.HymetryAnalyticsTooltips;
  const numberFormatter = new Intl.NumberFormat("en-US");
  const averageCountFormatter = new Intl.NumberFormat("en-US", {
    maximumFractionDigits: 2
  });
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

  const statusRegistry = globalScope.HymetryAnalyticsStatusColors || {};
  const fallbackUserStatusOrderLabels = ["Power", "Healthy", "Light", "Passive", "Dropped"];
  const fallbackStatusMeta = {
    Power: { label: "Power", color: "c-green", badge: "users-badge--green", sort: 0 },
    Healthy: { label: "Healthy", color: "c-blue", badge: "users-badge--blue", sort: 1 },
    Light: { label: "Light", color: "c-orange", badge: "users-badge--amber", sort: 2 },
    Passive: { label: "Passive", color: "c-brown", badge: "users-badge--brown", sort: 3 },
    Dropped: { label: "Dropped", color: "c-red", badge: "users-badge--red", sort: 4 }
  };
  const userStatusOrderLabels = statusRegistry.userStatusOrderLabels || fallbackUserStatusOrderLabels;
  const getUserStatusMeta = statusRegistry.getUserStatusMeta || ((status) => {
    const raw = String(status || "").trim();
    const key = raw.replace(/\s+/g, "_").replace(/-/g, "_").toLowerCase();
    const label = {
      power: "Power",
      healthy: "Healthy",
      active: "Healthy",
      light: "Light",
      risk: "Light",
      at_risk: "Light",
      atrisk: "Light",
      passive: "Passive",
      dropped: "Dropped"
    }[key] || raw;

    return fallbackStatusMeta[label] || { label: raw || "Unknown", color: "slate-400", badge: "users-badge--slate", sort: 99 };
  });
  const statusMeta = userStatusOrderLabels.reduce((lookup, label) => {
    lookup[label] = getUserStatusMeta(label, "users");
    return lookup;
  }, {});
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
      text: tailwindColor("slate-900"),
      mutedText: tailwindColor("slate-500"),
      labelText: tailwindColor("slate-700"),
      axis: tailwindColor("slate-300"),
      grid: tailwindColor("slate-200"),
      white: tailwindColor("white")
    },
    series: chartSeriesColors
  };
  const defaultProductAreas = [
    "Core product",
    "Billing",
    "Developer",
    "Administration",
    "Reporting",
    "Integrations",
    "Export",
    "Team permissions",
    "Settings"
  ];
  const providerProductAreaOptions = Array.isArray(provider.productAreaOptions)
    ? provider.productAreaOptions
      .map((area) => ({
        name: String(area?.name || area?.productAreaName || area?.product_area_name || "").trim(),
        shortName: String(area?.shortName || area?.short_name || area?.name || "").trim(),
        color: String(area?.color || "").trim()
      }))
      .filter((area) => area.name)
    : [];
  const productAreas = (Array.isArray(provider.productAreas) && provider.productAreas.length
    ? provider.productAreas
    : providerProductAreaOptions.map((area) => area.name).filter(Boolean)
  ).slice(0, 9);

  if (!productAreas.length) {
    productAreas.push(...defaultProductAreas);
  }

  const productAreaOrder = productAreas.concat("Other");
  const productAreaColorResolver = globalScope.HymetryProductAreaColors?.createResolver({
    resolveColor: tailwindColor,
    palette: chartSeriesColors
  }) || null;
  const usersTablePageSize = 20;
  const usersTableDefaultSortDirections = {
    name: "asc",
    company: "asc",
    status: "asc",
    companySharePct: "desc",
    engagedSeconds: "desc",
    visitsCount: "desc",
    avgVisitSeconds: "desc",
    avgSessionSeconds: "desc",
    lastActiveSort: "asc"
  };
  const usersScatterLimit = 300;
  const userScatterStatusOrder = userStatusOrderLabels;
  const usersScatterLabelLimit = 18;
  const usersScatterPointSize = 46;
  const usersScatterJitterX = 18;
  const usersScatterJitterY = 18;
  const featureProductAreas = {
    Dashboard: "Core product",
    Projects: "Core product",
    Sessions: "Core product",
    Reports: "Reporting",
    Users: "Team permissions",
    Billing: "Billing",
    Invoices: "Billing",
    Pricing: "Billing",
    "Payment methods": "Billing",
    "API keys": "Developer",
    Webhooks: "Developer",
    "Export report": "Export",
    "Data export": "Export",
    "Team permissions": "Team permissions",
    Roles: "Team permissions",
    "Audit log": "Administration",
    Settings: "Settings",
    "Core product": "Core product",
    Developer: "Developer",
    Administration: "Administration",
    Reporting: "Reporting",
    Integrations: "Integrations",
    Export: "Export",
    ...(provider.featureProductAreas || {})
  };
  const searchableSelectIds = new Set(["users-company-filter", "users-feature-filter"]);
  const groupedSelectIds = new Set(["users-feature-filter"]);
  const usersTableNumericSortKeys = new Set([
    "companySharePct",
    "engagedSeconds",
    "visitsCount",
    "avgVisitSeconds",
    "avgSessionSeconds",
    "lastActiveSort"
  ]);

  let currentData = null;
  let activeHeatmapMetric = "engagedSeconds";
  let userSearchMounted = false;
  const userSearchDebounceMs = 220;
  const userSearchRecentStorageKey = `hymetry:recent-users:${document.body?.dataset.projectId || "unknown-project"}`;
  let userSearchDebounceId = 0;
  let customSelectGlobalEventsMounted = false;
  let usersTableSortMounted = false;
  let adoptionCellTooltipId = 0;
  let periodChangeTooltipId = 0;
  let splitChangeValueWidthSyncFrame = 0;
  let usersTableFilterDebounceId = 0;
  const calloutPageSize = 10;
  const attentionListState = { page: 1 };
  const momentumListState = { page: 1 };
  const usersTableState = {
    page: 1,
    sortKey: "engagedSeconds",
    sortDirection: "desc",
    isLoading: false,
    loadingToken: 0
  };

  function usersTablePagination(data = currentData) {
    return data?.tableData?.users?.pagination || null;
  }

  function hasServerUsersTable(data = currentData) {
    return Boolean(usersTablePagination(data));
  }

  function serverUsersTableEnabled() {
    return Boolean(currentData && hasServerUsersTable(currentData) && typeof provider.loadUsersTable === "function");
  }

  function applyUsersTablePayload(payload) {
    if (!currentData || !payload || !Array.isArray(payload.rows)) {
      return false;
    }

    currentData.users = payload.rows;
    currentData.tableData = {
      ...(currentData.tableData || {}),
      users: payload
    };

    const page = Number(payload.pagination?.page);
    if (Number.isFinite(page) && page > 0) {
      usersTableState.page = Math.round(page);
    }

    return true;
  }
  const userSearchState = {
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

  function tableHeaderTooltip(label, description, tooltipId, options = {}) {
    const alignmentClass = options.align === "end" ? " metric-header-tooltip--end" : "";

    return `
      <span class="metric-header-tooltip${alignmentClass}" tabindex="0" aria-describedby="${escapeHtml(tooltipId)}">
        ${escapeHtml(label)}
        <span id="${escapeHtml(tooltipId)}" class="metric-header-tooltip__content" role="tooltip">${escapeHtml(description)}</span>
      </span>
    `;
  }

  function formatNumber(value) {
    return numberFormatter.format(Math.round(Number(value) || 0));
  }

  function formatPercent(value) {
    return `${Math.round(Number(value) || 0)}%`;
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

  function formatDeltaLabel(value) {
    const number = Number(value) || 0;
    const rounded = Math.abs(number) < 10 ? Math.round(number * 10) / 10 : Math.round(number);

    return `${number > 0 ? "+" : ""}${rounded}%`;
  }

  function formatSignedNumber(value) {
    const number = Math.round(Number(value) || 0);

    return `${number > 0 ? "+" : ""}${formatNumber(number)}`;
  }

  function formatDuration(totalSeconds) {
    const seconds = Math.max(0, Math.round(Number(totalSeconds) || 0));
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const remainingSeconds = seconds % 60;

    if (hours > 0) {
      return minutes > 0 ? `${hours}h ${minutes}m` : `${hours}h`;
    }

    if (minutes > 0) {
      return `${minutes}m`;
    }

    return `${remainingSeconds}s`;
  }

  function formatDurationWithSeconds(totalSeconds) {
    const seconds = Math.max(0, Math.round(Number(totalSeconds) || 0));

    if (seconds >= 3600) {
      return formatDuration(seconds);
    }

    const minutes = Math.floor(seconds / 60);
    const remainingSeconds = seconds % 60;

    if (minutes > 0) {
      return `${minutes}m ${String(remainingSeconds).padStart(2, "0")}s`;
    }

    return `${remainingSeconds}s`;
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

  function syncProductAreaPalette(data = currentData) {
    if (!productAreaColorResolver) {
      return;
    }

    productAreaColorResolver.reset();
    (provider.productAreaOptions || []).forEach((area) => productAreaColorResolver.add(area));
    providerProductAreaOptions.forEach((area) => productAreaColorResolver.add(area));
    productAreas.forEach((area) => productAreaColorResolver.add(area));
    (data?.productAreaOptions || []).forEach((area) => productAreaColorResolver.add(area));
    (data?.productAreas || []).forEach((area) => productAreaColorResolver.add(area));
    (data?.users || []).forEach((user) => {
      (user.pageGroups || []).forEach((group) => productAreaColorResolver.add(group.productArea || group.name, group.color));
      (user.productAreaAdoption || []).forEach((cell) => productAreaColorResolver.add(cell.productArea || cell.name, cell.color));
      productAreaColorResolver.add(user.topArea || user.topProductArea);
    });
    productAreaColorResolver.finalize();
  }

  function productAreaColor(area) {
    if (productAreaColorResolver) {
      const option = providerProductAreaOptions.find((item) => item.name === area);
      return productAreaColorResolver.color(area, option?.color || "");
    }

    const index = Math.max(productAreaOrder.indexOf(area), 0);
    return chartSeriesColors[index % chartSeriesColors.length] || visitsCircleColors[0];
  }

  function userStatusMetaFor(status) {
    const directMeta = statusMeta[status];

    if (directMeta) {
      return directMeta;
    }

    const normalizedMeta = getUserStatusMeta(status, "users");

    return statusMeta[normalizedMeta.label] || normalizedMeta || statusMeta.Light;
  }

  function statusColor(status) {
    const meta = userStatusMetaFor(status);

    return tailwindColor(meta.color || statusMeta.Light.color);
  }

  function productAreaShortLabel(area) {
    const option = providerProductAreaOptions.find((item) => item.name === area);
    const shortName = String(option?.shortName || "").trim();

    if (shortName && shortName !== area && shortName.length <= 8) {
      return shortName;
    }

    const words = String(area || "").trim().split(/\s+/).filter(Boolean);

    if (words.length > 1) {
      return words.map((word) => word[0]).join("").slice(0, 7).toUpperCase();
    }

    return words[0]?.length > 8 ? `${words[0].slice(0, 6)}.` : words[0] || "Area";
  }

  function syncProductAreaHeadings() {
    document.documentElement.style.setProperty("--users-product-area-count", String(Math.max(productAreas.length, 1)));
    document.querySelectorAll(".companies-matrix-heading").forEach((heading, headingIndex) => {
      heading.innerHTML = productAreas.map((area, areaIndex) => {
        const tooltipId = `users-dynamic-area-tooltip-${headingIndex}-${areaIndex}`;

        return `
          <span class="metric-header-tooltip" tabindex="0" aria-describedby="${tooltipId}">
            ${escapeHtml(productAreaShortLabel(area))}
            <span id="${tooltipId}" class="metric-header-tooltip__content" role="tooltip">${escapeHtml(area)}</span>
          </span>
        `;
      }).join("");
    });
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

      if (value === null || value === undefined) {
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

  function statusBadge(status) {
    const meta = userStatusMetaFor(status);

    return `<span class="users-badge ${meta.badge}">${escapeHtml(meta.label || status)}</span>`;
  }

  function deltaClass(value, invert = false) {
    const number = Number(value) || 0;

    if (number === 0) {
      return "text-slate-700";
    }

    const positive = invert ? number < 0 : number > 0;

    return positive ? "text-green-700" : "text-red-600";
  }

  function normalizeSelectOption(value) {
    if (value && typeof value === "object") {
      const label = value.label ?? value.value ?? "";
      const optionValue = value.value ?? label;
      const group = value.group || "";
      const search = value.search || [label, optionValue, group].filter(Boolean).join(" ");

      return {
        value: String(optionValue),
        label: String(label),
        group: String(group),
        search: String(search)
      };
    }

    return {
      value: String(value ?? ""),
      label: String(value ?? ""),
      group: "",
      search: String(value ?? "")
    };
  }

  function featureProductArea(featureName) {
    const name = String(featureName || "");

    if (productAreas.includes(name)) {
      return name;
    }

    return featureProductAreas[name] || "Other";
  }

  function productAreaSortValue(area) {
    const index = productAreaOrder.indexOf(area);

    return index === -1 ? productAreaOrder.length : index;
  }

  function buildFeatureFilterOptions(data, users) {
    const explicitFeatures = (data.pageFeatures || []).map(normalizeSelectOption);
    const names = new Set([
      ...(data.featureColumns || []),
      ...users.map((row) => row.topFeature).filter(Boolean),
      ...users.flatMap((row) => (row.topFeatures || []).map((item) => item.feature).filter(Boolean)),
      ...(data.pageGroups || [])
    ]);

    return explicitFeatures.concat(Array.from(names)
      .filter((name) => !explicitFeatures.some((option) => option.value === name))
      .map((name) => {
        const group = featureProductArea(name);

        return {
          value: name,
          label: name,
          group,
          search: `${name} ${group}`
        };
      }))
      .sort((a, b) => {
        const groupDelta = productAreaSortValue(a.group) - productAreaSortValue(b.group);

        return groupDelta || a.label.localeCompare(b.label);
      });
  }

  function populateSelect(selectId, values, fallbackLabel, options = {}) {
    const select = document.getElementById(selectId);

    if (!select) {
      return;
    }

    const currentValue = select.value;
    const normalizedValues = values.map(normalizeSelectOption).filter((option) => option.value || option.label);
    const sortedValues = options.sort === false
      ? normalizedValues
      : normalizedValues.slice().sort((a, b) => a.label.localeCompare(b.label));
    const firstOption = `<option value="" data-users-option-search="${escapeHtml(fallbackLabel)}">${escapeHtml(fallbackLabel)}</option>`;
    const optionMarkup = sortedValues
      .map((option) => `<option value="${escapeHtml(option.value)}" data-users-option-group="${escapeHtml(option.group)}" data-users-option-search="${escapeHtml(option.search)}">${escapeHtml(option.label)}</option>`)
      .join("");

    select.innerHTML = `${firstOption}${optionMarkup}`;

    if (sortedValues.some((option) => option.value === currentValue)) {
      select.value = currentValue;
    }

    syncCustomSelect(select);
  }

  function selectAccessibleLabel(select) {
    if (!select) {
      return "Select option";
    }

    const explicitLabel = select.getAttribute("aria-label");
    const label = select.id ? document.querySelector(`label[for="${select.id}"]`) : null;
    const text = explicitLabel || label?.textContent || select.options?.[0]?.textContent || "Select option";

    return text.replace(/\s+/g, " ").trim();
  }

  function selectedOptionText(select) {
    return select?.selectedOptions?.[0]?.textContent || select?.options?.[0]?.textContent || "";
  }

  function closeCustomSelect(select) {
    const widget = select?.__hymetryUsersSelect;

    if (!widget) {
      return;
    }

    widget.listbox.hidden = true;
    widget.button.setAttribute("aria-expanded", "false");
    widget.query = "";
  }

  function closeAllCustomSelects(exceptSelect = null) {
    document.querySelectorAll("select.users-filter-control").forEach((select) => {
      if (select !== exceptSelect) {
        closeCustomSelect(select);
      }
    });
  }

  function setCustomSelectValue(select, value) {
    if (!select) {
      return;
    }

    select.value = value;
    syncCustomSelect(select);
    closeCustomSelect(select);
    select.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function customSelectOptionMatches(option, query) {
    if (option.value === "") {
      return !query;
    }

    if (!query) {
      return true;
    }

    const searchableText = [
      option.textContent || "",
      option.dataset.usersOptionGroup || "",
      option.dataset.usersOptionSearch || ""
    ].join(" ").toLowerCase();

    return searchableText.includes(query);
  }

  function customSelectOptionMarkup(select, option, index, isActive = null) {
    const isSelected = option.value === select.value;
    const optionIsActive = isActive ?? isSelected;
    const isFeatureOption = select?.id === "users-feature-filter" && option.value;
    const optionClassName = isFeatureOption
      ? "company-search__option company-search__option--table"
      : "company-search__option";
    const optionContent = isFeatureOption
      ? `
        <span class="users-select__option-grid">
          <span class="company-search__name">${escapeHtml(option.textContent || "")}</span>
          <span class="users-select__option-area">${escapeHtml(option.dataset.usersOptionGroup || "Other")}</span>
        </span>
      `
      : `
        <span class="min-w-0">
          <span class="company-search__name">${escapeHtml(option.textContent || "")}</span>
        </span>
      `;

    return `
      <button
        id="${escapeHtml(select.id)}-custom-option-${index}"
        type="button"
        class="${optionClassName}"
        role="option"
        data-users-select-value="${escapeHtml(option.value)}"
        data-active="${String(optionIsActive)}"
        aria-selected="${String(isSelected)}">
        ${optionContent}
      </button>
    `;
  }

  function customSelectSearchPlaceholder(select) {
    if (select?.id === "users-company-filter") {
      return "Search companies...";
    }

    if (select?.id === "users-feature-filter") {
      return "Search pages...";
    }

    return "Search...";
  }

  function renderCustomSelectOptions(select, matchingOptions, query) {
    const activeOption = matchingOptions.find(({ option }) => option.value === select.value)
      || (query ? matchingOptions.find(({ option }) => option.value !== "") : null);
    const activeIndex = activeOption?.index ?? -1;

    if (!groupedSelectIds.has(select.id)) {
      const optionMarkup = matchingOptions
        .map(({ option, index }) => customSelectOptionMarkup(select, option, index, index === activeIndex))
        .join("");

      return optionMarkup || `<div class="users-select__empty">No matches</div>`;
    }

    const fallbackOptions = matchingOptions.filter(({ option }) => option.value === "");
    const groupedOptions = matchingOptions.filter(({ option }) => option.value !== "");
    const groups = groupedOptions.reduce((lookup, item) => {
      const group = item.option.dataset.usersOptionGroup || "Other";

      if (!lookup.has(group)) {
        lookup.set(group, []);
      }

      lookup.get(group).push(item);
      return lookup;
    }, new Map());

    const fallbackMarkup = fallbackOptions
      .map(({ option, index }) => customSelectOptionMarkup(select, option, index, index === activeIndex))
      .join("");
    const groupMarkup = Array.from(groups.entries())
      .sort(([groupA], [groupB]) => productAreaSortValue(groupA) - productAreaSortValue(groupB) || groupA.localeCompare(groupB))
      .map(([group, items]) => `
        <div class="users-select__group" data-users-select-group="${escapeHtml(group)}">
          ${items.map(({ option, index }) => customSelectOptionMarkup(select, option, index, index === activeIndex)).join("")}
        </div>
      `)
      .join("");
    const emptyMarkup = query && groupedOptions.length === 0
      ? `<div class="users-select__empty">No matching pages</div>`
      : "";

    return `${fallbackMarkup}${groupMarkup}${emptyMarkup}` || `<div class="users-select__empty">No matches</div>`;
  }

  function syncCustomSelect(select) {
    const widget = select?.__hymetryUsersSelect;

    if (!select || !widget) {
      return;
    }

    const label = selectAccessibleLabel(select);
    const valueText = selectedOptionText(select);
    const isSearchable = searchableSelectIds.has(select.id);
    const query = isSearchable ? String(widget.query || "").trim().toLowerCase() : "";
    const matchingOptions = Array.from(select.options)
      .map((option, index) => ({ option, index }))
      .filter(({ option }) => customSelectOptionMatches(option, query));
    const searchMarkup = isSearchable
      ? `
        <div class="users-select__search-wrap" role="presentation">
          <input
            class="users-select__search"
            type="search"
            value="${escapeHtml(widget.query || "")}"
            placeholder="${escapeHtml(customSelectSearchPlaceholder(select))}"
            aria-label="${escapeHtml(customSelectSearchPlaceholder(select))}"
            autocomplete="off"
            data-users-select-search />
        </div>
      `
      : "";

    widget.label.textContent = valueText;
    widget.button.setAttribute("aria-label", `${label}: ${valueText}`);
    widget.listbox.innerHTML = `${searchMarkup}${renderCustomSelectOptions(select, matchingOptions, query)}`;

    const searchInput = widget.listbox.querySelector("[data-users-select-search]");

    if (searchInput) {
      searchInput.addEventListener("input", () => {
        const cursorPosition = searchInput.selectionStart || searchInput.value.length;

        widget.query = searchInput.value;
        syncCustomSelect(select);

        const nextSearchInput = widget.listbox.querySelector("[data-users-select-search]");

        if (nextSearchInput && !widget.listbox.hidden) {
          nextSearchInput.focus();

          try {
            nextSearchInput.setSelectionRange(cursorPosition, cursorPosition);
          } catch {
            // Some browsers do not support selection ranges on search inputs.
          }
        }
      });

      searchInput.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
          event.stopPropagation();
          closeCustomSelect(select);
          widget.button.focus();
        }

        if (event.key === "ArrowDown") {
          event.preventDefault();
          widget.listbox.querySelector("[data-users-select-value]")?.focus();
        }
      });
    }

    widget.listbox.querySelectorAll("[data-users-select-value]").forEach((option) => {
      option.addEventListener("click", () => {
        setCustomSelectValue(select, option.getAttribute("data-users-select-value") || "");
      });
    });
  }

  function openCustomSelect(select) {
    const widget = select?.__hymetryUsersSelect;

    if (!widget) {
      return;
    }

    closeAllCustomSelects(select);
    widget.query = "";
    syncCustomSelect(select);
    widget.listbox.hidden = false;
    widget.button.setAttribute("aria-expanded", "true");

    if (searchableSelectIds.has(select.id)) {
      widget.listbox.querySelector("[data-users-select-search]")?.focus();
    } else {
      widget.listbox.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: "nearest" });
    }
  }

  function mountCustomSelectDropdowns() {
    document.querySelectorAll("select.users-filter-control").forEach((select) => {
      if (select.__hymetryUsersSelect) {
        syncCustomSelect(select);
        return;
      }

      const label = selectAccessibleLabel(select);
      const wrapper = document.createElement("div");
      const button = document.createElement("button");
      const buttonLabel = document.createElement("span");
      const chevron = document.createElement("span");
      const listbox = document.createElement("div");

      wrapper.className = "users-select";
      wrapper.dataset.selectId = select.id || "";
      button.type = "button";
      button.className = "users-filter-control users-select__button";
      button.setAttribute("aria-haspopup", "listbox");
      button.setAttribute("aria-expanded", "false");
      button.setAttribute("aria-label", `${label}: ${selectedOptionText(select)}`);
      buttonLabel.className = "truncate";
      buttonLabel.dataset.usersSelectLabel = "";
      chevron.className = "users-select__chevron";
      chevron.setAttribute("aria-hidden", "true");
      chevron.innerHTML = `
        <svg viewBox="0 0 24 24" fill="none">
          <path d="m6 9 6 6 6-6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></path>
        </svg>
      `;
      listbox.id = `${select.id || "users-select"}-custom-listbox`;
      listbox.className = "company-search__dropdown";
      listbox.setAttribute("role", "listbox");
      listbox.hidden = true;
      button.setAttribute("aria-controls", listbox.id);

      button.append(buttonLabel, chevron);
      wrapper.append(button, listbox);
      select.hidden = true;
      select.insertAdjacentElement("afterend", wrapper);
      select.__hymetryUsersSelect = {
        button,
        label: buttonLabel,
        listbox,
        wrapper,
        query: ""
      };

      button.addEventListener("click", () => {
        if (listbox.hidden) {
          openCustomSelect(select);
        } else {
          closeCustomSelect(select);
        }
      });

      button.addEventListener("keydown", (event) => {
        const options = Array.from(select.options);
        const currentIndex = Math.max(0, options.findIndex((option) => option.value === select.value));

        if (event.key === "Escape") {
          closeCustomSelect(select);
          return;
        }

        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          openCustomSelect(select);
          return;
        }

        if (event.key === "ArrowDown" || event.key === "ArrowUp") {
          event.preventDefault();
          const offset = event.key === "ArrowDown" ? 1 : -1;
          const nextIndex = (currentIndex + offset + options.length) % Math.max(options.length, 1);
          setCustomSelectValue(select, options[nextIndex]?.value || "");
        }
      });

      syncCustomSelect(select);
    });

    if (!customSelectGlobalEventsMounted) {
      customSelectGlobalEventsMounted = true;

      document.addEventListener("pointerdown", (event) => {
        if (!event.target.closest(".users-select")) {
          closeAllCustomSelects();
        }
      });

      globalScope.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
          closeAllCustomSelects();
        }
      });
    }
  }

  function populateFilters(data) {
    const users = [...(data.scatter || []), ...(data.users || [])];
    const unique = (key) => Array.from(new Set(users.map((row) => row[key]).filter(Boolean)));
    const filterOptions = data.tableData?.users?.filterOptions || {};
    const fallbackCompanies = Array.from(new Set([
      ...unique("company"),
      ...(data.usersByCompany || []).map((row) => row.company || row.companyName || row.name).filter(Boolean)
    ]));
    const companies = Array.isArray(filterOptions.companies) && filterOptions.companies.length
      ? filterOptions.companies
      : fallbackCompanies;
    const roles = Array.isArray(filterOptions.roles) && filterOptions.roles.length
      ? filterOptions.roles
      : unique("role");
    const statuses = Array.isArray(filterOptions.statuses) && filterOptions.statuses.length
      ? filterOptions.statuses
      : Object.keys(statusMeta);
    const featureOptions = buildFeatureFilterOptions(data, users);

    populateSelect("users-company-filter", companies, "All companies");
    populateSelect("users-table-company", companies, "All companies");
    populateSelect("users-table-role", roles, "All roles");
    populateSelect("users-table-status", statuses, "All statuses");
    populateSelect("users-feature-filter", featureOptions, "All pages", { sort: false });
  }

  function readFilterValue(id) {
    return document.getElementById(id)?.value || "";
  }

  function userSearchElements() {
    return {
      root: document.getElementById("users-header-search"),
      input: document.getElementById("users-filter-search"),
      listbox: document.getElementById("users-search-results")
    };
  }

  function normalizeUserSearchValue(value) {
    return String(value ?? "").trim().toLowerCase();
  }

  function userSearchUsesRemote() {
    return typeof provider.searchUsers === "function" && Boolean(document.body?.dataset.userOptionsUrl);
  }

  function getUserSearchRows() {
    const company = readFilterValue("users-company-filter");
    const feature = readFilterValue("users-feature-filter");

    return (currentData?.users || [])
      .filter((user) => !company || user.company === company)
      .filter((user) => userMatchesFeature(user, feature));
  }

  function userSearchMetadata(user) {
    return [
      user.email,
      user.company,
      user.role,
      `${formatDuration(user.engagedSeconds)} engaged`,
      `${formatNumber(user.visitsCount)} visits`,
      `${formatNumber(user.featuresCount)} features`,
      `last active ${user.lastActive}`
    ].filter(Boolean).join(" \u00b7 ");
  }

  function userDetailId(user) {
    return String(user?.id || user?.userId || user?.email || user?.name || "").trim();
  }

  function companyDetailId(user) {
    const directId = String(user?.companyId || user?.company_id || "").trim();

    if (directId) {
      return directId;
    }

    const companyName = String(user?.company || user?.companyName || "").trim();
    const userId = userDetailId(user);
    const matchedUser = (currentData?.users || []).find((row) => {
      const rowCompanyId = String(row?.companyId || row?.company_id || "").trim();
      const rowCompanyName = String(row?.company || row?.companyName || "").trim();

      if (!rowCompanyId) {
        return false;
      }

      return (userId && userDetailId(row) === userId) || (companyName && rowCompanyName === companyName);
    });

    return String(matchedUser?.companyId || matchedUser?.company_id || "").trim();
  }

  function normalizeUserSearchUser(user) {
    const id = userDetailId(user);
    const company = user?.company || user?.companyName || "";
    const companyId = companyDetailId(user);

    return {
      ...(user || {}),
      id,
      userId: id,
      name: user?.name || id,
      email: user?.email || "",
      companyId,
      company,
      companyName: company,
      role: user?.role || "",
      status: user?.status || "",
      engagedSeconds: Number(user?.engagedSeconds || 0),
      visitsCount: Number(user?.visitsCount || user?.visits || 0),
      featuresCount: Number(user?.featuresCount || 0),
      lastActive: user?.lastActive || "",
      lastActiveSort: Number(user?.lastActiveSort || 0)
    };
  }

  function readRecentUsers() {
    try {
      const value = globalScope.localStorage?.getItem(userSearchRecentStorageKey);
      const parsed = JSON.parse(value || "[]");

      return Array.isArray(parsed)
        ? parsed.map(normalizeUserSearchUser).filter((user) => user.id)
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
          .map(normalizeUserSearchUser)
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
    const normalized = normalizeUserSearchUser(user);

    if (!normalized.id) {
      return;
    }

    const users = readRecentUsers();
    writeRecentUsers([normalized, ...users.filter((item) => item.id !== normalized.id)]);
  }

  function userDetailHref(user) {
    const params = new URLSearchParams();
    const detailBaseUrl = document.body?.dataset.userDetailBaseUrl || "";
    const period = provider.coercePeriodKey(currentData?.period || getRequestedPeriod());
    const rangeByPeriod = {
      "7d": "last_7_days",
      "30d": "last_30_days",
      "90d": "last_90_days",
      "180d": "last_180_days"
    };

    if (!detailBaseUrl) {
      params.set("user_id", userDetailId(user));
      params.set("period", period);
      return `detail.html?${params.toString()}`;
    }

    const userUrl = new URL(
      detailBaseUrl.replace(/detail(?=\/|$)/, encodeURIComponent(userDetailId(user))),
      globalScope.location.origin
    );
    const rangeKey = rangeByPeriod[period] || rangeByPeriod[provider.DEFAULT_PERIOD] || "last_30_days";
    userUrl.searchParams.set("range", rangeKey);

    return `${userUrl.pathname}${userUrl.search}`;
  }

  function companyDetailHref(user) {
    const companyId = companyDetailId(user);
    const params = new URLSearchParams();
    const detailBaseUrl = document.body?.dataset.companyDetailBaseUrl || "";
    const period = provider.coercePeriodKey(currentData?.period || getRequestedPeriod());
    const rangeByPeriod = {
      "7d": "last_7_days",
      "30d": "last_30_days",
      "90d": "last_90_days",
      "180d": "last_180_days"
    };

    if (!companyId) {
      return "";
    }

    if (!detailBaseUrl) {
      params.set("company_id", companyId);
      params.set("period", period);
      return `../companies/detail.html?${params.toString()}`;
    }

    const companyUrl = new URL(
      detailBaseUrl.replace(/detail(?=\/|$)/, encodeURIComponent(companyId)),
      globalScope.location.origin
    );
    const rangeKey = rangeByPeriod[period] || rangeByPeriod[provider.DEFAULT_PERIOD] || "last_30_days";
    companyUrl.searchParams.set("range", rangeKey);

    return `${companyUrl.pathname}${companyUrl.search}`;
  }

  function getUserSearchMatches(query) {
    const normalizedQuery = normalizeUserSearchValue(query);

    if (userSearchUsesRemote() && !normalizedQuery) {
      const recentUsers = readRecentUsers();
      return (recentUsers.length
        ? recentUsers
        : (userSearchState.remoteQuery === normalizedQuery ? userSearchState.remoteResults : [])
      ).slice(0, 8);
    }

    if (userSearchUsesRemote()) {
      return userSearchState.remoteQuery === normalizedQuery ? userSearchState.remoteResults : [];
    }

    const rows = getUserSearchRows();

    if (!normalizedQuery) {
      return rows
        .slice()
        .sort((a, b) => a.name.localeCompare(b.name))
        .slice(0, 8);
    }

    return rows
      .filter((user) => `${user.name} ${user.email} ${user.company} ${user.role} ${user.status}`.toLowerCase().includes(normalizedQuery))
      .sort((a, b) => (Number(a.lastActiveSort) || 0) - (Number(b.lastActiveSort) || 0) || b.engagedSeconds - a.engagedSeconds)
      .slice(0, 8);
  }

  function closeUserSearchDropdown() {
    const { input, listbox } = userSearchElements();

    if (userSearchDebounceId) {
      globalScope.clearTimeout(userSearchDebounceId);
      userSearchDebounceId = 0;
    }

    userSearchState.isOpen = false;
    userSearchState.isLoading = false;
    userSearchState.activeIndex = -1;
    userSearchState.requestToken += 1;

    if (input) {
      input.setAttribute("aria-expanded", "false");
      input.removeAttribute("aria-activedescendant");
    }

    if (listbox) {
      listbox.hidden = true;
      listbox.innerHTML = "";
    }
  }

  function setUserSearchActiveIndex(nextIndex) {
    const { input, listbox } = userSearchElements();

    if (!listbox || !userSearchState.results.length) {
      userSearchState.activeIndex = -1;
      input?.removeAttribute("aria-activedescendant");
      return;
    }

    const count = userSearchState.results.length;
    userSearchState.activeIndex = (nextIndex + count) % count;

    listbox.querySelectorAll("[data-user-search-index]").forEach((option) => {
      const index = Number(option.getAttribute("data-user-search-index"));
      const isActive = index === userSearchState.activeIndex;

      option.dataset.active = String(isActive);
      option.setAttribute("aria-selected", String(isActive));
    });

    const activeId = `users-search-option-${userSearchState.activeIndex}`;
    input?.setAttribute("aria-activedescendant", activeId);
    document.getElementById(activeId)?.scrollIntoView({ block: "nearest" });
  }

  function openUserSearchResult(user) {
    if (!user) {
      return;
    }

    rememberRecentUser(user);
    globalScope.location.href = userDetailHref(user);
  }

  function renderUserSearchDropdown() {
    const { input, listbox } = userSearchElements();

    if (!input || !listbox) {
      return;
    }

    userSearchState.isOpen = true;
    input.setAttribute("aria-expanded", "true");
    listbox.hidden = false;

    if (!userSearchState.results.length) {
      userSearchState.activeIndex = -1;
      input.removeAttribute("aria-activedescendant");
      listbox.innerHTML = `<div class="company-search__empty" role="status">${userSearchState.isLoading ? "Loading users..." : "No users found"}</div>`;
      return;
    }

    listbox.innerHTML = userSearchState.results
      .map((user, index) => `
        <a
          id="users-search-option-${index}"
          href="${escapeHtml(userDetailHref(user))}"
          class="company-search__option"
          role="option"
          data-user-search-index="${index}"
          data-active="${String(index === userSearchState.activeIndex)}"
          aria-selected="${String(index === userSearchState.activeIndex)}">
          <span class="min-w-0">
            <span class="company-search__name">${escapeHtml(user.name)}</span>
            <span class="company-search__meta">${escapeHtml(userSearchMetadata(user))}</span>
          </span>
          <span class="company-search__open">Open \u2192</span>
        </a>
      `)
      .join("");

    setUserSearchActiveIndex(userSearchState.activeIndex);

    listbox.querySelectorAll("[data-user-search-index]").forEach((option) => {
      const index = Number(option.getAttribute("data-user-search-index"));

      option.addEventListener("mouseenter", () => {
        setUserSearchActiveIndex(index);
      });

      option.addEventListener("click", (event) => {
        if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
          return;
        }

        rememberRecentUser(userSearchState.results[index]);
        closeUserSearchDropdown();
      });

      option.addEventListener("auxclick", (event) => {
        if (event.button === 1) {
          rememberRecentUser(userSearchState.results[index]);
        }
      });
    });
  }

  function updateUserSearch(query) {
    if (userSearchDebounceId) {
      globalScope.clearTimeout(userSearchDebounceId);
      userSearchDebounceId = 0;
    }

    const normalizedQuery = normalizeUserSearchValue(query);
    const usesRemote = userSearchUsesRemote();
    const shouldLoadFallback = usesRemote && !normalizedQuery && !readRecentUsers().length;
    const shouldFetchRemote = usesRemote && (Boolean(normalizedQuery) || shouldLoadFallback) && userSearchState.remoteQuery !== normalizedQuery;
    userSearchState.query = query;

    if (shouldFetchRemote) {
      userSearchState.remoteResults = [];
    }

    userSearchState.results = getUserSearchMatches(query);
    userSearchState.activeIndex = userSearchState.results.length ? 0 : -1;
    userSearchState.isLoading = shouldFetchRemote;
    renderUserSearchDropdown();

    if (!shouldFetchRemote) {
      return;
    }

    const requestToken = userSearchState.requestToken + 1;
    userSearchState.requestToken = requestToken;

    provider.searchUsers(query, {
      period: currentData?.period || getRequestedPeriod(),
      limit: 20,
      alphabetical: shouldLoadFallback
    })
      .then((remoteUsers) => {
        if (
          requestToken !== userSearchState.requestToken ||
          !userSearchState.isOpen ||
          normalizeUserSearchValue(userSearchState.query) !== normalizedQuery
        ) {
          return;
        }

        userSearchState.remoteQuery = normalizedQuery;
        userSearchState.remoteResults = Array.isArray(remoteUsers)
          ? remoteUsers.map(normalizeUserSearchUser).filter((user) => user.id)
          : [];
        userSearchState.isLoading = false;
        userSearchState.results = getUserSearchMatches(query);
        userSearchState.activeIndex = userSearchState.results.length ? 0 : -1;
        renderUserSearchDropdown();
      })
      .catch(() => {
        if (requestToken !== userSearchState.requestToken) {
          return;
        }

        userSearchState.remoteQuery = normalizedQuery;
        userSearchState.remoteResults = [];
        userSearchState.isLoading = false;
        userSearchState.results = [];
        userSearchState.activeIndex = -1;
        renderUserSearchDropdown();
      });
  }

  function scheduleUserSearchUpdate(query) {
    userSearchState.query = query;

    if (userSearchDebounceId) {
      globalScope.clearTimeout(userSearchDebounceId);
    }

    userSearchDebounceId = globalScope.setTimeout(() => {
      updateUserSearch(query);
    }, userSearchDebounceMs);
  }

  function refreshUserSearchResults() {
    const { input } = userSearchElements();

    if (!userSearchMounted || !input) {
      return;
    }

    if (document.activeElement === input || userSearchState.isOpen) {
      updateUserSearch(input.value);
    }
  }

  function mountUserSearch() {
    const { root, input } = userSearchElements();

    if (!root || !input || userSearchMounted) {
      return;
    }

    userSearchMounted = true;

    root.addEventListener("overview-quick-jumper:close", closeUserSearchDropdown);

    input.addEventListener("input", () => {
      scheduleUserSearchUpdate(input.value);
    });

    input.addEventListener("focus", () => {
      updateUserSearch(input.value);
    });

    input.addEventListener("click", () => {
      updateUserSearch(input.value);
    });

    input.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        closeUserSearchDropdown();
        return;
      }

      if ((event.key === "ArrowDown" || event.key === "ArrowUp" || event.key === "Enter") && userSearchDebounceId) {
        updateUserSearch(input.value);
      }

      if ((event.key === "ArrowDown" || event.key === "ArrowUp") && !userSearchState.isOpen) {
        event.preventDefault();
        updateUserSearch(input.value);
        return;
      }

      if (!userSearchState.isOpen || !userSearchState.results.length) {
        return;
      }

      if (event.key === "ArrowDown") {
        event.preventDefault();
        setUserSearchActiveIndex(userSearchState.activeIndex + 1);
        return;
      }

      if (event.key === "ArrowUp") {
        event.preventDefault();
        setUserSearchActiveIndex(userSearchState.activeIndex - 1);
        return;
      }

      if (event.key === "Enter" && userSearchState.activeIndex >= 0) {
        event.preventDefault();
        openUserSearchResult(userSearchState.results[userSearchState.activeIndex]);
      }
    });

    document.addEventListener("pointerdown", (event) => {
      if (!root.contains(event.target)) {
        closeUserSearchDropdown();
      }
    });
  }

  function userMatchesFeature(user, feature) {
    if (!feature) {
      return true;
    }

    if (user.topFeature === feature) {
      return true;
    }

    if ((user.topFeatures || []).some((item) => item.feature === feature)) {
      return true;
    }

    return (user.pageGroups || []).some((item) => item.name === feature);
  }

  function userStableKey(user) {
    return String(user?.id || user?.userId || user?.email || user?.name || "").toLowerCase();
  }

  function stableHash(value) {
    const text = String(value || "");
    let hash = 2166136261;

    for (let index = 0; index < text.length; index += 1) {
      hash ^= text.charCodeAt(index);
      hash = Math.imul(hash, 16777619);
    }

    return hash >>> 0;
  }

  function stableUnit(value) {
    return stableHash(value) / 4294967295;
  }

  function userAvgSessionSeconds(user) {
    const explicitAvg = Number(user?.avgSessionSeconds);

    if (Number.isFinite(explicitAvg) && explicitAvg > 0) {
      return explicitAvg;
    }

    const engagedSeconds = Number(user?.engagedSeconds) || 0;
    const sessionsCount = Number(user?.sessionsCount) || Number(user?.sessionCount) || 0;

    return sessionsCount > 0 ? engagedSeconds / sessionsCount : 0;
  }

  function userTableSortValue(user, sortKey) {
    if (sortKey === "avgSessionSeconds") {
      return userAvgSessionSeconds(user);
    }

    if (sortKey === "avgVisitSeconds") {
      const explicitAvg = Number(user?.avgVisitSeconds);

      if (Number.isFinite(explicitAvg) && explicitAvg > 0) {
        return explicitAvg;
      }

      const visits = Number(user?.visitsCount) || 0;
      const engaged = Number(user?.engagedSeconds) || 0;

      return visits > 0 ? engaged / visits : 0;
    }

    return Number(user?.[sortKey]) || 0;
  }

  function getFilteredUsers() {
    const company = readFilterValue("users-company-filter");
    const feature = readFilterValue("users-feature-filter");
    const tableCompany = readFilterValue("users-table-company");
    const tableRole = readFilterValue("users-table-role");
    const tableStatus = readFilterValue("users-table-status");
    const query = readFilterValue("users-table-search").trim().toLowerCase();
    const identifiedOnly = document.getElementById("users-identified-filter")?.checked !== false;
    const sortKey = usersTableState.sortKey;
    const direction = usersTableState.sortDirection === "asc" ? 1 : -1;

    const rows = (currentData?.users || [])
      .filter((user) => !identifiedOnly || user.identified)
      .filter((user) => !company || user.company === company)
      .filter((user) => !tableCompany || user.company === tableCompany)
      .filter((user) => !tableRole || user.role === tableRole)
      .filter((user) => !tableStatus || user.status === tableStatus)
      .filter((user) => userMatchesFeature(user, feature))
      .filter((user) => {
        if (!query) {
          return true;
        }

        return `${user.name} ${user.email} ${user.company} ${user.role}`.toLowerCase().includes(query);
      });

    return rows.slice().sort((a, b) => {
      if (usersTableNumericSortKeys.has(sortKey)) {
        return (userTableSortValue(a, sortKey) - userTableSortValue(b, sortKey)) * direction ||
          userStableKey(a).localeCompare(userStableKey(b));
      }

      if (sortKey === "status") {
        return ((statusMeta[a.status]?.sort ?? 99) - (statusMeta[b.status]?.sort ?? 99)) * direction ||
          userStableKey(a).localeCompare(userStableKey(b));
      }

      return String(a?.[sortKey] || "").localeCompare(String(b?.[sortKey] || "")) * direction ||
        userStableKey(a).localeCompare(userStableKey(b));
    });
  }

  // Card values arrive already formatted, sparkline points do not, so the daily
  // series needs its own unit or engaged time reads as a bare second count.
  const kpiTrendValueFormats = {
    engagedPerUser: "duration"
  };

  function kpiTrendValueFormat(kpi) {
    return kpi?.sparklineValueType || kpiTrendValueFormats[kpi?.key] || "number";
  }

  function formatKpiTrendValue(value, valueFormat) {
    if (valueFormat === "duration") {
      return formatDurationWithSeconds(value);
    }

    if (valueFormat === "percent") {
      return formatPercentDecimal(value);
    }

    return formatNumber(value);
  }

  function formatKpiHeadlineValue(kpi) {
    if (typeof kpi?.value !== "number") {
      return kpi?.value ?? "";
    }

    if (kpi.sparklineScope === "daily") {
      return averageCountFormatter.format(kpi.value);
    }

    return formatNumber(kpi.value);
  }

  function renderKpiCards(data) {
    const container = document.getElementById("users-kpis");
    const grid = container?.querySelector("[data-users-kpis-grid]");
    const template = document.getElementById("users-kpi-card-template");

    if (!container || !grid || !template) {
      return;
    }

    grid.innerHTML = "";

    data.kpis.forEach((kpi, index) => {
      const fragment = template.content.cloneNode(true);
      const labelElement = fragment.querySelector("[data-users-kpi-label]");
      const valueElement = fragment.querySelector("[data-users-kpi-value]");
      const deltaElement = fragment.querySelector("[data-users-kpi-delta]");
      const trendElement = fragment.querySelector("[data-users-kpi-trend]");

      if (labelElement) {
        labelElement.textContent = kpi.label;
      }

      if (valueElement) {
        valueElement.textContent = formatKpiHeadlineValue(kpi);
      }

      if (deltaElement) {
        deltaElement.textContent = kpi.deltaLabel || formatDeltaLabel(kpi.delta);
        deltaElement.setAttribute("data-delta-direction", kpi.deltaType || "neutral");
      }

      if (trendElement) {
        trendElement.setAttribute("data-users-kpi-index", String(index));
      }

      grid.appendChild(fragment);
    });

    container.querySelectorAll("[data-users-kpi-index]").forEach((element) => {
      const index = Number(element.getAttribute("data-users-kpi-index"));
      const kpi = data.kpis[index];

      if (kpi?.sparkline?.length) {
        mountChart(element, createKpiTrendOption(
          kpi.sparkline,
          kpi.deltaType,
          kpi.sparklineLabels || data.dailyActiveTrend?.labels || [],
          kpi.sparklineLabel || kpi.label,
          kpiTrendValueFormat(kpi),
          kpi.sparklineScope,
          kpi.sparklineRender
        ));
      }
    });
  }

  function createKpiTrendOption(
    values,
    deltaType,
    labels = [],
    metricLabel = "Value",
    valueFormat = "number",
    trendScope = "period_to_date",
    render = "area"
  ) {
    const lineColor = tailwindColor("blue-400");
    const fillColor = tailwindColor("blue-50");
    const series = values.map((value) => {
      if (value === null || value === undefined) {
        return null;
      }

      const numericValue = Number(value);
      return Number.isFinite(numericValue) ? numericValue : null;
    });
    const numericSeries = finiteNumericValues(series);
    const trendLabels = alignTrendLabels(labels, series.length);

    return {
      animation: false,
      tooltip: analyticsTooltips.echarts({
        trigger: "axis",
        appendTo: "body",
        confine: false,
        axisPointer: {
          type: "line",
          lineStyle: {
            color: tailwindColor("slate-300"),
            width: 1
          }
        },
        formatter: (params) => {
          const item = Array.isArray(params) ? params[0] : params;
          const index = Number(item?.dataIndex) || 0;
          const dateLabel = formatTrendDateLabel(trendLabels[index] || item?.axisValueLabel || item?.name || "");
          const title = trendScope === "daily"
            ? (dateLabel || "Daily value")
            : (dateLabel ? `Through ${dateLabel}` : "Period to date");
          const pointValue = series[index];

          return analyticsTooltips.render({
            title,
            rows: [{
              label: metricLabel,
              value: pointValue === null
                ? "No activity"
                : formatKpiTrendValue(pointValue ?? item?.value ?? 0, valueFormat),
              marker: { color: lineColor }
            }]
          });
        }
      }),
      grid: { left: 0, right: 0, top: 4, bottom: 0 },
      xAxis: {
        type: "category",
        show: false,
        boundaryGap: false,
        data: trendLabels.length ? trendLabels : series.map((_, index) => index + 1)
      },
      yAxis: {
        type: "value",
        show: false,
        min: numericSeries.length ? Math.min(...numericSeries) : 0,
        max: compactAxisMax(series)
      },
      series: [
        {
          type: "line",
          smooth: trendScope !== "daily",
          showSymbol: false,
          data: series,
          // A share is read against its own range, so it carries no fill down
          // to zero the way a count does.
          ...(render === "area" ? { areaStyle: { color: fillColor } } : {}),
          lineStyle: { color: lineColor, width: 2 },
          emphasis: {
            disabled: true
          }
        }
      ]
    };
  }

  function renderInsights(data) {
    const container = document.getElementById("users-insights");

    if (!container) {
      return;
    }

    container.innerHTML = (data.insights || [])
      .map((insight) => {
        const badgeClass = insight.deltaType === "negative"
          ? "users-badge--red"
          : insight.deltaType === "warning"
            ? "users-badge--amber"
            : "users-badge--green";

        return `
          <article class="users-card px-4 py-4">
            <div class="flex items-start justify-between gap-3">
              <div class="min-w-0">
                <p class="text-xs font-medium uppercase text-slate-500">${escapeHtml(insight.label)}</p>
                <h3 class="mt-2 truncate text-base font-semibold text-slate-900">${escapeHtml(insight.title)}</h3>
                <p class="mt-1 truncate text-sm text-slate-500">${escapeHtml(insight.company)}</p>
              </div>
              <span class="users-badge ${badgeClass}">${escapeHtml(insight.delta)}</span>
            </div>
            <p class="mt-4 text-sm font-medium text-slate-700">${escapeHtml(insight.metric)}</p>
          </article>
        `;
      })
      .join("");
  }

  function setSegmentedButtonsActive(selector, activeValue, dataAttribute) {
    document.querySelectorAll(selector).forEach((button) => {
      const isActive = button.getAttribute(dataAttribute) === activeValue;

      button.classList.toggle("bg-slate-900", isActive);
      button.classList.toggle("text-white", isActive);
      button.classList.toggle("bg-white", !isActive);
      button.classList.toggle("text-slate-700", !isActive);
      button.classList.toggle("hover:bg-slate-50", !isActive);
      button.setAttribute("aria-pressed", String(isActive));
    });
  }

  function formatPercentDecimal(value) {
    const number = Math.round((Number(value) || 0) * 10) / 10;

    return `${number}%`;
  }

  function formatPercentRounded(value) {
    return `${Math.round(Number(value) || 0)}%`;
  }

  const STATUS_MIX_SELECTED_LABEL = "Selected period";
  const STATUS_MIX_PREVIOUS_LABEL = "Previous period";

  function statusMixDistributionRow(distribution) {
    const byLabel = new Map(
      (Array.isArray(distribution) ? distribution : []).map((row) => [
        userStatusMetaFor(row.status).label,
        row
      ])
    );

    return userStatusOrderLabels.map((status) => ({
      status,
      count: Number(byLabel.get(status)?.count) || 0,
      color: statusColor(status),
      definition: userStatusMetaFor(status).definition || ""
    }));
  }

  // Same treatment as Company health distribution: below this width a segment
  // cannot hold a legible label, so it borrows room from the wide ones.
  function statusMixSegments(statuses, rowIndex) {
    const total = statuses.reduce((sum, item) => sum + item.count, 0);
    const minPct = 4.5;
    const rawSegments = statuses.map((item) => {
      const rawPct = total ? (item.count / total) * 100 : 0;

      return {
        item,
        rawPct,
        isSmall: rawPct > 0 && rawPct < minPct
      };
    });
    const visibleSegments = rawSegments.filter((segment) => segment.rawPct > 0);
    const smallSegments = visibleSegments.filter((segment) => segment.isSmall);
    const regularSegments = visibleSegments.filter((segment) => !segment.isSmall);
    const smallPctTotal = Math.min(42, smallSegments.length * minPct);
    const regularRawTotal = regularSegments.reduce((sum, segment) => sum + segment.rawPct, 0) || 1;
    const regularPctTotal = Math.max(0, 100 - smallPctTotal);
    const smallPct = smallSegments.length ? smallPctTotal / smallSegments.length : 0;
    let cursor = 0;

    return visibleSegments.map((segment) => {
      const { item } = segment;
      const widthPct = segment.isSmall ? smallPct : (segment.rawPct / regularRawTotal) * regularPctTotal;
      const x0 = cursor;
      const x1 = cursor + widthPct;
      const labelText = widthPct < 5.5
        ? formatNumber(item.count)
        : `${item.status}\n${formatNumber(item.count)}`;

      cursor = x1;

      return {
        ...item,
        rowIndex,
        pct: segment.rawPct,
        pctLabel: formatPercentRounded(segment.rawPct),
        widthPct,
        labelText,
        value: [x0, x1, rowIndex]
      };
    });
  }

  function createStatusMixComparisonOption(selectedDistribution, previousDistribution) {
    // Selected period on top: it is what the reader came for, and the previous
    // period underneath is the thing it is measured against.
    const rows = [
      { label: STATUS_MIX_SELECTED_LABEL, statuses: statusMixDistributionRow(selectedDistribution) },
      { label: STATUS_MIX_PREVIOUS_LABEL, statuses: statusMixDistributionRow(previousDistribution) }
    ];
    const segments = rows.flatMap((row, rowIndex) => statusMixSegments(row.statuses, rowIndex));

    return {
      animation: false,
      tooltip: analyticsTooltips.echarts({
        trigger: "item",
        confine: true,
        formatter: (params) => {
          const item = params.data || {};

          return analyticsTooltips.render({
            title: `${rows[item.rowIndex]?.label || ""} — ${item.status || ""}`,
            rows: [
              { label: "Users", value: formatNumber(item.count || 0), marker: { color: item.color } },
              { label: "Share", value: item.pctLabel || "0%" },
              ...(item.definition ? [{ label: "Definition", value: item.definition }] : [])
            ]
          });
        }
      }),
      grid: {
        left: 104,
        right: 8,
        top: 18,
        bottom: 18
      },
      xAxis: {
        type: "value",
        min: 0,
        max: 100,
        show: false
      },
      yAxis: {
        type: "category",
        inverse: true,
        data: rows.map((row) => row.label),
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: {
          color: tailwindColor("slate-600"),
          fontSize: 12,
          fontWeight: 500
        }
      },
      series: [
        {
          type: "custom",
          data: segments,
          renderItem: (params, api) => {
            const item = segments[params.dataIndex] || {};
            const start = api.coord([api.value(0), api.value(2)]);
            const end = api.coord([api.value(1), api.value(2)]);
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
                  shape: { x, y, width, height, r: 5 },
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

  function createEngagementBucketBarOption(rows) {
    const buckets = Array.isArray(rows) ? rows : [];
    const total = buckets.reduce((sum, item) => sum + (Number(item.count) || 0), 0);
    const barColor = tailwindColor("c-light-blue");

    return {
      animation: false,
      tooltip: analyticsTooltips.echarts({
        trigger: "item",
        confine: true,
        formatter: (params) => {
          const row = buckets[params.dataIndex] || {};
          const count = Number(row.count) || 0;
          const pct = total ? count / total * 100 : 0;

          return analyticsTooltips.render({
            title: row.label || "",
            rows: [
              { label: "Users", value: formatNumber(count) },
              { label: "Share", value: formatPercentDecimal(pct) }
            ]
          });
        }
      }),
      grid: {
        left: 64,
        right: 64,
        top: 14,
        bottom: 34
      },
      xAxis: {
        type: "value",
        axisLine: { show: true, lineStyle: { color: tailwindColor("slate-300") } },
        axisTick: { show: false },
        axisLabel: { color: tailwindColor("slate-500"), formatter: formatNumber },
        splitLine: { show: false }
      },
      yAxis: {
        type: "category",
        inverse: true,
        data: buckets.map((item) => item.label),
        axisLine: { show: true, lineStyle: { color: tailwindColor("slate-300") } },
        axisTick: { show: false },
        axisLabel: { color: tailwindColor("slate-700") },
        splitLine: { show: false }
      },
      series: [
        {
          name: "Users",
          type: "bar",
          barWidth: 26,
          data: buckets.map((item) => Number(item.count) || 0),
          itemStyle: {
            borderRadius: [0, 5, 5, 0],
            color: barColor
          },
          label: {
            show: true,
            position: "right",
            color: tailwindColor("slate-600"),
            fontSize: 12,
            fontWeight: 500,
            formatter: (params) => formatNumber(params.value)
          }
        }
      ]
    };
  }

  function mountStatusMixChart(element, option) {
    return mountChart(element, option);
  }

  function mountEngagementDistribution(data) {
    mountChart(
      document.getElementById("users-engagement-bucket-chart"),
      createEngagementBucketBarOption(data.engagementBuckets || [])
    );
    mountStatusMixChart(
      document.getElementById("users-status-distribution-chart"),
      createStatusMixComparisonOption(
        data.statusDistribution || [],
        data.previousStatusDistribution || []
      )
    );
  }

  function userCell(user) {
    const userNameText = user.name || "User";
    const userEmailText = String(user.email || "").trim();
    const userName = escapeHtml(userNameText);
    const userEmail = escapeHtml(userEmailText);
    const tooltipClass = userEmailText ? "users-name-tooltip metric-header-tooltip" : "users-name-tooltip";
    const ariaLabel = userEmailText ? `${userNameText}, ${userEmailText}` : userNameText;

    return `
      <div class="flex min-w-0 items-center">
        <a href="${escapeHtml(userDetailHref(user))}" class="${tooltipClass} text-sky-800 hover:text-sky-900" aria-label="${escapeHtml(ariaLabel)}">
          <span class="block truncate font-medium">${userName}</span>
          ${userEmailText ? `<span class="metric-header-tooltip__content" role="tooltip">${userEmail}</span>` : ""}
        </a>
      </div>
    `;
  }

  function companyCell(user) {
    const companyNameText = user?.company || user?.companyName || "-";
    const companyName = escapeHtml(companyNameText);
    const href = companyDetailHref(user);

    if (!href) {
      return `<span class="font-medium text-slate-900">${companyName}</span>`;
    }

    return `<a href="${escapeHtml(href)}" class="font-medium text-sky-800 underline-offset-2 hover:underline">${companyName}</a>`;
  }

  function emptyAreaAdoptionCell(area) {
    return {
      productArea: area,
      used: false,
      engagedSeconds: 0,
      visits: 0,
      clicks: 0
    };
  }

  function buildUserAreaAdoption(user) {
    const cells = new Map(productAreas.map((area) => [area, emptyAreaAdoptionCell(area)]));
    const pageGroupAreas = new Set();

    (user.pageGroups || []).forEach((group) => {
      const area = productAreas.includes(group.name) ? group.name : featureProductArea(group.name);
      const cell = cells.get(area);

      if (!cell) {
        return;
      }

      pageGroupAreas.add(area);
      cell.engagedSeconds += Number(group.engagedSeconds) || 0;
      cell.visits += Number(group.visits) || 0;
      cell.clicks += Number(group.clicks) || 0;
      cell.used = cell.engagedSeconds > 0 || cell.visits > 0 || cell.clicks > 0;
    });

    (user.topFeatures || []).forEach((feature) => {
      const area = feature.productArea || feature.product_area || featureProductArea(feature.feature);
      const cell = cells.get(area);

      if (!cell || pageGroupAreas.has(area)) {
        return;
      }

      cell.engagedSeconds += Number(feature.engagedSeconds) || 0;
      cell.visits += Number(feature.visits) || 0;
      cell.clicks += Number(feature.clicks) || 0;
      cell.used = cell.engagedSeconds > 0 || cell.visits > 0 || cell.clicks > 0;
    });

    return productAreas.map((area) => cells.get(area) || emptyAreaAdoptionCell(area));
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

  function adoptionCellTooltip(cell, user, maxEngagedSeconds) {
    const tooltipId = `users-adoption-cell-tooltip-${adoptionCellTooltipId}`;
    const userName = user.name || "User";
    const relativeActivityPct = adoptionCellRelativeActivityPct(cell, maxEngagedSeconds);
    const usageLabel = cell.used && relativeActivityPct <= 0 ? adoptionCellIntensityGrade(1).label : adoptionCellUsageLabel(relativeActivityPct);
    const relativeActivityLabel = formatPercent(relativeActivityPct);
    const tooltipRows = [
      { label: "Product area", value: cell.productArea },
      { label: "Relative activity", value: relativeActivityLabel },
      { label: "Usage intensity", value: usageLabel }
    ];

    adoptionCellTooltipId += 1;

    if (!cell.used) {
      return {
        tooltipId,
        tooltipText: `${userName}. Not used yet. ${analyticsTooltips.text(tooltipRows)}`,
        tooltipHtml: analyticsTooltips.render({ title: userName, rows: tooltipRows })
      };
    }

    tooltipRows.push(
      { label: "Engaged", value: formatDuration(cell.engagedSeconds) },
      { label: "Visits", value: formatNumber(cell.visits) },
      { label: "Clicks", value: formatNumber(cell.clicks) }
    );

    return {
      tooltipId,
      tooltipText: `${userName}. Used during selected period. ${analyticsTooltips.text(tooltipRows)}`,
      tooltipHtml: analyticsTooltips.render({ title: userName, rows: tooltipRows })
    };
  }

  function adoptionMatrixCell(cell, user, maxEngagedSeconds) {
    const tooltip = adoptionCellTooltip(cell, user, maxEngagedSeconds);

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
        style="--area-bg-color:${rgbaFromHex(productAreaColor(cell.productArea), intensity)};"
        tabindex="0"
        aria-label="${escapeHtml(tooltip.tooltipText)}"
        aria-describedby="${tooltip.tooltipId}">
        <span id="${tooltip.tooltipId}" class="metric-header-tooltip__content" role="tooltip">${tooltip.tooltipHtml}</span>
      </span>
    `;
  }

  function adoptionMatrixCellGroup(user, areaAdoption, maxEngagedSeconds) {
    return `
      <div class="companies-adoption-matrix" aria-label="${escapeHtml(`${user.name || "User"} product area adoption`)}">
        ${(areaAdoption || buildUserAreaAdoption(user))
          .map((cell) => adoptionMatrixCell(cell, user, maxEngagedSeconds))
          .join("")}
      </div>
    `;
  }

  function progressBar(value, colorName = "c-blue", label = "") {
    const pct = clampPct(value);

    return `
      <span class="users-progress" aria-label="${escapeHtml(label || `${pct}%`)}">
        <span class="users-progress__bar" style="width:${pct}%; --progress-color: var(--color-${escapeHtml(colorName)});"></span>
      </span>
    `;
  }

  function microBar(value, maxValue) {
    const pct = Math.max(4, Math.round((Number(value) / Math.max(Number(maxValue) || 1, 1)) * 100));

    return `
      <span class="users-micro-bar" aria-hidden="true">
        <span class="users-micro-bar__bar" style="display:block;width:${clampPct(pct)}%;"></span>
      </span>
    `;
  }

  function formatValueByType(value, valueType) {
    if (valueType === "duration") {
      return formatDuration(value);
    }

    if (valueType === "percent") {
      return formatPercent(value);
    }

    return formatNumber(value);
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
      return formatDuration(numericValue);
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
    return `${prefix}${rounded}%`;
  }

  function renderSplitChangeDelta(currentValue, valueType, deltaValue, unit, maxAbsDelta, label, previousValue, deltaLabel = "", comparisonAvailable = true, invert = false) {
    const direction = deltaDirection(deltaValue, invert);
    const trackWidth = direction === "negative" ? 17 : 36;
    const barWidth = Number(deltaValue) === 0 ? 6 : Math.max(4, Math.round((Math.abs(Number(deltaValue) || 0) / Math.max(maxAbsDelta, 1)) * trackWidth));
    const formattedDelta = formatDeltaLabel(deltaValue);
    const tooltipId = `users-period-change-tooltip-${periodChangeTooltipId}`;
    const hasExplicitPrevious = previousValue !== null && previousValue !== undefined && Number.isFinite(Number(previousValue));
    const resolvedPreviousValue = hasExplicitPrevious
      ? Number(previousValue)
      : deltaLabel === "New"
        ? 0
        : previousPeriodValue(currentValue, deltaValue, unit);
    const changeLabel = resolvedPreviousValue === 0 && Number(currentValue) > 0 ? "New" : formatPeriodDelta(deltaValue, unit);
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

    periodChangeTooltipId += 1;

    return `
      <div class="pages-change-delta metric-header-tooltip" data-change-direction="${direction}" style="--pages-change-bar-width: ${barWidth}px;" tabindex="0" aria-label="${escapeHtml(`${label}. ${analyticsTooltips.text(tooltipRows)}`)}" aria-describedby="${tooltipId}">
        <span class="pages-change-delta__plot">
          <span class="pages-change-delta__bar pages-change-delta__bar--${direction}"></span>
        </span>
        <span class="pages-change-delta__label ${deltaClass(deltaValue, invert)}">${escapeHtml(formattedDelta)}</span>
        <span id="${tooltipId}" class="metric-header-tooltip__content" role="tooltip">
          ${analyticsTooltips.render({ rows: tooltipRows })}
        </span>
      </div>
    `;
  }

  function renderSplitMetricCell(row, metric, maxValues, maxAbsDelta) {
    const value = Number(row[metric.key]) || 0;
    const maxValue = Math.max(maxValues[metric.key] || 1, 1);
    const valueLabel = formatValueByType(value, metric.valueType);
    const barValue = metric.barMode === "percent" ? value : (value / maxValue) * 100;
    const deltaValue = Number(row[metric.deltaKey]) || 0;

    return `
      <td class="pages-split-change-cell py-3.5 pr-6 align-middle" data-split-metric="${escapeHtml(metric.key)}">
        <div class="pages-split-change-group">
          <div class="pages-metric-value">${metricBarValue(valueLabel, barValue, metric.label)}</div>
          ${renderSplitChangeDelta(value, metric.valueType, deltaValue, metric.deltaUnit || "%", maxAbsDelta, metric.label, row[metric.previousKey], row[metric.deltaLabelKey], row.comparisonAvailable !== false && row.comparison_available !== false)}
        </div>
      </td>
    `;
  }

  function renderBarMetricCell(row, metric, maxValues) {
    const value = Number(row[metric.key]) || 0;
    const maxValue = Math.max(maxValues[metric.key] || 1, 1);
    const valueLabel = formatValueByType(value, metric.valueType);
    const barValue = metric.barMode === "percent" ? value : (value / maxValue) * 100;

    return `
      <td class="py-3.5 pr-6 align-middle" data-split-metric="${escapeHtml(metric.key)}">
        <div class="pages-metric-value">${metricBarValue(valueLabel, barValue, metric.label)}</div>
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

  function syncSplitChangeValueWidths(root) {
    if (!root) {
      return;
    }

    const cellsByMetric = new Map();

    root.querySelectorAll(".pages-split-change-cell").forEach((cell) => {
      cell.style.removeProperty("--pages-split-value-width");
      const metric = cell.dataset.splitMetric || "default";

      if (!cellsByMetric.has(metric)) {
        cellsByMetric.set(metric, []);
      }

      cellsByMetric.get(metric).push(cell);
    });

    cellsByMetric.forEach((cells) => {
      const width = Math.max(
        ...cells.map((cell) => {
          const valueElement = cell.querySelector(".pages-metric-value");

          return valueElement ? Math.ceil(valueElement.getBoundingClientRect().width) : 0;
        }),
        0
      );

      cells.forEach((cell) => {
        cell.style.setProperty("--pages-split-value-width", `${width}px`);
      });
    });
  }

  function syncAllSplitChangeValueWidths() {
    syncSplitChangeValueWidths(document.getElementById("users-table-body"));
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

  function updateUsersTableSortButtons() {
    document.querySelectorAll("[data-users-table-sort]").forEach((button) => {
      const isActive = button.getAttribute("data-users-table-sort") === usersTableState.sortKey;

      button.setAttribute("data-sort-direction", isActive ? usersTableState.sortDirection : "");
      button.setAttribute("aria-pressed", isActive ? "true" : "false");
    });
  }

  function getUsersTablePageCount(rows) {
    const totalPages = Number(usersTablePagination()?.totalPages);

    if (Number.isFinite(totalPages) && totalPages > 0) {
      return Math.max(1, Math.ceil(totalPages));
    }

    return Math.max(1, Math.ceil(rows.length / usersTablePageSize));
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
    const container = document.querySelector("[data-users-pagination]");

    if (!container) {
      return;
    }

    if (totalPages <= 1) {
      container.hidden = true;
      container.innerHTML = "";
      return;
    }

    const currentPage = Math.min(totalPages, Math.max(1, usersTableState.page));
    const disabledAttr = usersTableState.isLoading ? " disabled" : "";

    container.hidden = false;
    container.innerHTML = `
      ${
        currentPage > 2
          ? `<button type="button" class="font-medium text-sky-700 hover:text-sky-800" data-users-page-action="first"${disabledAttr}>Go to first page</button>`
          : `<span aria-hidden="true"></span>`
      }
      <div class="flex items-center justify-between gap-6 sm:justify-end">
        ${
          currentPage > 1
            ? `<button type="button" class="inline-flex h-8 w-8 items-center justify-center text-sky-700 hover:text-sky-800" data-users-page-action="previous" aria-label="Back to previous page"${disabledAttr}>${usersPaginationIcon("previous")}</button>`
            : `<span class="invisible h-8 w-8" aria-hidden="true"></span>`
        }
        <span class="text-slate-700">Page ${currentPage}/${totalPages}</span>
        ${
          currentPage < totalPages
            ? `<button type="button" class="inline-flex items-center gap-2 rounded-md border border-slate-200 bg-transparent px-4 py-3 font-medium text-sky-700 duration-150 hover:bg-slate-100" data-users-page-action="next"${disabledAttr}>Continue to next page ${usersPaginationIcon("next")}</button>`
            : ""
        }
      </div>
    `;

    container.querySelectorAll("[data-users-page-action]").forEach((button) => {
      button.addEventListener("click", () => {
        const action = button.getAttribute("data-users-page-action");
        const targetPage =
          action === "first"
            ? 1
            : action === "previous"
              ? Math.max(1, usersTableState.page - 1)
              : Math.min(totalPages, usersTableState.page + 1);

        requestUsersTablePage(targetPage);
      });
    });
  }

  function setUsersTableLoading(isLoading) {
    const overlay = document.querySelector("[data-users-table-loading]");
    const tableShell = document.querySelector("[data-users-table-scroll]");
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

  function isUsersTableHeaderVisible() {
    const tableHead = document.querySelector("[data-users-table-scroll] thead");

    if (!tableHead) {
      return true;
    }

    const stickyTop = document.querySelector("body > nav")?.getBoundingClientRect().height || 48;
    const rect = tableHead.getBoundingClientRect();

    return rect.top >= stickyTop && rect.bottom <= globalScope.innerHeight;
  }

  function scrollUsersTableHeaderIntoView() {
    const tableHead = document.querySelector("[data-users-table-scroll] thead");

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

  function usersTableRequestOptions(targetPage) {
    const globalCompany = readFilterValue("users-company-filter");
    const tableCompany = readFilterValue("users-table-company");
    const identifiedControl = document.getElementById("users-identified-filter");

    return {
      page: targetPage,
      page_size: usersTablePageSize,
      sort: usersTableState.sortKey,
      direction: usersTableState.sortDirection,
      period: currentData?.period || provider.DEFAULT_PERIOD,
      company: tableCompany || globalCompany,
      role: readFilterValue("users-table-role"),
      status: readFilterValue("users-table-status"),
      q: readFilterValue("users-table-search").trim(),
      identified: (!identifiedControl || identifiedControl.checked) ? "1" : "0",
      feature: readFilterValue("users-feature-filter")
    };
  }

  function loadUsersTablePage(targetPage, options = {}) {
    if (!serverUsersTableEnabled()) {
      return false;
    }

    usersTableState.isLoading = true;
    usersTableState.loadingToken += 1;

    const token = usersTableState.loadingToken;
    const rows = currentData?.users || [];

    setUsersTableLoading(true);
    renderUsersPagination(getUsersTablePageCount(rows));

    if (options.scrollToTable && !isUsersTableHeaderVisible()) {
      scrollUsersTableHeaderIntoView();
    }

    Promise.resolve()
      .then(() => provider.loadUsersTable(usersTableRequestOptions(targetPage)))
      .then((payload) => {
        if (token !== usersTableState.loadingToken || !applyUsersTablePayload(payload)) {
          return;
        }

        renderUsersTable();
      })
      .catch(() => null)
      .finally(() => {
        if (token !== usersTableState.loadingToken) {
          return;
        }

        usersTableState.isLoading = false;
        setUsersTableLoading(false);
        renderUsersPagination(getUsersTablePageCount(currentData?.users || []));
      });

    return true;
  }

  function simulateUsersTableLoad(onComplete) {
    if (usersTableState.isLoading) {
      return;
    }

    usersTableState.isLoading = true;
    usersTableState.loadingToken += 1;

    const token = usersTableState.loadingToken;
    const rows = getFilteredUsers();

    setUsersTableLoading(true);
    renderUsersPagination(getUsersTablePageCount(rows));

    if (!isUsersTableHeaderVisible()) {
      scrollUsersTableHeaderIntoView();
    }

    globalScope.setTimeout(() => {
      if (token !== usersTableState.loadingToken) {
        return;
      }

      onComplete();
      usersTableState.isLoading = false;
      setUsersTableLoading(false);
      renderUsersPagination(getUsersTablePageCount(getFilteredUsers()));
    }, 350);
  }

  function requestUsersTablePage(targetPage) {
    if (!currentData || usersTableState.isLoading || targetPage === usersTableState.page) {
      return;
    }

    if (loadUsersTablePage(targetPage, { scrollToTable: true })) {
      return;
    }

    simulateUsersTableLoad(() => {
      usersTableState.page = targetPage;
      renderUsersTable();
    });
  }

  function renderUsersTable() {
    const tbody = document.getElementById("users-table-body");

    if (!tbody) {
      return;
    }

    const serverTable = hasServerUsersTable();
    const rows = serverTable ? (currentData?.users || []) : getFilteredUsers();
    const totalPages = getUsersTablePageCount(rows);

    const companyShareMetric = { key: "companySharePct", label: "Company share", valueType: "percent", barMode: "percent" };
    const splitMetrics = [
      { key: "engagedSeconds", label: "Engaged", valueType: "duration", deltaKey: "engagedDeltaPct", deltaUnit: "%", previousKey: "previousEngagedSeconds", deltaLabelKey: "engagedDeltaLabel" },
      { key: "visitsCount", label: "Visits", valueType: "number", deltaKey: "visitsDeltaPct", deltaUnit: "%", previousKey: "previousVisitsCount", deltaLabelKey: "visitsDeltaLabel" }
    ];
    const maxValues = tableMaxValues(rows, [companyShareMetric, ...splitMetrics]);
    const maxDeltaValues = tableDeltaMaxValues(rows, splitMetrics);
    const serverPage = Number(usersTablePagination()?.page);
    if (Number.isFinite(serverPage) && serverPage > 0) {
      usersTableState.page = Math.round(serverPage);
    }
    usersTableState.page = Math.min(totalPages, Math.max(1, usersTableState.page));
    updateUsersTableSortButtons();
    renderUsersPagination(totalPages);

    const pageStart = (usersTableState.page - 1) * usersTablePageSize;
    const pageRows = serverTable ? rows : rows.slice(pageStart, pageStart + usersTablePageSize);
    const areaAdoptionByUser = new Map(pageRows.map((user) => [user.id, buildUserAreaAdoption(user)]));
    const maxAreaEngaged = Math.max(
      ...Array.from(areaAdoptionByUser.values()).flatMap((cells) => cells.map((cell) => cell.engagedSeconds || 0)),
      1
    );

    if (!rows.length) {
      tbody.innerHTML = `
        <tr>
          <td colspan="8" class="px-6 py-12 text-center">
            <div class="mx-auto max-w-sm">
              <h3 class="text-base font-semibold text-slate-900">${escapeHtml(currentData.emptyState.title)}</h3>
              <p class="mt-1 text-sm text-slate-500">${escapeHtml(currentData.emptyState.text)}</p>
            </div>
          </td>
        </tr>
      `;
      renderUsersPagination(1);
      return;
    }

    adoptionCellTooltipId = 0;
    periodChangeTooltipId = 0;
    tbody.innerHTML = pageRows
      .map((user) => `
        <tr class="group hover:bg-slate-50">
          <td class="sticky left-0 z-[1] bg-white py-3.5 pl-0 pr-6 align-middle group-hover:bg-slate-50">${userCell(user)}</td>
          <td class="py-3.5 pr-6 align-middle">${companyCell(user)}</td>
          <td class="py-3.5 pr-6 align-middle">${statusBadge(user.status)}</td>
          ${renderBarMetricCell(user, companyShareMetric, maxValues)}
          ${renderSplitMetricCell(user, splitMetrics[0], maxValues, maxDeltaValues.engagedSeconds)}
          ${renderSplitMetricCell(user, splitMetrics[1], maxValues, maxDeltaValues.visitsCount)}
          <td class="py-3.5 pr-6 align-middle tabular-nums text-slate-700">${escapeHtml(formatDuration(user.avgVisitSeconds))}</td>
          <td class="py-3.5 pr-6 align-middle">${adoptionMatrixCellGroup(user, areaAdoptionByUser.get(user.id), maxAreaEngaged)}</td>
        </tr>
      `)
      .join("");
    syncSplitChangeValueWidths(tbody);
  }

  function periodDaysFromKey(periodKey) {
    if (periodKey && typeof periodKey === "object") {
      const explicitDays = Number(periodKey.days || periodKey.periodDays);

      if (Number.isFinite(explicitDays) && explicitDays > 0) {
        return explicitDays;
      }
    }

    const days = Number(String(periodKey || "").replace(/[^0-9.]/g, ""));

    return Number.isFinite(days) && days > 0 ? days : 30;
  }

  function firstPositiveNumber(...values) {
    const value = values.find((candidate) => Number(candidate) > 0);

    return Number(value) || 0;
  }

  function sessionIdFor(row, user, index) {
    return String(
      row?.session_id ||
      row?.sessionId ||
      row?.sessionID ||
      row?.id ||
      `${user.id || user.email || "user"}-session-${index + 1}`
    );
  }

  function sessionEngagedSeconds(row) {
    return firstPositiveNumber(
      row?.engaged_seconds,
      row?.engagedSeconds,
      row?.duration_seconds,
      row?.durationSeconds,
      row?.active_seconds,
      row?.activeSeconds
    );
  }

  function userSessionRows(user) {
    const pageVisits = Array.isArray(user.page_visits) ? user.page_visits : user.pageVisits;

    if (Array.isArray(pageVisits) && pageVisits.length) {
      return pageVisits;
    }

    const sessions = Array.isArray(user.sessions) ? user.sessions : user.sessionEvents;

    if (Array.isArray(sessions) && sessions.length) {
      return sessions;
    }

    if (Array.isArray(user.recentSessions) && user.recentSessions.length) {
      return user.recentSessions;
    }

    return [];
  }

  function fallbackSessionCount(user) {
    const visitsCount = Number(user.visitsCount) || 0;
    const estimatedCount = firstPositiveNumber(
      user.estimatedSessionsCount,
      user.estimatedSessionCount,
      user.estimated_sessions_count
    );
    const hasEstimatedFlag = [
      user.sessionsCountEstimated,
      user.sessionCountEstimated,
      user.sessions_count_estimated
    ].some((value) => typeof value === "boolean");
    const isEstimated = user.sessionsCountEstimated === true ||
      user.sessionCountEstimated === true ||
      user.sessions_count_estimated === true;

    if (isEstimated && visitsCount > 0) {
      return {
        count: Math.max(1, estimatedCount || visitsCount / 3),
        estimated: true
      };
    }

    const explicitCount = firstPositiveNumber(
      user.sessionsCount,
      user.sessionCount,
      user.distinctSessions,
      user.recentSessions?.length
    );

    if (explicitCount > 0) {
      const roundedLegacyEstimate = Math.max(1, Math.round(visitsCount / 3));

      if (!hasEstimatedFlag && visitsCount > 0 && Math.abs(explicitCount - roundedLegacyEstimate) < 0.001) {
        return {
          count: Math.max(1, visitsCount / 3),
          estimated: true
        };
      }

      return {
        count: Math.max(1, explicitCount),
        estimated: false
      };
    }

    if (visitsCount > 0) {
      return {
        count: Math.max(1, visitsCount / 3),
        estimated: true
      };
    }

    return {
      count: Number(user.engagedSeconds) > 0 ? 1 : 0,
      estimated: false
    };
  }

  function userConsistencyMetrics(user, periodDays) {
    const sessionsById = new Map();

    userSessionRows(user).forEach((row, index) => {
      const id = sessionIdFor(row, user, index);
      const engagedSeconds = sessionEngagedSeconds(row);

      sessionsById.set(id, (sessionsById.get(id) || 0) + engagedSeconds);
    });

    const fallbackSessions = fallbackSessionCount(user);
    const sessionCount = sessionsById.size || fallbackSessions.count;
    const sessionTotalEngaged = Array.from(sessionsById.values()).reduce((sum, value) => sum + value, 0);
    const totalEngagedSeconds = sessionTotalEngaged > 0
      ? sessionTotalEngaged
      : Number(user.engagedSeconds) || 0;

    return {
      sessionCount,
      sessionCountEstimated: !sessionsById.size && fallbackSessions.estimated,
      sessionsPerWeek: (sessionCount / Math.max(periodDays, 1)) * 7,
      totalEngagedSeconds,
      avgEngagedPerSession: sessionCount > 0 ? totalEngagedSeconds / sessionCount : 0
    };
  }

  function normalizeConsistencyStatus(status) {
    const value = String(status || "").trim();
    const mapped = getUserStatusMeta(value, "users")?.label || "";

    if (statusMeta[value]) {
      return value;
    }

    if (statusMeta[mapped]) {
      return mapped;
    }

    if (value === "At-risk" || value === "At risk" || value === "Risk") {
      return "Light";
    }

    return "";
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

  function consistencyStatus(user, metrics) {
    return normalizeConsistencyStatus(
      user.consistencyStatus ||
      user.consistency_status ||
      user.usageStatus ||
      user.usage_status ||
      user.status
    ) || deriveConsistencyStatus(metrics);
  }

  function getConsistencyFilteredUsers(data) {
    const company = readFilterValue("users-company-filter");
    const feature = readFilterValue("users-feature-filter");
    const sourceRows = Array.isArray(data.scatter) && data.scatter.length
      ? data.scatter
      : Array.isArray(data.users) ? data.users : [];

    return sourceRows
      .filter((user) => user.identified !== false)
      .filter((user) => !company || user.company === company)
      .filter((user) => userMatchesFeature(user, feature));
  }

  function areaUsageSegments(user) {
    const cells = buildUserAreaAdoption(user)
      .map((cell) => ({
        area: cell.productArea,
        value: Number(cell.engagedSeconds) || Number(cell.visits) || Number(cell.clicks) || 0,
        engagedSeconds: Number(cell.engagedSeconds) || 0
      }))
      .filter((cell) => cell.value > 0)
      .sort((a, b) => b.value - a.value);
    const topSegments = cells.slice(0, 5);
    const otherValue = cells.slice(5).reduce((sum, cell) => sum + cell.value, 0);

    if (otherValue > 0) {
      topSegments.push({
        area: "Other",
        value: otherValue,
        engagedSeconds: cells.slice(5).reduce((sum, cell) => sum + cell.engagedSeconds, 0)
      });
    }

    const total = topSegments.reduce((sum, cell) => sum + cell.value, 0) || 1;

    return topSegments.map((cell) => ({
      ...cell,
      pct: (cell.value / total) * 100,
      color: cell.area === "Other" ? visitsCircleColors[9] : productAreaColor(cell.area)
    }));
  }

  function compareScatterStable(a, b) {
    return (statusMeta[a.status]?.sort ?? 99) - (statusMeta[b.status]?.sort ?? 99) ||
      String(a.company || "").localeCompare(String(b.company || "")) ||
      String(a.userKey || a.userName || "").localeCompare(String(b.userKey || b.userName || ""));
  }

  function scatterSeededScore(row, salt) {
    return stableUnit(`${salt}|${row.userKey || row.userName || ""}|${row.status || ""}`);
  }

  function compareScatterSeeded(salt) {
    return (a, b) => scatterSeededScore(a, salt) - scatterSeededScore(b, salt) || compareScatterStable(a, b);
  }

  function scatterOrderedStatuses(rows) {
    const presentStatuses = new Set(rows.map((row) => row.status).filter(Boolean));

    return userScatterStatusOrder
      .concat(Array.from(presentStatuses).sort())
      .filter((status, index, statuses) => presentStatuses.has(status) && statuses.indexOf(status) === index);
  }

  function scatterRowsByStatus(rows) {
    return rows.reduce((groups, row) => {
      const status = row.status || "Unknown";

      if (!groups.has(status)) {
        groups.set(status, []);
      }

      groups.get(status).push(row);
      return groups;
    }, new Map());
  }

  function selectConsistencyScatterRows(rows) {
    const stableRows = rows.slice().sort(compareScatterStable);

    if (stableRows.length <= usersScatterLimit) {
      return stableRows;
    }

    const selected = [];
    const selectedKeys = new Set();
    const rowsByStatus = scatterRowsByStatus(stableRows);
    const statusReserve = Math.max(2, Math.floor(usersScatterLimit * 0.025));
    const stableRowKey = (row) => row.userKey || `${row.status}|${row.userName}|${row.company}`;
    const addRow = (row) => {
      const key = stableRowKey(row);

      if (selectedKeys.has(key) || selected.length >= usersScatterLimit) {
        return;
      }

      selectedKeys.add(key);
      selected.push(row);
    };

    scatterOrderedStatuses(stableRows).forEach((status) => {
      (rowsByStatus.get(status) || [])
        .slice()
        .sort(compareScatterSeeded(`consistency-status-${status}`))
        .slice(0, statusReserve)
        .forEach(addRow);
    });

    stableRows
      .filter((row) => !selectedKeys.has(stableRowKey(row)))
      .sort(compareScatterSeeded("consistency-random"))
      .forEach(addRow);

    return selected.sort(compareScatterStable);
  }

  function scatterLabelScore(row, xMedian, yMedian) {
    const statusScore = {
      Power: 520,
      Healthy: 460,
      Dropped: 280,
      Passive: 180,
      Light: 120
    }[row.status] || 0;
    const xDistance = Math.abs((Number(row.sessionsPerWeek) || 0) - xMedian) / Math.max(xMedian, 1);
    const yDistance = Math.abs((Number(row.avgEngagedPerSession) || 0) - yMedian) / Math.max(yMedian, 60);
    const volumeScore = Math.min(160, Math.log1p(Number(row.totalEngagedSeconds) || 0) * 18);
    const dropScore = Math.min(180, (Number(row.activityDropSeconds) || 0) / 120);

    return statusScore + xDistance * 150 + yDistance * 210 + volumeScore + dropScore;
  }

  function scatterLabelDistance(row, selectedRow, xDomainMax, yDomainMax) {
    const plotWidth = 1280;
    const plotHeight = 410;
    const x = ((Number(row.sessionsPerWeek) || 0) / Math.max(xDomainMax, 1)) * plotWidth;
    const y = ((Number(row.avgEngagedPerSession) || 0) / Math.max(yDomainMax, 1)) * plotHeight;
    const selectedX = ((Number(selectedRow.sessionsPerWeek) || 0) / Math.max(xDomainMax, 1)) * plotWidth;
    const selectedY = ((Number(selectedRow.avgEngagedPerSession) || 0) / Math.max(yDomainMax, 1)) * plotHeight;

    return Math.hypot(x - selectedX, y - selectedY);
  }

  function selectScatterLabelKeys(rows) {
    const baseLabelLimit = Math.max(usersScatterLabelLimit, 56);
    const labelLimit = Math.min(rows.length, rows.length > 220 ? 84 : rows.length > 120 ? 68 : baseLabelLimit);

    if (rows.length <= labelLimit) {
      return new Set(rows.map((row) => row.userKey));
    }

    const xMedian = median(rows.map((row) => row.sessionsPerWeek));
    const yMedian = median(rows.map((row) => row.avgEngagedPerSession));
    const xMax = Math.max(...rows.map((row) => row.sessionsPerWeek), 1);
    const yMax = Math.max(...rows.map((row) => row.avgEngagedPerSession), 60);
    const xDomainMax = compactAxisMax(xMax, { headroom: 0.1, minPadding: 0.15 });
    const yDomainMax = compactAxisMax(yMax, { headroom: 0.1, minPadding: 30 });
    const minDistance = rows.length > 220 ? 32 : rows.length > 120 ? 28 : 22;
    const candidates = rows
      .slice()
      .sort((a, b) => scatterLabelScore(b, xMedian, yMedian) - scatterLabelScore(a, xMedian, yMedian) || compareScatterStable(a, b));
    const selected = [];
    const selectedKeys = new Set();
    const selectedCountByStatus = new Map();
    const rowsByStatus = scatterRowsByStatus(candidates);
    const activeStatuses = scatterOrderedStatuses(candidates);
    const targetPerStatus = Math.max(2, Math.floor(labelLimit / Math.max(activeStatuses.length, 1)));
    const canSelect = (row, distance) => selected.every((selectedRow) => (
      scatterLabelDistance(row, selectedRow, xDomainMax, yDomainMax) >= distance
    ));
    const addSelected = (row) => {
      selected.push(row);
      selectedKeys.add(row.userKey);
      selectedCountByStatus.set(row.status, (selectedCountByStatus.get(row.status) || 0) + 1);
    };
    const selectFromRows = (candidateRows, distance) => {
      const row = candidateRows.find((candidate) => (
        selected.length < labelLimit &&
        !selectedKeys.has(candidate.userKey) &&
        canSelect(candidate, distance)
      ));

      if (!row) {
        return false;
      }

      addSelected(row);
      return true;
    };

    activeStatuses.forEach((status) => {
      const statusRows = rowsByStatus.get(status) || [];

      if (!selectFromRows(statusRows, minDistance * 0.72)) {
        selectFromRows(statusRows, minDistance * 0.5);
      }
    });

    activeStatuses.forEach((status) => {
      const statusRows = rowsByStatus.get(status) || [];

      while (
        selected.length < labelLimit &&
        (selectedCountByStatus.get(status) || 0) < targetPerStatus &&
        selectFromRows(statusRows, minDistance * 0.86)
      ) {
        // Keep the label set representative before the global outlier pass fills the rest.
      }
    });

    candidates.forEach((row) => {
      if (selected.length >= labelLimit || selectedKeys.has(row.userKey)) {
        return;
      }

      if (canSelect(row, minDistance)) {
        addSelected(row);
      }
    });

    if (selected.length < Math.min(10, labelLimit)) {
      candidates.forEach((row) => {
        if (selected.length >= labelLimit || selectedKeys.has(row.userKey)) {
          return;
        }

        if (canSelect(row, minDistance * 0.62)) {
          addSelected(row);
        }
      });
    }

    if (selected.length < labelLimit) {
      candidates.forEach((row) => {
        if (selected.length >= labelLimit || selectedKeys.has(row.userKey)) {
          return;
        }

        addSelected(row);
      });
    }

    return new Set(selected.map((row) => row.userKey));
  }

  function scatterVisualJitter(row, axis, crowding = 1) {
    const centered = (stableUnit(`${row.userKey}|${row.status}|${axis}`) - 0.5) * 2;
    const statusJitterScale = row.status === "Passive" ? 1.35 : row.status === "Light" ? 1.2 : 1;
    const magnitude = axis === "x"
      ? usersScatterJitterX * Math.min(1.35, crowding)
      : usersScatterJitterY * crowding * statusJitterScale;
    const rawValue = axis === "x" ? Number(row.sessionsPerWeek) || 0 : Number(row.avgEngagedPerSession) || 0;

    if (rawValue <= 0) {
      return axis === "x" ? Math.abs(centered) * magnitude : -Math.abs(centered) * magnitude;
    }

    if (axis === "x" && rawValue < 1) {
      return Math.abs(centered) * magnitude * 1.25;
    }

    return centered * magnitude;
  }

  function formatDecimal(value, maxFractionDigits = 1) {
    return new Intl.NumberFormat("en-US", {
      minimumFractionDigits: 0,
      maximumFractionDigits: maxFractionDigits
    }).format(Number(value) || 0);
  }

  function formatSessionCount(value, estimated = false) {
    const numericValue = Number(value) || 0;
    const hasFraction = Math.abs(numericValue - Math.round(numericValue)) > 0.01;
    const formattedValue = formatDecimal(numericValue, estimated || hasFraction ? 1 : 0);

    return estimated && numericValue > 0 ? `~${formattedValue}` : formattedValue;
  }

  function buildConsistencyIntensityRows(data) {
    const periodDays = periodDaysFromKey(data.period);
    const rows = getConsistencyFilteredUsers(data)
      .map((user) => {
        const metrics = userConsistencyMetrics(user, periodDays);
        const status = consistencyStatus(user, metrics);
        const segments = areaUsageSegments(user);
        const previousEngagedSeconds = Number(
          user.previousEngagedSeconds ??
          user.previous_period_engaged_seconds ??
          user.previousEngaged ??
          user.previous_engaged_seconds
        ) || 0;
        const activityDropSeconds = Math.max(
          0,
          Number(user.activityDropSeconds ?? user.activity_drop_seconds) || previousEngagedSeconds - metrics.totalEngagedSeconds
        );
        const areaUsageRows = segments.map((segment) => ({
          label: segment.area,
          value: formatDuration(segment.engagedSeconds || segment.value)
        }));

        return {
          userKey: userStableKey(user),
          userId: user.id,
          userName: user.name || "User",
          company: user.company || "Unknown company",
          status,
          sessions: metrics.sessionCount,
          sessionsEstimated: metrics.sessionCountEstimated,
          sessionsLabel: formatSessionCount(metrics.sessionCount, metrics.sessionCountEstimated),
          sessionsPerWeek: metrics.sessionsPerWeek,
          avgEngagedPerSession: metrics.avgEngagedPerSession,
          totalEngagedSeconds: metrics.totalEngagedSeconds,
          previousEngagedSeconds,
          activityDropSeconds,
          sessionsPerWeekLabel: formatDecimal(metrics.sessionsPerWeek),
          totalEngagedLabel: formatDuration(metrics.totalEngagedSeconds),
          avgEngagedLabel: formatDuration(metrics.avgEngagedPerSession),
          companyShareLabel: formatPercent(user.companySharePct),
          areaUsageRows
        };
      });
    const selectedRows = selectConsistencyScatterRows(rows);
    const visualCrowding = Math.min(1.8, Math.max(1, selectedRows.length / 180));
    const labelKeys = selectScatterLabelKeys(selectedRows);
    const xMedian = median(selectedRows.map((row) => row.sessionsPerWeek));
    const yMedian = median(selectedRows.map((row) => row.avgEngagedPerSession));

    return selectedRows.map((row) => ({
      ...row,
      jitterX: scatterVisualJitter(row, "x", visualCrowding),
      jitterY: scatterVisualJitter(row, "y", visualCrowding),
      pointSize: usersScatterPointSize,
      labelPriority: scatterLabelScore(row, xMedian, yMedian),
      showLabel: labelKeys.has(row.userKey)
    }));
  }

  function createUserConsistencyScatterSpec(rows, config) {
    const xMedian = median(rows.map((row) => row.sessionsPerWeek));
    const yMedian = median(rows.map((row) => row.avgEngagedPerSession));
    const xMax = Math.max(...rows.map((row) => row.sessionsPerWeek), 1);
    const yMax = Math.max(...rows.map((row) => row.avgEngagedPerSession), 60);
    const xDomainMax = compactAxisMax(xMax, { headroom: 0.1, minPadding: 0.15 });
    const yDomainMax = compactAxisMax(yMax, { headroom: 0.1, minPadding: 30 });
    const statuses = Object.keys(statusMeta);
    const statusColors = statuses.map((status) => statusColor(status));

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
              x: { signal: "max(0, min(width, scale('xScale', datum.sessionsPerWeek) + (datum.jitterX || 0)))" },
              y: { signal: "max(0, min(height, scale('yScale', datum.avgEngagedPerSession) + (datum.jitterY || 0)))" },
              shape: { value: "circle" },
              tooltip: {
                signal: "datum"
              }
            },
            update: {
              cursor: { value: "default" },
              fill: { scale: "colorScale", field: "status" },
              opacity: { value: 0.68 },
              size: { field: "pointSize" },
              stroke: { value: chartTheme.colors.white },
              strokeWidth: { value: 0.9 },
              zindex: { value: 0 }
            },
            hover: {
              opacity: { value: 1 },
              size: { signal: "datum.pointSize * 1.18" },
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
              text: { signal: "datum.datum.showLabel ? datum.datum.userName : ''" },
              fill: { value: chartTheme.colors.labelText },
              font: { value: "Inter, ui-sans-serif, system-ui, sans-serif" },
              fontSize: { value: 12 },
              fontWeight: { value: 400 },
              opacity: { signal: "datum.datum.showLabel ? 1 : 0" },
              limit: { value: 118 },
              zindex: { value: 2 }
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

  function median(values) {
    const sorted = values.map((value) => Number(value) || 0).sort((a, b) => a - b);
    const middle = Math.floor(sorted.length / 2);

    if (!sorted.length) {
      return 0;
    }

    return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
  }

  function formatUserConsistencyTooltip(point) {
    const value = point && typeof point === "object" ? point : {};
    const areaRows = Array.isArray(value.areaUsageRows) && value.areaUsageRows.length
      ? value.areaUsageRows
      : [{ label: "Usage", value: "No usage detected" }];

    return analyticsTooltips.render({
      title: value.userName || "User",
      sections: [
        {
          rows: [
            { label: "Company", value: value.company || "Unknown company" },
            { label: "Status", value: value.status || "Unknown" },
            { label: "Sessions", value: value.sessionsLabel || "0" },
            { label: "Sessions/week", value: value.sessionsPerWeekLabel || "0" },
            { label: "Total engaged time", value: value.totalEngagedLabel || "0m" },
            { label: "Avg engaged/session", value: value.avgEngagedLabel || "0m" },
            { label: "Company share", value: value.companyShareLabel || "0%" }
          ]
        },
        {
          title: "Area usage",
          rows: areaRows
        }
      ]
    });
  }

  function mountConsistencyIntensityScatter(data) {
    const element = document.getElementById("users-breadth-depth-scatter");

    if (!element) {
      return;
    }

    if (element.__hymetryChart) {
      element.__hymetryChart.dispose();
      element.__hymetryChart = null;
    }

    const rows = buildConsistencyIntensityRows(data);

    if (!rows.length) {
      chartUnavailable(element, "No identified user activity detected for this period.");
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

      globalScope.vegaEmbed(element, createUserConsistencyScatterSpec(rows, { width }), {
        actions: false,
        renderer: "canvas",
        tooltip: {
          formatTooltip: formatUserConsistencyTooltip
        }
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

  function renderHeatmap(data) {
    const container = document.getElementById("users-feature-heatmap");

    if (!container) {
      return;
    }

    const rows = data.featureHeatmap || [];
    const columns = data.featureColumns || [];
    const values = rows.flatMap((row) => columns.map((column) => row.values[column]?.[activeHeatmapMetric] || 0));
    const maxValue = Math.max(...values, 1);
    const heatmapMetricColors = {
      engagedSeconds: chartTheme.series[0],
      visits: chartTheme.series[1],
      clicks: chartTheme.series[2]
    };
    const color = heatmapMetricColors[activeHeatmapMetric] || chartTheme.series[0];
    const metricFormatter = activeHeatmapMetric === "engagedSeconds" ? formatDuration : formatNumber;
    const metricLabel = {
      engagedSeconds: "engaged time",
      visits: "visits",
      clicks: "clicks"
    }[activeHeatmapMetric] || "activity";

    container.innerHTML = [
      `<div class="users-heatmap__heading" role="columnheader">${tableHeaderTooltip("User", "User included in this feature activity comparison", "users-heatmap-tooltip-user")}</div>`,
      ...columns.map((column, columnIndex) => `<div class="users-heatmap__heading" role="columnheader">${tableHeaderTooltip(column, `Daily ${metricLabel} in ${column} for each user during the selected period`, `users-heatmap-tooltip-column-${columnIndex}`, columnIndex === columns.length - 1 ? { align: "end" } : {})}</div>`),
      ...rows.flatMap((row) => [
        `
          <div class="users-heatmap__user" role="rowheader">
            <span class="truncate font-medium text-slate-900">${escapeHtml(row.userName)}</span>
            <span class="truncate text-xs text-slate-500">${escapeHtml(row.company)}</span>
          </div>
        `,
        ...columns.map((column) => {
          const value = row.values[column]?.[activeHeatmapMetric] || 0;
          const intensity = value ? 0.1 + (value / maxValue) * 0.68 : 0;
          const background = value ? rgbaFromHex(color, intensity) : tailwindColor("slate-50");
          const label = value ? metricFormatter(value) : "";

          return `
            <div
              class="users-heatmap__cell"
              role="cell"
              style="background:${background};"
              aria-label="${escapeHtml(`${row.userName}, ${column}, ${metricFormatter(value)}`)}">
              ${escapeHtml(label)}
            </div>
          `;
        })
      ])
    ].join("");
  }

  function mountHeatmapControls() {
    document.querySelectorAll("[data-users-heatmap-metric]").forEach((button) => {
      if (button.__usersHeatmapMounted) {
        return;
      }

      button.__usersHeatmapMounted = true;
      button.addEventListener("click", () => {
        activeHeatmapMetric = button.getAttribute("data-users-heatmap-metric") || "engagedSeconds";
        setSegmentedButtonsActive("[data-users-heatmap-metric]", activeHeatmapMetric, "data-users-heatmap-metric");
        renderHeatmap(currentData);
      });
    });
  }

  function attentionReasonBadgeClass(severity) {
    if (severity === "negative") {
      return "users-badge--red";
    }

    if (severity === "low") {
      return "users-badge--amber";
    }

    return "users-badge--slate";
  }

  /**
   * Page one of the callout lists in the browser.
   *
   * These rows are bounded server-side and ride along in the payload, so there
   * is nothing to fetch: paging is a slice. The markup matches the Users table's
   * pagination so the page reads as one thing.
   */
  function renderCalloutPagination(selector, state, totalPages, actionAttribute, onNavigate) {
    const container = document.querySelector(selector);

    if (!container) {
      return;
    }

    if (totalPages <= 1) {
      container.hidden = true;
      container.innerHTML = "";
      return;
    }

    const currentPage = Math.min(totalPages, Math.max(1, state.page));

    container.hidden = false;
    container.innerHTML = `
      ${
        currentPage > 2
          ? `<button type="button" class="font-medium text-sky-700 hover:text-sky-800" ${actionAttribute}="first">Go to first page</button>`
          : `<span aria-hidden="true"></span>`
      }
      <div class="flex items-center justify-between gap-6 sm:justify-end">
        ${
          currentPage > 1
            ? `<button type="button" class="inline-flex h-8 w-8 items-center justify-center text-sky-700 hover:text-sky-800" ${actionAttribute}="previous" aria-label="Back to previous page">${usersPaginationIcon("previous")}</button>`
            : `<span class="invisible h-8 w-8" aria-hidden="true"></span>`
        }
        <span class="text-slate-700">Page ${currentPage}/${totalPages}</span>
        ${
          currentPage < totalPages
            ? `<button type="button" class="inline-flex items-center gap-2 rounded-md border border-slate-200 bg-transparent px-4 py-3 font-medium text-sky-700 duration-150 hover:bg-slate-100" ${actionAttribute}="next">Continue to next page ${usersPaginationIcon("next")}</button>`
            : ""
        }
      </div>
    `;

    container.querySelectorAll(`[${actionAttribute}]`).forEach((button) => {
      button.addEventListener("click", () => {
        const action = button.getAttribute(actionAttribute);

        state.page =
          action === "first"
            ? 1
            : action === "previous"
              ? Math.max(1, state.page - 1)
              : Math.min(totalPages, state.page + 1);

        onNavigate();
      });
    });
  }

  function calloutPageRows(rows, state) {
    const totalPages = Math.max(1, Math.ceil(rows.length / calloutPageSize));

    state.page = Math.min(totalPages, Math.max(1, state.page));

    const start = (state.page - 1) * calloutPageSize;

    return { totalPages, pageRows: rows.slice(start, start + calloutPageSize) };
  }

  function renderUsersNeedingAttention(data) {
    const container = document.getElementById("users-attention-list");

    if (!container) {
      return;
    }

    const allRows = data.usersNeedingAttention || [];

    if (!allRows.length) {
      container.innerHTML = `<div class="rounded-lg bg-slate-50 px-4 py-8 text-center text-sm text-slate-500">No users need attention right now.</div>`;
      renderCalloutPagination("[data-users-attention-pagination]", attentionListState, 1, "data-users-attention-page-action", () => {});
      return;
    }

    const { totalPages, pageRows: rows } = calloutPageRows(allRows, attentionListState);

    renderCalloutPagination(
      "[data-users-attention-pagination]",
      attentionListState,
      totalPages,
      "data-users-attention-page-action",
      () => renderUsersNeedingAttention(data)
    );

    container.innerHTML = `
      <div class="overflow-x-auto">
        <table class="w-full min-w-[720px] table-auto text-left">
          <thead class="border-b border-gray-300 bg-white text-slate-600">
            <tr>
              <th scope="col" class="py-3 pl-0 pr-4 font-normal">${tableHeaderTooltip("User", "User who needs attention based on recent activity", "users-attention-tooltip-user")}</th>
              <th scope="col" class="py-3 pr-4 font-normal">${tableHeaderTooltip("Company", "Company account associated with this user", "users-attention-tooltip-company")}</th>
              <th scope="col" class="py-3 pr-4 font-normal">${tableHeaderTooltip("Status", "User health state based on engagement, breadth, and recency", "users-attention-tooltip-status")}</th>
              <th scope="col" class="py-3 pr-4 font-normal">${tableHeaderTooltip("Signal", "Recent usage change that caused this user to need attention", "users-attention-tooltip-signal")}</th>
              <th scope="col" class="py-3 pr-0 font-normal">${tableHeaderTooltip("Reason", "Explanation of why this user was included", "users-attention-tooltip-reason", { align: "end" })}</th>
            </tr>
          </thead>
          <tbody class="text-slate-700">
            ${rows
              .map((row) => `
                <tr class="group hover:bg-slate-50">
                  <td class="py-3 pr-4 align-middle">
                    ${userCell(row)}
                  </td>
                  <td class="py-3 pr-4 align-middle text-slate-700">${companyCell(row)}</td>
                  <td class="py-3 pr-4 align-middle">${statusBadge(row.status)}</td>
                  <td class="py-3 pr-4 align-middle">
                    <span class="font-semibold text-slate-900">${escapeHtml(row.signal)}</span>
                  </td>
                  <td class="py-3 pr-0 align-middle">
                    <span class="users-badge ${attentionReasonBadgeClass(row.severity)}">${escapeHtml(row.reason)}</span>
                  </td>
                </tr>
              `)
              .join("")}
          </tbody>
        </table>
      </div>
    `;
  }

  function renderUsersGainingMomentum(data) {
    const container = document.getElementById("users-momentum-list");

    if (!container) {
      return;
    }

    const allRows = data.usersGainingMomentum || [];

    if (!allRows.length) {
      container.innerHTML = `<div class="rounded-lg bg-slate-50 px-4 py-8 text-center text-sm text-slate-500">No momentum signals found for this period.</div>`;
      renderCalloutPagination("[data-users-momentum-pagination]", momentumListState, 1, "data-users-momentum-page-action", () => {});
      return;
    }

    const { totalPages, pageRows: rows } = calloutPageRows(allRows, momentumListState);

    renderCalloutPagination(
      "[data-users-momentum-pagination]",
      momentumListState,
      totalPages,
      "data-users-momentum-page-action",
      () => renderUsersGainingMomentum(data)
    );

    container.innerHTML = `
      <div class="overflow-x-auto">
        <table class="w-full min-w-[720px] table-auto text-left">
          <thead class="border-b border-gray-300 bg-white text-slate-600">
            <tr>
              <th scope="col" class="py-3 pl-0 pr-4 font-normal">${tableHeaderTooltip("User", "User whose recent activity is gaining momentum", "users-momentum-tooltip-user")}</th>
              <th scope="col" class="py-3 pr-4 font-normal">${tableHeaderTooltip("Company", "Company account associated with this user", "users-momentum-tooltip-company")}</th>
              <th scope="col" class="py-3 pr-4 font-normal">${tableHeaderTooltip("Status", "User health state based on engagement, breadth, and recency", "users-momentum-tooltip-status")}</th>
              <th scope="col" class="py-3 pr-4 font-normal">${tableHeaderTooltip("Signal", "Recent positive usage change detected for this user", "users-momentum-tooltip-signal")}</th>
              <th scope="col" class="py-3 pr-0 font-normal">${tableHeaderTooltip("Reason", "Explanation of why this user was included", "users-momentum-tooltip-reason", { align: "end" })}</th>
            </tr>
          </thead>
          <tbody class="text-slate-700">
            ${rows
              .map((row) => `
                <tr class="group hover:bg-slate-50">
                  <td class="py-3 pr-4 align-middle">
                    ${userCell(row)}
                  </td>
                  <td class="py-3 pr-4 align-middle text-slate-700">${companyCell(row)}</td>
                  <td class="py-3 pr-4 align-middle">${statusBadge(row.status)}</td>
                  <td class="py-3 pr-4 align-middle">
                    <span class="font-semibold text-green-700">${escapeHtml(row.signal)}</span>
                  </td>
                  <td class="py-3 pr-0 align-middle">
                    <span class="users-badge users-badge--slate">${escapeHtml(row.reason)}</span>
                  </td>
                </tr>
              `)
              .join("")}
          </tbody>
        </table>
      </div>
    `;
  }

  function mountFilterEvents() {
    document.querySelectorAll("[data-users-filter], [data-users-table-filter], [data-users-sort]").forEach((control) => {
      if (control.__usersFilterMounted) {
        return;
      }

      control.__usersFilterMounted = true;
      const affectsScatter = control.matches("[data-users-filter]");
      const applyFilter = () => {
        usersTableState.page = 1;
        if (!loadUsersTablePage(1)) {
          renderUsersTable();
        }
        if (affectsScatter) {
          mountConsistencyIntensityScatter(currentData);
        }
        refreshUserSearchResults();
      };
      const isTextInput = control.matches('input[type="search"], input[type="text"]');

      if (isTextInput) {
        control.addEventListener("input", () => {
          globalScope.clearTimeout(usersTableFilterDebounceId);
          usersTableFilterDebounceId = globalScope.setTimeout(applyFilter, 180);
        });
      } else {
        control.addEventListener("change", applyFilter);
      }
    });

  }

  function mountUsersTableSort() {
    if (usersTableSortMounted) {
      return;
    }

    usersTableSortMounted = true;

    document.querySelectorAll("[data-users-table-sort]").forEach((button) => {
      button.addEventListener("click", () => {
        const sortKey = button.getAttribute("data-users-table-sort") || "visitsCount";

        if (!currentData) {
          return;
        }

        if (usersTableState.sortKey === sortKey) {
          usersTableState.sortDirection = usersTableState.sortDirection === "asc" ? "desc" : "asc";
        } else {
          usersTableState.sortKey = sortKey;
          usersTableState.sortDirection = usersTableDefaultSortDirections[sortKey] || "desc";
        }

        usersTableState.page = 1;
        updateUsersTableSortButtons();
        if (loadUsersTablePage(1)) {
          return;
        }

        simulateUsersTableLoad(() => {
          renderUsersTable();
        });
      });
    });
  }

  function renderAll(data) {
    currentData = data;

    const initialTablePage = Number(usersTablePagination(data)?.page);
    usersTableState.page = Number.isFinite(initialTablePage) && initialTablePage > 0
      ? Math.round(initialTablePage)
      : 1;

    syncProductAreaPalette(data);
    syncProductAreaHeadings();
    populateFilters(data);
    mountCustomSelectDropdowns();
    mountUserSearch();
    refreshUserSearchResults();
    mountFilterEvents();
    mountUsersTableSort();
    renderKpiCards(data);
    renderInsights(data);
    mountEngagementDistribution(data);
    renderUsersTable();
    mountConsistencyIntensityScatter(data);
    renderUsersNeedingAttention(data);
    renderUsersGainingMomentum(data);
  }

  function loadPeriod(period) {
    usersTableState.page = 1;
    renderAll(provider.getUsersAnalyticsData(period));
  }

  function getRequestedPeriod() {
    const params = new URLSearchParams(globalScope.location.search);
    return provider.coercePeriodKey(params.get("period") || params.get("days") || provider.DEFAULT_PERIOD);
  }

  function initUsersPage() {
    if (document.body.dataset.usersView !== "overview") {
      return;
    }

    globalScope.addEventListener("resize", scheduleSplitChangeValueWidthSync);
    document.fonts?.ready?.then(scheduleSplitChangeValueWidthSync);
    loadPeriod(getRequestedPeriod());
  }

  if (globalScope.__HymetryExposeTestHooks) {
    globalScope.HymetryUsersAnalyticsTesting = {
      createKpiTrendOption,
      createStatusMixComparisonOption,
      createUserConsistencyScatterSpec,
      formatKpiHeadlineValue,
      kpiTrendValueFormat,
      statusMixDistributionRow
    };
  }

  document.addEventListener("DOMContentLoaded", initUsersPage);
})(window);
