const assert = require('node:assert/strict');
const Module = require('node:module');
const path = require('node:path');
const esbuild = require('esbuild');

const MAX_BATCH_BYTES = 8 * 1024 * 1024;

function loadRecordingModule() {
  const sourcePath = path.resolve(__dirname, '../src/recording.js');
  const result = esbuild.buildSync({
    entryPoints: [sourcePath],
    bundle: true,
    format: 'cjs',
    platform: 'node',
    target: 'node20',
    write: false,
  });
  const compiledModule = new Module(sourcePath, module);
  compiledModule.filename = sourcePath;
  compiledModule.paths = Module._nodeModulePaths(path.dirname(sourcePath));
  compiledModule._compile(result.outputFiles[0].text, sourcePath);
  return compiledModule.exports;
}

function createEventTarget() {
  const listeners = new Map();

  return {
    addEventListener(type, listener) {
      const registered = listeners.get(type) || [];
      registered.push(listener);
      listeners.set(type, registered);
    },
    dispatchEvent(event) {
      for (const listener of (listeners.get(event.type) || []).slice()) {
        listener.call(this, event);
      }
    },
  };
}

function createStorage(initialValues = {}) {
  const values = new Map(Object.entries(initialValues));

  return {
    get length() {
      return values.size;
    },
    getItem(key) {
      return values.has(key) ? values.get(key) : null;
    },
    key(index) {
      return Array.from(values.keys())[index] ?? null;
    },
    setItem(key, value) {
      values.set(key, String(value));
    },
    removeItem(key) {
      values.delete(key);
    },
  };
}

function installRecordingEnvironment(options = {}) {
  const originalGlobals = {
    BroadcastChannel: global.BroadcastChannel,
    XMLHttpRequest: global.XMLHttpRequest,
    clearInterval: global.clearInterval,
    document: global.document,
    fetch: global.fetch,
    localStorage: global.localStorage,
    navigator: global.navigator,
    sessionStorage: global.sessionStorage,
    setInterval: global.setInterval,
    setTimeout: global.setTimeout,
    window: global.window,
  };
  const storage = createStorage(options.storage || {});
  const fetchCalls = [];
  const beaconCalls = [];
  const intervals = [];
  const runtimeLogs = [];
  let rrwebEmit = null;

  const document = Object.assign(createEventTarget(), {
    readyState: 'complete',
    title: 'Recording batch test',
    visibilityState: 'visible',
    querySelector(selector) {
      if (selector === 'script[src*="lib.min.js"]') return {};
      return null;
    },
  });
  const window = Object.assign(createEventTarget(), {
    crypto: {
      randomUUID() {
        return '11111111-1111-4111-8111-111111111111';
      },
    },
    location: {
      href: 'https://customer.example.com/dashboard',
    },
    localStorage: storage,
    sessionStorage: storage,
    rrweb: {
      record({ emit }) {
        rrwebEmit = emit;
        return () => {};
      },
    },
  });
  const navigator = {
    sendBeacon(url, payload) {
      beaconCalls.push({ url, payload });
      return true;
    },
  };

  global.window = window;
  global.document = document;
  global.localStorage = storage;
  global.sessionStorage = storage;
  Object.defineProperty(global, 'navigator', {
    configurable: true,
    writable: true,
    value: navigator,
  });
  global.fetch = async (url, requestOptions) => {
    fetchCalls.push({ url, options: requestOptions });
    return { ok: true };
  };
  global.BroadcastChannel = class BroadcastChannel {
    postMessage() {}
  };
  global.XMLHttpRequest = class XMLHttpRequest {};
  global.setTimeout = (callback) => {
    callback();
    return 1;
  };
  global.setInterval = (callback) => {
    intervals.push(callback);
    return intervals.length;
  };
  global.clearInterval = () => {};

  const runtime = {
    config: {
      apiKey: 'RECORDINGTEST123',
      libUrl: 'https://edge.example.com',
      recordingEndpoint: 'https://app.example.com/hm/e/',
    },
    visitorId: '22222222-2222-4222-8222-222222222222',
    log(...args) {
      runtimeLogs.push(args);
    },
  };

  function restore() {
    global.BroadcastChannel = originalGlobals.BroadcastChannel;
    global.XMLHttpRequest = originalGlobals.XMLHttpRequest;
    global.clearInterval = originalGlobals.clearInterval;
    global.document = originalGlobals.document;
    global.fetch = originalGlobals.fetch;
    global.localStorage = originalGlobals.localStorage;
    Object.defineProperty(global, 'navigator', {
      configurable: true,
      writable: true,
      value: originalGlobals.navigator,
    });
    global.sessionStorage = originalGlobals.sessionStorage;
    global.setInterval = originalGlobals.setInterval;
    global.setTimeout = originalGlobals.setTimeout;
    global.window = originalGlobals.window;
  }

  return {
    beaconCalls,
    document,
    emit(event) {
      assert.equal(typeof rrwebEmit, 'function');
      rrwebEmit(event);
    },
    fetchCalls,
    intervals,
    restore,
    runtime,
    runtimeLogs,
  };
}

async function startTestRecorder(env) {
  const { startRecording } = loadRecordingModule();
  startRecording(env.runtime);
  for (let index = 0; index < 4; index++) {
    await Promise.resolve();
  }
  assert.equal(env.intervals.length, 1);
}

function eventWithBytes(marker, byteCount) {
  return {
    type: 3,
    timestamp: Date.now(),
    data: {
      marker,
      text: 'x'.repeat(byteCount),
    },
  };
}

async function runPeriodicBatchSplittingScenario() {
  const env = installRecordingEnvironment();

  try {
    await startTestRecorder(env);
    env.emit(eventWithBytes('first', 5 * 1024 * 1024));
    env.emit(eventWithBytes('second', 5 * 1024 * 1024));

    env.intervals[0]();
    env.intervals[0]();

    assert.equal(env.fetchCalls.length, 2);
    const payloads = env.fetchCalls.map((call) => call.options.body);
    assert.ok(payloads.every((payload) => Buffer.byteLength(payload, 'utf8') <= MAX_BATCH_BYTES));
    assert.deepEqual(
      payloads.map((payload) => JSON.parse(payload).event_data.events[0].data.marker),
      ['first', 'second'],
    );
  } finally {
    env.restore();
  }
}

async function runOversizedEventDropScenario() {
  const env = installRecordingEnvironment();

  try {
    await startTestRecorder(env);
    env.emit(eventWithBytes('oversized', MAX_BATCH_BYTES));
    env.emit(eventWithBytes('kept', 1024));

    env.intervals[0]();

    assert.equal(env.fetchCalls.length, 1);
    const payload = env.fetchCalls[0].options.body;
    assert.ok(Buffer.byteLength(payload, 'utf8') <= MAX_BATCH_BYTES);
    assert.deepEqual(
      JSON.parse(payload).event_data.events.map((event) => event.data.marker),
      ['kept'],
    );
    assert.ok(
      env.runtimeLogs.some((args) => String(args[0]).includes('event dropped')),
    );
  } finally {
    env.restore();
  }
}

async function runFinalBatchSplittingScenario() {
  const env = installRecordingEnvironment();

  try {
    await startTestRecorder(env);
    env.emit(eventWithBytes('first-final', 5 * 1024 * 1024));
    env.emit(eventWithBytes('second-final', 5 * 1024 * 1024));

    env.document.visibilityState = 'hidden';
    env.document.dispatchEvent({ type: 'visibilitychange' });

    assert.equal(env.beaconCalls.length, 2);
    const payloads = env.beaconCalls.map((call) => String(call.payload));
    assert.ok(payloads.every((payload) => Buffer.byteLength(payload, 'utf8') <= MAX_BATCH_BYTES));
    assert.deepEqual(
      payloads.map((payload) => JSON.parse(payload).event_data.is_final_batch),
      [false, true],
    );
  } finally {
    env.restore();
  }
}

async function runOversizedPendingBatchDropScenario() {
  const pendingKey = 'tracker_pending_batches';
  const oversizedPayload = 'x'.repeat(MAX_BATCH_BYTES + 1);
  const eligiblePayload = '{"eligible":true}';
  const env = installRecordingEnvironment({
    storage: {
      [pendingKey]: JSON.stringify([
        { payload: oversizedPayload, timestamp: 1 },
        { payload: eligiblePayload, timestamp: 2 },
      ]),
    },
  });

  try {
    await startTestRecorder(env);

    assert.equal(env.fetchCalls.length, 1);
    assert.equal(env.fetchCalls[0].options.body, eligiblePayload);
    assert.equal(env.runtimeLogs.length, 1);
    assert.ok(String(env.runtimeLogs[0][0]).includes('pending recording batch dropped'));
    assert.equal(env.runtimeLogs[0][1], undefined);
  } finally {
    env.restore();
  }
}

(async () => {
  try {
    await runPeriodicBatchSplittingScenario();
    await runOversizedEventDropScenario();
    await runFinalBatchSplittingScenario();
    await runOversizedPendingBatchDropScenario();
    console.log('recording batch smoke test passed');
  } catch (error) {
    console.error(error);
    process.exitCode = 1;
  }
})();
