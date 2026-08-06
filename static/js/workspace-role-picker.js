(function mountWorkspaceRolePicker(root, factory) {
  const api = factory(root);

  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }

  root.HymetryWorkspaceRolePicker = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function createWorkspaceRolePicker(globalScope) {
  "use strict";

  const pickerSelector = "[data-workspace-role-picker]";
  const optionSelector = "[data-workspace-role-option]";
  const maximumMenuHeight = 320;
  const menuGap = 6;
  const viewportMargin = 8;

  function optionsFor(picker) {
    return Array.from(picker.querySelectorAll(optionSelector));
  }

  function optionIndexForKey(currentIndex, optionCount, key) {
    if (!optionCount) {
      return -1;
    }
    if (key === "Home") {
      return 0;
    }
    if (key === "End") {
      return optionCount - 1;
    }
    if (key === "ArrowDown") {
      return currentIndex < 0 ? 0 : (currentIndex + 1) % optionCount;
    }
    if (key === "ArrowUp") {
      return currentIndex <= 0 ? optionCount - 1 : currentIndex - 1;
    }
    return currentIndex;
  }

  function shouldOpenAbove(triggerRect, viewportHeight, menuHeight) {
    const spaceBelow = viewportHeight - triggerRect.bottom - menuGap - viewportMargin;
    const spaceAbove = triggerRect.top - menuGap - viewportMargin;
    return spaceBelow < menuHeight && spaceAbove > spaceBelow;
  }

  function syncRoleSelection(picker, value, { dispatchChange = false } = {}) {
    const select = picker.querySelector("select[name='role']");
    const label = picker.querySelector("[data-workspace-role-picker-label]");
    const trigger = picker.querySelector("[data-dropdown-toggle]");
    const options = optionsFor(picker);
    const selectedOption = options.find((option) => option.dataset.workspaceRoleOption === value);

    if (!select || !label || !selectedOption) {
      return false;
    }

    select.value = value;
    label.textContent = selectedOption.dataset.workspaceRoleName || selectedOption.textContent.trim();
    if (trigger) {
      const ariaLabel = trigger.dataset.workspaceRolePickerAriaLabel || "User role";
      trigger.setAttribute("aria-label", `${ariaLabel}: ${label.textContent}`);
    }
    options.forEach((option) => {
      const isSelected = option === selectedOption;
      option.setAttribute("aria-selected", String(isSelected));
      option.tabIndex = isSelected ? 0 : -1;
    });

    if (dispatchChange && typeof select.dispatchEvent === "function") {
      let changeEvent;
      if (typeof globalScope.Event === "function") {
        changeEvent = new globalScope.Event("change", { bubbles: true });
      } else if (globalScope.document?.createEvent) {
        changeEvent = globalScope.document.createEvent("Event");
        changeEvent.initEvent("change", true, false);
      }
      if (changeEvent) {
        select.dispatchEvent(changeEvent);
      }
    }

    return true;
  }

  function closeMenu(picker, { restoreFocus = false } = {}) {
    const menu = picker.querySelector("[data-dropdown-menu]");
    const trigger = picker.querySelector("[data-dropdown-toggle]");
    if (!menu || !trigger) {
      return;
    }

    if (typeof globalScope.toggleDropdown === "function") {
      globalScope.toggleDropdown(menu, true);
    } else {
      menu.classList.add("hidden", "opacity-0", "scale-95");
      menu.classList.remove("opacity-100", "scale-100");
      trigger.setAttribute("aria-expanded", "false");
    }

    if (restoreFocus) {
      trigger.focus();
    }
  }

  function positionMenu(picker) {
    const menu = picker.querySelector("[data-dropdown-menu]");
    const trigger = picker.querySelector("[data-dropdown-toggle]");
    const documentObject = globalScope.document;
    if (!menu || !trigger || !documentObject || menu.classList.contains("hidden")) {
      return;
    }

    menu.style.maxHeight = `${maximumMenuHeight}px`;
    const triggerRect = trigger.getBoundingClientRect();
    const viewportHeight = documentObject.documentElement.clientHeight || globalScope.innerHeight || 0;
    const menuHeight = Math.min(menu.scrollHeight || maximumMenuHeight, maximumMenuHeight);
    const openAbove = shouldOpenAbove(triggerRect, viewportHeight, menuHeight);
    const availableSpace = openAbove
      ? triggerRect.top - menuGap - viewportMargin
      : viewportHeight - triggerRect.bottom - menuGap - viewportMargin;

    menu.classList.toggle("workspace-role-picker-menu--above", openAbove);
    menu.style.maxHeight = `${Math.max(64, Math.min(maximumMenuHeight, availableSpace))}px`;
  }

  function scheduleMenuPosition(picker, callback) {
    const requestFrame = globalScope.requestAnimationFrame
      || ((frameCallback) => globalScope.setTimeout(frameCallback, 0));
    requestFrame(() => {
      positionMenu(picker);
      callback?.();
    });
  }

  function focusOption(picker, index) {
    const options = optionsFor(picker);
    const option = options[index];
    if (!option) {
      return;
    }

    options.forEach((candidate) => {
      candidate.tabIndex = candidate === option ? 0 : -1;
    });
    option.focus();
    option.scrollIntoView?.({ block: "nearest" });
  }

  function openMenuFromKeyboard(picker, key) {
    const documentObject = globalScope.document;
    const menu = picker.querySelector("[data-dropdown-menu]");
    if (!documentObject || !menu) {
      return;
    }

    documentObject.querySelectorAll("[data-dropdown-menu]").forEach((candidate) => {
      if (candidate === menu) {
        return;
      }
      if (typeof globalScope.toggleDropdown === "function") {
        globalScope.toggleDropdown(candidate, true);
      } else {
        candidate.classList.add("hidden");
      }
    });

    if (menu.classList.contains("hidden")) {
      if (typeof globalScope.toggleDropdown === "function") {
        globalScope.toggleDropdown(menu);
      } else {
        menu.classList.remove("hidden", "opacity-0", "scale-95");
        menu.classList.add("opacity-100", "scale-100");
        picker.querySelector("[data-dropdown-toggle]")?.setAttribute("aria-expanded", "true");
      }
    }

    scheduleMenuPosition(picker, () => {
      const options = optionsFor(picker);
      const selectedIndex = options.findIndex((option) => option.getAttribute("aria-selected") === "true");
      let targetIndex = Math.max(0, selectedIndex);
      if (key === "Home") {
        targetIndex = 0;
      } else if (key === "End") {
        targetIndex = options.length - 1;
      } else if (selectedIndex < 0 && key === "ArrowUp") {
        targetIndex = options.length - 1;
      }
      focusOption(picker, targetIndex);
    });
  }

  function mountRolePicker(picker) {
    if (picker.dataset.workspaceRolePickerReady === "true") {
      return;
    }

    const nativeWrapper = picker.querySelector("[data-workspace-role-picker-native]");
    const enhancedWrapper = picker.querySelector("[data-workspace-role-picker-enhanced]");
    const select = picker.querySelector("select[name='role']");
    const trigger = picker.querySelector("[data-dropdown-toggle]");
    const menu = picker.querySelector("[data-dropdown-menu]");
    const options = optionsFor(picker);
    if (!nativeWrapper || !enhancedWrapper || !select || !trigger || !menu || !options.length) {
      return;
    }

    const receivesModalFocus = select.hasAttribute("data-modal-input-focus");
    const shouldAutofocus = select.autofocus;
    const associatedLabel = Array.from(globalScope.document?.querySelectorAll("label[for]") || [])
      .find((label) => label.htmlFor === select.id);
    nativeWrapper.hidden = true;
    enhancedWrapper.hidden = false;
    select.setAttribute("aria-hidden", "true");
    select.tabIndex = -1;
    select.removeAttribute("data-modal-input-focus");
    select.autofocus = false;
    if (receivesModalFocus) {
      trigger.setAttribute("data-modal-input-focus", "");
    }
    if (shouldAutofocus) {
      trigger.autofocus = true;
    }
    if (associatedLabel) {
      associatedLabel.htmlFor = trigger.id;
    }

    syncRoleSelection(picker, select.value);

    trigger.addEventListener("click", () => {
      if (typeof globalScope.toggleDropdown !== "function") {
        const shouldOpen = menu.classList.contains("hidden");
        menu.classList.toggle("hidden", !shouldOpen);
        menu.classList.toggle("opacity-0", !shouldOpen);
        menu.classList.toggle("scale-95", !shouldOpen);
        menu.classList.toggle("opacity-100", shouldOpen);
        menu.classList.toggle("scale-100", shouldOpen);
        trigger.setAttribute("aria-expanded", String(shouldOpen));
      }
      scheduleMenuPosition(picker);
    });
    trigger.addEventListener("keydown", (event) => {
      if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
        event.preventDefault();
        event.stopPropagation();
        openMenuFromKeyboard(picker, event.key);
        return;
      }
      if (event.key === "Escape" && !menu.classList.contains("hidden")) {
        event.preventDefault();
        event.stopPropagation();
        closeMenu(picker, { restoreFocus: true });
      }
    });

    options.forEach((option) => {
      option.addEventListener("click", () => {
        if (syncRoleSelection(picker, option.dataset.workspaceRoleOption, { dispatchChange: true })) {
          closeMenu(picker, { restoreFocus: true });
        }
      });
    });

    menu.addEventListener("keydown", (event) => {
      const activeOption = event.target.closest?.(optionSelector);
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        closeMenu(picker, { restoreFocus: true });
        return;
      }
      if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
        event.preventDefault();
        event.stopPropagation();
        const currentIndex = options.indexOf(activeOption);
        focusOption(picker, optionIndexForKey(currentIndex, options.length, event.key));
        return;
      }
      if ((event.key === "Enter" || event.key === " ") && activeOption) {
        event.preventDefault();
        event.stopPropagation();
        activeOption.click();
      }
    });

    picker.addEventListener("focusout", () => {
      globalScope.setTimeout(() => {
        if (!picker.contains(globalScope.document?.activeElement)) {
          closeMenu(picker);
        }
      }, 0);
    });
    select.addEventListener("change", () => {
      syncRoleSelection(picker, select.value);
    });

    picker.dataset.workspaceRolePickerReady = "true";
  }

  function positionOpenMenus() {
    globalScope.document?.querySelectorAll(pickerSelector).forEach(positionMenu);
  }

  function mount() {
    const documentObject = globalScope.document;
    if (!documentObject) {
      return;
    }
    documentObject.querySelectorAll(pickerSelector).forEach(mountRolePicker);
    globalScope.addEventListener?.("resize", positionOpenMenus);
    globalScope.addEventListener?.("scroll", positionOpenMenus, true);
  }

  if (globalScope.document) {
    if (globalScope.document.readyState === "loading") {
      globalScope.document.addEventListener("DOMContentLoaded", mount, { once: true });
    } else {
      mount();
    }
  }

  return {
    mount,
    mountRolePicker,
    optionIndexForKey,
    shouldOpenAbove,
    syncRoleSelection
  };
});
