(function registerHymetryMetricDynamics(root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
    return;
  }

  root.HymetryMetricDynamics = factory();
})(typeof globalThis !== "undefined" ? globalThis : window, function createHymetryMetricDynamics() {
  const MIN_BENCHMARK_PEERS = 5;
  const MIN_BASELINE_POINTS = 3;
  const BASELINE_POINT_COUNT = 5;
  const PERCENTAGE_METRICS = new Set(["adoption", "penetration", "interaction", "interaction_rate", "consistency"]);

  // How a metric dynamics panel is drawn follows from what its points mean, not
  // from which detail page it sits on.
  //
  // - cumulative_total: a running total. It can only climb, so a fitted trend
  //   restates the shape already on screen; the fill carries the "so far" sense.
  // - rate: a ratio recomputed over the elapsed period. It can move either way,
  //   which is what makes a fitted trend worth reading, and a fill under a ratio
  //   would imply an area that means nothing.
  // - discrete_cumulative: a distinct count over the elapsed period. It holds a
  //   level until something new is used, so it steps rather than slopes.
  // - daily_state: an end-of-day state that holds until the next date. It steps
  //   too, but it can fall, so the fitted trend still says something.
  const METRIC_DYNAMICS_SHAPES = {
    cumulative_total: { step: false, filled: true, selfTrend: false },
    rate: { step: false, filled: false, selfTrend: true },
    discrete_cumulative: { step: true, filled: true, selfTrend: false },
    daily_state: { step: true, filled: false, selfTrend: true }
  };
  const RATE_METRICS = new Set([
    "adoption",
    "penetration",
    "avg_visit",
    "interaction",
    "interaction_rate",
    "clicks_per_visit",
    "avg_per_user",
    "intensity"
  ]);
  const DISCRETE_CUMULATIVE_METRICS = new Set(["adoption_breadth", "pages_used", "areas_used"]);
  const DAILY_STATE_METRICS = new Set(["at_risk_users"]);

  function getMetricDynamicsShapeName(metricType) {
    const normalized = normalizeMetricType(metricType);

    if (DAILY_STATE_METRICS.has(normalized)) {
      return "daily_state";
    }

    if (DISCRETE_CUMULATIVE_METRICS.has(normalized)) {
      return "discrete_cumulative";
    }

    if (RATE_METRICS.has(normalized)) {
      return "rate";
    }

    // Everything else on these panels is a running total of counts or seconds.
    return "cumulative_total";
  }

  function getMetricDynamicsShape(metricType) {
    const name = getMetricDynamicsShapeName(metricType);

    return { name, ...METRIC_DYNAMICS_SHAPES[name] };
  }

  function normalizeMetricType(metricType) {
    return String(metricType || "")
      .replace(/([a-z0-9])([A-Z])/g, "$1_$2")
      .replace(/[\s-]+/g, "_")
      .toLowerCase();
  }

  function isPercentageMetric(metricType) {
    return PERCENTAGE_METRICS.has(normalizeMetricType(metricType));
  }

  function finiteNumber(value) {
    if (value === null || value === undefined) {
      return null;
    }

    const numericValue = Number(value);

    return Number.isFinite(numericValue) ? numericValue : null;
  }

  function coerceSeriesValues(series) {
    if (!Array.isArray(series)) {
      return [];
    }

    return series.map((point) => {
      if (point && typeof point === "object" && "value" in point) {
        return finiteNumber(point.value);
      }

      return finiteNumber(point);
    });
  }

  function finiteValues(values) {
    return values.filter((value) => Number.isFinite(value));
  }

  function median(values) {
    const sortedValues = finiteValues(values).sort((a, b) => a - b);

    if (!sortedValues.length) {
      return null;
    }

    const midpoint = Math.floor(sortedValues.length / 2);

    if (sortedValues.length % 2) {
      return sortedValues[midpoint];
    }

    return (sortedValues[midpoint - 1] + sortedValues[midpoint]) / 2;
  }

  function firstAvailableValues(values, count) {
    const result = [];

    for (const value of values) {
      if (Number.isFinite(value)) {
        result.push(value);
      }

      if (result.length >= count) {
        break;
      }
    }

    return result;
  }

  function getBaseline(series, options = {}) {
    const values = coerceSeriesValues(series);
    const pointCount = Math.max(1, Number(options.pointCount) || BASELINE_POINT_COUNT);
    const minPoints = Math.max(1, Number(options.minPoints) || MIN_BASELINE_POINTS);
    const baselineValues = firstAvailableValues(values, pointCount);

    if (baselineValues.length < minPoints) {
      return null;
    }

    return median(baselineValues);
  }

  function normalizeSeries(series, metricType, options = {}) {
    const values = coerceSeriesValues(series);
    const baseline = Number.isFinite(options.baseline)
      ? Number(options.baseline)
      : getBaseline(values, { minPoints: options.minBaselinePoints || MIN_BASELINE_POINTS });

    if (!Number.isFinite(baseline)) {
      return [];
    }

    if (isPercentageMetric(metricType)) {
      return values.map((value) => (Number.isFinite(value) ? value - baseline : null));
    }

    const safeBaseline = Math.max(0, baseline);

    return values.map((value) => {
      if (!Number.isFinite(value)) {
        return null;
      }

      return Math.log1p(Math.max(0, value)) - Math.log1p(safeBaseline);
    });
  }

  function medianSeries(seriesList, targetLength = null) {
    const explicitLength = targetLength !== null && targetLength !== undefined && Number.isFinite(Number(targetLength))
      ? Math.max(0, Number(targetLength))
      : null;
    const maxLength = explicitLength ?? seriesList.reduce((length, series) => Math.max(length, series.length), 0);

    return Array.from({ length: maxLength }, (_, index) => median(seriesList.map((series) => series[index])));
  }

  function clamp(value, minValue, maxValue) {
    return Math.max(minValue, Math.min(maxValue, value));
  }

  function rebaseBenchmarkSeries(benchmarkNormalizedSeries, currentSeries, metricType, options = {}) {
    const currentBaseline = getBaseline(currentSeries, { minPoints: options.minBaselinePoints || MIN_BASELINE_POINTS });

    if (!Number.isFinite(currentBaseline)) {
      return [];
    }

    if (isPercentageMetric(metricType)) {
      return benchmarkNormalizedSeries.map((value) => (
        Number.isFinite(value) ? clamp(currentBaseline + value, 0, 100) : null
      ));
    }

    const safeBaseline = Math.max(0, currentBaseline);

    return benchmarkNormalizedSeries.map((value) => (
      Number.isFinite(value) ? Math.max(0, Math.exp(Math.log1p(safeBaseline) + value) - 1) : null
    ));
  }

  function buildStraightTrendLine(series) {
    const values = coerceSeriesValues(series);
    const points = values.reduce((result, value, index) => {
      if (Number.isFinite(value)) {
        result.push({ x: index, y: value });
      }

      return result;
    }, []);

    if (points.length < MIN_BASELINE_POINTS) {
      return [];
    }

    const meanX = points.reduce((total, point) => total + point.x, 0) / points.length;
    const meanY = points.reduce((total, point) => total + point.y, 0) / points.length;
    const sums = points.reduce((result, point) => {
      const xOffset = point.x - meanX;

      result.crossProduct += xOffset * (point.y - meanY);
      result.squaredXOffset += xOffset * xOffset;
      return result;
    }, { crossProduct: 0, squaredXOffset: 0 });

    if (!Number.isFinite(sums.crossProduct) || sums.squaredXOffset <= 0) {
      return [];
    }

    const slope = sums.crossProduct / sums.squaredXOffset;
    const intercept = meanY - slope * meanX;

    return values.map((_, index) => intercept + slope * index);
  }

  function bindLineTrendHover(chart, lineSeriesCount, element = null) {
    const count = Math.max(0, Math.floor(Number(lineSeriesCount) || 0));

    if (
      !chart
      || !count
      || typeof chart.on !== "function"
      || typeof chart.dispatchAction !== "function"
    ) {
      return chart;
    }

    let activeSeriesIndex = null;
    const mainSeriesIndexFor = (params) => {
      const seriesIndex = Number(params?.seriesIndex);

      if (
        params?.seriesType !== "line"
        || !Number.isInteger(seriesIndex)
        || seriesIndex < 0
        || seriesIndex >= count * 2
      ) {
        return null;
      }

      return seriesIndex < count ? seriesIndex : seriesIndex - count;
    };
    const clearActiveSeries = () => {
      if (activeSeriesIndex === null) {
        return;
      }

      const seriesIndex = activeSeriesIndex;
      activeSeriesIndex = null;
      chart.dispatchAction({
        type: "downplay",
        batch: [
          { seriesIndex },
          { seriesIndex: count * 2 + seriesIndex }
        ]
      });
    };

    chart.on("mouseover", (params) => {
      const seriesIndex = mainSeriesIndexFor(params);

      if (seriesIndex === null || seriesIndex === activeSeriesIndex) {
        return;
      }

      clearActiveSeries();
      activeSeriesIndex = seriesIndex;
      chart.dispatchAction({
        type: "highlight",
        batch: [
          { seriesIndex },
          { seriesIndex: count * 2 + seriesIndex, notBlur: true }
        ]
      });
    });

    chart.on("mouseout", (params) => {
      if (mainSeriesIndexFor(params) === activeSeriesIndex) {
        clearActiveSeries();
      }
    });

    chart.getZr?.()?.on?.("globalout", clearActiveSeries);
    element?.addEventListener?.("pointerleave", clearActiveSeries);
    element?.addEventListener?.("mouseleave", clearActiveSeries);
    return chart;
  }

  function getPeerId(peer) {
    return peer?.id || peer?.pageId || peer?.page_id || peer?.pageRuleId || peer?.companyId || peer?.company_id || peer?.userId || peer?.user_id || "";
  }

  function getPeerName(peer, index) {
    return peer?.name || peer?.pageName || peer?.companyName || peer?.userName || `Peer ${index + 1}`;
  }

  function getPeerValues(peer) {
    if (Array.isArray(peer)) {
      return coerceSeriesValues(peer);
    }

    return coerceSeriesValues(peer?.dailySeries || peer?.series || peer?.values || []);
  }

  function metricActualValue(value, metricType) {
    if (!Number.isFinite(value)) {
      return null;
    }

    if (isPercentageMetric(metricType)) {
      return clamp(value, 0, 100);
    }

    return Math.max(0, value);
  }

  function actualMetricSeries(values, metricType, targetLength) {
    const length = targetLength !== null && targetLength !== undefined && Number.isFinite(Number(targetLength))
      ? Math.max(0, Number(targetLength))
      : values.length;

    return Array.from({ length }, (_, index) => metricActualValue(values[index], metricType));
  }

  function hasEnoughData(values, minPoints) {
    return finiteValues(values).length >= minPoints;
  }

  function buildPeerTrace(peer, index, metricType, currentEntityId, minDataPoints, targetLength) {
    const id = getPeerId(peer);

    if (currentEntityId && String(id) === String(currentEntityId)) {
      return null;
    }

    const values = actualMetricSeries(getPeerValues(peer), metricType, targetLength);

    if (!hasEnoughData(values, minDataPoints)) {
      return null;
    }

    return {
      id,
      name: getPeerName(peer, index),
      data: values
    };
  }

  function buildMetricDynamicsSeries(options = {}) {
    const currentValues = coerceSeriesValues(options.currentSeries);
    const metricType = options.metricType || "";
    const minPeerCount = Math.max(1, Number(options.minPeerCount) || MIN_BENCHMARK_PEERS);
    const minDataPoints = Math.max(1, Number(options.minDataPoints) || MIN_BASELINE_POINTS);
    const peerSeriesList = Array.isArray(options.peerSeriesList) ? options.peerSeriesList : [];
    const peerTraces = peerSeriesList
      .map((peer, index) => buildPeerTrace(peer, index, metricType, options.currentEntityId, minDataPoints, currentValues.length))
      .filter(Boolean);
    const explicitBenchmarkSeries = Array.isArray(options.benchmarkSeries)
      ? actualMetricSeries(coerceSeriesValues(options.benchmarkSeries), metricType, currentValues.length)
      : [];
    const benchmarkEligiblePeerCount = Number(options.benchmarkEligiblePeerCount) || peerTraces.length;
    const benchmarkActual = benchmarkEligiblePeerCount >= minPeerCount
      && hasEnoughData(explicitBenchmarkSeries, minDataPoints)
      ? explicitBenchmarkSeries
      : peerTraces.length >= minPeerCount
      ? medianSeries(peerTraces.map((peer) => peer.data), currentValues.length)
      : [];
    const hasBenchmark = hasEnoughData(benchmarkActual, minDataPoints);
    // The shape is advice for the metric dynamics panels, which decide whether
    // to draw the self-trend. It is not applied here: other consumers use this
    // fit as their main line rather than as an overlay.
    const shape = getMetricDynamicsShape(metricType);
    const currentStraightTrend = buildStraightTrendLine(currentValues, options.selectedPeriodDays);
    const benchmarkStraightTrend = hasBenchmark
      ? buildStraightTrendLine(benchmarkActual, options.selectedPeriodDays)
      : [];
    const benchmarkUnavailableReason = hasBenchmark
      ? ""
      : "Benchmark unavailable: not enough comparable data.";

    return {
      actualSeries: currentValues,
      current: currentValues,
      currentStraightTrendSeries: currentStraightTrend,
      currentTrend: currentStraightTrend,
      benchmarkStraightTrendSeries: benchmarkStraightTrend,
      benchmark: benchmarkStraightTrend,
      benchmarkEligiblePeerCount,
      benchmarkUnavailableReason,
      peerSeriesList: options.showPeers ? peerTraces.map((peer) => ({ id: peer.id, name: peer.name, data: peer.data })) : [],
      peerTraces: options.showPeers ? peerTraces.map((peer) => ({ id: peer.id, name: peer.name, data: peer.data })) : [],
      hiddenPeerTraceCount: options.showPeers ? 0 : peerTraces.length,
      showPeers: Boolean(options.showPeers),
      metricType: normalizeMetricType(metricType),
      isPercentage: isPercentageMetric(metricType),
      shape
    };
  }

  function setMetricDynamicsLoadingState(elements, isLoading) {
    const loading = Boolean(isLoading);
    const grid = elements?.grid || null;
    const shell = elements?.shell || grid?.parentElement || null;
    const overlay = elements?.overlay || null;
    const toggle = elements?.toggle || null;

    if (shell?.dataset) {
      shell.dataset.loading = String(loading);
    }

    if (grid?.dataset) {
      grid.dataset.loading = String(loading);
    }

    if (overlay) {
      overlay.hidden = !loading;

      if (overlay.dataset) {
        overlay.dataset.visible = String(loading);
      }
    }

    if (toggle) {
      toggle.disabled = loading;
    }

    return loading;
  }

  function getMetricDynamicsAxisBounds(seriesList, options = {}) {
    const paddingRatio = Number.isFinite(Number(options.paddingRatio))
      ? Math.max(0, Number(options.paddingRatio))
      : 0.08;
    const values = [];

    (Array.isArray(seriesList) ? seriesList : []).forEach((series) => {
      const source = Array.isArray(series)
        ? series
        : series?.data || series?.values || series?.dailySeries || [];

      coerceSeriesValues(source).forEach((value) => {
        if (Number.isFinite(value)) {
          values.push(value);
        }
      });
    });

    if (!values.length) {
      return {
        min: "dataMin",
        max: "dataMax"
      };
    }

    const minValue = Math.min(...values);
    const maxValue = Math.max(...values);
    const range = maxValue - minValue;
    const paddingBase = range > 0 ? range : Math.max(Math.abs(minValue), Math.abs(maxValue), 1);
    const padding = paddingBase * paddingRatio;

    return {
      min: minValue - padding,
      max: maxValue + padding
    };
  }

  return {
    MIN_BENCHMARK_PEERS,
    MIN_BASELINE_POINTS,
    normalizeMetricType,
    isPercentageMetric,
    getMetricDynamicsShape,
    coerceSeriesValues,
    median,
    getBaseline,
    normalizeSeries,
    medianSeries,
    rebaseBenchmarkSeries,
    buildStraightTrendLine,
    bindLineTrendHover,
    buildMetricDynamicsSeries,
    getMetricDynamicsAxisBounds,
    setMetricDynamicsLoadingState
  };
});
