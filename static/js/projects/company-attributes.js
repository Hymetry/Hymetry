(function () {
  "use strict";

  const root = document.querySelector("[data-company-attributes-root]");
  if (!root) return;

  const pageState = root.querySelector("[data-company-attributes-page-state]");
  const pageFeedback = root.querySelector("[data-page-feedback]");
  const searchInput = root.querySelector("[data-company-search]");
  const managerOpen = root.querySelector("[data-manage-attributes-open]");
  const managerModal = root.querySelector("[data-attributes-manager]");
  const managerDialog = root.querySelector("[data-attributes-manager-dialog]");
  const managerList = root.querySelector("[data-attributes-list]");
  const managerEditor = root.querySelector("[data-attribute-editor]");
  const managerSaveError = root.querySelector("[data-attributes-save-error]");
  const managerSave = root.querySelector("[data-attributes-save]");
  const managerAdd = root.querySelector("[data-add-attribute]");
  const managerFooter = root.querySelector("[data-manager-footer]");
  const reorderStatus = root.querySelector("[data-reorder-status]");
  const colorMenu = root.querySelector("[data-option-color-menu]");
  const colorGrid = root.querySelector("[data-option-color-grid]");
  const valuesModal = root.querySelector("[data-company-values-modal]");
  const valuesDialog = root.querySelector("[data-company-values-dialog]");
  const valuesTitle = root.querySelector("[data-company-values-title]");
  const valuesForm = root.querySelector("[data-company-values-form]");
  const valuesSaveError = root.querySelector("[data-company-values-save-error]");
  const valuesSave = root.querySelector("[data-company-values-save]");
  const discardModal = root.querySelector("[data-attributes-discard-modal]");
  const discardDialog = root.querySelector("[data-attributes-discard-dialog]");

  const typeMeta = {
    text: {
      label: "Text",
      copy: "Use Text for notes, IDs, owners, links, or other free-form company context."
    },
    number: {
      label: "Number",
      copy: "Use Number for employees, seats, scores, or other numeric values."
    },
    money: {
      label: "Money",
      copy: "Money values are formatted with the selected currency and display format."
    },
    date: {
      label: "Date",
      copy: "Use Date for time-based company attributes such as renewal dates or contract start dates."
    },
    boolean: {
      label: "Boolean",
      copy: "Use Boolean for true or false attributes such as Strategic, Has CSM, or Onboarding complete."
    },
    single_select: {
      label: "Single select",
      copy: "Single select keeps category values consistent across companies."
    }
  };

  const moneyCurrencies = [
    "USD", "EUR", "GBP", "AED", "AUD", "BGN", "BRL", "CAD", "CHF", "CNY",
    "CZK", "DKK", "HKD", "HUF", "ILS", "INR", "JPY", "KRW", "MXN", "NOK",
    "NZD", "PLN", "RON", "SAR", "SEK", "SGD", "TRY", "UAH", "ZAR"
  ];

  const colors = [
    ["Red", "#B91C1C", "#FEE2E2", "#FECACA"],
    ["Orange", "#C2410C", "#FFEDD5", "#FED7AA"],
    ["Amber", "#B45309", "#FEF3C7", "#FDE68A"],
    ["Yellow", "#A16207", "#FEF9C3", "#FEF08A"],
    ["Lime", "#4D7C0F", "#ECFCCB", "#D9F99D"],
    ["Green", "#15803D", "#DCFCE7", "#BBF7D0"],
    ["Emerald", "#047857", "#D1FAE5", "#A7F3D0"],
    ["Teal", "#0F766E", "#CCFBF1", "#99F6E4"],
    ["Cyan", "#0E7490", "#CFFAFE", "#A5F3FC"],
    ["Sky", "#0369A1", "#E0F2FE", "#BAE6FD"],
    ["Blue", "#1D4ED8", "#DBEAFE", "#BFDBFE"],
    ["Indigo", "#4338CA", "#E0E7FF", "#C7D2FE"],
    ["Violet", "#6D28D9", "#EDE9FE", "#DDD6FE"],
    ["Purple", "#7E22CE", "#F3E8FF", "#E9D5FF"],
    ["Pink", "#BE185D", "#FCE7F3", "#FBCFE8"],
    ["Slate", "#334155", "#F1F5F9", "#E2E8F0"]
  ];

  const icons = {
    edit: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 -960 960 960" fill="currentColor" aria-hidden="true"><path d="M200-200h50.46l409.46-409.46-50.46-50.46L200-250.46V-200Zm-60 60v-135.38l527.62-527.39q9.07-8.24 20.03-12.73 10.97-4.5 23-4.5t23.3 4.27q11.28 4.27 19.97 13.58l48.85 49.46q9.31 8.69 13.27 20 3.96 11.31 3.96 22.62 0 12.07-4.12 23.03-4.12 10.97-13.11 20.04L275.38-140H140Z" /></svg>',
    check: '<svg class="company-attributes-checkmark" xmlns="http://www.w3.org/2000/svg" viewBox="0 -960 960 960" fill="currentColor" aria-label="Yes"><path d="M382-240 154-468l57-57 171 171 367-367 57 57-424 424Z" /></svg>',
    arrowLeft: '<svg xmlns="http://www.w3.org/2000/svg" height="20" viewBox="0 -960 960 960" width="20" fill="currentColor" aria-hidden="true"><path d="m504-480 184 184-42 42-226-226 226-226 42 42-184 184Z" /></svg>',
    arrowRight: '<svg xmlns="http://www.w3.org/2000/svg" height="20" viewBox="0 -960 960 960" width="20" fill="currentColor" aria-hidden="true"><path d="m504-480-184-184 42-42 226 226-226 226-42-42 184-184Z" /></svg>',
    drag: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 -960 960 960" fill="currentColor" aria-hidden="true"><path d="M360-190.77q-20.31 0-34.77-14.46-14.46-14.46-14.46-34.77 0-20.31 14.46-34.77 14.46-14.46 34.77-14.46 20.31 0 34.77 14.46 14.46 14.46 14.46 34.77 0 20.31-14.46 34.77-14.46 14.46-34.77 14.46Zm240 0q-20.31 0-34.77-14.46-14.46-14.46-14.46-34.77 0-20.31 14.46-34.77 14.46-14.46 34.77-14.46 20.31 0 34.77 14.46 14.46 14.46 14.46 34.77 0 20.31-14.46 34.77-14.46 14.46-34.77 14.46Zm-240-240q-20.31 0-34.77-14.46-14.46-14.46-14.46-34.77 0-20.31 14.46-34.77 14.46-14.46 34.77-14.46 20.31 0 34.77 14.46 14.46 14.46 14.46 34.77 0 20.31-14.46 34.77-14.46 14.46-34.77 14.46Zm240 0q-20.31 0-34.77-14.46-14.46-14.46-14.46-34.77 0-20.31 14.46-34.77 14.46-14.46 34.77-14.46 20.31 0 34.77 14.46 14.46 14.46 14.46 34.77 0 20.31-14.46 34.77-14.46 14.46-34.77 14.46Zm-240-240q-20.31 0-34.77-14.46-14.46-14.46-14.46-34.77 0-20.31 14.46-34.77 14.46-14.46 34.77-14.46 20.31 0 34.77 14.46 14.46 14.46 14.46 34.77 0 20.31-14.46 34.77-14.46 14.46-34.77 14.46Zm240 0q-20.31 0-34.77-14.46-14.46-14.46-14.46-34.77 0-20.31 14.46-34.77 14.46-14.46 34.77-14.46 20.31 0 34.77 14.46 14.46 14.46 14.46 34.77 0 20.31-14.46 34.77-14.46 14.46-34.77 14.46Z" /></svg>',
    delete: '<svg xmlns="http://www.w3.org/2000/svg" height="24" viewBox="0 -960 960 960" width="24" fill="currentColor" aria-hidden="true"><path d="M280-120q-33 0-56.5-23.5T200-200v-520h-40v-80h200v-40h240v40h200v80h-40v520q0 33-23.5 56.5T680-120H280Zm400-600H280v520h400v-520ZM360-280h80v-360h-80v360Zm160 0h80v-360h-80v360Z" /></svg>',
    chevron: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 -960 960 960" fill="currentColor" aria-hidden="true"><path d="M480-346.85 253.85-573 291-610.15l189 189 189-189L706.15-573 480-346.85Z" /></svg>'
  };

  let initialData;
  let attributes = [];
  let table = { companies: [], pagination: { page: 1, page_size: 10, total: 0, total_pages: 1 }, sort: { key: "company", direction: "asc" }, query: "" };
  let hasCompanies = false;
  let readOnly = false;
  let tableRequest = null;
  let searchTimer = null;
  let drafts = [];
  let deletedIds = [];
  let selectedDraftKey = null;
  let draftErrors = {};
  let activeColorTarget = null;
  let activeCompany = null;
  let initialValuesState = "";
  let valueErrors = {};
  let dragKey = null;
  let pendingDiscard = null;
  let definitionsSaving = false;
  let valuesSaving = false;
  const modalOpenTimers = new WeakMap();
  const modalCloseTimers = new WeakMap();
  const modalLastFocused = new WeakMap();
  const dialogLastFocused = new WeakMap();

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function escapeSelector(value) {
    if (window.CSS && typeof window.CSS.escape === "function") return window.CSS.escape(String(value));
    return String(value).replace(/[^a-zA-Z0-9_-]/g, function (character) { return "\\" + character; });
  }

  function normalizeType(value) {
    const type = String(value || "text").toLowerCase().replace(/-/g, "_");
    return typeMeta[type] ? type : "text";
  }

  function newClientId(prefix) {
    if (window.crypto && typeof window.crypto.randomUUID === "function") {
      return prefix + "_" + window.crypto.randomUUID();
    }
    return prefix + "_" + Date.now().toString(36) + "_" + Math.random().toString(36).slice(2);
  }

  function defaultSettings(type) {
    if (type === "number") return { format: "plain", decimal_places: 0 };
    if (type === "money") return { currency: "USD", display_format: "compact" };
    if (type === "boolean") return { display_style: "yes_no" };
    return {};
  }

  function normalizeColor(color, fallbackIndex) {
    const fallback = colors[fallbackIndex % colors.length];
    const source = color || {};
    return {
      text: source.text || source.color_text || fallback[1],
      bg: source.bg || source.background || source.color_bg || fallback[2],
      border: source.border || source.color_border || fallback[3]
    };
  }

  function normalizeOption(option, index) {
    const source = option || {};
    return {
      id: source.id == null ? null : source.id,
      client_id: source.client_id || (source.id == null ? newClientId("option") : null),
      label: String(source.label == null ? source.name || "" : source.label),
      position: Number.isFinite(Number(source.position)) ? Number(source.position) : index,
      color: normalizeColor(source.color || source, source.id == null ? 15 : index + 8)
    };
  }

  function normalizeAttribute(attribute, index) {
    const source = attribute || {};
    const type = normalizeType(source.type);
    const settings = Object.assign(defaultSettings(type), source.settings || {});
    return {
      id: source.id == null ? null : source.id,
      client_id: source.client_id || (source.id == null ? newClientId("attribute") : null),
      name: String(source.name || ""),
      type: type,
      position: Number.isFinite(Number(source.position)) ? Number(source.position) : index,
      settings: settings,
      options: Array.isArray(source.options) ? source.options.map(normalizeOption) : []
    };
  }

  function normalizeAttributes(items) {
    return (Array.isArray(items) ? items : [])
      .map(normalizeAttribute)
      .sort(function (a, b) { return a.position - b.position; })
      .map(function (item, index) { item.position = index; return item; });
  }

  function deepClone(items) {
    return normalizeAttributes(JSON.parse(JSON.stringify(items || [])));
  }

  function normalizePagination(source, companiesLength) {
    const value = source || {};
    const page = Math.max(1, Number(value.page || value.page_number || 1));
    const pageSize = Math.max(1, Number(value.page_size || value.per_page || 10));
    const total = Math.max(0, Number(value.total == null ? value.count == null ? companiesLength : value.count : value.total));
    const pages = Math.max(1, Number(value.total_pages || value.num_pages || Math.ceil(total / pageSize) || 1));
    return { page: page, page_size: pageSize, total: total, total_pages: pages };
  }

  function normalizeTable(source) {
    const value = source && source.table ? source.table : (source || {});
    const companies = Array.isArray(value.companies) ? value.companies : (Array.isArray(value.results) ? value.results : []);
    const sortSource = value.sort || {};
    return {
      companies: companies,
      pagination: normalizePagination(value.pagination, companies.length),
      sort: {
        key: String(sortSource.key || value.sort_key || "company"),
        direction: String(sortSource.direction || value.sort_direction || "asc") === "desc" ? "desc" : "asc"
      },
      query: String(value.query == null ? value.q || "" : value.query)
    };
  }

  function parseInitialData() {
    const script = document.getElementById("company-attributes-data");
    try {
      return script && script.textContent.trim() ? JSON.parse(script.textContent) : {};
    } catch (error) {
      showPageError("Company attributes could not be loaded. Refresh the page and try again.");
      return {};
    }
  }

  function showPageError(message) {
    pageFeedback.textContent = message;
    pageFeedback.hidden = false;
  }

  function clearPageError() {
    pageFeedback.hidden = true;
    pageFeedback.textContent = "";
  }

  function draftKey(attribute) {
    return attribute.id == null ? "client:" + attribute.client_id : "id:" + attribute.id;
  }

  function findDraft(key) {
    return drafts.find(function (attribute) { return draftKey(attribute) === key; }) || null;
  }

  function getCompanyValues(company) {
    return company && company.values && typeof company.values === "object" ? company.values : {};
  }

  function storedValue(company, attribute) {
    const values = getCompanyValues(company);
    if (Object.prototype.hasOwnProperty.call(values, String(attribute.id))) return values[String(attribute.id)];
    if (Object.prototype.hasOwnProperty.call(values, attribute.id)) return values[attribute.id];
    return null;
  }

  function rawValue(value) {
    if (value && typeof value === "object" && Object.prototype.hasOwnProperty.call(value, "raw")) return value.raw;
    if (value && typeof value === "object" && Object.prototype.hasOwnProperty.call(value, "value")) return value.value;
    return value;
  }

  function valueFor(company, attribute) {
    return rawValue(storedValue(company, attribute));
  }

  function optionForValue(attribute, value) {
    return attribute.options.find(function (option) {
      return String(option.id) === String(value) || option.label === value;
    }) || null;
  }

  function formatValue(company, attribute) {
    const stored = storedValue(company, attribute);
    if (stored && typeof stored === "object" && (Object.prototype.hasOwnProperty.call(stored, "display") || Object.prototype.hasOwnProperty.call(stored, "is_empty"))) {
      if (stored.is_empty || stored.display == null || stored.display === "") return '<span class="text-slate-400">-</span>';
      if (attribute.type === "single_select") {
        const color = normalizeColor(stored.color, 15);
        return '<span class="company-attributes-badge" style="--tag-text:' + escapeHtml(color.text) + ";--tag-bg:" + escapeHtml(color.bg) + ";--tag-border:" + escapeHtml(color.border) + '">' + escapeHtml(stored.display) + "</span>";
      }
      if (attribute.type === "boolean" && attribute.settings.display_style === "checkmark_dash") {
        return stored.display === "✓" ? icons.check : '<span class="text-slate-400">&mdash;</span>';
      }
      return escapeHtml(stored.display);
    }

    const displayValues = company.display_values || company.displayValues || {};
    if (Object.prototype.hasOwnProperty.call(displayValues, String(attribute.id))) {
      const display = displayValues[String(attribute.id)];
      return display == null || display === "" ? '<span class="text-slate-400">-</span>' : escapeHtml(display);
    }

    const value = valueFor(company, attribute);
    if (value == null || value === "") return '<span class="text-slate-400">-</span>';

    if (attribute.type === "single_select") {
      const option = optionForValue(attribute, value);
      if (!option) return escapeHtml(value);
      const color = option.color;
      return '<span class="company-attributes-badge" style="--tag-text:' + escapeHtml(color.text) + ";--tag-bg:" + escapeHtml(color.bg) + ";--tag-border:" + escapeHtml(color.border) + '">' + escapeHtml(option.label) + "</span>";
    }

    if (attribute.type === "boolean") {
      const truthy = value === true || value === 1 || value === "true" || value === "1";
      if (attribute.settings.display_style === "checkmark_dash") return truthy ? icons.check : '<span class="text-slate-400">&mdash;</span>';
      return truthy ? "Yes" : "No";
    }

    if (attribute.type === "date") {
      const match = String(value).match(/^(\d{4})-(\d{2})-(\d{2})/);
      if (!match) return escapeHtml(value);
      const date = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
      return escapeHtml(new Intl.DateTimeFormat(undefined, { year: "numeric", month: "short", day: "numeric" }).format(date));
    }

    if (attribute.type === "number") {
      const numeric = Number(value);
      if (!Number.isFinite(numeric)) return escapeHtml(value);
      const decimals = Math.max(0, Math.min(2, Number(attribute.settings.decimal_places || 0)));
      const formatted = new Intl.NumberFormat(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals }).format(numeric);
      return escapeHtml(formatted + (attribute.settings.format === "percentage" ? "%" : ""));
    }

    if (attribute.type === "money") {
      const numeric = Number(value);
      if (!Number.isFinite(numeric)) return escapeHtml(value);
      const currency = /^[A-Z]{3}$/.test(attribute.settings.currency || "") ? attribute.settings.currency : "USD";
      try {
        return escapeHtml(new Intl.NumberFormat(undefined, {
          style: "currency",
          currency: currency,
          notation: attribute.settings.display_format === "full" ? "standard" : "compact",
          maximumFractionDigits: attribute.settings.display_format === "full" ? 2 : 1
        }).format(numeric));
      } catch (error) {
        return escapeHtml(numeric + " " + currency);
      }
    }

    return escapeHtml(value);
  }

  function sortButton(key, label) {
    const active = table.sort.key === key;
    const direction = active ? ' data-sort-direction="' + table.sort.direction + '"' : "";
    return '<button type="button" class="company-attributes-heading" data-sort-key="' + escapeHtml(key) + '"' + direction + ' aria-label="Sort by ' + escapeHtml(label) + '"><span>' + escapeHtml(label) + "</span></button>";
  }

  function ariaSort(key) {
    if (table.sort.key !== key) return "none";
    return table.sort.direction === "asc" ? "ascending" : "descending";
  }

  function companyLink(company) {
    const name = company.name || company.company_name || company.id;
    const url = company.detail_url || company.url || "#";
    return '<a class="company-attributes-company-link" href="' + escapeHtml(url) + '">' + escapeHtml(name) + "</a>";
  }

  function tableRows() {
    if (!table.companies.length) {
      const colspan = Math.max(1, attributes.length + (attributes.length && !readOnly ? 2 : 1));
      const message = table.query ? "No companies match your search." : "No companies are available on this page.";
      return '<tr class="company-attributes-no-results"><td colspan="' + colspan + '">' + message + "</td></tr>";
    }

    return table.companies.map(function (company) {
      const companyCellClass = attributes.length ? ' class="company-attributes-sticky company-attributes-company-column"' : "";
      let cells = "<td" + companyCellClass + ">" + companyLink(company) + "</td>";
      if (attributes.length && !readOnly) {
        const name = company.name || company.company_name || company.id;
        cells += '<td class="company-attributes-edit-sticky company-attributes-edit-column"><button type="button" class="company-attributes-edit-button" data-edit-company="' + escapeHtml(company.id) + '" aria-label="Edit ' + escapeHtml(name) + ' attributes">' + icons.edit + "</button></td>";
      }
      attributes.forEach(function (attribute) {
        cells += '<td class="company-attributes-value-column"><div class="company-attributes-value">' + formatValue(company, attribute) + "</div></td>";
      });
      return "<tr>" + cells + "</tr>";
    }).join("");
  }

  function syncStickyColumnOffset() {
    const tableElement = pageState.querySelector('.company-attributes-table[data-has-attributes="true"]');
    const companyColumn = tableElement && tableElement.querySelector(".company-attributes-company-column");
    if (!companyColumn) return;
    tableElement.style.setProperty("--company-attributes-company-width", companyColumn.getBoundingClientRect().width + "px");
  }

  function paginationHtml() {
    const pagination = table.pagination;
    if (pagination.total_pages <= 1) return "";
    const first = pagination.page > 2 ? '<button type="button" class="company-attributes-pagination-button" data-page="1">Go to first page</button>' : '<span aria-hidden="true"></span>';
    const previous = pagination.page > 1 ? '<button type="button" class="company-attributes-pagination-button" data-page="' + (pagination.page - 1) + '" aria-label="Go to previous page">' + icons.arrowLeft + "</button>" : '<span class="company-attributes-pagination-spacer" aria-hidden="true"></span>';
    const next = pagination.page < pagination.total_pages ? '<button type="button" class="company-attributes-pagination-button" data-page="' + (pagination.page + 1) + '">Continue to next page' + icons.arrowRight + "</button>" : '<span aria-hidden="true"></span>';
    return '<nav class="company-attributes-pagination" aria-label="Company attributes table pages">' + first + '<div class="company-attributes-pagination-controls">' + previous + '<span class="company-attributes-pagination-page">Page ' + pagination.page + "/" + pagination.total_pages + "</span>" + next + "</div></nav>";
  }

  function helperHtml() {
    return '<aside class="company-attributes-helper" aria-label="Attribute helper">' +
      '<h2 class="text-base font-semibold text-slate-900">Add attributes to enrich companies</h2>' +
      '<p class="mt-3 leading-6 text-gray-950">Create custom attributes to keep important company context next to product usage data.</p>' +
      '<div class="company-attributes-chip-grid" aria-label="Example attributes">' +
      ["Plan", "ARR", "Employees", "Lifecycle stage", "Region", "Owner", "Renewal date", "Health score"].map(function (name) { return '<span class="company-attributes-chip">' + name + "</span>"; }).join("") +
      "</div>" +
      '<p class="text-sm leading-6 text-slate-600">Attributes will appear as columns in this table. Later, they can be used for segmentation, reporting, and company analysis.</p>' +
      (readOnly ? "" : '<button type="button" class="company-attributes-button company-attributes-button-primary mt-6" data-add-first-attribute>Add first attribute</button>') +
      "</aside>";
  }

  function renderPage() {
    pageState.setAttribute("aria-busy", "false");
    searchInput.disabled = !hasCompanies;
    managerOpen.disabled = false;
    managerOpen.title = readOnly ? "View company attributes" : "";

    if (!hasCompanies) {
      root.dataset.pageState = "empty-project";
      pageState.innerHTML = '<section class="company-attributes-empty-project" aria-live="polite"><div class="mx-auto max-w-xl"><p class="text-lg font-medium text-slate-600">No company data were found in the last 180 days.</p><img src="' + escapeHtml(root.dataset.emptyStateImageUrl || "/static/svg/no-sessions.svg") + '" alt="" /></div></section>';
      return;
    }

    const hasAttributes = attributes.length > 0;
    root.dataset.pageState = hasAttributes ? "populated" : "no-attributes";
    const companyHeadingClass = hasAttributes ? ' class="company-attributes-sticky company-attributes-company-column"' : "";
    let headings = "<th" + companyHeadingClass + ' scope="col" aria-sort="' + ariaSort("company") + '">' + sortButton("company", "Company") + "</th>";
    if (hasAttributes && !readOnly) headings += '<th class="company-attributes-edit-sticky company-attributes-edit-column" scope="col"><span class="sr-only">Edit company attributes</span></th>';
    attributes.forEach(function (attribute) {
      const key = "attr:" + attribute.id;
      headings += '<th class="company-attributes-value-column" scope="col" aria-sort="' + ariaSort(key) + '">' + sortButton(key, attribute.name) + "</th>";
    });

    const tableMarkup = '<div class="company-attributes-table-wrap"><table class="company-attributes-table" data-has-attributes="' + hasAttributes + '"><thead><tr>' + headings + "</tr></thead><tbody>" + tableRows() + "</tbody></table></div>";
    const className = hasAttributes ? "company-attributes-card" : "company-attributes-card company-attributes-card-grid";
    pageState.innerHTML = '<section class="' + className + '" aria-label="Company attributes table">' + tableMarkup + (hasAttributes ? "" : helperHtml()) + paginationHtml() + "</section>";
    syncStickyColumnOffset();
  }

  function showTableLoading() {
    const card = pageState.querySelector(".company-attributes-card");
    if (!card || card.querySelector(".company-attributes-table-loading")) return;
    card.insertAdjacentHTML("beforeend", '<div class="company-attributes-table-loading" role="status"><span class="company-attributes-spinner" aria-hidden="true"></span><span class="sr-only">Loading companies</span></div>');
    pageState.setAttribute("aria-busy", "true");
  }

  async function responseJson(response) {
    const contentType = response.headers.get("content-type") || "";
    if (!contentType.includes("application/json")) return {};
    try { return await response.json(); } catch (error) { return {}; }
  }

  async function fetchTable() {
    if (!root.dataset.tableUrl) return;
    if (tableRequest) tableRequest.abort();
    tableRequest = new AbortController();
    const url = new URL(root.dataset.tableUrl, window.location.origin);
    if (table.query) url.searchParams.set("q", table.query);
    url.searchParams.set("sort", table.sort.key);
    url.searchParams.set("direction", table.sort.direction);
    url.searchParams.set("page", String(table.pagination.page));
    showTableLoading();
    clearPageError();

    try {
      const response = await fetch(url.toString(), { credentials: "same-origin", signal: tableRequest.signal });
      const data = await responseJson(response);
      if (!response.ok) throw new Error(data.error || "Unable to load companies.");
      table = normalizeTable(data);
      hasCompanies = Boolean((initialData.state && initialData.state.has_companies) ?? initialData.has_companies ?? hasCompanies ?? table.pagination.total);
      renderPage();
    } catch (error) {
      if (error.name === "AbortError") return;
      pageState.setAttribute("aria-busy", "false");
      const overlay = pageState.querySelector(".company-attributes-table-loading");
      if (overlay) overlay.remove();
      showPageError(error.message || "Unable to load companies.");
    }
  }

  function csrfToken() {
    const input = root.querySelector('[name="csrfmiddlewaretoken"]');
    if (input && input.value) return input.value;
    const cookie = document.cookie.split(";").map(function (part) { return part.trim(); }).find(function (part) { return part.indexOf("csrftoken=") === 0; });
    return cookie ? decodeURIComponent(cookie.slice("csrftoken=".length)) : "";
  }

  function modalFocusable(dialog) {
    let elements = Array.from(dialog.querySelectorAll('a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'));
    if (dialog === managerDialog && !colorMenu.hidden) {
      elements = elements.concat(Array.from(colorMenu.querySelectorAll("button:not([disabled])")));
    }
    return elements.filter(function (element) {
      return !element.hidden && element.getClientRects().length > 0;
    });
  }

  function openModal(modalElement, dialog) {
    const closeTimer = modalCloseTimers.get(modalElement);
    if (closeTimer) window.clearTimeout(closeTimer);
    modalCloseTimers.delete(modalElement);
    const openTimer = modalOpenTimers.get(modalElement);
    if (openTimer) window.clearTimeout(openTimer);
    modalLastFocused.set(modalElement, document.activeElement);
    modalElement.removeAttribute("data-closing");
    modalElement.removeAttribute("data-open");
    modalElement.hidden = false;
    document.body.classList.add("company-attributes-modal-open");
    const timer = window.setTimeout(function () {
      modalElement.dataset.open = "true";
      modalOpenTimers.delete(modalElement);
      const focusable = modalFocusable(dialog);
      if (!dialog.contains(document.activeElement)) (focusable[0] || dialog).focus();
    }, 50);
    modalOpenTimers.set(modalElement, timer);
  }

  function closeModal(modalElement) {
    if (modalElement.hidden || modalElement.hasAttribute("data-closing")) return;
    const focusTarget = modalLastFocused.get(modalElement);
    const openTimer = modalOpenTimers.get(modalElement);
    if (openTimer) window.clearTimeout(openTimer);
    modalOpenTimers.delete(modalElement);
    modalElement.removeAttribute("data-open");
    modalElement.dataset.closing = "true";
    closeColorMenu();
    const timer = window.setTimeout(function () {
      modalElement.hidden = true;
      modalElement.removeAttribute("data-closing");
      modalCloseTimers.delete(modalElement);
      modalLastFocused.delete(modalElement);
      if (managerModal.hidden && valuesModal.hidden && discardModal.hidden) document.body.classList.remove("company-attributes-modal-open");
      if (focusTarget && document.contains(focusTarget)) focusTarget.focus();
    }, 250);
    modalCloseTimers.set(modalElement, timer);
  }

  function closeAttributesCustomSelect(picker) {
    if (!picker) return;
    const menu = picker.querySelector(".attributes-select-menu");
    const trigger = picker.querySelector(".attributes-select-trigger");
    if (menu) menu.classList.add("hidden");
    if (trigger) trigger.setAttribute("aria-expanded", "false");
    picker.removeAttribute("data-open");
  }

  function closeAttributesCustomSelects(exceptPicker) {
    root.querySelectorAll("[data-attributes-custom-select]").forEach(function (picker) {
      if (picker !== exceptPicker) closeAttributesCustomSelect(picker);
    });
  }

  function fitManagerDropdown(menu, trigger) {
    if (!menu || !trigger || !managerEditor.contains(trigger)) return;
    const editorRect = managerEditor.getBoundingClientRect();
    const triggerRect = trigger.getBoundingClientRect();
    const spaceBelow = Math.max(0, editorRect.bottom - triggerRect.bottom - 12);
    const spaceAbove = Math.max(0, triggerRect.top - editorRect.top - 12);
    const openAbove = spaceBelow < 160 && spaceAbove > spaceBelow;
    const available = openAbove ? spaceAbove : spaceBelow;
    menu.classList.toggle("attributes-menu-open-up", openAbove);
    menu.style.maxHeight = Math.max(80, Math.min(320, Math.floor(available))) + "px";
  }

  function syncAttributesCustomSelect(select) {
    const picker = select && select.nextElementSibling;
    if (!picker || !picker.matches("[data-attributes-custom-select]")) return;
    const selectedOption = select.selectedOptions[0] || select.options[0];
    const selectedValue = selectedOption ? selectedOption.value : "";
    const label = picker.querySelector(".attributes-select-trigger-label");
    if (label) label.textContent = selectedOption ? selectedOption.textContent.trim() : "";
    picker.querySelectorAll("[data-attributes-select-option]").forEach(function (option) {
      option.setAttribute("aria-selected", String(option.dataset.attributesSelectOption === selectedValue));
    });
  }

  function enhanceAttributesSelect(select, index) {
    if (!select || select.dataset.attributesSelectEnhanced === "true") return;
    const picker = document.createElement("span");
    const trigger = document.createElement("button");
    const triggerLabel = document.createElement("span");
    const menu = document.createElement("span");
    const labelText = select.closest(".attributes-form-row")?.querySelector(".attributes-form-label")?.textContent.trim();
    const labelledBy = select.getAttribute("aria-labelledby");
    const menuId = "attributes-select-menu-" + index + "-" + newClientId("menu");

    picker.className = "attributes-custom-select";
    picker.dataset.attributesCustomSelect = "";
    trigger.type = "button";
    trigger.className = "attributes-select-trigger";
    trigger.setAttribute("aria-haspopup", "listbox");
    trigger.setAttribute("aria-expanded", "false");
    trigger.setAttribute("aria-controls", menuId);
    trigger.disabled = select.disabled;
    if (select.getAttribute("aria-invalid") === "true") trigger.setAttribute("aria-invalid", "true");

    triggerLabel.className = "attributes-select-trigger-label";
    triggerLabel.id = menuId + "-value";
    trigger.append(triggerLabel);
    trigger.insertAdjacentHTML("beforeend", icons.chevron);
    if (labelledBy) trigger.setAttribute("aria-labelledby", labelledBy + " " + triggerLabel.id);

    menu.id = menuId;
    menu.className = "attributes-select-menu hidden";
    menu.setAttribute("role", "listbox");
    if (labelledBy) menu.setAttribute("aria-labelledby", labelledBy);
    else menu.setAttribute("aria-label", select.getAttribute("aria-label") || labelText || "Select value");
    Array.from(select.options).forEach(function (option) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "attributes-select-option";
      button.dataset.attributesSelectOption = option.value;
      button.setAttribute("role", "option");
      button.textContent = option.textContent.trim();
      menu.append(button);
    });

    select.dataset.attributesSelectEnhanced = "true";
    select.classList.add("attributes-select-native");
    select.setAttribute("aria-hidden", "true");
    select.tabIndex = -1;
    picker.append(trigger, menu);
    select.after(picker);
    syncAttributesCustomSelect(select);

    trigger.addEventListener("click", function (event) {
      event.preventDefault();
      if (picker.dataset.open === "true") {
        closeAttributesCustomSelect(picker);
      } else {
        closeAttributesCustomSelects(picker);
        fitManagerDropdown(menu, trigger);
        menu.classList.remove("hidden");
        trigger.setAttribute("aria-expanded", "true");
        picker.dataset.open = "true";
      }
    });

    trigger.addEventListener("keydown", function (event) {
      if (!["ArrowDown", "Enter", " "].includes(event.key)) return;
      event.preventDefault();
      closeAttributesCustomSelects(picker);
      fitManagerDropdown(menu, trigger);
      menu.classList.remove("hidden");
      trigger.setAttribute("aria-expanded", "true");
      picker.dataset.open = "true";
      (menu.querySelector('[aria-selected="true"]') || menu.querySelector(".attributes-select-option"))?.focus();
    });

    menu.addEventListener("click", function (event) {
      const option = event.target.closest("[data-attributes-select-option]");
      if (!option) return;
      event.preventDefault();
      select.value = option.dataset.attributesSelectOption;
      syncAttributesCustomSelect(select);
      select.dispatchEvent(new Event("change", { bubbles: true }));
      select.dispatchEvent(new Event("input", { bubbles: true }));
      closeAttributesCustomSelect(picker);
      trigger.focus();
    });

    menu.addEventListener("keydown", function (event) {
      const options = Array.from(menu.querySelectorAll("[data-attributes-select-option]"));
      const activeIndex = options.indexOf(document.activeElement);
      let nextIndex = activeIndex;
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        closeAttributesCustomSelect(picker);
        trigger.focus();
        return;
      }
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        document.activeElement?.click();
        return;
      }
      if (event.key === "ArrowDown") nextIndex = activeIndex >= 0 ? Math.min(activeIndex + 1, options.length - 1) : 0;
      else if (event.key === "ArrowUp") nextIndex = activeIndex >= 0 ? Math.max(activeIndex - 1, 0) : options.length - 1;
      else if (event.key === "Home") nextIndex = 0;
      else if (event.key === "End") nextIndex = options.length - 1;
      else return;
      event.preventDefault();
      options[nextIndex]?.focus();
    });

    select.addEventListener("change", function () { syncAttributesCustomSelect(select); });
  }

  function enhanceAttributesSelects(container) {
    container.querySelectorAll("select.attributes-select").forEach(function (select, index) {
      enhanceAttributesSelect(select, index);
    });
  }

  function renderColorGrid() {
    colorGrid.innerHTML = colors.map(function (color, index) {
      return '<button type="button" class="attributes-color-preset" data-color-index="' + index + '" style="--preset-text:' + color[1] + ";--preset-bg:" + color[2] + ";--preset-border:" + color[3] + '" role="menuitemradio"><span class="attributes-color-preset-tag">' + color[0] + "</span></button>";
    }).join("");
  }

  function definitionItems(items) {
    return items.map(function (attribute, index) {
      const settings = {};
      Object.keys(attribute.settings || {}).sort().forEach(function (key) {
        settings[key] = attribute.settings[key];
      });
      return {
        id: attribute.id,
        client_id: attribute.client_id,
        name: attribute.name,
        type: attribute.type,
        position: index,
        settings: settings,
        options: attribute.options.map(function (option, optionIndex) {
          return {
            id: option.id,
            client_id: option.client_id,
            label: option.label,
            position: optionIndex,
            color: {
              text: option.color.text,
              bg: option.color.bg,
              border: option.color.border
            }
          };
        })
      };
    });
  }

  function definitionState(items) {
    return JSON.stringify(definitionItems(items));
  }

  function managerHasUnsavedChanges() {
    const pendingOption = managerEditor.querySelector("[data-option-input]");
    return Boolean(pendingOption && pendingOption.value !== "") || definitionState(drafts) !== definitionState(attributes);
  }

  function openManager(selectNew) {
    if (definitionsSaving) return;
    drafts = deepClone(attributes);
    deletedIds = [];
    selectedDraftKey = null;
    draftErrors = {};
    managerSaveError.hidden = true;
    managerSaveError.textContent = "";
    if (selectNew && !readOnly) addDraft();
    else {
      renderManager();
      openModal(managerModal, managerDialog);
    }
  }

  function discardManager() {
    if (definitionsSaving) return;
    drafts = [];
    deletedIds = [];
    selectedDraftKey = null;
    draftErrors = {};
    closeModal(managerModal);
  }

  function addDraft() {
    if (readOnly) return;
    const attribute = normalizeAttribute({ client_id: newClientId("attribute"), name: "", type: "text", settings: defaultSettings("text"), options: [] }, drafts.length);
    drafts.push(attribute);
    selectedDraftKey = draftKey(attribute);
    renderManager();
    if (managerModal.hidden) openModal(managerModal, managerDialog);
    window.requestAnimationFrame(function () {
      const input = managerEditor.querySelector('[data-attribute-field="name"]');
      if (input) input.focus();
    });
  }

  function errorFor(key, field) {
    const errors = draftErrors[key] || {};
    return errors[field] || "";
  }

  function attributeHasErrors(key) {
    return Boolean(draftErrors[key] && Object.keys(draftErrors[key]).length);
  }

  function renderManagerList() {
    if (!drafts.length) {
      managerList.innerHTML = '<div class="attribute-list-empty"><p class="attribute-list-empty-title">No attributes yet</p><p class="attribute-list-empty-copy">Add your first attribute to enrich companies with custom context.</p></div>';
      return;
    }

    managerList.innerHTML = drafts.map(function (attribute, index) {
      const key = draftKey(attribute);
      const selected = key === selectedDraftKey;
      const invalid = attributeHasErrors(key);
      const draftNumber = drafts.slice(0, index + 1).filter(function (item) { return item.id == null; }).length;
      const draftLabel = draftNumber === 1 ? "New attribute" : "New attribute " + draftNumber;
      const name = attribute.name.trim() || (attribute.id == null ? draftLabel : "Untitled attribute");
      const typeLabel = attribute.id == null ? "Draft" : attribute.type === "single_select" ? "Select" : typeMeta[attribute.type].label;
      const itemClasses = ["attribute-list-item"];
      if (selected) itemClasses.push("attribute-list-item-active");
      if (invalid) itemClasses.push("attribute-list-item-invalid");
      return '<div class="attribute-list-entry" data-draft-key="' + escapeHtml(key) + '"' + (readOnly ? "" : ' draggable="true"') + '>' +
        '<button type="button" class="' + itemClasses.join(" ") + '" data-select-attribute="' + escapeHtml(key) + '"' + (selected ? ' aria-current="true"' : "") + '><span class="min-w-0"><span class="attribute-list-name">' + escapeHtml(name) + '</span><span class="attribute-list-type">' + escapeHtml(typeLabel) + "</span></span></button>" +
        (readOnly ? "" : '<button type="button" class="attribute-reorder-handle" data-reorder-handle aria-label="Move ' + escapeHtml(name) + '. Use up and down arrow keys to reorder." title="Drag the row or use arrow keys to reorder">' + icons.drag + "</button>") +
        "</div>";
    }).join("");
  }

  function fieldErrorHtml(key, field) {
    const error = errorFor(key, field);
    return error ? '<span class="attributes-field-error" data-field-error="' + escapeHtml(field) + '">' + escapeHtml(error) + "</span>" : "";
  }

  function typePickerHtml(attribute, key) {
    const options = Object.keys(typeMeta).map(function (type) {
      const meta = typeMeta[type];
      return '<button type="button" class="attributes-type-option" data-choose-type="' + type + '" aria-selected="' + (type === attribute.type) + '" role="option"><span class="attributes-type-option-title">' + meta.label + '</span><span class="attributes-type-option-copy">' + meta.copy + "</span></button>";
    }).join("");
    return '<div class="attributes-type-picker"><button type="button" class="attributes-type-trigger" data-type-trigger aria-haspopup="listbox" aria-expanded="false"><span>' + typeMeta[attribute.type].label + "</span>" + icons.chevron + '</button><div class="attributes-type-menu" data-type-menu role="listbox" aria-label="Attribute type" hidden>' + options + "</div></div>" + fieldErrorHtml(key, "type");
  }

  function selectHtml(field, value, options, key) {
    const invalid = errorFor(key, field) ? ' aria-invalid="true" aria-describedby="attribute-error-' + escapeHtml(field.replace(/[^a-z0-9]/gi, "-")) + '"' : "";
    return '<select class="attributes-select" data-setting-field="' + escapeHtml(field) + '"' + invalid + (readOnly ? " disabled" : "") + ">" + options.map(function (option) {
      return '<option value="' + escapeHtml(option[0]) + '"' + (String(option[0]) === String(value) ? " selected" : "") + ">" + escapeHtml(option[1]) + "</option>";
    }).join("") + "</select>" + fieldErrorHtml(key, field);
  }

  function settingsHtml(attribute, key) {
    if (attribute.type === "number") {
      return '<div class="attributes-form-row"><span class="attributes-form-label">Format</span><span class="attributes-form-control">' + selectHtml("settings.format", attribute.settings.format, [["plain", "Plain number"], ["percentage", "Percentage"]], key) + "</span></div>" +
        '<div class="attributes-form-row"><span class="attributes-form-label">Decimal places</span><span class="attributes-form-control">' + selectHtml("settings.decimal_places", attribute.settings.decimal_places, [[0, "0"], [1, "1"], [2, "2"]], key) + "</span></div>";
    }
    if (attribute.type === "money") {
      const displayOptions = attribute.id == null
        ? [["compact", "Compact, for example $1.2M"], ["full", "Full, for example $1,200,000"]]
        : [["compact", "Compact"], ["full", "Full"]];
      return '<div class="attributes-form-row"><span class="attributes-form-label">Currency</span><span class="attributes-form-control">' + selectHtml("settings.currency", attribute.settings.currency, moneyCurrencies.map(function (currency) { return [currency, currency]; }), key) + "</span></div>" +
        '<div class="attributes-form-row"><span class="attributes-form-label">Display format</span><span class="attributes-form-control">' + selectHtml("settings.display_format", attribute.settings.display_format, displayOptions, key) + "</span></div>";
    }
    if (attribute.type === "boolean") {
      return '<div class="attributes-form-row"><span class="attributes-form-label">Display style</span><span class="attributes-form-control">' + selectHtml("settings.display_style", attribute.settings.display_style, [["yes_no", "Yes / No"], ["checkmark_dash", "Checkmark / Dash"]], key) + "</span></div>";
    }
    return "";
  }

  function optionsHtml(attribute, key) {
    if (attribute.type !== "single_select") return "";
    const tags = attribute.options.map(function (option) {
      const color = option.color;
      const optionKey = option.id == null ? "client:" + option.client_id : "id:" + option.id;
      return '<span class="attributes-tag" style="--tag-text:' + escapeHtml(color.text) + ";--tag-bg:" + escapeHtml(color.bg) + ";--tag-border:" + escapeHtml(color.border) + '" data-option-key="' + escapeHtml(optionKey) + '"><button type="button" class="attributes-tag-color" data-option-color aria-label="Change ' + escapeHtml(option.label) + ' color"' + (readOnly ? " disabled" : "") + '></button><span>' + escapeHtml(option.label) + '</span><button type="button" class="attributes-tag-remove" data-remove-option aria-label="Remove ' + escapeHtml(option.label) + '"' + (readOnly ? " disabled" : "") + '>&times;</button></span>';
    }).join("");
    return '<div class="attributes-form-row attributes-form-row-start"><span class="attributes-form-label">Options</span><div class="attributes-form-control"><div class="attributes-tag-editor"><div class="attributes-tag-list" aria-label="Options">' + tags + '</div>' +
      (readOnly ? "" : '<div class="attributes-tag-input-row"><input class="attributes-input" type="text" maxlength="100" placeholder="Enter option and press Enter" data-option-input' + (errorFor(key, "options") ? ' aria-invalid="true"' : "") + '><button type="button" class="attributes-tag-add" data-add-option>Add</button></div>') +
      fieldErrorHtml(key, "options") + "</div></div></div>";
  }

  function renderEditor() {
    const attribute = findDraft(selectedDraftKey);
    managerEditor.classList.toggle("attributes-editor-body-empty", !attribute);
    if (!attribute) {
      if (!drafts.length) {
        managerEditor.innerHTML = '<div class="attributes-empty-state">' + (readOnly ? '<p class="attributes-empty-copy">There are no company attributes to display.</p>' : '<button type="button" class="attributes-button attributes-button-secondary" data-empty-add>Add attribute</button>') + "</div>";
      } else {
        managerEditor.innerHTML = '<div class="attributes-empty-state"><h3 class="attributes-empty-title">Select attribute</h3><p class="attributes-empty-copy">Choose an attribute from the list to edit its settings.</p></div>';
      }
      return;
    }

    const key = draftKey(attribute);
    const nameError = errorFor(key, "name");
    const generalError = errorFor(key, "general");
    const typeField = attribute.id == null ? typePickerHtml(attribute, key) : '<span class="attributes-form-value">' + escapeHtml(typeMeta[attribute.type].label) + ". Can't be changed after creation.</span>";
    managerEditor.innerHTML = '<div class="attributes-editor-top"><h3 class="attributes-editor-title">Set up attribute</h3>' + (readOnly ? "" : '<button type="button" class="attributes-icon-danger" data-delete-attribute aria-label="Remove attribute">' + icons.delete + "</button>") + "</div>" +
      (generalError ? '<p class="attributes-field-error mb-4" role="alert">' + escapeHtml(generalError) + "</p>" : "") +
      '<div class="attributes-form-stack"><div class="attributes-form-row"><label class="attributes-form-label" for="attribute-name-input">Name</label><span class="attributes-form-control"><input id="attribute-name-input" class="attributes-input" data-attribute-field="name" type="text" maxlength="100" value="' + escapeHtml(attribute.name) + '" placeholder="Attribute name"' + (nameError ? ' aria-invalid="true" aria-describedby="attribute-name-error"' : "") + (readOnly ? " disabled" : "") + ">" + (nameError ? '<span id="attribute-name-error" class="attributes-field-error" data-field-error="name">' + escapeHtml(nameError) + "</span>" : "") + "</span></div>" +
      '<div class="attributes-form-row"><span class="attributes-form-label">Type</span><span class="attributes-form-control">' + typeField + "</span></div>" + settingsHtml(attribute, key) + optionsHtml(attribute, key) + "</div>";
    enhanceAttributesSelects(managerEditor);
  }

  function renderManager() {
    renderManagerList();
    renderEditor();
    managerFooter.hidden = !drafts.length && !deletedIds.length;
    managerAdd.disabled = readOnly;
    managerSave.disabled = readOnly;
  }

  function selectDraft(key) {
    if (!findDraft(key)) return;
    selectedDraftKey = key;
    closeColorMenu();
    renderManager();
  }

  function deleteSelectedDraft() {
    const attribute = findDraft(selectedDraftKey);
    if (!attribute || readOnly) return;
    if (attribute.id != null && !deletedIds.some(function (id) { return String(id) === String(attribute.id); })) deletedIds.push(attribute.id);
    drafts = drafts.filter(function (item) { return draftKey(item) !== selectedDraftKey; });
    drafts.forEach(function (item, index) { item.position = index; });
    delete draftErrors[selectedDraftKey];
    selectedDraftKey = null;
    renderManager();
  }

  function setNestedSetting(attribute, field, value) {
    const name = field.replace(/^settings\./, "");
    attribute.settings[name] = name === "decimal_places" ? Number(value) : value;
  }

  function clearDraftFieldError(key, field) {
    if (!draftErrors[key]) return;
    delete draftErrors[key][field];
    if (!Object.keys(draftErrors[key]).length) delete draftErrors[key];
    const errorNode = managerEditor.querySelector('[data-field-error="' + field + '"]');
    if (errorNode) errorNode.remove();
    const input = field === "name" ? managerEditor.querySelector('[data-attribute-field="name"]') : managerEditor.querySelector('[data-setting-field="' + field + '"]');
    if (input) {
      input.removeAttribute("aria-invalid");
      const customTrigger = input.nextElementSibling?.querySelector(".attributes-select-trigger");
      if (customTrigger) customTrigger.removeAttribute("aria-invalid");
    }
    const listItem = managerList.querySelector('[data-draft-key="' + escapeSelector(key) + '"] .attribute-list-item');
    if (listItem && !attributeHasErrors(key)) listItem.classList.remove("attribute-list-item-invalid");
  }

  function changeDraftType(type) {
    const attribute = findDraft(selectedDraftKey);
    if (!attribute || attribute.id != null || !typeMeta[type] || readOnly) return;
    if (attribute.type === type) return;
    attribute.type = type;
    attribute.settings = defaultSettings(type);
    attribute.options = [];
    clearDraftFieldError(selectedDraftKey, "type");
    clearDraftFieldError(selectedDraftKey, "options");
    renderManager();
  }

  function addOption(focusAfter) {
    const attribute = findDraft(selectedDraftKey);
    const input = managerEditor.querySelector("[data-option-input]");
    if (!attribute || !input || readOnly) return;
    const label = input.value.trim().replace(/,$/, "").trim();
    if (!label) {
      input.setAttribute("aria-invalid", "true");
      return;
    }
    const normalizedLabel = label.toLocaleLowerCase();
    if (attribute.options.some(function (option) { return option.label.trim().toLocaleLowerCase() === normalizedLabel; })) {
      input.value = "";
      return;
    }
    input.value = "";
    attribute.options.push(normalizeOption({ client_id: newClientId("option"), label: label }, attribute.options.length));
    clearDraftFieldError(selectedDraftKey, "options");
    renderEditor();
    const nextInput = managerEditor.querySelector("[data-option-input]");
    if (nextInput && focusAfter !== false) nextInput.focus();
  }

  function optionKey(option) {
    return option.id == null ? "client:" + option.client_id : "id:" + option.id;
  }

  function removeOption(key) {
    const attribute = findDraft(selectedDraftKey);
    if (!attribute || readOnly) return;
    attribute.options = attribute.options.filter(function (option) { return optionKey(option) !== key; });
    attribute.options.forEach(function (option, index) { option.position = index; });
    renderEditor();
  }

  function openColorMenu(trigger, optionKeyValue) {
    const attribute = findDraft(selectedDraftKey);
    const option = attribute && attribute.options.find(function (item) { return optionKey(item) === optionKeyValue; });
    if (!option || readOnly) return;
    activeColorTarget = { attributeKey: selectedDraftKey, optionKey: optionKeyValue };
    colorMenu.hidden = false;
    colorGrid.querySelectorAll("[data-color-index]").forEach(function (button) {
      const color = colors[Number(button.dataset.colorIndex)];
      button.setAttribute("aria-checked", String(color[1] === option.color.text));
    });
    const rect = trigger.getBoundingClientRect();
    const menuRect = colorMenu.getBoundingClientRect();
    const viewportPadding = 16;
    const left = Math.min(
      Math.max(viewportPadding, rect.left - 12),
      window.innerWidth - menuRect.width - viewportPadding
    );
    let top = rect.bottom + 8;
    if (top + menuRect.height > window.innerHeight - viewportPadding) {
      top = Math.max(viewportPadding, rect.top - menuRect.height - 8);
    }
    colorMenu.style.left = left + "px";
    colorMenu.style.top = top + "px";
  }

  function closeColorMenu() {
    colorMenu.hidden = true;
    activeColorTarget = null;
  }

  function chooseColor(index) {
    if (!activeColorTarget) return;
    const attribute = findDraft(activeColorTarget.attributeKey);
    const option = attribute && attribute.options.find(function (item) { return optionKey(item) === activeColorTarget.optionKey; });
    const color = colors[index];
    if (!option || !color) return;
    option.color = { text: color[1], bg: color[2], border: color[3] };
    closeColorMenu();
    renderEditor();
  }

  function moveDraft(key, direction) {
    const index = drafts.findIndex(function (attribute) { return draftKey(attribute) === key; });
    const nextIndex = index + direction;
    if (index < 0 || nextIndex < 0 || nextIndex >= drafts.length) return;
    const moved = drafts.splice(index, 1)[0];
    drafts.splice(nextIndex, 0, moved);
    drafts.forEach(function (attribute, position) { attribute.position = position; });
    managerFooter.hidden = false;
    renderManagerList();
    reorderStatus.textContent = (moved.name || "Untitled attribute") + " moved to position " + (nextIndex + 1) + " of " + drafts.length + ".";
    const handle = managerList.querySelector('[data-draft-key="' + escapeSelector(key) + '"] [data-reorder-handle]');
    if (handle) handle.focus();
  }

  function validateDrafts() {
    const errors = {};
    const names = {};
    function add(key, field, message) {
      if (!errors[key]) errors[key] = {};
      if (!errors[key][field]) errors[key][field] = message;
    }

    drafts.forEach(function (attribute) {
      const key = draftKey(attribute);
      const name = attribute.name.trim();
      attribute.name = name;
      if (!name) add(key, "name", "Enter an attribute name.");
      else if (name.length > 100) add(key, "name", "Use 100 characters or fewer.");
      const normalizedName = name.toLocaleLowerCase();
      if (name) {
        if (!names[normalizedName]) names[normalizedName] = [];
        names[normalizedName].push(key);
      }

      if (attribute.type === "single_select") {
        if (!attribute.options.length) add(key, "options", "Add at least one option.");
        const optionNames = {};
        attribute.options.forEach(function (option) {
          option.label = option.label.trim();
          const normalized = option.label.toLocaleLowerCase();
          if (!option.label) add(key, "options", "Option names cannot be empty.");
          else if (option.label.length > 100) add(key, "options", "Use 100 characters or fewer for each option.");
          else if (optionNames[normalized]) add(key, "options", "Option names must be unique.");
          optionNames[normalized] = true;
        });
      }
    });

    Object.keys(names).forEach(function (name) {
      if (names[name].length > 1) names[name].forEach(function (key) { add(key, "name", "Attribute names must be unique."); });
    });
    return errors;
  }

  function firstErrorKey() {
    return drafts.map(draftKey).find(function (key) { return attributeHasErrors(key); }) || null;
  }

  function focusFirstDraftError() {
    window.requestAnimationFrame(function () {
      const field = managerEditor.querySelector('[aria-invalid="true"]:not(.attributes-select-native)');
      if (field) field.focus();
    });
  }

  function flattenServerErrors(value, prefix, output) {
    if (typeof value === "string") {
      output[prefix || "general"] = value;
    } else if (Array.isArray(value)) {
      output[prefix || "general"] = value.join(" ");
    } else if (value && typeof value === "object") {
      Object.keys(value).forEach(function (key) {
        const nextPrefix = prefix ? prefix + "." + key : key;
        flattenServerErrors(value[key], nextPrefix, output);
      });
    }
  }

  function applyServerDraftErrors(data) {
    const source = data.errors || data.field_errors || {};
    const mapped = {};
    Object.keys(source).forEach(function (serverKey) {
      const attribute = drafts.find(function (item) {
        return String(item.id) === String(serverKey) || item.client_id === serverKey || draftKey(item) === serverKey;
      });
      if (!attribute) return;
      const flat = {};
      flattenServerErrors(source[serverKey], "", flat);
      Object.keys(flat).forEach(function (field) {
        let normalized = field.replace(/^settings\./, "settings.");
        if (normalized.indexOf("options") === 0) normalized = "options";
        if (!["name", "type", "options", "settings.format", "settings.decimal_places", "settings.currency", "settings.display_format", "settings.display_style"].includes(normalized)) normalized = "general";
        if (!mapped[draftKey(attribute)]) mapped[draftKey(attribute)] = {};
        mapped[draftKey(attribute)][normalized] = flat[field];
      });
    });
    draftErrors = mapped;
  }

  function definitionPayload() {
    return {
      attributes: definitionItems(drafts),
      deleted_ids: deletedIds.slice()
    };
  }

  async function saveDefinitions() {
    if (readOnly || definitionsSaving || !root.dataset.definitionsUrl) return;
    const pendingOption = managerEditor.querySelector("[data-option-input]");
    if (pendingOption && pendingOption.value.trim()) addOption(false);
    draftErrors = validateDrafts();
    const invalidKey = firstErrorKey();
    if (invalidKey) {
      selectedDraftKey = invalidKey;
      managerSaveError.textContent = "Fix the highlighted attributes before saving.";
      managerSaveError.hidden = false;
      renderManager();
      focusFirstDraftError();
      return;
    }

    closeColorMenu();
    definitionsSaving = true;
    managerDialog.classList.add("attributes-dialog-saving");
    managerDialog.setAttribute("aria-busy", "true");
    managerDialog.setAttribute("inert", "");
    managerSave.disabled = true;
    managerSave.textContent = "Saving…";
    managerSaveError.hidden = true;
    try {
      const response = await fetch(root.dataset.definitionsUrl, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken(), "Accept": "application/json" },
        body: JSON.stringify(definitionPayload())
      });
      const data = await responseJson(response);
      if (!response.ok) {
        applyServerDraftErrors(data);
        const first = firstErrorKey();
        if (first) {
          selectedDraftKey = first;
          renderManager();
          focusFirstDraftError();
        }
        const fallback = response.status === 403
          ? "Company attributes could not be changed. The project may be read-only or your access may have changed."
          : "Fix the highlighted attributes before saving.";
        throw new Error(data.error || data.detail || fallback);
      }
      if (Array.isArray(data.attributes)) {
        attributes = normalizeAttributes(data.attributes);
        closeModal(managerModal);
        await fetchTable();
      } else {
        window.location.reload();
      }
    } catch (error) {
      managerSaveError.textContent = error.message || "Attributes could not be saved.";
      managerSaveError.hidden = false;
    } finally {
      definitionsSaving = false;
      managerDialog.classList.remove("attributes-dialog-saving");
      managerDialog.removeAttribute("aria-busy");
      managerDialog.removeAttribute("inert");
      managerSave.disabled = readOnly;
      managerSave.textContent = "Save";
    }
  }

  function inputId(attribute) {
    return "company-value-" + String(attribute.id).replace(/[^a-zA-Z0-9_-]/g, "-");
  }

  function valueLabelId(attribute) {
    return inputId(attribute) + "-label";
  }

  function valueInputHtml(company, attribute) {
    const value = valueFor(company, attribute);
    const id = inputId(attribute);
    const common = ' id="' + id + '" data-value-attribute="' + escapeHtml(attribute.id) + '" aria-labelledby="' + valueLabelId(attribute) + '"';
    if (attribute.type === "single_select") {
      return '<select class="attributes-select"' + common + '><option value="">No value</option>' + attribute.options.map(function (option) {
        const optionValue = option.id == null ? option.label : option.id;
        return '<option value="' + escapeHtml(optionValue) + '"' + (String(optionValue) === String(value) || option.label === value ? " selected" : "") + ">" + escapeHtml(option.label) + "</option>";
      }).join("") + "</select>";
    }
    if (attribute.type === "boolean") {
      const normalized = value === true || value === 1 || value === "true" || value === "1" ? "true" : value === false || value === 0 || value === "false" || value === "0" ? "false" : "";
      return '<select class="attributes-select"' + common + '><option value=""' + (normalized === "" ? " selected" : "") + '>No value</option><option value="true"' + (normalized === "true" ? " selected" : "") + '>Yes</option><option value="false"' + (normalized === "false" ? " selected" : "") + ">No</option></select>";
    }
    if (attribute.type === "date") return '<input class="attributes-input" type="date"' + common + ' value="' + escapeHtml(value || "") + '">';
    if (attribute.type === "number") return '<input class="attributes-input" type="number" step="any"' + common + ' value="' + escapeHtml(value == null ? "" : value) + '">';
    if (attribute.type === "money") {
      return '<span class="attributes-input-addon" data-value-input-shell="' + escapeHtml(attribute.id) + '"><input class="attributes-input" type="text" inputmode="decimal" autocomplete="off"' + common + ' value="' + escapeHtml(value == null ? "" : value) + '"><span class="attributes-input-addon-suffix">' + escapeHtml(attribute.settings.currency || "USD") + "</span></span>";
    }
    return '<input class="attributes-input" type="text"' + common + ' value="' + escapeHtml(value == null ? "" : value) + '">';
  }

  function renderValuesForm() {
    valueErrors = {};
    valuesTitle.textContent = (activeCompany.name || activeCompany.company_name || activeCompany.id) + " attributes";
    valuesForm.innerHTML = attributes.map(function (attribute) {
      const labelId = valueLabelId(attribute);
      const rowClass = attribute.type === "money" ? "attributes-form-row attributes-form-row-start" : "attributes-form-row";
      return '<div class="' + rowClass + '" data-value-row-type="' + escapeHtml(attribute.type) + '"><span class="attributes-form-label" id="' + labelId + '">' + escapeHtml(attribute.name) + '</span><span class="attributes-form-control" data-value-control="' + escapeHtml(attribute.id) + '">' + valueInputHtml(activeCompany, attribute) + "</span></div>";
    }).join("");
    enhanceAttributesSelects(valuesForm);
    valuesSaveError.hidden = true;
    valuesSaveError.textContent = "";
  }

  function valueFieldsState(fields) {
    return JSON.stringify(Array.from(fields).map(function (field) {
      return [String(field.dataset.valueAttribute), field.value, Boolean(field.validity && field.validity.badInput)];
    }));
  }

  function valuesFormState() {
    return valueFieldsState(valuesForm.querySelectorAll("[data-value-attribute]"));
  }

  function valuesHaveUnsavedChanges() {
    return valuesFormState() !== initialValuesState;
  }

  function openValues(companyId) {
    if (valuesSaving) return;
    activeCompany = table.companies.find(function (company) { return String(company.id) === String(companyId); });
    if (!activeCompany || readOnly) return;
    renderValuesForm();
    initialValuesState = valuesFormState();
    openModal(valuesModal, valuesDialog);
  }

  function discardValues() {
    if (valuesSaving) return;
    activeCompany = null;
    initialValuesState = "";
    valueErrors = {};
    closeModal(valuesModal);
  }

  function openDiscardConfirmation(target) {
    if (pendingDiscard) return;
    pendingDiscard = target;
    const sourceDialog = target === "manager" ? managerDialog : valuesDialog;
    const rememberedFocus = dialogLastFocused.get(sourceDialog);
    const returnFocus = sourceDialog.contains(document.activeElement)
      ? document.activeElement
      : rememberedFocus && document.contains(rememberedFocus)
        ? rememberedFocus
        : sourceDialog;
    openModal(discardModal, discardDialog);
    modalLastFocused.set(discardModal, returnFocus);
    closeColorMenu();
    closeAttributesCustomSelects();
    sourceDialog.setAttribute("inert", "");
  }

  function closeDiscardConfirmation() {
    const target = pendingDiscard;
    pendingDiscard = null;
    if (target === "manager" && !definitionsSaving) managerDialog.removeAttribute("inert");
    if (target === "values" && !valuesSaving) valuesDialog.removeAttribute("inert");
    closeModal(discardModal);
  }

  function requestManagerClose() {
    if (definitionsSaving || managerModal.hidden || managerModal.hasAttribute("data-closing")) return;
    if (managerHasUnsavedChanges()) openDiscardConfirmation("manager");
    else discardManager();
  }

  function requestValuesClose() {
    if (valuesSaving || valuesModal.hidden || valuesModal.hasAttribute("data-closing")) return;
    if (valuesHaveUnsavedChanges()) openDiscardConfirmation("values");
    else discardValues();
  }

  function confirmDiscardChanges() {
    const target = pendingDiscard;
    closeDiscardConfirmation();
    if (target === "manager") discardManager();
    if (target === "values") discardValues();
  }

  function collectValues() {
    const output = {};
    valueErrors = {};
    attributes.forEach(function (attribute) {
      const input = valuesForm.querySelector('[data-value-attribute="' + escapeSelector(String(attribute.id)) + '"]');
      if (!input) return;
      const value = input.value.trim();
      if (value === "") output[String(attribute.id)] = null;
      else if (attribute.type === "number" || attribute.type === "money") {
        if (!/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(value)) valueErrors[String(attribute.id)] = "Enter a valid number.";
        else output[String(attribute.id)] = value;
      } else if (attribute.type === "boolean") output[String(attribute.id)] = value === "true";
      else output[String(attribute.id)] = value;
    });
    return output;
  }

  function renderValueErrors() {
    Object.keys(valueErrors).forEach(function (attributeId) {
      const control = valuesForm.querySelector('[data-value-control="' + escapeSelector(attributeId) + '"]');
      const input = control && control.querySelector("input, select");
      const visibleInput = input && input.matches("select") ? input.nextElementSibling?.querySelector(".attributes-select-trigger") || input : input;
      const shell = control && control.querySelector("[data-value-input-shell]");
      if (!control || !input) return;
      control.closest(".attributes-form-row")?.classList.add("attributes-form-row-start");
      input.setAttribute("aria-invalid", "true");
      if (visibleInput && visibleInput !== input) visibleInput.setAttribute("aria-invalid", "true");
      if (shell) shell.dataset.invalid = "true";
      control.insertAdjacentHTML("beforeend", '<span class="attributes-field-error" data-value-error>' + escapeHtml(valueErrors[attributeId]) + "</span>");
    });
    const first = valuesForm.querySelector('[aria-invalid="true"]:not(.attributes-select-native)');
    if (first) first.focus();
  }

  function applyServerValueErrors(data) {
    const source = data.errors && data.errors.values ? data.errors.values : (data.errors || {});
    valueErrors = {};
    Object.keys(source).forEach(function (key) {
      const value = source[key];
      if (Array.isArray(value)) valueErrors[String(key)] = value.join(" ");
      else if (typeof value === "string") valueErrors[String(key)] = value;
      else {
        const flat = {};
        flattenServerErrors(value, "", flat);
        valueErrors[String(key)] = Object.values(flat)[0] || "Enter a valid value.";
      }
    });
  }

  async function saveValues() {
    if (!activeCompany || readOnly || valuesSaving) return;
    valuesForm.querySelectorAll("[data-value-error]").forEach(function (node) { node.remove(); });
    valuesForm.querySelectorAll('[aria-invalid="true"]').forEach(function (node) { node.removeAttribute("aria-invalid"); });
    valuesForm.querySelectorAll("[data-value-input-shell]").forEach(function (node) { node.removeAttribute("data-invalid"); });
    const values = collectValues();
    if (Object.keys(valueErrors).length) {
      renderValueErrors();
      valuesSaveError.textContent = "Fix the highlighted values before saving.";
      valuesSaveError.hidden = false;
      return;
    }

    const url = root.dataset.valuesUrlTemplate.replace("__company_id__", encodeURIComponent(activeCompany.id));
    valuesSaving = true;
    valuesDialog.classList.add("attributes-dialog-saving");
    valuesDialog.setAttribute("aria-busy", "true");
    valuesDialog.setAttribute("inert", "");
    valuesSave.disabled = true;
    valuesSave.textContent = "Saving…";
    valuesSaveError.hidden = true;
    try {
      const response = await fetch(url, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken(), "Accept": "application/json" },
        body: JSON.stringify({ values: values })
      });
      const data = await responseJson(response);
      if (!response.ok) {
        applyServerValueErrors(data);
        renderValueErrors();
        const fallback = response.status === 403
          ? "Company attributes could not be changed. The project may be read-only or your access may have changed."
          : "Fix the highlighted values before saving.";
        throw new Error(data.error || data.detail || fallback);
      }
      closeModal(valuesModal);
      activeCompany = null;
      initialValuesState = "";
      await fetchTable();
    } catch (error) {
      valuesSaveError.textContent = error.message || "Company values could not be saved.";
      valuesSaveError.hidden = false;
    } finally {
      valuesSaving = false;
      valuesDialog.classList.remove("attributes-dialog-saving");
      valuesDialog.removeAttribute("aria-busy");
      valuesDialog.removeAttribute("inert");
      valuesSave.disabled = false;
      valuesSave.textContent = "Save";
    }
  }

  function trapModalKeydown(event) {
    const modalElement = !discardModal.hidden ? discardModal : !valuesModal.hidden ? valuesModal : !managerModal.hidden ? managerModal : null;
    if (!modalElement) return;
    if (event.key === "Escape") {
      event.preventDefault();
      if (modalElement === discardModal) closeDiscardConfirmation();
      else if (modalElement === valuesModal) requestValuesClose();
      else requestManagerClose();
      return;
    }
    if (event.key !== "Tab") return;
    const dialog = modalElement === discardModal ? discardDialog : modalElement === valuesModal ? valuesDialog : managerDialog;
    const focusable = modalFocusable(dialog);
    if (!focusable.length) {
      event.preventDefault();
      dialog.focus();
      return;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  root.addEventListener("click", function (event) {
    if (event.target.matches(".company-attributes-modal-overlay")) {
      const modalElement = event.target.parentElement;
      if (modalElement === discardModal) closeDiscardConfirmation();
      else if (modalElement === valuesModal) requestValuesClose();
      else if (modalElement === managerModal) requestManagerClose();
      return;
    }

    const sort = event.target.closest("[data-sort-key]");
    if (sort) {
      const key = sort.dataset.sortKey;
      table.sort.direction = table.sort.key === key && table.sort.direction === "asc" ? "desc" : "asc";
      table.sort.key = key;
      table.pagination.page = 1;
      fetchTable();
      return;
    }

    const page = event.target.closest("[data-page]");
    if (page) {
      table.pagination.page = Number(page.dataset.page);
      fetchTable();
      return;
    }

    if (event.target.closest("[data-manage-attributes-open]")) { openManager(false); return; }
    if (event.target.closest("[data-add-first-attribute]")) { openManager(true); return; }
    if (event.target.closest("[data-attributes-manager-close], [data-attributes-manager-cancel]")) { requestManagerClose(); return; }
    if (event.target.closest("[data-company-values-close], [data-company-values-cancel]")) { requestValuesClose(); return; }
    if (event.target.closest("[data-attributes-keep-editing]")) { closeDiscardConfirmation(); return; }
    if (event.target.closest("[data-attributes-discard-changes]")) { confirmDiscardChanges(); return; }
    if (event.target.closest("[data-add-attribute], [data-empty-add]")) { addDraft(); return; }
    if (event.target.closest("[data-delete-attribute]")) { deleteSelectedDraft(); return; }
    if (event.target.closest("[data-attributes-save]")) { saveDefinitions(); return; }
    if (event.target.closest("[data-company-values-save]")) { saveValues(); return; }

    const select = event.target.closest("[data-select-attribute]");
    if (select) { selectDraft(select.dataset.selectAttribute); return; }

    const edit = event.target.closest("[data-edit-company]");
    if (edit) { openValues(edit.dataset.editCompany); return; }

    const typeTrigger = event.target.closest("[data-type-trigger]");
    if (typeTrigger) {
      closeAttributesCustomSelects();
      closeColorMenu();
      const menu = managerEditor.querySelector("[data-type-menu]");
      const willOpen = menu.hidden;
      if (willOpen) fitManagerDropdown(menu, typeTrigger);
      menu.hidden = !willOpen;
      typeTrigger.setAttribute("aria-expanded", String(willOpen));
      if (willOpen) {
        const selected = menu.querySelector('[aria-selected="true"]');
        if (selected) selected.focus();
      }
      return;
    }

    const typeOption = event.target.closest("[data-choose-type]");
    if (typeOption) { changeDraftType(typeOption.dataset.chooseType); return; }
    if (event.target.closest("[data-add-option]")) { addOption(); return; }

    const remove = event.target.closest("[data-remove-option]");
    if (remove) {
      const tag = remove.closest("[data-option-key]");
      if (tag) removeOption(tag.dataset.optionKey);
      return;
    }

    const colorTrigger = event.target.closest("[data-option-color]");
    if (colorTrigger) {
      const tag = colorTrigger.closest("[data-option-key]");
      if (tag) openColorMenu(colorTrigger, tag.dataset.optionKey);
      return;
    }

    const colorPreset = event.target.closest("[data-color-index]");
    if (colorPreset) { chooseColor(Number(colorPreset.dataset.colorIndex)); return; }

    if (!event.target.closest("[data-type-picker]") && !event.target.closest(".attributes-type-picker")) {
      const menu = managerEditor.querySelector("[data-type-menu]");
      const trigger = managerEditor.querySelector("[data-type-trigger]");
      if (menu) menu.hidden = true;
      if (trigger) trigger.setAttribute("aria-expanded", "false");
    }
    if (!event.target.closest("[data-option-color-menu], [data-option-color]")) closeColorMenu();
    if (!event.target.closest("[data-attributes-custom-select]")) closeAttributesCustomSelects();
  });

  root.addEventListener("focusin", function (event) {
    if (managerDialog.contains(event.target)) dialogLastFocused.set(managerDialog, event.target);
    if (valuesDialog.contains(event.target)) dialogLastFocused.set(valuesDialog, event.target);
  });

  searchInput.addEventListener("input", function () {
    window.clearTimeout(searchTimer);
    searchTimer = window.setTimeout(function () {
      table.query = searchInput.value.trim();
      table.pagination.page = 1;
      fetchTable();
    }, 500);
  });

  managerEditor.addEventListener("input", function (event) {
    const attribute = findDraft(selectedDraftKey);
    if (!attribute || readOnly) return;
    if (event.target.matches('[data-attribute-field="name"]')) {
      attribute.name = event.target.value;
      clearDraftFieldError(selectedDraftKey, "name");
      const label = managerList.querySelector('[data-draft-key="' + escapeSelector(selectedDraftKey) + '"] .attribute-list-name');
      const attributeIndex = drafts.indexOf(attribute);
      const draftNumber = drafts.slice(0, attributeIndex + 1).filter(function (item) { return item.id == null; }).length;
      const draftLabel = draftNumber === 1 ? "New attribute" : "New attribute " + draftNumber;
      if (label) label.textContent = attribute.name.trim() || (attribute.id == null ? draftLabel : "Untitled attribute");
    }
    if (event.target.matches("[data-option-input]")) clearDraftFieldError(selectedDraftKey, "options");
  });

  managerEditor.addEventListener("change", function (event) {
    const attribute = findDraft(selectedDraftKey);
    if (!attribute || !event.target.matches("[data-setting-field]") || readOnly) return;
    setNestedSetting(attribute, event.target.dataset.settingField, event.target.value);
    clearDraftFieldError(selectedDraftKey, event.target.dataset.settingField);
  });

  managerEditor.addEventListener("keydown", function (event) {
    if (event.target.matches("[data-option-input]") && (event.key === "Enter" || event.key === ",")) {
      event.preventDefault();
      addOption();
    }
  });

  managerEditor.addEventListener("focusout", function (event) {
    if (!event.target.matches("[data-option-input]") || !event.target.value.trim()) return;
    if (event.relatedTarget && event.relatedTarget.closest("[data-add-option]")) return;
    addOption(false);
  });

  managerList.addEventListener("keydown", function (event) {
    const handle = event.target.closest("[data-reorder-handle]");
    if (!handle || !["ArrowUp", "ArrowDown", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const entry = handle.closest("[data-draft-key]");
    const index = drafts.findIndex(function (attribute) { return draftKey(attribute) === entry.dataset.draftKey; });
    const direction = event.key === "Home" ? -index : event.key === "End" ? drafts.length - index - 1 : event.key === "ArrowUp" ? -1 : 1;
    moveDraft(entry.dataset.draftKey, direction);
  });

  managerList.addEventListener("dragstart", function (event) {
    const entry = event.target.closest('[data-draft-key][draggable="true"]');
    if (!entry || entry.parentElement !== managerList) { event.preventDefault(); return; }
    dragKey = entry.dataset.draftKey;
    entry.classList.add("attribute-list-entry-dragging");
    managerList.classList.add("attributes-list-dragging");
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", dragKey);
  });

  managerList.addEventListener("dragover", function (event) {
    if (!dragKey) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
    const target = event.target.closest("[data-draft-key]");
    const dragged = managerList.querySelector('[data-draft-key="' + escapeSelector(dragKey) + '"]');
    if (!dragged) return;
    if (target && target !== dragged && target.parentElement === managerList) {
      const rect = target.getBoundingClientRect();
      managerList.insertBefore(dragged, event.clientY < rect.top + rect.height / 2 ? target : target.nextSibling);
    } else if (!target && event.clientY > managerList.getBoundingClientRect().top) {
      managerList.append(dragged);
    }

    const listRect = managerList.getBoundingClientRect();
    if (event.clientY < listRect.top + 32) managerList.scrollTop -= 12;
    else if (event.clientY > listRect.bottom - 32) managerList.scrollTop += 12;
  });

  managerList.addEventListener("drop", function (event) {
    if (!dragKey) return;
    event.preventDefault();
    const order = Array.from(managerList.querySelectorAll("[data-draft-key]")).map(function (entry) { return entry.dataset.draftKey; });
    drafts.sort(function (a, b) { return order.indexOf(draftKey(a)) - order.indexOf(draftKey(b)); });
    drafts.forEach(function (attribute, index) { attribute.position = index; });
    managerFooter.hidden = false;
    const moved = findDraft(dragKey);
    reorderStatus.textContent = (moved ? moved.name || "Untitled attribute" : "Attribute") + " moved to position " + (order.indexOf(dragKey) + 1) + " of " + drafts.length + ".";
  });

  managerList.addEventListener("dragend", function () {
    managerList.querySelectorAll(".attribute-list-entry-dragging").forEach(function (entry) { entry.classList.remove("attribute-list-entry-dragging"); });
    managerList.classList.remove("attributes-list-dragging");
    dragKey = null;
    renderManagerList();
  });

  valuesForm.addEventListener("input", function (event) {
    const input = event.target.closest("[data-value-attribute]");
    if (!input) return;
    const id = String(input.dataset.valueAttribute);
    delete valueErrors[id];
    input.removeAttribute("aria-invalid");
    const customTrigger = input.matches("select") ? input.nextElementSibling?.querySelector(".attributes-select-trigger") : null;
    if (customTrigger) customTrigger.removeAttribute("aria-invalid");
    const control = input.closest("[data-value-control]");
    const error = control && control.querySelector("[data-value-error]");
    const shell = control && control.querySelector("[data-value-input-shell]");
    const row = control && control.closest("[data-value-row-type]");
    if (error) error.remove();
    if (shell) shell.removeAttribute("data-invalid");
    if (row && row.dataset.valueRowType !== "money") row.classList.remove("attributes-form-row-start");
  });

  valuesForm.addEventListener("submit", function (event) {
    event.preventDefault();
    saveValues();
  });

  valuesForm.addEventListener("click", function (event) {
    const input = event.target.closest('input[type="date"]');
    if (!input || typeof input.showPicker !== "function") return;
    try { input.showPicker(); } catch (error) { /* Trusted activation is browser-dependent. */ }
  });

  valuesForm.addEventListener("keydown", function (event) {
    const input = event.target.closest('input[type="date"]');
    if (!input || !["Enter", " ", "ArrowDown"].includes(event.key) || typeof input.showPicker !== "function") return;
    event.preventDefault();
    try { input.showPicker(); } catch (error) { /* Trusted activation is browser-dependent. */ }
  });

  document.addEventListener("keydown", trapModalKeydown);
  window.addEventListener("resize", closeColorMenu);
  window.addEventListener("resize", syncStickyColumnOffset);
  window.addEventListener("scroll", closeColorMenu, true);

  initialData = parseInitialData();
  attributes = normalizeAttributes(initialData.attributes);
  table = normalizeTable(initialData.table || initialData);
  const state = initialData.state || {};
  hasCompanies = Boolean(state.has_companies ?? initialData.has_companies ?? table.pagination.total ?? table.companies.length);
  readOnly = Boolean(state.read_only ?? initialData.read_only ?? false);
  searchInput.value = table.query;
  renderColorGrid();
  renderPage();
})();
