(function mountDjangoCompaniesData(globalScope) {
  const dataElement = document.getElementById("companies-overview-data");
  const body = document.body || {};
  let payload = {};

  try {
    payload = JSON.parse(dataElement?.textContent || "{}");
  } catch {
    payload = {};
  }

  const PERIOD_OPTIONS = [7, 30, 90, 180];
  const periodDays = Number(payload.period?.days) || 30;
  const DEFAULT_PERIOD = `${periodDays}d`;
  const rangeByPeriod = {
    "7d": "last_7_days",
    "30d": "last_30_days",
    "90d": "last_90_days",
    "180d": "last_180_days"
  };
  const GENERIC_EXPANSION_REASON = "Strong usage footprint";
  const GENERIC_EXPANSION_ACTION = "Validate expansion fit";
  const LEGACY_EXPANSION_ACTIONS = new Set([GENERIC_EXPANSION_ACTION, "Map executive expansion path"]);
  const LEGACY_AT_RISK_ACTIONS = new Set(["Review adoption pattern", "Invite more users", "Schedule reactivation touchpoint"]);

  function coercePeriodKey(value) {
    const normalized = String(value || DEFAULT_PERIOD).trim().toLowerCase();
    const digits = normalized.replace(/[^0-9]/g, "");
    const period = `${digits || periodDays}d`;

    return PERIOD_OPTIONS.includes(Number(digits)) ? period : DEFAULT_PERIOD;
  }

  function navigateToPeriod(period) {
    const range = rangeByPeriod[period];

    if (!range || period === DEFAULT_PERIOD) {
      return;
    }

    const params = new URLSearchParams(globalScope.location.search);
    params.delete("period");
    params.set("range", range);
    globalScope.location.assign(`${globalScope.location.pathname}?${params.toString()}`);
  }

  function optionsUrl(baseUrl, query, periodValue, limit = 20) {
    const nextUrl = new URL(baseUrl, globalScope.location.origin);

    nextUrl.searchParams.set("period", coercePeriodKey(periodValue || DEFAULT_PERIOD));
    nextUrl.searchParams.set("limit", String(limit));

    if (String(query || "").trim()) {
      nextUrl.searchParams.set("q", String(query || "").trim());
    } else {
      nextUrl.searchParams.delete("q");
    }

    return `${nextUrl.pathname}${nextUrl.search}`;
  }

  function tableRequestUrl(baseUrl, options = {}) {
    const nextUrl = new URL(baseUrl, globalScope.location.origin);

    nextUrl.searchParams.set("period", coercePeriodKey(options.period || options.periodValue || DEFAULT_PERIOD));

    Object.entries(options).forEach(([key, value]) => {
      if (key === "period" || key === "periodValue" || value === undefined || value === null || value === "") {
        return;
      }
      nextUrl.searchParams.set(key, String(value));
    });

    return `${nextUrl.pathname}${nextUrl.search}`;
  }

  function fetchTable(baseUrl, options = {}) {
    if (!baseUrl || !globalScope.fetch) {
      return Promise.resolve(null);
    }

    return globalScope.fetch(tableRequestUrl(baseUrl, options), {
      credentials: "same-origin",
      headers: { Accept: "application/json" }
    })
      .then((response) => (response.ok ? response.json() : null))
      .catch(() => null);
  }

  function formatRelativeDate(value) {
    if (!value || !payload.period?.end_date) {
      return "-";
    }

    const endDate = new Date(`${payload.period.end_date}T00:00:00Z`);
    const date = new Date(`${value}T00:00:00Z`);
    const days = Math.max(0, Math.round((endDate - date) / 86400000));

    if (days <= 0) {
      return "Today";
    }

    return `${days}d ago`;
  }

  function daysSince(value) {
    if (!value || !payload.period?.end_date) {
      return 0;
    }

    const endDate = new Date(`${payload.period.end_date}T00:00:00Z`);
    const date = new Date(`${value}T00:00:00Z`);
    return Math.max(0, Math.round((endDate - date) / 86400000));
  }

  function fallbackProductAreaShortLabel(areaName) {
    const labelText = String(areaName || "").trim();
    const words = labelText.split(/\s+/).filter(Boolean);
    if (words.length > 1) {
      return words.map((word) => word[0]).join("").slice(0, 6).toUpperCase();
    }

    const label = words[0] || "";
    return label.length > 7 ? `${label.slice(0, 6)}.` : label;
  }

  function normalizeProductAreaShortLabel(areaName, shortName = "") {
    const normalizedName = String(areaName || "").trim();
    const normalizedShortName = String(shortName || "").trim();

    if (!normalizedShortName || normalizedShortName === normalizedName || normalizedShortName.length > 8) {
      return fallbackProductAreaShortLabel(normalizedShortName || normalizedName);
    }

    return normalizedShortName;
  }

  function productAreaOptions() {
    const options = [];
    const add = (name, shortName = "", color = "") => {
      const normalizedName = String(name || "").trim();

      if (!normalizedName || options.some((option) => option.name === normalizedName)) {
        return;
      }

      options.push({
        name: normalizedName,
        shortName: normalizeProductAreaShortLabel(normalizedName, shortName),
        color: String(color || "").trim()
      });
    };

    (payload.productAreas || []).forEach((area) => {
      if (area && typeof area === "object") {
        add(area.name, area.shortName || area.short_name, area.color);
        return;
      }

      add(area);
    });

    const fromCompanies = (payload.companies || []).flatMap((company) => company.productAreas || []);
    fromCompanies.forEach((areaName) => add(areaName));

    return options;
  }

  function productAreaNames() {
    return productAreaOptions().map((area) => area.name);
  }

  function formatTrendDateLabel(date) {
    if (!(date instanceof Date) || Number.isNaN(date.getTime())) {
      return "";
    }

    return new Intl.DateTimeFormat("en-US", {
      month: "short",
      day: "numeric",
      timeZone: "UTC"
    }).format(date);
  }

  function trendDateLabels(length) {
    const count = Math.max(0, Number(length) || 0);
    const endDate = new Date(`${payload.period?.end_date || ""}T00:00:00Z`);

    if (!count || Number.isNaN(endDate.getTime())) {
      return [];
    }

    const firstDate = new Date(endDate);
    firstDate.setUTCDate(firstDate.getUTCDate() - count + 1);

    return Array.from({ length: count }, (_, index) => {
      const date = new Date(firstDate);
      date.setUTCDate(firstDate.getUTCDate() + index);
      return formatTrendDateLabel(date);
    });
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function syncProductAreaMatrixHeadings() {
    const areas = productAreaOptions();
    globalScope.document.documentElement.style.setProperty("--companies-product-area-count", String(Math.max(areas.length, 1)));

    globalScope.document.querySelectorAll(".companies-matrix-heading").forEach((heading, headingIndex) => {
      heading.innerHTML = areas.map((area, areaIndex) => {
        const tooltipId = `companies-dynamic-area-tooltip-${headingIndex}-${areaIndex}`;
        return `
          <span class="metric-header-tooltip" tabindex="0" aria-describedby="${tooltipId}">
            ${escapeHtml(area.shortName)}
            <span id="${tooltipId}" class="metric-header-tooltip__content" role="tooltip">${escapeHtml(area.name)}</span>
          </span>
        `;
      }).join("");
    });
  }

  function mapAreaDistribution(row) {
    return (row.productAreaDistribution || []).map((area) => ({
      productArea: area.product_area_name || area.productArea || area.name || "Unassigned",
      percent: Number(area.percent) || 0,
      engagedSeconds: Number(area.engaged_seconds || area.engagedSeconds || 0),
      visits: Number(area.visits) || 0
    }));
  }

  function areaAdoption(row) {
    const distributions = row.productAreaDistribution || [];
    const byName = new Map(distributions.map((area) => [area.product_area_name || area.productArea, area]));
    return productAreaNames().map((areaName) => {
      const area = byName.get(areaName);
      const engagedSeconds = Number(area?.engaged_seconds || area?.engagedSeconds || 0);
      return {
        productArea: areaName,
        used: engagedSeconds > 0 || (row.productAreas || []).includes(areaName),
        engagedSeconds,
        visits: Number(area?.visits) || 0,
        activeUsers: engagedSeconds ? Math.max(1, Math.round((Number(row.activeUsers) || 0) * 0.75)) : 0,
        pagesUsed: engagedSeconds ? Math.max(1, Math.round((Number(row.pagesUsed) || 0) / Math.max(Number(row.productAreasUsed) || 1, 1))) : 0
      };
    });
  }

  function normalizeCompanyStatus(row) {
    const status = String(row.status || "").trim();

    if (row.isNew || status === "new") {
      return "new";
    }
    if (row.isReactivated || status === "reactivated") {
      return "reactivated";
    }

    return status;
  }

  function mapCompany(row) {
    const topArea = row.productAreas?.[0] || row.productAreaDistribution?.[0]?.product_area_name || "";
    const status = normalizeCompanyStatus(row);
    const companyId = row.companyId || row.id || "";
    const companyName = row.companyName || row.name || companyId;
    return {
      id: companyId,
      companyId,
      name: companyName,
      companyName,
      domain: row.domain || "",
      status,
      originalStatus: row.status || status,
      isNew: Boolean(row.isNew),
      isReactivated: Boolean(row.isReactivated),
      activeUsers: Number(row.activeUsers) || 0,
      averageActiveUsers: Number(row.averageActiveUsers ?? row.avgActiveUsers ?? row.activeUsers) || 0,
      activeUsersDeltaPct: Number(row.activeUsersDeltaPct) || 0,
      productAreasUsed: Number(row.productAreasUsed) || 0,
      productAreasDelta: Number(row.productAreasDelta) || 0,
      pagesUsed: Number(row.pagesUsed) || 0,
      visits: Number(row.visits) || 0,
      visitsDeltaPct: Number(row.visitsDeltaPct) || 0,
      engagedSeconds: Number(row.engagedSeconds) || 0,
      engagedDeltaPct: Number(row.engagedDeltaPct) || 0,
      avgEngagedSecondsPerUser: Number(row.avgEngagedSecondsPerUser) || 0,
      interactionPct: Number(row.interactionPct) || 0,
      interactionDeltaPp: Number(row.interactionDeltaPp) || 0,
      lastSeen: row.lastSeen || formatRelativeDate(row.lastSeenDate),
      lastSeenDays: Number(row.lastSeenDays) || daysSince(row.lastSeenDate),
      firstSeenDate: row.firstSeenDate,
      topProductArea: topArea,
      productAreas: row.productAreas || [],
      productAreaDistribution: mapAreaDistribution(row),
      userHealthMix: row.userHealthMix || row.user_health_mix || {},
      productAreaAdoption: areaAdoption(row)
    };
  }

  function formatExpansionDuration(totalSeconds) {
    const seconds = Math.max(0, Math.round(Number(totalSeconds) || 0));
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.round((seconds % 3600) / 60);

    if (hours > 0) {
      return minutes > 0 ? `${hours}h ${String(minutes).padStart(2, "0")}m` : `${hours}h`;
    }

    return `${Math.max(minutes, 1)}m`;
  }

  function firstMissingProductArea(row) {
    const adopted = new Set(row.productAreas || []);
    return productAreaNames().slice(0, 6).find((areaName) => areaName && !adopted.has(areaName)) || "";
  }

  function expansionRecommendation(row) {
    const activeUsers = Number(row.activeUsers) || 0;
    const avgEngaged = Number(row.avgEngagedSecondsPerUser) || 0;
    const interaction = Number(row.interactionPct) || 0;
    const productAreas = Number(row.productAreasUsed) || 0;
    const distribution = row.productAreaDistribution || [];
    const topArea = distribution[0]?.productArea || distribution[0]?.product_area_name || distribution[0]?.name || "";
    const topShare = Number(distribution[0]?.percent) || 0;
    const missingArea = productAreas >= 2 ? firstMissingProductArea(row) : "";

    if (topShare >= 70 && topArea) {
      return {
        reason: `${topArea} dominates usage`,
        suggestedAction: `Expand beyond ${topArea}`
      };
    }
    if (missingArea) {
      return {
        reason: `No ${missingArea} adoption`,
        suggestedAction: `Introduce ${missingArea} workflow`
      };
    }
    if (activeUsers >= 50 && avgEngaged >= 3600) {
      if (activeUsers >= 80) {
        return {
          reason: `${activeUsers} enterprise users engaged`,
          suggestedAction: "Map executive expansion path"
        };
      }
      if (avgEngaged >= 18000) {
        return {
          reason: `${formatExpansionDuration(avgEngaged)}/user depth`,
          suggestedAction: "Design premium workflow rollout"
        };
      }
      if (activeUsers >= 60 && productAreas >= 4) {
        return {
          reason: `${productAreas} areas broadly adopted`,
          suggestedAction: "Package cross-area expansion"
        };
      }
      if (avgEngaged >= 14400) {
        return {
          reason: `${formatExpansionDuration(avgEngaged)}/user engagement`,
          suggestedAction: "Offer advanced workflow pilot"
        };
      }
      if (Math.round(interaction) >= 60) {
        return {
          reason: `${Math.round(interaction)}% interaction rate`,
          suggestedAction: "Target power-user workflows"
        };
      }
      return {
        reason: `${activeUsers} users deeply engaged`,
        suggestedAction: "Map executive expansion path"
      };
    }
    if (activeUsers >= 50) {
      return {
        reason: `${activeUsers} active users`,
        suggestedAction: "Identify team champions"
      };
    }
    if (avgEngaged >= 3600) {
      return {
        reason: `${formatExpansionDuration(avgEngaged)}/user engagement`,
        suggestedAction: "Offer advanced workflow pilot"
      };
    }
    if (Math.round(interaction) >= 60) {
      return {
        reason: `${Math.round(interaction)}% interaction rate`,
        suggestedAction: "Target power-user workflows"
      };
    }
    if (productAreas >= 4) {
      return {
        reason: `${productAreas} areas adopted`,
        suggestedAction: "Package cross-area expansion"
      };
    }

    return {
      reason: GENERIC_EXPANSION_REASON,
      suggestedAction: GENERIC_EXPANSION_ACTION
    };
  }

  function expansionText(row) {
    const reason = String(row.reason || "").trim();
    const suggestedAction = String(row.suggestedAction || "").trim();
    const shouldRefreshLegacyAction = LEGACY_EXPANSION_ACTIONS.has(suggestedAction);

    if (reason && suggestedAction && reason !== GENERIC_EXPANSION_REASON && !shouldRefreshLegacyAction) {
      return { reason, suggestedAction };
    }

    const recommendation = expansionRecommendation(row);
    return {
      reason: reason && reason !== GENERIC_EXPANSION_REASON && !shouldRefreshLegacyAction ? reason : recommendation.reason,
      suggestedAction: suggestedAction && !shouldRefreshLegacyAction ? suggestedAction : recommendation.suggestedAction
    };
  }

  function riskReasonText(row) {
    const reasons = Array.isArray(row.riskReasons) ? row.riskReasons : [];
    return [row.riskReason, ...reasons].filter(Boolean).join(" ");
  }

  function atRiskSuggestedAction(row) {
    const existingAction = String(row.suggestedAction || "").trim();

    if (existingAction && !LEGACY_AT_RISK_ACTIONS.has(existingAction)) {
      return existingAction;
    }

    const text = riskReasonText(row);
    const activeUsers = Number(row.activeUsers) || 0;
    const activeUsersDelta = Number(row.activeUsersDeltaPct) || 0;
    const engagedSeconds = Number(row.engagedSeconds) || 0;
    const engagedDelta = Number(row.engagedDeltaPct) || 0;
    const productAreas = Number(row.productAreasUsed) || 0;

    if (text.includes("Only 1 active user")) {
      return "Add backup champions";
    }
    if (text.includes("No activity")) {
      if (activeUsers >= 50) {
        return "Reconnect recent power users";
      }
      if (productAreas >= 3 && engagedSeconds >= 28800) {
        return "Restart cross-area usage";
      }
      if (activeUsers >= 20) {
        return "Re-engage active cohort";
      }
      if (activeUsers <= 6 && engagedSeconds >= 3600) {
        return "Check account owner status";
      }
      if (engagedSeconds >= 28800) {
        return "Restart usage cadence";
      }
      return "Schedule reactivation touchpoint";
    }
    if ((text.includes("Users dropped") || activeUsersDelta <= -50) && (text.includes("Engaged drop") || engagedDelta <= -50)) {
      return "Run user reactivation";
    }
    if (text.includes("Users dropped") || activeUsersDelta <= -50) {
      return "Rebuild active user base";
    }
    if (text.includes("Product areas")) {
      return engagedDelta >= 0 || engagedSeconds >= 7200 ? "Expand adjacent workflows" : "Restore lost workflows";
    }
    if (text.includes("Engaged drop") || engagedDelta <= -50) {
      return activeUsers >= 2 ? "Review workflow value" : "Re-engage quiet account";
    }

    return existingAction || "Review account health";
  }

  function normalizedHealthDistribution(rows, companies) {
    const labels = {
      new: "New",
      activated: "Activated",
      reactivated: "Reactivated",
      healthy: "Healthy",
      power: "Power",
      at_risk: "Risk",
      dormant: "Dormant"
    };
    const order = ["new", "activated", "reactivated", "healthy", "power", "at_risk", "dormant"];
    const counts = new Map((rows || []).map((row) => [row.status, Number(row.count) || 0]));

    if (!(rows || []).length) {
      companies.forEach((company) => {
        counts.set(company.status, (counts.get(company.status) || 0) + 1);
      });
    } else {
      companies.forEach((company) => {
        if (!company.originalStatus || company.originalStatus === company.status) {
          return;
        }

        counts.set(company.originalStatus, Math.max(0, (counts.get(company.originalStatus) || 0) - 1));
        counts.set(company.status, (counts.get(company.status) || 0) + 1);
      });
    }

    const total = order.reduce((sum, status) => sum + (counts.get(status) || 0), 0) || 1;
    return order
      .map((status) => ({
        status,
        label: labels[status] || status,
        count: counts.get(status) || 0,
        pct: Math.round(((counts.get(status) || 0) / total) * 1000) / 10
      }))
      .filter((row) => row.count > 0);
  }

  function activationStatus(row) {
    if (row.activeUsers >= 2 && row.productAreasUsed >= 3 && row.engagedSeconds >= 1800) {
      return "activated";
    }
    if (row.activeUsers >= 2 || row.productAreasUsed >= 2) {
      return "partially_activated";
    }
    return "not_activated";
  }

  function buildNewReactivatedRows(companies) {
    return companies
      .filter((row) => row.isNew || row.isReactivated || row.status === "new" || row.status === "reactivated")
      .slice(0, 12)
      .map((row) => ({
        companyId: row.id,
        companyName: row.name,
        domain: row.domain,
        type: row.isReactivated || row.status === "reactivated" ? "reactivated" : "new",
        startDate: row.firstSeenDate || payload.period?.start_date,
        daysSinceStart: Math.max(1, daysSince(row.firstSeenDate || payload.period?.start_date)),
        activeUsers: row.activeUsers,
        productAreasUsed: row.productAreasUsed,
        pagesUsed: row.pagesUsed,
        engagedSeconds: row.engagedSeconds,
        firstProductArea: row.topProductArea || productAreaNames()[0] || "",
        topProductArea: row.topProductArea,
        topPage: row.topProductArea || "Core product",
        avgEngagedSecondsPerUser: row.avgEngagedSecondsPerUser,
        activationStatus: activationStatus(row),
        productAreaAdoption: row.productAreaAdoption,
        suggestedNextStep: row.productAreasUsed <= 1 ? "Explore adjacent workflows" : "Review adoption pattern"
      }));
  }

  function buildAdoptionRamp(newRows) {
    if (!newRows.length) {
      return [];
    }

    const areas = productAreaNames().slice(0, 5);
    const offsets = [0, 1, 3, 7, 14, 30, 60, 90].filter((offset) => offset <= periodDays);
    const cohortSize = newRows.length;

    return offsets.flatMap((dayOffset, dayIndex) => {
      const progress = Math.min(1, (dayIndex + 1) / Math.max(offsets.length, 1));
      return areas.map((area) => {
        const adopters = newRows.filter((row) => row.productAreaAdoption?.some((cell) => cell.productArea === area && cell.used)).length;
        const targetPct = Math.round((adopters / Math.max(cohortSize, 1)) * 100);
        const adoptionPct = Math.round(targetPct * progress);
        return {
          dayOffset,
          productArea: area,
          adoptionPct,
          companiesAdopted: Math.round((adoptionPct / 100) * cohortSize),
          cohortSize
        };
      });
    });
  }

  function mapKpis() {
    const byLabel = new Map((payload.kpis || []).map((kpi) => [kpi.label, kpi]));
    const active = byLabel.get("Active companies") || {};
    const newReactivated = byLabel.get("New / reactivated") || {};
    const median = byLabel.get("Median adoption breadth") || {};
    const atRisk = byLabel.get("At-risk companies") || {};
    const activeTrend = active.trend || [];
    const newReactivatedTrend = newReactivated.trend || [];
    const medianTrend = median.trend || [];
    const atRiskTrend = atRisk.trend || [];

    return {
      activeCompanies: {
        label: "Active companies",
        value: String(active.value ?? 0),
        secondary: active.delta?.label || "",
        delta: active.delta?.label || "",
        deltaType: active.delta?.direction || "neutral",
        sparkline: activeTrend,
        sparklineLabels: trendDateLabels(activeTrend.length)
      },
      newReactivatedCompanies: {
        label: "New / reactivated",
        value: String(newReactivated.value ?? 0),
        secondary: newReactivated.secondary || newReactivated.delta?.label || "",
        delta: newReactivated.delta?.label || "",
        deltaType: newReactivated.delta?.direction || "neutral",
        sparkline: newReactivatedTrend,
        sparklineLabels: trendDateLabels(newReactivatedTrend.length)
      },
      medianAdoptionBreadth: {
        label: "Median adoption breadth",
        value: `${median.value ?? 0} areas`,
        secondary: median.delta?.label || "",
        delta: median.delta?.label || "",
        deltaType: median.delta?.direction || "neutral",
        sparkline: medianTrend,
        sparklineLabels: trendDateLabels(medianTrend.length)
      },
      atRiskCompanies: {
        label: "At-risk companies",
        value: String(atRisk.value ?? 0),
        secondary: atRisk.delta?.label || "",
        delta: atRisk.delta?.label || "",
        deltaType: atRisk.delta?.direction || "neutral",
        sparkline: atRiskTrend,
        sparklineLabels: trendDateLabels(atRiskTrend.length)
      }
    };
  }

  function buildData(periodValue) {
    const requestedPeriod = coercePeriodKey(periodValue);
    navigateToPeriod(requestedPeriod);

    const companies = (payload.companies || []).map(mapCompany);
    const scatterPayload = payload.scatter || {};
    const scatterFallback = (scatterPayload.points || []).map(mapCompany);
    const scatterSource = scatterFallback.length ? scatterFallback : companies;
    const newReactivatedSource = (payload.newReactivatedCompanies?.length ? payload.newReactivatedCompanies : payload.companies || []).map(mapCompany);
    const newRows = buildNewReactivatedRows(newReactivatedSource);
    const atRiskRows = (payload.atRiskCompanies || [])
      .filter((row) => !row.isNew && !row.isReactivated && row.status !== "new" && row.status !== "reactivated")
      .map((row) => {
        const company = mapCompany(row);
        const riskRow = {
          ...row,
          ...company,
          riskReason: row.riskReason || row.riskReasons?.[0] || "At risk"
        };

        return {
          ...company,
          companyId: row.companyId,
          companyName: row.companyName,
          riskReason: riskRow.riskReason,
          suggestedAction: atRiskSuggestedAction(riskRow),
          productAreaAdoption: areaAdoption(row)
        };
      });
    const expansionRows = (payload.expansionOpportunities || []).map((row) => {
      const company = mapCompany(row);
      const recommendation = expansionText({ ...row, ...company });

      return {
        ...company,
        companyId: row.companyId,
        companyName: row.companyName,
        expansionPriority: row.expansionPriority || "medium",
        reason: recommendation.reason,
        suggestedAction: recommendation.suggestedAction,
        productAreaAdoption: areaAdoption(row)
      };
    });

    return {
      period: DEFAULT_PERIOD,
      productAreas: productAreaNames(),
      productAreaOptions: productAreaOptions(),
      pageFeatures: [],
      kpis: mapKpis(),
      healthDistribution: normalizedHealthDistribution(payload.healthDistribution || [], companies),
      companies,
      tableData: payload.tableData || {},
      scatter: scatterSource,
      scatterMeta: {
        visibleLimit: Number(scatterPayload.visibleLimit) || 500,
        totalActiveCompanies: Number(scatterPayload.totalActiveCompanies) || scatterSource.length,
        shownCompanies: Number(scatterPayload.shownCompanies) || scatterFallback.length || scatterSource.length,
        isLimited: Boolean(scatterPayload.isLimited),
        futureDensityMode: scatterPayload.futureDensityMode || null
      },
      newReactivatedCompanies: newRows,
      productAreaAdoption: payload.productAreaAdoption || [],
      newCompanyAdoptionRamp: payload.newCompanyAdoptionRamp?.length ? payload.newCompanyAdoptionRamp : buildAdoptionRamp(newRows),
      heatmap: [],
      atRiskCompanies: atRiskRows,
      expansionOpportunities: expansionRows
    };
  }

  function searchCompanies(query = "", options = {}) {
    const baseUrl = body.dataset?.companyOptionsUrl || "";

    if (!baseUrl || !globalScope.fetch) {
      return Promise.resolve([]);
    }

    return globalScope.fetch(optionsUrl(baseUrl, query, options.period || options.periodValue, options.limit || 20), {
      credentials: "same-origin",
      headers: {
        Accept: "application/json"
      }
    })
      .then((response) => {
        if (!response.ok) {
          return null;
        }

        return response.json();
      })
      .then((data) => (Array.isArray(data?.companies) ? data.companies : Array.isArray(data?.results) ? data.results : []))
      .then((rows) => rows.map(mapCompany).filter((company) => company.id))
      .catch(() => []);
  }

  function loadCompaniesTable(options = {}) {
    return fetchTable(body.dataset?.companiesTableUrl || "", options)
      .then((data) => {
        if (!data || !Array.isArray(data.rows)) {
          return null;
        }

        return {
          ...data,
          rows: data.rows.map(mapCompany).filter((company) => company.id)
        };
      });
  }

  globalScope.HymetryCompaniesDemoData = {
    PERIOD_OPTIONS,
    DEFAULT_PERIOD,
    productAreas: productAreaNames(),
    productAreaOptions: productAreaOptions(),
    pageFeatures: [],
    getCompaniesDemoData: buildData,
    searchCompanies,
    loadCompaniesTable,
    coercePeriodKey
  };

  if (globalScope.document.readyState === "loading") {
    globalScope.document.addEventListener("DOMContentLoaded", syncProductAreaMatrixHeadings, { once: true });
  } else {
    syncProductAreaMatrixHeadings();
  }
})(window);
