(function mountAnalyticsVariantPolling(globalScope) {
  // A cold variant is built by a worker, so the wait is bounded by that build
  // rather than by anything the page can influence. What the schedule controls
  // is how much of the build is spent already finished but not yet noticed.
  //
  // That cost is relative, not absolute. Waiting three seconds on a build that
  // took forty is barely visible; waiting three seconds on a build that took
  // four doubles it. So the gap has to start far below the shortest plausible
  // build and grow with elapsed time, which keeps the wasted fraction roughly
  // constant instead of concentrating it where it hurts most.
  //
  // The first poll is also the one that catches a build already in flight when
  // the page loaded -- another tab, or a request inside the dispatch dedup
  // window -- which can complete at any moment, including immediately.
  const FIRST_DELAY_MS = 400;
  const MAX_DELAY_MS = 10000;
  const BACKOFF = 1.3;
  const GIVE_UP_AFTER_MS = 5 * 60 * 1000;

  function nextDelay(previousDelay) {
    if (!previousDelay) {
      return FIRST_DELAY_MS;
    }
    return Math.min(Math.round(previousDelay * BACKOFF), MAX_DELAY_MS);
  }

  if (globalScope.__HymetryExposeTestHooks) {
    globalScope.HymetryAnalyticsVariantPollingTesting = {
      FIRST_DELAY_MS,
      MAX_DELAY_MS,
      BACKOFF,
      GIVE_UP_AFTER_MS,
      nextDelay
    };
  }

  const marker = document.querySelector("[data-analytics-preparing]");

  if (!marker || !globalScope.fetch) {
    return;
  }

  const statusUrl = marker.getAttribute("data-analytics-status-url") || "";
  const surface = marker.getAttribute("data-analytics-surface") || "";

  if (!statusUrl || !surface) {
    return;
  }

  const startedAt = Date.now();
  let delay = nextDelay(0);
  let stopped = false;

  function requestUrl() {
    const url = new URL(statusUrl, globalScope.location.origin);
    const current = new URLSearchParams(globalScope.location.search);

    url.searchParams.set("surface", surface);
    const range = current.get("range");
    if (range) {
      url.searchParams.set("range", range);
    }
    current.forEach((value, key) => {
      if (key.startsWith("ca.")) {
        url.searchParams.append(key, value);
      }
    });
    return `${url.pathname}${url.search}`;
  }

  function giveUp() {
    stopped = true;
    const message = document.querySelector("[data-analytics-preparing-message]");
    if (message) {
      message.textContent =
        "This is taking longer than expected. Reload the page to check again.";
    }
    marker.remove();
  }

  function schedule() {
    if (stopped) {
      return;
    }
    if (Date.now() - startedAt > GIVE_UP_AFTER_MS) {
      giveUp();
      return;
    }
    globalScope.setTimeout(poll, delay);
    delay = nextDelay(delay);
  }

  function poll() {
    if (stopped || document.visibilityState === "hidden") {
      schedule();
      return;
    }

    globalScope
      .fetch(requestUrl(), {
        credentials: "same-origin",
        headers: { Accept: "application/json" }
      })
      .then((response) => (response.ok ? response.json() : null))
      .then((data) => {
        if (data && data.ready) {
          stopped = true;
          globalScope.location.reload();
          return;
        }
        schedule();
      })
      .catch(() => schedule());
  }

  schedule();
})(window);
