const assert = require('node:assert/strict');
const path = require('node:path');

function createEventTarget() {
  const listeners = new Map();

  return {
    addEventListener(type, listener) {
      const existing = listeners.get(type) || [];
      existing.push(listener);
      listeners.set(type, existing);
    },
    removeEventListener(type, listener) {
      const existing = listeners.get(type) || [];
      listeners.set(
        type,
        existing.filter((registered) => registered !== listener),
      );
    },
    dispatchEvent(event) {
      const listenersForType = (listeners.get(event.type) || []).slice();
      for (const listener of listenersForType) {
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

function installBrowserStubs(options = {}) {
  const bundlePath = path.resolve(__dirname, '../../../static/js/main.js');
  const RealDate = Date;
  let nowMs = 0;
  const storedVisitorId = options.storedVisitorId || null;

  class FakeDate extends RealDate {
    constructor(...args) {
      super(...(args.length ? args : [nowMs]));
    }

    static now() {
      return nowMs;
    }
  }

  class FakeElement {
    constructor(tagName = 'DIV', text = '') {
      this.tagName = String(tagName || 'DIV').toUpperCase();
      this.innerText = text;
      this.textContent = text;
      this.parentElement = null;
      this.previousElementSibling = null;
      this.childNodes = [];
      this.attributes = {};
      this.className = '';
      this.id = '';
    }

    closest(selector) {
      if (selector === 'label') return null;
      if (typeof selector === 'string' && selector.includes('button') && this.tagName === 'BUTTON') {
        return this;
      }
      if (
        typeof selector === 'string' &&
        selector.includes('a[href]') &&
        this.tagName === 'A' &&
        this.getAttribute('href')
      ) {
        return this;
      }
      return null;
    }

    querySelector() {
      return null;
    }

    querySelectorAll() {
      return [];
    }

    getAttribute(name) {
      return Object.prototype.hasOwnProperty.call(this.attributes, name)
        ? this.attributes[name]
        : null;
    }

    matches() {
      return false;
    }

    cloneNode() {
      return new FakeElement(this.tagName, this.innerText);
    }
  }

  class FakeButtonElement extends FakeElement {
    constructor(text) {
      super('BUTTON', text);
    }
  }

  class FakeInputElement extends FakeElement {
    constructor() {
      super('INPUT', '');
      this.type = 'text';
      this.labels = [];
      this.value = '';
      this.placeholder = '';
    }
  }

  class FakeSelectElement extends FakeElement {
    constructor() {
      super('SELECT', '');
      this.selectedOptions = [];
    }
  }

  class FakeTextAreaElement extends FakeElement {}
  class FakeAnchorElement extends FakeElement {
    constructor(text, href) {
      super('A', text);
      this.attributes.href = href || '';
    }
  }

  const storage = createStorage(
    storedVisitorId ? { tracker_visitor_id: storedVisitorId } : {},
  );
  const beaconCalls = [];
  const navigator = {
    sendBeacon(url, payload) {
      beaconCalls.push({ url, payload });
      if (typeof options.sendBeaconResult === 'boolean') {
        return options.sendBeaconResult;
      }
      return false;
    },
  };
  const fetchCalls = [];
  const intervals = [];
  const consoleCalls = {
    log: [],
    info: [],
    warn: [],
    error: [],
  };
  let nextIntervalId = 1;

  const document = Object.assign(createEventTarget(), {
    title: 'Tracker Test',
    visibilityState: 'visible',
    currentScript: {
      dataset: {
        apiKey: 'TRACKERTEST123',
        apiUrl: 'https://app.example.com',
        capture: 'analytics',
        analyticsFlushMs: '5000',
        analyticsBatchSize: '10',
        analyticsPassiveThrottleMs: '500',
      },
    },
    body: new FakeElement('BODY', ''),
    head: {
      appendChild() {},
    },
    querySelector(selector) {
      if (selector === 'script[data-api-key]') {
        return this.currentScript;
      }
      return null;
    },
    getElementById() {
      return null;
    },
  });

  const crypto = {};
  if (options.disableRandomUUID !== true) {
    crypto.randomUUID = function randomUUID() {
      return '11111111-1111-4111-8111-111111111111';
    };
  }
  if (typeof options.getRandomValues === 'function') {
    crypto.getRandomValues = options.getRandomValues;
  }

  const window = Object.assign(createEventTarget(), {
    location: {
      href: 'https://app.example.com/dashboard?bootstrap=1',
      origin: 'https://app.example.com',
    },
    hymetrySettings: options.hymetrySettings,
    localStorage: storage,
    sessionStorage: storage,
    crypto,
    navigator,
  });

  const originalGlobals = {
    Blob: global.Blob,
    Date: global.Date,
    Element: global.Element,
    HTMLAnchorElement: global.HTMLAnchorElement,
    HTMLButtonElement: global.HTMLButtonElement,
    HTMLInputElement: global.HTMLInputElement,
    HTMLSelectElement: global.HTMLSelectElement,
    HTMLTextAreaElement: global.HTMLTextAreaElement,
    Node: global.Node,
    clearInterval: global.clearInterval,
    console: global.console,
    document: global.document,
    fetch: global.fetch,
    navigator: global.navigator,
    setInterval: global.setInterval,
    window: global.window,
  };

  global.Date = FakeDate;
  global.window = window;
  global.document = document;
  Object.defineProperty(global, 'navigator', {
    configurable: true,
    writable: true,
    value: navigator,
  });
  global.fetch = async (url, options) => {
    fetchCalls.push({ url, options });
    return { ok: true };
  };
  global.Blob = class Blob {
    constructor(parts, options) {
      this.parts = parts;
      this.type = options?.type || '';
    }
  };
  global.Element = FakeElement;
  global.HTMLButtonElement = FakeButtonElement;
  global.HTMLAnchorElement = FakeAnchorElement;
  global.HTMLInputElement = FakeInputElement;
  global.HTMLSelectElement = FakeSelectElement;
  global.HTMLTextAreaElement = FakeTextAreaElement;
  global.Node = { TEXT_NODE: 3 };
  global.setInterval = (callback) => {
    const id = nextIntervalId;
    nextIntervalId += 1;
    intervals.push({ id, callback });
    return id;
  };
  global.clearInterval = () => {};
  global.console = {
    log(...args) {
      consoleCalls.log.push(args);
    },
    info(...args) {
      consoleCalls.info.push(args);
    },
    warn(...args) {
      consoleCalls.warn.push(args);
    },
    error(...args) {
      consoleCalls.error.push(args);
    },
  };

  function setHref(nextHref) {
    const nextUrl = new URL(nextHref);
    window.location.href = nextUrl.href;
    window.location.origin = nextUrl.origin;
  }

  function setNow(nextNowMs) {
    nowMs = nextNowMs;
  }

  function restore() {
    global.Blob = originalGlobals.Blob;
    global.Date = originalGlobals.Date;
    global.Element = originalGlobals.Element;
    global.HTMLAnchorElement = originalGlobals.HTMLAnchorElement;
    global.HTMLButtonElement = originalGlobals.HTMLButtonElement;
    global.HTMLInputElement = originalGlobals.HTMLInputElement;
    global.HTMLSelectElement = originalGlobals.HTMLSelectElement;
    global.HTMLTextAreaElement = originalGlobals.HTMLTextAreaElement;
    global.Node = originalGlobals.Node;
    global.clearInterval = originalGlobals.clearInterval;
    global.console = originalGlobals.console;
    global.document = originalGlobals.document;
    global.fetch = originalGlobals.fetch;
    global.setInterval = originalGlobals.setInterval;
    global.window = originalGlobals.window;
    Object.defineProperty(global, 'navigator', {
      configurable: true,
      writable: true,
      value: originalGlobals.navigator,
    });
  }

  return {
    FakeButtonElement,
    bundlePath,
    beaconCalls,
    consoleCalls,
    document,
    fetchCalls,
    intervals,
    restore,
    FakeAnchorElement,
    setHref,
    setNow,
    storage,
    window,
  };
}

function run() {
  const env = installBrowserStubs();

  try {
    delete require.cache[require.resolve(env.bundlePath)];
    require(env.bundlePath);

    env.setNow(1000);
    env.setHref('https://app.example.com/dashboard?scroll=bootstrap');
    env.document.dispatchEvent({ type: 'scroll' });

    env.setNow(1200);
    env.setHref('https://app.example.com/dashboard?scroll=ignored');
    env.document.dispatchEvent({ type: 'scroll' });

    env.setNow(1700);
    env.setHref('https://app.example.com/dashboard?scroll=latest');
    env.document.dispatchEvent({ type: 'scroll' });

    env.setNow(1800);
    env.setHref('https://app.example.com/dashboard?move=first');
    env.document.dispatchEvent({ type: 'mousemove' });

    env.setNow(1900);
    env.setHref('https://app.example.com/dashboard?move=ignored');
    env.document.dispatchEvent({ type: 'mousemove' });

    env.setNow(2400);
    env.setHref('https://app.example.com/dashboard?move=latest');
    env.document.dispatchEvent({ type: 'mousemove' });

    env.setNow(2600);
    env.setHref('https://app.example.com/dashboard?click=final');
    env.document.dispatchEvent({
      type: 'click',
      target: new env.FakeButtonElement('Open dashboard'),
    });

    assert.equal(env.fetchCalls.length, 0);
    assert.equal(env.intervals.length, 1);

    env.intervals[0].callback();

    assert.equal(env.fetchCalls.length, 1);

    const payload = JSON.parse(env.fetchCalls[0].options.body);
    const batch = payload.batch;
    const eventTypes = batch.map((event) => event.type);

    assert.equal(eventTypes.filter((type) => type === 'click').length, 1);
    assert.equal(eventTypes.filter((type) => type === 'scroll').length, 1);
    assert.equal(eventTypes.filter((type) => type === 'mouse_move').length, 1);
    assert.equal(batch.find((event) => event.type === 'scroll').page.url, 'https://app.example.com/dashboard');
    assert.equal(batch.find((event) => event.type === 'mouse_move').page.url, 'https://app.example.com/dashboard');
    assert.equal(batch.find((event) => event.type === 'click').page.url, 'https://app.example.com/dashboard');
    assert.equal(batch.find((event) => event.type === 'click').elementKey, 'Button: Open dashboard');

    env.intervals[0].callback();
    assert.equal(env.fetchCalls.length, 1);
  } finally {
    env.restore();
  }
}

function runFallbackVisitorIdScenario() {
  const env = installBrowserStubs({
    disableRandomUUID: true,
    getRandomValues(bytes) {
      for (let i = 0; i < bytes.length; i++) {
        bytes[i] = i;
      }
      return bytes;
    },
    storedVisitorId: 'mobf9liv_zmwztu7r',
  });

  try {
    delete require.cache[require.resolve(env.bundlePath)];
    require(env.bundlePath);

    env.document.dispatchEvent({ type: 'scroll' });

    const visitorId = env.storage.getItem('tracker_visitor_id');
    assert.notEqual(visitorId, 'mobf9liv_zmwztu7r');
    assert.match(
      visitorId,
      /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i,
    );
  } finally {
    env.restore();
  }
}

function parseBeaconPayload(beaconCall) {
  const payload = beaconCall.payload;
  if (payload && Array.isArray(payload.parts)) {
    return JSON.parse(payload.parts.join(''));
  }

  return JSON.parse(String(payload));
}

function runBootstrapNavigationClickScenario() {
  const env = installBrowserStubs({ sendBeaconResult: true });

  try {
    delete require.cache[require.resolve(env.bundlePath)];
    require(env.bundlePath);

    env.setNow(1000);
    env.setHref('https://app.example.com/jobs/');
    env.document.dispatchEvent({
      type: 'click',
      target: new env.FakeAnchorElement('Frontend Engineer', '/jobs/frontend-engineer/'),
      button: 0,
      defaultPrevented: false,
    });

    assert.equal(env.beaconCalls.length, 0);
    assert.equal(env.fetchCalls.length, 0);

    const keys = [];
    for (let i = 0; i < env.storage.length; i++) {
      keys.push(env.storage.key(i));
    }

    const pendingKey = keys.find((key) => typeof key === 'string' && key.startsWith('tracker_pending_analytics:'));
    assert.ok(pendingKey);

    const storedSnapshot = JSON.parse(env.storage.getItem(pendingKey));
    assert.equal(storedSnapshot.clickEvents.length, 1);
    assert.equal(storedSnapshot.clickEvents[0].type, 'click');
    assert.equal(storedSnapshot.clickEvents[0].elementKey, 'Link: Frontend Engineer');
    assert.equal(storedSnapshot.clickEvents[0].page.url, 'https://app.example.com/jobs/');

    env.intervals[0].callback();
    assert.equal(env.fetchCalls.length, 1);
  } finally {
    env.restore();
  }
}

function runNavigationFlushesPassiveEventsScenario() {
  const env = installBrowserStubs({ sendBeaconResult: true });

  try {
    delete require.cache[require.resolve(env.bundlePath)];
    require(env.bundlePath);

    env.setNow(1000);
    env.setHref('https://app.example.com/jobs/');
    env.document.dispatchEvent({ type: 'scroll' });

    env.setNow(1600);
    env.setHref('https://app.example.com/jobs/?mouse=1');
    env.document.dispatchEvent({ type: 'mousemove' });

    env.setNow(2200);
    env.setHref('https://app.example.com/jobs/');
    env.document.dispatchEvent({
      type: 'click',
      target: new env.FakeAnchorElement('Backend Engineer', '/jobs/backend-engineer/'),
      button: 0,
      defaultPrevented: false,
    });

    assert.equal(env.beaconCalls.length, 0);
    assert.equal(env.fetchCalls.length, 0);

    env.intervals[0].callback();

    assert.equal(env.fetchCalls.length, 1);

    const payload = JSON.parse(env.fetchCalls[0].options.body);
    const eventTypes = payload.batch.map((event) => event.type);

    assert.equal(eventTypes.filter((type) => type === 'click').length, 1);
    assert.equal(eventTypes.filter((type) => type === 'scroll').length, 1);
    assert.equal(eventTypes.filter((type) => type === 'mouse_move').length, 1);
    assert.equal(
      payload.batch.find((event) => event.type === 'click').elementKey,
      'Link: Backend Engineer',
    );
  } finally {
    env.restore();
  }
}

function runOrphanedStoragePickupScenario() {
  const orphanedSnapshot = {
    clickEvents: [
      {
        type: 'click',
        ts: '2026-04-23T12:00:00.000Z',
        page: {
          url: 'https://app.example.com/jobs/frontend-engineer/',
          title: 'Frontend Engineer',
        },
        elementKey: 'Link: Apply',
      },
    ],
    scrollEvent: null,
    mouseMoveEvent: null,
    updatedAt: 1,
  };
  const env = installBrowserStubs({
    storedVisitorId: '11111111-1111-4111-8111-111111111111',
  });

  try {
    env.storage.setItem(
      'tracker_pending_analytics:orphaned-tab',
      JSON.stringify(orphanedSnapshot),
    );

    delete require.cache[require.resolve(env.bundlePath)];
    require(env.bundlePath);

    env.setNow(20000);
    env.intervals[0].callback();

    assert.equal(env.fetchCalls.length, 1);
    const payload = JSON.parse(env.fetchCalls[0].options.body);
    assert.equal(payload.batch.length, 1);
    assert.equal(payload.batch[0].elementKey, 'Link: Apply');
    assert.equal(env.storage.getItem('tracker_pending_analytics:orphaned-tab'), null);
  } finally {
    env.restore();
  }
}

function runSettingsIdentifyScenario() {
  const env = installBrowserStubs({
    hymetrySettings: {
      identify: {
        user: {
          id: 'user-123',
          traits: {
            name: 'Jane Cooper',
          },
        },
        company: {
          id: 'company-456',
          traits: {
            name: 'Acme Inc.',
          },
        },
      },
    },
  });

  try {
    delete require.cache[require.resolve(env.bundlePath)];
    require(env.bundlePath);

    env.setNow(1000);
    env.document.dispatchEvent({ type: 'scroll' });
    env.intervals[0].callback();

    assert.equal(env.fetchCalls.length, 1);

    const payload = JSON.parse(env.fetchCalls[0].options.body);
    assert.equal(payload.batch.length, 1);
    assert.equal(payload.batch[0].user_id, 'user-123');
    assert.equal(payload.batch[0].company_id, 'company-456');
    assert.equal(payload.batch[0].user.id, 'user-123');
    assert.equal(payload.batch[0].user.traits.name, 'Jane Cooper');
    assert.equal(payload.batch[0].company.id, 'company-456');
    assert.equal(payload.batch[0].company.traits.name, 'Acme Inc.');
  } finally {
    env.restore();
  }
}

function runSettingsIdentifyUserIdFallbackScenario() {
  const env = installBrowserStubs({
    hymetrySettings: {
      identify: {
        user: {
          id: 'user-without-traits',
        },
        company: {
          id: 'company-without-traits',
        },
      },
    },
  });

  try {
    delete require.cache[require.resolve(env.bundlePath)];
    require(env.bundlePath);

    env.setNow(1000);
    env.document.dispatchEvent({ type: 'scroll' });
    env.intervals[0].callback();

    assert.equal(env.fetchCalls.length, 1);

    const payload = JSON.parse(env.fetchCalls[0].options.body);
    assert.equal(payload.batch.length, 1);
    assert.equal(payload.batch[0].user_id, 'user-without-traits');
    assert.equal(payload.batch[0].user.id, 'user-without-traits');
    assert.deepEqual(payload.batch[0].user.traits, {});
    assert.equal(payload.batch[0].company_id, 'company-without-traits');
  } finally {
    env.restore();
  }
}

function runSettingsIdentifyEmailFallbackScenario() {
  const env = installBrowserStubs({
    hymetrySettings: {
      identify: {
        user: {
          id: 'user-with-email-trait',
          traits: {
            email: 'person@example.com',
          },
        },
        company: {
          id: 'company-456',
          traits: {
            name: 'Acme Inc.',
          },
        },
      },
    },
  });

  try {
    delete require.cache[require.resolve(env.bundlePath)];
    require(env.bundlePath);

    env.setNow(1000);
    env.document.dispatchEvent({ type: 'scroll' });
    env.intervals[0].callback();

    assert.equal(env.fetchCalls.length, 1);

    const payload = JSON.parse(env.fetchCalls[0].options.body);
    assert.equal(payload.batch.length, 1);
    assert.equal(payload.batch[0].user_id, 'user-with-email-trait');
    assert.equal(payload.batch[0].user.id, 'user-with-email-trait');
    assert.equal(payload.batch[0].user.traits.email, 'person@example.com');
  } finally {
    env.restore();
  }
}

function runMissingSettingsIdentityScenario() {
  const env = installBrowserStubs();

  try {
    delete require.cache[require.resolve(env.bundlePath)];
    require(env.bundlePath);

    env.setNow(1000);
    env.document.dispatchEvent({ type: 'scroll' });

    const errorMessages = env.consoleCalls.error.map((args) => args.join(' '));
    assert.ok(
      errorMessages.some((message) => message.includes('Hymetry: identity is not configured')),
    );
  } finally {
    env.restore();
  }
}

try {
  run();
  runFallbackVisitorIdScenario();
  runBootstrapNavigationClickScenario();
  runNavigationFlushesPassiveEventsScenario();
  runOrphanedStoragePickupScenario();
  runSettingsIdentifyScenario();
  runSettingsIdentifyEmailFallbackScenario();
  runSettingsIdentifyUserIdFallbackScenario();
  runMissingSettingsIdentityScenario();
  console.log('passive analytics smoke test passed');
} catch (error) {
  console.error(error);
  process.exitCode = 1;
}
