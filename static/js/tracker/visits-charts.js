(() => {
  "use strict";

  const tooltipUi = window.HymetryAnalyticsTooltips || {
    render({ title = "", rows = [] } = {}) {
      const body = rows.map((row) => `<span><span>${escapeHtml(row.label)}</span> <strong>${escapeHtml(row.value)}</strong></span>`).join("");
      return `<span>${title ? `<strong>${escapeHtml(title)}</strong>` : ""}${body}</span>`;
    },
    echarts(options = {}) {
      return options;
    }
  };

  if (!window.echarts || !window.VisitsChartHelpers) return;

  const {
    calculateSegmentLabelLayout,
    buildProductAreaSegments,
    calculateVisibleMinutes,
    calculateP85ActiveMinutes,
    countDistinctPageIdentities,
    splitSegmentsForVisibleRange
  } = window.VisitsChartHelpers;
  const sessionList = document.querySelector("[data-visits-session-list]");
  const timelineRuler = document.querySelector("#timeline-ruler [data-visits-timeline-ticks]");
  if (!sessionList || !timelineRuler) return;

  const colorCanvas = document.createElement("canvas");
  const colorContext = colorCanvas.getContext("2d", { willReadFrequently: true });
  colorCanvas.width = 1;
  colorCanvas.height = 1;

  const colorChannels = (color) => {
    if (!colorContext) return null;
    colorContext.clearRect(0, 0, 1, 1);
    colorContext.fillStyle = "#4269d0";
    colorContext.fillStyle = color || "#4269d0";
    colorContext.fillRect(0, 0, 1, 1);
    return Array.from(colorContext.getImageData(0, 0, 1, 1).data.slice(0, 3));
  };

  const lighterColor = (color, amount = 0.35) => {
    const channels = colorChannels(color);
    if (!channels) return color;
    const lighten = (channel) => Math.round(channel + (255 - channel) * amount);
    return `rgb(${lighten(channels[0])}, ${lighten(channels[1])}, ${lighten(channels[2])})`;
  };

  const readableTextColor = (backgroundColor) => {
    const channels = colorChannels(backgroundColor);
    if (!channels) return "#0f172a";
    const brightness = (channels[0] * 0.299 + channels[1] * 0.587 + channels[2] * 0.114) / 255;
    return brightness > 0.62 ? "#0f172a" : "#ffffff";
  };

  const formatDuration = (seconds) => {
    const totalSeconds = Math.max(0, Math.round(Number(seconds) || 0));
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const remainingSeconds = totalSeconds % 60;
    const parts = [];
    if (hours) parts.push(`${hours}h`);
    if (minutes) parts.push(`${minutes}m`);
    if (remainingSeconds || !parts.length) parts.push(`${remainingSeconds}s`);
    return parts.join(" ");
  };

  const formatCompactDuration = (seconds) => {
    const totalSeconds = Math.max(0, Math.round(Number(seconds) || 0));
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const remainingSeconds = totalSeconds % 60;
    if (hours) return minutes ? `${hours}h ${minutes}m` : `${hours}h`;
    if (minutes) return remainingSeconds ? `${minutes}m ${remainingSeconds}s` : `${minutes}m`;
    return `${remainingSeconds}s`;
  };

  const formatAccessibleDuration = (seconds) => {
    const totalSeconds = Math.max(0, Math.round(Number(seconds) || 0));
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const remainingSeconds = totalSeconds % 60;
    const parts = [];
    if (hours) parts.push(`${hours} ${hours === 1 ? "hour" : "hours"}`);
    if (minutes) parts.push(`${minutes} ${minutes === 1 ? "minute" : "minutes"}`);
    if (remainingSeconds) parts.push(`${remainingSeconds} ${remainingSeconds === 1 ? "second" : "seconds"}`);
    return parts.join(", ") || "0 seconds";
  };

  const escapeHtml = (value) => String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");

  const renderTimelineRuler = (visibleMinutes) => {
    const ticks = document.createDocumentFragment();
    for (let minute = 0; minute <= visibleMinutes; minute += 1) {
      const left = `${(minute / visibleMinutes) * 100}%`;
      if (minute % 5 === 0) {
        const marker = document.createElement("div");
        marker.className = "visits-timeline-marker";
        marker.style.left = left;

        const label = document.createElement("span");
        label.className = "visits-timeline-marker__label";
        label.style.transform = minute === 0
          ? "translateX(-50%)"
          : minute === visibleMinutes
            ? "translateX(-100%)"
            : "translateX(-50%)";
        label.textContent = minute === 0
          ? "0"
          : minute >= 60 && minute % 60 === 0
            ? `${minute / 60}h`
            : `${minute} min`;

        const line = document.createElement("span");
        line.className = "visits-timeline-marker__line";
        marker.append(label, line);
        ticks.append(marker);
        continue;
      }

      const tick = document.createElement("span");
      tick.className = "visits-timeline-minor-tick";
      tick.style.left = left;
      ticks.append(tick);
    }
    timelineRuler.replaceChildren(ticks);
  };

  const rowStates = [];
  sessionList.querySelectorAll("[data-visits-chart]").forEach((container) => {
    const source = container.querySelector('script[type="application/json"]');
    if (!source) return;

    let chartData;
    try {
      chartData = JSON.parse(source.textContent);
    } catch {
      chartData = [];
    }

    const segments = buildProductAreaSegments(chartData).map((segment) => ({
      ...segment,
      isOther: false,
      pageCount: 1,
      pages: [],
      hoverBorderColor: lighterColor(segment.color),
      textColor: readableTextColor(segment.color),
      labelText: segment.page
    }));

    if (!segments.length) return;

    const totalSeconds = segments.reduce((sum, segment) => sum + segment.seconds, 0);
    const host = document.createElement("div");
    host.className = "visits-stacked-chart";
    host.setAttribute("role", "img");
    host.setAttribute("aria-label", segments.map((segment) => (
      `${segment.productArea}, ${segment.page}: ${formatDuration(segment.seconds)}`
    )).join(", "));

    const overflowIndicator = document.createElement("button");
    overflowIndicator.type = "button";
    overflowIndicator.className = "visits-overflow-indicator";
    overflowIndicator.hidden = true;
    overflowIndicator.setAttribute("aria-haspopup", "true");
    overflowIndicator.setAttribute("aria-expanded", "false");
    overflowIndicator.setAttribute("aria-controls", "visits-overflow-popover");

    // The reference starts with utility classes in the server markup, then
    // promotes populated cells to the full-width runtime chart container.
    container.className = "visits-stacked-chart-container";
    container.replaceChildren(host, overflowIndicator);
    const chart = window.echarts.init(host, null, { renderer: "canvas" });
    rowStates.push({
      chart,
      container,
      host,
      overflowIndicator,
      segments,
      totalSeconds
    });
  });

  if (!rowStates.length) return;

  const overflowPopover = document.createElement("div");
  overflowPopover.id = "visits-overflow-popover";
  overflowPopover.className = "visits-overflow-popover";
  overflowPopover.hidden = true;
  overflowPopover.setAttribute("role", "tooltip");
  document.body.appendChild(overflowPopover);

  const indicatorData = new WeakMap();
  let activeIndicator = null;
  let closePopoverTimer = null;

  const positionOverflowPopover = () => {
    if (!activeIndicator || overflowPopover.hidden) return;
    const anchor = activeIndicator.getBoundingClientRect();
    const popover = overflowPopover.getBoundingClientRect();
    const padding = 8;
    const maximumLeft = Math.max(padding, window.innerWidth - popover.width - padding);
    const left = Math.min(Math.max(padding, anchor.right - popover.width), maximumLeft);
    let top = anchor.bottom + padding;
    if (top + popover.height > window.innerHeight - padding) {
      top = Math.max(padding, anchor.top - popover.height - padding);
    }
    overflowPopover.style.left = `${left}px`;
    overflowPopover.style.top = `${top}px`;
  };

  const hideOverflowPopover = (restoreFocus = false) => {
    clearTimeout(closePopoverTimer);
    if (!activeIndicator) return;
    const previousIndicator = activeIndicator;
    previousIndicator.setAttribute("aria-expanded", "false");
    overflowPopover.hidden = true;
    activeIndicator = null;
    if (restoreFocus) previousIndicator.focus();
  };

  const renderOverflowPopover = (overflow) => {
    const title = document.createElement("div");
    title.className = "visits-overflow-popover__title";
    title.textContent = `${formatCompactDuration(overflow.hiddenActiveSeconds)} outside the current scale`;

    const list = document.createElement("div");
    list.className = "visits-overflow-popover__list";
    overflow.overflowSegments.forEach((segment) => {
      const row = document.createElement("div");
      row.className = "visits-overflow-popover__row";

      const swatch = document.createElement("span");
      swatch.className = "visits-overflow-popover__swatch";
      swatch.style.backgroundColor = segment.color || "#cbd5e1";
      swatch.setAttribute("aria-hidden", "true");

      const page = document.createElement("span");
      page.className = "visits-overflow-popover__page";
      page.textContent = `${segment.productArea} · ${segment.page}`;

      const duration = document.createElement("span");
      duration.className = "visits-overflow-popover__duration";
      duration.textContent = `${formatCompactDuration(segment.seconds)}${segment.partiallyVisible ? " more" : ""}`;
      row.append(swatch, page, duration);
      list.append(row);
    });

    overflowPopover.replaceChildren(title, list);
  };

  const showOverflowPopover = (indicator) => {
    const overflow = indicatorData.get(indicator);
    if (!overflow || !overflow.hiddenActiveSeconds) return;
    clearTimeout(closePopoverTimer);
    if (activeIndicator && activeIndicator !== indicator) {
      activeIndicator.setAttribute("aria-expanded", "false");
    }
    activeIndicator = indicator;
    indicator.setAttribute("aria-expanded", "true");
    renderOverflowPopover(overflow);
    overflowPopover.hidden = false;
    positionOverflowPopover();
  };

  const scheduleOverflowPopoverClose = () => {
    clearTimeout(closePopoverTimer);
    closePopoverTimer = setTimeout(() => {
      if (activeIndicator?.matches(":hover, :focus") || overflowPopover.matches(":hover, :focus-within")) return;
      hideOverflowPopover();
    }, 100);
  };

  overflowPopover.addEventListener("pointerenter", () => clearTimeout(closePopoverTimer));
  overflowPopover.addEventListener("pointerleave", scheduleOverflowPopoverClose);
  document.addEventListener("pointerdown", (event) => {
    if (!activeIndicator) return;
    if (activeIndicator.contains(event.target) || overflowPopover.contains(event.target)) return;
    hideOverflowPopover();
  }, true);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && activeIndicator) {
      event.preventDefault();
      hideOverflowPopover(true);
    }
  });

  rowStates.forEach(({ overflowIndicator }) => {
    overflowIndicator.addEventListener("pointerenter", () => showOverflowPopover(overflowIndicator));
    overflowIndicator.addEventListener("pointerleave", scheduleOverflowPopoverClose);
    overflowIndicator.addEventListener("focus", () => showOverflowPopover(overflowIndicator));
    overflowIndicator.addEventListener("blur", scheduleOverflowPopoverClose);
    overflowIndicator.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      showOverflowPopover(overflowIndicator);
    });
  });

  const rowSplitCache = new WeakMap();
  const splitForRange = (segments, visibleSeconds) => {
    let cache = rowSplitCache.get(segments);
    if (!cache) {
      cache = new Map();
      rowSplitCache.set(segments, cache);
    }
    if (!cache.has(visibleSeconds)) {
      cache.set(visibleSeconds, splitSegmentsForVisibleRange(segments, visibleSeconds));
    }
    return cache.get(visibleSeconds);
  };

  const p85ActiveMinutes = calculateP85ActiveMinutes(rowStates.map((state) => state.totalSeconds));
  const chartOption = (state, split, visibleSeconds, plotWidth) => ({
    animation: false,
    grid: {
      top: 0,
      right: 0,
      bottom: 0,
      left: 0,
      containLabel: false
    },
    tooltip: tooltipUi.echarts({
      trigger: "item",
      renderMode: "html",
      appendToBody: true,
      confine: false,
      formatter: (params) => {
        const time = formatDuration(params.data.originalSeconds ?? params.value);
        return tooltipUi.render({
          title: params.data.productArea,
          rows: [
            { label: "Page", value: params.seriesName },
            { label: "Active time", value: time }
          ]
        });
      }
    }),
    xAxis: {
      type: "value",
      min: 0,
      max: visibleSeconds,
      interval: 5 * 60,
      show: false
    },
    yAxis: {
      type: "category",
      data: [""],
      show: false
    },
    series: split.visibleSegments.map((segment) => {
      const segmentWidth = (segment.seconds / visibleSeconds) * plotWidth;
      const labelLayout = calculateSegmentLabelLayout({
        labelText: segment.labelText,
        segmentWidth
      });

      return {
        name: segment.page,
        type: "bar",
        stack: "visit",
        barWidth: 24,
        data: [{
          value: segment.seconds,
          originalSeconds: segment.originalSeconds,
          productArea: segment.productArea
        }],
        itemStyle: {
          color: segment.color,
          borderColor: "#ffffff",
          borderWidth: 1,
          borderRadius: 3
        },
        label: {
          show: labelLayout.show,
          position: "inside",
          color: segment.textColor,
          fontSize: 11,
          fontWeight: 500,
          fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif",
          width: labelLayout.width,
          overflow: "truncate",
          ellipsis: "…",
          formatter: segment.labelText
        },
        emphasis: {
          focus: "none",
          itemStyle: {
            color: segment.color,
            borderColor: segment.hoverBorderColor,
            borderWidth: 1,
            shadowBlur: 0
          }
        },
        blur: {
          itemStyle: { opacity: 1 },
          label: { opacity: 1 }
        }
      };
    })
  });

  const updateTruncatedCellTooltips = () => {
    sessionList.querySelectorAll(".visits-session-entity-links > *").forEach((label, index) => {
      const fullLabel = label.dataset.fullTooltipLabel || label.textContent.trim();
      const isTruncated = label.scrollWidth > label.clientWidth;
      const tooltipId = `visits-entity-tooltip-${index}`;
      const existingTooltip = label.querySelector(":scope > .metric-header-tooltip__content");

      label.dataset.fullTooltipLabel = fullLabel;

      if (!isTruncated) {
        existingTooltip?.remove();
        label.classList.remove("metric-header-tooltip");
        label.removeAttribute("aria-label");
        label.removeAttribute("aria-describedby");
        label.removeAttribute("data-tooltip-kind");
        if (label.tagName !== "A") label.removeAttribute("tabindex");
        return;
      }

      const entityType = label === label.parentElement?.firstElementChild ? "User" : "Company";
      const tooltipRows = [{ label: entityType, value: fullLabel }];
      const tooltipContent = existingTooltip || document.createElement("span");

      label.classList.add("metric-header-tooltip");
      label.dataset.tooltipKind = "entity-name";
      label.setAttribute("aria-label", tooltipUi.text ? tooltipUi.text(tooltipRows) : `${entityType}: ${fullLabel}`);
      label.setAttribute("aria-describedby", tooltipId);
      if (label.tagName !== "A") label.setAttribute("tabindex", "0");
      tooltipContent.id = tooltipId;
      tooltipContent.className = "metric-header-tooltip__content";
      tooltipContent.setAttribute("role", "tooltip");
      tooltipContent.innerHTML = tooltipUi.render({ rows: tooltipRows });
      if (!existingTooltip) label.appendChild(tooltipContent);
    });
  };

  let lastPlotWidth = 0;
  let lastVisibleMinutes = 0;
  let renderFrame = 0;
  const renderCharts = () => {
    renderFrame = 0;
    const plotWidth = Math.max(1, Math.floor(rowStates[0].host.clientWidth));
    const visibleMinutes = calculateVisibleMinutes({ plotWidth, p85ActiveMinutes });
    if (plotWidth === lastPlotWidth && visibleMinutes === lastVisibleMinutes) return;

    lastPlotWidth = plotWidth;
    lastVisibleMinutes = visibleMinutes;
    const visibleSeconds = visibleMinutes * 60;
    const majorTickWidth = plotWidth / (visibleMinutes / 5);
    sessionList.style.setProperty("--visits-major-tick-width", `${majorTickWidth}px`);
    renderTimelineRuler(visibleMinutes);

    rowStates.forEach((state) => {
      const split = splitForRange(state.segments, visibleSeconds);
      state.chart.setOption(chartOption(state, split, visibleSeconds, plotWidth), { notMerge: true });
      state.chart.resize();

      const pageCount = countDistinctPageIdentities(split.overflowSegments);
      state.overflowIndicator.hidden = split.hiddenActiveSeconds <= 0;
      if (split.hiddenActiveSeconds > 0) {
        state.overflowIndicator.textContent = `+${formatCompactDuration(split.hiddenActiveSeconds)}`;
        state.overflowIndicator.setAttribute(
          "aria-label",
          `${formatAccessibleDuration(split.hiddenActiveSeconds)} and ${pageCount} ${pageCount === 1 ? "page is" : "pages are"} outside the current chart scale`
        );
        indicatorData.set(state.overflowIndicator, split);
      } else {
        state.overflowIndicator.removeAttribute("aria-label");
        state.overflowIndicator.setAttribute("aria-expanded", "false");
        indicatorData.delete(state.overflowIndicator);
        if (activeIndicator === state.overflowIndicator) hideOverflowPopover();
      }
    });

    updateTruncatedCellTooltips();
    positionOverflowPopover();
  };

  const scheduleRender = () => {
    if (renderFrame) return;
    renderFrame = window.requestAnimationFrame(renderCharts);
  };

  if ("ResizeObserver" in window) {
    const chartColumnObserver = new ResizeObserver(scheduleRender);
    chartColumnObserver.observe(rowStates[0].host);
  } else {
    window.addEventListener("resize", scheduleRender, { passive: true });
  }
  window.addEventListener("scroll", positionOverflowPopover, { passive: true });
  scheduleRender();
})();
