(function (root, factory) {
  const helpers = factory();

  if (typeof module === "object" && module.exports) {
    module.exports = helpers;
  }

  root.VisitsChartHelpers = helpers;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const RANGE_STEP_MINUTES = 5;
  const MIN_VISIBLE_MINUTES = 20;
  const MAX_AUTOMATIC_MINUTES = 90;
  const MIN_PX_PER_MINUTE = 18;
  // Let common sub-30-minute visits make fuller use of wide displays before
  // expanding the ruler to cover more time.
  const MAX_PX_PER_MINUTE = 60;
  const DEFAULT_UNCLASSIFIED_AREA = "Unclassified";
  const DEFAULT_UNCLASSIFIED_COLOR = "#e2e8f0";
  const DEFAULT_CLASSIFIED_COLOR = "#4269d0";
  const SEGMENT_LABEL_HORIZONTAL_INSET = 14;
  const SEGMENT_LABEL_MINIMUM_WIDTH = 24;

  const ceilToStep = (value, step) => Math.ceil(value / step) * step;
  const floorToStep = (value, step) => Math.floor(value / step) * step;
  const clamp = (value, min, max) => Math.min(Math.max(value, min), max);

  function calculateSegmentLabelLayout({ labelText, segmentWidth }) {
    const text = String(labelText || "").trim();
    const availableWidth = Math.max(
      0,
      (Number(segmentWidth) || 0) - SEGMENT_LABEL_HORIZONTAL_INSET
    );

    return {
      show: Boolean(text) && availableWidth >= SEGMENT_LABEL_MINIMUM_WIDTH,
      width: availableWidth
    };
  }

  /**
   * Combine repeated page observations and order them for the stacked bar.
   * Product-area metadata and colors are supplied by the backend; this helper
   * deliberately contains no page-to-area or area-to-color lookup table.
   */
  function buildProductAreaSegments(chartData, options = {}) {
    const unclassifiedArea = String(options.unclassifiedArea || DEFAULT_UNCLASSIFIED_AREA);
    const unclassifiedColor = String(options.unclassifiedColor || DEFAULT_UNCLASSIFIED_COLOR);
    const classifiedFallbackColor = String(options.classifiedFallbackColor || DEFAULT_CLASSIFIED_COLOR);
    const rawEntries = Array.isArray(chartData) ? chartData : [];

    const pageTotals = new Map();

    rawEntries.forEach((rawEntry) => {
      const seconds = Math.max(0, Number(rawEntry?.seconds) || 0);
      if (seconds <= 0) return;

      const suppliedArea = String(rawEntry?.productArea || rawEntry?.product_area || "").trim();
      const isUnclassified = Boolean(rawEntry?.isUnclassified)
        || rawEntry?.classified === false
        || !suppliedArea;
      const productArea = isUnclassified ? unclassifiedArea : suppliedArea;
      const productAreaKey = String(
        rawEntry?.productAreaKey || rawEntry?.product_area_key || productArea
      ).trim() || productArea;
      const page = String(rawEntry?.page || "Unknown page").trim() || "Unknown page";
      const pageKey = String(rawEntry?.pageKey || rawEntry?.page_key || page).trim() || page;
      const key = `${isUnclassified ? "unclassified" : "classified"}\u0000${productAreaKey}\u0000${pageKey}`;
      const suppliedColor = String(rawEntry?.color || "").trim();
      const existing = pageTotals.get(key);

      if (existing) {
        existing.seconds += seconds;
        if (suppliedColor) existing.colors.add(suppliedColor);
        return;
      }

      pageTotals.set(key, {
        productArea,
        productAreaKey,
        page,
        pageKey,
        seconds,
        isUnclassified,
        colors: new Set(suppliedColor ? [suppliedColor] : [])
      });
    });

    const areaGroups = new Map();
    pageTotals.forEach((page) => {
      const key = `${page.isUnclassified ? "unclassified" : "classified"}\u0000${page.productAreaKey}`;
      if (!areaGroups.has(key)) {
        areaGroups.set(key, {
          productArea: page.productArea,
          productAreaKey: page.productAreaKey,
          seconds: 0,
          isUnclassified: page.isUnclassified,
          colors: new Set(),
          pages: []
        });
      }

      const group = areaGroups.get(key);
      group.seconds += page.seconds;
      page.colors.forEach((color) => group.colors.add(color));
      group.pages.push(page);
    });

    return Array.from(areaGroups.values())
      .sort((a, b) => b.seconds - a.seconds || a.productArea.localeCompare(b.productArea))
      .flatMap((group) => {
        const groupColor = group.isUnclassified
          ? unclassifiedColor
          : Array.from(group.colors).sort()[0] || classifiedFallbackColor;

        return group.pages
          .sort((a, b) => b.seconds - a.seconds || a.page.localeCompare(b.page))
          .map((page) => ({
            productArea: group.productArea,
            productAreaKey: group.productAreaKey,
            page: page.page,
            pageKey: page.pageKey,
            seconds: page.seconds,
            color: groupColor,
            isUnclassified: group.isUnclassified
          }));
      });
  }

  function calculateVisibleMinutes({ plotWidth, p85ActiveMinutes }) {
    const safePlotWidth = Math.max(0, Number(plotWidth) || 0);
    const safeP85 = Math.max(0, Number(p85ActiveMinutes) || 0);
    const desiredDataRange = clamp(
      ceilToStep(safeP85, RANGE_STEP_MINUTES),
      MIN_VISIBLE_MINUTES,
      MAX_AUTOMATIC_MINUTES
    );
    const maximumReadableRange = Math.max(
      MIN_VISIBLE_MINUTES,
      floorToStep(safePlotWidth / MIN_PX_PER_MINUTE, RANGE_STEP_MINUTES)
    );
    const rangeNeededForAvailableWidth = Math.max(
      MIN_VISIBLE_MINUTES,
      ceilToStep(safePlotWidth / MAX_PX_PER_MINUTE, RANGE_STEP_MINUTES)
    );

    return clamp(
      Math.max(
        Math.min(desiredDataRange, maximumReadableRange),
        rangeNeededForAvailableWidth
      ),
      MIN_VISIBLE_MINUTES,
      MAX_AUTOMATIC_MINUTES
    );
  }

  function calculateP85ActiveMinutes(activeSeconds) {
    const values = (Array.isArray(activeSeconds) ? activeSeconds : [])
      .map((seconds) => Math.max(0, Number(seconds) || 0))
      .filter((seconds) => seconds > 0)
      .sort((a, b) => a - b);

    if (!values.length) return 25;

    const nearestRankIndex = Math.max(0, Math.ceil(values.length * 0.85) - 1);
    return values[nearestRankIndex] / 60;
  }

  function overflowEntriesForSegment(segment, visibleSeconds) {
    const segmentSeconds = Math.max(0, Number(segment.seconds) || 0);
    const visible = clamp(Number(visibleSeconds) || 0, 0, segmentSeconds);
    const hidden = segmentSeconds - visible;
    if (hidden <= 0) return [];

    const segmentProductArea = String(
      segment.productArea || segment.product_area || DEFAULT_UNCLASSIFIED_AREA
    ).trim() || DEFAULT_UNCLASSIFIED_AREA;
    const segmentProductAreaKey = String(
      segment.productAreaKey || segment.product_area_key || segmentProductArea
    ).trim() || segmentProductArea;
    const segmentPage = String(segment.page || "Other").trim() || "Other";
    const segmentPageKey = String(
      segment.pageKey || segment.page_key || segmentPage
    ).trim() || segmentPage;

    const children = Array.isArray(segment.pages)
      ? segment.pages
        .map((page) => {
          const productArea = String(
            page?.productArea || page?.product_area || segmentProductArea
          ).trim() || segmentProductArea;
          const productAreaKey = String(
            page?.productAreaKey || page?.product_area_key || segmentProductAreaKey
          ).trim() || segmentProductAreaKey;
          const pageLabel = String(page?.page || "Unknown page").trim() || "Unknown page";
          const pageKey = String(page?.pageKey || page?.page_key || pageLabel).trim() || pageLabel;

          return {
            productArea,
            productAreaKey,
            page: pageLabel,
            pageKey,
            seconds: Math.max(0, Number(page?.seconds) || 0)
          };
        })
        .filter((page) => page.seconds > 0)
      : [];

    if (!segment.isOther || !children.length) {
      return [{
        page: segmentPage,
        pageKey: segmentPageKey,
        productArea: segmentProductArea,
        productAreaKey: segmentProductAreaKey,
        seconds: hidden,
        partiallyVisible: visible > 0,
        color: segment.color || null
      }];
    }

    const entries = [];
    let remainingVisible = visible;
    let accountedSeconds = 0;

    children.forEach((child) => {
      accountedSeconds += child.seconds;
      const childVisible = Math.min(child.seconds, remainingVisible);
      const childHidden = child.seconds - childVisible;
      remainingVisible -= childVisible;

      if (childHidden > 0) {
        entries.push({
          page: child.page,
          pageKey: child.pageKey,
          productArea: child.productArea,
          productAreaKey: child.productAreaKey,
          seconds: childHidden,
          partiallyVisible: childVisible > 0,
          color: segment.color || null
        });
      }
    });

    const ungroupedSeconds = Math.max(0, segmentSeconds - accountedSeconds);
    const ungroupedVisible = Math.min(ungroupedSeconds, remainingVisible);
    const ungroupedHidden = ungroupedSeconds - ungroupedVisible;
    if (ungroupedHidden > 0) {
      entries.push({
        page: segmentPage,
        pageKey: segmentPageKey,
        productArea: segmentProductArea,
        productAreaKey: segmentProductAreaKey,
        seconds: ungroupedHidden,
        partiallyVisible: ungroupedVisible > 0,
        color: segment.color || null
      });
    }

    return entries;
  }

  function countDistinctPageIdentities(entries) {
    const identities = new Set();

    (Array.isArray(entries) ? entries : []).forEach((entry) => {
      const productArea = String(
        entry?.productArea || entry?.product_area || DEFAULT_UNCLASSIFIED_AREA
      ).trim() || DEFAULT_UNCLASSIFIED_AREA;
      const productAreaKey = String(
        entry?.productAreaKey || entry?.product_area_key || productArea
      ).trim() || productArea;
      const page = String(entry?.page || "Unknown page").trim() || "Unknown page";
      const pageKey = String(entry?.pageKey || entry?.page_key || page).trim() || page;
      identities.add(`${productAreaKey}\u0000${pageKey}`);
    });

    return identities.size;
  }

  function splitSegmentsForVisibleRange(segments, visibleSeconds) {
    const originals = Array.isArray(segments) ? segments : [];
    let remainingVisible = Math.max(0, Number(visibleSeconds) || 0);
    const visibleSegments = [];
    const overflowSegments = [];

    originals.forEach((segment) => {
      const seconds = Math.max(0, Number(segment.seconds) || 0);
      if (seconds <= 0) return;

      const shownSeconds = Math.min(seconds, remainingVisible);
      if (shownSeconds > 0) {
        visibleSegments.push({
          ...segment,
          seconds: shownSeconds,
          originalSeconds: seconds,
          partiallyVisible: shownSeconds < seconds
        });
      }

      overflowSegments.push(...overflowEntriesForSegment(segment, shownSeconds));
      remainingVisible -= shownSeconds;
    });

    const visibleActiveSeconds = visibleSegments.reduce((sum, segment) => sum + segment.seconds, 0);
    const totalObservedActiveSeconds = originals.reduce(
      (sum, segment) => sum + Math.max(0, Number(segment.seconds) || 0),
      0
    );
    const hiddenActiveSeconds = Math.max(0, totalObservedActiveSeconds - visibleActiveSeconds);

    return {
      visibleSegments,
      overflowSegments,
      visibleActiveSeconds,
      hiddenActiveSeconds,
      totalObservedActiveSeconds
    };
  }

  return {
    RANGE_STEP_MINUTES,
    MIN_VISIBLE_MINUTES,
    MAX_AUTOMATIC_MINUTES,
    MIN_PX_PER_MINUTE,
    MAX_PX_PER_MINUTE,
    calculateSegmentLabelLayout,
    buildProductAreaSegments,
    calculateVisibleMinutes,
    calculateP85ActiveMinutes,
    countDistinctPageIdentities,
    splitSegmentsForVisibleRange
  };
});
