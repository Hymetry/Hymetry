(function mountHymetryAnalyticsTooltips(root, factory) {
  const helpers = factory(root);

  if (typeof module === "object" && module.exports) {
    module.exports = helpers;
  }

  root.HymetryAnalyticsTooltips = helpers;
})(typeof globalThis !== "undefined" ? globalThis : this, function createHymetryAnalyticsTooltips(globalScope) {
  "use strict";

  const fontFamily = "Inter, ui-sans-serif, system-ui, sans-serif";
  const textColor = "#334155";
  const borderColor = "#e2e8f0";
  const backgroundColor = "#ffffff";
  const floatingTriggerSelector = ".metric-header-tooltip";
  let floatingControllerMounted = false;

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function safeMarkerColor(value) {
    const color = String(value || "").trim();
    const supported = [
      /^#[0-9a-f]{3,8}$/i,
      /^rgba?\([\d\s.,%+-]+\)$/i,
      /^hsla?\([\d\s.,%+-]+\)$/i,
      /^okl(?:ch|ab)\([\d\s.,%+\/-]+\)$/i,
      /^var\(--[a-z0-9_-]+\)$/i
    ];

    return supported.some((pattern) => pattern.test(color)) ? color : "#94a3b8";
  }

  function markerMarkup(marker) {
    if (!marker) {
      return "";
    }

    const options = typeof marker === "string" ? { color: marker } : marker;
    const type = options.type === "line" ? "line" : "dot";
    const classes = ["analytics-tooltip__marker", `analytics-tooltip__marker--${type}`];

    if (options.dashed) {
      classes.push("analytics-tooltip__marker--dashed");
    }

    return `<span class="${classes.join(" ")}" style="--analytics-tooltip-marker:${safeMarkerColor(options.color)}" aria-hidden="true"></span>`;
  }

  function rowMarkup(row) {
    const normalized = row && typeof row === "object" ? row : { label: "", value: row };
    const marker = markerMarkup(normalized.marker);
    const markerClass = marker ? " analytics-tooltip__row--marker" : "";
    const hasSecondaryValue = normalized.secondaryValue !== undefined
      && normalized.secondaryValue !== null
      && normalized.secondaryValue !== "";
    const secondaryValueClass = hasSecondaryValue ? " analytics-tooltip__row--three-column" : "";
    const secondaryValue = hasSecondaryValue
      ? `<strong class="analytics-tooltip__secondary-value">${escapeHtml(normalized.secondaryValue)}</strong>`
      : "";

    return `
      <span class="analytics-tooltip__row${markerClass}${secondaryValueClass}">
        ${marker}
        <span class="analytics-tooltip__label">${escapeHtml(normalized.label)}</span>
        <strong class="analytics-tooltip__value">${escapeHtml(normalized.value)}</strong>
        ${secondaryValue}
      </span>
    `;
  }

  function rowsMarkup(rows) {
    const normalizedRows = Array.isArray(rows) ? rows : [];
    const hasSecondaryValues = normalizedRows.some((row) => (
      row?.secondaryValue !== undefined
      && row?.secondaryValue !== null
      && row?.secondaryValue !== ""
    ));
    const hasMarkers = normalizedRows.some((row) => Boolean(row?.marker));
    const classes = ["analytics-tooltip__rows"];

    if (hasSecondaryValues) {
      classes.push("analytics-tooltip__rows--three-column");
    }
    if (hasMarkers) {
      classes.push("analytics-tooltip__rows--with-markers");
    }

    return `<span class="${classes.join(" ")}">${normalizedRows.map(rowMarkup).join("")}</span>`;
  }

  function render(options = {}) {
    const sections = Array.isArray(options.sections) && options.sections.length
      ? options.sections
      : [{ rows: options.rows || [] }];
    const populatedSections = sections.filter((section) => (
      (Array.isArray(section?.rows) && section.rows.length)
      || (section?.title !== undefined && section?.title !== null && section?.title !== "")
    ));
    const tableClass = populatedSections.length ? " analytics-tooltip--table" : "";
    const title = options.title === undefined || options.title === null || options.title === ""
      ? ""
      : `<span class="analytics-tooltip__title">${escapeHtml(options.title)}</span>`;
    const body = populatedSections
      .map((section, index) => {
        const sectionTitle = section?.title === undefined || section?.title === null || section?.title === ""
          ? ""
          : `<span class="analytics-tooltip__section-title">${escapeHtml(section.title)}</span>`;
        const sectionRows = Array.isArray(section?.rows) && section.rows.length
          ? rowsMarkup(section.rows)
          : "";
        return `${index > 0 ? '<span class="analytics-tooltip__divider"></span>' : ""}${sectionTitle}${sectionRows}`;
      })
      .join("");

    return `<span class="analytics-tooltip${tableClass}">${title}${body}</span>`;
  }

  function text(rows) {
    return (Array.isArray(rows) ? rows : [])
      .map((row) => {
        const secondaryValue = row?.secondaryValue === undefined || row?.secondaryValue === null || row?.secondaryValue === ""
          ? ""
          : `, ${String(row.secondaryValue).trim()}`;
        return `${String(row?.label || "").trim()}: ${String(row?.value ?? "").trim()}${secondaryValue}`;
      })
      .join(". ");
  }

  function echarts(overrides = {}) {
    const baseExtraCss = "border-radius:6px;box-shadow:0 10px 24px rgba(15,23,42,.12);color:#334155;font-size:14px;line-height:1.35;white-space:normal;";

    return {
      renderMode: "html",
      backgroundColor,
      borderColor,
      borderWidth: 1,
      padding: [8, 10],
      ...overrides,
      textStyle: {
        fontFamily,
        fontSize: 14,
        color: textColor,
        fontWeight: 400,
        ...(overrides.textStyle || {})
      },
      extraCssText: `${baseExtraCss}${overrides.extraCssText || ""}`
    };
  }

  function tooltipKind(trigger) {
    if (trigger.dataset.tooltipKind) {
      return trigger.dataset.tooltipKind;
    }
    if (trigger.classList.contains("two-way-movement-cell")) {
      return "two-way-movement";
    }
    if (trigger.classList.contains("companies-area-mix")) {
      return "area-mix";
    }
    if (trigger.classList.contains("companies-adoption-cell")) {
      return "adoption-cell";
    }
    if (trigger.closest(".companies-matrix-heading")) {
      return "matrix-heading";
    }
    if (trigger.closest("thead")) {
      return "table-header";
    }
    return "delta";
  }

  function floatingTooltipLeft({
    triggerRect = {},
    tooltipWidth = 0,
    viewportWidth = 0,
    pointerX,
    margin = 8
  } = {}) {
    const numericPointerX = Number(pointerX);
    const hasPointerAnchor = pointerX !== undefined
      && pointerX !== null
      && Number.isFinite(numericPointerX);
    const anchorX = hasPointerAnchor
      ? numericPointerX
      : Number(triggerRect.left || 0) + Number(triggerRect.width || 0) / 2;
    const idealLeft = anchorX - Number(tooltipWidth || 0) / 2;
    const maximumLeft = Math.max(
      margin,
      Number(viewportWidth || 0) - Number(tooltipWidth || 0) - margin
    );

    return Math.min(Math.max(margin, idealLeft), maximumLeft);
  }

  function mountFloatingTooltips() {
    const documentObject = globalScope.document;

    if (floatingControllerMounted || !documentObject?.body) {
      return;
    }

    floatingControllerMounted = true;
    documentObject.body.classList.add("metric-floating-tooltips-enabled");

    const floatingTooltip = documentObject.createElement("div");
    floatingTooltip.className = "metric-header-tooltip__content metric-floating-tooltip";
    floatingTooltip.dataset.visible = "false";
    floatingTooltip.setAttribute("aria-hidden", "true");
    floatingTooltip.setAttribute("role", "tooltip");
    documentObject.body.appendChild(floatingTooltip);

    const requestFrame = globalScope.requestAnimationFrame || ((callback) => globalScope.setTimeout(callback, 0));
    const verticalGap = 8;
    let activeTrigger = null;
    let activePointerX = null;
    let positionAnimationFrame = 0;

    function getTrigger(target) {
      if (!target || typeof target.closest !== "function") {
        return null;
      }
      return target.closest(floatingTriggerSelector);
    }

    function setVisible(isVisible) {
      floatingTooltip.dataset.visible = String(isVisible);
      floatingTooltip.setAttribute("aria-hidden", String(!isVisible));
    }

    function hide(trigger = activeTrigger) {
      if (trigger && activeTrigger && trigger !== activeTrigger) {
        return;
      }
      activeTrigger = null;
      activePointerX = null;
      setVisible(false);
    }

    function updatePosition() {
      positionAnimationFrame = 0;
      if (!activeTrigger || !activeTrigger.isConnected) {
        hide();
        return;
      }

      const triggerRect = activeTrigger.getBoundingClientRect();
      const tooltipRect = floatingTooltip.getBoundingClientRect();
      const viewportWidth = documentObject.documentElement.clientWidth || globalScope.innerWidth || 0;
      const viewportHeight = documentObject.documentElement.clientHeight || globalScope.innerHeight || 0;
      const margin = 8;

      if (
        triggerRect.bottom < 0
        || triggerRect.top > viewportHeight
        || triggerRect.right < 0
        || triggerRect.left > viewportWidth
      ) {
        hide();
        return;
      }

      const shouldPlaceAbove = triggerRect.bottom + verticalGap + tooltipRect.height > viewportHeight - margin
        && triggerRect.top - verticalGap - tooltipRect.height >= margin;
      const desiredTop = shouldPlaceAbove
        ? triggerRect.top - tooltipRect.height - verticalGap
        : triggerRect.bottom + verticalGap;
      const maxTop = Math.max(margin, viewportHeight - tooltipRect.height - margin);
      const left = floatingTooltipLeft({
        triggerRect,
        tooltipWidth: tooltipRect.width,
        viewportWidth,
        pointerX: activeTrigger.dataset.tooltipAnchor === "pointer"
          ? activePointerX
          : null,
        margin
      });
      const top = Math.min(Math.max(desiredTop, margin), maxTop);

      floatingTooltip.dataset.placement = shouldPlaceAbove ? "top" : "bottom";
      floatingTooltip.style.left = `${Math.round(left)}px`;
      floatingTooltip.style.top = `${Math.round(top)}px`;
    }

    function queuePosition() {
      if (!positionAnimationFrame) {
        positionAnimationFrame = requestFrame(updatePosition);
      }
    }

    function show(trigger, { pointerX } = {}) {
      const source = trigger?.querySelector(":scope > .metric-header-tooltip__content")
        || trigger?.querySelector(".metric-header-tooltip__content");

      if (!source) {
        return;
      }

      activeTrigger = trigger;
      const numericPointerX = Number(pointerX);
      activePointerX = trigger.dataset.tooltipAnchor === "pointer"
        && pointerX !== undefined
        && pointerX !== null
        && Number.isFinite(numericPointerX)
        ? numericPointerX
        : null;
      floatingTooltip.innerHTML = source.innerHTML;
      floatingTooltip.dataset.tooltipKind = tooltipKind(trigger);
      const areaLabelWidth = trigger.style.getPropertyValue("--area-tooltip-label-width");
      if (areaLabelWidth) {
        floatingTooltip.style.setProperty("--area-tooltip-label-width", areaLabelWidth);
      } else {
        floatingTooltip.style.removeProperty("--area-tooltip-label-width");
      }
      floatingTooltip.style.left = "0px";
      floatingTooltip.style.top = "0px";
      setVisible(false);
      updatePosition();
      setVisible(true);
    }

    documentObject.addEventListener("pointerover", (event) => {
      const trigger = getTrigger(event.target);
      if (!trigger || trigger.contains(event.relatedTarget)) {
        return;
      }
      show(trigger, { pointerX: event.clientX });
    });
    documentObject.addEventListener("pointermove", (event) => {
      if (activeTrigger?.dataset.tooltipAnchor !== "pointer") {
        return;
      }
      const trigger = getTrigger(event.target);
      if (
        trigger !== activeTrigger
        || !Number.isFinite(Number(event.clientX))
      ) {
        return;
      }
      activePointerX = Number(event.clientX);
      queuePosition();
    });
    documentObject.addEventListener("pointerout", (event) => {
      const trigger = getTrigger(event.target);
      if (!trigger || trigger.contains(event.relatedTarget)) {
        return;
      }
      hide(trigger);
    });
    documentObject.addEventListener("focusin", (event) => {
      const trigger = getTrigger(event.target);
      if (trigger) {
        show(trigger);
      }
    });
    documentObject.addEventListener("focusout", (event) => {
      const trigger = getTrigger(event.target);
      if (!trigger || trigger.contains(event.relatedTarget)) {
        return;
      }
      hide(trigger);
    });
    documentObject.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        hide();
      }
    });
    globalScope.addEventListener?.("resize", queuePosition);
    globalScope.addEventListener?.("scroll", queuePosition, true);
  }

  if (globalScope.document) {
    if (globalScope.document.readyState === "loading") {
      globalScope.document.addEventListener("DOMContentLoaded", mountFloatingTooltips, { once: true });
    } else {
      mountFloatingTooltips();
    }
  }

  return {
    echarts,
    escapeHtml,
    markerMarkup,
    mountFloatingTooltips,
    floatingTooltipLeft,
    render,
    rowMarkup,
    rowsMarkup,
    text
  };
});
