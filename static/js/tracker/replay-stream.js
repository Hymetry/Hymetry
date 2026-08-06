(function (root, factory) {
  const api = factory();

  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }

  root.ReplayStream = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const BOUNDARY_TOLERANCE_MS = 100;

  function finiteNumber(value, fallback = 0) {
    const number = Number(value);
    return Number.isFinite(number) ? number : fallback;
  }

  function positiveInteger(value, fallback) {
    return Math.max(1, Math.floor(finiteNumber(value, fallback)));
  }

  function defaultYieldControl() {
    return new Promise((resolve) => setTimeout(resolve, 0));
  }

  function defaultAbortController() {
    return typeof AbortController === "function" ? new AbortController() : {
      signal: undefined,
      abort() {}
    };
  }

  async function appendEventsInBatches({
    player,
    events,
    batchSize,
    yieldControl = defaultYieldControl,
    isCancelled = () => false
  }) {
    if (!player || typeof player.addEvent !== "function") {
      throw new TypeError("The installed rrweb-player does not expose addEvent");
    }

    const orderedEvents = Array.isArray(events) ? events : [];
    const size = positiveInteger(batchSize, 250);
    for (let offset = 0; offset < orderedEvents.length; offset += size) {
      if (isCancelled()) return false;
      const batchEnd = Math.min(offset + size, orderedEvents.length);
      for (let index = offset; index < batchEnd; index += 1) {
        if (isCancelled()) return false;
        player.addEvent(orderedEvents[index]);
      }
      // addEvent itself schedules a microtask. Yielding between bounded batches
      // lets rrweb consume them and keeps the replay controls responsive.
      await yieldControl();
    }
    return !isCancelled();
  }

  function destroyRrwebPlayer(player) {
    if (!player) return;
    let replayer = null;
    try {
      replayer = typeof player.getReplayer === "function" ? player.getReplayer() : null;
    } catch (_) {}
    try {
      if (replayer && typeof replayer.destroy === "function") replayer.destroy();
    } catch (_) {}
    try {
      if (typeof player.$destroy === "function") player.$destroy();
    } catch (_) {}
  }

  class ReplayStreamController {
    constructor(options = {}) {
      if (!options.player) throw new TypeError("ReplayStreamController requires a player");
      if (typeof options.fetchChunk !== "function") {
        throw new TypeError("ReplayStreamController requires fetchChunk");
      }

      this.player = options.player;
      this.fetchChunk = options.fetchChunk;
      this.fetchSeekBootstrap = typeof options.fetchSeekBootstrap === "function"
        ? options.fetchSeekBootstrap
        : null;
      this.createPlayer = typeof options.createPlayer === "function"
        ? options.createPlayer
        : null;
      this.onPlayerChange = options.onPlayerChange || (() => {});
      this.segmentStartMs = Math.max(0, finiteNumber(options.segmentStartMs));
      this.seekableFromMs = Math.max(
        this.segmentStartMs,
        finiteNumber(options.seekableFromMs, this.segmentStartMs)
      );
      this.seekCursor = options.seekCursor || null;
      this.cursor = options.initialCursor || null;
      this.hasMore = Boolean(options.initialHasMore && this.cursor);
      this.loadedThroughMs = Math.max(0, finiteNumber(options.initialLoadedThroughMs));
      this.fullDurationMs = Math.max(
        this.loadedThroughMs,
        finiteNumber(options.fullDurationMs, this.loadedThroughMs)
      );
      this.prefetchThresholdMs = Math.max(
        0,
        finiteNumber(options.prefetchThresholdMs, 30_000)
      );
      this.appendBatchSize = positiveInteger(options.appendBatchSize, 250);
      this.yieldControl = options.yieldControl || defaultYieldControl;
      this.createAbortController = options.createAbortController || defaultAbortController;
      this.onChunkMetadata = options.onChunkMetadata || (() => {});
      this.onChunk = options.onChunk || (() => {});
      this.onBufferingChange = options.onBufferingChange || (() => {});
      this.onPlayingIntentChange = options.onPlayingIntentChange || (() => {});
      this.onExhausted = options.onExhausted || (() => {});
      this.onError = options.onError || (() => {});
      this.destroyPlayer = options.destroyPlayer !== false;

      this.currentTimeMs = 0;
      this.playerTimeMs = 0;
      this.preserveDisplayTime = false;
      this.playIntent = false;
      this.actualPlayerState = "paused";
      this.buffering = false;
      this.destroyed = false;
      this.exhaustedNotified = false;
      this.waitingAtBoundary = false;
      this.boundaryLoadedThroughMs = null;
      this.boundaryReceivedEvents = false;
      this.error = null;
      this.abortController = null;
      this.pumpPromise = null;
      this.fetchAtLeastOne = false;
      this.requestedThroughMs = null;
      this.pendingSeekMs = null;
      this.pendingPlayerTargetMs = null;
      this.pendingTargetReady = null;
      this.lastCompletedSeekMs = null;
      this.seekGeneration = 0;
      this.remoteSeekPending = false;
      this.seekAbortController = null;
      this.seekPromise = null;
      this.failedSeekTargetMs = null;
      this.generation = 0;
    }

    get state() {
      return {
        cursor: this.cursor,
        seekCursor: this.seekCursor,
        segmentStartMs: this.segmentStartMs,
        seekableFromMs: this.seekableFromMs,
        hasMore: this.hasMore,
        loadedThroughMs: this.loadedThroughMs,
        fullDurationMs: this.fullDurationMs,
        currentTimeMs: this.currentTimeMs,
        playerTimeMs: this.playerTimeMs,
        playIntent: this.playIntent,
        actualPlayerState: this.actualPlayerState,
        buffering: this.buffering,
        waitingAtBoundary: this.waitingAtBoundary,
        fetching: Boolean(this.pumpPromise),
        seeking: this.remoteSeekPending,
        destroyed: this.destroyed,
        error: this.error
      };
    }

    toRecordingTime(playerTimeMs) {
      return this.segmentStartMs + Math.max(0, finiteNumber(playerTimeMs));
    }

    toPlayerTime(recordingTimeMs) {
      return Math.max(0, finiteNumber(recordingTimeMs) - this.segmentStartMs);
    }

    _setTimes(displayTimeMs, playerTimeMs = displayTimeMs) {
      const displayTime = Math.max(0, finiteNumber(displayTimeMs));
      const replayTime = Math.max(0, finiteNumber(playerTimeMs, displayTime));
      this.currentTimeMs = displayTime;
      this.playerTimeMs = replayTime;
      this.preserveDisplayTime = displayTime > this.fullDurationMs
        && replayTime < displayTime;
    }

    _isLoadedInCurrentSegment(recordingTimeMs) {
      const target = finiteNumber(recordingTimeMs);
      return target >= this.seekableFromMs && target <= this.loadedThroughMs;
    }

    _setBuffering(flag) {
      const next = Boolean(flag);
      if (this.buffering === next) return;
      this.buffering = next;
      this.onBufferingChange(next);
    }

    _setPlayIntent(flag) {
      const next = Boolean(flag);
      if (this.playIntent === next) return;
      this.playIntent = next;
      this.onPlayingIntentChange(next);
    }

    _atLoadedBoundary(timeMs = this.playerTimeMs) {
      return timeMs >= this.loadedThroughMs - BOUNDARY_TOLERANCE_MS;
    }

    _clearBoundaryWait() {
      this.waitingAtBoundary = false;
      this.boundaryLoadedThroughMs = null;
      this.boundaryReceivedEvents = false;
    }

    _notifyTrueEnd() {
      if (this.hasMore || this.pumpPromise || this.destroyed) return;
      const shouldNotify = !this.exhaustedNotified;
      this.exhaustedNotified = true;
      this._clearBoundaryWait();
      this._setBuffering(false);
      this._setPlayIntent(false);
      if (shouldNotify) this.onExhausted();
    }

    _resumeAt(timeMs) {
      if (this.destroyed || !this.playIntent || this.pendingSeekMs !== null) return;
      const resumeOffset = Math.max(0, finiteNumber(timeMs, this.playerTimeMs));
      this.playerTimeMs = resumeOffset;
      if (!this.preserveDisplayTime) this.currentTimeMs = resumeOffset;
      this._setBuffering(false);
      // rrweb's finish latch makes plain play() restart at zero. goto(offset,
      // true) explicitly resumes from the temporary loaded boundary.
      this.player.goto(this.toPlayerTime(resumeOffset), true);
    }

    _settleBoundaryWait() {
      if (
        this.destroyed
        || this.error
        || !this.waitingAtBoundary
        || this.pendingSeekMs !== null
      ) return;

      const receivedMoreReplay = this.boundaryReceivedEvents || (
        this.boundaryLoadedThroughMs !== null
        && this.loadedThroughMs > this.boundaryLoadedThroughMs
      );
      if (receivedMoreReplay) {
        this._clearBoundaryWait();
        if (this.playIntent && this.actualPlayerState !== "playing") {
          this._resumeAt(this.playerTimeMs);
        } else {
          this._setBuffering(false);
        }
        return;
      }

      if (!this.hasMore && !this.pumpPromise) this._notifyTrueEnd();
    }

    _completePendingSeekIfReady() {
      if (this.pendingSeekMs === null || this.destroyed || this.error) return false;
      const requiredBoundary = this.pendingPlayerTargetMs === null
        ? Math.min(this.pendingSeekMs, this.fullDurationMs)
        : this.pendingPlayerTargetMs;
      const targetReady = !this.hasMore
        || this.pendingTargetReady === true
        || (
          this.pendingTargetReady === null
          && this.loadedThroughMs >= requiredBoundary
        );
      if (!targetReady) return false;
      const target = this.pendingSeekMs;
      this.pendingSeekMs = null;
      this.pendingPlayerTargetMs = null;
      this.pendingTargetReady = null;
      this.lastCompletedSeekMs = target;
      this.requestedThroughMs = null;
      this._setTimes(target, requiredBoundary);
      this._clearBoundaryWait();
      this._setBuffering(false);
      this.player.goto(this.toPlayerTime(requiredBoundary), this.playIntent);
      return true;
    }

    start() {
      if (!this.hasMore || this.destroyed || this.remoteSeekPending) return Promise.resolve();
      if (!this.pumpPromise) this.fetchAtLeastOne = true;
      return this._ensurePump();
    }

    play(timeMs) {
      if (this.destroyed) return;
      if (timeMs !== undefined) {
        const requestedTime = Math.max(0, finiteNumber(timeMs, this.currentTimeMs));
        this._setTimes(requestedTime, Math.min(requestedTime, this.fullDurationMs));
      }
      this.exhaustedNotified = false;
      this._setPlayIntent(true);

      if (this.remoteSeekPending) {
        if (!this.error) this._setBuffering(true);
        return;
      }

      if (this.pendingSeekMs !== null) {
        if (this.error) return;
        this._setBuffering(true);
        if (!this.pumpPromise) this.fetchAtLeastOne = true;
        this._ensurePump();
        return;
      }

      if (this.waitingAtBoundary) {
        if (this.error) return;
        this._settleBoundaryWait();
        if (!this.waitingAtBoundary) return;
        this._setBuffering(true);
        if (!this.pumpPromise && this.hasMore) this.fetchAtLeastOne = true;
        this._ensurePump();
        return;
      }

      this.player.goto(this.toPlayerTime(this.playerTimeMs), true);
    }

    pause() {
      if (this.destroyed) return;
      this._setPlayIntent(false);
      this._setBuffering(false);
      if (typeof this.player.pause === "function") this.player.pause();
    }

    observeTime(timeMs) {
      if (this.destroyed || this.remoteSeekPending) return;
      this.playerTimeMs = this.toRecordingTime(timeMs);
      if (!this.preserveDisplayTime) this.currentTimeMs = this.playerTimeMs;
      if (!this.hasMore || this.error) return;
      if (this.loadedThroughMs - this.playerTimeMs <= this.prefetchThresholdMs) {
        if (!this.pumpPromise) this.fetchAtLeastOne = true;
        this._ensurePump();
      }
    }

    observePlayerState(state) {
      if (this.destroyed || this.remoteSeekPending) return;
      this.actualPlayerState = String(state || "paused");
      if (this.actualPlayerState === "playing") {
        this._setBuffering(false);
      }
    }

    finish() {
      if (this.destroyed || this.remoteSeekPending) return;
      this.actualPlayerState = "paused";
      if (this.hasMore || this.pumpPromise) {
        if (!this.waitingAtBoundary) {
          this.waitingAtBoundary = true;
          this.boundaryLoadedThroughMs = this.loadedThroughMs;
          this.boundaryReceivedEvents = false;
        }
        if (this.playIntent && !this.error) this._setBuffering(true);
        if (this.error) return;
        if (!this.pumpPromise) this.fetchAtLeastOne = this.hasMore;
        this._ensurePump();
        return;
      }
      this._notifyTrueEnd();
    }

    async seek(timeMs) {
      if (this.destroyed) return 0;
      const seekGeneration = ++this.seekGeneration;
      const previousTimeMs = this.currentTimeMs;
      const previousPlayerTimeMs = this.playerTimeMs;
      const target = Math.max(0, finiteNumber(timeMs));
      this._abortSeekRequest();
      this.exhaustedNotified = false;
      this._clearBoundaryWait();
      const requiredBoundary = Math.min(target, this.fullDurationMs);

      if (this._isLoadedInCurrentSegment(requiredBoundary)) {
        this.remoteSeekPending = false;
        this.pendingSeekMs = null;
        this.pendingPlayerTargetMs = null;
        this.pendingTargetReady = null;
        this.requestedThroughMs = null;
        this.lastCompletedSeekMs = null;
        this._setTimes(target, requiredBoundary);
        this._setBuffering(false);
        this.player.goto(this.toPlayerTime(requiredBoundary), this.playIntent);
        return target;
      }

      if (this.fetchSeekBootstrap && this.createPlayer && this.seekCursor) {
        return this._seekFromSnapshot({
          target,
          previousTimeMs,
          previousPlayerTimeMs,
          seekGeneration
        });
      }

      this.pendingSeekMs = target;
      this.pendingPlayerTargetMs = requiredBoundary;
      this.pendingTargetReady = null;
      this.requestedThroughMs = requiredBoundary;
      if (this.error) return previousTimeMs;

      this._setTimes(target, requiredBoundary);
      this._setBuffering(true);
      if (typeof this.player.pause === "function") this.player.pause();
      await this._ensurePump();

      if (this.destroyed || seekGeneration !== this.seekGeneration) {
        return this.currentTimeMs;
      }
      if (this.error) {
        this._setTimes(previousTimeMs, previousPlayerTimeMs);
        return this.currentTimeMs;
      }
      if (this.lastCompletedSeekMs === target) {
        this.lastCompletedSeekMs = null;
        return this.currentTimeMs;
      }
      if (this._completePendingSeekIfReady()) return target;
      this.pendingSeekMs = null;
      this.pendingPlayerTargetMs = null;
      this.pendingTargetReady = null;
      this.requestedThroughMs = null;
      this._setBuffering(false);
      this.player.goto(this.toPlayerTime(requiredBoundary), this.playIntent);
      return target;
    }

    _abortSeekRequest() {
      if (!this.seekAbortController) return;
      try { this.seekAbortController.abort(); } catch (_) {}
      this.seekAbortController = null;
    }

    _cancelChunkPump() {
      this.generation += 1;
      this.fetchAtLeastOne = false;
      this.requestedThroughMs = null;
      this.pendingSeekMs = null;
      this.pendingPlayerTargetMs = null;
      this.pendingTargetReady = null;
      if (this.abortController) {
        try { this.abortController.abort(); } catch (_) {}
        this.abortController = null;
      }
      // The stale pump's identity-checked finally handler must not clear a
      // newer segment's pump after a player replacement.
      this.pumpPromise = null;
    }

    async _seekFromSnapshot({
      target,
      previousTimeMs,
      previousPlayerTimeMs,
      seekGeneration
    }) {
      this._cancelChunkPump();
      this.error = null;
      this.failedSeekTargetMs = null;
      this.remoteSeekPending = true;
      this.pendingSeekMs = target;
      this.pendingPlayerTargetMs = null;
      this.pendingTargetReady = null;
      this.currentTimeMs = target;
      this.preserveDisplayTime = false;
      this.actualPlayerState = "paused";
      this._setBuffering(true);
      if (typeof this.player.pause === "function") this.player.pause();

      const abortController = this.createAbortController();
      this.seekAbortController = abortController;
      let request;
      try {
        request = Promise.resolve(this.fetchSeekBootstrap(
          target,
          this.seekCursor,
          abortController.signal
        ));
      } catch (error) {
        request = Promise.reject(error);
      }
      this.seekPromise = request;

      let bootstrap;
      try {
        bootstrap = await request;
      } catch (error) {
        if (
          this.destroyed
          || seekGeneration !== this.seekGeneration
          || error?.name === "AbortError"
        ) {
          return this.currentTimeMs;
        }
        this.error = error;
        this.failedSeekTargetMs = target;
        this.remoteSeekPending = false;
        this.pendingSeekMs = null;
        this.pendingPlayerTargetMs = null;
        this.pendingTargetReady = null;
        this._setTimes(previousTimeMs, previousPlayerTimeMs);
        this._setBuffering(false);
        this.onError(error);
        return previousTimeMs;
      } finally {
        if (this.seekAbortController === abortController) {
          this.seekAbortController = null;
        }
        if (this.seekPromise === request) this.seekPromise = null;
      }

      if (this.destroyed || seekGeneration !== this.seekGeneration) {
        return this.currentTimeMs;
      }
      if (
        !bootstrap
        || Number(bootstrap.protocol_version) !== 1
        || bootstrap.response_kind !== "seek"
        || !Array.isArray(bootstrap.events)
        || bootstrap.events.length < 2
      ) {
        const error = new Error("Unsupported replay seek response");
        error.code = "unsupported_seek";
        this.error = error;
        this.failedSeekTargetMs = target;
        this.remoteSeekPending = false;
        this.pendingSeekMs = null;
        this.pendingPlayerTargetMs = null;
        this.pendingTargetReady = null;
        this._setTimes(previousTimeMs, previousPlayerTimeMs);
        this._setBuffering(false);
        this.onError(error);
        return previousTimeMs;
      }

      const resolvedTarget = Math.max(0, finiteNumber(bootstrap.seek_target_ms, target));
      const segmentStartMs = Math.max(
        0,
        finiteNumber(bootstrap.segment_start_ms, bootstrap.events[0]?.timestamp)
      );
      const loadedThroughMs = Math.max(
        segmentStartMs,
        finiteNumber(bootstrap.loaded_through_ms, segmentStartMs)
      );
      const seekableFromMs = Math.max(
        segmentStartMs,
        finiteNumber(bootstrap.seekable_from_ms, segmentStartMs)
      );
      if (seekableFromMs > resolvedTarget || loadedThroughMs < segmentStartMs) {
        const error = new Error("Invalid replay seek boundaries");
        error.code = "invalid_seek_boundaries";
        this.error = error;
        this.failedSeekTargetMs = target;
        this.remoteSeekPending = false;
        this.pendingSeekMs = null;
        this.pendingPlayerTargetMs = null;
        this.pendingTargetReady = null;
        this._setTimes(previousTimeMs, previousPlayerTimeMs);
        this._setBuffering(false);
        this.onError(error);
        return previousTimeMs;
      }

      let nextPlayer;
      try {
        nextPlayer = this.createPlayer(bootstrap.events, bootstrap);
        if (!nextPlayer || typeof nextPlayer.goto !== "function") {
          throw new TypeError("createPlayer must return an rrweb-player instance");
        }
      } catch (error) {
        this.error = error;
        this.failedSeekTargetMs = target;
        this.remoteSeekPending = false;
        this.pendingSeekMs = null;
        this.pendingPlayerTargetMs = null;
        this.pendingTargetReady = null;
        this._setTimes(previousTimeMs, previousPlayerTimeMs);
        this._setBuffering(false);
        this.onError(error);
        return previousTimeMs;
      }

      if (this.destroyed || seekGeneration !== this.seekGeneration) {
        destroyRrwebPlayer(nextPlayer);
        return this.currentTimeMs;
      }

      const previousPlayer = this.player;
      destroyRrwebPlayer(previousPlayer);
      this.player = nextPlayer;
      this.segmentStartMs = segmentStartMs;
      this.seekableFromMs = seekableFromMs;
      this.cursor = bootstrap.next_cursor || null;
      this.hasMore = Boolean(bootstrap.has_more && this.cursor);
      this.loadedThroughMs = loadedThroughMs;
      this.seekCursor = bootstrap.seek_cursor || this.seekCursor;
      this._setTimes(target, resolvedTarget);
      this.error = null;
      this.failedSeekTargetMs = null;
      this.exhaustedNotified = false;
      this.lastCompletedSeekMs = null;
      this._clearBoundaryWait();
      this.onPlayerChange(nextPlayer, previousPlayer, bootstrap);

      const explicitTargetReady = typeof bootstrap.target_ready === "boolean"
        ? bootstrap.target_ready
        : null;
      const targetReady = !this.hasMore
        || explicitTargetReady === true
        || (explicitTargetReady === null && loadedThroughMs >= resolvedTarget);
      this.remoteSeekPending = false;
      if (targetReady) {
        this.pendingSeekMs = null;
        this.pendingPlayerTargetMs = null;
        this.pendingTargetReady = null;
        this.requestedThroughMs = null;
        this._setBuffering(false);
        nextPlayer.goto(this.toPlayerTime(resolvedTarget), this.playIntent);
      } else {
        this.pendingSeekMs = target;
        this.pendingPlayerTargetMs = resolvedTarget;
        this.pendingTargetReady = explicitTargetReady;
        this.requestedThroughMs = resolvedTarget;
        this._setBuffering(true);
        // Render the selected snapshot and every event already present in the
        // seek bootstrap while the short remainder up to the target loads.
        nextPlayer.goto(this.toPlayerTime(resolvedTarget), false);
      }

      if (this.hasMore) {
        this.fetchAtLeastOne = true;
        const pump = this._ensurePump();
        // A ready seek bootstrap is enough to render and resume. Its next
        // chunk is deliberately prefetched without delaying seek completion.
        if (!targetReady) await pump;
      } else if (!targetReady) {
        this._completePendingSeekIfReady();
      }
      return this.currentTimeMs;
    }

    retry() {
      if (this.destroyed) return Promise.resolve();
      if (this.failedSeekTargetMs !== null) {
        const target = this.failedSeekTargetMs;
        this.error = null;
        return this.seek(target);
      }
      if (!this.hasMore) return Promise.resolve();
      this.error = null;
      if (!this.pumpPromise) this.fetchAtLeastOne = true;
      this._setBuffering(true);
      return this._ensurePump();
    }

    _shouldFetch() {
      if (
        this.destroyed
        || this.remoteSeekPending
        || this.error
        || !this.hasMore
        || !this.cursor
      ) return false;
      if (this.fetchAtLeastOne) return true;
      if (this.pendingSeekMs !== null && this.pendingTargetReady === false) {
        return true;
      }
      if (
        this.requestedThroughMs !== null
        && this.loadedThroughMs < this.requestedThroughMs
      ) return true;
      return this.playIntent
        && this.loadedThroughMs - this.playerTimeMs <= this.prefetchThresholdMs;
    }

    _ensurePump() {
      if (this.destroyed) return Promise.resolve();
      if (!this.pumpPromise) {
        const generation = this.generation;
        let trackedPromise;
        trackedPromise = this._pump(generation).finally(() => {
          if (this.pumpPromise !== trackedPromise) return;
          this.pumpPromise = null;
          if (generation !== this.generation) return;
          if (!this.error) {
            this._settleBoundaryWait();
            if (!this.waitingAtBoundary && this.pendingSeekMs === null) {
              this._setBuffering(false);
            }
          }
        });
        this.pumpPromise = trackedPromise;
      }
      return this.pumpPromise;
    }

    async _pump(generation) {
      while (this._shouldFetch() && generation === this.generation) {
        this.fetchAtLeastOne = false;
        const requestedCursor = this.cursor;
        const abortController = this.createAbortController();
        this.abortController = abortController;
        let chunk;
        try {
          chunk = await this.fetchChunk(requestedCursor, abortController.signal);
        } catch (error) {
          if (this.destroyed || generation !== this.generation || error?.name === "AbortError") {
            return;
          }
          this.error = error;
          this._setBuffering(false);
          this.onError(error);
          return;
        } finally {
          if (this.abortController === abortController) this.abortController = null;
        }

        if (this.destroyed || generation !== this.generation) return;
        if (!chunk || Number(chunk.protocol_version) !== 1) {
          const error = new Error("Unsupported replay stream response");
          error.code = "unsupported_stream";
          this.error = error;
          this._setBuffering(false);
          this.onError(error);
          return;
        }

        this.onChunkMetadata(chunk);

        const appended = await appendEventsInBatches({
          player: this.player,
          events: chunk.events,
          batchSize: this.appendBatchSize,
          yieldControl: this.yieldControl,
          isCancelled: () => this.destroyed || generation !== this.generation
        });
        if (!appended || this.destroyed || generation !== this.generation) return;

        if (this.waitingAtBoundary && Array.isArray(chunk.events) && chunk.events.length) {
          this.boundaryReceivedEvents = true;
        }

        this.cursor = chunk.next_cursor || null;
        this.hasMore = Boolean(chunk.has_more && this.cursor);
        this.loadedThroughMs = Math.max(
          this.loadedThroughMs,
          finiteNumber(chunk.loaded_through_ms, this.loadedThroughMs)
        );
        this.onChunk(chunk);

        if (this.pendingSeekMs !== null) {
          if (typeof chunk.target_ready === "boolean") {
            this.pendingTargetReady = chunk.target_ready;
          } else if (
            this.pendingTargetReady === false
            && this.pendingPlayerTargetMs !== null
            && this.loadedThroughMs > this.pendingPlayerTargetMs
          ) {
            // A rolling-deploy response may not know the cursor-boundary
            // signal. Preserve an earlier explicit false until the legacy
            // timestamp boundary has been passed, not merely reached.
            this.pendingTargetReady = true;
          }
        }

        if (
          this.requestedThroughMs !== null
          && (
            !this.hasMore
            || this.pendingTargetReady === true
            || (
              this.pendingTargetReady === null
              && this.loadedThroughMs >= this.requestedThroughMs
            )
          )
        ) {
          this.requestedThroughMs = null;
        }

        const completedPendingSeek = this._completePendingSeekIfReady();
        if (!completedPendingSeek) this._settleBoundaryWait();
      }
    }

    destroy() {
      if (this.destroyed) return;
      this.destroyed = true;
      this.seekGeneration += 1;
      this.generation += 1;
      this.remoteSeekPending = false;
      this.fetchAtLeastOne = false;
      this.requestedThroughMs = null;
      this.pendingSeekMs = null;
      this.pendingPlayerTargetMs = null;
      this.pendingTargetReady = null;
      this._clearBoundaryWait();
      this._setBuffering(false);
      if (this.abortController) {
        try { this.abortController.abort(); } catch (_) {}
        this.abortController = null;
      }
      this._abortSeekRequest();
      if (this.destroyPlayer) destroyRrwebPlayer(this.player);
    }
  }

  function createController(options) {
    return new ReplayStreamController(options);
  }

  return {
    BOUNDARY_TOLERANCE_MS,
    ReplayStreamController,
    appendEventsInBatches,
    createController,
    destroyRrwebPlayer
  };
});
