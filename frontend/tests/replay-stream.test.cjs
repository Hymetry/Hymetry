const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const {
  appendEventsInBatches,
  createController
} = require("../../static/js/tracker/replay-stream.js");

const installedPlayerBundle = fs.readFileSync(
  path.join(__dirname, "../../static/js/tracker/lib-player.js"),
  "utf8"
);
assert.match(installedPlayerBundle, /get addEvent\(\)/);
assert.match(installedPlayerBundle, /get getReplayer\(\)/);
assert.match(installedPlayerBundle, /get goto\(\)/);
assert.match(installedPlayerBundle, /\$destroy\(\)/);

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function fakePlayer() {
  const replayer = {
    destroyCalls: 0,
    destroy() { this.destroyCalls += 1; }
  };
  return {
    added: [],
    gotos: [],
    pauseCalls: 0,
    destroyCalls: 0,
    replayer,
    addEvent(event) { this.added.push(event); },
    goto(offset, playing) { this.gotos.push([offset, playing]); },
    pause() { this.pauseCalls += 1; },
    getReplayer() { return replayer; },
    $destroy() { this.destroyCalls += 1; }
  };
}

async function testBatchAppendOrder() {
  const player = fakePlayer();
  const events = Array.from({ length: 501 }, (_, index) => ({ index, timestamp: index }));
  let yields = 0;

  const appended = await appendEventsInBatches({
    player,
    events,
    batchSize: 250,
    yieldControl: async () => { yields += 1; }
  });

  assert.equal(appended, true);
  assert.deepEqual(player.added.map((event) => event.index), events.map((event) => event.index));
  assert.equal(yields, 3);
}

async function testImmediatePlaybackAndSingleFlightBackgroundFetch() {
  const player = fakePlayer();
  const pending = deferred();
  let fetchCalls = 0;
  const controller = createController({
    player,
    initialCursor: "cursor-1",
    initialHasMore: true,
    initialLoadedThroughMs: 45_000,
    fullDurationMs: 180_000,
    prefetchThresholdMs: 30_000,
    fetchChunk: async () => {
      fetchCalls += 1;
      return pending.promise;
    },
    yieldControl: async () => {}
  });

  const background = controller.start();
  controller.play(0);
  controller.observeTime(20_000);
  controller.observeTime(20_001);

  assert.deepEqual(player.gotos, [[0, true]]);
  assert.equal(fetchCalls, 1);
  pending.resolve({
    protocol_version: 1,
    events: [{ timestamp: 60_000 }, { timestamp: 105_000 }],
    tab_switches: [],
    loaded_through_ms: 105_000,
    has_more: true,
    next_cursor: "cursor-2"
  });
  await background;

  assert.deepEqual(player.added.map((event) => event.timestamp), [60_000, 105_000]);
  assert.equal(controller.state.loadedThroughMs, 105_000);
  assert.equal(controller.state.cursor, "cursor-2");
  assert.equal(controller.state.playIntent, true);
}

async function testBoundaryBuffersAndResumesAtSavedOffset() {
  const player = fakePlayer();
  const pending = deferred();
  const buffering = [];
  const controller = createController({
    player,
    initialCursor: "cursor-1",
    initialHasMore: true,
    initialLoadedThroughMs: 10_000,
    fullDurationMs: 30_000,
    prefetchThresholdMs: 1_000,
    fetchChunk: async () => pending.promise,
    yieldControl: async () => {},
    onBufferingChange: (value) => buffering.push(value)
  });

  const background = controller.start();
  controller.play(9_000);
  controller.observeTime(10_000);
  controller.finish();
  assert.equal(controller.state.buffering, true);

  pending.resolve({
    protocol_version: 1,
    events: [{ timestamp: 20_000 }, { timestamp: 30_000 }],
    loaded_through_ms: 30_000,
    has_more: false,
    next_cursor: null
  });
  await background;

  assert.deepEqual(player.gotos, [[9_000, true], [10_000, true]]);
  assert.deepEqual(buffering, [true, false]);
  assert.equal(controller.state.playIntent, true);
  controller.finish();
  assert.equal(controller.state.playIntent, false);
}

async function testDeliberatePauseDuringBufferingNeverAutoResumes() {
  const player = fakePlayer();
  const pending = deferred();
  const controller = createController({
    player,
    initialCursor: "cursor-1",
    initialHasMore: true,
    initialLoadedThroughMs: 10_000,
    fullDurationMs: 20_000,
    fetchChunk: async () => pending.promise,
    yieldControl: async () => {}
  });

  controller.play(10_000);
  controller.finish();
  controller.pause();
  pending.resolve({
    protocol_version: 1,
    events: [{ timestamp: 20_000 }],
    loaded_through_ms: 20_000,
    has_more: false,
    next_cursor: null
  });
  await new Promise((resolve) => setImmediate(resolve));

  assert.deepEqual(player.gotos, [[10_000, true]]);
  assert.equal(controller.state.playIntent, false);
  assert.equal(controller.state.buffering, false);
  assert.equal(player.pauseCalls >= 1, true);
}

async function testTinyBootstrapAndNearBoundaryPauseStillPlayImmediately() {
  const tinyPlayer = fakePlayer();
  const tinyController = createController({
    player: tinyPlayer,
    initialCursor: "cursor-1",
    initialHasMore: true,
    initialLoadedThroughMs: 50,
    fullDurationMs: 10_000,
    fetchChunk: async () => new Promise(() => {})
  });

  tinyController.play(0);
  assert.deepEqual(tinyPlayer.gotos, [[0, true]]);
  assert.equal(tinyController.state.buffering, false);
  tinyController.destroy();

  const nearBoundaryPlayer = fakePlayer();
  const nearBoundaryController = createController({
    player: nearBoundaryPlayer,
    initialCursor: "cursor-1",
    initialHasMore: true,
    initialLoadedThroughMs: 1_000,
    fullDurationMs: 10_000,
    fetchChunk: async () => new Promise(() => {})
  });

  nearBoundaryController.play(950);
  nearBoundaryController.pause();
  nearBoundaryController.play(950);
  assert.deepEqual(nearBoundaryPlayer.gotos, [[950, true], [950, true]]);
  assert.equal(nearBoundaryController.state.buffering, false);
  nearBoundaryController.destroy();
}

async function testPrefetchErrorWaitsForExplicitRetryAndClearsStatus() {
  const player = fakePlayer();
  const buffering = [];
  const errors = [];
  let fetchCalls = 0;
  const controller = createController({
    player,
    initialCursor: "cursor-1",
    initialHasMore: true,
    initialLoadedThroughMs: 10_000,
    fullDurationMs: 30_000,
    prefetchThresholdMs: 5_000,
    fetchChunk: async () => {
      fetchCalls += 1;
      if (fetchCalls === 1) throw new Error("network unavailable");
      return {
        protocol_version: 1,
        events: [{ timestamp: 20_000 }],
        loaded_through_ms: 20_000,
        has_more: true,
        next_cursor: "cursor-2"
      };
    },
    yieldControl: async () => {},
    onBufferingChange: (value) => buffering.push(value),
    onError: (error) => errors.push(error.message)
  });

  await controller.start();
  assert.equal(fetchCalls, 1);
  assert.deepEqual(errors, ["network unavailable"]);

  controller.observeTime(9_500);
  controller.observePlayerState("paused");
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(fetchCalls, 1);
  assert.equal(controller.state.buffering, false);

  // A background error must not prevent seeks within already appended data.
  assert.equal(await controller.seek(1_000), 1_000);
  assert.deepEqual(player.gotos, [[1_000, false]]);

  await controller.retry();
  assert.equal(fetchCalls, 2);
  assert.equal(controller.state.error, null);
  assert.deepEqual(buffering, [true, false]);
}

async function testActivePrefetchDoesNotRestartAStillPlayingReplayer() {
  const player = fakePlayer();
  const pending = deferred();
  const controller = createController({
    player,
    initialCursor: "cursor-1",
    initialHasMore: true,
    initialLoadedThroughMs: 10_000,
    fullDurationMs: 30_000,
    prefetchThresholdMs: 1_000,
    fetchChunk: async () => pending.promise,
    yieldControl: async () => {}
  });

  const background = controller.start();
  controller.play(0);
  controller.observePlayerState("playing");
  controller.observeTime(9_950);
  pending.resolve({
    protocol_version: 1,
    events: [{ timestamp: 20_000 }],
    loaded_through_ms: 20_000,
    has_more: true,
    next_cursor: "cursor-2"
  });
  await background;

  assert.deepEqual(player.gotos, [[0, true]]);
  assert.equal(controller.state.buffering, false);
}

async function testExhaustionResetsForASecondPlayback() {
  const player = fakePlayer();
  let exhausted = 0;
  const controller = createController({
    player,
    initialHasMore: false,
    initialLoadedThroughMs: 10_000,
    fullDurationMs: 10_000,
    fetchChunk: async () => {
      throw new Error("should not fetch");
    },
    onExhausted: () => { exhausted += 1; }
  });

  controller.play(0);
  controller.finish();
  assert.equal(controller.state.playIntent, false);
  controller.play(0);
  controller.finish();

  assert.equal(controller.state.playIntent, false);
  assert.equal(exhausted, 2);
}

async function testForwardSeekConsumesMultipleCursorsAndKeepsPauseIntent() {
  const player = fakePlayer();
  const chunks = [
    {
      protocol_version: 1,
      events: [{ timestamp: 20_000 }],
      loaded_through_ms: 20_000,
      has_more: true,
      next_cursor: "cursor-2"
    },
    {
      protocol_version: 1,
      events: [{ timestamp: 50_000 }],
      loaded_through_ms: 50_000,
      has_more: false,
      next_cursor: null
    }
  ];
  const seenCursors = [];
  const controller = createController({
    player,
    initialCursor: "cursor-1",
    initialHasMore: true,
    initialLoadedThroughMs: 10_000,
    fullDurationMs: 50_000,
    fetchChunk: async (cursor) => {
      seenCursors.push(cursor);
      return chunks.shift();
    },
    yieldControl: async () => {}
  });

  const sought = await controller.seek(40_000);

  assert.equal(sought, 40_000);
  assert.deepEqual(seenCursors, ["cursor-1", "cursor-2"]);
  assert.deepEqual(player.added.map((event) => event.timestamp), [20_000, 50_000]);
  assert.deepEqual(player.gotos, [[40_000, false]]);
  assert.equal(controller.state.playIntent, false);
}

async function testLatestForwardSeekWinsWhileChunkIsPending() {
  const player = fakePlayer();
  const pending = deferred();
  const controller = createController({
    player,
    initialCursor: "cursor-1",
    initialHasMore: true,
    initialLoadedThroughMs: 10_000,
    fullDurationMs: 50_000,
    fetchChunk: async () => pending.promise,
    yieldControl: async () => {}
  });

  const firstSeek = controller.seek(40_000);
  const secondSeek = controller.seek(20_000);
  pending.resolve({
    protocol_version: 1,
    events: [{ timestamp: 50_000 }],
    loaded_through_ms: 50_000,
    has_more: false,
    next_cursor: null
  });
  await Promise.all([firstSeek, secondSeek]);

  assert.deepEqual(player.gotos, [[20_000, false]]);
}

async function testNewLocalSeekCancelsAnOlderDownloadHorizon() {
  const player = fakePlayer();
  const firstChunk = deferred();
  let fetchCalls = 0;
  const controller = createController({
    player,
    initialCursor: "cursor-1",
    initialHasMore: true,
    initialLoadedThroughMs: 10_000,
    fullDurationMs: 100_000,
    fetchChunk: async () => {
      fetchCalls += 1;
      if (fetchCalls > 1) throw new Error("abandoned seek fetched too far");
      return firstChunk.promise;
    },
    yieldControl: async () => {}
  });

  const oldSeek = controller.seek(90_000);
  const newSeek = controller.seek(5_000);
  firstChunk.resolve({
    protocol_version: 1,
    events: [{ timestamp: 20_000 }],
    loaded_through_ms: 20_000,
    has_more: true,
    next_cursor: "cursor-2"
  });

  assert.deepEqual(await Promise.all([oldSeek, newSeek]), [5_000, 5_000]);
  assert.equal(fetchCalls, 1);
  assert.deepEqual(player.gotos, [[5_000, false]]);
}

async function testChunkMetadataArrivesBeforeItsReplayEvents() {
  const player = fakePlayer();
  const order = [];
  player.addEvent = (event) => {
    order.push(`event:${event.timestamp}`);
    player.added.push(event);
  };
  const controller = createController({
    player,
    initialCursor: "cursor-1",
    initialHasMore: true,
    initialLoadedThroughMs: 10_000,
    fetchChunk: async () => ({
      protocol_version: 1,
      events: [{ timestamp: 20_000 }],
      tab_switches: [{ timestamp: 20_000, to_tab: "tab-2" }],
      loaded_through_ms: 20_000,
      has_more: false,
      next_cursor: null
    }),
    yieldControl: async () => {},
    onChunkMetadata: () => order.push("metadata"),
    onChunk: () => order.push("complete")
  });

  await controller.start();
  assert.deepEqual(order, ["metadata", "event:20000", "complete"]);
}

async function testSegmentTimeMappingKeepsControllerTimesRecordingGlobal() {
  const player = fakePlayer();
  const controller = createController({
    player,
    segmentStartMs: 65_000,
    initialHasMore: false,
    initialLoadedThroughMs: 90_000,
    fullDurationMs: 100_000,
    fetchChunk: async () => {
      throw new Error("should not fetch");
    }
  });

  assert.equal(controller.toRecordingTime(5_000), 70_000);
  assert.equal(controller.toPlayerTime(70_000), 5_000);
  assert.equal(await controller.seek(70_000), 70_000);
  controller.play(71_000);
  controller.observeTime(7_000);

  assert.deepEqual(player.gotos, [[5_000, false], [6_000, true]]);
  assert.equal(controller.state.currentTimeMs, 72_000);
}

async function testRemoteSeekRebuildsFromSnapshotAndUsesLocalGoto() {
  const oldPlayer = fakePlayer();
  const newPlayer = fakePlayer();
  const seekCalls = [];
  const replacements = [];
  let chunkFetches = 0;
  const controller = createController({
    player: oldPlayer,
    initialCursor: "linear-cursor",
    initialHasMore: true,
    initialLoadedThroughMs: 45_000,
    fullDurationMs: 700_000,
    seekCursor: "stable-seek-cursor",
    fetchChunk: async () => {
      chunkFetches += 1;
      throw new Error("seek should not walk intermediate chunks");
    },
    fetchSeekBootstrap: async (target, seekCursor) => {
      seekCalls.push([target, seekCursor]);
      return {
        protocol_version: 1,
        response_kind: "seek",
        events: [
          { type: 2, timestamp: 625_000 },
          { type: 3, timestamp: 640_000 }
        ],
        segment_start_ms: 625_000,
        seek_target_ms: 630_000,
        target_ready: true,
        loaded_through_ms: 640_000,
        has_more: false,
        next_cursor: null,
        seek_cursor: "stable-seek-cursor"
      };
    },
    createPlayer: (events) => {
      assert.deepEqual(events.map((event) => event.timestamp), [625_000, 640_000]);
      return newPlayer;
    },
    onPlayerChange: (...args) => replacements.push(args)
  });

  controller.play(10_000);
  const resolved = await controller.seek(630_000);

  assert.equal(resolved, 630_000);
  assert.deepEqual(seekCalls, [[630_000, "stable-seek-cursor"]]);
  assert.equal(chunkFetches, 0);
  assert.equal(oldPlayer.replayer.destroyCalls, 1);
  assert.equal(oldPlayer.destroyCalls, 1);
  assert.equal(replacements.length, 1);
  assert.equal(replacements[0][0], newPlayer);
  assert.equal(replacements[0][1], oldPlayer);
  assert.deepEqual(newPlayer.gotos, [[5_000, true]]);
  assert.equal(controller.state.segmentStartMs, 625_000);
  assert.equal(controller.state.playIntent, true);
}

async function testPauseWhileRemoteSeekIsPendingPreventsAutoResume() {
  const oldPlayer = fakePlayer();
  const newPlayer = fakePlayer();
  const pending = deferred();
  const controller = createController({
    player: oldPlayer,
    initialCursor: "linear-cursor",
    initialHasMore: true,
    initialLoadedThroughMs: 45_000,
    fullDurationMs: 700_000,
    seekCursor: "stable-seek-cursor",
    fetchChunk: async () => new Promise(() => {}),
    fetchSeekBootstrap: async () => pending.promise,
    createPlayer: () => newPlayer
  });

  controller.play(10_000);
  const seek = controller.seek(630_000);
  controller.pause();
  pending.resolve({
    protocol_version: 1,
    response_kind: "seek",
    events: [
      { type: 2, timestamp: 625_000 },
      { type: 3, timestamp: 640_000 }
    ],
    segment_start_ms: 625_000,
    seek_target_ms: 630_000,
    target_ready: true,
    loaded_through_ms: 640_000,
    has_more: false,
    next_cursor: null
  });
  await seek;

  assert.deepEqual(newPlayer.gotos, [[5_000, false]]);
  assert.equal(controller.state.playIntent, false);
  assert.equal(controller.state.buffering, false);
}

async function testNotReadySeekBootstrapContinuesOnlyFromSnapshotCursor() {
  const oldPlayer = fakePlayer();
  const newPlayer = fakePlayer();
  const chunkCursors = [];
  const controller = createController({
    player: oldPlayer,
    initialCursor: "linear-cursor",
    initialHasMore: true,
    initialLoadedThroughMs: 45_000,
    fullDurationMs: 700_000,
    seekCursor: "stable-seek-cursor",
    fetchSeekBootstrap: async () => ({
      protocol_version: 1,
      response_kind: "seek",
      events: [
        { type: 2, timestamp: 600_000 },
        { type: 3, timestamp: 610_000 }
      ],
      segment_start_ms: 600_000,
      seek_target_ms: 630_000,
      target_ready: false,
      loaded_through_ms: 610_000,
      has_more: true,
      next_cursor: "snapshot-next-cursor"
    }),
    fetchChunk: async (cursor) => {
      chunkCursors.push(cursor);
      return {
        protocol_version: 1,
        events: [
          { type: 3, timestamp: 620_000 },
          { type: 3, timestamp: 635_000 }
        ],
        target_ready: true,
        loaded_through_ms: 635_000,
        has_more: false,
        next_cursor: null
      };
    },
    createPlayer: () => newPlayer,
    yieldControl: async () => {}
  });
  let simulatedBootstrapFinish = false;
  newPlayer.goto = (offset, playing) => {
    newPlayer.gotos.push([offset, playing]);
    if (!simulatedBootstrapFinish) {
      simulatedBootstrapFinish = true;
      controller.finish();
    }
  };

  assert.equal(await controller.seek(630_000), 630_000);
  assert.deepEqual(chunkCursors, ["snapshot-next-cursor"]);
  assert.deepEqual(newPlayer.added.map((event) => event.timestamp), [620_000, 635_000]);
  assert.deepEqual(newPlayer.gotos, [[30_000, false], [30_000, false]]);
  assert.equal(controller.state.waitingAtBoundary, false);
}

async function testRapidRemoteSeekAbortsStaleBootstrap() {
  const oldPlayer = fakePlayer();
  const latestPlayer = fakePlayer();
  const requestedTargets = [];
  let aborted = 0;
  const controller = createController({
    player: oldPlayer,
    initialCursor: "linear-cursor",
    initialHasMore: true,
    initialLoadedThroughMs: 45_000,
    fullDurationMs: 800_000,
    seekCursor: "stable-seek-cursor",
    fetchChunk: async () => new Promise(() => {}),
    fetchSeekBootstrap: async (target, _seekCursor, signal) => {
      requestedTargets.push(target);
      if (target === 600_000) {
        return new Promise((_resolve, reject) => {
          signal.addEventListener("abort", () => {
            aborted += 1;
            const error = new Error("aborted");
            error.name = "AbortError";
            reject(error);
          });
        });
      }
      return {
        protocol_version: 1,
        response_kind: "seek",
        events: [
          { type: 2, timestamp: 695_000 },
          { type: 3, timestamp: 710_000 }
        ],
        segment_start_ms: 695_000,
        seek_target_ms: 700_000,
        target_ready: true,
        loaded_through_ms: 710_000,
        has_more: false,
        next_cursor: null
      };
    },
    createPlayer: () => latestPlayer
  });

  const stale = controller.seek(600_000);
  const latest = controller.seek(700_000);
  assert.deepEqual(await Promise.all([stale, latest]), [700_000, 700_000]);

  assert.equal(aborted, 1);
  assert.deepEqual(requestedTargets, [600_000, 700_000]);
  assert.deepEqual(latestPlayer.gotos, [[5_000, false]]);
}

async function testBackendClampKeepsAnalyticalTimeButUsesTheLastReplayFrame() {
  const oldPlayer = fakePlayer();
  const newPlayer = fakePlayer();
  const requestedTargets = [];
  const controller = createController({
    player: oldPlayer,
    initialCursor: "linear-cursor",
    initialHasMore: true,
    initialLoadedThroughMs: 45_000,
    fullDurationMs: 700_000,
    seekCursor: "stable-seek-cursor",
    fetchChunk: async () => new Promise(() => {}),
    fetchSeekBootstrap: async (target) => {
      requestedTargets.push(target);
      return {
        protocol_version: 1,
        response_kind: "seek",
        events: [
          { type: 2, timestamp: 695_000 },
          { type: 3, timestamp: 700_000 }
        ],
        segment_start_ms: 695_000,
        seekable_from_ms: 695_000,
        requested_seek_ms: 720_000,
        seek_target_ms: 700_000,
        target_ready: true,
        loaded_through_ms: 700_000,
        has_more: false,
        next_cursor: null
      };
    },
    createPlayer: () => newPlayer
  });

  assert.equal(await controller.seek(720_000), 720_000);
  assert.deepEqual(requestedTargets, [720_000]);
  assert.deepEqual(newPlayer.gotos, [[5_000, false]]);
  assert.equal(controller.state.currentTimeMs, 720_000);
  assert.equal(controller.state.playerTimeMs, 700_000);

  controller.observeTime(5_000);
  assert.equal(controller.state.currentTimeMs, 720_000);
  controller.play();
  assert.deepEqual(newPlayer.gotos, [
    [5_000, false],
    [5_000, true]
  ]);
}

async function testNotReadyBackendClampUsesResolvedTargetAfterContinuation() {
  const oldPlayer = fakePlayer();
  const newPlayer = fakePlayer();
  const buffering = [];
  const controller = createController({
    player: oldPlayer,
    initialCursor: "linear-cursor",
    initialHasMore: true,
    initialLoadedThroughMs: 45_000,
    fullDurationMs: 700_000,
    seekCursor: "stable-seek-cursor",
    fetchSeekBootstrap: async () => ({
      protocol_version: 1,
      response_kind: "seek",
      events: [
        { type: 4, timestamp: 650_000 },
        { type: 2, timestamp: 680_000 }
      ],
      segment_start_ms: 650_000,
      seekable_from_ms: 680_000,
      requested_seek_ms: 720_000,
      seek_target_ms: 700_000,
      target_ready: false,
      loaded_through_ms: 680_000,
      has_more: true,
      next_cursor: "snapshot-next-cursor"
    }),
    fetchChunk: async () => ({
      protocol_version: 1,
      events: [{ type: 3, timestamp: 700_000 }],
      loaded_through_ms: 700_000,
      has_more: false,
      next_cursor: null
    }),
    createPlayer: () => newPlayer,
    yieldControl: async () => {},
    onBufferingChange: (value) => buffering.push(value)
  });

  assert.equal(await controller.seek(720_000), 720_000);
  assert.deepEqual(newPlayer.gotos, [
    [50_000, false],
    [50_000, false]
  ]);
  assert.equal(controller.state.currentTimeMs, 720_000);
  assert.equal(controller.state.playerTimeMs, 700_000);
  assert.equal(controller.state.buffering, false);
  assert.deepEqual(buffering, [true, false]);

  controller.observeTime(50_000);
  assert.equal(controller.state.currentTimeMs, 720_000);
  controller.play();
  assert.deepEqual(newPlayer.gotos.at(-1), [50_000, true]);
}

async function testPendingSeekConsumesEveryEventAtTheTargetTimestamp() {
  const oldPlayer = fakePlayer();
  const newPlayer = fakePlayer();
  const seenCursors = [];
  const buffering = [];
  const chunks = [
    {
      protocol_version: 1,
      events: [{ type: 3, timestamp: 70_000, marker: "target-second" }],
      target_ready: true,
      loaded_through_ms: 70_000,
      has_more: true,
      next_cursor: "background-cursor"
    }
  ];
  const controller = createController({
    player: oldPlayer,
    initialCursor: "linear-cursor",
    initialHasMore: true,
    initialLoadedThroughMs: 10_000,
    fullDurationMs: 120_000,
    seekCursor: "stable-seek-cursor",
    fetchSeekBootstrap: async () => ({
      protocol_version: 1,
      response_kind: "seek",
      events: [
        { type: 4, timestamp: 0 },
        { type: 2, timestamp: 65_000 },
        { type: 3, timestamp: 70_000, marker: "target-first" }
      ],
      segment_start_ms: 0,
      seekable_from_ms: 65_000,
      seek_target_ms: 70_000,
      target_ready: false,
      loaded_through_ms: 70_000,
      has_more: true,
      next_cursor: "cursor-at-target-timestamp"
    }),
    fetchChunk: async (cursor) => {
      seenCursors.push(cursor);
      return chunks.shift();
    },
    createPlayer: () => newPlayer,
    yieldControl: async () => {},
    onBufferingChange: (value) => buffering.push(value)
  });

  assert.equal(await controller.seek(70_000), 70_000);
  assert.deepEqual(seenCursors, ["cursor-at-target-timestamp"]);
  assert.deepEqual(
    newPlayer.added.map((event) => event.marker),
    ["target-second"]
  );
  assert.deepEqual(newPlayer.gotos, [
    [70_000, false],
    [70_000, false]
  ]);
  assert.equal(controller.state.cursor, "background-cursor");
  assert.equal(controller.state.hasMore, true);
  assert.equal(controller.state.buffering, false);
  assert.deepEqual(buffering, [true, false]);
}

async function testLegacyContinuationPassesAnExplicitlyIncompleteTarget() {
  const oldPlayer = fakePlayer();
  const newPlayer = fakePlayer();
  const seenCursors = [];
  const chunks = [
    {
      protocol_version: 1,
      events: [{ type: 3, timestamp: 70_000, marker: "target-second" }],
      loaded_through_ms: 70_000,
      has_more: true,
      next_cursor: "cursor-after-target-timestamp"
    },
    {
      protocol_version: 1,
      events: [{ type: 3, timestamp: 90_000, marker: "after-target" }],
      loaded_through_ms: 90_000,
      has_more: true,
      next_cursor: "background-cursor"
    }
  ];
  const controller = createController({
    player: oldPlayer,
    initialCursor: "linear-cursor",
    initialHasMore: true,
    initialLoadedThroughMs: 10_000,
    fullDurationMs: 120_000,
    seekCursor: "stable-seek-cursor",
    fetchSeekBootstrap: async () => ({
      protocol_version: 1,
      response_kind: "seek",
      events: [
        { type: 4, timestamp: 0 },
        { type: 2, timestamp: 65_000 },
        { type: 3, timestamp: 70_000, marker: "target-first" }
      ],
      segment_start_ms: 0,
      seekable_from_ms: 65_000,
      seek_target_ms: 70_000,
      target_ready: false,
      loaded_through_ms: 70_000,
      has_more: true,
      next_cursor: "cursor-at-target-timestamp"
    }),
    fetchChunk: async (cursor) => {
      seenCursors.push(cursor);
      return chunks.shift();
    },
    createPlayer: () => newPlayer,
    yieldControl: async () => {}
  });

  assert.equal(await controller.seek(70_000), 70_000);
  assert.deepEqual(seenCursors, [
    "cursor-at-target-timestamp",
    "cursor-after-target-timestamp"
  ]);
  assert.deepEqual(
    newPlayer.added.map((event) => event.marker),
    ["target-second", "after-target"]
  );
  assert.equal(controller.state.cursor, "background-cursor");
  assert.equal(controller.state.buffering, false);
}

async function testLoadedAnalyticalOverrunReusesTheLastReplayFrame() {
  const player = fakePlayer();
  const controller = createController({
    player,
    initialHasMore: false,
    initialLoadedThroughMs: 700_000,
    fullDurationMs: 700_000,
    fetchChunk: async () => {
      throw new Error("should not fetch");
    }
  });

  assert.equal(await controller.seek(720_000), 720_000);
  assert.deepEqual(player.gotos, [[700_000, false]]);
  assert.equal(controller.state.currentTimeMs, 720_000);
  assert.equal(controller.state.playerTimeMs, 700_000);

  controller.observeTime(700_000);
  assert.equal(controller.state.currentTimeMs, 720_000);
  controller.play();
  assert.deepEqual(player.gotos.at(-1), [700_000, true]);
}

async function testSeekableFromIsIndependentOfThePlayerSegmentOrigin() {
  const oldPlayer = fakePlayer();
  const newPlayer = fakePlayer();
  let seekFetches = 0;
  const controller = createController({
    player: oldPlayer,
    segmentStartMs: 0,
    seekableFromMs: 100_000,
    initialCursor: "linear-cursor",
    initialHasMore: true,
    initialLoadedThroughMs: 200_000,
    fullDurationMs: 300_000,
    seekCursor: "stable-seek-cursor",
    fetchChunk: async () => new Promise(() => {}),
    fetchSeekBootstrap: async () => {
      seekFetches += 1;
      return {
        protocol_version: 1,
        response_kind: "seek",
        events: [
          { type: 4, timestamp: 0 },
          { type: 2, timestamp: 40_000 }
        ],
        segment_start_ms: 0,
        seekable_from_ms: 40_000,
        seek_target_ms: 50_000,
        target_ready: true,
        loaded_through_ms: 50_000,
        has_more: false,
        next_cursor: null
      };
    },
    createPlayer: () => newPlayer
  });

  assert.equal(await controller.seek(50_000), 50_000);
  assert.equal(seekFetches, 1);
  assert.equal(controller.state.segmentStartMs, 0);
  assert.equal(controller.state.seekableFromMs, 40_000);
  assert.deepEqual(newPlayer.gotos, [[50_000, false]]);
}

async function testRemoteSeekRejectsANonSeekV1Response() {
  const oldPlayer = fakePlayer();
  const errors = [];
  let createCalls = 0;
  const controller = createController({
    player: oldPlayer,
    initialCursor: "linear-cursor",
    initialHasMore: true,
    initialLoadedThroughMs: 45_000,
    fullDurationMs: 300_000,
    seekCursor: "stable-seek-cursor",
    fetchChunk: async () => new Promise(() => {}),
    fetchSeekBootstrap: async () => ({
      protocol_version: 1,
      events: [
        { type: 4, timestamp: 0 },
        { type: 2, timestamp: 100_000 }
      ],
      segment_start_ms: 0,
      seek_target_ms: 100_000,
      target_ready: true,
      loaded_through_ms: 100_000,
      has_more: false,
      next_cursor: null
    }),
    createPlayer: () => {
      createCalls += 1;
      return fakePlayer();
    },
    onError: (error) => errors.push(error.code)
  });

  assert.equal(await controller.seek(100_000), 0);
  assert.deepEqual(errors, ["unsupported_seek"]);
  assert.equal(createCalls, 0);
  assert.equal(oldPlayer.destroyCalls, 0);
}

async function testDestroyAbortsAPendingRemoteSeek() {
  const player = fakePlayer();
  let aborted = 0;
  const controller = createController({
    player,
    initialCursor: "linear-cursor",
    initialHasMore: true,
    initialLoadedThroughMs: 45_000,
    fullDurationMs: 300_000,
    seekCursor: "stable-seek-cursor",
    fetchChunk: async () => new Promise(() => {}),
    fetchSeekBootstrap: async (_target, _seekCursor, signal) => (
      new Promise((_resolve, reject) => {
        signal.addEventListener("abort", () => {
          aborted += 1;
          const error = new Error("aborted");
          error.name = "AbortError";
          reject(error);
        });
      })
    ),
    createPlayer: () => fakePlayer()
  });

  const seek = controller.seek(100_000);
  controller.destroy();
  await seek;

  assert.equal(aborted, 1);
  assert.equal(player.destroyCalls, 1);
  assert.equal(controller.state.destroyed, true);
}

async function testDestroyAbortsAndDestroysPlayerOnce() {
  const player = fakePlayer();
  const pending = deferred();
  const aborts = [];
  const controller = createController({
    player,
    initialCursor: "cursor-1",
    initialHasMore: true,
    initialLoadedThroughMs: 10_000,
    fetchChunk: async () => pending.promise,
    createAbortController: () => ({
      signal: {},
      abort() { aborts.push(true); }
    })
  });

  controller.start();
  controller.destroy();
  controller.destroy();
  pending.resolve({
    protocol_version: 1,
    events: [{ timestamp: 20_000 }],
    loaded_through_ms: 20_000,
    has_more: false,
    next_cursor: null
  });
  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(aborts.length, 1);
  assert.equal(player.replayer.destroyCalls, 1);
  assert.equal(player.destroyCalls, 1);
  assert.deepEqual(player.added, []);
}

(async () => {
  await testBatchAppendOrder();
  await testImmediatePlaybackAndSingleFlightBackgroundFetch();
  await testBoundaryBuffersAndResumesAtSavedOffset();
  await testDeliberatePauseDuringBufferingNeverAutoResumes();
  await testTinyBootstrapAndNearBoundaryPauseStillPlayImmediately();
  await testPrefetchErrorWaitsForExplicitRetryAndClearsStatus();
  await testActivePrefetchDoesNotRestartAStillPlayingReplayer();
  await testExhaustionResetsForASecondPlayback();
  await testForwardSeekConsumesMultipleCursorsAndKeepsPauseIntent();
  await testLatestForwardSeekWinsWhileChunkIsPending();
  await testNewLocalSeekCancelsAnOlderDownloadHorizon();
  await testChunkMetadataArrivesBeforeItsReplayEvents();
  await testSegmentTimeMappingKeepsControllerTimesRecordingGlobal();
  await testRemoteSeekRebuildsFromSnapshotAndUsesLocalGoto();
  await testPauseWhileRemoteSeekIsPendingPreventsAutoResume();
  await testNotReadySeekBootstrapContinuesOnlyFromSnapshotCursor();
  await testRapidRemoteSeekAbortsStaleBootstrap();
  await testBackendClampKeepsAnalyticalTimeButUsesTheLastReplayFrame();
  await testNotReadyBackendClampUsesResolvedTargetAfterContinuation();
  await testPendingSeekConsumesEveryEventAtTheTargetTimestamp();
  await testLegacyContinuationPassesAnExplicitlyIncompleteTarget();
  await testLoadedAnalyticalOverrunReusesTheLastReplayFrame();
  await testSeekableFromIsIndependentOfThePlayerSegmentOrigin();
  await testRemoteSeekRejectsANonSeekV1Response();
  await testDestroyAbortsAPendingRemoteSeek();
  await testDestroyAbortsAndDestroysPlayerOnce();
  console.log("replay-stream tests passed");
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
