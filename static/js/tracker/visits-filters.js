(() => {
  const filterRoots = new Map(
    Array.from(document.querySelectorAll("[data-visits-filter]"))
      .map((root) => [root.dataset.visitsFilter, root])
  );

  if (!filterRoots.size) return;

  const pageDataNode = document.getElementById("visits-page-filter-data");
  let pageGroups = [];
  try {
    pageGroups = JSON.parse(pageDataNode?.textContent || "[]");
  } catch (_error) {
    pageGroups = [];
  }

  let openFilterName = "";
  let entityRequest = null;
  let entitySearchTimer = null;

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function elements(name) {
    const root = filterRoots.get(name);
    return {
      root,
      trigger: root?.querySelector("[data-visits-filter-trigger]"),
      clear: root?.querySelector("[data-visits-filter-clear]"),
      popover: root?.querySelector("[data-visits-filter-popover]")
    };
  }

  function closeFilter(name, restoreFocus = false) {
    const { trigger, popover } = elements(name);
    if (!trigger || !popover) return;

    popover.hidden = true;
    trigger.setAttribute("aria-expanded", "false");
    popover.querySelector('[role="combobox"]')?.setAttribute("aria-expanded", "false");
    if (openFilterName === name) openFilterName = "";
    if (restoreFocus) trigger.focus();
  }

  function closeAllFilters(exceptName = "") {
    filterRoots.forEach((_root, name) => {
      if (name !== exceptName) closeFilter(name);
    });
  }

  function navigateWithFilters(values, keysToRemove) {
    const url = new URL(window.location.href);
    keysToRemove.forEach((key) => url.searchParams.delete(key));
    Object.entries(values).forEach(([key, value]) => url.searchParams.set(key, String(value)));
    url.searchParams.delete("page");
    window.location.assign(url.toString());
  }

  function appendCompanyAttributeParams(url) {
    const currentParams = new URLSearchParams(window.location.search);
    const existingKeys = Array.from(url.searchParams.keys())
      .filter((key) => key.startsWith("ca."));

    existingKeys.forEach((key) => url.searchParams.delete(key));
    currentParams.forEach((value, key) => {
      if (key.startsWith("ca.")) {
        url.searchParams.append(key, value);
      }
    });
    return url;
  }

  function selected(root, type, id) {
    return root?.dataset.selectedType === type && root?.dataset.selectedId === String(id);
  }

  function entityOptionMarkup(option, type) {
    const meta = type === "user" ? option.companyName || option.email : "";
    return `
      <button
        type="button"
        class="visits-filter__option"
        data-visits-entity-option
        data-entity-type="${type}"
        data-entity-id="${escapeHtml(option.id)}"
        role="option"
        aria-selected="${String(selected(filterRoots.get("entity"), type, option.id))}">
        <span class="visits-filter__option-name">${escapeHtml(option.name || option.id)}</span>
        ${meta ? `<span class="visits-filter__option-company">${escapeHtml(meta)}</span>` : ""}
      </button>`;
  }

  function entityGroupMarkup(title, type, options, pending) {
    const optionMarkup = options.map((option) => entityOptionMarkup(option, type)).join("");
    const emptyMessage = pending
      ? `${title} data is being prepared…`
      : `No ${title.toLowerCase()} found`;
    return `
      <div class="visits-filter__group" role="group" aria-label="${title}">
        <div class="visits-filter__group-title">${title}</div>
        ${optionMarkup || `<div class="visits-filter__group-empty" role="status">${emptyMessage}</div>`}
      </div>`;
  }

  function renderEntityResults(payload) {
    const container = filterRoots.get("entity")?.querySelector("[data-visits-entity-options]");
    if (!container) return;
    const companies = Array.isArray(payload?.companies) ? payload.companies : [];
    const users = Array.isArray(payload?.users) ? payload.users : [];
    container.innerHTML = [
      entityGroupMarkup("Companies", "company", companies, Boolean(payload?.companiesPending)),
      entityGroupMarkup("Users", "user", users, Boolean(payload?.usersPending))
    ].join("");
  }

  async function searchEntities(query = "") {
    const root = filterRoots.get("entity");
    const container = root?.querySelector("[data-visits-entity-options]");
    if (!root || !container || !root.dataset.optionsUrl) return;

    entityRequest?.abort();
    entityRequest = new AbortController();
    container.innerHTML = '<div class="visits-filter__empty" role="status">Searching companies and users…</div>';
    const url = new URL(root.dataset.optionsUrl, window.location.origin);
    url.searchParams.set("q", query.trim());
    url.searchParams.set("limit", "20");
    url.searchParams.set("range", root.dataset.range || "last_30_days");
    appendCompanyAttributeParams(url);

    try {
      const response = await fetch(url.toString(), {
        headers: { Accept: "application/json" },
        signal: entityRequest.signal
      });
      if (!response.ok) throw new Error(`Entity search failed (${response.status})`);
      renderEntityResults(await response.json());
    } catch (error) {
      if (error.name === "AbortError") return;
      container.innerHTML = '<div class="visits-filter__empty" role="status">Could not load companies and users</div>';
    }
  }

  function renderPageOptions(query = "") {
    const root = filterRoots.get("page");
    const container = root?.querySelector("[data-visits-page-options]");
    if (!container) return;

    const normalizedQuery = query.trim().toLowerCase();
    const markup = pageGroups.map((group) => {
      const groupMatches = String(group.name || "").toLowerCase().includes(normalizedQuery);
      const pages = Array.isArray(group.pages) ? group.pages : [];
      const matchingPages = groupMatches
        ? pages
        : pages.filter((page) => String(page.name || "").toLowerCase().includes(normalizedQuery));
      if (!groupMatches && !matchingPages.length) return "";

      return `
        <div class="visits-filter__group" role="group" aria-label="${escapeHtml(group.name)}">
          <button
            type="button"
            class="visits-filter__option"
            data-visits-page-option
            data-page-filter-type="area"
            data-page-filter-id="${escapeHtml(group.id)}"
            role="option"
            aria-selected="${String(selected(root, "area", group.id))}">
            <span class="visits-filter__option-name">${escapeHtml(group.name)}</span>
          </button>
          ${matchingPages.map((page) => `
            <button
              type="button"
              class="visits-filter__option visits-filter__page-option--child"
              data-visits-page-option
              data-page-filter-type="page"
              data-page-filter-id="${escapeHtml(page.id)}"
              role="option"
              aria-selected="${String(selected(root, "page", page.id))}">
              <span class="visits-filter__option-name">${escapeHtml(page.name)}</span>
            </button>`).join("")}
        </div>`;
    }).join("");
    container.innerHTML = markup || '<div class="visits-filter__empty" role="status">No product areas or pages found</div>';
  }

  function openFilter(name) {
    const { trigger, popover } = elements(name);
    if (!trigger || !popover) return;

    closeAllFilters(name);
    popover.hidden = false;
    trigger.setAttribute("aria-expanded", "true");
    openFilterName = name;

    const input = popover.querySelector('[role="combobox"]');
    if (input) {
      input.value = "";
      input.setAttribute("aria-expanded", "true");
      if (name === "entity") searchEntities();
      if (name === "page") renderPageOptions();
      requestAnimationFrame(() => input.focus());
    }
  }

  filterRoots.forEach((root, name) => {
    const { trigger, clear } = elements(name);
    trigger?.addEventListener("click", () => {
      if (openFilterName === name) closeFilter(name);
      else openFilter(name);
    });

    clear?.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      closeFilter(name);
      if (name === "entity") {
        navigateWithFilters({}, ["entity_type", "entity_id"]);
      } else {
        navigateWithFilters({}, ["page_filter_type", "page_filter_id"]);
      }
    });

    root.addEventListener("click", (event) => {
      const entityOption = event.target.closest("[data-visits-entity-option]");
      if (entityOption) {
        closeFilter("entity");
        navigateWithFilters(
          {
            entity_type: entityOption.dataset.entityType,
            entity_id: entityOption.dataset.entityId
          },
          ["entity_type", "entity_id"]
        );
        return;
      }

      const pageOption = event.target.closest("[data-visits-page-option]");
      if (pageOption) {
        closeFilter("page");
        navigateWithFilters(
          {
            page_filter_type: pageOption.dataset.pageFilterType,
            page_filter_id: pageOption.dataset.pageFilterId
          },
          ["page_filter_type", "page_filter_id"]
        );
      }
    });
  });

  const entitySearch = filterRoots.get("entity")?.querySelector("[data-visits-entity-search]");
  entitySearch?.addEventListener("input", () => {
    window.clearTimeout(entitySearchTimer);
    entitySearchTimer = window.setTimeout(() => searchEntities(entitySearch.value), 220);
  });

  const pageSearch = filterRoots.get("page")?.querySelector("[data-visits-page-search]");
  pageSearch?.addEventListener("input", () => renderPageOptions(pageSearch.value));

  document.addEventListener("click", (event) => {
    if (openFilterName && !filterRoots.get(openFilterName)?.contains(event.target)) {
      closeFilter(openFilterName);
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && openFilterName) {
      const name = openFilterName;
      event.preventDefault();
      closeFilter(name, true);
    }
  });

  renderPageOptions();
})();
