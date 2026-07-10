(function registerHymetryCompanyDetailHelpers(root, factory) {
  if (typeof module === "object" && module.exports) {
    const pageDetailsHelpers = require("../Pages/page-details-helpers");
    module.exports = factory(pageDetailsHelpers);
    return;
  }

  root.HymetryCompanyDetailHelpers = factory(root.HymetryPageDetailsHelpers || {});
})(typeof globalThis !== "undefined" ? globalThis : window, function createHymetryCompanyDetailHelpers(pageDetailsHelpers) {
  const PERIOD_OPTIONS = [7, 30, 90, 180];
  const DEFAULT_PERIOD = "30d";
  const DEFAULT_END_DATE = "2026-05-06";

  const planOptions = ["Growth", "Business", "Scale", "Enterprise"];
  const industryOptions = ["SaaS", "Fintech", "Healthcare", "Operations", "Analytics", "Education"];
  const firstNames = [
    "Avery",
    "Blair",
    "Casey",
    "Drew",
    "Elliot",
    "Finley",
    "Gray",
    "Harper",
    "Jordan",
    "Kai",
    "Logan",
    "Morgan",
    "Parker",
    "Quinn",
    "Riley",
    "Sawyer",
    "Taylor",
    "Vale",
    "Wren",
    "Zion"
  ];
  const lastNames = [
    "Adams",
    "Bennett",
    "Chen",
    "Diaz",
    "Ellis",
    "Foster",
    "Gupta",
    "Hayes",
    "Ivanov",
    "Jones",
    "Kim",
    "Lopez",
    "Miller",
    "Nguyen",
    "Patel",
    "Reed",
    "Singh",
    "Turner",
    "Walker",
    "Young"
  ];
  const userHealthDistributionOrder = ["power", "healthy", "light", "passive", "dropped"];
  const userHealthDistributionLabels = {
    dropped: "Dropped",
    healthy: "Healthy",
    light: "Light",
    passive: "Passive",
    power: "Power"
  };

  const pageCatalog = [
    { pageRuleId: "dashboard", pageName: "Dashboard", productArea: "Core product" },
    { pageRuleId: "projects", pageName: "Projects", productArea: "Core product" },
    { pageRuleId: "sessions", pageName: "Sessions", productArea: "Core product" },
    { pageRuleId: "billing", pageName: "Billing", productArea: "Billing" },
    { pageRuleId: "pricing", pageName: "Pricing", productArea: "Billing" },
    { pageRuleId: "invoices", pageName: "Invoices", productArea: "Billing" },
    { pageRuleId: "payment-methods", pageName: "Payment methods", productArea: "Billing" },
    { pageRuleId: "api-keys", pageName: "API keys", productArea: "Developer" },
    { pageRuleId: "webhooks", pageName: "Webhooks", productArea: "Developer" },
    { pageRuleId: "integrations", pageName: "Integrations", productArea: "Integrations" },
    { pageRuleId: "users", pageName: "Users", productArea: "Administration" },
    { pageRuleId: "audit-log", pageName: "Audit log", productArea: "Administration" },
    { pageRuleId: "notifications", pageName: "Notifications", productArea: "Administration" },
    { pageRuleId: "reports", pageName: "Reports", productArea: "Reporting" },
    { pageRuleId: "data-export", pageName: "Data export", productArea: "Export" },
    { pageRuleId: "team-permissions", pageName: "Team permissions", productArea: "Team permissions" },
    { pageRuleId: "settings", pageName: "Settings", productArea: "Settings" },
    { pageRuleId: "help-center", pageName: "Help center", productArea: "Core product" },
    { pageRuleId: "contact", pageName: "Contact", productArea: "Settings" },
    { pageRuleId: "status", pageName: "Status", productArea: "Core product" }
  ];

  const calculateMetricDelta = pageDetailsHelpers.calculateMetricDelta || fallbackCalculateMetricDelta;

  function fallbackCalculateMetricDelta(currentValue, previousValue, deltaType) {
    const current = Number(currentValue);
    const previous = Number(previousValue);

    if (!Number.isFinite(current) || !Number.isFinite(previous)) {
      return { value: null, label: "-", direction: "neutral" };
    }

    if (deltaType === "percentage_point") {
      const delta = current - previous;
      return {
        value: delta,
        label: formatSignedNumber(delta, " pp"),
        direction: delta > 0 ? "positive" : delta < 0 ? "negative" : "neutral"
      };
    }

    if (previous === 0) {
      if (current > 0) {
        return { value: null, label: "new", direction: "positive" };
      }

      return { value: 0, label: "0%", direction: "neutral" };
    }

    const delta = ((current - previous) / Math.abs(previous)) * 100;

    return {
      value: delta,
      label: formatSignedNumber(delta, "%"),
      direction: delta > 0 ? "positive" : delta < 0 ? "negative" : "neutral"
    };
  }

  function formatSignedNumber(value, suffix) {
    const rounded = Math.round(Number(value) || 0);
    const prefix = rounded > 0 ? "+" : "";

    return `${prefix}${rounded}${suffix}`;
  }

  function slugify(value) {
    return String(value || "item")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/(^-|-$)/g, "");
  }

  function coerceCompanyDetailPeriod(value) {
    const raw = String(value || DEFAULT_PERIOD).trim().toLowerCase().replace("d", "");
    const days = Number(raw);

    return PERIOD_OPTIONS.includes(days) ? `${days}d` : DEFAULT_PERIOD;
  }

  function daysFromPeriod(period) {
    return Number(coerceCompanyDetailPeriod(period).replace("d", ""));
  }

  function toUtcDate(value) {
    const parsed = value ? new Date(`${String(value).slice(0, 10)}T00:00:00Z`) : new Date(`${DEFAULT_END_DATE}T00:00:00Z`);

    if (Number.isNaN(parsed.getTime())) {
      return new Date(`${DEFAULT_END_DATE}T00:00:00Z`);
    }

    return new Date(Date.UTC(parsed.getUTCFullYear(), parsed.getUTCMonth(), parsed.getUTCDate()));
  }

  function addDays(date, days) {
    const next = new Date(date.getTime());
    next.setUTCDate(next.getUTCDate() + days);

    return next;
  }

  function formatIsoDate(date) {
    return date.toISOString().slice(0, 10);
  }

  function calculateCompanyDetailsPeriod(periodValue, endDateValue) {
    const key = coerceCompanyDetailPeriod(periodValue);
    const days = daysFromPeriod(key);
    const endDate = toUtcDate(endDateValue || DEFAULT_END_DATE);
    const startDate = addDays(endDate, -(days - 1));
    const previousEndDate = addDays(startDate, -1);
    const previousStartDate = addDays(previousEndDate, -(days - 1));

    return {
      key,
      days,
      startDate: formatIsoDate(startDate),
      endDate: formatIsoDate(endDate),
      previousStartDate: formatIsoDate(previousStartDate),
      previousEndDate: formatIsoDate(previousEndDate)
    };
  }

  function clamp(value, min, max) {
    return Math.max(min, Math.min(max, Number(value) || 0));
  }

  function sum(rows, selector) {
    return rows.reduce((total, row, index) => total + (Number(selector(row, index)) || 0), 0);
  }

  function median(values) {
    const numericValues = values.map((value) => Number(value)).filter(Number.isFinite).sort((a, b) => a - b);

    if (!numericValues.length) {
      return 0;
    }

    const midpoint = Math.floor(numericValues.length / 2);

    return numericValues.length % 2 === 0
      ? (numericValues[midpoint - 1] + numericValues[midpoint]) / 2
      : numericValues[midpoint];
  }

  function previousPeriodValue(currentValue, deltaValue, unit) {
    const current = Number(currentValue) || 0;
    const delta = Number(deltaValue) || 0;

    if (unit === "pp") {
      return clamp(current - delta, 0, 100);
    }

    const divisor = 1 + delta / 100;

    return divisor > 0 ? current / divisor : 0;
  }

  function deterministicNumber(seedText, min, max) {
    const source = String(seedText || "seed");
    let hash = 0;

    for (let index = 0; index < source.length; index += 1) {
      hash = (hash * 31 + source.charCodeAt(index)) % 1000003;
    }

    return min + (hash % (max - min + 1));
  }

  function companyIndex(data, companyId) {
    return Math.max(0, (data.companies || []).findIndex((row) => row.id === companyId));
  }

  function getCompanyAreas(company, productAreas) {
    const distributionAreas = (company.productAreaDistribution || []).map((item) => item.productArea).filter(Boolean);

    if (distributionAreas.length) {
      return distributionAreas;
    }

    return (productAreas || []).slice(0, Math.max(1, company.productAreasUsed || 1));
  }

  function metadataForCompany(company, data) {
    const index = companyIndex(data, company.id);
    const activeUsers = Number(company.activeUsers) || 0;
    const totalKnownUsers = Math.max(activeUsers, activeUsers + deterministicNumber(`${company.id}:known-users`, 2, Math.max(5, activeUsers + 8)));
    const accountAgeDays = deterministicNumber(`${company.id}:account-age`, 28, 960);
    const segment = activeUsers >= 35 ? "Enterprise" : activeUsers >= 18 ? "Mid-market" : activeUsers >= 8 ? "SMB" : "Startup";

    return {
      plan: planOptions[index % planOptions.length],
      segment,
      industry: industryOptions[index % industryOptions.length],
      accountAgeDays,
      totalKnownUsers
    };
  }

  function enhanceCompany(company, data) {
    const metadata = metadataForCompany(company, data);
    const activeUsers = Number(company.activeUsers) || 0;
    const engagedSeconds = Number(company.engagedSeconds) || 0;
    const avgEngagedSecondsPerUser = Number(company.avgEngagedSecondsPerUser) || 0;
    const activeUsersDeltaPct = Number(company.activeUsersDeltaPct) || 0;
    const engagedDeltaPct = Number(company.engagedDeltaPct) || 0;
    const previousActiveUsers = previousPeriodValue(activeUsers, activeUsersDeltaPct, "%");
    const previousEngagedSeconds = previousPeriodValue(engagedSeconds, engagedDeltaPct, "%");
    const previousAvgEngagedSecondsPerUser = previousActiveUsers > 0 ? previousEngagedSeconds / previousActiveUsers : 0;

    return {
      id: company.id,
      name: company.name,
      domain: company.domain || "",
      status: company.status,
      plan: metadata.plan,
      segment: metadata.segment,
      industry: metadata.industry,
      lastActiveAt: company.lastSeen || "",
      lastSeenDays: Number(company.lastSeenDays) || 0,
      accountAgeDays: metadata.accountAgeDays,
      activeUsers,
      totalKnownUsers: metadata.totalKnownUsers,
      productAreasUsed: Number(company.productAreasUsed) || 0,
      pagesUsed: Number(company.pagesUsed) || 0,
      visits: Number(company.visits) || 0,
      engagedSeconds,
      avgEngagedSecondsPerUser,
      avgEngagedSecondsPerUserDeltaPct: calculateMetricDelta(avgEngagedSecondsPerUser, previousAvgEngagedSecondsPerUser, "percent").value || 0,
      interactionPct: Number(company.interactionPct) || 0,
      activeUsersDeltaPct,
      visitsDeltaPct: Number(company.visitsDeltaPct) || 0,
      engagedDeltaPct,
      interactionDeltaPp: Number(company.interactionDeltaPp) || 0,
      productAreasDelta: Number(company.productAreasDelta) || 0,
      topProductArea: company.topProductArea || "",
      productAreaDistribution: company.productAreaDistribution || []
    };
  }

  function dateSeries(period) {
    const endDate = toUtcDate(period.endDate);

    return Array.from({ length: period.days }, (_, index) => formatIsoDate(addDays(endDate, index - (period.days - 1))));
  }

  function distributedSeries(total, period, seed, options = {}) {
    const totalValue = Math.max(0, Number(total) || 0);
    const dates = dateSeries(period);

    if (!dates.length) {
      return [];
    }

    if (totalValue === 0) {
      return dates.map((date) => ({ date, value: 0 }));
    }

    const trendBias = Number(options.trendBias) || 0;
    const weights = dates.map((_, index) => {
      const progress = dates.length <= 1 ? 1 : index / (dates.length - 1);
      const seasonal = 1 + Math.sin((index + seed) * 0.83) * 0.18 + Math.cos((index + seed * 0.37) * 0.41) * 0.1;
      const trend = 1 + (progress - 0.5) * trendBias;

      return Math.max(0.08, seasonal * trend);
    });
    const weightTotal = sum(weights, (value) => value) || 1;
    let allocated = 0;

    return dates.map((date, index) => {
      const isLast = index === dates.length - 1;
      const rawValue = isLast ? totalValue - allocated : (totalValue * weights[index]) / weightTotal;
      const value = options.integer === false ? Math.max(0, rawValue) : Math.max(0, Math.round(rawValue));

      allocated += value;

      return { date, value };
    });
  }

  function dailyLevelSeries(levelValue, period, seed, options = {}) {
    const level = Math.max(0, Number(levelValue) || 0);
    const dates = dateSeries(period);
    const minValue = Number(options.minValue) || 0;
    const maxValue = Number(options.maxValue) || Math.max(level * 1.36, minValue + 1);

    return dates.map((date, index) => {
      const wave = Math.sin((index + seed) * 0.71) * 0.14 + Math.cos((index + seed * 0.21) * 0.53) * 0.08;
      const trend = (Number(options.trendBias) || 0) * (dates.length <= 1 ? 0 : index / (dates.length - 1) - 0.5);
      const value = clamp(level * (1 + wave + trend), minValue, maxValue);

      return {
        date,
        value: options.integer === false ? value : Math.round(value)
      };
    });
  }

  function cumulativeSeries(finalValue, period, seed) {
    const final = Math.max(0, Math.round(Number(finalValue) || 0));
    const dates = dateSeries(period);

    if (!dates.length || final === 0) {
      return dates.map((date) => ({ date, value: 0 }));
    }

    return dates.map((date, index) => {
      const progress = (index + 1) / dates.length;
      const curve = 1 - Math.exp(-progress * (2.5 + (seed % 4) * 0.26));
      const jitter = Math.sin((index + seed) * 0.6) * 0.035;

      return {
        date,
        value: Math.min(final, Math.max(1, Math.round(final * clamp(curve + jitter, 0, 1))))
      };
    });
  }

  function usedPageCatalog(company, data) {
    const productAreas = data.productAreas || [];
    const usedAreas = getCompanyAreas(company, productAreas);
    const pagesByArea = new Map();

    pageCatalog.forEach((page) => {
      if (!pagesByArea.has(page.productArea)) {
        pagesByArea.set(page.productArea, []);
      }

      pagesByArea.get(page.productArea).push(page);
    });

    const usedPages = [];

    usedAreas.forEach((area) => {
      const pages = pagesByArea.get(area) || [];
      const desiredCount = Math.max(1, Math.ceil((Number(company.pagesUsed) || 1) / Math.max(usedAreas.length, 1)));

      usedPages.push(...pages.slice(0, desiredCount));
    });

    if (usedPages.length < Math.min(company.pagesUsed || 1, pageCatalog.length)) {
      pageCatalog.forEach((page) => {
        if (usedPages.length >= Math.min(company.pagesUsed || 1, pageCatalog.length)) {
          return;
        }

        if (!usedPages.some((usedPage) => usedPage.pageRuleId === page.pageRuleId)) {
          usedPages.push(page);
        }
      });
    }

    return usedPages.slice(0, Math.min(Math.max(company.pagesUsed || 1, 1), pageCatalog.length));
  }

  function areaWeightLookup(company, data) {
    const distribution = company.productAreaDistribution || [];
    const usedAreas = getCompanyAreas(company, data.productAreas || []);

    if (distribution.length) {
      const lookup = new Map(distribution.map((item) => [item.productArea, Math.max(0, Number(item.percent) || 0)]));
      const total = sum(Array.from(lookup.values()), (value) => value) || 1;

      return new Map(Array.from(lookup.entries()).map(([area, value]) => [area, value / total]));
    }

    const totalWeight = sum(usedAreas, (_, index) => 1 / (index + 1));

    return new Map(usedAreas.map((area, index) => [area, (1 / (index + 1)) / totalWeight]));
  }

  function buildPageUsage(company, data, period) {
    const pages = usedPageCatalog(company, data);
    const areaWeights = areaWeightLookup(company, data);
    const pagesByArea = pages.reduce((lookup, page) => {
      if (!lookup.has(page.productArea)) {
        lookup.set(page.productArea, []);
      }

      lookup.get(page.productArea).push(page);
      return lookup;
    }, new Map());
    const rows = [];

    pagesByArea.forEach((areaPages, area) => {
      const areaWeight = areaWeights.get(area) || (1 / Math.max(pagesByArea.size, 1));
      const areaEngaged = Math.max(0, company.engagedSeconds * areaWeight);
      const areaVisits = Math.max(0, company.visits * areaWeight);

      areaPages.forEach((page, pageIndex) => {
        const pageWeight = 1 / (pageIndex + 1.18);
        const pageWeightTotal = sum(areaPages, (_, index) => 1 / (index + 1.18)) || 1;
        const share = pageWeight / pageWeightTotal;
        const engagedSeconds = Math.max(60, Math.round(areaEngaged * share));
        const visits = Math.max(1, Math.round(areaVisits * share));
        const users = Math.max(1, Math.min(company.activeUsers, Math.round(company.activeUsers * areaWeight * (0.92 - pageIndex * 0.08))));
        const avgVisitSeconds = visits ? Math.round(engagedSeconds / visits) : 0;
        const interactionPct = clamp(company.interactionPct + ((pageIndex % 5) - 2) * 3 + deterministicNumber(`${company.id}:${page.pageRuleId}:interaction`, -2, 4), 3, 98);
        const previousUsers = previousPeriodValue(users, company.activeUsersDeltaPct + deterministicNumber(`${page.pageRuleId}:users-delta`, -8, 8), "%");
        const previousVisits = previousPeriodValue(visits, company.visitsDeltaPct + deterministicNumber(`${page.pageRuleId}:visits-delta`, -7, 7), "%");
        const previousEngaged = previousPeriodValue(engagedSeconds, company.engagedDeltaPct + deterministicNumber(`${page.pageRuleId}:engaged-delta`, -8, 8), "%");
        const previousAvgVisit = previousVisits ? previousEngaged / previousVisits : 0;
        const seed = deterministicNumber(`${company.id}:${page.pageRuleId}:trend`, 1, 97);

        rows.push({
          pageRuleId: page.pageRuleId,
          pageName: page.pageName,
          productArea: page.productArea,
          users,
          usersDeltaPct: calculateMetricDelta(users, previousUsers, "percent").value || 0,
          visits,
          visitsDeltaPct: calculateMetricDelta(visits, previousVisits, "percent").value || 0,
          engagedSeconds,
          engagedDeltaPct: calculateMetricDelta(engagedSeconds, previousEngaged, "percent").value || 0,
          avgVisitSeconds,
          avgVisitDeltaPct: calculateMetricDelta(avgVisitSeconds, previousAvgVisit, "percent").value || 0,
          interactionPct,
          interactionDeltaPp: company.interactionDeltaPp + deterministicNumber(`${page.pageRuleId}:interaction-delta`, -4, 4),
          dailySeries: distributedSeries(engagedSeconds, period, seed, {
            trendBias: (company.engagedDeltaPct || 0) / 120,
            integer: true
          })
        });
      });
    });

    return rows
      .sort((a, b) => b.engagedSeconds - a.engagedSeconds || b.visits - a.visits || a.pageName.localeCompare(b.pageName));
  }

  function buildAreaTreemap(topPages, company) {
    const totalEngagedSeconds = sum(topPages, (row) => row.engagedSeconds);
    const byArea = topPages.reduce((lookup, row) => {
      if (!lookup.has(row.productArea)) {
        lookup.set(row.productArea, []);
      }

      lookup.get(row.productArea).push(row);
      return lookup;
    }, new Map());

    return {
      totalEngagedSeconds,
      nodes: Array.from(byArea.entries()).map(([area, rows]) => ({
        name: area,
        page_group: area,
        productArea: area,
        value: sum(rows, (row) => row.engagedSeconds),
        engagedSeconds: sum(rows, (row) => row.engagedSeconds),
        visits: sum(rows, (row) => row.visits),
        activeUsers: Math.min(company.activeUsers, sum(rows, (row) => row.users)),
        pageCount: rows.length,
        isGroup: true,
        children: rows.map((row) => ({
          name: row.pageName,
          pageRuleId: row.pageRuleId,
          page_group: row.productArea,
          productArea: row.productArea,
          value: row.engagedSeconds,
          engagedSeconds: row.engagedSeconds,
          visits: row.visits,
          activeUsers: row.users,
          shareOfCompanyEngaged: totalEngagedSeconds ? (row.engagedSeconds / totalEngagedSeconds) * 100 : 0
        }))
      }))
    };
  }

  function buildAdoptionBreadthSeries(topPages, data, period, company) {
    const dates = dateSeries(period);
    const pages = topPages.map((page, index) => ({
      ...page,
      firstSeenIndex: Math.min(dates.length - 1, Math.max(0, Math.round((index / Math.max(topPages.length, 1)) * (dates.length - 1))))
    }));
    const productAreas = data.productAreas || [];

    return {
      dates,
      productAreas,
      series: productAreas.map((area) => ({
        productArea: area,
        values: dates.map((_, dateIndex) =>
          sum(
            pages.filter((page) => page.productArea === area && page.firstSeenIndex <= dateIndex),
            (page) => Number(page.dailySeries?.[dateIndex]?.value) || 0
          )
        ),
        topPagesByDate: dates.map((date, dateIndex) => ({
          date,
          pageNames: pages
            .filter((page) => page.productArea === area && page.firstSeenIndex <= dateIndex)
            .slice(0, 3)
            .map((page) => page.pageName)
        }))
      })).filter((row) => row.values.some((value) => value > 0)),
      finalAreaCount: company.productAreasUsed,
      finalPageCount: company.pagesUsed
    };
  }

  function dailyMetricPayload({ key, label, valueType, currentValue, previousValue, dailySeries, peerCompanies, period, secondaryText }) {
    const delta = calculateMetricDelta(currentValue, previousValue, valueType === "percent" ? "percentage_point" : "percent");
    const metricSeed = deterministicNumber(key, 1, 83);

    return {
      key,
      label,
      valueType,
      value: currentValue,
      previousValue,
      deltaValue: delta.value,
      deltaDirection: delta.direction,
      formattedDelta: delta.label,
      secondaryText: secondaryText || "",
      dailySeries,
      peerSeries: (peerCompanies || []).slice(0, 10).map((peer, index) => {
        const peerValue = peerMetricValue(peer, key);
        const seed = deterministicNumber(`${peer.id}:${key}`, 1, 97);

        return {
          companyId: peer.id,
          companyName: peer.name,
          dailySeries: key === "interaction"
            ? dailyLevelSeries(peerValue, period, seed, { integer: false, minValue: 0, maxValue: 100, trendBias: peer.interactionDeltaPp / 80 })
            : key === "adoptionBreadth"
              ? cumulativeSeries(peer.pagesUsed, period, seed)
              : key === "activeUsers" || key === "newReactivatedUsers" || key === "atRiskUsers"
                ? dailyLevelSeries(peerValue, period, seed + metricSeed, { integer: true, minValue: 0, trendBias: (peer.activeUsersDeltaPct || 0) / 140 })
                : distributedSeries(peerValue, period, seed + index, { integer: true, trendBias: (peer.engagedDeltaPct || 0) / 140 })
        };
      })
    };
  }

  function peerMetricValue(company, key) {
    switch (key) {
      case "activeUsers":
        return company.activeUsers;
      case "newReactivatedUsers":
        return estimateNewReactivatedUsers(company).total;
      case "visits":
        return company.visits;
      case "engaged":
        return company.engagedSeconds;
      case "avgPerUser":
        return company.avgEngagedSecondsPerUser;
      case "interaction":
        return company.interactionPct;
      case "adoptionBreadth":
        return company.pagesUsed;
      case "atRiskUsers":
        return estimateAtRiskUsers(company).current;
      default:
        return 0;
    }
  }

  function estimateNewReactivatedUsers(company) {
    const activeUsers = Number(company.activeUsers) || 0;
    const statusBoost = company.status === "new" ? 0.55 : company.status === "reactivated" ? 0.38 : company.status === "activated" ? 0.18 : 0.08;
    const growthBoost = Math.max(0, Number(company.activeUsersDeltaPct) || 0) / 180;
    const total = Math.max(0, Math.round(activeUsers * Math.min(0.72, statusBoost + growthBoost)));
    const newUsers = company.status === "new" ? Math.max(1, Math.round(total * 0.72)) : Math.max(0, Math.round(total * 0.42));

    return {
      total,
      newUsers: Math.min(total, newUsers),
      reactivatedUsers: Math.max(0, total - Math.min(total, newUsers))
    };
  }

  function estimateAtRiskUsers(company) {
    const activeDrop = Math.max(0, -(Number(company.activeUsersDeltaPct) || 0));
    const engagedDrop = Math.max(0, -(Number(company.engagedDeltaPct) || 0));
    const statusBoost = company.status === "at_risk" ? 0.22 : company.status === "dormant" ? 0.35 : 0.05;
    const ratio = Math.min(0.72, statusBoost + (activeDrop + engagedDrop) / 240);
    const current = Math.max(0, Math.round((Number(company.activeUsers) || 0) * ratio));
    const previous = Math.max(0, Math.round(current * (company.status === "at_risk" ? 0.72 : 1.18)));

    return { current, previous };
  }

  function buildMetricCards(company, peerCompanies, period) {
    const activeUsersPrevious = previousPeriodValue(company.activeUsers, company.activeUsersDeltaPct, "%");
    const visitsPrevious = previousPeriodValue(company.visits, company.visitsDeltaPct, "%");
    const engagedPrevious = previousPeriodValue(company.engagedSeconds, company.engagedDeltaPct, "%");
    const avgCurrent = company.activeUsers ? company.engagedSeconds / company.activeUsers : 0;
    const avgPrevious = activeUsersPrevious ? engagedPrevious / activeUsersPrevious : 0;
    const interactionPrevious = previousPeriodValue(company.interactionPct, company.interactionDeltaPp, "pp");
    const newReactivated = estimateNewReactivatedUsers(company);
    const previousNewReactivated = Math.max(0, Math.round(newReactivated.total / (1 + Math.max(company.activeUsersDeltaPct, -80) / 140 || 1)));
    const previousAreas = Math.max(0, company.productAreasUsed - company.productAreasDelta);
    const previousPages = Math.max(0, company.pagesUsed - Math.round(company.productAreasDelta * 2.6));
    const atRisk = estimateAtRiskUsers(company);

    return [
      dailyMetricPayload({
        key: "activeUsers",
        label: "ACTIVE USERS",
        valueType: "number",
        currentValue: company.activeUsers,
        previousValue: activeUsersPrevious,
        dailySeries: dailyLevelSeries(company.activeUsers * 0.52, period, deterministicNumber(`${company.id}:active`, 1, 97), {
          integer: true,
          minValue: Math.min(company.activeUsers, 1),
          maxValue: Math.max(company.activeUsers, 2),
          trendBias: company.activeUsersDeltaPct / 120
        }),
        peerCompanies,
        period
      }),
      dailyMetricPayload({
        key: "newReactivatedUsers",
        label: "NEW / REACTIVATED",
        valueType: "number",
        currentValue: newReactivated.total,
        previousValue: previousNewReactivated,
        dailySeries: distributedSeries(newReactivated.total, period, deterministicNumber(`${company.id}:new-reactivated`, 1, 97), {
          integer: true,
          trendBias: company.activeUsersDeltaPct / 160
        }),
        peerCompanies,
        period,
        secondaryText: `${newReactivated.newUsers} new \u00b7 ${newReactivated.reactivatedUsers} reactivated`
      }),
      dailyMetricPayload({
        key: "visits",
        label: "VISITS",
        valueType: "number",
        currentValue: company.visits,
        previousValue: visitsPrevious,
        dailySeries: distributedSeries(company.visits, period, deterministicNumber(`${company.id}:visits`, 1, 97), {
          integer: true,
          trendBias: company.visitsDeltaPct / 120
        }),
        peerCompanies,
        period
      }),
      dailyMetricPayload({
        key: "engaged",
        label: "ENGAGED",
        valueType: "duration",
        currentValue: company.engagedSeconds,
        previousValue: engagedPrevious,
        dailySeries: distributedSeries(company.engagedSeconds, period, deterministicNumber(`${company.id}:engaged`, 1, 97), {
          integer: true,
          trendBias: company.engagedDeltaPct / 120
        }),
        peerCompanies,
        period
      }),
      dailyMetricPayload({
        key: "avgPerUser",
        label: "AVG / USER",
        valueType: "duration",
        currentValue: avgCurrent,
        previousValue: avgPrevious,
        dailySeries: dailyLevelSeries(avgCurrent, period, deterministicNumber(`${company.id}:avg-user`, 1, 97), {
          integer: true,
          minValue: 0,
          trendBias: (company.engagedDeltaPct - company.activeUsersDeltaPct) / 140
        }),
        peerCompanies,
        period
      }),
      dailyMetricPayload({
        key: "interaction",
        label: "INTERACTION",
        valueType: "percent",
        currentValue: company.interactionPct,
        previousValue: interactionPrevious,
        dailySeries: dailyLevelSeries(company.interactionPct, period, deterministicNumber(`${company.id}:interaction`, 1, 97), {
          integer: false,
          minValue: 0,
          maxValue: 100,
          trendBias: company.interactionDeltaPp / 60
        }),
        peerCompanies,
        period
      }),
      {
        ...dailyMetricPayload({
          key: "adoptionBreadth",
          label: "ADOPTION BREADTH",
          valueType: "number",
          currentValue: company.productAreasUsed,
          previousValue: previousAreas,
          dailySeries: cumulativeSeries(company.pagesUsed, period, deterministicNumber(`${company.id}:adoption`, 1, 97)),
          peerCompanies,
          period,
          secondaryText: `${company.productAreasUsed} areas \u00b7 ${company.pagesUsed} pages`
        }),
        previousPages,
        formattedDelta: company.productAreasDelta
          ? `${company.productAreasDelta > 0 ? "+" : ""}${company.productAreasDelta} area`
          : `${company.pagesUsed - previousPages > 0 ? "+" : ""}${company.pagesUsed - previousPages} pages`,
        deltaDirection: company.productAreasDelta > 0 || company.pagesUsed > previousPages ? "positive" : company.productAreasDelta < 0 || company.pagesUsed < previousPages ? "negative" : "neutral"
      },
      dailyMetricPayload({
        key: "atRiskUsers",
        label: "AT-RISK USERS",
        valueType: "number",
        currentValue: atRisk.current,
        previousValue: atRisk.previous,
        dailySeries: dailyLevelSeries(atRisk.current, period, deterministicNumber(`${company.id}:risk`, 1, 97), {
          integer: true,
          minValue: 0,
          trendBias: company.status === "at_risk" ? 0.34 : -0.18
        }),
        peerCompanies,
        period
      })
    ];
  }

  function selectSimilarCompanies(companies, companyId, limit = 10, data = {}) {
    const currentSource = (companies || []).find((row) => row.id === companyId);

    if (!currentSource) {
      return [];
    }

    const current = enhanceCompany(currentSource, data);
    const rows = (companies || [])
      .filter((row) => row.id !== companyId && (Number(row.activeUsers) || 0) > 0)
      .map((row) => enhanceCompany(row, data))
      .map((row) => {
        const activeSimilarity = Math.abs(Math.log2((row.activeUsers + 1) / (current.activeUsers + 1)));
        const totalUsersSimilarity = Math.abs(Math.log2((row.totalKnownUsers + 1) / (current.totalKnownUsers + 1)));
        const ageSimilarity = Math.abs(row.accountAgeDays - current.accountAgeDays) / 365;
        const samePlanBonus = row.plan === current.plan ? -0.42 : 0;
        const sameSegmentBonus = row.segment === current.segment ? -0.68 : 0;
        const sameIndustryBonus = row.industry === current.industry ? -0.28 : 0;

        return {
          ...row,
          peerScore: activeSimilarity * 2.8 + totalUsersSimilarity * 1.2 + ageSimilarity * 0.9 + samePlanBonus + sameSegmentBonus + sameIndustryBonus
        };
      });

    return rows
      .sort((a, b) => a.peerScore - b.peerScore || a.name.localeCompare(b.name))
      .slice(0, Math.max(0, Number(limit) || 10));
  }

  function productAreaDistributionToCells(company, data) {
    const distributionByArea = new Map((company.productAreaDistribution || []).map((item) => [
      item.productArea || item.product_area_name || item.name,
      item
    ]));

    return (data.productAreas || []).map((area) => {
      const distributionItem = distributionByArea.get(area) || {};
      const percent = Math.max(0, Number(distributionItem.percent) || 0);
      const rawEngagedSeconds = distributionItem.engagedSeconds ?? distributionItem.engaged_seconds;
      const rawVisits = distributionItem.visits ?? distributionItem.visits_count;
      const rawPagesUsed = distributionItem.pagesUsed ?? distributionItem.pages_used;
      const used = percent > 0 || (Number(rawEngagedSeconds) || 0) > 0 || (Number(rawVisits) || 0) > 0;
      const engagedSeconds = used
        ? Math.round(rawEngagedSeconds == null ? company.engagedSeconds * (percent / 100) : Math.max(0, Number(rawEngagedSeconds) || 0))
        : 0;
      const visits = used
        ? Math.max(1, Math.round(rawVisits == null ? company.visits * (percent / 100) : Math.max(0, Number(rawVisits) || 0)))
        : 0;

      return {
        productArea: area,
        used,
        engagedSeconds,
        visits,
        activeUsers: used ? Math.max(1, Math.round(company.activeUsers * Math.min(0.95, 0.35 + percent / 100))) : 0,
        pagesUsed: used ? Math.max(1, Math.round(rawPagesUsed == null ? company.pagesUsed * (percent / 100) : Math.max(0, Number(rawPagesUsed) || 0))) : 0
      };
    });
  }

  function keyDifference(peer, current) {
    const peerTopArea = peer.topProductArea || "";
    const currentAreas = new Set((current.productAreaDistribution || []).filter((item) => item.percent > 0).map((item) => item.productArea || item.product_area_name || item.name));
    const engagedDiff = peer.avgEngagedSecondsPerUser - current.avgEngagedSecondsPerUser;
    const breadthDiff = peer.productAreasUsed - current.productAreasUsed;

    if (peerTopArea && !currentAreas.has(peerTopArea)) {
      return `Uses ${peerTopArea} more than this company`;
    }

    if (breadthDiff >= 2) {
      return "Higher adoption breadth";
    }

    if (breadthDiff <= -2) {
      return "Lower adoption breadth";
    }

    if (engagedDiff > current.avgEngagedSecondsPerUser * 0.18) {
      return "Higher engaged/user";
    }

    if (engagedDiff < -current.avgEngagedSecondsPerUser * 0.18) {
      return "Lower engaged/user";
    }

    return "Similar adoption breadth";
  }

  function peerMedianRow(peers, data) {
    if (!peers.length) {
      return null;
    }

    const medianCompany = {
      id: "peer-median",
      name: "Peer median",
      status: "healthy",
      activeUsers: Math.round(median(peers.map((row) => row.activeUsers))),
      visits: Math.round(median(peers.map((row) => row.visits))),
      engagedSeconds: Math.round(median(peers.map((row) => row.engagedSeconds))),
      avgEngagedSecondsPerUser: Math.round(median(peers.map((row) => row.avgEngagedSecondsPerUser))),
      avgEngagedSecondsPerUserDeltaPct: Math.round(median(peers.map((row) => row.avgEngagedSecondsPerUserDeltaPct))),
      productAreasUsed: Math.round(median(peers.map((row) => row.productAreasUsed))),
      pagesUsed: Math.round(median(peers.map((row) => row.pagesUsed))),
      interactionPct: Math.round(median(peers.map((row) => row.interactionPct))),
      productAreaDistribution: (data.productAreas || []).map((area) => ({
        productArea: area,
        percent: Math.round(median(peers.map((row) => {
          const item = (row.productAreaDistribution || []).find((distributionItem) => (distributionItem.productArea || distributionItem.product_area_name || distributionItem.name) === area);
          return item?.percent || 0;
        }))),
        engagedSeconds: Math.round(median(peers.map((row) => {
          const item = (row.productAreaDistribution || []).find((distributionItem) => (distributionItem.productArea || distributionItem.product_area_name || distributionItem.name) === area);
          return item?.engagedSeconds || item?.engaged_seconds || ((Number(row.engagedSeconds) || 0) * (Number(item?.percent) || 0)) / 100;
        }))),
        visits: Math.round(median(peers.map((row) => {
          const item = (row.productAreaDistribution || []).find((distributionItem) => (distributionItem.productArea || distributionItem.product_area_name || distributionItem.name) === area);
          return item?.visits || ((Number(row.visits) || 0) * (Number(item?.percent) || 0)) / 100;
        })))
      })).filter((item) => item.percent > 0)
    };

    return {
      ...medianCompany,
      productAreaAdoption: productAreaDistributionToCells(medianCompany, data),
      keyDifference: "Median of similar companies",
      rowType: "median"
    };
  }

  function buildPeerComparison(current, peers, data) {
    const currentRow = {
      ...current,
      productAreaAdoption: productAreaDistributionToCells(current, data),
      keyDifference: "This company",
      rowType: "current"
    };
    const medianRow = peerMedianRow(peers, data);
    const peerRows = peers.map((peer) => ({
      ...peer,
      productAreaAdoption: productAreaDistributionToCells(peer, data),
      keyDifference: keyDifference(peer, current),
      rowType: "peer"
    }));
    const rows = [currentRow, medianRow, ...peerRows].filter(Boolean);
    const insights = [];

    if (medianRow) {
      if (current.avgEngagedSecondsPerUser > medianRow.avgEngagedSecondsPerUser * 1.12) {
        insights.push("Above peer median in engagement");
      } else if (current.avgEngagedSecondsPerUser < medianRow.avgEngagedSecondsPerUser * 0.88) {
        insights.push("Below peer median in engagement");
      }

      if (current.productAreasUsed > medianRow.productAreasUsed) {
        insights.push("Above peer median in adoption breadth");
      } else if (current.productAreasUsed < medianRow.productAreasUsed) {
        insights.push("Below peer median in adoption breadth");
      }

      const missingArea = (data.productAreas || []).find((area) => {
        const currentPercent = current.productAreaDistribution.find((item) => item.productArea === area)?.percent || 0;
        const peerMedianPercent = medianRow.productAreaDistribution.find((item) => item.productArea === area)?.percent || 0;

        return currentPercent <= 2 && peerMedianPercent >= 8;
      });

      if (missingArea) {
        insights.push(`${missingArea} unused, while most peers use it`);
      }
    }

    return {
      insights: insights.slice(0, 3),
      rows
    };
  }

  function userStatusForIndex(company, index, activeLimit) {
    if (index >= activeLimit) {
      return "dropped";
    }

    if ((company.status === "at_risk" || company.engagedDeltaPct < -25) && index % 4 === 0) {
      return "passive";
    }

    const rankRatio = activeLimit > 0 ? index / activeLimit : 1;

    if ((company.status === "power" || company.productAreasUsed >= 6) && rankRatio < 0.22) {
      return "power";
    }

    if (rankRatio < 0.48) {
      return "healthy";
    }

    if (rankRatio < 0.82) {
      return "light";
    }

    return "passive";
  }

  function userIdentityForIndex(company, index) {
    const longNameOverrides = [
      { name: "Alexandria Montgomery-Wellington", emailName: "alexandria.montgomery-wellington" },
      { name: "Christopher Jonathan Van Der Meer", emailName: "christopher.jonathan.van-der-meer" }
    ];
    const override = longNameOverrides[index];

    if (override) {
      return override;
    }

    const firstNameIndex = index % firstNames.length;
    const nameCycle = Math.floor(index / firstNames.length);
    const generation = Math.floor(index / (firstNames.length * lastNames.length));
    const firstName = firstNames[firstNameIndex];
    const lastName = lastNames[(firstNameIndex + nameCycle + company.id.length) % lastNames.length];
    const suffix = generation > 0 ? ` ${generation + 1}` : "";
    const emailSuffix = generation > 0 ? `-${generation + 1}` : "";

    return {
      name: `${firstName} ${lastName}${suffix}`,
      emailName: `${slugify(firstName)}.${slugify(lastName)}${emailSuffix}`
    };
  }

  function buildUserRows(company, data, topPages) {
    const totalKnownUsers = Math.max(company.totalKnownUsers, company.activeUsers);
    const activeLimit = Math.min(totalKnownUsers, company.activeUsers);
    const domain = company.domain || `${slugify(company.name)}.example`;
    const areas = getCompanyAreas(company, data.productAreas || []);
    const areaWeights = areaWeightLookup(company, data);

    return Array.from({ length: totalKnownUsers }, (_, index) => {
      const status = userStatusForIndex(company, index, activeLimit);
      const isActive = index < activeLimit;
      const userShare = isActive ? Math.max(0.08, 1.4 - index * 0.055) : 0;
      const activeShareTotal = sum(Array.from({ length: activeLimit }, (_, activeIndex) => Math.max(0.08, 1.4 - activeIndex * 0.055)), (value) => value) || 1;
      const engagedSeconds = isActive ? Math.round((company.engagedSeconds * userShare) / activeShareTotal) : 0;
      const visits = isActive ? Math.max(1, Math.round((company.visits * userShare) / activeShareTotal)) : 0;
      const userEngagedDelta = isActive
        ? company.engagedDeltaPct + deterministicNumber(`${company.id}:user:${index}:engaged-delta`, -12, 12) + (status === "passive" ? -18 : 0) + (status === "power" ? 12 : status === "healthy" ? 6 : 0)
        : 0;
      const userVisitsDelta = isActive
        ? company.visitsDeltaPct + deterministicNumber(`${company.id}:user:${index}:visits-delta`, -10, 10) + (status === "passive" ? -16 : 0) + (status === "power" ? 10 : status === "healthy" ? 5 : 0)
        : 0;
      const previousEngagedSeconds = isActive ? previousPeriodValue(engagedSeconds, userEngagedDelta, "%") : 0;
      const previousVisits = isActive ? previousPeriodValue(visits, userVisitsDelta, "%") : 0;
      const sessionDepthTarget = {
        power: 540 + deterministicNumber(`${company.id}:user:${index}:session-depth`, 0, 240),
        healthy: 360 + deterministicNumber(`${company.id}:user:${index}:session-depth`, 0, 210),
        light: 180 + deterministicNumber(`${company.id}:user:${index}:session-depth`, 0, 150),
        passive: 80 + deterministicNumber(`${company.id}:user:${index}:session-depth`, 0, 120),
        dropped: 0
      }[status] || 240;
      const sessionsCount = isActive
        ? Math.max(1, Math.min(visits, Math.round(engagedSeconds / Math.max(sessionDepthTarget, 1))))
        : 0;
      const activeDays = isActive ? Math.max(1, Math.round((daysFromPeriod(data.period) * Math.min(0.82, 0.12 + userShare / 3)) / (status === "passive" ? 1.8 : status === "light" ? 1.35 : 1))) : 0;
      const topArea = areas[index % Math.max(areas.length, 1)] || company.topProductArea || "Core product";
      const productAreaAdoption = (data.productAreas || []).map((area, areaIndex) => {
        const areaPercent = areaWeights.get(area) || 0;
        const used = isActive && (areas.includes(area) && (area === topArea || (index + areaIndex) % 3 !== 1));
        const areaEngaged = used ? Math.round(engagedSeconds * Math.max(0.12, area === topArea ? 0.58 : areaPercent)) : 0;

        return {
          productArea: area,
          used,
          engagedSeconds: areaEngaged,
          visits: areaEngaged ? Math.max(1, Math.round(visits * (areaEngaged / Math.max(engagedSeconds, 1)))) : 0,
          activeUsers: used ? 1 : 0,
          pagesUsed: used ? Math.max(1, topPages.filter((page) => page.productArea === area).length) : 0
        };
      });
      const identity = userIdentityForIndex(company, index);
      const lastActiveDays = isActive
        ? status === "passive"
          ? deterministicNumber(`${company.id}:user:${index}:risk-last`, 4, Math.min(21, daysFromPeriod(data.period)))
          : deterministicNumber(`${company.id}:user:${index}:last`, 0, Math.min(6, daysFromPeriod(data.period)))
        : deterministicNumber(`${company.id}:user:${index}:dropped-last`, daysFromPeriod(data.period) + 3, daysFromPeriod(data.period) + 90);

      return {
        id: `${company.id}-user-${index + 1}`,
        name: identity.name,
        email: `${identity.emailName}@${domain}`,
        status,
        lastActiveDays,
        lastActive: lastActiveDays === 0 ? "Today" : `${lastActiveDays}d ago`,
        activeDays,
        engagedSeconds,
        engagedDeltaPct: calculateMetricDelta(engagedSeconds, previousEngagedSeconds, "percent").value || 0,
        sessionsCount,
        visits,
        visitsDeltaPct: calculateMetricDelta(visits, previousVisits, "percent").value || 0,
        interactionPct: visits ? clamp(company.interactionPct + deterministicNumber(`${company.id}:user:${index}:interaction`, -12, 10), 0, 100) : 0,
        productAreaAdoption,
        topArea: isActive ? topArea : ""
      };
    }).sort((a, b) => b.engagedSeconds - a.engagedSeconds || a.name.localeCompare(b.name));
  }

  function buildCompanyHealthDistribution(users) {
    const counts = new Map();
    const total = Array.isArray(users) ? users.length : 0;

    if (!total) {
      return [];
    }

    users.forEach((user) => {
      const status = user.status || "healthy";
      counts.set(status, (counts.get(status) || 0) + 1);
    });

    return userHealthDistributionOrder
      .concat(Array.from(counts.keys()).filter((status) => !userHealthDistributionOrder.includes(status)).sort())
      .filter((status, index, statuses) => statuses.indexOf(status) === index)
      .map((status) => {
        const count = counts.get(status) || 0;

        return {
          status,
          label: userHealthDistributionLabels[status] || status,
          count,
          pct: Math.round((count / total) * 1000) / 10
        };
      })
      .filter((item) => item.count > 0);
  }

  function buildHealthSummary(company, data, peerComparison) {
    if (!company.visits || !company.activeUsers) {
      return "Not enough activity in this period to generate a reliable company insight.";
    }

    const missingAreas = (data.productAreas || []).filter((area) => !(company.productAreaDistribution || []).some((item) => item.productArea === area && item.percent > 1));
    const topAreas = (company.productAreaDistribution || []).slice(0, 2).map((item) => item.productArea).filter(Boolean);
    const peerMedian = peerComparison.rows.find((row) => row.rowType === "median");

    if (company.status === "at_risk" || company.engagedDeltaPct < -30) {
      return `Engagement is declining, with usage concentrated in ${topAreas.join(" and ") || company.topProductArea}.`;
    }

    if (peerMedian && company.productAreasUsed < peerMedian.productAreasUsed && missingAreas.length) {
      return `Strong engagement, but adoption is concentrated in ${topAreas.join(" and ") || company.topProductArea}. ${missingAreas.slice(0, 2).join(" and ")} are underused.`;
    }

    if (company.status === "power" || company.productAreasUsed >= 6) {
      return "Broad adoption and strong engagement indicate a healthy expansion-ready account.";
    }

    if (company.productAreasUsed <= 2) {
      return `Usage is concentrated in ${topAreas[0] || company.topProductArea}; adjacent product areas are underused.`;
    }

    return `Consistent engagement across ${company.productAreasUsed} product areas, with ${topAreas.join(" and ")} leading usage.`;
  }

  function buildRecommendedActions(company, data, peerComparison, users) {
    const actions = [];
    const peerMedian = peerComparison.rows.find((row) => row.rowType === "median");
    const passiveUsers = users.filter((user) => user.status === "passive");
    const topArea = company.productAreaDistribution?.[0]?.productArea || company.topProductArea;
    const topAreaShare = company.productAreaDistribution?.[0]?.percent || 0;
    const productAreas = data.productAreas || [];
    const underusedAreas = productAreas.filter((area) => {
      const currentPercent = company.productAreaDistribution.find((item) => item.productArea === area)?.percent || 0;

      return currentPercent <= 2;
    });
    const championUsers = users.filter((user) => user.engagedSeconds > 0 && ["power", "healthy"].includes(user.status));
    const durationMinutes = (seconds) => `${Math.max(1, Math.round((Number(seconds) || 0) / 60))}m`;
    const gapLabel = (count) => `${count} ${count === 1 ? "gap" : "gaps"}`;
    const missingPeerArea = peerMedian
      ? productAreas.find((area) => {
          const currentPercent = company.productAreaDistribution.find((item) => item.productArea === area)?.percent || 0;
          const peerPercent = peerMedian.productAreaDistribution.find((item) => item.productArea === area)?.percent || 0;

          return currentPercent <= 2 && peerPercent >= 8;
        })
      : null;

    if (company.productAreasUsed <= 3) {
      actions.push({
        type: "Adoption gap",
        priority: "warning",
        title: "Review underused areas",
        reason: underusedAreas.length
          ? `${underusedAreas.slice(0, 2).join(" and ")} ${underusedAreas.length === 1 ? "is" : "are"} lightly used or unused.`
          : `${company.productAreasUsed} of ${productAreas.length} product areas are active in this period.`,
        metric: `${company.productAreasUsed} areas`,
        metricLabel: gapLabel(Math.max(0, productAreas.length - company.productAreasUsed)),
        supportingMetrics: [],
        ctaLabel: "Review areas",
        targetAnchor: "area-usage"
      });
    }

    if (missingPeerArea) {
      actions.push({
        type: "Peer gap",
        priority: "warning",
        title: "Investigate peer gap",
        reason: `${missingPeerArea} is used more often by similar companies.`,
        metric: "Below peers",
        metricLabel: "Below peers",
        supportingMetrics: [],
        ctaLabel: "Compare peers",
        targetAnchor: "peer-comparison"
      });
    }

    if (passiveUsers.length) {
      actions.push({
        type: "Churn risk",
        priority: "risk",
        title: "Check passive users",
        reason: "Several users show recent activity drops or stale activity.",
        metric: `${passiveUsers.length} users`,
        metricLabel: `${passiveUsers.length} passive`,
        supportingMetrics: [`${users.filter((user) => user.status === "dropped").length} dropped`],
        ctaLabel: "Open users",
        targetAnchor: "company-users"
      });
    }

    if (topAreaShare >= 48) {
      actions.push({
        type: "Adoption gap",
        priority: "warning",
        title: "Review underused areas",
        reason: `Usage is concentrated in ${topArea}.`,
        metric: `${Math.round(topAreaShare)}% share`,
        metricLabel: `${Math.round(topAreaShare)}% share`,
        supportingMetrics: underusedAreas.length ? [gapLabel(underusedAreas.length)] : [],
        ctaLabel: "Review areas",
        targetAnchor: "area-usage"
      });
    }

    if (company.avgEngagedSecondsPerUser >= (peerMedian?.avgEngagedSecondsPerUser || 0) * 1.12 && company.productAreasUsed >= (peerMedian?.productAreasUsed || 0)) {
      actions.push({
        type: "Expansion",
        priority: "opportunity",
        title: "Expand this account",
        reason: "Engagement and adoption are above the peer baseline.",
        metric: "Above median",
        metricLabel: peerMedian
          ? `${durationMinutes(company.avgEngagedSecondsPerUser)} engaged/user`
          : "Above median",
        supportingMetrics: peerMedian
          ? [`${durationMinutes(peerMedian.avgEngagedSecondsPerUser)} peer median`]
          : [],
        ctaLabel: "Compare peers",
        targetAnchor: "peer-comparison"
      });
    }

    if (!actions.length) {
      actions.push({
        type: "Health watch",
        priority: "neutral",
        title: "Monitor next period",
        reason: "This company is close to peer benchmarks across engagement and breadth.",
        metric: "Stable",
        metricLabel: "Stable",
        supportingMetrics: [`${company.productAreasUsed} areas used`],
        ctaLabel: "Compare peers",
        targetAnchor: "peer-comparison"
      });
    }

    [
      {
        type: "Adoption gap",
        priority: "neutral",
        title: "Review underused areas",
        reason: underusedAreas.length
          ? `${underusedAreas.slice(0, 2).join(" and ")} ${underusedAreas.length === 1 ? "is" : "are"} lightly used or unused.`
          : "Look for areas with low or missing adoption before the next account review.",
        metric: gapLabel(Math.max(0, productAreas.length - company.productAreasUsed)),
        metricLabel: gapLabel(Math.max(0, productAreas.length - company.productAreasUsed)),
        supportingMetrics: [],
        ctaLabel: "Review areas",
        targetAnchor: "area-usage"
      },
      {
        type: "Champion users",
        priority: "opportunity",
        title: "Start from active champions",
        reason: "Several users show strong recent engagement and can drive expansion.",
        metric: `${company.activeUsers} active`,
        metricLabel: `${company.activeUsers} active`,
        supportingMetrics: [`${Math.min(championUsers.length, Math.max(1, Math.round(company.activeUsers * 0.2)))} champions`],
        ctaLabel: "View users",
        targetAnchor: "company-users"
      },
      {
        type: company.status === "at_risk" ? "Churn risk" : "Health watch",
        priority: company.status === "at_risk" ? "risk" : "neutral",
        title: company.status === "at_risk" ? "Check passive users" : "Monitor next period",
        reason: "Recheck engagement, breadth, and passive users after the next period closes.",
        metric: company.status === "at_risk" ? "Risk watch" : "Health watch",
        metricLabel: company.status === "at_risk" ? "Risk watch" : "Health watch",
        supportingMetrics: [`Last active: ${company.lastActiveAt || "Unknown"}`],
        ctaLabel: "Open users",
        targetAnchor: "company-users"
      }
    ].forEach((fallbackAction) => {
      if (actions.length >= 3 || actions.some((action) => action.title === fallbackAction.title)) {
        return;
      }

      actions.push(fallbackAction);
    });

    return actions.slice(0, 5);
  }

  function buildCompanyDetailsData(data, companyId, options = {}) {
    const period = calculateCompanyDetailsPeriod(data?.period || DEFAULT_PERIOD, options.endDate || data?.endDate || DEFAULT_END_DATE);
    const sourceCompany = (data?.companies || []).find((row) => row.id === companyId);

    if (!sourceCompany) {
      return null;
    }

    const company = enhanceCompany(sourceCompany, data);
    const peerCompanies = selectSimilarCompanies(data.companies || [], company.id, 10, data);
    const topPages = buildPageUsage(company, data, period);
    const areaTreemap = buildAreaTreemap(topPages, company);
    const adoptionBreadthSeries = buildAdoptionBreadthSeries(topPages, data, period, company);
    const metricCards = buildMetricCards(company, peerCompanies, period);
    const peerComparison = buildPeerComparison(company, peerCompanies, data);
    const users = buildUserRows(company, { ...data, period: period.key }, topPages);
    const companyHealthDistribution = buildCompanyHealthDistribution(users);
    const recommendedActions = buildRecommendedActions(company, data, peerComparison, users);
    const healthSummary = buildHealthSummary(company, data, peerComparison);

    return {
      company,
      period,
      healthSummary,
      metricCards,
      areaTreemap,
      adoptionBreadthSeries,
      topPages: topPages.slice(0, 15),
      allTopPages: topPages,
      peerComparison,
      companyHealthDistribution,
      users,
      recommendedActions
    };
  }

  return {
    PERIOD_OPTIONS,
    DEFAULT_PERIOD,
    DEFAULT_END_DATE,
    pageCatalog,
    coerceCompanyDetailPeriod,
    calculateCompanyDetailsPeriod,
    previousPeriodValue,
    median,
    selectSimilarCompanies,
    buildCompanyDetailsData
  };
});
