(function (globalObject, factory) {
  "use strict";

  var api = factory();

  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }

  if (globalObject) {
    globalObject.CompanyAttributeFilters = api;
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

  var PREVIEW_DELAY_MS = 350;
  var MAX_DECIMAL_PLACES = 10;
  var MAX_DECIMAL_WHOLE_DIGITS = 20;
  var SEGMENT_PARAMETER = "segment";
  var EMPTY_OPERATORS = new Set(["empty", "not_empty"]);
  var TYPE_ALIASES = {
    select: "single_select",
    "single-select": "single_select",
    single_select: "single_select",
  };
  var TYPE_LABELS = {
    single_select: "Select",
    money: "Money",
    number: "Number",
    text: "Text",
    date: "Date",
    boolean: "Boolean",
  };
  var CURRENCY_SYMBOLS = {
    USD: "$",
    EUR: "€",
    GBP: "£",
  };
  var OPERATORS = {
    single_select: [
      ["in", "is one of"],
      ["not_in", "is not one of"],
      ["empty", "is empty"],
      ["not_empty", "is not empty"],
    ],
    money: [
      ["eq", "equals"],
      ["gt", "greater than"],
      ["gte", "greater than or equal to"],
      ["lt", "less than"],
      ["lte", "less than or equal to"],
      ["between", "between"],
      ["empty", "is empty"],
      ["not_empty", "is not empty"],
    ],
    number: [
      ["eq", "equals"],
      ["gt", "greater than"],
      ["gte", "greater than or equal to"],
      ["lt", "less than"],
      ["lte", "less than or equal to"],
      ["between", "between"],
      ["empty", "is empty"],
      ["not_empty", "is not empty"],
    ],
    text: [
      ["contains", "contains"],
      ["not_contains", "does not contain"],
      ["eq", "is"],
      ["neq", "is not"],
      ["empty", "is empty"],
      ["not_empty", "is not empty"],
    ],
    date: [
      ["on", "on"],
      ["before", "before"],
      ["after", "after"],
      ["between", "between"],
      ["empty", "is empty"],
      ["not_empty", "is not empty"],
    ],
    boolean: [["eq", "is"]],
  };

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function positiveIntegerString(value) {
    var rendered = String(value == null ? "" : value).trim();
    if (!/^[1-9]\d*$/.test(rendered)) return "";
    return rendered;
  }

  function normalizeType(value) {
    var type = String(value || "").trim().toLowerCase();
    return TYPE_ALIASES[type] || type;
  }

  function optionColorStyle(color) {
    if (!color || typeof color !== "object") return "";
    var text = /^#[0-9a-f]{6}$/i.test(color.text || "") ? color.text : "";
    var bg = /^#[0-9a-f]{6}$/i.test(color.bg || "") ? color.bg : "";
    var border = /^#[0-9a-f]{6}$/i.test(color.border || "") ? color.border : "";
    var declarations = [];
    if (text) declarations.push("--tag-text:" + text);
    if (bg) declarations.push("--tag-bg:" + bg);
    if (border) declarations.push("--tag-border:" + border);
    return declarations.length ? ' style="' + declarations.join(";") + '"' : "";
  }

  function normalizeOperators(attribute, type) {
    var fallback = OPERATORS[type] || [];
    var labelsByCode = {};
    var source = Array.isArray(attribute.operators) ? attribute.operators : [];

    source.forEach(function (operator) {
      var code = "";
      var label = "";
      if (Array.isArray(operator)) {
        code = String(operator[0] || "");
        label = String(operator[1] || "");
      } else if (operator && typeof operator === "object") {
        code = String(operator.code || operator.value || operator.op || "");
        label = String(operator.label || operator.name || "");
      }
      if (code && label) labelsByCode[code] = label;
    });

    return fallback.map(function (operator) {
      return [operator[0], labelsByCode[operator[0]] || operator[1]];
    });
  }

  function normalizeAttributes(rawAttributes) {
    if (!Array.isArray(rawAttributes)) return [];

    return rawAttributes
      .map(function (rawAttribute, attributeIndex) {
        if (!rawAttribute || typeof rawAttribute !== "object") return null;
        var id = positiveIntegerString(rawAttribute.id);
        var type = normalizeType(rawAttribute.type || rawAttribute.attribute_type);
        if (!id || !Object.prototype.hasOwnProperty.call(TYPE_LABELS, type)) return null;
        var settings = rawAttribute.settings && typeof rawAttribute.settings === "object"
          ? rawAttribute.settings
          : {};
        var options = Array.isArray(rawAttribute.options)
          ? rawAttribute.options
              .map(function (rawOption, optionIndex) {
                if (!rawOption || typeof rawOption !== "object") return null;
                var optionId = positiveIntegerString(rawOption.id);
                if (!optionId) return null;
                return {
                  id: optionId,
                  label: String(rawOption.label || ""),
                  color: rawOption.color,
                  position: Number.isFinite(Number(rawOption.position))
                    ? Number(rawOption.position)
                    : optionIndex,
                };
              })
              .filter(Boolean)
              .sort(function (left, right) {
                return left.position - right.position || Number(left.id) - Number(right.id);
              })
          : [];

        return {
          id: id,
          name: String(rawAttribute.name || ""),
          type: type,
          typeLabel: String(rawAttribute.type_label || rawAttribute.typeLabel || TYPE_LABELS[type]),
          currency: String(rawAttribute.currency || settings.currency || ""),
          position: Number.isFinite(Number(rawAttribute.position))
            ? Number(rawAttribute.position)
            : attributeIndex,
          options: options,
          operators: normalizeOperators(rawAttribute, type),
        };
      })
      .filter(Boolean)
      .sort(function (left, right) {
        return left.position - right.position || Number(left.id) - Number(right.id);
      });
  }

  function normalizeFilter(rawFilter) {
    if (!rawFilter || typeof rawFilter !== "object") return null;
    var op = String(rawFilter.op || rawFilter.operator || "").trim();
    if (!op) return null;
    var normalized = { op: op };

    if (Array.isArray(rawFilter.values)) {
      normalized.values = rawFilter.values.map(String);
    } else if (Array.isArray(rawFilter.value)) {
      normalized.values = rawFilter.value.map(String);
    } else if (rawFilter.value !== undefined && rawFilter.value !== null) {
      normalized.value = String(rawFilter.value);
    }

    ["min", "max", "from", "to"].forEach(function (key) {
      if (rawFilter[key] !== undefined && rawFilter[key] !== null) {
        normalized[key] = String(rawFilter[key]);
      }
    });
    return normalized;
  }

  function normalizeApplied(rawApplied, attributes) {
    var attributeIds = new Set(attributes.map(function (attribute) { return attribute.id; }));
    var state = {};
    var entries = [];

    if (Array.isArray(rawApplied)) {
      entries = rawApplied.map(function (filter) {
        return [
          positiveIntegerString(filter && (filter.attribute_id || filter.attributeId || filter.id)),
          filter,
        ];
      });
    } else if (rawApplied && Array.isArray(rawApplied.filters)) {
      entries = rawApplied.filters.map(function (filter) {
        return [
          positiveIntegerString(filter && (filter.attribute_id || filter.attributeId || filter.id)),
          filter,
        ];
      });
    } else if (rawApplied && typeof rawApplied === "object") {
      entries = Object.entries(rawApplied);
    }

    entries.forEach(function (entry) {
      var attributeId = positiveIntegerString(entry[0]);
      var filter = normalizeFilter(entry[1]);
      if (attributeId && attributeIds.has(attributeId) && filter) {
        state[attributeId] = filter;
      }
    });
    return state;
  }

  function cloneState(state) {
    return JSON.parse(JSON.stringify(state || {}));
  }

  function appliedPayload(payload) {
    if (payload && Object.prototype.hasOwnProperty.call(payload, "applied")) {
      return { present: true, value: payload.applied };
    }
    if (payload && payload.state && Object.prototype.hasOwnProperty.call(payload.state, "applied")) {
      return { present: true, value: payload.state.applied };
    }
    return { present: false, value: undefined };
  }

  function parseStateFromUrl(attributes, href) {
    var state = {};
    var url;
    try {
      url = new URL(href);
    } catch (error) {
      return state;
    }

    attributes.forEach(function (attribute) {
      var prefix = "ca." + attribute.id + ".";
      var op = String(url.searchParams.get(prefix + "op") || "").trim();
      if (!op) return;
      var filter = { op: op };

      if (attribute.type === "single_select" && (op === "in" || op === "not_in")) {
        filter.values = url.searchParams.getAll(prefix + "value");
      } else if (op === "between" && (attribute.type === "number" || attribute.type === "money")) {
        filter.min = url.searchParams.get(prefix + "min") || "";
        filter.max = url.searchParams.get(prefix + "max") || "";
      } else if (op === "between" && attribute.type === "date") {
        filter.from = url.searchParams.get(prefix + "from") || "";
        filter.to = url.searchParams.get(prefix + "to") || "";
      } else if (!EMPTY_OPERATORS.has(op)) {
        filter.value = url.searchParams.get(prefix + "value") || "";
      }
      state[attribute.id] = filter;
    });

    return state;
  }

  function decimalParts(value) {
    var raw = String(value == null ? "" : value).trim();
    var match = /^([+-]?)(\d*)(?:\.(\d*))?$/.exec(raw);
    if (!match || (!match[2] && !match[3])) return null;
    var integer = (match[2] || "0").replace(/^0+(?=\d)/, "");
    var fraction = match[3] || "";
    var digits = (integer + fraction).replace(/^0+/, "") || "0";
    return {
      sign: match[1] === "-" && digits !== "0" ? -1 : 1,
      integer: integer,
      fraction: fraction,
    };
  }

  function compareDecimalStrings(leftValue, rightValue) {
    var left = decimalParts(leftValue);
    var right = decimalParts(rightValue);
    if (!left || !right) return null;
    if (left.sign !== right.sign) return left.sign < right.sign ? -1 : 1;

    var scale = Math.max(left.fraction.length, right.fraction.length);
    var leftMagnitude = BigInt(
      (left.integer + left.fraction.padEnd(scale, "0")).replace(/^0+/, "") || "0"
    );
    var rightMagnitude = BigInt(
      (right.integer + right.fraction.padEnd(scale, "0")).replace(/^0+/, "") || "0"
    );
    if (leftMagnitude === rightMagnitude) return 0;
    var comparison = leftMagnitude < rightMagnitude ? -1 : 1;
    return left.sign < 0 ? -comparison : comparison;
  }

  function isStoredDecimal(value) {
    var parts = decimalParts(value);
    if (!parts) return false;
    var wholeDigits = parts.integer.replace(/^0+/, "");
    return wholeDigits.length <= MAX_DECIMAL_WHOLE_DIGITS
      && parts.fraction.length <= MAX_DECIMAL_PLACES;
  }

  function isIsoDate(value) {
    var match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value || "").trim());
    if (!match) return false;
    var year = Number(match[1]);
    var month = Number(match[2]);
    var day = Number(match[3]);
    var timestamp = Date.UTC(year, month - 1, day);
    var date = new Date(timestamp);
    return date.getUTCFullYear() === year
      && date.getUTCMonth() === month - 1
      && date.getUTCDate() === day;
  }

  function filterAllowedOperators(attribute) {
    return new Set((OPERATORS[attribute.type] || []).map(function (operator) {
      return operator[0];
    }));
  }

  function validateDraft(attributes, draft) {
    var errors = {};
    var activeCount = 0;

    attributes.forEach(function (attribute) {
      var filter = draft && draft[attribute.id];
      if (!filter || !filter.op) return;
      activeCount += 1;

      if (!filterAllowedOperators(attribute).has(filter.op)) {
        errors[attribute.id] = "Choose a valid condition.";
        return;
      }

      if (attribute.type === "boolean") {
        if (filter.op !== "eq" || !["true", "false"].includes(String(filter.value))) {
          errors[attribute.id] = "Choose Yes or No.";
        }
        return;
      }

      if (EMPTY_OPERATORS.has(filter.op)) return;

      if (attribute.type === "single_select") {
        var allowedOptions = new Set(attribute.options.map(function (option) { return option.id; }));
        var selected = Array.isArray(filter.values)
          ? Array.from(new Set(filter.values.map(String)))
          : filter.value != null
            ? [String(filter.value)]
            : [];
        if (!selected.length || selected.some(function (optionId) { return !allowedOptions.has(optionId); })) {
          errors[attribute.id] = "Select at least one option.";
        }
        return;
      }

      if (attribute.type === "number" || attribute.type === "money") {
        var numericLabel = attribute.type === "money" ? "amount" : "number";
        if (filter.op === "between") {
          var minimum = String(filter.min == null ? "" : filter.min).trim();
          var maximum = String(filter.max == null ? "" : filter.max).trim();
          if (!isStoredDecimal(minimum) || !isStoredDecimal(maximum)) {
            errors[attribute.id] = "Enter both " + numericLabel + " values.";
          } else if (compareDecimalStrings(minimum, maximum) > 0) {
            errors[attribute.id] = "The lower bound cannot exceed the upper bound.";
          }
        } else if (!isStoredDecimal(filter.value)) {
          errors[attribute.id] = "Enter a valid " + numericLabel + ".";
        }
        return;
      }

      if (attribute.type === "text") {
        if (!String(filter.value == null ? "" : filter.value).trim()) {
          errors[attribute.id] = "Enter text.";
        }
        return;
      }

      if (attribute.type === "date") {
        if (filter.op === "between") {
          var from = String(filter.from || "").trim();
          var to = String(filter.to || "").trim();
          if (!isIsoDate(from) || !isIsoDate(to)) {
            errors[attribute.id] = "Enter both dates.";
          } else if (from > to) {
            errors[attribute.id] = "The start date cannot be after the end date.";
          }
        } else if (!isIsoDate(filter.value)) {
          errors[attribute.id] = "Enter a valid date.";
        }
      }
    });

    return {
      valid: Object.keys(errors).length === 0,
      errors: errors,
      activeCount: activeCount,
    };
  }

  function sortedSelectedValues(values) {
    return Array.from(new Set((values || []).map(String))).sort(function (left, right) {
      var leftNumber = Number(left);
      var rightNumber = Number(right);
      if (Number.isSafeInteger(leftNumber) && Number.isSafeInteger(rightNumber)) {
        return leftNumber - rightNumber;
      }
      return left.localeCompare(right);
    });
  }

  function canonicalPairs(attributes, draft) {
    var pairs = [];
    attributes
      .slice()
      .sort(function (left, right) { return Number(left.id) - Number(right.id); })
      .forEach(function (attribute) {
        var filter = draft && draft[attribute.id];
        if (!filter || !filter.op) return;
        var prefix = "ca." + attribute.id + ".";
        pairs.push([prefix + "op", filter.op]);

        if (EMPTY_OPERATORS.has(filter.op)) return;
        if (attribute.type === "single_select") {
          sortedSelectedValues(filter.values || (filter.value == null ? [] : [filter.value]))
            .forEach(function (optionId) {
              pairs.push([prefix + "value", optionId]);
            });
        } else if (filter.op === "between" && (attribute.type === "number" || attribute.type === "money")) {
          pairs.push([prefix + "min", String(filter.min || "").trim()]);
          pairs.push([prefix + "max", String(filter.max || "").trim()]);
        } else if (filter.op === "between" && attribute.type === "date") {
          pairs.push([prefix + "from", String(filter.from || "").trim()]);
          pairs.push([prefix + "to", String(filter.to || "").trim()]);
        } else {
          var value = String(filter.value == null ? "" : filter.value);
          pairs.push([prefix + "value", attribute.type === "text" ? value.trim() : value.trim()]);
        }
      });
    return pairs;
  }

  function removeCompanyAttributeParams(params) {
    Array.from(params.keys()).forEach(function (key) {
      if (key.indexOf("ca.") === 0) params.delete(key);
    });
  }

  function buildApplyUrl(currentHref, attributes, draft, segmentId) {
    var url = new URL(currentHref);
    var params = new URLSearchParams(url.search);
    removeCompanyAttributeParams(params);
    params.delete("page");
    params.delete(SEGMENT_PARAMETER);
    canonicalPairs(attributes, draft).forEach(function (pair) {
      params.append(pair[0], pair[1]);
    });
    var segment = String(segmentId == null ? "" : segmentId).trim();
    if (segment) params.set(SEGMENT_PARAMETER, segment);
    url.search = params.toString();
    return url.toString();
  }

  function buildPreviewUrl(previewUrl, currentHref, surface, attributes, draft) {
    var current = new URL(currentHref);
    var endpoint = new URL(previewUrl, current);
    var endpointPairs = Array.from(endpoint.searchParams.entries());
    var params = new URLSearchParams();

    current.searchParams.forEach(function (value, key) {
      if (key.indexOf("ca.") !== 0 && key !== "page" && key !== SEGMENT_PARAMETER) {
        params.append(key, value);
      }
    });
    Array.from(new Set(endpointPairs.map(function (pair) { return pair[0]; })))
      .forEach(function (key) { params.delete(key); });
    endpointPairs.forEach(function (pair) {
      params.append(pair[0], pair[1]);
    });
    canonicalPairs(attributes, draft).forEach(function (pair) {
      params.append(pair[0], pair[1]);
    });
    if (surface) params.set("surface", surface);
    endpoint.search = params.toString();
    endpoint.hash = "";
    return endpoint.toString();
  }

  function extractPayloadState(payload, attributes, href) {
    var extracted = appliedPayload(payload);
    return extracted.present
      ? normalizeApplied(extracted.value, attributes)
      : parseStateFromUrl(attributes, href);
  }

  function payloadValue(payload, camelKey, snakeKey) {
    if (payload && payload[camelKey] !== undefined) return payload[camelKey];
    if (payload && payload[snakeKey] !== undefined) return payload[snakeKey];
    if (payload && payload.state && payload.state[camelKey] !== undefined) {
      return payload.state[camelKey];
    }
    if (payload && payload.state && payload.state[snakeKey] !== undefined) {
      return payload.state[snakeKey];
    }
    return undefined;
  }

  function readPayload(documentRef) {
    var payloadElement = documentRef.getElementById("company-attribute-filter-payload");
    if (!payloadElement) return {};
    try {
      var parsed = JSON.parse(payloadElement.textContent || "{}");
      return parsed && typeof parsed === "object" ? parsed : {};
    } catch (error) {
      return {};
    }
  }

  function operatorOptionsHtml(attribute, selectedOperator) {
    var html = '<option value="">Any</option>';
    attribute.operators.forEach(function (operator) {
      html += '<option value="' + escapeHtml(operator[0]) + '"'
        + (operator[0] === selectedOperator ? " selected" : "")
        + ">" + escapeHtml(operator[1]) + "</option>";
    });
    return html;
  }

  function selectedOptions(attribute, filter) {
    var selectedIds = new Set(
      Array.isArray(filter && filter.values)
        ? filter.values.map(String)
        : filter && filter.value != null
          ? [String(filter.value)]
          : []
    );
    return attribute.options.filter(function (option) {
      return selectedIds.has(option.id);
    });
  }

  function multiselectHtml(attribute, filter) {
    var selected = selectedOptions(attribute, filter);
    var tags = selected.map(function (option) {
      return '<span class="attribute-filter-tag"' + optionColorStyle(option.color) + ">"
        + '<span>' + escapeHtml(option.label) + "</span>"
        + '<button type="button" class="attribute-filter-tag-remove" data-filter-option-remove="'
        + escapeHtml(option.id) + '" aria-label="Remove ' + escapeHtml(option.label) + '">&times;</button>'
        + "</span>";
    }).join("");
    var options = attribute.options.map(function (option) {
      var isSelected = selected.some(function (selectedOption) {
        return selectedOption.id === option.id;
      });
      return '<button type="button" class="attribute-filter-value-option" role="option"'
        + ' data-filter-option-id="' + escapeHtml(option.id) + '"'
        + ' data-filter-option-search="' + escapeHtml(option.label.toLowerCase()) + '"'
        + ' aria-selected="' + (isSelected ? "true" : "false") + '">'
        + '<span class="attribute-filter-value-check" aria-hidden="true">&#10003;</span>'
        + '<span class="attribute-filter-value-label">' + escapeHtml(option.label) + "</span>"
        + "</button>";
    }).join("");
    var pickerId = "attribute-filter-options-" + attribute.id;

    return '<div class="attribute-filter-value-picker" data-filter-value-picker data-selected-count="'
      + selected.length + '">'
      + '<div class="attribute-filter-multiselect" data-filter-multiselect>'
      + '<div class="attribute-filter-tag-list">' + tags
      + '<input type="search" class="attribute-filter-multiselect-input"'
      + ' data-filter-option-search-input role="combobox" aria-autocomplete="list"'
      + ' aria-expanded="false" aria-controls="' + pickerId + '"'
      + ' aria-label="Search ' + escapeHtml(attribute.name) + ' options"'
      + ' autocomplete="off" placeholder="Search…"></div>'
      + (selected.length
        ? '<button type="button" class="attribute-filter-multiselect-clear" data-filter-options-clear aria-label="Clear selected options">&times;</button>'
        : "")
      + "</div>"
      + '<div id="' + pickerId + '" class="attribute-filter-value-menu"'
      + ' data-filter-value-menu role="listbox" aria-multiselectable="true" hidden>'
      + options
      + '<div class="attribute-filter-value-empty" data-filter-option-empty hidden>No matching options</div>'
      + "</div></div>";
  }

  function inputHtml(attribute, filter, field, label, inputType) {
    var currency = attribute.type === "money" ? attribute.currency : "";
    var currencyDisplay = CURRENCY_SYMBOLS[currency] || currency;
    var value = String(filter && filter[field] != null ? filter[field] : "");
    return '<span class="attribute-filter-input-shell"'
      + (currency ? ' data-currency="' + escapeHtml(currency) + '"' : "") + ">"
      + '<input class="attribute-filter-input" type="' + inputType + '"'
      + (inputType === "text" ? ' inputmode="decimal"' : "")
      + ' data-filter-field="' + field + '" value="' + escapeHtml(value) + '"'
      + ' aria-label="' + escapeHtml(attribute.name + " " + label) + '"'
      + (attribute.type === "text" ? ' maxlength="500"' : "") + ">"
      + (currency ? '<span class="attribute-filter-input-addon">' + escapeHtml(currencyDisplay) + "</span>" : "")
      + "</span>";
  }

  function valueControlHtml(attribute, filter) {
    if (!filter || !filter.op || EMPTY_OPERATORS.has(filter.op)) return "";
    if (attribute.type === "single_select") return multiselectHtml(attribute, filter);

    if (attribute.type === "number" || attribute.type === "money") {
      if (filter.op === "between") {
        return '<span class="attribute-filter-range">'
          + inputHtml(attribute, filter, "min", "minimum", "text")
          + inputHtml(attribute, filter, "max", "maximum", "text")
          + "</span>";
      }
      return inputHtml(attribute, filter, "value", "value", "text");
    }

    if (attribute.type === "text") {
      return '<span class="attribute-filter-input-shell">'
        + '<input class="attribute-filter-input" type="text" data-filter-field="value"'
        + ' value="' + escapeHtml(filter.value || "") + '" maxlength="500"'
        + ' aria-label="' + escapeHtml(attribute.name + " text") + '"></span>';
    }

    if (attribute.type === "date") {
      if (filter.op === "between") {
        return '<span class="attribute-filter-date-range">'
          + inputHtml(attribute, filter, "from", "start date", "date")
          + inputHtml(attribute, filter, "to", "end date", "date")
          + "</span>";
      }
      return inputHtml(attribute, filter, "value", "date", "date");
    }
    return "";
  }

  function booleanControlHtml(attribute, filter) {
    var currentValue = filter && filter.op === "eq" ? String(filter.value) : "";
    return '<div class="attribute-filter-segment" role="group" aria-labelledby="attribute-filter-label-'
      + attribute.id + '">'
      + '<button type="button" data-filter-boolean-value="" aria-pressed="'
      + (currentValue === "" ? "true" : "false") + '">Any</button>'
      + '<button type="button" data-filter-boolean-value="true" aria-pressed="'
      + (currentValue === "true" ? "true" : "false") + '">Yes</button>'
      + '<button type="button" data-filter-boolean-value="false" aria-pressed="'
      + (currentValue === "false" ? "true" : "false") + '">No</button>'
      + "</div>";
  }

  function renderRowHtml(attribute, filter) {
    var active = Boolean(filter && filter.op);
    var control = attribute.type === "boolean"
      ? booleanControlHtml(attribute, filter)
      : '<select class="attribute-filter-select" data-filter-operator'
        + ' aria-labelledby="attribute-filter-label-' + attribute.id + '">'
        + operatorOptionsHtml(attribute, active ? filter.op : "") + "</select>"
        + valueControlHtml(attribute, filter);
    var errorId = "attribute-filter-error-" + attribute.id;

    return '<div class="company-attribute-filter-row" data-filter-row data-attribute-id="'
      + attribute.id + '" data-active="' + (active ? "true" : "false") + '">'
      + '<div class="company-attribute-filter-label" id="attribute-filter-label-' + attribute.id + '">'
      + '<span class="company-attribute-filter-name" title="' + escapeHtml(attribute.name) + '">'
      + escapeHtml(attribute.name) + "</span>"
      + '<span class="company-attribute-filter-type">' + escapeHtml(attribute.typeLabel) + "</span>"
      + "</div>"
      + '<div class="company-attribute-filter-control">' + control
      + (active
        ? '<button type="button" class="attribute-filter-clear" data-filter-row-clear>Clear</button>'
        : "")
      + '<p id="' + errorId + '" class="attribute-filter-error" data-filter-error role="alert" hidden></p>'
      + "</div></div>";
  }

  function actionButtonHtml(action, label, variant) {
    return '<button type="button" class="attribute-filter-action attribute-filter-action-'
      + variant + '" data-attribute-filter-action="' + action + '">'
      + escapeHtml(label) + "</button>";
  }

  function footerActionsHtml(mode, canSaveSegments) {
    if (mode === "edit-segment") {
      return actionButtonHtml("cancel", "Cancel", "secondary")
        + actionButtonHtml("save-changes", "Save changes", "primary");
    }
    return (canSaveSegments ? actionButtonHtml("save-as", "Save as segment…", "tertiary") : "")
      + actionButtonHtml("apply", "Apply", "primary");
  }

  function summaryText(summary) {
    if (typeof summary === "string") return summary;
    if (!summary || typeof summary !== "object") return "";
    return String(summary.text || summary.summary || summary.label || "");
  }

  function deletedAttributeDetail(record) {
    if (!record || typeof record !== "object") return "";
    var supplied = String(record.detail || "").trim();
    if (supplied) return supplied;
    var name = String(record.attributeName || record.name || "").trim();
    if (!name) return "";
    var actor = String(record.deletedBy || "").trim();
    var when = String(record.deletedOn || "").trim();
    return '"' + name + '" was deleted'
      + (actor ? " by " + actor : "")
      + (when ? " on " + when : "")
      + ".";
  }

  /**
   * What the editor owes the owner of a segment that outlived one of its
   * attributes. The deleted conditions have no row to appear in, so the notice
   * is the only account of why the segment no longer says what it used to.
   */
  function segmentReviewNotice(segment) {
    var records = segment && Array.isArray(segment.deletedAttributes)
      ? segment.deletedAttributes
      : [];
    var details = records.map(deletedAttributeDetail).filter(Boolean);
    if (!details.length) return null;
    return {
      title: details.length === 1
        ? "A company attribute used by this segment was deleted"
        : "Company attributes used by this segment were deleted",
      details: details,
      copy: "Their conditions were removed from this editor. Review the remaining"
        + " filters and save to confirm what this segment should match.",
    };
  }

  function preserveCompanyAttributeParamsInLinks(documentRef, currentHref) {
    var currentUrl;
    try {
      currentUrl = new URL(currentHref);
    } catch (error) {
      return;
    }
    var companyAttributePairs = Array.from(currentUrl.searchParams.entries()).filter(function (pair) {
      return pair[0].indexOf("ca.") === 0 || pair[0] === SEGMENT_PARAMETER;
    });
    if (!companyAttributePairs.length) return;

    documentRef.querySelectorAll(
      '[data-overview-filters] a[href], .visits-filter--range a[href]'
    ).forEach(function (link) {
      var targetUrl;
      try {
        targetUrl = new URL(link.getAttribute("href"), currentUrl);
      } catch (error) {
        return;
      }
      removeCompanyAttributeParams(targetUrl.searchParams);
      targetUrl.searchParams.delete("page");
      targetUrl.searchParams.delete(SEGMENT_PARAMETER);
      companyAttributePairs.forEach(function (pair) {
        targetUrl.searchParams.append(pair[0], pair[1]);
      });
      link.setAttribute("href", targetUrl.pathname + targetUrl.search + targetUrl.hash);
    });
  }

  function initRoot(root, documentRef) {
    if (root.dataset.companyAttributeFilterReady === "true") return null;
    root.dataset.companyAttributeFilterReady = "true";

    var view = documentRef.defaultView || (typeof window !== "undefined" ? window : null);
    if (!view) return null;
    var payload = readPayload(documentRef);
    var attributes = normalizeAttributes(payload.attributes);
    var summary = documentRef.querySelector("[data-attribute-filter-summary]");
    var dialog = root.querySelector(".company-attribute-filter-dialog");
    var title = root.querySelector("[data-attribute-filter-title]");
    var subtitle = root.querySelector("[data-attribute-filter-subtitle]");
    var context = root.querySelector("[data-attribute-filter-context]");
    var contextText = root.querySelector("[data-attribute-filter-context-text]");
    var review = root.querySelector("[data-attribute-filter-review]");
    var reviewTitle = root.querySelector("[data-attribute-filter-review-title]");
    var reviewList = root.querySelector("[data-attribute-filter-review-list]");
    var reviewCopy = root.querySelector("[data-attribute-filter-review-copy]");
    var rows = root.querySelector("[data-attribute-filter-rows]");
    var reset = root.querySelector("[data-attribute-filter-reset]");
    var actions = root.querySelector("[data-attribute-filter-actions]");
    var draftError = root.querySelector("[data-attribute-filter-draft-error]");
    var previewLabel = root.querySelector("[data-attribute-filter-preview-label]");
    var previewFill = root.querySelector("[data-attribute-filter-preview-fill]");
    var hasAttributes = root.dataset.hasAttributes === "true" && Boolean(rows);
    var previewUrl = root.dataset.previewUrl
      || payload.previewUrl
      || payload.preview_url
      || "";
    var surface = root.dataset.surface || payload.surface || "";
    var initialApplied = extractPayloadState(payload, attributes, view.location.href);
    var draft = cloneState(initialApplied);
    var previewTimer = null;
    var previewController = null;
    var previewSequence = 0;
    var open = false;
    // Attribute rows whose error the last submission raised. Editing a row
    // removes it, so a new error only appears on the next submission.
    var errorAttributeIds = new Set();
    var pending = false;
    var session = null;

    preserveCompanyAttributeParamsInLinks(documentRef, view.location.href);

    function anchorElement() {
      return (session && session.anchor)
        || documentRef.querySelector("[data-company-scope-trigger]");
    }

    function renderSummaryChips() {
      var summaries = payloadValue(payload, "summaries", "summaries");
      if (!summary) return;
      summary.replaceChildren();
      (Array.isArray(summaries) ? summaries : []).forEach(function (item) {
        var text = summaryText(item);
        if (!text) return;
        var chip = documentRef.createElement("span");
        chip.className = "attribute-filter-summary-chip";
        chip.textContent = text;
        summary.appendChild(chip);
      });
      summary.hidden = !summary.children.length;
    }

    function renderPreview(matchingCount, eligibleCount) {
      if (!previewLabel || !previewFill) return;
      var matching = Math.max(0, Number(matchingCount) || 0);
      var eligible = Math.max(0, Number(eligibleCount) || 0);
      var percentage = eligible ? Math.min(100, Math.max(0, matching / eligible * 100)) : 0;
      previewLabel.textContent = matching + " of " + eligible + " companies match";
      previewFill.style.setProperty("--preview-width", percentage.toFixed(2) + "%");
    }

    function renderPreviewMessage(message, loading) {
      if (!previewLabel) return;
      previewLabel.replaceChildren();
      if (loading) {
        var spinner = documentRef.createElement("span");
        spinner.className = "attribute-filter-spinner";
        spinner.setAttribute("aria-hidden", "true");
        previewLabel.appendChild(spinner);
      }
      previewLabel.appendChild(documentRef.createTextNode(message));
    }

    function cancelPreview() {
      if (previewTimer !== null) {
        view.clearTimeout(previewTimer);
        previewTimer = null;
      }
      if (previewController) {
        previewController.abort();
        previewController = null;
      }
      previewSequence += 1;
    }

    function fetchPreview() {
      previewTimer = null;
      if (!open || !previewUrl) return;
      if (previewController) previewController.abort();
      previewController = new view.AbortController();
      var requestSequence = ++previewSequence;
      var requestUrl = buildPreviewUrl(
        previewUrl,
        view.location.href,
        surface,
        attributes,
        draft
      );
      renderPreviewMessage("Updating preview…", true);

      view.fetch(requestUrl, {
        method: "GET",
        credentials: "same-origin",
        headers: {
          Accept: "application/json",
          "X-Requested-With": "XMLHttpRequest",
        },
        signal: previewController.signal,
      })
        .then(function (response) {
          if (!response.ok) throw new Error("Preview request failed");
          return response.json();
        })
        .then(function (responsePayload) {
          if (!open || requestSequence !== previewSequence) return;
          var preview = responsePayload && responsePayload.preview
            ? responsePayload.preview
            : responsePayload || {};
          renderPreview(
            preview.matching_count !== undefined ? preview.matching_count : preview.matchingCount,
            preview.eligible_count !== undefined ? preview.eligible_count : preview.eligibleCount
          );
        })
        .catch(function (error) {
          if (error && error.name === "AbortError") return;
          if (!open || requestSequence !== previewSequence) return;
          renderPreviewMessage("Preview unavailable. Try changing a filter.", false);
        });
    }

    function schedulePreview(validation) {
      cancelPreview();
      if (!validation.valid) {
        renderPreviewMessage("Finish the filter conditions to preview matches.", false);
        return;
      }
      if (!previewUrl) {
        renderPreviewMessage("Preview is unavailable.", false);
        return;
      }
      previewTimer = view.setTimeout(fetchPreview, PREVIEW_DELAY_MS);
    }

    function renderRowErrors(validation) {
      if (!rows) return;
      rows.querySelectorAll("[data-filter-row]").forEach(function (row) {
        var attributeId = row.dataset.attributeId;
        var message = errorAttributeIds.has(attributeId)
          ? validation.errors[attributeId] || ""
          : "";
        var error = row.querySelector("[data-filter-error]");
        row.dataset.invalid = message ? "true" : "false";
        row.querySelectorAll("input, select").forEach(function (control) {
          if (message) {
            control.setAttribute("aria-invalid", "true");
            control.setAttribute("aria-describedby", "attribute-filter-error-" + attributeId);
          } else {
            control.removeAttribute("aria-invalid");
            control.removeAttribute("aria-describedby");
          }
        });
        if (error) {
          error.textContent = message;
          error.hidden = !message;
        }
      });
    }

    function applyValidation(validation, requestPreview) {
      renderRowErrors(validation);
      if (reset) reset.hidden = validation.activeCount === 0;
      if (requestPreview) schedulePreview(validation);
      return validation;
    }

    function refreshDraft(requestPreview) {
      return applyValidation(validateDraft(attributes, draft), requestPreview);
    }

    function noteDraftEdit(attributeId) {
      errorAttributeIds.delete(String(attributeId));
      setDraftError("");
    }

    function setDraftError(message) {
      if (!draftError) return;
      draftError.textContent = message || "";
      draftError.hidden = !message;
    }

    function focusRowControl(attributeId, selector) {
      view.requestAnimationFrame(function () {
        if (!rows) return;
        var row = rows.querySelector('[data-attribute-id="' + attributeId + '"]');
        var control = row && row.querySelector(selector || "input, select, button");
        if (control) control.focus();
      });
    }

    function renderRows(focusAttributeId, focusSelector, reopenPicker) {
      if (!rows) return;
      rows.innerHTML = attributes.map(function (attribute) {
        return renderRowHtml(attribute, draft[attribute.id]);
      }).join("");
      refreshDraft(true);

      if (focusAttributeId) {
        focusRowControl(focusAttributeId, focusSelector);
        if (reopenPicker) {
          view.requestAnimationFrame(function () {
            var row = rows.querySelector('[data-attribute-id="' + focusAttributeId + '"]');
            var picker = row && row.querySelector("[data-filter-value-picker]");
            if (picker) openValuePicker(picker);
          });
        }
      }
    }

    function closeValuePickers(exceptPicker) {
      if (!rows) return;
      rows.querySelectorAll("[data-filter-value-picker]").forEach(function (picker) {
        if (picker === exceptPicker) return;
        var menu = picker.querySelector("[data-filter-value-menu]");
        var input = picker.querySelector("[data-filter-option-search-input]");
        if (menu) menu.hidden = true;
        if (input) input.setAttribute("aria-expanded", "false");
      });
    }

    function positionValueMenu(picker) {
      var menu = picker.querySelector("[data-filter-value-menu]");
      var anchor = picker.querySelector("[data-filter-multiselect]");
      if (!menu || !anchor || menu.hidden) return;
      var rect = anchor.getBoundingClientRect();
      var viewportWidth = documentRef.documentElement.clientWidth;
      var viewportHeight = documentRef.documentElement.clientHeight;
      var width = Math.max(rect.width, 240);
      var menuHeight = Math.min(menu.scrollHeight || 300, 300);
      var below = viewportHeight - rect.bottom - 12;
      var above = rect.top - 12;
      var openAbove = below < Math.min(menuHeight, 180) && above > below;
      var top = openAbove
        ? Math.max(12, rect.top - Math.min(menuHeight, above) - 6)
        : rect.bottom + 6;
      var left = Math.max(12, Math.min(rect.left, viewportWidth - width - 12));
      menu.style.setProperty("--value-menu-top", Math.round(top) + "px");
      menu.style.setProperty("--value-menu-left", Math.round(left) + "px");
      menu.style.setProperty("--attribute-filter-value-menu-width", Math.round(width) + "px");
      menu.style.setProperty("--value-menu-max-height", Math.max(120, openAbove ? above - 6 : below - 6) + "px");
    }

    function openValuePicker(picker) {
      closeValuePickers(picker);
      var menu = picker.querySelector("[data-filter-value-menu]");
      var input = picker.querySelector("[data-filter-option-search-input]");
      if (!menu || !input) return;
      menu.hidden = false;
      input.setAttribute("aria-expanded", "true");
      positionValueMenu(picker);
    }

    function filterValueOptions(input) {
      var picker = input.closest("[data-filter-value-picker]");
      var query = input.value.trim().toLowerCase();
      var visible = 0;
      picker.querySelectorAll("[data-filter-option-id]").forEach(function (option) {
        var matches = !query || (option.dataset.filterOptionSearch || "").includes(query);
        option.hidden = !matches;
        if (matches) visible += 1;
      });
      var empty = picker.querySelector("[data-filter-option-empty]");
      if (empty) empty.hidden = visible !== 0;
      openValuePicker(picker);
    }

    function attributeForRow(row) {
      var id = row && row.dataset.attributeId;
      return attributes.find(function (attribute) { return attribute.id === id; });
    }

    function positionDialog() {
      var anchor = anchorElement();
      if (!anchor || !open) return;
      var edgeGap = 12;
      var anchorGap = 8;
      var triggerRect = anchor.getBoundingClientRect();
      var viewportWidth = documentRef.documentElement.clientWidth;
      var viewportHeight = documentRef.documentElement.clientHeight;
      var dialogWidth = Math.min(900, viewportWidth - edgeGap * 2);
      var left = Math.min(
        Math.max(edgeGap, triggerRect.left),
        Math.max(edgeGap, viewportWidth - dialogWidth - edgeGap)
      );
      var spaceBelow = viewportHeight - triggerRect.bottom - anchorGap - edgeGap;
      var spaceAbove = triggerRect.top - anchorGap - edgeGap;
      var openAbove = spaceBelow < 360 && spaceAbove > spaceBelow;
      var availableHeight = Math.max(240, openAbove ? spaceAbove : spaceBelow);
      var naturalHeight = Math.min(dialog.scrollHeight, availableHeight);
      var top = openAbove
        ? Math.max(edgeGap, triggerRect.top - anchorGap - naturalHeight)
        : Math.max(
          edgeGap,
          Math.min(
            triggerRect.bottom + anchorGap,
            Math.max(edgeGap, viewportHeight - edgeGap - naturalHeight)
          )
        );
      root.style.setProperty("--attribute-filter-popup-top", Math.round(top) + "px");
      root.style.setProperty("--attribute-filter-popup-left", Math.round(left) + "px");
      root.style.setProperty("--attribute-filter-popup-max-height", Math.round(availableHeight) + "px");
    }

    function focusableElements() {
      return Array.from(
        dialog.querySelectorAll(
          'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'
        )
      ).filter(function (element) {
        return !element.hidden && !element.closest("[hidden]");
      });
    }

    function renderReviewNotice(notice) {
      if (!review) return;
      if (reviewTitle) reviewTitle.textContent = notice ? notice.title : "";
      if (reviewList) {
        reviewList.replaceChildren();
        (notice ? notice.details : []).forEach(function (detail) {
          var item = documentRef.createElement("li");
          item.textContent = detail;
          reviewList.appendChild(item);
        });
      }
      if (reviewCopy) reviewCopy.textContent = notice ? notice.copy : "";
      review.hidden = !notice;
    }

    function renderChrome() {
      var mode = session && session.mode === "edit-segment" ? "edit-segment" : "filter";
      if (title) {
        title.textContent = mode === "edit-segment"
          ? "Edit company segment"
          : "Filter by company attributes";
      }
      if (subtitle) {
        var subtitleText = mode === "edit-segment" && session.segment ? session.segment.name : "";
        subtitle.textContent = subtitleText;
        subtitle.hidden = !subtitleText;
      }
      if (context && contextText) {
        var basedOn = mode === "filter" && session && session.segment ? session.segment : null;
        contextText.textContent = basedOn ? "Using segment: " + basedOn.name : "";
        context.hidden = !basedOn;
      }
      renderReviewNotice(
        mode === "edit-segment" && session ? segmentReviewNotice(session.segment) : null
      );
      if (actions) {
        actions.innerHTML = footerActionsHtml(mode, Boolean(session && session.canSaveSegments));
      }
      setDraftError("");
    }

    function updateSegmentContext() {
      if (!context || !contextText) return;
      if (!session || session.mode !== "filter" || !session.segment) return;
      var changed = JSON.stringify(canonicalPairs(attributes, draft))
        !== JSON.stringify(canonicalPairs(attributes, session.segment.definition || {}));
      contextText.textContent = changed
        ? "Custom filter based on " + session.segment.name + ". The saved segment won’t be changed."
        : "Using segment: " + session.segment.name;
    }

    function openDialog(options) {
      if (open) {
        // Reopening replaces the session outright; the previous one gets no
        // close callback because nothing was dismissed.
        session = null;
        closeDialog(false);
      }
      session = {
        mode: options && options.mode === "edit-segment" ? "edit-segment" : "filter",
        segment: (options && options.segment) || null,
        canSaveSegments: Boolean(options && options.canSaveSegments),
        anchor: (options && options.anchor) || null,
        onApply: (options && options.onApply) || null,
        onSaveAs: (options && options.onSaveAs) || null,
        onSaveChanges: (options && options.onSaveChanges) || null,
        onClose: (options && options.onClose) || null,
      };
      open = true;
      errorAttributeIds = new Set();
      pending = false;
      draft = options && options.definition
        ? normalizeApplied(options.definition, attributes)
        : cloneState(initialApplied);
      root.hidden = false;
      renderChrome();
      if (hasAttributes) {
        renderRows();
        updateSegmentContext();
        var initialPreview = payload.preview
          || (payload.state && payload.state.preview)
          || null;
        if (initialPreview) {
          renderPreview(
            initialPreview.matching_count !== undefined
              ? initialPreview.matching_count
              : initialPreview.matchingCount,
            initialPreview.eligible_count !== undefined
              ? initialPreview.eligible_count
              : initialPreview.eligibleCount
          );
        }
      }
      positionDialog();
      view.requestAnimationFrame(function () {
        positionDialog();
        var firstControl = hasAttributes && rows
          ? rows.querySelector("[data-filter-operator], [data-filter-boolean-value]")
          : dialog.querySelector("[data-attribute-filter-close], a[href]");
        (firstControl || dialog).focus();
      });
    }

    function closeDialog(restoreFocus) {
      if (!open || pending) return;
      var closingSession = session;
      open = false;
      session = null;
      cancelPreview();
      closeValuePickers();
      draft = cloneState(initialApplied);
      errorAttributeIds = new Set();
      root.hidden = true;
      setDraftError("");
      if (closingSession && closingSession.onClose) {
        closingSession.onClose({ restoreFocus: restoreFocus !== false });
      } else if (restoreFocus !== false) {
        var anchor = anchorElement();
        if (anchor) anchor.focus();
      }
    }

    function submitValidation() {
      var validation = validateDraft(attributes, draft);
      errorAttributeIds = new Set(Object.keys(validation.errors));
      applyValidation(validation, false);
      if (!validation.valid && rows) {
        var invalidRow = rows.querySelector('[data-invalid="true"]');
        var invalidControl = invalidRow && invalidRow.querySelector("input, select, button");
        if (invalidControl) invalidControl.focus();
      }
      return validation;
    }

    function setPending(isPending, button) {
      pending = Boolean(isPending);
      root.dataset.pending = pending ? "true" : "false";
      if (dialog) dialog.setAttribute("aria-busy", pending ? "true" : "false");
      if (actions) {
        actions.querySelectorAll("button").forEach(function (control) {
          control.disabled = pending;
        });
      }
      if (button) button.setAttribute("aria-busy", pending ? "true" : "false");
      var documentElement = documentRef.documentElement;
      if (documentElement) {
        if (pending) documentElement.dataset.companyScopeBusy = "true";
        else delete documentElement.dataset.companyScopeBusy;
      }
    }

    function handleAction(action, button) {
      if (pending || !session) return;
      if (action === "cancel") {
        closeDialog(true);
        return;
      }
      if (action === "apply" && session.onApply) {
        var applyValidationResult = submitValidation();
        if (!applyValidationResult.valid) return;
        session.onApply(cloneState(draft), button);
        return;
      }
      if (action === "save-as" && session.onSaveAs) {
        var saveAsValidation = submitValidation();
        if (!saveAsValidation.valid) return;
        if (!saveAsValidation.activeCount) {
          setDraftError("Add at least one company attribute condition before saving a segment.");
          return;
        }
        session.onSaveAs(cloneState(draft), button);
        return;
      }
      if (action === "save-changes" && session.onSaveChanges) {
        var saveValidation = submitValidation();
        if (!saveValidation.valid) return;
        if (!saveValidation.activeCount) {
          setDraftError("Add at least one company attribute condition before saving a segment.");
          return;
        }
        session.onSaveChanges(cloneState(draft), button);
      }
    }

    renderSummaryChips();

    if (!dialog) return null;

    root.addEventListener("click", function (event) {
      var actionButton = event.target.closest("[data-attribute-filter-action]");
      if (actionButton) {
        handleAction(actionButton.dataset.attributeFilterAction, actionButton);
        return;
      }

      var closeButton = event.target.closest("[data-attribute-filter-close]");
      if (closeButton) {
        closeDialog(true);
        return;
      }

      if (!hasAttributes || pending) return;
      var row = event.target.closest("[data-filter-row]");
      var attribute = attributeForRow(row);
      if (!row || !attribute) return;
      var attributeId = attribute.id;

      var clearRow = event.target.closest("[data-filter-row-clear]");
      if (clearRow) {
        noteDraftEdit(attributeId);
        delete draft[attributeId];
        renderRows(attributeId, attribute.type === "boolean"
          ? '[data-filter-boolean-value=""]'
          : "[data-filter-operator]");
        updateSegmentContext();
        return;
      }

      var booleanButton = event.target.closest("[data-filter-boolean-value]");
      if (booleanButton) {
        noteDraftEdit(attributeId);
        var booleanValue = booleanButton.dataset.filterBooleanValue;
        if (booleanValue) draft[attributeId] = { op: "eq", value: booleanValue };
        else delete draft[attributeId];
        renderRows(
          attributeId,
          '[data-filter-boolean-value="' + booleanValue + '"]'
        );
        updateSegmentContext();
        return;
      }

      var removeOption = event.target.closest("[data-filter-option-remove]");
      if (removeOption) {
        noteDraftEdit(attributeId);
        var selectedFilter = draft[attributeId];
        selectedFilter.values = (selectedFilter.values || []).filter(function (optionId) {
          return String(optionId) !== removeOption.dataset.filterOptionRemove;
        });
        renderRows(attributeId, "[data-filter-option-search-input]", true);
        updateSegmentContext();
        return;
      }

      var clearOptions = event.target.closest("[data-filter-options-clear]");
      if (clearOptions) {
        noteDraftEdit(attributeId);
        draft[attributeId].values = [];
        renderRows(attributeId, "[data-filter-option-search-input]", true);
        updateSegmentContext();
        return;
      }

      var option = event.target.closest("[data-filter-option-id]");
      if (option) {
        noteDraftEdit(attributeId);
        var optionId = option.dataset.filterOptionId;
        var filter = draft[attributeId];
        var values = new Set((filter.values || []).map(String));
        if (values.has(optionId)) values.delete(optionId);
        else values.add(optionId);
        filter.values = Array.from(values);
        renderRows(attributeId, "[data-filter-option-search-input]", true);
        updateSegmentContext();
        return;
      }

      var picker = event.target.closest("[data-filter-value-picker]");
      if (picker) {
        if (event.target.closest("[data-filter-multiselect]")) openValuePicker(picker);
      } else {
        closeValuePickers();
      }
    });

    root.addEventListener("change", function (event) {
      var operator = event.target.closest("[data-filter-operator]");
      if (!operator || pending) return;
      var row = operator.closest("[data-filter-row]");
      var attribute = attributeForRow(row);
      if (!attribute) return;
      noteDraftEdit(attribute.id);
      if (!operator.value) {
        delete draft[attribute.id];
        renderRows(attribute.id, "[data-filter-operator]");
        updateSegmentContext();
        return;
      }
      var filter = { op: operator.value };
      if (attribute.type === "single_select" && ["in", "not_in"].includes(filter.op)) {
        filter.values = [];
      }
      draft[attribute.id] = filter;
      renderRows(
        attribute.id,
        attribute.type === "single_select" && ["in", "not_in"].includes(filter.op)
          ? "[data-filter-option-search-input]"
          : "[data-filter-field], [data-filter-operator]",
        attribute.type === "single_select" && ["in", "not_in"].includes(filter.op)
      );
      updateSegmentContext();
    });

    root.addEventListener("input", function (event) {
      var optionSearch = event.target.closest("[data-filter-option-search-input]");
      if (optionSearch) {
        filterValueOptions(optionSearch);
        return;
      }
      var input = event.target.closest("[data-filter-field]");
      if (!input) return;
      var row = input.closest("[data-filter-row]");
      var attribute = attributeForRow(row);
      if (!attribute || !draft[attribute.id]) return;
      draft[attribute.id][input.dataset.filterField] = input.value;
      noteDraftEdit(attribute.id);
      refreshDraft(true);
      updateSegmentContext();
    });

    root.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        event.preventDefault();
        closeDialog(true);
        return;
      }

      var search = event.target.closest("[data-filter-option-search-input]");
      if (search && ["ArrowDown", "Enter"].includes(event.key)) {
        var searchPicker = search.closest("[data-filter-value-picker]");
        openValuePicker(searchPicker);
        var firstOption = searchPicker.querySelector("[data-filter-option-id]:not([hidden])");
        if (firstOption) {
          event.preventDefault();
          if (event.key === "Enter") firstOption.click();
          else firstOption.focus();
        }
        return;
      }

      var option = event.target.closest("[data-filter-option-id]");
      if (option) {
        var picker = option.closest("[data-filter-value-picker]");
        var visibleOptions = Array.from(
          picker.querySelectorAll("[data-filter-option-id]:not([hidden])")
        );
        var index = visibleOptions.indexOf(option);
        if (event.key === "ArrowDown" || event.key === "ArrowUp") {
          event.preventDefault();
          var direction = event.key === "ArrowDown" ? 1 : -1;
          visibleOptions[(index + direction + visibleOptions.length) % visibleOptions.length].focus();
        } else if (event.key === "Home" || event.key === "End") {
          event.preventDefault();
          visibleOptions[event.key === "Home" ? 0 : visibleOptions.length - 1].focus();
        } else if (event.key === " " || event.key === "Enter") {
          event.preventDefault();
          option.click();
        }
        return;
      }

      if (event.key === "Tab") {
        var focusable = focusableElements();
        if (!focusable.length) {
          event.preventDefault();
          dialog.focus();
          return;
        }
        var first = focusable[0];
        var last = focusable[focusable.length - 1];
        if (event.shiftKey && documentRef.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && documentRef.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    });

    if (reset) {
      reset.addEventListener("click", function () {
        if (pending) return;
        draft = {};
        errorAttributeIds = new Set();
        setDraftError("");
        renderRows();
        updateSegmentContext();
        var firstControl = rows && rows.querySelector("[data-filter-operator], [data-filter-boolean-value]");
        if (firstControl) firstControl.focus();
      });
    }

    documentRef.addEventListener("pointerdown", function (event) {
      if (!open || pending) return;
      if (root.contains(event.target)) return;
      var anchor = anchorElement();
      if (anchor && anchor.contains(event.target)) return;
      if (event.target.closest && event.target.closest("[data-company-segment-dialog-layer]")) return;
      closeDialog(false);
    });

    view.addEventListener("resize", function () {
      if (open) {
        positionDialog();
        closeValuePickers();
      }
    });
    view.addEventListener("scroll", function (event) {
      if (open) {
        if (event.target && event.target.closest
          && event.target.closest("[data-filter-value-menu]")) {
          return;
        }
        positionDialog();
        closeValuePickers();
      }
    }, true);

    return {
      root: root,
      attributes: attributes,
      payload: payload,
      hasAttributes: hasAttributes,
      appliedState: function () { return cloneState(initialApplied); },
      isOpen: function () { return open; },
      open: openDialog,
      close: closeDialog,
      draft: function () { return cloneState(draft); },
      setPending: setPending,
      setDraftError: setDraftError,
    };
  }

  var controllers = [];

  function init(documentRef) {
    if (!documentRef || !documentRef.querySelectorAll) return;
    documentRef.querySelectorAll("[data-company-attribute-filter-root]").forEach(function (root) {
      var controller = initRoot(root, documentRef);
      if (controller) controllers.push(controller);
    });
  }

  function getController(documentRef) {
    if (!documentRef) return controllers[0] || null;
    return controllers.find(function (controller) {
      return documentRef.contains(controller.root);
    }) || null;
  }

  return {
    init: init,
    getController: getController,
    normalizeAttributes: normalizeAttributes,
    normalizeApplied: normalizeApplied,
    parseStateFromUrl: parseStateFromUrl,
    compareDecimalStrings: compareDecimalStrings,
    validateDraft: validateDraft,
    canonicalPairs: canonicalPairs,
    buildApplyUrl: buildApplyUrl,
    buildPreviewUrl: buildPreviewUrl,
    preserveCompanyAttributeParamsInLinks: preserveCompanyAttributeParamsInLinks,
    segmentReviewNotice: segmentReviewNotice,
  };
});
