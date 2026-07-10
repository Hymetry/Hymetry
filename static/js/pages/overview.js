(function mountPagesOverview() {
  const script = document.getElementById("pages-overview-data");
  const root = document.querySelector("[data-pages-overview]");

  if (!script || !root) {
    return;
  }

  const payload = JSON.parse(script.textContent || "{}");
  const numberFormatter = new Intl.NumberFormat("en-US");
  const averageUsersFormatter = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 });
  const palette = [
    "#4269d0",
    "#efb118",
    "#ff725c",
    "#6cc5b0",
    "#3ca951",
    "#ff8ab7",
    "#a463f2",
    "#97bbf5",
    "#9c6b4e",
    "#0891b2",
    "#be123c",
    "#ca8a04"
  ];

  const metrics = [
    { key: "companies", label: "Companies", color: "#4269d0", barClass: "bg-c-blue", width: 104, value: (row) => number(row.companies_count), formatPoint: number },
    { key: "adoption", label: "Adoption", color: "#6cc5b0", barClass: "bg-c-teal", width: 100, value: (row) => percent(row.adoption_pct), formatPoint: percent },
    { key: "users", label: "Users", color: "#3ca951", barClass: "bg-c-green", width: 96, value: (row) => number(row.users_count), formatPoint: number },
    { key: "penetration", label: "Penetration", color: "#97bbf5", barClass: "bg-c-light-blue", width: 96, value: (row) => percent(row.penetration_pct), formatPoint: percent, valueOnly: true },
    { key: "visits", label: "Visits", color: "#a463f2", barClass: "bg-c-purple", width: 104, value: (row) => number(row.visits_count), formatPoint: number },
    { key: "engaged", label: "Engaged", color: "#efb118", barClass: "bg-c-orange", width: 100, value: (row) => row.engaged_label || duration(row.engaged_seconds), formatPoint: duration },
    { key: "avg_visit", label: "Avg / visit", color: "#ff8ab7", barClass: "bg-c-rose", width: 112, value: (row) => row.avg_visit_label || duration(row.avg_visit_seconds), formatPoint: duration, valueOnly: true },
    { key: "interaction", label: "Interaction", color: "#ff725c", barClass: "bg-c-red", width: 100, value: (row) => percent(row.interaction_pct), formatPoint: percent },
    { key: "clicks_per_visit", label: "Clicks / visit", color: "#9c6b4e", barClass: "bg-c-brown", width: 88, value: (row) => decimal(row.clicks_per_visit), formatPoint: decimal, valueOnly: true }
  ];

  const productAreaSummaryMetrics = [
    { key: "companies", label: "Companies" },
    { key: "adoption", label: "Adoption" },
    { key: "users", label: "Users" },
    { key: "engaged", label: "Engaged" }
  ];

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function number(value) {
    const numericValue = Number(value) || 0;
    const formattedValue = numberFormatter.format(Object.is(numericValue, -0) ? 0 : numericValue);

    return formattedValue === "-0" ? "0" : formattedValue;
  }

  function averageUsers(value) {
    const numericValue = Number(value) || 0;
    return averageUsersFormatter.format(Math.round(numericValue * 100) / 100);
  }

  function decimal(value) {
    const rounded = Math.round((Number(value) || 0) * 100) / 100;
    return Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(2).replace(/0$/, "");
  }

  function percent(value) {
    return `${number(Math.round(Number(value) || 0))}%`;
  }

  function duration(seconds) {
    const value = Math.max(0, Math.round(Number(seconds) || 0));
    if (value < 60) {
      return `${value}s`;
    }

    const hours = Math.floor(value / 3600);
    const minutes = Math.round((value % 3600) / 60);

    if (hours > 0) {
      return minutes > 0 ? `${hours}h ${minutes}m` : `${hours}h`;
    }

    return `${minutes}m`;
  }

  function directionClass(direction) {
    if (direction === "positive") {
      return "text-green-700";
    }
    if (direction === "negative") {
      return "text-red-600";
    }
    return "text-slate-900";
  }

  function directionColor(direction) {
    if (direction === "positive") {
      return "#22c55e";
    }
    if (direction === "negative") {
      return "#ef4444";
    }
    return "#0f172a";
  }

  function emptyState(label) {
    return `<div class="pages-empty-state">${escapeHtml(label)}</div>`;
  }

  function clamp(value, min, max) {
    return Math.max(min, Math.min(max, value));
  }

  function hashKey(value) {
    const text = String(value || "");
    let hash = 0;
    for (let index = 0; index < text.length; index += 1) {
      hash = ((hash << 5) - hash) + text.charCodeAt(index);
      hash |= 0;
    }
    return Math.abs(hash);
  }

  function colorForKey(key, index) {
    if (index !== undefined) {
      return palette[index % palette.length];
    }
    return palette[hashKey(key) % palette.length];
  }

  function formatDateLabel(dateValue) {
    const rawValue = String(dateValue || "").trim();
    const monthNames = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    const isoDateMatch = rawValue.match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (isoDateMatch) {
      const monthIndex = Number(isoDateMatch[2]) - 1;
      return `${monthNames[monthIndex] || isoDateMatch[2]} ${Number(isoDateMatch[3])}`;
    }
    const monthDayMatch = rawValue.match(/^([A-Za-z]{3,})\s+0?(\d{1,2})/);
    if (monthDayMatch) {
      return `${monthDayMatch[1].slice(0, 3)} ${Number(monthDayMatch[2])}`;
    }
    return rawValue;
  }

  function truncate(value, length) {
    const text = String(value || "");
    if (text.length <= length) {
      return text;
    }
    return `${text.slice(0, Math.max(0, length - 1))}...`;
  }

  function alignTrendLabels(labels, length) {
    const count = Math.max(0, Number(length) || 0);
    const source = Array.isArray(labels) ? labels.map(formatDateLabel).filter(Boolean) : [];

    if (!count) {
      return [];
    }

    if (source.length >= count) {
      return source.slice(source.length - count);
    }

    return Array.from({ length: count }, (_, index) => source[index] || String(index + 1));
  }

  function formatKpiTrendValue(kpi, value) {
    if (kpi?.trend_format === "duration") {
      return duration(value);
    }
    if (kpi?.trend_format === "percent") {
      return percent(value);
    }
    return number(value);
  }

  function mountSparklineTooltip(target, coordinates, values, labels, kpi) {
    const svg = target.querySelector("svg");
    const tooltip = target.querySelector("[data-pages-kpi-tooltip]");
    const hoverLine = target.querySelector("[data-pages-kpi-hover-line]");

    if (!svg || !tooltip || !hoverLine) {
      return;
    }

    const setActivePoint = (index, clientX) => {
      const point = coordinates[index];
      if (!point) {
        return;
      }

      const tooltipWidth = tooltip.offsetWidth || 84;
      const containerRect = target.getBoundingClientRect();
      const left = clamp(clientX - containerRect.left + 12, 0, Math.max(0, containerRect.width - tooltipWidth));

      hoverLine.setAttribute("x1", point[0].toFixed(1));
      hoverLine.setAttribute("x2", point[0].toFixed(1));
      hoverLine.removeAttribute("hidden");
      tooltip.innerHTML = `
        <div class="pages-kpi-tooltip-date">${escapeHtml(labels[index] || String(index + 1))}</div>
        <div class="pages-kpi-tooltip-row">
          <span class="pages-kpi-tooltip-dot" aria-hidden="true"></span>
          <span class="pages-kpi-tooltip-value">${escapeHtml(formatKpiTrendValue(kpi, values[index]))}</span>
        </div>
      `;
      tooltip.style.left = `${left}px`;
      tooltip.dataset.visible = "true";
    };

    const clearActivePoint = () => {
      hoverLine.setAttribute("hidden", "");
      tooltip.dataset.visible = "false";
    };

    svg.addEventListener("mousemove", (event) => {
      const rect = svg.getBoundingClientRect();
      const svgX = ((event.clientX - rect.left) / Math.max(rect.width, 1)) * 220;
      let closestIndex = 0;
      let closestDistance = Infinity;

      coordinates.forEach(([x], index) => {
        const distance = Math.abs(x - svgX);
        if (distance < closestDistance) {
          closestDistance = distance;
          closestIndex = index;
        }
      });

      setActivePoint(closestIndex, event.clientX);
    });
    svg.addEventListener("mouseleave", clearActivePoint);
    svg.addEventListener("focusout", clearActivePoint);
  }

  function renderSparkline(target, values, labels, kpi) {
    const points = (Array.isArray(values) ? values : []).map((value) => Number(value) || 0);
    if (!target || points.length < 2) {
      if (target) {
        target.innerHTML = "";
      }
      return;
    }

    const width = 220;
    const height = 48;
    const padding = 4;
    const max = Math.max(...points, 1);
    const min = Math.min(...points);
    const range = Math.max(max - min, 1);
    const xStep = (width - padding * 2) / (points.length - 1);
    const coordinates = points.map((value, index) => {
      const x = padding + index * xStep;
      const y = padding + (1 - ((value - min) / range)) * (height - padding * 2);
      return [x, y];
    });
    const path = coordinates.map(([x, y], index) => `${index === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`).join(" ");
    const area = `${path} L${width - padding} ${height - padding} L${padding} ${height - padding} Z`;
    const trendLabels = alignTrendLabels(labels, points.length);

    target.innerHTML = `
      <svg viewBox="0 0 ${width} ${height}" width="100%" height="${height}" preserveAspectRatio="none" role="img" aria-label="KPI trend">
        <path d="${area}" fill="var(--pages-kpi-trend-fill-color, #eff6ff)"></path>
        <path d="${path}" fill="none" stroke="var(--pages-kpi-trend-color, #60a5fa)" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"></path>
        <line data-pages-kpi-hover-line hidden x1="0" y1="${padding}" x2="0" y2="${height - padding}" stroke="var(--pages-kpi-trend-axis-color, #cbd5e1)" stroke-width="1" stroke-dasharray="4 3"></line>
      </svg>
      <div data-pages-kpi-tooltip class="pages-kpi-tooltip" data-visible="false"></div>
    `;
    mountSparklineTooltip(target, coordinates, points, trendLabels, kpi);
  }

  function kpiDeltaDirection(kpi) {
    if (kpi.delta_value !== null && kpi.delta_value !== undefined && Number.isFinite(Number(kpi.delta_value))) {
      return Number(kpi.delta_value) > 0 ? "positive" : Number(kpi.delta_value) < 0 ? "negative" : "neutral";
    }
    const label = String(kpi.delta || "");
    if (label.trim().startsWith("-")) {
      return "negative";
    }
    if (label.trim().startsWith("+")) {
      return "positive";
    }
    if (label.trim().toLowerCase().startsWith("new")) {
      return "positive";
    }
    return "neutral";
  }

  function renderKpis() {
    const grid = root.querySelector("[data-pages-kpis-grid]");
    const shell = root.querySelector("[data-pages-kpis-shell]");
    const template = document.getElementById("pages-kpi-card-template");
    const kpis = payload.kpis || [];

    if (!grid || !shell) {
      return;
    }

    if (!kpis.length) {
      shell.innerHTML = emptyState("No page metrics found for this period yet.");
      return;
    }

    grid.replaceChildren();
    kpis.forEach((kpi, index) => {
      const node = template.content.firstElementChild.cloneNode(true);
      const direction = kpiDeltaDirection(kpi);
      node.querySelector("[data-pages-kpi-label]").textContent = kpi.label || "";
      node.querySelector("[data-pages-kpi-value]").textContent = kpi.value || "";
      const delta = node.querySelector("[data-pages-kpi-delta]");
      delta.textContent = kpi.delta || "";
      delta.dataset.deltaDirection = direction;
      renderSparkline(node.querySelector("[data-pages-kpi-trend]"), kpi.trend_values, kpi.trend_labels, kpi);
      grid.appendChild(node);
    });
  }

  function rowDelta(row, metric) {
    return (row.deltas || {})[metric.key] || { value: 0, label: "0", direction: "neutral" };
  }

  function rowBar(row, metric) {
    return clamp(Number((row.bars || {})[metric.key]) || 0, 0, 100);
  }

  function deltaMagnitude(delta) {
    if (delta.value === null && delta.direction === "positive") {
      return 100;
    }
    return Math.abs(Number(delta.value) || 0);
  }

  function deltaLabel(delta, metric) {
    if (delta.label && delta.label === "New") {
      return delta.label;
    }
    const value = Math.round(Number(delta.value) || 0);
    const prefix = value > 0 ? "+" : "";
    return metric.key === "adoption" || metric.key === "penetration" || metric.key === "interaction"
      ? `${prefix}${number(value)} pp`
      : `${prefix}${number(value)}%`;
  }

  function deltaDirectionFromValue(value, unit) {
    const numeric = Math.round(Number(value) || 0);
    if (numeric > 0) {
      return "positive";
    }
    if (numeric < 0) {
      return "negative";
    }
    return "neutral";
  }

  function formattedDelta(value, unit) {
    const rounded = Math.round(Number(value) || 0);
    const prefix = rounded > 0 ? "+" : "";
    return unit === "pp" ? `${prefix}${number(rounded)} pp` : `${prefix}${number(rounded)}%`;
  }

  function renderTrendSvg(values, options) {
    const points = (Array.isArray(values) ? values : []).map((value) => Number(value) || 0);
    if (!points.length) {
      return "";
    }

    const width = options?.width || 112;
    const height = options?.height || 30;
    const padding = 2;
    const min = Math.min(...points);
    const max = Math.max(...points, min + 1);
    const range = Math.max(max - min, 1);
    const xStep = points.length === 1 ? 0 : (width - padding * 2) / (points.length - 1);
    const coordinates = points.map((value, index) => {
      const x = points.length === 1 ? width / 2 : padding + index * xStep;
      const y = padding + (1 - ((value - min) / range)) * (height - padding * 2);
      return [x, y];
    });
    const path = coordinates.map(([x, y], index) => `${index === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`).join(" ");
    const area = `${path} L${width - padding} ${height - padding} L${padding} ${height - padding} Z`;
    const stroke = options?.stroke || "#60a5fa";
    const fill = options?.fill || "#eff6ff";

    return `
      <svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-hidden="true">
        <path d="${area}" fill="${fill}"></path>
        <path d="${path}" fill="none" stroke="${stroke}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></path>
      </svg>
    `;
  }

  function currentSeries(row, metricKey) {
    const points = (row.relative_change_series || {})[metricKey] || [];
    return points.map((point) => Number(point.current) || 0);
  }

  function buildProductAreaSummaryRows() {
    const explicitRows = payload.product_area_summary || [];
    if (explicitRows.length) {
      return explicitRows;
    }

    const rows = payload.change_aware_rows || [];
    const groups = new Map();

    rows.forEach((row) => {
      const areaName = row.product_area_name || row.product_area || row.page_name || "Unassigned";
      const key = row.product_area_key || areaName;
      if (!groups.has(key)) {
        groups.set(key, {
          product_area: areaName,
          page_count: 0,
          companies_count: 0,
          adoption_pct: 0,
          users_count: 0,
          engaged_seconds: 0,
          rows: [],
          trends: {
            companies: [],
            adoption: [],
            users: [],
            engaged: []
          }
        });
      }

      const group = groups.get(key);
      group.rows.push(row);
      group.page_count += Number(row.page_count || 1) || 1;
      group.companies_count = Math.max(group.companies_count, Number(row.companies_count) || 0);
      group.adoption_pct = Math.max(group.adoption_pct, Number(row.adoption_pct) || 0);
      group.users_count = Math.max(group.users_count, Number(row.users_count) || 0);
      group.engaged_seconds += Number(row.engaged_seconds) || 0;
      group.trends.companies = mergeTrendMax(group.trends.companies, currentSeries(row, "companies"));
      group.trends.adoption = mergeTrendMax(group.trends.adoption, currentSeries(row, "adoption"));
      group.trends.users = mergeTrendMax(group.trends.users, currentSeries(row, "users"));
      group.trends.engaged = mergeTrendSum(group.trends.engaged, currentSeries(row, "engaged"));
    });

    const summaries = Array.from(groups.values()).map((group) => {
      const groupRows = group.rows || [];
      const leadRow = [...groupRows].sort((left, right) => {
        const engagedDifference = (Number(right.engaged_seconds) || 0) - (Number(left.engaged_seconds) || 0);
        return engagedDifference || (Number(right.companies_count) || 0) - (Number(left.companies_count) || 0);
      })[0];
      const engagedDelta = aggregateDeltaFromRows(groupRows, "engaged_seconds", "engaged");

      return {
        ...group,
        companies_count: Number(leadRow?.companies_count) || group.companies_count,
        companies_change_pct: Number((leadRow?.deltas || {}).companies?.value) || 0,
        adoption_pct: Number(leadRow?.adoption_pct) || group.adoption_pct,
        adoption_change_pp: Number((leadRow?.deltas || {}).adoption?.value) || 0,
        users_count: Number(leadRow?.users_count) || group.users_count,
        users_change_pct: Number((leadRow?.deltas || {}).users?.value) || 0,
        engaged_change_pct: engagedDelta
      };
    });
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
      .sort((left, right) => right.engaged_seconds - left.engaged_seconds || right.companies_count - left.companies_count);
  }

  function aggregateDeltaFromRows(rows, valueKey, deltaKey) {
    const totals = rows.reduce(
      (accumulator, row) => {
        const current = Number(row[valueKey]) || 0;
        const delta = Number((row.deltas || {})[deltaKey]?.value) || 0;
        const previous = delta <= -100 ? 0 : current / (1 + delta / 100);
        accumulator.current += current;
        accumulator.previous += Number.isFinite(previous) ? previous : 0;
        return accumulator;
      },
      { current: 0, previous: 0 }
    );

    if (totals.previous <= 0) {
      return totals.current > 0 ? 100 : 0;
    }

    return Math.round(((totals.current - totals.previous) / totals.previous) * 100);
  }

  function mergeTrendMax(left, right) {
    const length = Math.max(left.length, right.length);
    return Array.from({ length }, (_, index) => Math.max(Number(left[index]) || 0, Number(right[index]) || 0));
  }

  function mergeTrendSum(left, right) {
    const length = Math.max(left.length, right.length);
    return Array.from({ length }, (_, index) => (Number(left[index]) || 0) + (Number(right[index]) || 0));
  }

  function getProductAreaMetricDisplay(row, metricKey) {
    if (metricKey === "companies") {
      return { valueLabel: number(row.companies_count), deltaValue: row.companies_change_pct, deltaUnit: "%", barValue: row.companies_bar_value };
    }
    if (metricKey === "adoption") {
      return { valueLabel: percent(row.adoption_pct), deltaValue: row.adoption_change_pp, deltaUnit: "pp", barValue: row.adoption_bar_value };
    }
    if (metricKey === "users") {
      return { valueLabel: number(row.users_count), deltaValue: row.users_change_pct, deltaUnit: "%", barValue: row.users_bar_value };
    }
    if (metricKey === "engaged") {
      return { valueLabel: duration(row.engaged_seconds), deltaValue: row.engaged_change_pct, deltaUnit: "%", barValue: row.engaged_bar_value };
    }
    return null;
  }

  function productAreaChangeScaleByMetric(rows) {
    return productAreaSummaryMetrics.reduce((lookup, metric) => {
      lookup[metric.key] = Math.max(
        ...rows.map((row) => Math.abs(Number(getProductAreaMetricDisplay(row, metric.key)?.deltaValue) || 0)),
        1
      );
      return lookup;
    }, {});
  }

  function productAreaMetricWidthByMetric(rows) {
    return productAreaSummaryMetrics.reduce((lookup, metric) => {
      lookup[metric.key] = Math.ceil(Math.max(
        ...rows.map((row) => {
          const display = getProductAreaMetricDisplay(row, metric.key);
          if (!display) {
            return 0;
          }
          const barWidth = Math.max(4, Math.round((clamp(Number(display.barValue) || 0, 0, 100) / 100) * 72));
          return barWidth + 4 + Math.ceil(String(display.valueLabel || "").length * 7.5);
        }),
        56
      ));
      return lookup;
    }, {});
  }

  function renderProductAreaDelta(display, metric, maxAbsDelta) {
    const deltaValue = Number(display.deltaValue) || 0;
    const direction = deltaDirectionFromValue(deltaValue, display.deltaUnit);
    const trackWidth = direction === "negative" ? 17 : 36;
    const barWidth = deltaValue === 0 ? 6 : Math.max(4, Math.round((Math.abs(deltaValue) / Math.max(maxAbsDelta, 1)) * trackWidth));
    const label = formattedDelta(deltaValue, display.deltaUnit);

    return `
      <div class="pages-change-delta" data-change-direction="${escapeHtml(direction)}" style="--pages-change-bar-width: ${barWidth}px;" aria-label="${escapeHtml(`${metric.label} change ${label}`)}">
        <span class="pages-change-delta__plot">
          <span class="pages-change-delta__bar pages-change-delta__bar--${escapeHtml(direction)}"></span>
        </span>
        <span class="pages-change-delta__label ${directionClass(direction)}">${escapeHtml(label)}</span>
      </div>
    `;
  }

  function renderDisplayMetricBarValue(display, metric, widthOverride) {
    const barWidth = Math.max(4, Math.round((clamp(Number(display.barValue) || 0, 0, 100) / 100) * 72));
    const blockWidth = widthOverride || metric.width || 104;

    return `
      <div class="pages-metric-value" style="--pages-metric-block-width: ${blockWidth}px;">
        <div class="pages-value-bar" style="--pages-value-bar-width: ${barWidth}px;" aria-label="${escapeHtml(`${metric.label} ${display.valueLabel}`)}">
          <span class="pages-value-bar__bar bg-c-light-blue"></span>
          <span class="pages-value-bar__label">${escapeHtml(display.valueLabel)}</span>
        </div>
      </div>
    `;
  }

  function renderProductAreaMetricCell({ row, metric, trendValues, maxAbsDelta, metricBlockWidth }) {
    const display = getProductAreaMetricDisplay(row, metric.key);
    if (!display) {
      return "";
    }

    const splitMetricBlockWidth = metricBlockWidth || 104;
    return `
      <td class="product-area-metric-cell pages-split-change-cell py-3.5 align-middle" style="--pages-split-metric-width: ${splitMetricBlockWidth}px;">
        <div class="product-area-metric-layout">
          <div class="pages-split-change-group">
            ${renderDisplayMetricBarValue(display, metric, splitMetricBlockWidth)}
            ${renderProductAreaDelta(display, metric, maxAbsDelta)}
          </div>
          <span class="product-area-metric__trend">${renderTrendSvg(trendValues, { width: 96, height: 30 })}</span>
        </div>
      </td>
    `;
  }

  function renderProductAreaSummary() {
    const target = document.getElementById("product-area-summary-body");
    if (!target) {
      return;
    }

    const rows = buildProductAreaSummaryRows();
    if (!rows.length) {
      target.innerHTML = `<tr><td colspan="6" class="px-6 py-10 text-center text-slate-500">No product area data found for this period.</td></tr>`;
      return;
    }

    const changeScale = productAreaChangeScaleByMetric(rows);
    const metricWidths = productAreaMetricWidthByMetric(rows);

    target.innerHTML = rows.map((row) => {
      const areaName = row.product_area || row.product_area_name || "Unassigned";
      return `
        <tr class="align-middle hover:bg-slate-50">
          <td class="py-3.5 pl-0 font-medium text-slate-900">${escapeHtml(areaName)}</td>
          <td class="product-area-pages-cell py-3.5 tabular-nums">${number(row.page_count)}</td>
          ${renderProductAreaMetricCell({ row, metric: productAreaSummaryMetrics[0], trendValues: row.trends?.companies, maxAbsDelta: changeScale.companies, metricBlockWidth: metricWidths.companies })}
          ${renderProductAreaMetricCell({ row, metric: productAreaSummaryMetrics[1], trendValues: row.trends?.adoption, maxAbsDelta: changeScale.adoption, metricBlockWidth: metricWidths.adoption })}
          ${renderProductAreaMetricCell({ row, metric: productAreaSummaryMetrics[2], trendValues: row.trends?.users, maxAbsDelta: changeScale.users, metricBlockWidth: metricWidths.users })}
          ${renderProductAreaMetricCell({ row, metric: productAreaSummaryMetrics[3], trendValues: row.trends?.engaged, maxAbsDelta: changeScale.engaged, metricBlockWidth: metricWidths.engaged })}
        </tr>
      `;
    }).join("");
  }

  function renderMetricBarValue(row, metric, widthOverride) {
    return renderDisplayMetricBarValue({ valueLabel: metric.value(row), barValue: rowBar(row, metric) }, metric, widthOverride);
  }

  function splitMetricWidth(rows, metric) {
    return Math.max(
      ...rows.map((row) => {
        const label = metric.value(row);
        const barWidth = Math.max(4, Math.round((rowBar(row, metric) / 100) * 72));
        return barWidth + 4 + Math.ceil(String(label || "").length * 7.5);
      }),
      56
    );
  }

  function renderSplitChangeDelta(row, metric, maxAbsDelta) {
    const delta = rowDelta(row, metric);
    const direction = delta.direction || "neutral";
    const trackWidth = direction === "negative" ? 17 : 36;
    const magnitude = deltaMagnitude(delta);
    const barWidth = magnitude === 0 ? 6 : Math.max(4, Math.round((magnitude / Math.max(maxAbsDelta, 1)) * trackWidth));
    const label = deltaLabel(delta, metric);

    return `
      <div class="pages-change-delta" data-change-direction="${escapeHtml(direction)}" style="--pages-change-bar-width: ${barWidth}px;" aria-label="${escapeHtml(`${metric.label} change ${label}`)}">
        <span class="pages-change-delta__plot">
          <span class="pages-change-delta__bar pages-change-delta__bar--${escapeHtml(direction)}"></span>
        </span>
        <span class="pages-change-delta__label ${directionClass(direction)}">${escapeHtml(label)}</span>
      </div>
    `;
  }

  function renderSplitMetricCell(row, metric, maxAbsDelta, width) {
    return `
      <td class="pages-split-change-cell py-3.5 pr-6 align-middle" style="--pages-split-metric-width: ${width}px;">
        <div class="pages-split-change-group">
          ${renderMetricBarValue(row, metric, width)}
          ${renderSplitChangeDelta(row, metric, maxAbsDelta)}
        </div>
      </td>
    `;
  }

  function renderRows() {
    const target = document.getElementById("pages-change-table-body");
    const rows = payload.change_aware_rows || [];
    if (!target) {
      return;
    }

    if (!rows.length) {
      target.innerHTML = `<tr><td colspan="10" class="px-6 py-10 text-center text-slate-500">No page metrics found for this period.</td></tr>`;
      return;
    }

    const deltaScale = {};
    const metricWidths = {};
    metrics.forEach((metric) => {
      if (!metric.valueOnly) {
        deltaScale[metric.key] = Math.max(...rows.map((row) => deltaMagnitude(rowDelta(row, metric))), 1);
        metricWidths[metric.key] = splitMetricWidth(rows, metric);
      }
    });

    target.innerHTML = rows.map((row) => `
      <tr class="group align-middle hover:bg-slate-50">
        <td class="sticky left-0 z-[1] bg-white py-3.5 pl-0 pr-6 font-medium group-hover:bg-slate-50">
          <a class="text-sky-800 underline-offset-2 hover:underline" href="#">${escapeHtml(row.page_name || row.product_area_name)}</a>
        </td>
        ${metrics.map((metric) => {
          if (metric.valueOnly) {
            return `<td class="py-3.5 pr-6 align-middle">${renderMetricBarValue(row, metric)}</td>`;
          }
          return renderSplitMetricCell(row, metric, deltaScale[metric.key], metricWidths[metric.key]);
        }).join("")}
      </tr>
    `).join("");
  }

  function mountPageMetricsStickyHeader() {
    const table = document.querySelector(".pages-combined-table");
    const tableHead = table?.querySelector("thead");
    const scrollContainer = table?.closest("[data-page-metrics-scroll]");

    if (!table || !tableHead || !scrollContainer) {
      return;
    }

    let stickyHeader = document.getElementById("page-metrics-sticky-header");
    if (!stickyHeader) {
      stickyHeader = document.createElement("div");
      stickyHeader.id = "page-metrics-sticky-header";
      stickyHeader.className = "page-metrics-sticky-header";
      stickyHeader.setAttribute("aria-hidden", "true");
      document.body.appendChild(stickyHeader);
    }

    const cloneTable = table.cloneNode(false);
    const cloneHead = tableHead.cloneNode(true);
    cloneHead.querySelectorAll("[id]").forEach((element) => element.removeAttribute("id"));
    cloneHead.querySelectorAll("[tabindex]").forEach((element) => element.removeAttribute("tabindex"));
    cloneTable.appendChild(cloneHead);
    stickyHeader.replaceChildren(cloneTable);

    const syncStickyHeader = () => {
      const stickyTop = document.querySelector("body > nav")?.getBoundingClientRect().height || 48;
      const tableRect = table.getBoundingClientRect();
      const scrollRect = scrollContainer.getBoundingClientRect();
      const scrollStyle = window.getComputedStyle(scrollContainer);
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
    window.addEventListener("scroll", syncStickyHeader, { passive: true });
    window.addEventListener("resize", syncStickyHeader);
    scrollContainer.addEventListener("scroll", syncStickyHeader, { passive: true });
  }

  function collectDates(series) {
    return Array.from(new Set(series.flatMap((item) => (item.data || []).map((point) => point.date)))).sort();
  }

  function renderLineChart(elementId, data, formatter, emptyLabel) {
    const target = document.getElementById(elementId);
    if (!target) {
      return;
    }

    const series = (data?.series || []).filter((item) => (item.data || []).length);
    const dates = collectDates(series);
    if (!series.length || !dates.length) {
      target.innerHTML = emptyState(emptyLabel);
      return;
    }

    const width = 760;
    const height = 260;
    const left = 48;
    const right = 18;
    const top = 16;
    const bottom = 42;
    const plotWidth = width - left - right;
    const plotHeight = height - top - bottom;
    const values = series.flatMap((item) => item.data || []).map((point) => Number(point.value) || 0);
    const maxValue = Math.max(...values, 1);
    const xFor = (index) => left + (dates.length === 1 ? plotWidth / 2 : (index / (dates.length - 1)) * plotWidth);
    const yFor = (value) => top + (1 - ((Number(value) || 0) / maxValue)) * plotHeight;
    const grid = [0, 0.25, 0.5, 0.75, 1].map((ratio) => {
      const y = top + ratio * plotHeight;
      const label = formatter(Math.round(maxValue * (1 - ratio)));
      return `
        <line x1="${left}" y1="${y}" x2="${width - right}" y2="${y}" stroke="#e2e8f0" stroke-width="1"></line>
        <text x="${left - 8}" y="${y + 4}" text-anchor="end" font-size="11" fill="#64748b">${escapeHtml(label)}</text>
      `;
    }).join("");

    const lines = series.map((item, seriesIndex) => {
      const byDate = new Map((item.data || []).map((point) => [point.date, Number(point.value) || 0]));
      const coordinates = dates.map((dateValue, index) => [xFor(index), yFor(byDate.get(dateValue) || 0), byDate.get(dateValue) || 0, dateValue]);
      const path = coordinates.map(([x, y], index) => `${index === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`).join(" ");
      const color = colorForKey(item.product_area_key || item.name, seriesIndex);
      return `
        <path d="${path}" fill="none" stroke="${color}" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"></path>
        ${coordinates.map(([x, y, value, dateValue]) => `
          <circle cx="${x}" cy="${y}" r="3" fill="${color}">
            <title>${escapeHtml(`${item.name}\n${formatDateLabel(dateValue)}: ${formatter(value)}`)}</title>
          </circle>
        `).join("")}
      `;
    }).join("");

    const axisLabels = dates.map((dateValue, index) => {
      if (dates.length > 10 && index !== 0 && index !== dates.length - 1 && index !== Math.floor(dates.length / 2)) {
        return "";
      }
      const x = xFor(index);
      return `<text x="${x}" y="${height - 12}" text-anchor="middle" font-size="11" fill="#64748b">${escapeHtml(formatDateLabel(dateValue))}</text>`;
    }).join("");

    const legendPageSize = 3;
    const legendPageCount = Math.max(1, Math.ceil(series.length / legendPageSize));
    const legend = series.map((item, index) => `
      <span class="pages-chart-legend-item" data-pages-chart-legend-item data-legend-page="${Math.floor(index / legendPageSize)}">
        <span class="pages-chart-legend-swatch" style="background-color: ${colorForKey(item.product_area_key || item.name, index)};"></span>
        <span>${escapeHtml(item.name)}</span>
      </span>
    `).join("");
    const legendControls = legendPageCount > 1
      ? `
        <div class="pages-chart-legend-controls" aria-label="Legend pages">
          <button type="button" class="pages-chart-legend-button" data-pages-legend-prev aria-label="Previous legend page">
            <span aria-hidden="true"></span>
          </button>
          <span class="pages-chart-legend-page" data-pages-legend-page-label>1/${legendPageCount}</span>
          <button type="button" class="pages-chart-legend-button pages-chart-legend-button--next" data-pages-legend-next aria-label="Next legend page">
            <span aria-hidden="true"></span>
          </button>
        </div>
      `
      : "";

    target.innerHTML = `
      <div class="pages-chart-legend pages-chart-legend--top" data-pages-chart-legend data-current-page="0" data-page-count="${legendPageCount}">
        <div class="pages-chart-legend-items">${legend}</div>
        ${legendControls}
      </div>
      <div class="pages-time-chart-plot">
        <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHtml(emptyLabel)}">
          ${grid}
          <line x1="${left}" y1="${height - bottom}" x2="${width - right}" y2="${height - bottom}" stroke="#cbd5e1"></line>
          ${lines}
          ${axisLabels}
        </svg>
      </div>
    `;
    mountChartLegendPagination(target);
  }

  function mountChartLegendPagination(target) {
    const legend = target.querySelector("[data-pages-chart-legend]");
    if (!legend) {
      return;
    }

    const pageCount = Number(legend.dataset.pageCount) || 1;
    const items = Array.from(legend.querySelectorAll("[data-pages-chart-legend-item]"));
    const label = legend.querySelector("[data-pages-legend-page-label]");
    const previousButton = legend.querySelector("[data-pages-legend-prev]");
    const nextButton = legend.querySelector("[data-pages-legend-next]");
    const setPage = (page) => {
      const nextPage = clamp(page, 0, pageCount - 1);
      legend.dataset.currentPage = String(nextPage);
      items.forEach((item) => {
        item.hidden = Number(item.dataset.legendPage) !== nextPage;
      });
      if (label) {
        label.textContent = `${nextPage + 1}/${pageCount}`;
      }
      if (previousButton) {
        previousButton.disabled = nextPage <= 0;
      }
      if (nextButton) {
        nextButton.disabled = nextPage >= pageCount - 1;
      }
    };

    previousButton?.addEventListener("click", () => setPage((Number(legend.dataset.currentPage) || 0) - 1));
    nextButton?.addEventListener("click", () => setPage((Number(legend.dataset.currentPage) || 0) + 1));
    setPage(0);
  }

  function splitItems(items) {
    const total = items.reduce((sum, item) => sum + item.value, 0);
    let bestIndex = 1;
    let accumulated = items[0]?.value || 0;
    let bestDistance = Math.abs(total / 2 - accumulated);

    for (let index = 1; index < items.length - 1; index += 1) {
      accumulated += items[index].value;
      const distance = Math.abs(total / 2 - accumulated);
      if (distance < bestDistance) {
        bestDistance = distance;
        bestIndex = index + 1;
      }
    }

    return [items.slice(0, bestIndex), items.slice(bestIndex)];
  }

  function treemapLayout(items, x, y, width, height) {
    if (!items.length) {
      return [];
    }
    if (items.length === 1) {
      return [{ ...items[0], x, y, width, height }];
    }

    const total = items.reduce((sum, item) => sum + item.value, 0);
    const [first, second] = splitItems(items);
    const firstTotal = first.reduce((sum, item) => sum + item.value, 0);

    if (width >= height) {
      const firstWidth = width * (firstTotal / total);
      return [
        ...treemapLayout(first, x, y, firstWidth, height),
        ...treemapLayout(second, x + firstWidth, y, width - firstWidth, height)
      ];
    }

    const firstHeight = height * (firstTotal / total);
    return [
      ...treemapLayout(first, x, y, width, firstHeight),
      ...treemapLayout(second, x, y + firstHeight, width, height - firstHeight)
    ];
  }

  function renderTreemap() {
    const target = document.getElementById("engaged-time-treemap-chart");
    if (!target) {
      return;
    }

    const children = (payload.engaged_time_treemap?.nodes || []).flatMap((node) => node.children || []);
    const items = children
      .map((child) => ({ ...child, value: Number(child.value || child.engaged_seconds) || 0 }))
      .filter((child) => child.value > 0)
      .sort((left, right) => right.value - left.value);

    if (!items.length) {
      target.innerHTML = emptyState("No engaged-time treemap data prepared yet.");
      return;
    }

    const width = 760;
    const height = 360;
    const rects = treemapLayout(items, 0, 0, width, height);
    const total = Math.max(Number(payload.engaged_time_treemap?.total_engaged_seconds) || 0, items.reduce((sum, item) => sum + item.value, 0));

    target.innerHTML = `
      <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Where users spend time">
        ${rects.map((rect) => {
          const gap = 3;
          const x = rect.x + gap;
          const y = rect.y + gap;
          const rectWidth = Math.max(0, rect.width - gap * 2);
          const rectHeight = Math.max(0, rect.height - gap * 2);
          const showLabel = rectWidth > 82 && rectHeight > 44;
          const share = total > 0 ? Math.round((rect.value / total) * 100) : 0;
          const color = colorForKey(rect.product_area_key || rect.name);
          const title = [
            rect.name,
            `Engaged time: ${rect.engaged_label || duration(rect.value)}`,
            `Visits: ${number(rect.visits_count)}`,
            `Companies: ${number(rect.companies_count)}`,
            `Adoption: ${percent(rect.adoption_pct)}`,
            `Share: ${number(share)}%`
          ].join("\n");
          return `
            <g>
              <rect x="${x}" y="${y}" width="${rectWidth}" height="${rectHeight}" rx="6" fill="${color}" opacity="0.90">
                <title>${escapeHtml(title)}</title>
              </rect>
              ${showLabel ? `
                <text x="${x + 10}" y="${y + 20}" fill="#ffffff" font-size="13" font-weight="600">${escapeHtml(truncate(rect.name, Math.floor(rectWidth / 7)))}</text>
                <text x="${x + 10}" y="${y + 38}" fill="#ffffff" font-size="12" opacity="0.90">${escapeHtml(rect.engaged_label || duration(rect.value))}</text>
              ` : ""}
            </g>
          `;
        }).join("")}
      </svg>
    `;
  }

  function unique(values) {
    return Array.from(new Set(values));
  }

  function renderSankey() {
    const target = document.getElementById("overview-flow-chart");
    if (!target) {
      return;
    }

    const normalizedLinks = (payload.sankey?.links || [])
      .map((link) => ({
        ...link,
        source: String(link.source || ""),
        target: String(link.target || ""),
        value: Number(link.value) || 0
      }))
      .filter((link) => link.source && link.target && link.source !== link.target && link.value > 0)
      .sort((left, right) => right.value - left.value);
    const adjacency = new Map();
    const hasPath = (start, end, visited = new Set()) => {
      if (start === end) {
        return true;
      }
      if (visited.has(start)) {
        return false;
      }
      visited.add(start);
      return Array.from(adjacency.get(start) || []).some((next) => hasPath(next, end, visited));
    };
    const links = [];

    normalizedLinks.forEach((link) => {
      if (links.length >= 18 || hasPath(link.target, link.source)) {
        return;
      }
      links.push(link);
      if (!adjacency.has(link.source)) {
        adjacency.set(link.source, new Set());
      }
      adjacency.get(link.source).add(link.target);
    });

    if (!links.length) {
      target.innerHTML = emptyState("No page-flow transitions prepared yet.");
      return;
    }

    const width = 1000;
    const height = 360;
    const nodeWidth = 14;
    const nodeGap = 18;
    const top = 18;
    const bottom = 18;
    const left = 80;
    const right = width - 180;
    const nodesByName = new Map();

    (payload.sankey?.nodes || []).forEach((node, index) => {
      const name = String(node.name || "");
      if (name && !nodesByName.has(name)) {
        nodesByName.set(name, {
          name,
          order: index,
          depth: 0,
          incoming: [],
          outgoing: [],
          incomingValue: 0,
          outgoingValue: 0,
          value: 0
        });
      }
    });

    links.forEach((link) => {
      [link.source, link.target].forEach((name) => {
        if (!nodesByName.has(name)) {
          nodesByName.set(name, {
            name,
            order: nodesByName.size,
            depth: 0,
            incoming: [],
            outgoing: [],
            incomingValue: 0,
            outgoingValue: 0,
            value: 0
          });
        }
      });

      const sourceNode = nodesByName.get(link.source);
      const targetNode = nodesByName.get(link.target);
      sourceNode.outgoing.push(link);
      sourceNode.outgoingValue += link.value;
      targetNode.incoming.push(link);
      targetNode.incomingValue += link.value;
    });

    const nodes = Array.from(nodesByName.values())
      .filter((node) => node.incoming.length || node.outgoing.length);

    nodes.forEach((node) => {
      node.value = Math.max(node.incomingValue, node.outgoingValue, 1);
    });

    const maxAllowedDepth = 3;
    links.forEach((link) => {
      const sourceNode = nodesByName.get(link.source);
      const targetNode = nodesByName.get(link.target);
      targetNode.depth = Math.max(targetNode.depth, Math.min(sourceNode.depth + 1, maxAllowedDepth));
    });

    let maxDepth = Math.max(...nodes.map((node) => node.depth), 1);
    nodes.forEach((node) => {
      if (node.incoming.length && !node.outgoing.length) {
        node.depth = maxDepth;
      }
    });

    links.forEach((link) => {
      const sourceNode = nodesByName.get(link.source);
      const targetNode = nodesByName.get(link.target);
      if (targetNode.depth <= sourceNode.depth) {
        if (sourceNode.depth < maxAllowedDepth) {
          targetNode.depth = sourceNode.depth + 1;
        } else {
          sourceNode.depth = Math.max(0, targetNode.depth - 1);
        }
      }
    });

    maxDepth = Math.max(...nodes.map((node) => node.depth), 1);

    const layers = Array.from({ length: maxDepth + 1 }, () => []);
    nodes.forEach((node) => {
      layers[node.depth].push(node);
    });

    layers.forEach((layer) => {
      layer.sort((leftNode, rightNode) => rightNode.value - leftNode.value || leftNode.order - rightNode.order);
    });

    const availableHeight = height - top - bottom;
    const maxLayerValue = Math.max(...layers.map((layer) => layer.reduce((sum, node) => sum + node.value, 0)), 1);
    const maxLayerCount = Math.max(...layers.map((layer) => layer.length), 1);
    const scale = Math.max(0.1, (availableHeight - nodeGap * Math.max(0, maxLayerCount - 1)) / maxLayerValue);

    layers.forEach((layer, depth) => {
      if (!layer.length) {
        return;
      }

      const rawHeights = layer.map((node) => Math.max(10, node.value * scale));
      const rawTotal = rawHeights.reduce((sum, value) => sum + value, 0);
      const gapTotal = nodeGap * Math.max(0, layer.length - 1);
      const shrink = rawTotal + gapTotal > availableHeight
        ? Math.max(0.1, (availableHeight - gapTotal) / rawTotal)
        : 1;
      const heights = rawHeights.map((value) => value * shrink);
      const layerHeight = heights.reduce((sum, value) => sum + value, 0) + gapTotal;
      let y = top + Math.max(0, (availableHeight - layerHeight) / 2);

      layer.forEach((node, index) => {
        node.x = left + (maxDepth === 0 ? 0 : (depth / maxDepth) * (right - left));
        node.y = y;
        node.height = heights[index];
        y += heights[index] + nodeGap;
      });
    });

    nodes.forEach((node) => {
      node.outgoing.sort((leftLink, rightLink) => {
        const leftNode = nodesByName.get(leftLink.target);
        const rightNode = nodesByName.get(rightLink.target);
        return (leftNode.y + leftNode.height / 2) - (rightNode.y + rightNode.height / 2);
      });
      node.incoming.sort((leftLink, rightLink) => {
        const leftNode = nodesByName.get(leftLink.source);
        const rightNode = nodesByName.get(rightLink.source);
        return (leftNode.y + leftNode.height / 2) - (rightNode.y + rightNode.height / 2);
      });
      node.sourceOffset = 0;
      node.targetOffset = 0;
    });

    const thicknessFor = (link) => Math.max(3, link.value * scale);
    const nodeColor = (node) => {
      if (node.depth === 0) {
        return "#64748b";
      }
      if (node.depth === 1) {
        return "#4269d0";
      }
      return "#6cc5b0";
    };
    const linkColor = (link, index) => {
      const sourceNode = nodesByName.get(link.source);
      return sourceNode?.depth === 0 ? "#64748b" : colorForKey(link.source, index);
    };

    const paths = links.map((link, index) => {
      const sourceNode = nodesByName.get(link.source);
      const targetNode = nodesByName.get(link.target);
      const thickness = thicknessFor(link);
      const sourceY = sourceNode.y + sourceNode.sourceOffset + thickness / 2;
      const targetY = targetNode.y + targetNode.targetOffset + thickness / 2;
      const sourceX = sourceNode.x + nodeWidth;
      const targetX = targetNode.x;
      const curve = Math.max(80, (targetX - sourceX) * 0.52);
      sourceNode.sourceOffset += thickness;
      targetNode.targetOffset += thickness;
      const title = [
        `${link.source} -> ${link.target}`,
        `${number(link.value)} transitions`,
        `${number(link.sessions_count)} sessions`,
        `${number(link.companies_count)} companies`
      ].join("\n");
      return `
        <path
          d="M${sourceX.toFixed(1)} ${sourceY.toFixed(1)} C${(sourceX + curve).toFixed(1)} ${sourceY.toFixed(1)}, ${(targetX - curve).toFixed(1)} ${targetY.toFixed(1)}, ${targetX.toFixed(1)} ${targetY.toFixed(1)}"
          fill="none"
          stroke="${linkColor(link, index)}"
          stroke-width="${thickness.toFixed(1)}"
          stroke-linecap="butt"
          opacity="0.28">
          <title>${escapeHtml(title)}</title>
        </path>
      `;
    }).join("");

    const nodeBars = nodes.map((node) => {
      const labelX = node.x + nodeWidth + 6;
      const labelY = node.y + node.height / 2 + 4;
      return `
        <g>
          <rect
            x="${node.x.toFixed(1)}"
            y="${node.y.toFixed(1)}"
            width="${nodeWidth}"
            height="${node.height.toFixed(1)}"
            rx="1"
            fill="${nodeColor(node)}"
            stroke="#ffffff"
            stroke-width="1">
            <title>${escapeHtml(`${node.name}\n${number(node.value)} transitions`)}</title>
          </rect>
          <text x="${labelX.toFixed(1)}" y="${labelY.toFixed(1)}" font-size="12" fill="#334155">${escapeHtml(truncate(node.name, 24))}</text>
        </g>
      `;
    }).join("");

    target.innerHTML = `
      <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Most common page flows">
        ${paths}
        ${nodeBars}
      </svg>
    `;
  }

  function scatterTooltip(point) {
    return [
      point.company_name || point.company_id || "Company",
      `${averageUsers(point.active_users)} avg active users`,
      `${duration(point.avg_engaged_seconds_per_user)} avg engaged/user`,
      `${duration(point.total_engaged_seconds)} total engaged`,
      `${number(point.visits_count)} visits`
    ].join("\n");
  }

  function niceStep(rawStep) {
    const value = Math.max(Number(rawStep) || 1, 1);
    const exponent = Math.floor(Math.log10(value));
    const magnitude = 10 ** exponent;
    const residual = value / magnitude;
    let niceResidual = 10;

    if (residual <= 1) {
      niceResidual = 1;
    } else if (residual <= 2) {
      niceResidual = 2;
    } else if (residual <= 2.5) {
      niceResidual = 2.5;
    } else if (residual <= 5) {
      niceResidual = 5;
    }

    return niceResidual * magnitude;
  }

  function makeLinearTicks(maxValue, desiredIntervals, shouldCeilDomain) {
    const safeMax = Math.max(Number(maxValue) || 0, 1);
    const step = niceStep(safeMax / Math.max(Number(desiredIntervals) || 1, 1));
    const domainMax = shouldCeilDomain ? Math.ceil(safeMax / step) * step : safeMax;
    const tickMax = shouldCeilDomain ? domainMax : Math.floor(safeMax / step) * step;
    const ticks = [];

    for (let value = 0; value <= tickMax + step / 1000; value += step) {
      ticks.push(Math.round(value * 1000) / 1000);
    }

    if (ticks.length < 2) {
      ticks.push(step);
    }

    return {
      domainMax: Math.max(domainMax, ticks[ticks.length - 1] || safeMax),
      ticks
    };
  }

  function boxesOverlap(leftBox, rightBox) {
    return !(
      leftBox.x2 < rightBox.x1 ||
      leftBox.x1 > rightBox.x2 ||
      leftBox.y2 < rightBox.y1 ||
      leftBox.y1 > rightBox.y2
    );
  }

  function scatterLabelPlacements(points, bounds) {
    const placed = [];
    const placements = new Map();
    const anchors = [
      { dx: 9, dy: -7, anchor: "start" },
      { dx: 9, dy: 7, anchor: "start" },
      { dx: -9, dy: -7, anchor: "end" },
      { dx: -9, dy: 7, anchor: "end" },
      { dx: 0, dy: -13, anchor: "middle" },
      { dx: 0, dy: 17, anchor: "middle" },
      { dx: 12, dy: 0, anchor: "start" },
      { dx: -12, dy: 0, anchor: "end" }
    ];

    [...points]
      .sort((leftPoint, rightPoint) => rightPoint.score - leftPoint.score)
      .forEach((point) => {
        const label = truncate(point.label, 22);
        const estimatedWidth = Math.max(24, label.length * 6.3);
        const estimatedHeight = 14;

        for (const anchor of anchors) {
          const textX = point.x + anchor.dx;
          const textY = point.y + anchor.dy;
          let x1 = textX;
          let x2 = textX + estimatedWidth;

          if (anchor.anchor === "end") {
            x1 = textX - estimatedWidth;
            x2 = textX;
          } else if (anchor.anchor === "middle") {
            x1 = textX - estimatedWidth / 2;
            x2 = textX + estimatedWidth / 2;
          }

          const box = {
            x1: x1 - 3,
            x2: x2 + 3,
            y1: textY - estimatedHeight,
            y2: textY + 3
          };

          if (
            box.x1 < bounds.left ||
            box.x2 > bounds.right ||
            box.y1 < bounds.top ||
            box.y2 > bounds.bottom ||
            placed.some((placedBox) => boxesOverlap(box, placedBox))
          ) {
            continue;
          }

          placed.push(box);
          placements.set(point.key, {
            label,
            textX,
            textY,
            anchor: anchor.anchor
          });
          break;
        }
      });

    return placements;
  }

  function renderScatterSvg(group, groupIndex) {
    const points = (group.points || []).slice(0, 80);
    if (!points.length) {
      return emptyState("No company engagement data prepared for this product area.");
    }

    const width = 720;
    const height = 360;
    const left = 64;
    const right = 42;
    const top = 58;
    const bottom = 54;
    const plotWidth = width - left - right;
    const plotHeight = height - top - bottom;
    const maxX = Math.max(...points.map((point) => Number(point.active_users) || 0), 1);
    const maxY = Math.max(...points.map((point) => Number(point.avg_engaged_seconds_per_user) || 0), 1);
    const xAxis = makeLinearTicks(maxX + Math.max(4, maxX * 0.22), 5, true);
    const yAxis = makeLinearTicks(maxY + Math.max(120, maxY * 0.08), 4, false);
    const xFor = (value) => left + ((Number(value) || 0) / xAxis.domainMax) * plotWidth;
    const yFor = (value) => top + (1 - ((Number(value) || 0) / yAxis.domainMax)) * plotHeight;
    const color = colorForKey(group.product_area_key || group.product_area_name, groupIndex);
    const plottedPoints = points.map((point, index) => {
      const activeUsers = Number(point.active_users) || 0;
      const avgEngaged = Number(point.avg_engaged_seconds_per_user) || 0;
      const totalEngaged = Number(point.total_engaged_seconds) || 0;
      return {
        key: `${point.company_id || point.company_name || "company"}-${index}`,
        label: point.company_name || point.company_id || "Company",
        point,
        x: xFor(activeUsers),
        y: yFor(avgEngaged),
        score: totalEngaged + activeUsers * 120
      };
    });
    const labelPlacements = scatterLabelPlacements(
      plottedPoints,
      {
        left: left + 2,
        right: width - right - 2,
        top: top - 30,
        bottom: height - bottom - 2
      }
    );

    return `
      <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHtml(group.product_area_name)} company engagement">
        <line x1="${left}" y1="${height - bottom}" x2="${width - right}" y2="${height - bottom}" stroke="#cbd5e1"></line>
        <line x1="${left}" y1="${top}" x2="${left}" y2="${height - bottom}" stroke="#cbd5e1"></line>
        <text x="${Math.max(0, left - 72)}" y="${top - 24}" font-size="12" font-weight="500" fill="#64748b">Avg engaged time / user</text>
        ${yAxis.ticks.map((tick) => {
          const y = yFor(tick);
          return `
            <line x1="${left - 6}" y1="${y.toFixed(1)}" x2="${left}" y2="${y.toFixed(1)}" stroke="#cbd5e1"></line>
            <text x="${left - 12}" y="${(y + 4).toFixed(1)}" text-anchor="end" font-size="11" fill="#64748b">${number(tick)}</text>
          `;
        }).join("")}
        ${xAxis.ticks.map((tick) => {
          const x = xFor(tick);
          return `
            <line x1="${x.toFixed(1)}" y1="${height - bottom}" x2="${x.toFixed(1)}" y2="${height - bottom + 6}" stroke="#cbd5e1"></line>
            <text x="${x.toFixed(1)}" y="${height - 24}" text-anchor="middle" font-size="11" fill="#64748b">${number(tick)}</text>
          `;
        }).join("")}
        <text x="${left + plotWidth / 2}" y="${height - 4}" text-anchor="middle" font-size="12" font-weight="500" fill="#64748b">Avg active users</text>
        ${plottedPoints.map(({ point, x, y, key }) => {
          const tooltipKey = `${group.product_area_key}::${point.company_id}`;
          const label = labelPlacements.get(key);
          return `
            <g>
              <circle
                cx="${x.toFixed(1)}"
                cy="${y.toFixed(1)}"
                r="5"
                fill="${color}"
                fill-opacity="0.72"
                stroke="#ffffff"
                stroke-width="1.5"
                tabindex="0"
                data-tooltip-key="${escapeHtml(tooltipKey)}"
                aria-label="${escapeHtml(scatterTooltip(point))}">
                <title>${escapeHtml(scatterTooltip(point))}</title>
              </circle>
              ${label ? `<text x="${label.textX.toFixed(1)}" y="${label.textY.toFixed(1)}" text-anchor="${label.anchor}" font-size="12" fill="#1f2937">${escapeHtml(label.label)}</text>` : ""}
            </g>
          `;
        }).join("")}
      </svg>
    `;
  }

  function createCompanyEngagementScatterSpec(group, config) {
    const pointColor = colorForKey(group.product_area_key || group.product_area_name, config.index);
    const points = (group.points || []).map((point) => {
      const avgEngaged = Number(point.avg_engaged_seconds_per_user) || 0;
      const totalEngaged = Number(point.total_engaged_seconds) || 0;
      const visits = Number(point.visits_count ?? point.visits) || 0;
      const activeUsers = Number(point.active_users) || 0;

      return {
        company_id: point.company_id,
        company_name: point.company_name || point.company_id || "Company",
        active_users: activeUsers,
        active_users_label: point.active_users_label || averageUsers(activeUsers),
        avg_engaged_seconds_per_user: avgEngaged,
        avg_engaged_label: point.avg_engaged_label || duration(avgEngaged),
        total_engaged_seconds: totalEngaged,
        total_engaged_label: point.total_engaged_label || duration(totalEngaged),
        visits
      };
    });
    const xMax = Math.max(...points.map((point) => point.active_users), 1);
    const yMax = Math.max(...points.map((point) => point.avg_engaged_seconds_per_user), 60);
    const xDomainMax = Math.ceil(xMax + Math.max(4, xMax * 0.22));
    const yDomainMax = Math.ceil(yMax + Math.max(120, yMax * 0.08));

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
      background: "#ffffff",
      config: {
        font: "Inter, ui-sans-serif, system-ui, sans-serif",
        axis: {
          domainColor: "#cbd5e1",
          gridColor: "#e2e8f0",
          gridOpacity: 1,
          labelColor: "#64748b",
          labelFont: "Inter, ui-sans-serif, system-ui, sans-serif",
          labelFontSize: 11,
          labelPadding: 7,
          tickColor: "#cbd5e1",
          titleColor: "#64748b",
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
          nice: true,
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
              stroke: { value: "#ffffff" },
              strokeWidth: { value: 1.5 }
            },
            update: {
              cursor: { value: "pointer" },
              fill: [
                { test: "hoveredCompany === datum.company_name", value: "#ff8ab7" },
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
              fill: { value: "#1f2937" },
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
    if (!element || !window.vegaEmbed) {
      return;
    }

    let renderToken = 0;
    let isFontReady = !document?.fonts?.load;
    let isFontRenderQueued = false;
    const fontReadyPromise = isFontReady
      ? Promise.resolve()
      : Promise.all([
        document.fonts.load('400 12px "Inter"'),
        document.fonts.load('500 12px "Inter"'),
        document.fonts.ready
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

      window.vegaEmbed(element, createCompanyEngagementScatterSpec(group, { index, width }), {
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
            element.innerHTML = renderScatterSvg(group, index);
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

    if (window.ResizeObserver) {
      let animationFrame = null;
      const observer = new ResizeObserver(() => {
        if (animationFrame) {
          window.cancelAnimationFrame(animationFrame);
        }

        animationFrame = window.requestAnimationFrame(renderWhenFontReady);
      });

      observer.observe(element);
      element.__hymetryResizeObserver = observer;
    }
  }

  function renderScatter() {
    const target = document.getElementById("company-engagement-page-group-grid");
    if (!target) {
      return;
    }

    const groups = payload.company_engagement_by_product_area || [];
    if (!groups.length) {
      target.innerHTML = emptyState("No company engagement data prepared yet.");
      return;
    }

    target.innerHTML = groups.map((group, index) => `
      <article class="company-engagement-card rounded-lg border border-slate-200 bg-white p-4">
        <h3 class="text-sm font-semibold text-slate-900">${escapeHtml(group.product_area_name || group.product_area_key)}</h3>
        <div id="company-engagement-page-group-chart-${index}" class="company-engagement-chart mt-4 w-full">
          ${renderScatterSvg(group, index)}
        </div>
      </article>
    `).join("");

    if (window.vegaEmbed) {
      groups.forEach((group, index) => {
        mountCompanyEngagementScatterChart(document.getElementById(`company-engagement-page-group-chart-${index}`), group, index);
      });
    }
  }

  function formatDeltaLabel(value, unit) {
    const rounded = Math.round(Number(value) || 0);
    const prefix = rounded > 0 ? "+" : "";
    return unit === "pp" ? `${prefix}${number(rounded)} pp` : `${prefix}${number(rounded)}%`;
  }

  function actionMetricBarCell(valueLabel, deltaValue, unit, barValue, barClass, deltaLabel, deltaDirection) {
    const label = deltaLabel === "New" ? deltaLabel : formatDeltaLabel(deltaValue, unit);
    const direction = label === "New" ? "positive" : (deltaDirection || deltaDirectionFromValue(deltaValue, unit));
    return `
      <div class="w-full">
        <div class="flex w-full items-center justify-between gap-3">
          <span class="min-w-0 flex-1 whitespace-nowrap text-left font-medium leading-tight text-slate-900">${escapeHtml(valueLabel)}</span>
          <span class="flex-none whitespace-nowrap text-right text-xs font-medium leading-tight ${directionClass(direction)}" style="min-width: 44px;">${escapeHtml(label)}</span>
        </div>
        <div class="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
          <div class="h-full rounded-full ${barClass}" style="width: ${clamp(Number(barValue) || 0, 0, 100)}%"></div>
        </div>
      </div>
    `;
  }

  function renderActions() {
    const target = document.getElementById("overview-top-actions-grid");
    const pages = payload.top_actions_by_page || [];
    if (!target) {
      return;
    }

    if (!pages.length) {
      target.innerHTML = `<div class="col-span-full py-8 text-center text-slate-500">No page group actions found for this period.</div>`;
      return;
    }

    target.innerHTML = pages.map((page) => {
      const actions = (page.actions || [])
        .slice()
        .sort((left, right) => (Number(right.clicks_count) || 0) - (Number(left.clicks_count) || 0))
        .slice(0, 5);
      const maxClicks = Math.max(...actions.map((action) => Number(action.clicks_count) || 0), 1);
      return `
        <article class="min-w-0 rounded-lg border border-slate-200 bg-white p-4">
          <h3 class="text-sm font-semibold text-slate-900">${escapeHtml(page.page_label || page.url_normalized)}</h3>
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
              ${actions.length ? actions.map((action) => `
                <tr>
                  <td class="py-3.5 pr-6">
                    <span class="block truncate font-medium leading-6 text-slate-900" title="${escapeHtml(action.element_key)}">${escapeHtml(action.element_key)}</span>
                  </td>
                  <td class="py-3.5 pr-6 tabular-nums">${actionMetricBarCell(number(action.clicks_count), action.clicks_delta_pct, "%", ((Number(action.clicks_count) || 0) / maxClicks) * 100, "bg-c-orange", action.clicks_delta_label, action.clicks_delta_direction)}</td>
                  <td class="py-3.5 tabular-nums">${actionMetricBarCell(percent(action.visits_pct), action.visits_pct_delta_pp, "pp", action.visits_pct, "bg-c-purple", action.visits_pct_delta_label, action.visits_pct_delta_direction)}</td>
                </tr>
              `).join("") : `<tr><td colspan="3" class="py-6 text-center text-slate-500">No clicked elements for this page.</td></tr>`}
            </tbody>
          </table>
        </article>
      `;
    }).join("");
  }

  function hydrateScatterTooltips() {
    const url = root.getAttribute("data-scatter-tooltips-url");
    if (!url) {
      return;
    }

    const setElementTitle = (element, title) => {
      element.setAttribute("aria-label", title);
      let titleNode = element.querySelector("title");
      if (!titleNode) {
        titleNode = document.createElementNS("http://www.w3.org/2000/svg", "title");
        element.appendChild(titleNode);
      }
      titleNode.textContent = title;
    };

    const load = () => {
      fetch(url, { headers: { Accept: "application/json" } })
        .then((response) => response.ok ? response.json() : null)
        .then((data) => {
          if (!data?.items?.length) {
            return;
          }

          const byKey = new Map(data.items.map((item) => [`${item.product_area_key}::${item.company_id}`, item]));
          root.querySelectorAll("[data-tooltip-key]").forEach((element) => {
            const item = byKey.get(element.getAttribute("data-tooltip-key"));
            if (!item) {
              return;
            }
            setElementTitle(element, [
              item.company_name || item.company_id || "Company",
              `${averageUsers(item.active_users)} avg active users`,
              `${duration(item.avg_engaged_seconds_per_user)} avg engaged/user`,
              `${duration(item.total_engaged_seconds)} total engaged`,
              `${number(item.visits_count)} visits`,
              `${number(item.clicks_count)} clicks`
            ].join("\n"));
          });
        })
        .catch(() => {});
    };

    if ("requestIdleCallback" in window) {
      window.requestIdleCallback(load);
    } else {
      window.setTimeout(load, 0);
    }
  }

  renderKpis();
  renderProductAreaSummary();
  renderRows();
  mountPageMetricsStickyHeader();
  renderLineChart(
    "top-pages-visits-time-chart",
    payload.top_pages_by_visits_over_time,
    number,
    "No visits time-series data prepared yet."
  );
  renderLineChart(
    "top-pages-engaged-time-chart",
    payload.top_pages_by_engaged_time_over_time,
    duration,
    "No engaged-time series data prepared yet."
  );
  renderTreemap();
  renderSankey();
  renderScatter();
  renderActions();
  hydrateScatterTooltips();
})();
