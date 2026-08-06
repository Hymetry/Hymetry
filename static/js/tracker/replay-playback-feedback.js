(function (root, factory) {
  const api = factory();

  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }

  root.ReplayPlaybackFeedback = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const DEFAULT_DURATION_MS = 1000;
  const VISIBLE_CLASS = "replay-playback-feedback--visible";

  function create(options) {
    const config = options || {};
    const element = config.element;
    const playIcon = config.playIcon;
    const pauseIcon = config.pauseIcon;
    const label = config.label;
    if (!element || !playIcon || !pauseIcon || !label) {
      throw new Error("Replay playback feedback requires its element, icons, and label.");
    }

    const requestedDuration = Number(config.durationMs);
    const durationMs = Number.isFinite(requestedDuration) && requestedDuration >= 0
      ? requestedDuration
      : DEFAULT_DURATION_MS;
    const schedule = config.schedule || ((callback, delay) => setTimeout(callback, delay));
    const cancel = config.cancel || ((timer) => clearTimeout(timer));
    let hideTimer = null;
    let generation = 0;
    let destroyed = false;

    function hide() {
      element.classList.remove(VISIBLE_CLASS);
      element.setAttribute("aria-hidden", "true");
    }

    function show(playing) {
      if (destroyed) return;
      const shouldPlay = Boolean(playing);
      const currentGeneration = ++generation;
      playIcon.classList.toggle("hidden", !shouldPlay);
      pauseIcon.classList.toggle("hidden", shouldPlay);
      element.setAttribute("aria-hidden", "false");
      label.textContent = shouldPlay ? "Playing" : "Paused";
      element.dataset.state = shouldPlay ? "playing" : "paused";

      if (hideTimer !== null) cancel(hideTimer);
      element.classList.remove(VISIBLE_CLASS);
      void element.offsetWidth;
      element.classList.add(VISIBLE_CLASS);
      hideTimer = schedule(() => {
        if (destroyed || currentGeneration !== generation) return;
        hideTimer = null;
        hide();
      }, durationMs);
    }

    function destroy() {
      if (destroyed) return;
      destroyed = true;
      generation += 1;
      if (hideTimer !== null) {
        cancel(hideTimer);
        hideTimer = null;
      }
      hide();
    }

    return { destroy, show };
  }

  return { create };
});
