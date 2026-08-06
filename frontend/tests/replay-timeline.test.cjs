const assert = require("node:assert/strict");
const {
  analyticalDisplayTime,
  clamp,
  create,
  formatDuration,
  normalizeSegments,
  readableTextColor,
  segmentIndexAtTime,
  segmentTooltipData,
  seekPlayer,
  seekTimeFromClientX
} = require("../../static/js/tracker/replay-timeline.js");
const tooltipUi = require("../../static/js/shared/analytics-tooltips.js");

assert.equal(clamp(-20, 0, 100), 0);
assert.equal(clamp(120, 0, 100), 100);
assert.equal(clamp(25, 0, 100), 25);
assert.equal(formatDuration(83_000), "1m 23s");
assert.equal(readableTextColor("#CBD5E1"), "#0f172a");
assert.equal(readableTextColor("#123456"), "#ffffff");
assert.deepEqual(
  segmentTooltipData({
    kind: "page",
    label: "Projects list",
    productArea: "Project management",
    durationMs: 38_000
  }),
  {
    title: "Project management",
    rows: [
      { label: "Page", value: "Projects list" },
      { label: "Active time", value: "38s" }
    ]
  }
);
assert.deepEqual(
  segmentTooltipData({ kind: "inactive", label: "Inactive", durationMs: 12_000 }),
  { title: "Inactive", rows: [{ label: "Duration", value: "12s" }] }
);
assert.deepEqual(
  segmentTooltipData({ kind: "unavailable", label: "Unavailable", durationMs: 7_000 }),
  { title: "Unavailable", rows: [{ label: "Duration", value: "7s" }] }
);

// The analytical visit is the control clock. A shorter rrweb recording must
// still receive the exact analytical offset, while a longer recording cannot
// move the visible playhead beyond the analytical end.
const oneMinuteRecording = {
  durationMs: 60_000,
  sought: [],
  goto(timeMs) { this.sought.push(timeMs); }
};
assert.equal(seekPlayer(oneMinuteRecording, 480_000, 600_000), 480_000);
assert.deepEqual(oneMinuteRecording.sought, [480_000]);
assert.equal(analyticalDisplayTime(900_000, 600_000), 600_000);
assert.equal(analyticalDisplayTime(45_000, 600_000), 45_000);

const chronological = normalizeSegments([
  { kind: "page", page: "Dashboard", startMs: 0, endMs: 10_000 },
  { kind: "inactive", startMs: 10_000, endMs: 30_000 },
  { kind: "page", page: "Projects", startMs: 30_000, endMs: 60_000 },
  { kind: "page", page: "Dashboard", startMs: 60_000, endMs: 100_000 }
], 100_000);

assert.deepEqual(
  chronological.map(({ kind, label, startMs, endMs }) => ({ kind, label, startMs, endMs })),
  [
    { kind: "page", label: "Dashboard", startMs: 0, endMs: 10_000 },
    { kind: "inactive", label: "Inactive", startMs: 10_000, endMs: 30_000 },
    { kind: "page", label: "Projects", startMs: 30_000, endMs: 60_000 },
    { kind: "page", label: "Dashboard", startMs: 60_000, endMs: 100_000 }
  ]
);
assert.equal(chronological.filter((segment) => segment.label === "Dashboard").length, 2);
assert.equal(segmentIndexAtTime(chronological, 0, 100_000), 0);
assert.equal(segmentIndexAtTime(chronological, 10_000, 100_000), 1);
assert.equal(segmentIndexAtTime(chronological, 100_000, 100_000), 3);

const clippedCoverage = normalizeSegments([
  { kind: "page", page: "Before replay", startMs: -200, endMs: 200 },
  { kind: "page", page: "After gap", startMs: 400, endMs: 1_200 }
], 1_000);

assert.deepEqual(
  clippedCoverage.map(({ kind, startMs, endMs, durationMs }) => ({
    kind,
    startMs,
    endMs,
    durationMs
  })),
  [
    { kind: "page", startMs: 0, endMs: 200, durationMs: 200 },
    { kind: "unavailable", startMs: 200, endMs: 400, durationMs: 200 },
    { kind: "page", startMs: 400, endMs: 1_000, durationMs: 600 }
  ]
);
assert.equal(
  clippedCoverage.reduce((total, segment) => total + segment.durationMs, 0),
  1_000
);
clippedCoverage.forEach((segment, index) => {
  if (index > 0) assert.equal(segment.startMs, clippedCoverage[index - 1].endMs);
});

const durationOnly = normalizeSegments([
  { kind: "page", page: "Home", durationMs: 250 },
  { kind: "inactive", durationMs: 50 }
], 400);
assert.deepEqual(
  durationOnly.map(({ kind, startMs, endMs }) => ({ kind, startMs, endMs })),
  [
    { kind: "page", startMs: 0, endMs: 250 },
    { kind: "inactive", startMs: 250, endMs: 300 },
    { kind: "unavailable", startMs: 300, endMs: 400 }
  ]
);
assert.deepEqual(
  normalizeSegments([], 600).map(({ kind, startMs, endMs }) => ({ kind, startMs, endMs })),
  [{ kind: "unavailable", startMs: 0, endMs: 600 }]
);

const bounds = { left: 100, width: 400 };
assert.equal(seekTimeFromClientX(300, bounds, 120_000), 60_000);
assert.equal(seekTimeFromClientX(-50, bounds, 120_000), 0);
assert.equal(seekTimeFromClientX(900, bounds, 120_000), 120_000);
assert.equal(seekTimeFromClientX({ clientX: 350, ...bounds, durationMs: 100_000 }), 62_500);

class FakeElement {
  constructor(tagName, ownerDocument) {
    this.tagName = tagName.toUpperCase();
    this.ownerDocument = ownerDocument;
    this.attributes = new Map();
    this.children = [];
    this.style = {};
    this.className = "";
    this.textContent = "";
    this.listeners = new Map();
    this.bounds = { left: 20, width: 200 };
  }

  setAttribute(name, value) {
    this.attributes.set(name, String(value));
  }

  getAttribute(name) {
    return this.attributes.get(name) ?? null;
  }

  hasAttribute(name) {
    return this.attributes.has(name);
  }

  appendChild(child) {
    this.children.push(child);
    return child;
  }

  replaceChildren(...children) {
    this.children = children;
  }

  addEventListener(type, listener) {
    if (!this.listeners.has(type)) this.listeners.set(type, []);
    this.listeners.get(type).push(listener);
  }

  removeEventListener(type, listener) {
    const listeners = this.listeners.get(type) || [];
    this.listeners.set(type, listeners.filter((candidate) => candidate !== listener));
  }

  dispatch(type, event) {
    (this.listeners.get(type) || []).slice().forEach((listener) => listener(event));
  }

  getBoundingClientRect() {
    return this.bounds;
  }

  contains(candidate) {
    if (candidate === this) return true;
    return this.children.some((child) => (
      typeof child.contains === "function" ? child.contains(candidate) : child === candidate
    ));
  }
}

class FakeDocument {
  constructor() {
    this.listeners = new Map();
  }

  createElement(tagName) {
    return new FakeElement(tagName, this);
  }

  addEventListener(type, listener) {
    if (!this.listeners.has(type)) this.listeners.set(type, []);
    this.listeners.get(type).push(listener);
  }

  removeEventListener(type, listener) {
    const listeners = this.listeners.get(type) || [];
    this.listeners.set(type, listeners.filter((candidate) => candidate !== listener));
  }

  dispatch(type, event) {
    (this.listeners.get(type) || []).slice().forEach((listener) => listener(event));
  }
}

const fakeDocument = new FakeDocument();
const container = new FakeElement("div", fakeDocument);
const hoverMarker = new FakeElement("span", fakeDocument);
const soughtTimes = [];
const controller = create({
  container,
  hoverMarker,
  totalDuration: 1_000,
  segments: [
    {
      kind: "page",
      page: "Dashboard",
      productArea: "Workspace",
      startMs: 0,
      endMs: 250,
      color: "#CBD5E1"
    },
    {
      kind: "page",
      page: "Dashboard",
      productArea: "Workspace",
      startMs: 250,
      endMs: 1_000,
      color: "#123456"
    }
  ],
  onSeek: (timeMs) => soughtTimes.push(timeMs),
  tooltipUi
});

assert.equal((container.listeners.get("click") || []).length, 1);
assert.equal((container.listeners.get("pointermove") || []).length, 1);
assert.equal((container.listeners.get("pointerleave") || []).length, 1);
assert.equal((container.listeners.get("pointercancel") || []).length, 1);
assert.equal((fakeDocument.listeners.get("pointermove") || []).length, 1);
assert.equal(hoverMarker.hidden, true);
assert.equal(hoverMarker.getAttribute("aria-hidden"), "true");

container.dispatch("pointermove", { clientX: 70, pointerType: "mouse" });
assert.equal(hoverMarker.hidden, false);
assert.equal(hoverMarker.style.left, "25%");
assert.deepEqual(soughtTimes, []);
assert.equal(container.getAttribute("aria-valuenow"), "0");
fakeDocument.dispatch("pointermove", {
  target: container.children[0],
  pointerType: "mouse"
});
assert.equal(hoverMarker.hidden, false);
fakeDocument.dispatch("pointermove", {
  target: new FakeElement("div", fakeDocument),
  pointerType: "mouse"
});
assert.equal(hoverMarker.hidden, true);

container.dispatch("pointermove", { clientX: -50, pointerType: "mouse" });
assert.equal(hoverMarker.style.left, "0%");
container.dispatch("pointermove", { clientX: 400, pointerType: "mouse" });
assert.equal(hoverMarker.style.left, "100%");
container.dispatch("pointermove", { clientX: 70, pointerType: "touch" });
assert.equal(hoverMarker.hidden, true);

container.dispatch("pointermove", { clientX: 70, pointerType: "mouse" });
container.dispatch("pointerleave", {});
assert.equal(hoverMarker.hidden, true);
container.dispatch("pointermove", { clientX: 70, pointerType: "mouse" });
container.dispatch("pointercancel", {});
assert.equal(hoverMarker.hidden, true);

container.dispatch("click", { clientX: 70 });
assert.deepEqual(soughtTimes, [250]);
assert.equal(container.getAttribute("aria-valuenow"), "250");
assert.equal(container.getAttribute("aria-valuetext"), "0s of 1s");

assert.equal(container.children.length, 2);
assert.equal(
  container.children[0].className,
  "replay-timeline-segment replay-timeline-segment--page metric-header-tooltip"
);
assert.equal(container.children[0].style.left, "0%");
assert.equal(container.children[0].style.width, "25%");
assert.equal(container.children[0].style.color, "#0f172a");
assert.equal(container.children[1].style.color, "#ffffff");
assert.equal(container.children[0].children[0].className, "replay-timeline-segment__label");
assert.equal(container.children[0].children[0].textContent, "Dashboard");
assert.equal(container.children[0].getAttribute("title"), null);
assert.equal(container.children[0].getAttribute("aria-label"), "Dashboard: 0s");
assert.equal(container.children[0].getAttribute("data-tooltip-anchor"), "pointer");
assert.equal(container.children[0].getAttribute("data-tooltip-kind"), "replay-segment");
const firstTooltip = container.children[0].children[1];
const secondTooltip = container.children[1].children[1];
assert.equal(firstTooltip.className, "metric-header-tooltip__content");
assert.equal(firstTooltip.getAttribute("role"), "tooltip");
assert.equal(
  container.children[0].getAttribute("aria-describedby"),
  firstTooltip.id
);
assert.notEqual(firstTooltip.id, secondTooltip.id);
assert.equal(container.getAttribute("aria-describedby"), secondTooltip.id);
assert.match(firstTooltip.innerHTML, /analytics-tooltip__title">Workspace/);
assert.match(firstTooltip.innerHTML, /analytics-tooltip__label">Page/);
assert.match(firstTooltip.innerHTML, /analytics-tooltip__value">Dashboard/);
assert.match(firstTooltip.innerHTML, /analytics-tooltip__label">Active time/);

const terminalContainer = new FakeElement("div", fakeDocument);
create({
  container: terminalContainer,
  totalDuration: 1_000,
  segments: [
    { kind: "page", page: "Dashboard", startMs: 0, endMs: 999 },
    { kind: "page", page: "Projects", startMs: 999, endMs: 1_000 }
  ]
});
assert.match(
  terminalContainer.children[1].className,
  /replay-timeline-segment--terminal-marker/
);

controller.setCurrentTime(2_000);
assert.equal(container.getAttribute("aria-valuenow"), "1000");
controller.destroy();
assert.equal((container.listeners.get("click") || []).length, 0);
assert.equal((container.listeners.get("pointermove") || []).length, 0);
assert.equal((container.listeners.get("pointerleave") || []).length, 0);
assert.equal((container.listeners.get("pointercancel") || []).length, 0);
assert.equal((fakeDocument.listeners.get("pointermove") || []).length, 0);
assert.equal(hoverMarker.hidden, true);
container.dispatch("pointermove", { clientX: 120, pointerType: "mouse" });
assert.equal(hoverMarker.hidden, true);
container.dispatch("click", { clientX: 220 });
assert.deepEqual(soughtTimes, [250]);

console.log("replay-timeline tests passed");
