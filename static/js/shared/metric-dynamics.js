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

  function clampInteger(value, minValue, maxValue) {
    return Math.max(minValue, Math.min(maxValue, Math.round(Number(value) || 0)));
  }

  function straightTrendWindowSize(seriesLength, selectedPeriodDays) {
    const length = Math.max(0, Number(seriesLength) || 0);
    const days = Number(selectedPeriodDays) || length;
    const maxWindowSize = Math.max(2, Math.floor(length / 2));
    let desiredWindowSize;

    if (days <= 7) {
      desiredWindowSize = 2;
    } else if (days <= 30) {
      desiredWindowSize = 7;
    } else if (days <= 90) {
      desiredWindowSize = clampInteger(length * 0.2, 14, 21);
    } else if (days <= 180) {
      desiredWindowSize = 30;
    } else {
      desiredWindowSize = clampInteger(length * 0.2, 2, 30);
    }

    return Math.min(desiredWindowSize, maxWindowSize);
  }

  function firstWindowValues(values, windowSize) {
    const result = [];

    for (const value of values) {
      if (Number.isFinite(value)) {
        result.push(value);
      }

      if (result.length >= windowSize) {
        break;
      }
    }

    return result;
  }

  function lastWindowValues(values, windowSize) {
    const result = [];

    for (let index = values.length - 1; index >= 0; index -= 1) {
      const value = values[index];

      if (Number.isFinite(value)) {
        result.unshift(value);
      }

      if (result.length >= windowSize) {
        break;
      }
    }

    return result;
  }

  function buildStraightTrendLine(series, selectedPeriodDays) {
    const values = coerceSeriesValues(series);
    const validCount = finiteValues(values).length;

    if (validCount < MIN_BASELINE_POINTS) {
      return [];
    }

    const windowSize = straightTrendWindowSize(values.length, selectedPeriodDays);
    const startValue = median(firstWindowValues(values, windowSize));
    const endValue = median(lastWindowValues(values, windowSize));

    if (!Number.isFinite(startValue) || !Number.isFinite(endValue)) {
      return [];
    }

    if (values.length === 1) {
      return [startValue];
    }

    return values.map((_, index) => startValue + ((endValue - startValue) * index) / (values.length - 1));
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
    const benchmarkActual = hasEnoughData(explicitBenchmarkSeries, minDataPoints)
      ? explicitBenchmarkSeries
      : peerTraces.length >= minPeerCount
      ? medianSeries(peerTraces.map((peer) => peer.data), currentValues.length)
      : [];
    const hasBenchmark = hasEnoughData(benchmarkActual, minDataPoints);
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
      benchmarkEligiblePeerCount: Number(options.benchmarkEligiblePeerCount) || peerTraces.length,
      benchmarkUnavailableReason,
      peerSeriesList: options.showPeers ? peerTraces.map((peer) => ({ id: peer.id, name: peer.name, data: peer.data })) : [],
      peerTraces: options.showPeers ? peerTraces.map((peer) => ({ id: peer.id, name: peer.name, data: peer.data })) : [],
      hiddenPeerTraceCount: options.showPeers ? 0 : peerTraces.length,
      showPeers: Boolean(options.showPeers),
      metricType: normalizeMetricType(metricType),
      isPercentage: isPercentageMetric(metricType)
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
    coerceSeriesValues,
    median,
    getBaseline,
    normalizeSeries,
    medianSeries,
    rebaseBenchmarkSeries,
    straightTrendWindowSize,
    buildStraightTrendLine,
    buildMetricDynamicsSeries,
    getMetricDynamicsAxisBounds,
    setMetricDynamicsLoadingState
  };
});
