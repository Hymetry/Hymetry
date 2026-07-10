const VISITOR_ID_KEY = 'tracker_visitor_id';

export const STARTING_EVENTS = ['click', 'mousemove', 'scroll', 'touchstart', 'keydown'];

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function byteToHex(byte) {
  return byte.toString(16).padStart(2, '0');
}

function formatUuid(bytes) {
  return (
    byteToHex(bytes[0]) +
    byteToHex(bytes[1]) +
    byteToHex(bytes[2]) +
    byteToHex(bytes[3]) +
    '-' +
    byteToHex(bytes[4]) +
    byteToHex(bytes[5]) +
    '-' +
    byteToHex(bytes[6]) +
    byteToHex(bytes[7]) +
    '-' +
    byteToHex(bytes[8]) +
    byteToHex(bytes[9]) +
    '-' +
    byteToHex(bytes[10]) +
    byteToHex(bytes[11]) +
    byteToHex(bytes[12]) +
    byteToHex(bytes[13]) +
    byteToHex(bytes[14]) +
    byteToHex(bytes[15])
  );
}

function createFallbackUuid() {
  const bytes = new Uint8Array(16);

  if (window.crypto && typeof window.crypto.getRandomValues === 'function') {
    window.crypto.getRandomValues(bytes);
  } else {
    for (let i = 0; i < bytes.length; i++) {
      bytes[i] = Math.floor(Math.random() * 256);
    }
  }

  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  return formatUuid(bytes);
}

export function createId() {
  if (window.crypto && typeof window.crypto.randomUUID === 'function') {
    return window.crypto.randomUUID();
  }

  return createFallbackUuid();
}

export function nowIso() {
  return new Date().toISOString();
}

function safeGet(storage, key) {
  try {
    return storage.getItem(key);
  } catch (e) {
    return null;
  }
}

function safeSet(storage, key, value) {
  try {
    storage.setItem(key, value);
    return true;
  } catch (e) {
    return false;
  }
}

function safeString(value, maxLength) {
  if (value == null) return null;
  const text = String(value).trim();
  if (!text) return null;
  return text.slice(0, maxLength || 300);
}

function isUuid(value) {
  const text = safeString(value, 64);
  return !!(text && UUID_RE.test(text));
}

function cloneTraits(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return {};
  }

  try {
    return JSON.parse(JSON.stringify(value));
  } catch (e) {
    return {};
  }
}

function normalizeCaptureModes(rawCapture) {
  const result = { recording: false, analytics: false };
  const raw = safeString(rawCapture, 200) || 'analytics,recording';
  const values = raw.split(',').map((part) => part.trim().toLowerCase()).filter(Boolean);

  if (!values.length) {
    result.recording = true;
    result.analytics = true;
    return result;
  }

  for (let i = 0; i < values.length; i++) {
    if (values[i] === 'recording') result.recording = true;
    if (values[i] === 'analytics') result.analytics = true;
  }

  if (!result.recording && !result.analytics) {
    result.recording = true;
  }

  return result;
}

function getTrackerScript() {
  if (document.currentScript && document.currentScript.dataset?.apiKey) {
    return document.currentScript;
  }

  return document.querySelector('script[data-api-key]');
}

function stripTrailingSlash(url) {
  return String(url || '').replace(/\/$/, '');
}

function getBaseUrl(script) {
  if (script?.dataset.apiUrl) {
    return stripTrailingSlash(script.dataset.apiUrl);
  }

  if (script?.src) {
    try {
      const url = new URL(script.src);
      return `${url.protocol}//${url.host}`;
    } catch (e) {
      // ignore URL parsing failures and fallback
    }
  }

  return window.location.origin;
}

function getLibUrl(script) {
  if (script?.dataset.libUrl) {
    return stripTrailingSlash(script.dataset.libUrl);
  }

  if (script?.src) {
    try {
      const url = new URL(script.src);
      const path = url.pathname.replace(/\/[^\/]*$/, '');
      return url.origin + path;
    } catch (e) {
      // ignore URL parsing failures and fallback
    }
  }

  return window.location.origin;
}

function getVisitorId() {
  let visitorId = safeGet(window.localStorage, VISITOR_ID_KEY);
  if (!isUuid(visitorId)) {
    visitorId = createId();
    safeSet(window.localStorage, VISITOR_ID_KEY, visitorId);
  }
  return visitorId;
}

export function createRuntime() {
  const script = getTrackerScript();
  const apiKey = script?.dataset.apiKey;

  if (!apiKey) {
    console.error('Hymetry: data-api-key not set in <script> definition');
    return null;
  }

  const trackerUrl = getBaseUrl(script);
  const captureModes = normalizeCaptureModes(script?.dataset.capture);
  const runtime = {
    script,
    visitorId: getVisitorId(),
    identity: {
      user: { id: null, traits: {} },
      company: { id: null, traits: {} },
    },
    config: {
      apiKey,
      trackerUrl,
      libUrl: getLibUrl(script),
      app: safeString(script?.dataset.app, 100) || 'hymetry',
      captureModes,
      recordingEndpoint: `${trackerUrl}/hm/e/`,
      analyticsEndpoint: `${trackerUrl}/hm/ae/`,
      analyticsBatchSize: Number(script?.dataset.analyticsBatchSize || 10),
      analyticsFlushIntervalMs: Number(script?.dataset.analyticsFlushMs || 5000),
      analyticsPassiveThrottleMs: Number(script?.dataset.analyticsPassiveThrottleMs || 500),
      debug: script?.dataset.debug === 'true',
    },
  };

  runtime.log = function log() {
    if (!runtime.config.debug) return;
    const args = Array.prototype.slice.call(arguments);
    console.log.apply(console, ['[hymetry]'].concat(args));
  };

  runtime.getIdentity = function getIdentity() {
    return {
      user: {
        id: runtime.identity.user.id ?? null,
        traits: cloneTraits(runtime.identity.user.traits),
      },
      company: {
        id: runtime.identity.company.id ?? null,
        traits: cloneTraits(runtime.identity.company.traits),
      },
    };
  };

  runtime.setIdentity = function setIdentity(payload) {
    const data = payload || {};
    runtime.identity = {
      user: {
        id: safeString(data?.user?.id, 255),
        traits: cloneTraits(data?.user?.traits),
      },
      company: {
        id: safeString(data?.company?.id, 255),
        traits: cloneTraits(data?.company?.traits),
      },
    };
    runtime.log('identify', runtime.identity);
  };

  return runtime;
}

export function createDeferredApiBridge() {
  const existing = window.hymetry || {};
  const queuedIdentifyCalls = [];
  let handlers = null;

  function identify(payload) {
    if (handlers?.identify) {
      handlers.identify(payload || {});
      return;
    }
    queuedIdentifyCalls.push(payload || {});
  }

  function flush() {
    if (handlers?.flush) {
      handlers.flush();
    }
  }

  window.hymetry = Object.assign(existing, {
    identify,
    flush,
  });

  return {
    bind(nextHandlers) {
      handlers = nextHandlers || {};
      while (queuedIdentifyCalls.length) {
        handlers?.identify?.(queuedIdentifyCalls.shift());
      }
    },
  };
}
