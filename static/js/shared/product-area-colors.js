(function mountHymetryProductAreaColors(globalScope) {
  const fallbackPalette = [
    "#4269D0",
    "#EFB118",
    "#FF725C",
    "#6CC5B0",
    "#3CA951",
    "#FF8AB7",
    "#A463F2",
    "#97BBF5",
    "#9C6B4E",
    "#E5E7EB"
  ];

  const knownProductAreaColors = {
    "core product": "#4269D0",
    billing: "#EFB118",
    developer: "#3CA951",
    development: "#3CA951",
    administration: "#6CC5B0",
    admin: "#6CC5B0",
    analytics: "#A463F2",
    reporting: "#A463F2",
    reports: "#A463F2",
    collaboration: "#97BBF5",
    integrations: "#97BBF5",
    export: "#FF8AB7",
    "team permissions": "#9C6B4E",
    permissions: "#9C6B4E",
    settings: "#E5E7EB"
  };

  function normalizeProductAreaName(area) {
    if (area && typeof area === "object") {
      return String(
        area.name ||
        area.productArea ||
        area.productAreaName ||
        area.product_area_name ||
        area.product_area ||
        area.key ||
        area.slug ||
        ""
      ).trim() || "Unassigned";
    }

    return String(area || "").trim() || "Unassigned";
  }

  function normalizeKey(area) {
    return normalizeProductAreaName(area).toLowerCase().replace(/\s+/g, " ").trim();
  }

  function colorCandidate(area, explicitColor = "") {
    if (explicitColor) {
      return String(explicitColor).trim();
    }

    if (!area || typeof area !== "object") {
      return "";
    }

    return String(
      area.color ||
      area.productAreaColor ||
      area.product_area_color ||
      area.areaColor ||
      ""
    ).trim();
  }

  const supportedHexColorPattern = /^#[0-9a-f]{6}$/i;
  const supportedColorTokenPattern = /^[a-z0-9_-]+$/i;

  function supportedHexColor(value) {
    const color = String(value || "").trim();
    return supportedHexColorPattern.test(color) ? color : "";
  }

  function tokenFromCssVariable(value) {
    const match = String(value || "").trim().match(/^var\(--color-([a-z0-9_-]+)\)$/i);
    return match ? match[1] : "";
  }

  function resolveColorValue(value, resolveColor) {
    const raw = String(value || "").trim();

    if (!raw) {
      return "";
    }

    const hexColor = supportedHexColor(raw);
    if (hexColor) {
      return hexColor;
    }

    const token = tokenFromCssVariable(raw) || (supportedColorTokenPattern.test(raw) ? raw : "");
    if (!token) {
      return "";
    }

    return supportedHexColor(resolveColor(token));
  }

  function createResolver(options = {}) {
    const resolveColor = typeof options.resolveColor === "function" ? options.resolveColor : (value) => value;
    const palette = Array.isArray(options.palette) && options.palette.length ? options.palette : fallbackPalette;
    let names = [];
    let colorByName = new Map();
    let explicitColorNames = new Set();

    function reset() {
      names = [];
      colorByName = new Map();
      explicitColorNames = new Set();
    }

    function add(area, explicitColor = "") {
      const name = normalizeProductAreaName(area);

      if (!name) {
        return;
      }

      if (!names.includes(name)) {
        names.push(name);
      }

      const color = resolveColorValue(colorCandidate(area, explicitColor), resolveColor);
      if (color && !explicitColorNames.has(name)) {
        colorByName.set(name, color);
        explicitColorNames.add(name);
      }
    }

    function addMany(areas) {
      (Array.isArray(areas) ? areas : []).forEach((area) => add(area));
    }

    function finalize() {
      names.forEach((name, index) => {
        if (colorByName.has(name)) {
          return;
        }

        const key = normalizeKey(name);
        const fallback = knownProductAreaColors[key] || palette[index % palette.length] || fallbackPalette[0];
        colorByName.set(name, resolveColorValue(fallback, resolveColor));
      });
    }

    function color(area, explicitColor = "") {
      const name = normalizeProductAreaName(area);
      add(area, explicitColor);
      finalize();

      return colorByName.get(name) || resolveColorValue(palette[0] || fallbackPalette[0], resolveColor);
    }

    return {
      reset,
      add,
      addMany,
      finalize,
      color,
      normalizeProductAreaName
    };
  }

  globalScope.HymetryProductAreaColors = {
    fallbackPalette,
    knownProductAreaColors,
    normalizeProductAreaName,
    createResolver
  };
})(window);
