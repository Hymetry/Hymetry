(function mountHymetryAnalyticsStatusColors(globalScope) {
  const companyStatusOrder = ["power", "healthy", "activated", "new", "reactivated", "at_risk", "dormant"];
  const userStatusOrder = ["power", "healthy", "light", "passive", "dropped"];

  const companyStatusAliases = {
    active: "activated",
    "at-risk": "at_risk",
    atrisk: "at_risk",
    risk: "at_risk",
    dropped: "dormant"
  };

  const userStatusAliases = {
    active: "healthy",
    "at-risk": "light",
    at_risk: "light",
    atrisk: "light",
    risk: "light"
  };

  const companyStatusMeta = {
    new: {
      key: "new",
      label: "New",
      color: "c-light-blue",
      badge: "companies-badge--light-blue",
      definition: "First seen in the selected period."
    },
    activated: {
      key: "activated",
      label: "Activated",
      color: "c-teal",
      badge: "companies-badge--teal",
      definition: "Recently reached activation criteria."
    },
    reactivated: {
      key: "reactivated",
      label: "Reactivated",
      color: "c-blue",
      badge: "companies-badge--blue",
      definition: "Returned after a quiet period."
    },
    healthy: {
      key: "healthy",
      label: "Healthy",
      color: "c-blue",
      badge: "companies-badge--blue",
      definition: "Consistent account-level engagement."
    },
    power: {
      key: "power",
      label: "Power",
      color: "c-green",
      badge: "companies-badge--green",
      definition: "High breadth and depth of adoption."
    },
    at_risk: {
      key: "at_risk",
      label: "At risk",
      color: "c-orange",
      badge: "companies-badge--orange",
      definition: "Meaningful usage drop or stale activity."
    },
    dormant: {
      key: "dormant",
      label: "Dormant",
      color: "c-red",
      badge: "companies-badge--red",
      definition: "Little or no activity in this period."
    }
  };

  const userStatusMeta = {
    power: {
      key: "power",
      label: "Power",
      color: "c-green",
      usersBadge: "users-badge--green",
      companiesBadge: "companies-badge--green",
      definition: "High engagement, repeated usage, and broad product-area usage."
    },
    healthy: {
      key: "healthy",
      label: "Healthy",
      color: "c-blue",
      usersBadge: "users-badge--blue",
      companiesBadge: "companies-badge--blue",
      definition: "Regular usage with meaningful engagement."
    },
    light: {
      key: "light",
      label: "Light",
      color: "c-orange",
      usersBadge: "users-badge--amber",
      companiesBadge: "companies-badge--orange",
      definition: "Some usage, but limited depth or frequency."
    },
    passive: {
      key: "passive",
      label: "Passive",
      color: "c-brown",
      usersBadge: "users-badge--brown",
      companiesBadge: "companies-badge--brown",
      definition: "Very low interaction or recent decline."
    },
    dropped: {
      key: "dropped",
      label: "Dropped",
      color: "c-red",
      usersBadge: "users-badge--red",
      companiesBadge: "companies-badge--red",
      definition: "Previously known user with no or almost no recent activity."
    }
  };

  function normalizeStatusKey(status, aliases) {
    const raw = String(status || "").trim();
    const key = raw.replace(/\s+/g, "_").replace(/-/g, "_").toLowerCase();

    return aliases[key] || key;
  }

  function unknownStatusMeta(status, badgePrefix) {
    const label = String(status || "Unknown").trim() || "Unknown";
    const badge = badgePrefix === "users" ? "users-badge--slate" : "companies-badge--gray";

    return {
      key: "unknown",
      label,
      color: "slate-400",
      badge,
      sort: 99,
      definition: ""
    };
  }

  function normalizeCompanyStatus(status) {
    return normalizeStatusKey(status, companyStatusAliases);
  }

  function normalizeUserStatus(status) {
    return normalizeStatusKey(status, userStatusAliases);
  }

  function getCompanyStatusMeta(status) {
    const key = normalizeCompanyStatus(status);
    const meta = companyStatusMeta[key];

    if (!meta) {
      return unknownStatusMeta(status, "companies");
    }

    return {
      ...meta,
      sort: companyStatusOrder.indexOf(key)
    };
  }

  function getUserStatusMeta(status, badgePrefix = "users") {
    const key = normalizeUserStatus(status);
    const meta = userStatusMeta[key];

    if (!meta) {
      return unknownStatusMeta(status, badgePrefix);
    }

    return {
      ...meta,
      badge: badgePrefix === "companies" ? meta.companiesBadge : meta.usersBadge,
      sort: userStatusOrder.indexOf(key)
    };
  }

  function metaMap(keys, getter) {
    return keys.reduce((lookup, key) => {
      const meta = getter(key);
      lookup[key] = meta;
      return lookup;
    }, {});
  }

  function sortMap(keys) {
    return keys.reduce((lookup, key, index) => {
      lookup[key] = index;
      return lookup;
    }, {});
  }

  globalScope.HymetryAnalyticsStatusColors = {
    companyStatusOrder,
    userStatusOrder,
    userStatusOrderLabels: userStatusOrder.map((key) => userStatusMeta[key].label),
    companyStatusSort: sortMap(companyStatusOrder),
    userHealthSegments: userStatusOrder.map((key) => [key, userStatusMeta[key].label, userStatusMeta[key].color]),
    companyStatusMeta: metaMap(companyStatusOrder, getCompanyStatusMeta),
    userStatusMeta: metaMap(userStatusOrder, (key) => getUserStatusMeta(key, "users")),
    companyDetailUserStatusMeta: metaMap(userStatusOrder, (key) => getUserStatusMeta(key, "companies")),
    normalizeCompanyStatus,
    normalizeUserStatus,
    getCompanyStatusMeta,
    getUserStatusMeta
  };
})(window);
