(function mountNetworkLoaders(globalScope) {
  "use strict";

  const SVG_NS = "http://www.w3.org/2000/svg";
  const document = globalScope.document;
  const activeLoaderCounts = new WeakMap();

  if (!document) {
    return;
  }

  const DEFAULT_POINTS = [
    [10.4, 13.4],
    [46.7, 9.0],
    [99.1, 9.1],
    [139.7, 10.6],
    [75.4, 22.2],
    [119.4, 28.4],
    [23.8, 34.1],
    [54.4, 36.2],
    [91.2, 39.3],
    [137.4, 43.4],
    [9.2, 52.6],
    [74.5, 56.4],
    [105.5, 58.1],
    [39.5, 62.0],
    [133.4, 66.5],
    [15.5, 79.0],
    [55.3, 79.5],
    [77.7, 80.4],
    [104.5, 81.4],
    [45.0, 100.7],
    [119.2, 102.0],
    [141.6, 104.8],
    [11.3, 105.5],
    [81.6, 105.0]
  ];

  const DEFAULTS = {
    minNodes: 3,
    maxNodes: 7,
    stepDuration: 210,
    holdDuration: 230,
    fadeDuration: 380,
    pauseDuration: 260,
    connectionCheckInterval: 1000,
    minLinkDistance: 17,
    maxLinkDistance: 43
  };

  function activateWaitCursor(ownerDocument) {
    const activeCount = activeLoaderCounts.get(ownerDocument) || 0;
    activeLoaderCounts.set(ownerDocument, activeCount + 1);
    ownerDocument.documentElement.classList.add("network-loader-active");
  }

  function deactivateWaitCursor(ownerDocument) {
    const activeCount = activeLoaderCounts.get(ownerDocument) || 0;
    if (activeCount > 1) {
      activeLoaderCounts.set(ownerDocument, activeCount - 1);
      return;
    }

    activeLoaderCounts.delete(ownerDocument);
    ownerDocument.documentElement.classList.remove("network-loader-active");
  }

  function createSvgElement(name, attributes = {}) {
    const element = document.createElementNS(SVG_NS, name);
    for (const [key, value] of Object.entries(attributes)) {
      element.setAttribute(key, String(value));
    }
    return element;
  }

  function distance(a, b) {
    return Math.hypot(a[0] - b[0], a[1] - b[1]);
  }

  function randomInteger(min, max) {
    return Math.floor(Math.random() * (max - min + 1)) + min;
  }

  function randomItem(items) {
    return items[Math.floor(Math.random() * items.length)];
  }

  class NetworkLoader {
    constructor(root, options = {}) {
      if (!(root instanceof globalScope.HTMLElement)) {
        throw new TypeError("NetworkLoader requires an HTMLElement root.");
      }

      this.root = root;
      this.options = { ...DEFAULTS, ...options };
      this.points = options.points || DEFAULT_POINTS;
      this.destroyed = false;
      this.waitCursorActive = false;
      this.timers = new Map();
      this.activeElements = [];
      this.lastStartIndex = -1;
      this.runGeneration = 0;
      this.motionQuery = globalScope.matchMedia(
        "(prefers-reduced-motion: reduce)"
      );
      this.handleMotionPreferenceChange = () => {
        this.applyMotionPreference();
      };

      this.build();
      activateWaitCursor(this.root.ownerDocument);
      this.waitCursorActive = true;
      this.adjacency = this.buildAdjacency();
      if (this.motionQuery.addEventListener) {
        this.motionQuery.addEventListener(
          "change",
          this.handleMotionPreferenceChange
        );
      } else {
        this.motionQuery.addListener(this.handleMotionPreferenceChange);
      }
      this.applyMotionPreference();
    }

    build() {
      this.root.classList.add("network-loader");
      this.root.setAttribute("aria-hidden", "true");

      this.svg = createSvgElement("svg", {
        class: "network-loader__svg",
        viewBox: "0 0 150 115",
        "aria-hidden": "true",
        focusable: "false"
      });

      this.linesLayer = createSvgElement("g");
      this.dotsLayer = createSvgElement("g");
      this.traceLayer = createSvgElement("g");

      this.points.forEach(([cx, cy], index) => {
        const dot = createSvgElement("circle", {
          class: "network-loader__dot",
          cx,
          cy,
          r: index % 7 === 0 ? 4.05 : 3.65
        });
        this.dotsLayer.append(dot);
      });

      this.head = createSvgElement("g", {
        class: "network-loader__head"
      });
      this.head.append(
        createSvgElement("circle", {
          class: "network-loader__head-halo",
          cx: 0,
          cy: 0,
          r: 7.4
        }),
        createSvgElement("circle", {
          class: "network-loader__head-core",
          cx: 0,
          cy: 0,
          r: 4.65
        })
      );
      this.traceLayer.append(this.head);

      this.svg.append(this.linesLayer, this.dotsLayer, this.traceLayer);
      this.root.replaceChildren(this.svg);
    }

    buildAdjacency() {
      const { minLinkDistance, maxLinkDistance } = this.options;

      return this.points.map((point, index) => {
        const neighbours = this.points
          .map((otherPoint, otherIndex) => ({
            index: otherIndex,
            distance: distance(point, otherPoint)
          }))
          .filter(
            ({ index: otherIndex, distance: value }) =>
              otherIndex !== index &&
              value >= minLinkDistance &&
              value <= maxLinkDistance
          )
          .sort((a, b) => a.distance - b.distance);

        return neighbours.slice(0, 7).map(({ index: otherIndex }) => otherIndex);
      });
    }

    createRoute() {
      const desiredLength = randomInteger(
        this.options.minNodes,
        this.options.maxNodes
      );

      const validStarts = this.adjacency
        .map((neighbours, index) => ({ index, count: neighbours.length }))
        .filter(
          ({ index, count }) => count >= 2 && index !== this.lastStartIndex
        )
        .map(({ index }) => index);

      const fallbackStarts = this.points.map((_, index) => index);
      const start = randomItem(validStarts.length ? validStarts : fallbackStarts);
      const route = [start];
      const visited = new Set(route);

      while (route.length < desiredLength) {
        const current = route.at(-1);
        const previous = route.length > 1 ? route.at(-2) : -1;
        let candidates = this.adjacency[current].filter(
          (index) => !visited.has(index)
        );

        if (previous >= 0 && candidates.length > 1) {
          const [px, py] = this.points[previous];
          const [cx, cy] = this.points[current];
          const incomingAngle = Math.atan2(cy - py, cx - px);

          candidates = candidates
            .map((index) => {
              const [nx, ny] = this.points[index];
              const outgoingAngle = Math.atan2(ny - cy, nx - cx);
              const turn = Math.abs(
                Math.atan2(
                  Math.sin(outgoingAngle - incomingAngle),
                  Math.cos(outgoingAngle - incomingAngle)
                )
              );
              return { index, score: turn + Math.random() * 0.9 };
            })
            .sort((a, b) => a.score - b.score)
            .slice(0, 3)
            .map((item) => item.index);
        }

        if (!candidates.length) {
          break;
        }

        const next = randomItem(candidates);
        route.push(next);
        visited.add(next);
      }

      this.lastStartIndex = start;
      return route;
    }

    reveal(element) {
      globalScope.requestAnimationFrame(() => {
        if (!this.destroyed && element.isConnected) {
          element.classList.add("is-visible");
        }
      });
    }

    addRing(pointIndex) {
      const [cx, cy] = this.points[pointIndex];
      const ring = createSvgElement("circle", {
        class: "network-loader__ring",
        cx,
        cy,
        r: 6.7
      });

      this.traceLayer.insertBefore(ring, this.head);
      this.activeElements.push(ring);
      this.reveal(ring);
    }

    addLine(fromIndex, toIndex) {
      const [x1, y1] = this.points[fromIndex];
      const [x2, y2] = this.points[toIndex];
      const line = createSvgElement("line", {
        class: "network-loader__line",
        x1,
        y1,
        x2,
        y2,
        pathLength: 1,
        "stroke-dasharray": 1,
        "stroke-dashoffset": 1
      });

      this.linesLayer.append(line);
      this.activeElements.push(line);
      this.reveal(line);
    }

    moveHead(pointIndex, immediate = false) {
      const [x, y] = this.points[pointIndex];

      if (immediate) {
        this.head.style.transition = "none";
        this.head.style.transform = `translate(${x}px, ${y}px)`;
        this.head.getBoundingClientRect();
        this.head.style.transition = "";
      } else {
        this.head.style.transform = `translate(${x}px, ${y}px)`;
      }

      this.head.classList.add("is-visible");
    }

    wait(milliseconds) {
      return new Promise((resolve) => {
        const timer = globalScope.setTimeout(() => {
          this.timers.delete(timer);
          if (!this.root.isConnected) {
            this.destroy();
          }
          resolve();
        }, milliseconds);
        this.timers.set(timer, resolve);
      });
    }

    cancelPendingWaits() {
      this.timers.forEach((resolve, timer) => {
        globalScope.clearTimeout(timer);
        resolve();
      });
      this.timers.clear();
    }

    clearRoute() {
      this.activeElements.forEach((element) => element.remove());
      this.activeElements = [];
      this.linesLayer.replaceChildren();
      this.head.classList.remove("is-visible", "is-fading");
    }

    isStopped(generation) {
      return this.destroyed || generation !== this.runGeneration;
    }

    applyMotionPreference() {
      if (this.destroyed) {
        return;
      }

      const generation = this.runGeneration + 1;
      this.runGeneration = generation;
      this.cancelPendingWaits();
      this.clearRoute();

      if (this.motionQuery.matches) {
        this.moveHead(11, true);
        this.monitorConnection(generation);
        return;
      }

      this.run(generation);
    }

    async monitorConnection(generation) {
      while (!this.isStopped(generation)) {
        await this.wait(this.options.connectionCheckInterval);
      }
    }

    async playRoute(route, generation) {
      const { stepDuration, holdDuration, fadeDuration } = this.options;

      this.moveHead(route[0], true);
      await this.wait(Math.round(stepDuration * 0.55));
      if (this.isStopped(generation)) {
        return;
      }

      for (let index = 1; index < route.length; index += 1) {
        const from = route[index - 1];
        const to = route[index];

        this.addRing(from);
        this.addLine(from, to);
        this.moveHead(to);

        await this.wait(stepDuration);
        if (this.isStopped(generation)) {
          return;
        }
      }

      this.addRing(route.at(-1));
      this.head.classList.remove("is-visible");

      await this.wait(holdDuration);
      if (this.isStopped(generation)) {
        return;
      }

      const elements = [...this.activeElements];
      for (const element of elements) {
        element.classList.add("is-fading");
        await this.wait(
          Math.max(24, Math.round(fadeDuration / elements.length))
        );
        if (this.isStopped(generation)) {
          return;
        }
      }

      await this.wait(fadeDuration);
      if (this.isStopped(generation)) {
        return;
      }
      elements.forEach((element) => element.remove());
      this.activeElements = [];
    }

    async run(generation) {
      while (!this.isStopped(generation)) {
        await this.playRoute(this.createRoute(), generation);
        if (!this.isStopped(generation)) {
          await this.wait(this.options.pauseDuration);
        }
      }
    }

    destroy() {
      if (this.destroyed) {
        return;
      }

      this.destroyed = true;
      this.runGeneration += 1;
      if (this.motionQuery.removeEventListener) {
        this.motionQuery.removeEventListener(
          "change",
          this.handleMotionPreferenceChange
        );
      } else {
        this.motionQuery.removeListener(this.handleMotionPreferenceChange);
      }
      this.cancelPendingWaits();
      this.clearRoute();
      if (this.waitCursorActive) {
        deactivateWaitCursor(this.root.ownerDocument);
        this.waitCursorActive = false;
      }
      this.root.replaceChildren();
      if (this.root.networkLoader === this) {
        delete this.root.networkLoader;
      }
    }
  }

  globalScope.NetworkLoader = NetworkLoader;

  function initialiseLoaders() {
    document.querySelectorAll("[data-network-loader]").forEach((element) => {
      if (!element.networkLoader) {
        element.networkLoader = new NetworkLoader(element);
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialiseLoaders, {
      once: true
    });
  } else {
    initialiseLoaders();
  }
})(window);
