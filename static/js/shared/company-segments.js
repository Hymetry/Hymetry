(function (globalObject, factory) {
  "use strict";

  var api = factory();

  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }

  if (globalObject) {
    globalObject.CompanySegments = api;
    if (globalObject.document) {
      if (globalObject.document.readyState === "loading") {
        globalObject.document.addEventListener("DOMContentLoaded", function () {
          api.init(globalObject.document);
        });
      } else {
        api.init(globalObject.document);
      }
    }
  }
})(typeof window !== "undefined" ? window : null, function () {
  "use strict";

  var SEGMENT_NAME_MAX_LENGTH = 100;
  var SCALAR_CLAUSE_KEYS = ["value", "min", "max", "from", "to"];
  var TOAST_MS = 4000;
  var ICONS = {
    check:
      '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 -960 960 960" fill="currentColor" aria-hidden="true"><path d="M382-221.91 135.91-468l75.66-75.65L382-373.22l366.43-366.43L824.09-664 382-221.91Z"/></svg>',
    more:
      '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 -960 960 960" fill="currentColor" aria-hidden="true"><path d="M249.23-420q-24.75 0-42.37-17.63-17.63-17.62-17.63-42.37 0-24.75 17.63-42.37Q224.48-540 249.23-540q24.75 0 42.38 17.63 17.62 17.62 17.62 42.37 0 24.75-17.62 42.37Q273.98-420 249.23-420ZM480-420q-24.75 0-42.37-17.63Q420-455.25 420-480q0-24.75 17.63-42.37Q455.25-540 480-540q24.75 0 42.37 17.63Q540-504.75 540-480q0 24.75-17.63 42.37Q504.75-420 480-420Zm230.77 0q-24.75 0-42.38-17.63-17.62-17.62-17.62-42.37 0-24.75 17.62-42.37Q686.02-540 710.77-540q24.75 0 42.37 17.63 17.63 17.62 17.63 42.37 0 24.75-17.63 42.37Q735.52-420 710.77-420Z"/></svg>',
    filter:
      '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 -960 960 960" fill="currentColor" aria-hidden="true"><path d="M455.39-180q-15.08 0-25.23-10.16Q420-200.31 420-215.39v-231.53L196.08-731.38q-11.54-15.39-3.35-32 8.2-16.62 27.66-16.62h519.22q19.46 0 27.66 16.62 8.19 16.61-3.35 32L540-446.92v231.53q0 15.08-10.16 25.23Q519.69-180 504.61-180h-49.22ZM480-468l198-252H282l198 252Zm0 0Z"/></svg>',
    manage:
      '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 -960 960 960" fill="currentColor" aria-hidden="true"><path d="m387.69-100-15.23-121.85q-16.07-5.38-32.96-15.07-16.88-9.7-30.19-20.77L196.46-210l-92.3-160 97.61-73.77q-1.38-8.92-1.96-17.92-.58-9-.58-17.93 0-8.53.58-17.34t1.96-19.27L104.16-590l92.3-159.23 112.46 47.31q14.47-11.46 30.89-20.96t32.27-15.27L387.69-860h184.62l15.23 122.23q18 6.54 32.57 15.27 14.58 8.73 29.43 20.58l114-47.31L855.84-590l-99.15 74.92q2.15 9.69 2.35 18.12.19 8.42.19 16.96 0 8.15-.39 16.58-.38 8.42-2.76 19.27L854.46-370l-92.31 160-112.61-48.08q-14.85 11.85-30.31 20.96-15.46 9.12-31.69 14.89L572.31-100H387.69ZM440-160h78.62L533-267.15q30.62-8 55.96-22.73 25.35-14.74 48.89-37.89L737.23-286l39.39-68-86.77-65.38q5-15.54 6.8-30.47 1.81-14.92 1.81-30.15 0-15.62-1.81-30.15-1.8-14.54-6.8-29.7L777.38-606 738-674l-100.54 42.38q-20.08-21.46-48.11-37.92-28.04-16.46-56.73-23.31L520-800h-79.38l-13.24 106.77q-30.61 7.23-56.53 22.15-25.93 14.93-49.47 38.46L222-674l-39.38 68L269-541.62q-5 14.24-7 29.62t-2 32.38q0 15.62 2 30.62 2 15 6.62 29.62l-86 65.38L222-286l99-42q22.77 23.38 48.69 38.31 25.93 14.92 57.31 22.92L440-160Zm40.46-200q49.92 0 84.96-35.04 35.04-35.04 35.04-84.96 0-49.92-35.04-84.96Q530.38-600 480.46-600q-50.54 0-85.27 35.04T360.46-480q0 49.92 34.73 84.96Q429.92-360 480.46-360ZM480-480Z"/></svg>',
    add:
      '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 -960 960 960" fill="currentColor" aria-hidden="true"><path d="M450-450H220v-60h230v-230h60v230h230v60H510v230h-60v-230Z"/></svg>',
    edit:
      '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 -960 960 960" fill="currentColor" aria-hidden="true"><path d="M200-200h50.46l409.46-409.46-50.46-50.46L200-250.46V-200Zm-60 60v-135.38l527.62-527.39q9.07-8.24 20.03-12.73 10.97-4.5 23-4.5t23.3 4.27q11.28 4.27 19.97 13.58l48.85 49.46q9.31 8.69 13.27 20 3.96 11.31 3.96 22.62 0 12.07-4.12 23.03-4.12 10.97-13.11 20.04L275.38-140H140Z"/></svg>',
    warning:
      '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 -960 960 960" fill="currentColor" aria-hidden="true"><path d="m40-120 440-760 440 760H40Zm104-60h672L480-760 144-180Zm340.18-57q12.82 0 21.32-8.68 8.5-8.67 8.5-21.5 0-12.82-8.68-21.32-8.67-8.5-21.5-8.5-12.82 0-21.32 8.68-8.5 8.67-8.5 21.5 0 12.82 8.68 21.32 8.67 8.5 21.5 8.5Zm-30.18-118h60v-200h-60v200Z"/></svg>',
  };

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function trimmed(value) {
    return value === undefined || value === null ? "" : String(value).trim();
  }

  function clone(value) {
    return value === undefined ? undefined : JSON.parse(JSON.stringify(value));
  }

  function normalizeClause(clause) {
    if (!clause || typeof clause !== "object" || Array.isArray(clause)) return null;
    var operator = trimmed(clause.op || clause.operator);
    if (!operator) return null;
    var normalized = { op: operator };

    if (Array.isArray(clause.values)) {
      var values = Array.from(new Set(clause.values.map(trimmed).filter(Boolean))).sort(
        function (left, right) {
          var leftNumber = Number(left);
          var rightNumber = Number(right);
          if (Number.isSafeInteger(leftNumber) && Number.isSafeInteger(rightNumber)) {
            return leftNumber - rightNumber;
          }
          return left.localeCompare(right);
        }
      );
      if (values.length) normalized.values = values;
    }

    SCALAR_CLAUSE_KEYS.forEach(function (key) {
      if (clause[key] === undefined || clause[key] === null) return;
      var value = trimmed(clause[key]);
      if (value) normalized[key] = value;
    });

    return normalized;
  }

  /**
   * Canonical form used to compare a draft with a saved definition. Comparison
   * must survive key order, duplicate select values, and whitespace, so that
   * changing a value and restoring it counts as unchanged.
   */
  function normalizeDefinition(definition) {
    if (!definition || typeof definition !== "object" || Array.isArray(definition)) return {};
    return Object.keys(definition)
      .map(function (key) { return [trimmed(key), definition[key]]; })
      .filter(function (entry) { return Boolean(entry[0]); })
      .sort(function (left, right) {
        return left[0].localeCompare(right[0], undefined, { numeric: true });
      })
      .reduce(function (normalized, entry) {
        var clause = normalizeClause(entry[1]);
        if (clause) normalized[entry[0]] = clause;
        return normalized;
      }, {});
  }

  function serializeDefinition(definition) {
    return JSON.stringify(normalizeDefinition(definition));
  }

  function areDefinitionsEqual(left, right) {
    return serializeDefinition(left) === serializeDefinition(right);
  }

  function activeConditionCount(definition) {
    return Object.keys(normalizeDefinition(definition)).length;
  }

  function validateSegmentName(name, maxLength) {
    var limit = Number(maxLength) > 0 ? Number(maxLength) : SEGMENT_NAME_MAX_LENGTH;
    var value = trimmed(name);
    if (!value) return { valid: false, name: "", message: "Enter a segment name." };
    if (value.length > limit) {
      return { valid: false, name: value, message: "Use " + limit + " characters or fewer." };
    }
    return { valid: true, name: value, message: "" };
  }

  function segmentNeedsReview(segment) {
    return Boolean(segment && segment.needsReview);
  }

  /**
   * Why a segment cannot be applied yet. A segment that outlived one of its
   * attributes still matches companies on the conditions that remain, and that
   * narrower cohort is exactly what must not be served under the segment's
   * name, so applying is refused until its owner has confirmed the definition.
   */
  function reviewBlockMessage(segment) {
    var name = segment && segment.name ? segment.name : "This company segment";
    return "“" + name + "” can’t be applied until it’s reviewed. A company attribute"
      + " it used was deleted, so its conditions are no longer complete.";
  }

  function scopeForSegment(segment) {
    return {
      type: "segment",
      segmentId: String(segment.id),
      segmentName: segment.name,
      definition: normalizeDefinition(segment.definition),
    };
  }

  /**
   * Apply resolves to the saved segment only when the draft still matches it.
   * Every other non-empty draft becomes an unsaved custom filter, which is what
   * keeps the normal dialog from silently rewriting a saved segment.
   */
  function scopeAfterApplyingDraft(committedScope, draftDefinition, basedOnSegment) {
    var definition = normalizeDefinition(draftDefinition);
    if (!Object.keys(definition).length) return { type: "all", definition: {} };
    if (
      basedOnSegment
      && committedScope
      && committedScope.type === "segment"
      && String(committedScope.segmentId) === String(basedOnSegment.id)
      && areDefinitionsEqual(definition, basedOnSegment.definition)
    ) {
      return scopeForSegment(basedOnSegment);
    }
    return { type: "custom", definition: definition };
  }

  function scopeAfterSegmentDelete(scope, deletedSegmentId) {
    if (!scope || scope.type !== "segment" || String(scope.segmentId) !== String(deletedSegmentId)) {
      return clone(scope);
    }
    var definition = normalizeDefinition(scope.definition);
    if (!Object.keys(definition).length) return { type: "all", definition: {} };
    return { type: "custom", definition: definition };
  }

  function scopeLabel(scope) {
    if (!scope) return "All companies";
    if (scope.type === "segment") return scope.segmentName || "Company segment";
    if (scope.type === "custom") return "Custom filter";
    return "All companies";
  }

  function readPayload(documentRef) {
    var element = documentRef.getElementById("company-attribute-filter-payload");
    if (!element) return {};
    try {
      var parsed = JSON.parse(element.textContent || "{}");
      return parsed && typeof parsed === "object" ? parsed : {};
    } catch (error) {
      return {};
    }
  }

  function initRoot(scopeRoot, documentRef) {
    if (scopeRoot.dataset.companySegmentsReady === "true") return null;
    scopeRoot.dataset.companySegmentsReady = "true";

    var view = documentRef.defaultView || (typeof window !== "undefined" ? window : null);
    var filtersApi = view && view.CompanyAttributeFilters;
    if (!view || !filtersApi) return null;

    var payload = readPayload(documentRef);
    var attributes = filtersApi.normalizeAttributes(payload.attributes);
    var nameMaxLength = Number(payload.segmentNameMaxLength) || SEGMENT_NAME_MAX_LENGTH;
    var segmentUrls = (payload.segmentUrls && typeof payload.segmentUrls === "object")
      ? payload.segmentUrls
      : {};
    var segmentsEnabled = Boolean(payload.segmentsEnabled) && Boolean(segmentUrls.list);
    // Listing and applying segments is one capability; saving, editing,
    // renaming, and deleting is another. The read-only demo has only the first.
    var canManageSegments = segmentsEnabled
      && Boolean(payload.canManageSegments)
      && Boolean(segmentUrls.create);
    var surface = String(payload.surface || "");

    var trigger = scopeRoot.querySelector("[data-company-scope-trigger]");
    var scopeValue = scopeRoot.querySelector("[data-company-scope-value]");
    var scopeCount = scopeRoot.querySelector("[data-company-scope-count]");
    var popover = scopeRoot.querySelector("[data-company-scope-popover]");
    var layer = documentRef.querySelector("[data-company-segment-dialog-layer]");
    var segmentDialog = layer && layer.querySelector("[data-company-segment-dialog]");
    var dialogTitle = layer && layer.querySelector("[data-company-segment-dialog-title]");
    var dialogBody = layer && layer.querySelector("[data-company-segment-dialog-body]");
    var dialogFooter = layer && layer.querySelector("[data-company-segment-dialog-footer]");
    var toast = documentRef.querySelector("[data-company-segment-toast]");
    var live = documentRef.querySelector("[data-company-segment-live]");
    var reviewBanner = documentRef.querySelector("[data-company-segment-review-banner]");
    var blockedBanner = documentRef.querySelector("[data-company-segment-blocked-banner]");
    if (!trigger || !popover) return null;

    var rawScope = (payload.scope && typeof payload.scope === "object") ? payload.scope : {};
    var committedScope = {
      type: rawScope.type === "segment" || rawScope.type === "custom" ? rawScope.type : "all",
      segmentId: String(rawScope.segmentId || ""),
      segmentName: String(rawScope.segmentName || ""),
      definition: normalizeDefinition(filtersApi.normalizeApplied(payload.applied, attributes)),
    };
    if (committedScope.type === "segment" && !committedScope.segmentId) committedScope.type = "custom";
    // The segment this request asked for and the server declined to apply. It
    // is not part of the scope — nothing of it was applied — but it is what the
    // page's blocked banner and its Edit segment action are about.
    var blockedSegmentId = String(rawScope.blockedSegmentId || "");

    var segments = [];
    var segmentListState = segmentsEnabled ? "idle" : "disabled";
    var segmentListError = "";
    var popoverOpen = false;
    var layerState = null;
    var restoreFocusTarget = null;
    var toastTimer = null;
    var navigating = false;
    var editingSegment = null;

    var filterController = filtersApi.getController(documentRef);

    function announce(message) {
      if (!live || !message) return;
      live.textContent = "";
      view.setTimeout(function () { live.textContent = message; }, 30);
    }

    function showToast(message, tone) {
      if (!toast || !message) return;
      toast.textContent = message;
      toast.dataset.tone = tone || "info";
      toast.hidden = false;
      if (toastTimer) view.clearTimeout(toastTimer);
      toastTimer = view.setTimeout(function () { toast.hidden = true; }, TOAST_MS);
    }

    function setBusyCursor(isBusy) {
      var documentElement = documentRef.documentElement;
      if (!documentElement) return;
      if (isBusy) documentElement.dataset.companyScopeBusy = "true";
      else delete documentElement.dataset.companyScopeBusy;
    }

    function setButtonPending(button, isPending) {
      if (!button) return;
      button.disabled = isPending;
      button.setAttribute("aria-busy", isPending ? "true" : "false");
    }

    function csrfToken() {
      var input = documentRef.querySelector('[name="csrfmiddlewaretoken"]');
      if (input && input.value) return input.value;
      var cookie = String(documentRef.cookie || "")
        .split(";")
        .map(function (part) { return part.trim(); })
        .find(function (part) { return part.indexOf("csrftoken=") === 0; });
      return cookie ? decodeURIComponent(cookie.slice("csrftoken=".length)) : "";
    }

    function segmentUrl(kind, segmentId) {
      var template = String(segmentUrls[kind] || "");
      if (!segmentId) return template;
      return template.replace("__segment_id__", encodeURIComponent(String(segmentId)));
    }

    /**
     * Counts follow the page's own scope, so the list request carries the
     * current surface filters but never the company scope itself.
     */
    function segmentRequestUrl() {
      var url = new URL(segmentUrl("list"), view.location.href);
      var reservedKeys = new Set(Array.from(url.searchParams.keys()));
      if (surface) {
        url.searchParams.set("surface", surface);
        reservedKeys.add("surface");
      }
      new URL(view.location.href).searchParams.forEach(function (value, key) {
        if (key === "page" || key === "segment" || reservedKeys.has(key)) return;
        if (key.indexOf("ca.") === 0) return;
        url.searchParams.append(key, value);
      });
      return url.toString();
    }

    function request(url, options) {
      return view.fetch(url, {
        method: (options && options.method) || "GET",
        credentials: "same-origin",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
          "X-Requested-With": "XMLHttpRequest",
          "X-CSRFToken": csrfToken(),
        },
        body: options && options.body ? JSON.stringify(options.body) : undefined,
      }).then(function (response) {
        return response.json().catch(function () { return {}; }).then(function (data) {
          if (!response.ok || data.ok === false) {
            var error = new Error("Request failed");
            error.errors = data.errors || {};
            error.status = response.status;
            throw error;
          }
          return data;
        });
      });
    }

    function firstErrorMessage(error, fallback) {
      var errors = (error && error.errors) || {};
      var values = Object.keys(errors).map(function (key) {
        var value = errors[key];
        return Array.isArray(value) ? value[0] : value;
      }).filter(Boolean);
      return values.length ? String(values[0]) : fallback;
    }

    function adoptSegments(data) {
      segments = (data && Array.isArray(data.segments) ? data.segments : []).map(function (segment) {
        return {
          id: String(segment.id),
          name: String(segment.name || ""),
          definition: normalizeDefinition(segment.definition),
          needsReview: Boolean(segment.needsReview),
          deletedAttributes: Array.isArray(segment.deletedAttributes)
            ? segment.deletedAttributes
            : [],
          matchingCompanyCount: Number.isFinite(Number(segment.matchingCompanyCount))
            ? Number(segment.matchingCompanyCount)
            : undefined,
        };
      });
      segmentListState = "ready";
      segmentListError = "";
      syncReviewBanners();
    }

    /**
     * The banners are server-rendered, so they are already correct on load.
     * This only retires them once a fresh list proves the last affected segment
     * was reviewed, which spares the owner a reload to be rid of them.
     */
    function syncReviewBanners() {
      if (segmentListState !== "ready") return;
      var outstanding = segments.filter(segmentNeedsReview);
      if (reviewBanner && !outstanding.length) {
        reviewBanner.remove();
        reviewBanner = null;
      }
      if (blockedBanner && !outstanding.some(function (segment) {
        return segment.id === blockedSegmentId;
      })) {
        blockedBanner.remove();
        blockedBanner = null;
      }
    }

    function loadSegments(force) {
      if (!segmentsEnabled) return Promise.resolve();
      if (!force && (segmentListState === "ready" || segmentListState === "loading")) {
        return Promise.resolve();
      }
      segmentListState = "loading";
      segmentListError = "";
      renderPopover();
      return request(segmentRequestUrl())
        .then(function (data) {
          adoptSegments(data);
        })
        .catch(function () {
          segmentListState = "error";
          segmentListError = "Company segments could not be loaded.";
        })
        .then(function () {
          renderPopover();
          if (layerState && layerState.kind === "manage") renderManageBody();
        });
    }

    function segmentById(segmentId) {
      return segments.find(function (segment) { return segment.id === String(segmentId); }) || null;
    }

    function activeSegment() {
      if (committedScope.type !== "segment") return null;
      // The server guarantees the applied conditions equal the segment
      // definition, so the scope itself is a usable stand-in before the list
      // request resolves.
      return segmentById(committedScope.segmentId) || {
        id: committedScope.segmentId,
        name: committedScope.segmentName,
        definition: committedScope.definition,
      };
    }

    function scopeUrl(definition, segmentId) {
      return filtersApi.buildApplyUrl(view.location.href, attributes, definition || {}, segmentId || "");
    }

    function navigateTo(url, button) {
      if (navigating) return;
      var current = new URL(view.location.href);
      var next = new URL(url, current);
      if (next.href === current.href) {
        closePopover(false);
        if (filterController) filterController.close(false);
        closeLayer(false, { returnToParent: false });
        return;
      }
      navigating = true;
      setBusyCursor(true);
      setButtonPending(button, true);
      view.location.assign(next.href);
    }

    function renderTrigger() {
      var label = scopeLabel(committedScope);
      var count = activeConditionCount(committedScope.definition);
      if (scopeValue) scopeValue.textContent = label;
      trigger.setAttribute(
        "aria-label",
        "Companies: " + label
          + (committedScope.type === "custom" && count
            ? ", " + count + (count === 1 ? " condition" : " conditions")
            : "")
      );
      trigger.dataset.scopeType = committedScope.type;
      if (scopeCount) {
        var showCount = committedScope.type === "custom" && count > 0;
        scopeCount.hidden = !showCount;
        scopeCount.textContent = showCount ? "· " + count : "";
      }
    }

    function checkMarkup(isSelected) {
      return '<span class="company-scope__check" aria-hidden="true">'
        + (isSelected ? ICONS.check : "") + "</span>";
    }

    function choiceMarkup(options) {
      return '<button type="button" class="company-scope__menu-item" role="menuitemradio" tabindex="-1"'
        + ' aria-checked="' + String(Boolean(options.selected)) + '" ' + options.dataAttribute
        + (options.needsReview ? ' data-needs-review="true"' : "")
        + ' aria-label="' + escapeHtml(options.ariaLabel || options.label) + '">'
        + checkMarkup(options.selected)
        // The warning rides inside the name cell: the menu item is a fixed
        // three-column grid, and the marker belongs to the label anyway.
        + '<span class="company-scope__name">'
        + (options.needsReview
          ? '<span class="company-scope__warning" aria-hidden="true">' + ICONS.warning + "</span>"
          : "")
        + escapeHtml(options.label) + "</span>"
        + (options.meta === undefined
          ? "<span></span>"
          : '<span class="company-scope__match-count">' + escapeHtml(options.meta) + "</span>")
        + "</button>";
    }

    function actionMarkup(action, label, icon) {
      return '<button type="button" class="company-scope__action" role="menuitem" tabindex="-1"'
        + ' data-scope-action="' + action + '">'
        + '<span class="company-scope__action-icon" aria-hidden="true">' + icon + "</span>"
        + "<span>" + escapeHtml(label) + "</span></button>";
    }

    function segmentRowMarkup(segment) {
      var isSelected = committedScope.type === "segment" && committedScope.segmentId === segment.id;
      var needsReview = segmentNeedsReview(segment);
      return '<div class="company-scope__segment-row" data-company-segment-row="'
        + escapeHtml(segment.id) + '">'
        + choiceMarkup({
          selected: isSelected,
          // The stored name is shown untouched; the warning is a marker beside
          // it, never a rename.
          label: segment.name,
          ariaLabel: segment.name
            + (needsReview
              ? ", needs review"
              : segment.matchingCompanyCount === undefined
                ? ""
                : ", " + segment.matchingCompanyCount + " matching companies"),
          meta: needsReview ? undefined : segment.matchingCompanyCount,
          needsReview: needsReview,
          dataAttribute: 'data-apply-segment="' + escapeHtml(segment.id) + '"',
        })
        + "</div>";
    }

    function renderPopover() {
      popover.setAttribute("aria-busy", String(segmentListState === "loading"));

      var markup = choiceMarkup({
        selected: committedScope.type === "all",
        label: "All companies",
        dataAttribute: "data-apply-all",
      });

      if (committedScope.type === "custom") {
        var count = activeConditionCount(committedScope.definition);
        markup += '<div class="company-scope__section-label">Custom filter</div>'
          + choiceMarkup({
            selected: true,
            label: "Custom filter · " + count + (count === 1 ? " condition" : " conditions"),
            dataAttribute: "data-scope-action=\"filter-attributes\"",
          });
      }

      if (segmentsEnabled) {
        markup += '<div class="company-scope__section-label">Company segments</div>';
        if (segmentListState === "loading") {
          markup += '<div class="company-scope__skeleton" aria-hidden="true"></div>'
            + '<div class="company-scope__skeleton" aria-hidden="true"></div>'
            + '<p class="company-scope__message" role="status">Loading company segments…</p>';
        } else if (segmentListState === "error") {
          markup += '<div class="company-scope__message company-scope__message--error" role="alert">'
            + escapeHtml(segmentListError)
            + '<br /><button type="button" class="company-scope__retry" data-segment-list-retry>Try again</button></div>';
        } else if (!segments.length) {
          markup += '<p class="company-scope__message">No saved company segments yet.</p>';
        } else {
          markup += segments.map(segmentRowMarkup).join("");
        }
      }

      markup += '<div class="company-scope__divider"></div>'
        + actionMarkup("filter-attributes", "Filter by company attributes…", ICONS.filter);

      if (canManageSegments) {
        if (committedScope.type === "custom") {
          markup += actionMarkup("save-current", "Save as segment…", ICONS.add);
        }
        // Managing only becomes meaningful once a segment exists, so the action
        // stays out of the menu until the list loads with at least one.
        if (segmentListState === "ready" && segments.length) {
          markup += actionMarkup("manage", "Manage segments", ICONS.manage);
        }
      }

      popover.innerHTML = markup;
      var focusTarget = popover.querySelector('[role="menuitemradio"][aria-checked="true"]')
        || popover.querySelector('[role="menuitemradio"], [role="menuitem"]');
      if (focusTarget) focusTarget.setAttribute("tabindex", "0");
    }

    function openPopover(shouldFocus) {
      renderPopover();
      popover.hidden = false;
      popoverOpen = true;
      trigger.setAttribute("aria-expanded", "true");
      loadSegments(false);
      if (shouldFocus !== false) {
        view.requestAnimationFrame(function () {
          var item = popover.querySelector('[role="menuitemradio"][aria-checked="true"]')
            || popover.querySelector('[role="menuitemradio"], [role="menuitem"]');
          if (item) item.focus();
        });
      }
    }

    function closePopover(restoreFocus) {
      if (!popoverOpen) return;
      popoverOpen = false;
      popover.hidden = true;
      trigger.setAttribute("aria-expanded", "false");
      if (restoreFocus) trigger.focus();
    }

    function menuItems() {
      return Array.from(popover.querySelectorAll('[role="menuitemradio"], [role="menuitem"]'))
        .filter(function (item) { return !item.disabled; });
    }

    function moveMenuFocus(current, direction) {
      var items = menuItems();
      if (!items.length) return;
      var index = Math.max(0, items.indexOf(current));
      var next = direction === "first"
        ? 0
        : direction === "last"
          ? items.length - 1
          : (index + direction + items.length) % items.length;
      items[next].focus();
    }

    /* ---------------------------------------------------------------- dialogs */

    function layerButton(label, action, variant) {
      return '<button type="button" class="company-segment-button'
        + (variant ? " company-segment-button--" + variant : "")
        + '" data-layer-action="' + action + '">' + escapeHtml(label) + "</button>";
    }

    function nameFieldMarkup(name, hint) {
      return '<div class="company-segment-field">'
        + '<label for="company-segment-name">Name</label>'
        + '<input id="company-segment-name" type="text" value="' + escapeHtml(name || "")
        + '" maxlength="' + nameMaxLength
        + '" aria-describedby="company-segment-name-hint company-segment-name-error"'
        + ' autocomplete="off" autofocus />'
        + '<p id="company-segment-name-hint" class="company-segment-field__hint">'
        + escapeHtml(hint) + "</p>"
        + '<p id="company-segment-name-error" class="company-segment-field__error" role="alert"></p>'
        + "</div>";
    }

    function manageRowMarkup(segment) {
      var needsReview = segmentNeedsReview(segment);
      var meta = needsReview
        ? '<span class="company-segment-row__meta company-segment-row__meta--review">Needs review</span>'
        : segment.matchingCompanyCount === undefined
          ? ""
          : '<span class="company-segment-row__meta">' + escapeHtml(segment.matchingCompanyCount)
            + " matching</span>";
      return '<div class="company-segment-row" data-manage-segment-row="' + escapeHtml(segment.id) + '"'
        + (needsReview ? ' data-needs-review="true"' : "") + ">"
        + '<button type="button" class="company-segment-row__name" data-segment-action="edit"'
        + ' data-segment-id="' + escapeHtml(segment.id) + '"'
        + ' aria-label="Edit ' + escapeHtml(segment.name) + ' filter'
        + (needsReview ? ", needs review" : "") + '">'
        + (needsReview
          ? '<span class="company-segment-row__warning" aria-hidden="true">' + ICONS.warning + "</span>"
          : "")
        + '<span class="company-segment-row__name-label">' + escapeHtml(segment.name) + "</span>"
        + '<span class="company-segment-row__edit-icon" aria-hidden="true">' + ICONS.edit + "</span>"
        + "</button>"
        + meta
        + '<button type="button" class="company-segment-row__overflow" data-segment-overflow="'
        + escapeHtml(segment.id) + '" aria-haspopup="menu" aria-expanded="false"'
        + ' aria-label="Actions for ' + escapeHtml(segment.name) + '">' + ICONS.more + "</button>"
        + '<div class="company-segment-overflow-menu" data-segment-overflow-menu="'
        + escapeHtml(segment.id) + '" role="menu" aria-label="' + escapeHtml(segment.name)
        + ' actions" hidden>'
        + '<button type="button" role="menuitem" data-segment-action="rename" data-segment-id="'
        + escapeHtml(segment.id) + '">Rename</button>'
        + '<button type="button" role="menuitem" data-segment-action="delete" data-segment-id="'
        + escapeHtml(segment.id) + '">Delete segment</button>'
        + "</div></div>";
    }

    function manageBodyMarkup() {
      if (segmentListState === "loading") {
        return '<div aria-busy="true" aria-label="Loading company segments">'
          + '<div class="company-scope__skeleton"></div>'
          + '<div class="company-scope__skeleton"></div>'
          + '<div class="company-scope__skeleton"></div></div>';
      }
      if (segmentListState === "error") {
        return '<div class="company-scope__message company-scope__message--error" role="alert">'
          + escapeHtml(segmentListError)
          + '<br /><button type="button" class="company-scope__retry" data-segment-list-retry>Try again</button></div>';
      }
      if (!segments.length) {
        return '<div class="company-segment-empty">'
          + '<span class="company-segment-empty__icon" aria-hidden="true">' + ICONS.filter + "</span>"
          + '<h3 class="company-segment-empty__title">No company segments yet</h3>'
          + '<p class="company-segment-empty__copy">Save a company filter as a segment to reuse it across analytics pages.</p>'
          + '<button type="button" class="company-segment-button" data-scope-action="filter-attributes">Filter by company attributes…</button>'
          + "</div>";
      }
      return '<div class="company-segment-list" data-company-segment-list>'
        + segments.map(manageRowMarkup).join("") + "</div>";
    }

    function renderManageBody() {
      if (!dialogBody || !layerState || layerState.kind !== "manage") return;
      dialogBody.innerHTML = manageBodyMarkup();
      positionLayer();
    }

    function positionLayer() {
      if (!layer || layer.hidden || !segmentDialog) return;
      var edgeGap = 12;
      var anchorGap = 8;
      var childOffset = 28;
      var triggerRect = trigger.getBoundingClientRect();
      var viewportWidth = documentRef.documentElement.clientWidth;
      var viewportHeight = documentRef.documentElement.clientHeight;

      segmentDialog.style.setProperty("--company-segment-dialog-left", edgeGap + "px");
      segmentDialog.style.setProperty("--company-segment-dialog-top", edgeGap + "px");
      segmentDialog.style.setProperty(
        "--company-segment-dialog-max-height",
        Math.max(180, viewportHeight - edgeGap * 2) + "px"
      );

      var dialogWidth = segmentDialog.getBoundingClientRect().width;
      var filterDialog = filterController
        && filterController.root
        && filterController.root.querySelector(".company-attribute-filter-dialog");
      var parentRect = layerState
        && layerState.returnKind === "builder"
        && filterController
        && filterController.isOpen()
        && filterDialog
        ? filterDialog.getBoundingClientRect()
        : null;
      var left = Math.min(
        Math.max(
          edgeGap,
          parentRect ? parentRect.left + childOffset : triggerRect.right - dialogWidth
        ),
        Math.max(edgeGap, viewportWidth - dialogWidth - edgeGap)
      );
      var availableHeight;
      var top;

      if (layerState && layerState.kind === "manage") {
        var spaceBelow = viewportHeight - triggerRect.bottom - anchorGap - edgeGap;
        var spaceAbove = triggerRect.top - anchorGap - edgeGap;
        var openAbove = spaceBelow < 240 && spaceAbove > spaceBelow;
        availableHeight = Math.max(180, openAbove ? spaceAbove : spaceBelow);
        var manageHeight = Math.min(segmentDialog.scrollHeight, availableHeight);
        top = openAbove
          ? Math.max(edgeGap, triggerRect.top - anchorGap - manageHeight)
          : Math.max(
            edgeGap,
            Math.min(
              triggerRect.bottom + anchorGap,
              Math.max(edgeGap, viewportHeight - edgeGap - manageHeight)
            )
          );
      } else {
        var preferredTop = parentRect
          ? parentRect.top + childOffset
          : triggerRect.bottom + anchorGap;
        var viewportAvailableHeight = Math.max(180, viewportHeight - edgeGap * 2);
        var naturalHeight = Math.min(segmentDialog.scrollHeight, viewportAvailableHeight);
        top = Math.max(
          edgeGap,
          Math.min(preferredTop, Math.max(edgeGap, viewportHeight - edgeGap - naturalHeight))
        );
        availableHeight = Math.max(180, viewportHeight - top - edgeGap);
      }

      segmentDialog.style.setProperty("--company-segment-dialog-left", Math.round(left) + "px");
      segmentDialog.style.setProperty("--company-segment-dialog-top", Math.round(top) + "px");
      segmentDialog.style.setProperty(
        "--company-segment-dialog-max-height",
        Math.round(availableHeight) + "px"
      );
    }

    function showLayer(kind, title, bodyMarkup, footerMarkup, options) {
      if (!layer || !segmentDialog) return;
      restoreFocusTarget = (options && options.restoreFocus) || documentRef.activeElement;
      layerState = {
        kind: kind,
        returnKind: (options && options.returnKind) || null,
        segment: (options && options.segment) || null,
        definition: (options && options.definition) || null,
        builderMode: (options && options.builderMode) || "filter",
        builderSegment: (options && options.builderSegment) || null,
        builderDefinition: (options && options.builderDefinition) || null,
        pending: false,
      };
      layer.dataset.dialogKind = kind;
      segmentDialog.dataset.dialogKind = kind;
      segmentDialog.setAttribute("aria-modal", kind === "manage" ? "false" : "true");
      segmentDialog.setAttribute("aria-busy", "false");
      if (dialogTitle) dialogTitle.textContent = title;
      if (dialogBody) dialogBody.innerHTML = bodyMarkup;
      if (dialogFooter) dialogFooter.innerHTML = footerMarkup;
      layer.hidden = false;
      positionLayer();
      view.requestAnimationFrame(function () {
        positionLayer();
        var target = segmentDialog.querySelector("[autofocus]")
          || segmentDialog.querySelector("[data-company-segment-dialog-title]")
          || segmentDialog.querySelector("button");
        if (target) {
          target.focus();
          if (options && options.selectInput && typeof target.select === "function") target.select();
        }
      });
    }

    function closeLayer(restoreFocus, options) {
      if (!layer || layer.hidden || (layerState && layerState.pending)) return;
      var previous = layerState;
      var focusTarget = restoreFocusTarget;
      layer.hidden = true;
      layerState = null;
      restoreFocusTarget = null;
      var returnToParent = !options || options.returnToParent !== false;

      if (returnToParent && previous && previous.returnKind === "manage") {
        openManageDialog();
        return;
      }
      if (returnToParent && previous && previous.returnKind === "builder" && filterController) {
        filterController.open(builderOptions(previous.builderMode, previous.builderSegment, previous.builderDefinition));
        return;
      }
      if (restoreFocus) (focusTarget || trigger).focus();
    }

    function dismissLayer(restoreFocus) {
      closeLayer(restoreFocus, {
        returnToParent: Boolean(layerState && layerState.returnKind === "builder"),
      });
    }

    function setLayerPending(isPending, button) {
      if (layerState) layerState.pending = isPending;
      if (segmentDialog) {
        segmentDialog.setAttribute("aria-busy", isPending ? "true" : "false");
        segmentDialog.querySelectorAll("button, input").forEach(function (control) {
          control.disabled = isPending;
        });
      }
      setButtonPending(button, isPending);
      setBusyCursor(isPending);
    }

    function setNameError(message) {
      if (!segmentDialog) return;
      var input = segmentDialog.querySelector("#company-segment-name");
      var error = segmentDialog.querySelector("#company-segment-name-error");
      if (input) input.setAttribute("aria-invalid", message ? "true" : "false");
      if (error) error.textContent = message || "";
    }

    function submittedName() {
      var input = segmentDialog && segmentDialog.querySelector("#company-segment-name");
      return validateSegmentName(input ? input.value : "", nameMaxLength);
    }

    function focusNameInput() {
      var input = segmentDialog && segmentDialog.querySelector("#company-segment-name");
      if (input) input.focus();
    }

    /* --------------------------------------------------------------- actions */

    function builderOptions(mode, segment, definition) {
      return {
        mode: mode,
        segment: segment || null,
        definition: definition,
        canSaveSegments: canManageSegments,
        anchor: trigger,
        onApply: handleBuilderApply,
        onSaveAs: handleBuilderSaveAs,
        onSaveChanges: handleBuilderSaveChanges,
        onClose: function (event) {
          editingSegment = null;
          if (event && event.restoreFocus) trigger.focus();
        },
      };
    }

    function openBuilder(mode, segment, definition) {
      if (!filterController) return;
      closePopover(false);
      closeLayer(false, { returnToParent: false });
      filterController.open(builderOptions(mode, segment, definition));
    }

    function openCurrentFilterBuilder() {
      var segment = activeSegment();
      openBuilder(
        "filter",
        segment,
        committedScope.definition
      );
    }

    function handleBuilderApply(draft, button) {
      var segment = activeSegment();
      var nextScope = scopeAfterApplyingDraft(committedScope, draft, segment);
      navigateTo(
        scopeUrl(nextScope.definition, nextScope.type === "segment" ? nextScope.segmentId : ""),
        button
      );
    }

    function handleBuilderSaveAs(draft) {
      if (!canManageSegments) return;
      showLayer(
        "save",
        "Save company segment",
        nameFieldMarkup("", "Names are unique for you in this project."),
        layerButton("Cancel", "cancel") + layerButton("Save & apply", "save-and-apply", "primary"),
        {
          returnKind: "builder",
          builderMode: "filter",
          builderSegment: activeSegment(),
          builderDefinition: normalizeDefinition(draft),
          definition: normalizeDefinition(draft),
          restoreFocus: trigger,
        }
      );
    }

    function handleBuilderSaveChanges(draft, button) {
      var segment = editingSegment;
      if (!filterController || !segment) return;
      filterController.setPending(true, button);
      request(segmentUrl("update", segment.id), {
        method: "POST",
        body: { definition: normalizeDefinition(draft) },
      })
        .then(function (data) {
          adoptSegments(data);
          var updated = segmentById(segment.id);
          var isActive = committedScope.type === "segment" && committedScope.segmentId === segment.id;
          // A segment that was refused for this very page becomes the scope as
          // soon as its review is done: finishing the fix is the request to see
          // it applied.
          var wasBlocked = segment.id === blockedSegmentId
            && Boolean(updated)
            && !segmentNeedsReview(updated);
          if (isActive || wasBlocked) {
            navigateTo(scopeUrl(updated ? updated.definition : draft, segment.id), button);
            return;
          }
          filterController.setPending(false, button);
          editingSegment = null;
          filterController.close(false);
          renderPopover();
          openManageDialog();
          showToast("Company segment updated.");
        })
        .catch(function (error) {
          filterController.setPending(false, button);
          filterController.setDraftError(
            firstErrorMessage(error, "The company segment could not be saved. Try again.")
          );
        });
    }

    function beginSegmentEdit(segment) {
      if (!segment) return;
      openBuilder("edit-segment", segment, segment.definition);
      editingSegment = segment;
    }

    function openManageDialog() {
      if (!canManageSegments) return;
      closePopover(false);
      if (filterController) filterController.close(false);
      showLayer("manage", "Manage company segments", manageBodyMarkup(), "", { restoreFocus: trigger });
      loadSegments(false);
    }

    function openRenameDialog(segment, returnKind) {
      if (!segment) return;
      closePopover(false);
      showLayer(
        "rename",
        "Rename company segment",
        nameFieldMarkup(segment.name, "Names are unique for you in this project."),
        layerButton("Cancel", "cancel") + layerButton("Rename", "rename", "primary"),
        { segment: segment, returnKind: returnKind, restoreFocus: trigger, selectInput: true }
      );
    }

    function openDeleteDialog(segment, returnKind) {
      if (!segment) return;
      var isActive = committedScope.type === "segment" && committedScope.segmentId === segment.id;
      closePopover(false);
      showLayer(
        "delete",
        "Delete “" + segment.name + "”?",
        '<p class="company-segment-dialog__copy">This removes the saved segment.</p>'
          + (isActive
            ? '<p class="company-segment-dialog__copy">Its conditions stay applied as a custom filter.</p>'
            : ""),
        layerButton("Cancel", "cancel") + layerButton("Delete segment", "delete", "danger"),
        { segment: segment, returnKind: returnKind, restoreFocus: trigger }
      );
    }

    /**
     * The refusal a viewer sees when they pick a segment that still references
     * a deleted attribute. The server refuses the same request on its own; this
     * only turns that refusal into an explanation and a way out.
     */
    function openReviewRequiredDialog(segment, returnKind) {
      // Without the dialog layer — the read-only demo — refusing to navigate is
      // the whole of the behavior, and the popover stays open behind it.
      if (!segment || !layer || !segmentDialog) return;
      closePopover(false);
      var details = (segment.deletedAttributes || [])
        .map(function (record) {
          return String((record && record.detail) || "").trim();
        })
        .filter(Boolean);
      showLayer(
        "review",
        "“" + segment.name + "” needs review",
        '<p class="company-segment-dialog__copy">' + escapeHtml(reviewBlockMessage(segment)) + "</p>"
          + (details.length
            ? '<ul class="company-segment-dialog__list">'
              + details.map(function (detail) {
                return "<li>" + escapeHtml(detail) + "</li>";
              }).join("")
              + "</ul>"
            : "")
          + '<p class="company-segment-dialog__copy">Edit the segment to drop the removed'
          + " conditions and save it. Until then it stays out of the analytics pages.</p>",
        layerButton("Cancel", "cancel")
          + (canManageSegments ? layerButton("Edit segment", "edit-segment", "primary") : ""),
        { segment: segment, returnKind: returnKind, restoreFocus: trigger }
      );
    }

    function openSaveCurrentDialog() {
      if (!canManageSegments || committedScope.type !== "custom") return;
      closePopover(false);
      showLayer(
        "save",
        "Save company segment",
        nameFieldMarkup("", "Names are unique for you in this project."),
        layerButton("Cancel", "cancel") + layerButton("Save & apply", "save-and-apply", "primary"),
        { definition: committedScope.definition, restoreFocus: trigger }
      );
    }

    function saveAndApplySegment(button) {
      if (!layerState || layerState.kind !== "save") return;
      var validation = submittedName();
      if (!validation.valid) {
        setNameError(validation.message);
        focusNameInput();
        return;
      }
      setNameError("");
      var definition = normalizeDefinition(layerState.definition);
      if (!Object.keys(definition).length) {
        setNameError("Add at least one company attribute condition before saving a segment.");
        return;
      }
      setLayerPending(true, button);
      request(segmentUrl("create"), {
        method: "POST",
        body: { name: validation.name, definition: definition },
      })
        .then(function (data) {
          var created = data && data.segment;
          adoptSegments(data);
          navigateTo(scopeUrl(definition, created ? created.id : ""), button);
        })
        .catch(function (error) {
          setLayerPending(false, button);
          setNameError(firstErrorMessage(error, "The company segment could not be saved. Try again."));
          focusNameInput();
        });
    }

    function renameSegment(button) {
      if (!layerState || layerState.kind !== "rename" || !layerState.segment) return;
      var segment = layerState.segment;
      var validation = submittedName();
      if (!validation.valid) {
        setNameError(validation.message);
        focusNameInput();
        return;
      }
      setNameError("");
      setLayerPending(true, button);
      request(segmentUrl("update", segment.id), {
        method: "POST",
        body: { name: validation.name },
      })
        .then(function (data) {
          adoptSegments(data);
          if (committedScope.type === "segment" && committedScope.segmentId === segment.id) {
            committedScope.segmentName = validation.name;
            renderTrigger();
          }
          setLayerPending(false, button);
          closeLayer(true);
          renderPopover();
          showToast("Company segment renamed.");
          announce("Company segment renamed to " + validation.name + ".");
        })
        .catch(function (error) {
          setLayerPending(false, button);
          setNameError(firstErrorMessage(error, "The company segment could not be renamed. Try again."));
          focusNameInput();
        });
    }

    function deleteSegment(button) {
      if (!layerState || layerState.kind !== "delete" || !layerState.segment) return;
      var segment = layerState.segment;
      var isActive = committedScope.type === "segment" && committedScope.segmentId === segment.id;
      var nextScope = scopeAfterSegmentDelete(committedScope, segment.id);
      setLayerPending(true, button);
      request(segmentUrl("delete", segment.id), { method: "POST" })
        .then(function (data) {
          adoptSegments(data);
          if (isActive) {
            navigateTo(scopeUrl(nextScope.definition, ""), button);
            return;
          }
          setLayerPending(false, button);
          closeLayer(true);
          renderPopover();
          showToast("Company segment deleted.");
        })
        .catch(function (error) {
          setLayerPending(false, button);
          showToast(
            firstErrorMessage(error, "The company segment could not be deleted. Try again."),
            "error"
          );
        });
    }

    function closeOverflowMenus(exceptId) {
      if (!segmentDialog) return;
      segmentDialog.querySelectorAll("[data-segment-overflow-menu]").forEach(function (menu) {
        if (menu.dataset.segmentOverflowMenu === exceptId) return;
        menu.hidden = true;
      });
      segmentDialog.querySelectorAll("[data-segment-overflow]").forEach(function (button) {
        if (button.dataset.segmentOverflow === exceptId) return;
        button.setAttribute("aria-expanded", "false");
      });
    }

    function positionOverflowMenu(overflow, menu) {
      if (!overflow || !menu || menu.hidden) return;
      var edgeGap = 8;
      var menuGap = 4;
      var viewportWidth = documentRef.documentElement.clientWidth;
      var viewportHeight = documentRef.documentElement.clientHeight;
      var triggerRect = overflow.getBoundingClientRect();

      menu.style.setProperty("--company-segment-menu-left", edgeGap + "px");
      menu.style.setProperty("--company-segment-menu-top", edgeGap + "px");

      var menuRect = menu.getBoundingClientRect();
      var left = Math.min(
        Math.max(edgeGap, triggerRect.right - menuRect.width),
        Math.max(edgeGap, viewportWidth - menuRect.width - edgeGap)
      );
      var spaceBelow = viewportHeight - triggerRect.bottom - menuGap - edgeGap;
      var spaceAbove = triggerRect.top - menuGap - edgeGap;
      var top = spaceBelow >= menuRect.height || spaceBelow >= spaceAbove
        ? Math.min(
          triggerRect.bottom + menuGap,
          Math.max(edgeGap, viewportHeight - menuRect.height - edgeGap)
        )
        : Math.max(edgeGap, triggerRect.top - menuGap - menuRect.height);

      menu.style.setProperty("--company-segment-menu-left", Math.round(left) + "px");
      menu.style.setProperty("--company-segment-menu-top", Math.round(top) + "px");
    }

    function handleSegmentAction(action, segmentId, returnKind) {
      if (!canManageSegments) return;
      var segment = segmentById(segmentId);
      if (!segment) return;
      if (action === "edit") {
        beginSegmentEdit(segment);
        return;
      }
      if (action === "rename") {
        openRenameDialog(segment, returnKind);
        return;
      }
      if (action === "delete") openDeleteDialog(segment, returnKind);
    }

    function handleScopeAction(action) {
      if (action === "filter-attributes") {
        openCurrentFilterBuilder();
        return;
      }
      if (action === "save-current") {
        openSaveCurrentDialog();
        return;
      }
      if (action === "manage") openManageDialog();
    }

    /* ---------------------------------------------------------------- wiring */

    renderTrigger();

    trigger.addEventListener("click", function () {
      if (navigating) return;
      if (popoverOpen) closePopover(true);
      else openPopover(true);
    });

    popover.addEventListener("click", function (event) {
      if (navigating) return;
      var applyAll = event.target.closest("[data-apply-all]");
      if (applyAll) {
        navigateTo(scopeUrl({}, ""), applyAll);
        return;
      }
      var applySegment = event.target.closest("[data-apply-segment]");
      if (applySegment) {
        var segment = segmentById(applySegment.dataset.applySegment);
        if (!segment) return;
        if (segmentNeedsReview(segment)) {
          openReviewRequiredDialog(segment, null);
          return;
        }
        navigateTo(scopeUrl(segment.definition, segment.id), applySegment);
        return;
      }
      var retry = event.target.closest("[data-segment-list-retry]");
      if (retry) {
        loadSegments(true);
        return;
      }
      var action = event.target.closest("[data-scope-action]");
      if (action) handleScopeAction(action.dataset.scopeAction);
    });

    popover.addEventListener("keydown", function (event) {
      var item = event.target.closest('[role="menuitemradio"], [role="menuitem"]');
      if (event.key === "Escape") {
        event.preventDefault();
        closePopover(true);
        return;
      }
      if (!item) return;
      if (event.key === "ArrowDown") {
        event.preventDefault();
        moveMenuFocus(item, 1);
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        moveMenuFocus(item, -1);
      } else if (event.key === "Home") {
        event.preventDefault();
        moveMenuFocus(item, "first");
      } else if (event.key === "End") {
        event.preventDefault();
        moveMenuFocus(item, "last");
      }
    });

    trigger.addEventListener("keydown", function (event) {
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        if (!popoverOpen) openPopover(true);
      } else if (event.key === "Escape" && popoverOpen) {
        event.preventDefault();
        closePopover(true);
      }
    });

    if (layer) {
      layer.addEventListener("click", function (event) {
        if (navigating) return;
        if (event.target === layer) {
          dismissLayer(true);
          return;
        }
        var closeButton = event.target.closest("[data-company-segment-dialog-close]");
        if (closeButton) {
          dismissLayer(true);
          return;
        }

        var overflow = event.target.closest("[data-segment-overflow]");
        if (overflow) {
          var menu = segmentDialog.querySelector(
            '[data-segment-overflow-menu="' + overflow.dataset.segmentOverflow + '"]'
          );
          var willOpen = Boolean(menu && menu.hidden);
          closeOverflowMenus(willOpen ? overflow.dataset.segmentOverflow : "");
          if (menu && willOpen) {
            menu.hidden = false;
            positionOverflowMenu(overflow, menu);
            overflow.setAttribute("aria-expanded", "true");
            var firstMenuItem = menu.querySelector('[role="menuitem"]');
            if (firstMenuItem) firstMenuItem.focus();
          } else {
            overflow.setAttribute("aria-expanded", "false");
          }
          return;
        }

        var segmentAction = event.target.closest("[data-segment-action]");
        if (segmentAction) {
          closeOverflowMenus("");
          handleSegmentAction(
            segmentAction.dataset.segmentAction,
            segmentAction.dataset.segmentId,
            "manage"
          );
          return;
        }

        var retry = event.target.closest("[data-segment-list-retry]");
        if (retry) {
          loadSegments(true).then(renderManageBody);
          return;
        }

        var scopeAction = event.target.closest("[data-scope-action]");
        if (scopeAction) {
          handleScopeAction(scopeAction.dataset.scopeAction);
          return;
        }

        var layerAction = event.target.closest("[data-layer-action]");
        if (!layerAction) {
          closeOverflowMenus("");
          return;
        }
        var action = layerAction.dataset.layerAction;
        if (action === "cancel") {
          closeLayer(true);
        } else if (action === "edit-segment") {
          var reviewSegment = layerState && layerState.segment;
          closeLayer(false, { returnToParent: false });
          beginSegmentEdit(reviewSegment);
        } else if (action === "save-and-apply") {
          saveAndApplySegment(layerAction);
        } else if (action === "rename") {
          renameSegment(layerAction);
        } else if (action === "delete") {
          deleteSegment(layerAction);
        }
      });

      layer.addEventListener("input", function (event) {
        if (event.target.id === "company-segment-name") setNameError("");
      });

      layer.addEventListener("keydown", function (event) {
        if (event.key === "Escape") {
          event.preventDefault();
          dismissLayer(true);
          return;
        }
        if (event.key === "Enter" && event.target.id === "company-segment-name") {
          event.preventDefault();
          var primary = segmentDialog.querySelector(".company-segment-button--primary");
          if (primary) primary.click();
        }
      });
    }

    if (reviewBanner) {
      reviewBanner.addEventListener("click", function (event) {
        if (navigating || !event.target.closest("[data-company-segment-review-action]")) return;
        // The affected segments are marked in the manage list, which is where
        // reviewing them actually happens.
        openManageDialog();
      });
    }

    if (blockedBanner) {
      blockedBanner.addEventListener("click", function (event) {
        if (navigating || !event.target.closest("[data-company-segment-edit-action]")) return;
        loadSegments(false).then(function () {
          var segment = segmentById(blockedSegmentId);
          if (segment) beginSegmentEdit(segment);
          else openManageDialog();
        });
      });
    }

    documentRef.addEventListener("pointerdown", function (event) {
      if (popoverOpen && !scopeRoot.contains(event.target)) closePopover(false);
    });

    view.addEventListener("resize", function () {
      closeOverflowMenus("");
      positionLayer();
    });
    view.addEventListener("scroll", function () {
      closeOverflowMenus("");
      positionLayer();
    }, true);

    return {
      scopeRoot: scopeRoot,
      committedScope: function () { return clone(committedScope); },
      segments: function () { return clone(segments); },
    };
  }

  function init(documentRef) {
    if (!documentRef || !documentRef.querySelectorAll) return;
    documentRef.querySelectorAll("[data-company-scope]").forEach(function (scopeRoot) {
      initRoot(scopeRoot, documentRef);
    });
  }

  return {
    init: init,
    SEGMENT_NAME_MAX_LENGTH: SEGMENT_NAME_MAX_LENGTH,
    normalizeDefinition: normalizeDefinition,
    serializeDefinition: serializeDefinition,
    areDefinitionsEqual: areDefinitionsEqual,
    activeConditionCount: activeConditionCount,
    validateSegmentName: validateSegmentName,
    scopeForSegment: scopeForSegment,
    scopeAfterApplyingDraft: scopeAfterApplyingDraft,
    scopeAfterSegmentDelete: scopeAfterSegmentDelete,
    scopeLabel: scopeLabel,
    segmentNeedsReview: segmentNeedsReview,
    reviewBlockMessage: reviewBlockMessage,
  };
});
