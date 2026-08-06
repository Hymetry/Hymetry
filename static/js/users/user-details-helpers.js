(function registerHymetryUserDetailsHelpers(root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
    return;
  }

  root.HymetryUserDetailsHelpers = factory();
})(typeof globalThis !== "undefined" ? globalThis : window, function createHymetryUserDetailsHelpers() {
  const numberFormatter = new Intl.NumberFormat("en-US");
  const periodOptions = [7, 30, 90, 180];
  const defaultPeriodDays = 30;

  const statusLabels = {
    power_user: "Power user",
    healthy: "Healthy",
    sporadic: "Sporadic",
    at_risk: "At risk",
    new: "New"
  };

  const statusBadgeVariants = {
    power_user: "users-badge--green",
    healthy: "users-badge--blue",
    sporadic: "users-badge--amber",
    at_risk: "users-badge--red",
    new: "users-badge--slate"
  };

  const priorityBadgeVariants = {
    high: "users-badge--red",
    medium: "users-badge--amber",
    low: "users-badge--blue"
  };

  const recommendedActionTypeLabels = {
    usage_drop: "Usage drop",
    underused_page: "Underused page",
    champion_signal: "Champion signal",
    unusual_usage: "Unusual usage",
    friction_signal: "Friction signal",
    activation_gap: "Activation gap"
  };

  const recommendedActionTypeBadgeVariants = {
    usage_drop: "users-badge--red",
    underused_page: "users-badge--amber",
    champion_signal: "users-badge--green",
    unusual_usage: "users-badge--blue",
    friction_signal: "users-badge--amber",
    activation_gap: "users-badge--slate"
  };

  const recommendedActionStatusLabels = {
    open: "Open",
    in_progress: "In progress",
    done: "Done",
    dismissed: "Dismissed"
  };

  const recommendedActionStatusBadgeVariants = {
    open: "users-badge--blue",
    in_progress: "users-badge--amber",
    done: "users-badge--green",
    dismissed: "users-badge--slate"
  };

  const recommendedActionPriorityOrder = {
    high: 0,
    medium: 1,
    low: 2
  };

  const recommendedActionTypeOrder = {
    usage_drop: 0,
    underused_page: 1,
    friction_signal: 2,
    unusual_usage: 3,
    champion_signal: 4,
    activation_gap: 5
  };

  function safeDivide(numerator, denominator) {
    const top = Number(numerator) || 0;
    const bottom = Number(denominator) || 0;

    return bottom === 0 ? 0 : top / bottom;
  }

  function formatNumber(value) {
    return numberFormatter.format(Math.round(Number(value) || 0));
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

  function formatPercent(value) {
    const numericValue = Number(value) || 0;
    const percent = Math.abs(numericValue) <= 1 ? numericValue * 100 : numericValue;
    const decimals = Math.abs(percent) < 10 && percent % 1 !== 0 ? 1 : 0;

    return `${percent.toFixed(decimals)}%`;
  }

  function formatDelta(value, type) {
    const numericValue = Number(value) || 0;
    const prefix = numericValue > 0 ? "+" : "";

    if (type === "pp") {
      const decimals = Math.abs(numericValue) < 10 && numericValue % 1 !== 0 ? 1 : 0;
      return `${prefix}${numericValue.toFixed(decimals)}pp`;
    }

    if (type === "absolute") {
      return `${prefix}${formatNumber(numericValue)}`;
    }

    const decimals = Math.abs(numericValue) < 10 && numericValue % 1 !== 0 ? 1 : 0;
    return `${prefix}${numericValue.toFixed(decimals)}%`;
  }

  function getStatusLabel(status) {
    return statusLabels[status] || "Unknown";
  }

  function getStatusBadgeVariant(status) {
    return statusBadgeVariants[status] || statusBadgeVariants.new;
  }

  function getPriorityBadgeVariant(priority) {
    return priorityBadgeVariants[priority] || priorityBadgeVariants.low;
  }

  function getRecommendedActionTypeLabel(type) {
    return recommendedActionTypeLabels[type] || recommendedActionTypeLabels.activation_gap;
  }

  function getRecommendedActionTypeBadgeVariant(type) {
    return recommendedActionTypeBadgeVariants[type] || recommendedActionTypeBadgeVariants.activation_gap;
  }

  function getRecommendedActionStatusLabel(status) {
    return recommendedActionStatusLabels[status] || recommendedActionStatusLabels.open;
  }

  function getRecommendedActionStatusBadgeVariant(status) {
    return recommendedActionStatusBadgeVariants[status] || recommendedActionStatusBadgeVariants.open;
  }

  function calculateConsistency(activeDays, periodDays) {
    return safeDivide(activeDays, periodDays);
  }

  function calculateIntensity(engagedSeconds, activeDays) {
    return safeDivide(engagedSeconds, activeDays);
  }

  function coercePeriodDays(value) {
    const numericValue = Number(String(value || defaultPeriodDays).replace(/[^0-9.]/g, ""));

    return periodOptions.includes(numericValue) ? numericValue : defaultPeriodDays;
  }

  function metricValue(row, metric) {
    if (!row) {
      return 0;
    }

    if (metric === "interaction") {
      return Number(row.interactionRate) || 0;
    }

    return Number(row[metric]) || 0;
  }

  function sortPeersByMetric(peers, metric) {
    return (Array.isArray(peers) ? peers : [])
      .slice()
      .sort((a, b) => metricValue(b, metric) - metricValue(a, metric) || String(a.name || "").localeCompare(String(b.name || "")));
  }

  function getPeersAroundCurrentUser(peers, currentUserId, metric, count) {
    const rows = sortPeersByMetric(peers, metric).map((row, index) => ({
      ...row,
      rank: index + 1
    }));
    const currentIndex = rows.findIndex((row) => row.userId === currentUserId);
    const sideCount = Math.max(1, Number(count) || 4);

    if (currentIndex === -1) {
      return rows.slice(0, sideCount * 2 + 1);
    }

    const start = Math.max(0, currentIndex - sideCount);
    const end = Math.min(rows.length, currentIndex + sideCount + 1);
    const windowRows = rows.slice(start, end);

    if (windowRows.some((row) => row.userId === currentUserId)) {
      return windowRows;
    }

    return [rows[currentIndex], ...windowRows].filter(Boolean);
  }

  function getTopPeers(peers, metric, count) {
    return sortPeersByMetric(peers, metric)
      .slice(0, Math.max(1, Number(count) || 10))
      .map((row, index) => ({
        ...row,
        rank: index + 1
      }));
  }

  function median(values) {
    const rows = (Array.isArray(values) ? values : [])
      .map((value) => Number(value))
      .filter(Number.isFinite)
      .sort((a, b) => a - b);
    const midpoint = Math.floor(rows.length / 2);

    if (!rows.length) {
      return 0;
    }

    return rows.length % 2 === 0 ? (rows[midpoint - 1] + rows[midpoint]) / 2 : rows[midpoint];
  }

  function sum(rows, selector) {
    return (Array.isArray(rows) ? rows : []).reduce((total, row, index) => total + (Number(selector(row, index)) || 0), 0);
  }

  function percentileRank(rows, currentUserId, metric) {
    const sorted = sortPeersByMetric(rows, metric);
    const index = sorted.findIndex((row) => row.userId === currentUserId);

    if (index === -1 || sorted.length <= 1) {
      return 50;
    }

    return Math.round(((index + 1) / sorted.length) * 100);
  }

  function metricCardById(data, id) {
    return (data?.metricCards || []).find((card) => card.id === id) || null;
  }

  function buildInsightSummary(data) {
    const insights = [];
    const selectedUserId = data?.selectedUser?.id;
    const peerRows = data?.peerComparison || [];
    const engagedPercentile = percentileRank(peerRows, selectedUserId, "engagedSeconds");
    const engagedCard = metricCardById(data, "engaged_time");
    const activeDaysCard = metricCardById(data, "active_days");
    const largestMixDifference = (data?.productAreaMix || [])
      .slice()
      .sort((a, b) => Math.abs(b.deltaPp) - Math.abs(a.deltaPp))[0];
    const peerLabel = data?.peerGroupLabel || "peers";
    const company = data?.selectedUser?.companyName || "the company";
    const topPeerArea = (data?.peerAreaMedianTop || "").trim();
    const frictionPage = (data?.pagesUsed || [])
      .filter((page) => page.visits >= 10 && page.interactionRate < 0.22)
      .sort((a, b) => b.visits - a.visits)[0];
    const missingPage = (data?.underusedPages || [])[0];

    if (engagedPercentile <= 15) {
      insights.push(`This user is in the top ${Math.max(1, engagedPercentile)}% by engaged time among ${peerLabel}.`);
    } else if (engagedPercentile >= 65) {
      insights.push(`This user is below the engaged-time median for ${peerLabel}.`);
    }

    // The Active days card's own delta is in percentage points, so the day
    // difference this sentence reports comes from its dedicated field.
    const activeDaysDelta = Number(activeDaysCard?.activeDaysDelta);

    if (engagedCard && engagedCard.deltaValue <= -25) {
      insights.push(`Usage dropped ${Math.abs(Math.round(engagedCard.deltaValue))}% versus the previous period.`);
    } else if (Number.isFinite(activeDaysDelta) && activeDaysDelta >= 4) {
      insights.push(`Active days increased by ${Math.round(activeDaysDelta)} days versus the previous period.`);
    }

    if (largestMixDifference && Math.abs(largestMixDifference.deltaPp) >= 12) {
      const direction = largestMixDifference.deltaPp > 0 ? "more" : "less";
      const peerContrast = topPeerArea && topPeerArea !== largestMixDifference.productAreaName
        ? `, while ${peerLabel} lean toward ${topPeerArea}`
        : "";
      insights.push(`Usage is unusually weighted toward ${largestMixDifference.productAreaName}: ${Math.abs(Math.round(largestMixDifference.deltaPp))}pp ${direction} than ${peerLabel}${peerContrast}.`);
    }

    if (frictionPage) {
      insights.push(`High visits but low interaction on ${frictionPage.pageName} may indicate friction.`);
    }

    if (missingPage) {
      insights.push(`${missingPage.pageName} is common among ${peerLabel}, but this user has ${missingPage.userUsageLabel.toLowerCase()}.`);
    }

    if (!insights.length) {
      insights.push(`Usage is close to the ${company} peer baseline across engagement, breadth, and interaction.`);
    }

    return insights.slice(0, 5);
  }

  function getUnderusedPages(pagesUsed, peerUsage) {
    const usageByPage = new Map((Array.isArray(pagesUsed) ? pagesUsed : []).map((page) => [page.pageRuleId, page]));

    return (Array.isArray(peerUsage) ? peerUsage : [])
      .map((page) => {
        const userPage = usageByPage.get(page.pageRuleId);
        const visits = Number(userPage?.visits) || 0;
        const peerMedianVisits = Number(page.peerMedianVisits) || 0;
        const muchLower = visits > 0 && peerMedianVisits > 0 && visits < peerMedianVisits * 0.35;

        if ((Number(page.peerUsagePct) || 0) < 40 || (visits > 0 && !muchLower)) {
          return null;
        }

        return {
          pageRuleId: page.pageRuleId,
          pageName: page.pageName,
          productAreaId: page.productAreaId,
          productAreaName: page.productAreaName,
          peerUsagePct: Number(page.peerUsagePct) || 0,
          userUsageLabel: visits ? `${visits} visits` : "0 visits",
          whyItMatters: page.whyItMatters || "Common among similar active users"
        };
      })
      .filter(Boolean)
      .sort((a, b) => b.peerUsagePct - a.peerUsagePct || a.pageName.localeCompare(b.pageName))
      .slice(0, 6);
  }

  function normalizeRecommendedActionType(type) {
    return recommendedActionTypeLabels[type] ? type : "activation_gap";
  }

  function normalizeRecommendedActionPriority(priority) {
    return Object.prototype.hasOwnProperty.call(recommendedActionPriorityOrder, priority) ? priority : "low";
  }

  function normalizeRecommendedActionStatus(status) {
    return recommendedActionStatusLabels[status] ? status : "open";
  }

  function normalizeRecommendedActionOwner(owner) {
    return ["CSM", "Product", "Sales", "Support"].includes(owner) ? owner : "CSM";
  }

  function underusedPagePriority(peerUsagePct) {
    const usage = Number(peerUsagePct) || 0;

    if (usage >= 75) {
      return "high";
    }

    if (usage >= 40) {
      return "medium";
    }

    return "low";
  }

  function relatedAreaLabel(pageName, productAreaName) {
    if (pageName && productAreaName) {
      return `${pageName} \u00b7 ${productAreaName}`;
    }

    return pageName || productAreaName || "Overall";
  }

  function recommendedActionEvidenceScore(action) {
    if (Number.isFinite(Number(action?.sortScore))) {
      return Number(action.sortScore);
    }

    const values = String(action?.evidence || "")
      .match(/[-+]?\d+(\.\d+)?/g)
      ?.map((value) => Math.abs(Number(value)) || 0) || [];

    return Math.max(0, ...values);
  }

  function normalizeRecommendedAction(action, index) {
    const type = normalizeRecommendedActionType(action?.type);

    return {
      id: action?.id || `action_${index + 1}`,
      priority: normalizeRecommendedActionPriority(action?.priority),
      type,
      action: String(action?.action || "Review usage pattern"),
      reason: String(action?.reason || "Usage pattern needs review"),
      evidence: String(action?.evidence || ""),
      relatedLabel: action?.relatedLabel || "",
      relatedPageName: action?.relatedPageName || "",
      relatedProductAreaName: action?.relatedProductAreaName || "",
      relatedProductAreaColor: action?.relatedProductAreaColor || "",
      owner: normalizeRecommendedActionOwner(action?.owner),
      status: normalizeRecommendedActionStatus(action?.status),
      sortScore: recommendedActionEvidenceScore(action)
    };
  }

  function underusedPageToRecommendedAction(page, index) {
    const peerUsagePct = Number(page?.peerUsagePct) || 0;
    const pageName = String(page?.pageName || "this page");
    const productAreaName = String(page?.productAreaName || "");
    const userUsageLabel = String(page?.userUsageLabel || "0 visits");

    return {
      id: `underused_${page?.pageRuleId || index + 1}`,
      priority: underusedPagePriority(peerUsagePct),
      type: "underused_page",
      action: `Offer enablement on ${pageName}`,
      reason: "Peers commonly use this page, this user does not",
      evidence: `${pageName}: ${formatPercent(peerUsagePct)} peer usage, ${userUsageLabel}`,
      relatedLabel: relatedAreaLabel(pageName, productAreaName),
      relatedPageName: pageName,
      relatedProductAreaName: productAreaName,
      relatedProductAreaColor: page?.productAreaColor || "",
      owner: "CSM",
      status: "open",
      sortScore: peerUsagePct
    };
  }

  function normalizedActionPageKey(action) {
    const directPage = String(action?.relatedPageName || "").trim().toLowerCase();

    if (directPage) {
      return directPage;
    }

    const match = String(action?.action || "").match(/^offer enablement on\s+(.+)$/i);

    return match ? match[1].trim().toLowerCase() : "";
  }

  function isDuplicateUnderusedAction(existing, incoming) {
    const existingPageKey = normalizedActionPageKey(existing);
    const incomingPageKey = normalizedActionPageKey(incoming);

    return Boolean(
      incomingPageKey &&
        existingPageKey === incomingPageKey &&
        (existing.type === "underused_page" || String(existing.action || "").toLowerCase() === String(incoming.action || "").toLowerCase())
    );
  }

  function strongestPriority(first, second) {
    const firstOrder = recommendedActionPriorityOrder[normalizeRecommendedActionPriority(first)];
    const secondOrder = recommendedActionPriorityOrder[normalizeRecommendedActionPriority(second)];

    return firstOrder <= secondOrder ? first : second;
  }

  function mergeEvidence(existingEvidence, incomingEvidence) {
    const existing = String(existingEvidence || "").trim();
    const incoming = String(incomingEvidence || "").trim();

    if (!existing) {
      return incoming;
    }

    if (!incoming) {
      return existing;
    }

    const existingLower = existing.toLowerCase();
    const incomingLower = incoming.toLowerCase();

    if (incomingLower.includes(existingLower)) {
      return incoming;
    }

    if (existingLower.includes(incomingLower)) {
      return existing;
    }

    return `${existing}; ${incoming}`;
  }

  function mergeRecommendedAction(existing, incoming) {
    existing.priority = strongestPriority(existing.priority, incoming.priority);
    existing.type = incoming.type === "underused_page" ? "underused_page" : existing.type || incoming.type;
    existing.reason = existing.reason || incoming.reason;
    existing.evidence = mergeEvidence(existing.evidence, incoming.evidence);
    existing.relatedLabel = existing.relatedLabel || incoming.relatedLabel;
    existing.relatedPageName = existing.relatedPageName || incoming.relatedPageName;
    existing.relatedProductAreaName = existing.relatedProductAreaName || incoming.relatedProductAreaName;
    existing.relatedProductAreaColor = existing.relatedProductAreaColor || incoming.relatedProductAreaColor;
    existing.owner = existing.owner || incoming.owner;
    existing.status = existing.status || incoming.status;
    existing.sortScore = Math.max(Number(existing.sortScore) || 0, Number(incoming.sortScore) || 0);
  }

  function sortRecommendedActions(actions) {
    return (Array.isArray(actions) ? actions : [])
      .slice()
      .sort((a, b) => {
        const priorityComparison = recommendedActionPriorityOrder[a.priority] - recommendedActionPriorityOrder[b.priority];
        const typeComparison = recommendedActionTypeOrder[a.type] - recommendedActionTypeOrder[b.type];
        const evidenceComparison = (Number(b.sortScore) || 0) - (Number(a.sortScore) || 0);

        return priorityComparison || typeComparison || evidenceComparison || String(a.action || "").localeCompare(String(b.action || ""));
      })
      .map(({ sortScore, ...action }) => action);
  }

  function buildRecommendedNextSteps({ recommendedActions = [], underusedPages = [] } = {}) {
    const actions = (Array.isArray(recommendedActions) ? recommendedActions : []).map(normalizeRecommendedAction);

    (Array.isArray(underusedPages) ? underusedPages : []).forEach((page, index) => {
      const incoming = underusedPageToRecommendedAction(page, index);
      const duplicate = actions.find((action) => isDuplicateUnderusedAction(action, incoming));

      if (duplicate) {
        mergeRecommendedAction(duplicate, incoming);
        return;
      }

      actions.push(incoming);
    });

    return sortRecommendedActions(actions);
  }

  function getRecommendedActions(data) {
    const actions = [];
    const addAction = (action) => {
      if (actions.some((existing) => existing.action === action.action)) {
        return;
      }

      actions.push({
        id: `action_${actions.length + 1}`,
        status: "open",
        ...action
      });
    };
    const productAreaForName = (areaName) => (data?.productAreas || []).find((area) => area.name === areaName || area.id === areaName) || null;
    const relatedAreaFields = (areaName, pageName = "") => {
      const area = productAreaForName(areaName);
      const resolvedAreaName = area?.name || areaName || "";

      return {
        relatedLabel: relatedAreaLabel(pageName, resolvedAreaName),
        relatedPageName: pageName,
        relatedProductAreaName: resolvedAreaName,
        relatedProductAreaColor: area?.color || ""
      };
    };
    const metrics = data?.userMetrics || {};
    const engagedCard = metricCardById(data, "engaged_time");
    const pagesCard = metricCardById(data, "pages_used");
    const currentPeerRow = (data?.peerComparison || []).find((row) => row.isCurrentUser);
    const peerRows = data?.peerComparison || [];
    const rankPct = percentileRank(peerRows, data?.selectedUser?.id, "engagedSeconds");
    const frictionPage = (data?.pagesUsed || [])
      .filter((page) => page.visits >= 10 && page.interactionRate < 0.22)
      .sort((a, b) => b.visits - a.visits)[0];
    const unusualArea = (data?.productAreaMix || [])
      .slice()
      .sort((a, b) => Math.abs(b.deltaPp) - Math.abs(a.deltaPp))[0];

    if (engagedCard && engagedCard.deltaValue <= -35) {
      addAction({
        priority: "high",
        type: "usage_drop",
        action: "Reach out about usage drop",
        reason: "Activity dropped sharply",
        evidence: `Engaged ${formatDelta(engagedCard.deltaValue, "percent")} vs previous period`,
        relatedLabel: "Overall usage",
        owner: "CSM",
        sortScore: Math.abs(Number(engagedCard.deltaValue) || 0)
      });
    }

    if (frictionPage) {
      addAction({
        priority: "medium",
        type: "friction_signal",
        action: `Investigate friction on ${frictionPage.pageName}`,
        reason: "High visits, low interaction",
        evidence: `${frictionPage.visits} visits, ${formatPercent(frictionPage.interactionRate)} interaction`,
        ...relatedAreaFields(frictionPage.productAreaName, frictionPage.pageName),
        owner: "Product",
        sortScore: frictionPage.visits * Math.max(0, 1 - (Number(frictionPage.interactionRate) || 0))
      });
    }

    if (rankPct <= 15 && metrics.consistency >= 0.55 && metrics.pagesUsed >= 8) {
      addAction({
        priority: "low",
        type: "champion_signal",
        action: "Mark as potential champion",
        reason: "High consistency and broad page usage",
        evidence: `Top ${Math.max(1, rankPct)}% by engaged time, ${metrics.pagesUsed} pages used`,
        relatedLabel: "Overall",
        owner: "CSM",
        sortScore: Math.max(1, 100 - rankPct)
      });
    }

    if (pagesCard && pagesCard.deltaValue <= -2) {
      addAction({
        priority: "medium",
        type: "activation_gap",
        action: "Review activation gap",
        reason: "Page breadth declined",
        evidence: `Pages used ${formatDelta(pagesCard.deltaValue, "absolute")} vs previous period`,
        relatedLabel: "Overall activation",
        owner: "CSM",
        sortScore: Math.abs(Number(pagesCard.deltaValue) || 0)
      });
    }

    if (unusualArea && Math.abs(unusualArea.deltaPp) >= 18) {
      const isHeavyUsage = unusualArea.deltaPp > 0;

      addAction({
        priority: "medium",
        type: "unusual_usage",
        action: isHeavyUsage ? `Validate ${unusualArea.productAreaName}-heavy usage pattern` : `Review low ${unusualArea.productAreaName} usage`,
        reason: "Usage mix differs from peers",
        evidence: `${formatDelta(unusualArea.deltaPp, "pp")} vs peer median share`,
        ...relatedAreaFields(unusualArea.productAreaName),
        owner: unusualArea.productAreaName === "Billing" ? "Sales" : "Product",
        sortScore: Math.abs(Number(unusualArea.deltaPp) || 0)
      });
    }

    if (currentPeerRow && currentPeerRow.topArea === "Administration" && metrics.interactionRate >= 0.65) {
      addAction({
        priority: "low",
        type: "champion_signal",
        action: "Explore admin expansion signal",
        reason: "Strong administrative usage",
        evidence: `${currentPeerRow.topArea} is top area, ${formatPercent(metrics.interactionRate)} interaction`,
        ...relatedAreaFields(currentPeerRow.topArea),
        owner: "Sales",
        sortScore: Number(metrics.interactionRate) * 100
      });
    }

    if (!actions.length && metrics.visits > 0) {
      addAction({
        priority: "low",
        type: "activation_gap",
        action: "Monitor next period",
        reason: "Usage is near peer baseline",
        evidence: `${formatDuration(metrics.engagedSeconds)} engaged, ${metrics.activeDays} active days`,
        relatedLabel: "Overall",
        owner: "CSM",
        sortScore: Number(metrics.engagedSeconds) || 0
      });
    }

    return actions.slice(0, 5);
  }

  return {
    PERIOD_OPTIONS: periodOptions,
    DEFAULT_PERIOD_DAYS: defaultPeriodDays,
    safeDivide,
    formatNumber,
    formatDuration,
    formatPercent,
    formatDelta,
    getStatusLabel,
    getStatusBadgeVariant,
    getPriorityBadgeVariant,
    getRecommendedActionTypeLabel,
    getRecommendedActionTypeBadgeVariant,
    getRecommendedActionStatusLabel,
    getRecommendedActionStatusBadgeVariant,
    calculateConsistency,
    calculateIntensity,
    coercePeriodDays,
    metricValue,
    getPeersAroundCurrentUser,
    getTopPeers,
    median,
    sum,
    percentileRank,
    buildInsightSummary,
    getUnderusedPages,
    getRecommendedActions,
    buildRecommendedNextSteps
  };
});
