(function (root, factory) {
  const api = factory();

  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }

  root.ReplayTimeline = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const DEFAULT_PAGE_COLOR = "#4269D0";
  const DEFAULT_NEUTRAL_COLOR = "#CBD5E1";
  const SEGMENT_KINDS = new Set(["page", "inactive", "unavailable"]);
  let timelineInstanceCount = 0;

  function toFiniteNumber(value, fallback) {
    const number = Number(value);
    return Number.isFinite(number) ? number : fallback;
  }

  function firstFinite(values) {
    for (const value of values) {
      const number = Number(value);
      if (Number.isFinite(number)) return number;
    }
    return undefined;
  }

  function clamp(value, minimum, maximum) {
    const min = toFiniteNumber(minimum, 0);
    const max = Math.max(min, toFiniteNumber(maximum, min));
    const number = toFiniteNumber(value, min);
    return Math.min(Math.max(number, min), max);
  }

  /**
   * Seek on the analytical clock and pass that elapsed value to rrweb unchanged.
   * The recording may be shorter or longer than the analytical visit, so its
   * own duration must never participate in this clamp.
   */
  function seekPlayer(player, requestedTimeMs, analyticalDurationMs) {
    const target = clamp(requestedTimeMs, 0, analyticalDurationMs);
    if (player && typeof player.goto === "function") player.goto(target);
    return target;
  }

  function analyticalDisplayTime(playerTimeMs, analyticalDurationMs) {
    return clamp(playerTimeMs, 0, analyticalDurationMs);
  }

  function formatDuration(durationMs) {
    const totalSeconds = Math.max(0, Math.round(toFiniteNumber(durationMs, 0) / 1000));
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const seconds = totalSeconds % 60;
    const parts = [];

    if (hours) parts.push(`${hours}h`);
    if (minutes) parts.push(`${minutes}m`);
    if (seconds || !parts.length) parts.push(`${seconds}s`);
    return parts.join(" ");
  }

  function normalizeKind(rawSegment) {
    const suppliedKind = String(rawSegment?.kind || rawSegment?.type || "")
      .trim()
      .toLowerCase();

    if (SEGMENT_KINDS.has(suppliedKind)) return suppliedKind;
    if (["idle", "inactivity"].includes(suppliedKind) || rawSegment?.inactive === true) {
      return "inactive";
    }
    if (["active", "pageview", "page_view"].includes(suppliedKind)) return "page";
    if (String(rawSegment?.page || "").trim()) return "page";
    return "unavailable";
  }

  function segmentLabel(rawSegment, kind) {
    const suppliedLabel = String(rawSegment?.label || rawSegment?.page || "").trim();
    if (suppliedLabel) return suppliedLabel;
    if (kind === "inactive") return "Inactive";
    if (kind === "unavailable") return "Unavailable";
    return "Unknown page";
  }

  function segmentColor(rawSegment, kind) {
    const suppliedColor = String(rawSegment?.color || "").trim();
    if (suppliedColor) return suppliedColor;
    return kind === "page" ? DEFAULT_PAGE_COLOR : DEFAULT_NEUTRAL_COLOR;
  }

  function colorChannels(color) {
    const value = String(color || "").trim();
    const hexMatch = value.match(/^#([0-9a-f]{3}|[0-9a-f]{4}|[0-9a-f]{6}|[0-9a-f]{8})$/i);
    if (hexMatch) {
      const hex = hexMatch[1];
      const channels = hex.length <= 4
        ? hex.slice(0, 3).split("").map((channel) => parseInt(channel + channel, 16))
        : [0, 2, 4].map((index) => parseInt(hex.slice(index, index + 2), 16));
      return channels;
    }

    const rgbMatch = value.match(/^rgba?\(\s*([\d.]+)\s*[, ]\s*([\d.]+)\s*[, ]\s*([\d.]+)/i);
    if (!rgbMatch) return null;
    return rgbMatch.slice(1, 4).map((channel) => clamp(Number(channel), 0, 255));
  }

  function readableTextColor(backgroundColor) {
    const channels = colorChannels(backgroundColor);
    if (!channels) return "#ffffff";
    const brightness = (
      channels[0] * 0.299
      + channels[1] * 0.587
      + channels[2] * 0.114
    ) / 255;
    return brightness > 0.62 ? "#0f172a" : "#ffffff";
  }

  function rawRanges(segments) {
    const ranges = [];
    let cursor = 0;

    (Array.isArray(segments) ? segments : []).forEach((rawSegment) => {
      if (!rawSegment || typeof rawSegment !== "object") return;

      const suppliedStart = firstFinite([
        rawSegment.startMs,
        rawSegment.start_ms,
        rawSegment.offsetMs,
        rawSegment.offset_ms
      ]);
      const startMs = suppliedStart === undefined ? cursor : suppliedStart;
      const suppliedEnd = firstFinite([rawSegment.endMs, rawSegment.end_ms]);
      const suppliedDuration = firstFinite([
        rawSegment.durationMs,
        rawSegment.duration_ms
      ]);
      const endMs = suppliedEnd === undefined
        ? suppliedDuration === undefined
          ? undefined
          : startMs + Math.max(0, suppliedDuration)
        : suppliedEnd;

      if (endMs === undefined || endMs <= startMs) return;

      ranges.push({ rawSegment, startMs, endMs });
      cursor = Math.max(cursor, endMs);
    });

    return ranges;
  }

  function unavailableSegment(startMs, endMs) {
    return {
      kind: "unavailable",
      startMs,
      endMs,
      durationMs: endMs - startMs,
      label: "Unavailable",
      page: "",
      pageKey: "",
      productArea: "Unavailable",
      productAreaKey: "",
      color: DEFAULT_NEUTRAL_COLOR,
      classified: false
    };
  }

  /**
   * Normalize a chronological analytics sequence to the replay clock.
   *
   * Input order is retained. Repeated pages remain separate, out-of-bounds
   * portions are clipped, overlaps are trimmed, and uncovered replay time is
   * represented as unavailable rather than being attributed to rrweb events.
   */
  function normalizeSegments(segments, suppliedTotalDuration) {
    const ranges = rawRanges(segments);
    const hasSuppliedDuration = suppliedTotalDuration !== undefined
      && suppliedTotalDuration !== null;
    const durationValue = typeof suppliedTotalDuration === "object"
      ? suppliedTotalDuration.totalDuration
        ?? suppliedTotalDuration.totalDurationMs
        ?? suppliedTotalDuration.durationMs
      : suppliedTotalDuration;
    const derivedDuration = ranges.reduce(
      (maximum, range) => Math.max(maximum, range.endMs),
      0
    );
    const totalDuration = Math.max(
      0,
      toFiniteNumber(durationValue, hasSuppliedDuration ? 0 : derivedDuration)
    );
    const normalized = [];
    let coverageEnd = 0;

    ranges.forEach(({ rawSegment, startMs: rawStart, endMs: rawEnd }) => {
      const clippedStart = clamp(rawStart, 0, totalDuration);
      const clippedEnd = clamp(rawEnd, 0, totalDuration);

      if (clippedStart > coverageEnd) {
        normalized.push(unavailableSegment(coverageEnd, clippedStart));
        coverageEnd = clippedStart;
      }

      const startMs = Math.max(coverageEnd, clippedStart);
      if (clippedEnd <= startMs) return;

      const kind = normalizeKind(rawSegment);
      const endMs = clippedEnd;
      normalized.push({
        ...rawSegment,
        kind,
        startMs,
        endMs,
        durationMs: endMs - startMs,
        label: segmentLabel(rawSegment, kind),
        color: segmentColor(rawSegment, kind)
      });
      coverageEnd = endMs;
    });

    if (coverageEnd < totalDuration) {
      normalized.push(unavailableSegment(coverageEnd, totalDuration));
    }

    return normalized;
  }

  function seekTimeFromClientX(clientXOrOptions, rect, totalDuration) {
    let clientX = clientXOrOptions;
    let bounds = rect;
    let duration = totalDuration;

    if (clientXOrOptions && typeof clientXOrOptions === "object") {
      clientX = clientXOrOptions.clientX;
      bounds = clientXOrOptions.rect || clientXOrOptions.bounds || clientXOrOptions;
      duration = clientXOrOptions.totalDuration
        ?? clientXOrOptions.totalDurationMs
        ?? clientXOrOptions.durationMs;
    }

    const left = toFiniteNumber(bounds?.left, 0);
    const right = toFiniteNumber(bounds?.right, left);
    const width = toFiniteNumber(bounds?.width, right - left);
    const safeDuration = Math.max(0, toFiniteNumber(duration, 0));
    if (width <= 0 || safeDuration <= 0) return 0;

    const proportion = clamp((toFiniteNumber(clientX, left) - left) / width, 0, 1);
    return proportion * safeDuration;
  }

  function segmentAccessibleText(segment) {
    return `${segment.label}: ${formatDuration(segment.durationMs)}`;
  }

  function segmentIndexAtTime(segments, timeMs, totalDuration) {
    const items = Array.isArray(segments) ? segments : [];
    const currentTime = clamp(timeMs, 0, totalDuration);
    let lower = 0;
    let upper = items.length - 1;

    while (lower <= upper) {
      const index = Math.floor((lower + upper) / 2);
      const segment = items[index];
      const includesFinalBoundary = currentTime === totalDuration
        && segment.endMs === totalDuration;

      if (currentTime < segment.startMs) {
        upper = index - 1;
      } else if (currentTime >= segment.endMs && !includesFinalBoundary) {
        lower = index + 1;
      } else {
        return index;
      }
    }

    return -1;
  }

  function segmentTooltipData(segment) {
    const duration = formatDuration(segment.durationMs);

    if (segment.kind === "page") {
      return {
        title: String(segment.productArea || "Unclassified").trim() || "Unclassified",
        rows: [
          { label: "Page", value: segment.label },
          { label: "Active time", value: duration }
        ]
      };
    }

    return {
      title: segment.kind === "inactive" ? "Inactive" : "Unavailable",
      rows: [{ label: "Duration", value: duration }]
    };
  }

  function appendSegmentTooltip({
    element,
    ownerDocument,
    segment,
    tooltipId,
    tooltipUi
  }) {
    const tooltip = ownerDocument.createElement("span");
    const renderer = tooltipUi && typeof tooltipUi.render === "function"
      ? tooltipUi.render.bind(tooltipUi)
      : null;

    element.className += " metric-header-tooltip";
    element.setAttribute("aria-describedby", tooltipId);
    element.setAttribute("data-tooltip-anchor", "pointer");
    element.setAttribute("data-tooltip-kind", "replay-segment");
    tooltip.id = tooltipId;
    tooltip.className = "metric-header-tooltip__content";
    tooltip.setAttribute("role", "tooltip");

    if (renderer) {
      tooltip.innerHTML = renderer(segmentTooltipData(segment));
    } else {
      tooltip.textContent = segmentAccessibleText(segment);
    }

    element.appendChild(tooltip);
  }

  function percentage(value, totalDuration) {
    if (totalDuration <= 0) return "0%";
    return `${(value / totalDuration) * 100}%`;
  }

  function create({
    container,
    segments = [],
    totalDuration = 0,
    hoverMarker,
    onSeek,
    tooltipUi
  } = {}) {
    if (!container || typeof container.addEventListener !== "function") {
      throw new TypeError("ReplayTimeline.create requires a container element");
    }

    const safeTotalDuration = Math.max(0, toFiniteNumber(totalDuration, 0));
    const normalizedSegments = normalizeSegments(segments, safeTotalDuration);
    const ownerDocument = container.ownerDocument
      || (typeof document !== "undefined" ? document : null);

    if (!ownerDocument || typeof ownerDocument.createElement !== "function") {
      throw new TypeError("ReplayTimeline.create requires a DOM document");
    }

    const sharedTooltipUi = tooltipUi
      || ownerDocument.defaultView?.HymetryAnalyticsTooltips
      || (typeof globalThis !== "undefined" ? globalThis.HymetryAnalyticsTooltips : null);
    const tooltipIdPrefix = `replay-timeline-tooltip-${++timelineInstanceCount}`;

    const segmentElements = normalizedSegments.map((segment, index) => {
      const element = ownerDocument.createElement("div");
      const label = ownerDocument.createElement("span");
      const accessibleText = segmentAccessibleText(segment);
      const pinTerminalMarker = segment.kind === "page"
        && segment.startMs > 0
        && segment.endMs === safeTotalDuration;

      element.className = [
        "replay-timeline-segment",
        `replay-timeline-segment--${segment.kind}`,
        pinTerminalMarker ? "replay-timeline-segment--terminal-marker" : ""
      ].filter(Boolean).join(" ");
      element.style.left = percentage(segment.startMs, safeTotalDuration);
      element.style.width = percentage(segment.durationMs, safeTotalDuration);
      element.style.backgroundColor = segment.color;
      element.style.color = readableTextColor(segment.color);
      element.setAttribute("aria-label", accessibleText);

      label.className = "replay-timeline-segment__label";
      label.textContent = segment.label;
      element.appendChild(label);
      appendSegmentTooltip({
        element,
        ownerDocument,
        segment,
        tooltipId: `${tooltipIdPrefix}-${index + 1}`,
        tooltipUi: sharedTooltipUi
      });
      return element;
    });

    if (typeof container.replaceChildren === "function") {
      container.replaceChildren(...segmentElements);
    } else {
      while (container.firstChild) container.removeChild(container.firstChild);
      segmentElements.forEach((element) => container.appendChild(element));
    }

    container.setAttribute("role", "slider");
    container.setAttribute("aria-orientation", "horizontal");
    container.setAttribute("aria-valuemin", "0");
    container.setAttribute("aria-valuemax", String(safeTotalDuration));
    if (!container.hasAttribute("aria-label")) {
      container.setAttribute("aria-label", "Replay timeline");
    }
    if (!container.hasAttribute("tabindex")) {
      container.setAttribute("tabindex", "0");
    }

    let currentTime = 0;
    let destroyed = false;
    const seekPreview = hoverMarker && hoverMarker.style ? hoverMarker : null;
    const pointerDocument = seekPreview
      && typeof ownerDocument.addEventListener === "function"
      ? ownerDocument
      : null;

    if (seekPreview) {
      seekPreview.hidden = true;
      if (typeof seekPreview.setAttribute === "function") {
        seekPreview.setAttribute("aria-hidden", "true");
      }
    }

    function setCurrentTime(timeMs) {
      currentTime = clamp(timeMs, 0, safeTotalDuration);
      const currentSegmentIndex = segmentIndexAtTime(
        normalizedSegments,
        currentTime,
        safeTotalDuration
      );
      if (currentSegmentIndex >= 0) {
        container.setAttribute(
          "aria-describedby",
          `${tooltipIdPrefix}-${currentSegmentIndex + 1}`
        );
      }
      container.setAttribute("aria-valuenow", String(currentTime));
      container.setAttribute(
        "aria-valuetext",
        `${formatDuration(currentTime)} of ${formatDuration(safeTotalDuration)}`
      );
      return currentTime;
    }

    function handleClick(event) {
      const nextTime = seekTimeFromClientX(
        event?.clientX,
        container.getBoundingClientRect(),
        safeTotalDuration
      );
      setCurrentTime(nextTime);
      if (typeof onSeek === "function") onSeek(nextTime);
    }

    function hideSeekPreview() {
      if (seekPreview) seekPreview.hidden = true;
    }

    function handlePointerMove(event) {
      if (!seekPreview) return;
      if (event?.pointerType === "touch") {
        hideSeekPreview();
        return;
      }

      const bounds = container.getBoundingClientRect();
      const left = toFiniteNumber(bounds?.left, 0);
      const right = toFiniteNumber(bounds?.right, left);
      const width = toFiniteNumber(bounds?.width, right - left);
      if (safeTotalDuration <= 0 || width <= 0) {
        hideSeekPreview();
        return;
      }

      const previewTime = seekTimeFromClientX(
        event?.clientX,
        bounds,
        safeTotalDuration
      );
      seekPreview.style.left = percentage(previewTime, safeTotalDuration);
      seekPreview.hidden = false;
    }

    function handleDocumentPointerMove(event) {
      if (!seekPreview) return;
      const target = event?.target;
      const pointerIsInside = target === container
        || (target && typeof container.contains === "function" && container.contains(target));
      if (event?.pointerType === "touch" || !pointerIsInside) hideSeekPreview();
    }

    function destroy() {
      if (destroyed) return;
      destroyed = true;
      container.removeEventListener("click", handleClick);
      if (seekPreview) {
        container.removeEventListener("pointermove", handlePointerMove);
        container.removeEventListener("pointerleave", hideSeekPreview);
        container.removeEventListener("pointercancel", hideSeekPreview);
        pointerDocument?.removeEventListener("pointermove", handleDocumentPointerMove);
        hideSeekPreview();
      }
    }

    setCurrentTime(0);
    container.addEventListener("click", handleClick);
    if (seekPreview) {
      container.addEventListener("pointermove", handlePointerMove);
      container.addEventListener("pointerleave", hideSeekPreview);
      container.addEventListener("pointercancel", hideSeekPreview);
      pointerDocument?.addEventListener("pointermove", handleDocumentPointerMove);
    }

    return {
      segments: normalizedSegments,
      totalDuration: safeTotalDuration,
      setCurrentTime,
      destroy
    };
  }

  return {
    clamp,
    analyticalDisplayTime,
    seekTimeFromClientX,
    seekPlayer,
    formatDuration,
    readableTextColor,
    segmentIndexAtTime,
    segmentTooltipData,
    normalizeSegments,
    create
  };
});
