const assert = require("node:assert/strict");
const path = require("node:path");
const test = require("node:test");

const rolePicker = require(path.resolve(
  __dirname,
  "../../static/js/workspace-role-picker.js"
));

test("role picker keyboard navigation wraps and supports boundaries", () => {
  assert.equal(rolePicker.optionIndexForKey(-1, 4, "ArrowDown"), 0);
  assert.equal(rolePicker.optionIndexForKey(0, 4, "ArrowUp"), 3);
  assert.equal(rolePicker.optionIndexForKey(3, 4, "ArrowDown"), 0);
  assert.equal(rolePicker.optionIndexForKey(2, 4, "Home"), 0);
  assert.equal(rolePicker.optionIndexForKey(1, 4, "End"), 3);
  assert.equal(rolePicker.optionIndexForKey(1, 0, "ArrowDown"), -1);
});

test("role picker opens above only when that provides more usable space", () => {
  assert.equal(
    rolePicker.shouldOpenAbove({ top: 300, bottom: 344 }, 500, 320),
    true
  );
  assert.equal(
    rolePicker.shouldOpenAbove({ top: 50, bottom: 94 }, 500, 320),
    false
  );
});

test("role selection synchronizes the form value, label, and selected option", () => {
  function createOption(value, name, selected = false) {
    const attributes = { "aria-selected": String(selected) };
    return {
      dataset: {
        workspaceRoleOption: value,
        workspaceRoleName: name
      },
      tabIndex: selected ? 0 : -1,
      textContent: name,
      getAttribute(attribute) {
        return attributes[attribute] ?? null;
      },
      setAttribute(attribute, attributeValue) {
        attributes[attribute] = String(attributeValue);
      }
    };
  }

  const options = [
    createOption("admin", "Admin"),
    createOption("member", "Member", true),
    createOption("viewer", "Viewer")
  ];
  const dispatchedEvents = [];
  const select = {
    value: "member",
    dispatchEvent(event) {
      dispatchedEvents.push(event.type);
    }
  };
  const label = { textContent: "Member" };
  const triggerAttributes = {};
  const trigger = {
    dataset: { workspaceRolePickerAriaLabel: "User role" },
    setAttribute(attribute, attributeValue) {
      triggerAttributes[attribute] = String(attributeValue);
    }
  };
  const picker = {
    querySelector(selector) {
      if (selector === "select[name='role']") return select;
      if (selector === "[data-workspace-role-picker-label]") return label;
      if (selector === "[data-dropdown-toggle]") return trigger;
      return null;
    },
    querySelectorAll(selector) {
      return selector === "[data-workspace-role-option]" ? options : [];
    }
  };

  assert.equal(
    rolePicker.syncRoleSelection(picker, "viewer", { dispatchChange: true }),
    true
  );
  assert.equal(select.value, "viewer");
  assert.equal(label.textContent, "Viewer");
  assert.equal(triggerAttributes["aria-label"], "User role: Viewer");
  assert.deepEqual(options.map((option) => option.getAttribute("aria-selected")), ["false", "false", "true"]);
  assert.deepEqual(options.map((option) => option.tabIndex), [-1, -1, 0]);
  assert.deepEqual(dispatchedEvents, ["change"]);
  assert.equal(rolePicker.syncRoleSelection(picker, "owner"), false);
  assert.equal(select.value, "viewer");
});

test("mounting enhances the native control and preserves selection without the shared dropdown script", async () => {
  function createClassList(initial = []) {
    const classes = new Set(initial);
    return {
      add(...names) {
        names.forEach((name) => classes.add(name));
      },
      contains(name) {
        return classes.has(name);
      },
      remove(...names) {
        names.forEach((name) => classes.delete(name));
      },
      toggle(name, force) {
        const shouldAdd = force === undefined ? !classes.has(name) : force;
        if (shouldAdd) classes.add(name);
        else classes.delete(name);
        return shouldAdd;
      }
    };
  }

  function createEventTarget(properties = {}) {
    const listeners = {};
    return {
      ...properties,
      addEventListener(type, listener) {
        (listeners[type] ||= []).push(listener);
      },
      emit(type, event = {}) {
        (listeners[type] || []).forEach((listener) => listener(event));
      }
    };
  }

  function createOption(value, name, selected = false) {
    const attributes = { "aria-selected": String(selected) };
    const option = createEventTarget({
      classList: createClassList(),
      dataset: {
        workspaceRoleOption: value,
        workspaceRoleName: name
      },
      tabIndex: selected ? 0 : -1,
      textContent: name,
      focus() {},
      scrollIntoView() {},
      getAttribute(attribute) {
        return attributes[attribute] ?? null;
      },
      setAttribute(attribute, attributeValue) {
        attributes[attribute] = String(attributeValue);
      }
    });
    option.click = () => option.emit("click");
    return option;
  }

  const options = [
    createOption("admin", "Admin"),
    createOption("member", "Member", true),
    createOption("viewer", "Viewer")
  ];
  const nativeWrapper = { hidden: false };
  const enhancedWrapper = { hidden: true };
  const selectAttributes = new Set(["data-modal-input-focus"]);
  const select = createEventTarget({
    id: "mounted-role",
    value: "member",
    autofocus: true,
    tabIndex: 0,
    hasAttribute(attribute) {
      return selectAttributes.has(attribute);
    },
    removeAttribute(attribute) {
      selectAttributes.delete(attribute);
    },
    setAttribute(attribute) {
      selectAttributes.add(attribute);
    },
    dispatchEvent() {}
  });
  const triggerAttributes = {};
  let triggerFocused = false;
  const trigger = createEventTarget({
    id: "mounted-role-trigger",
    autofocus: false,
    classList: createClassList(),
    dataset: { workspaceRolePickerAriaLabel: "New user role" },
    focus() {
      triggerFocused = true;
    },
    getBoundingClientRect() {
      return { top: 100, bottom: 144 };
    },
    setAttribute(attribute, attributeValue) {
      triggerAttributes[attribute] = String(attributeValue);
    }
  });
  const menu = createEventTarget({
    classList: createClassList(["hidden", "opacity-0", "scale-95"]),
    scrollHeight: 240,
    style: {}
  });
  const label = { textContent: "Member" };
  const externalLabel = { htmlFor: "mounted-role" };
  const picker = createEventTarget({
    dataset: {},
    contains() {
      return false;
    },
    querySelector(selector) {
      const elements = {
        "[data-workspace-role-picker-native]": nativeWrapper,
        "[data-workspace-role-picker-enhanced]": enhancedWrapper,
        "select[name='role']": select,
        "[data-dropdown-toggle]": trigger,
        "[data-dropdown-menu]": menu,
        "[data-workspace-role-picker-label]": label
      };
      return elements[selector] || null;
    },
    querySelectorAll(selector) {
      return selector === "[data-workspace-role-option]" ? options : [];
    }
  });

  const originalDocument = global.document;
  global.document = {
    activeElement: null,
    documentElement: { clientHeight: 500 },
    querySelectorAll(selector) {
      if (selector === "label[for]") return [externalLabel];
      if (selector === "[data-dropdown-menu]") return [menu];
      return [];
    }
  };

  try {
    rolePicker.mountRolePicker(picker);

    assert.equal(nativeWrapper.hidden, true);
    assert.equal(enhancedWrapper.hidden, false);
    assert.equal(select.tabIndex, -1);
    assert.equal(select.hasAttribute("aria-hidden"), true);
    assert.equal(select.hasAttribute("data-modal-input-focus"), false);
    assert.equal(triggerAttributes["data-modal-input-focus"], "");
    assert.equal(trigger.autofocus, true);
    assert.equal(externalLabel.htmlFor, "mounted-role-trigger");
    assert.equal(picker.dataset.workspaceRolePickerReady, "true");

    trigger.emit("click");
    assert.equal(menu.classList.contains("hidden"), false);
    assert.equal(triggerAttributes["aria-expanded"], "true");

    options[2].click();
    assert.equal(select.value, "viewer");
    assert.equal(label.textContent, "Viewer");
    assert.equal(triggerAttributes["aria-label"], "New user role: Viewer");
    assert.equal(menu.classList.contains("hidden"), true);
    assert.equal(triggerFocused, true);

    await new Promise((resolve) => setTimeout(resolve, 5));
  } finally {
    global.document = originalDocument;
  }
});
