const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { create } = require("../../static/js/tracker/replay-playback-feedback.js");

const root = path.resolve(__dirname, "../..");

class FakeClassList {
  constructor(...classes) {
    this.classes = new Set(classes);
  }

  add(...classes) {
    classes.forEach((className) => this.classes.add(className));
  }

  remove(...classes) {
    classes.forEach((className) => this.classes.delete(className));
  }

  toggle(className, force) {
    const shouldAdd = force === undefined ? !this.classes.has(className) : Boolean(force);
    if (shouldAdd) this.classes.add(className);
    else this.classes.delete(className);
    return shouldAdd;
  }

  contains(className) {
    return this.classes.has(className);
  }
}

class FakeElement {
  constructor(...classes) {
    this.attributes = new Map();
    this.classList = new FakeClassList(...classes);
    this.dataset = {};
    this.offsetWidth = 640;
    this.textContent = "";
  }

  getAttribute(name) {
    return this.attributes.get(name) ?? null;
  }

  setAttribute(name, value) {
    this.attributes.set(name, String(value));
  }
}

const element = new FakeElement("replay-playback-feedback");
element.setAttribute("aria-hidden", "true");
const playIcon = new FakeElement();
const pauseIcon = new FakeElement("hidden");
const label = new FakeElement();
const timers = [];
const schedule = (callback, delay) => {
  const timer = { callback, canceled: false, delay };
  timers.push(timer);
  return timer;
};
const cancel = (timer) => {
  timer.canceled = true;
};

const feedback = create({
  element,
  playIcon,
  pauseIcon,
  label,
  schedule,
  cancel
});

feedback.show(false);
assert.equal(element.dataset.state, "paused");
assert.equal(element.getAttribute("aria-hidden"), "false");
assert.equal(element.classList.contains("replay-playback-feedback--visible"), true);
assert.equal(playIcon.classList.contains("hidden"), true);
assert.equal(pauseIcon.classList.contains("hidden"), false);
assert.equal(label.textContent, "Paused");
assert.equal(timers[0].delay, 1000);

feedback.show(true);
assert.equal(timers[0].canceled, true);
assert.equal(element.dataset.state, "playing");
assert.equal(playIcon.classList.contains("hidden"), false);
assert.equal(pauseIcon.classList.contains("hidden"), true);
assert.equal(label.textContent, "Playing");

// Even if an already-canceled callback is delivered, it cannot hide newer feedback.
timers[0].callback();
assert.equal(element.classList.contains("replay-playback-feedback--visible"), true);
assert.equal(element.getAttribute("aria-hidden"), "false");

timers[1].callback();
assert.equal(element.classList.contains("replay-playback-feedback--visible"), false);
assert.equal(element.getAttribute("aria-hidden"), "true");

feedback.show(false);
feedback.destroy();
assert.equal(timers[2].canceled, true);
assert.equal(element.classList.contains("replay-playback-feedback--visible"), false);
assert.equal(element.getAttribute("aria-hidden"), "true");

feedback.show(true);
assert.equal(timers.length, 3);

const replayTemplate = fs.readFileSync(
  path.join(root, "apps/tracker/templates/tracker/recording.html"),
  "utf8"
);
assert.match(
  replayTemplate,
  /\$\('playBtn'\)\.addEventListener\('click', \(\) => \{\s+togglePlayback\(\);\s+\}\);/
);
assert.match(
  replayTemplate,
  /\$\('player'\)\.addEventListener\('click', \(event\) => \{[\s\S]*?togglePlayback\(true\);\s+\}\);/
);

const recordingCss = fs.readFileSync(
  path.join(root, "static/css/tracker/recording.css"),
  "utf8"
);
assert.match(
  recordingCss,
  /\.replay-playback-feedback \{[\s\S]*?pointer-events: none;[\s\S]*?\}/
);
assert.match(
  recordingCss,
  /@media \(prefers-reduced-motion: reduce\) \{[\s\S]*?animation-name: replay-playback-feedback-reduced;/
);

console.log("replay-playback-feedback tests passed");
