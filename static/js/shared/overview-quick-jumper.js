(function mountOverviewQuickJumpers(globalScope) {
  function closeQuickJumper(root, options = {}) {
    const trigger = root.querySelector("[data-overview-quick-jumper-trigger]");
    const popover = root.querySelector("[data-overview-quick-jumper-popover]");

    if (!trigger || !popover || popover.hidden) {
      return;
    }

    trigger.setAttribute("aria-expanded", "false");
    popover.hidden = true;
    root.dispatchEvent(new globalScope.CustomEvent("overview-quick-jumper:close"));

    if (options.restoreFocus) {
      trigger.focus();
    }
  }

  function openQuickJumper(root) {
    const trigger = root.querySelector("[data-overview-quick-jumper-trigger]");
    const popover = root.querySelector("[data-overview-quick-jumper-popover]");
    const input = popover?.querySelector("input[type='search']");

    if (!trigger || !popover || !input) {
      return;
    }

    trigger.setAttribute("aria-expanded", "true");
    popover.hidden = false;

    const focusInput = () => input.focus();
    if (typeof globalScope.requestAnimationFrame === "function") {
      globalScope.requestAnimationFrame(focusInput);
    } else {
      globalScope.setTimeout(focusInput, 0);
    }
  }

  function mountQuickJumper(root) {
    const trigger = root.querySelector("[data-overview-quick-jumper-trigger]");
    const popover = root.querySelector("[data-overview-quick-jumper-popover]");
    const input = popover?.querySelector("input[type='search']");
    const reset = popover?.querySelector("[data-overview-quick-jumper-reset]");

    if (!trigger || !popover || root.dataset.overviewQuickJumperMounted === "true") {
      return;
    }

    root.dataset.overviewQuickJumperMounted = "true";

    if (input && reset) {
      const syncResetVisibility = () => {
        reset.hidden = input.value.length === 0;
      };

      input.addEventListener("input", syncResetVisibility);
      reset.addEventListener("click", () => {
        input.value = "";
        syncResetVisibility();
        input.dispatchEvent(new globalScope.Event("input", { bubbles: true }));
        input.focus();
      });
      syncResetVisibility();
    }

    trigger.addEventListener("click", () => {
      if (popover.hidden) {
        openQuickJumper(root);
      } else {
        closeQuickJumper(root);
      }
    });

    root.addEventListener("keydown", (event) => {
      if (event.key !== "Escape" || popover.hidden) {
        return;
      }

      event.preventDefault();
      event.stopPropagation();
      closeQuickJumper(root, { restoreFocus: true });
    });

    document.addEventListener("pointerdown", (event) => {
      if (!root.contains(event.target)) {
        closeQuickJumper(root);
      }
    });
  }

  function initQuickJumpers() {
    document.querySelectorAll("[data-overview-quick-jumper]").forEach(mountQuickJumper);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initQuickJumpers);
  } else {
    initQuickJumpers();
  }
})(window);
