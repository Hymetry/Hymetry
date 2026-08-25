import { createId, nowIso } from './init';

const TAB_ID_KEY = 'tracker_tab_id';
const ANALYTICS_STORAGE_PREFIX = 'tracker_pending_analytics:';
const ORPHANED_ANALYTICS_MAX_AGE_MS = 15000;

// The sampled event types.  Only the newest observation of each survives to
// the next flush, which is all the question they answer -- was the visitor
// doing this at all -- needs.  Clicks are the exception and are kept one for
// one, because each is a separate act on a separate target.
//
// `storageKey` is the field the persisted snapshot uses.  A snapshot outlives
// the bundle that wrote it -- a tab persists one, the page reloads, a newer
// bundle reads it back -- so those names are part of a stored format and are
// spelled out here rather than derived from the type.
//
// Every site that has to touch all of them reads this list, so a type added
// here cannot be forgotten in one of them.  Dropping a pending event on a
// failed flush would be silent, which is exactly the bug worth designing out.
const PASSIVE_EVENTS = [
  { type: 'scroll', storageKey: 'scrollEvent' },
  { type: 'mouse_move', storageKey: 'mouseMoveEvent' },
  { type: 'key_press', storageKey: 'keyPressEvent' },
  { type: 'touch_move', storageKey: 'touchMoveEvent' },
];

export function hasPendingAnalyticsStorage() {
  try {
    const storage = window.localStorage;
    const total = storage.length || 0;

    for (let i = 0; i < total; i++) {
      const key = storage.key(i);
      if (typeof key === 'string' && key.startsWith(ANALYTICS_STORAGE_PREFIX)) {
        return true;
      }
    }
  } catch (e) {
    return false;
  }

  return false;
}

function safeString(value, maxLength) {
  if (value == null) return null;
  const text = String(value).trim();
  if (!text) return null;

  const limit = 40;
  if (text.length <= limit) {
    return text;
  }

  const cutLength = Math.max(limit - 1, 0);
  const shortened = text.slice(0, cutLength).trim();
  return `${shortened}…`;
}

function getPageContext() {
  const url = window.location.href;
  return {
    url,
    title: document.title || url,
  };
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

function safeRemove(storage, key) {
  try {
    storage.removeItem(key);
    return true;
  } catch (e) {
    return false;
  }
}

const INTERACTIVE_SELECTOR = [
  'button',
  'a[href]',
  'input',
  'select',
  'textarea',
  'summary',
  '[role="button"]',
  '[role="link"]',
  '[role="checkbox"]',
  '[role="radio"]',
  '[role="tab"]',
  '[role="menuitem"]',
  '[onclick]',
].join(', ');

function getEventTargetElement(event) {
  if (!event) return null;

  if (typeof event.composedPath === 'function') {
    const path = event.composedPath();
    for (let i = 0; i < path.length; i++) {
      const element = normalizeTarget(path[i]);
      if (element) return element;
    }
  }

  return normalizeTarget(event.target);
}

function pickClickTarget(startEl) {
  const element = normalizeTarget(startEl);
  if (!element) return null;

  const control = findMeaningfulControl(element);
  if (control) return control;

  return element.closest('[id], [name], [aria-label], [title]') || element;
}

function getClickInfo(target) {
  const element = normalizeTarget(target);

  if (!element) {
    return {
      name: 'Page background',
      interactive: false,
      category: 'background',
    };
  }

  const control = findMeaningfulControl(element);
  if (control) {
    return describeInteractiveElement(control);
  }

  const text = getClosestReadableText(element);
  if (text) {
    return {
      name: text === 'Some text' ? 'Some text' : `Text: ${text}`,
      interactive: false,
      category: 'text',
    };
  }

  return {
    name: 'Page background',
    interactive: false,
    category: 'background',
  };
}

function getReadableElementName(target) {
  return getClickInfo(target).name;
}

function normalizeTarget(target) {
  if (!target) return null;

  if (target instanceof Element) return target;

  if (typeof Node !== 'undefined' && target.nodeType === Node.TEXT_NODE) {
    return target.parentElement || null;
  }

  return null;
}

function findMeaningfulControl(start) {
  const label = start.closest('label');
  if (label) {
    const labelControl = resolveLabelControl(label);
    if (labelControl) return labelControl;
  }

  const interactive = start.closest(INTERACTIVE_SELECTOR);
  if (!interactive) return null;

  if (interactive instanceof HTMLInputElement) {
    const type = (interactive.type || '').toLowerCase();
    if (type === 'hidden') return null;
  }

  return interactive;
}

function resolveLabelControl(label) {
  const nested = label.querySelector('input:not([type="hidden"]), select, textarea');
  if (nested) return nested;

  const forId = label.getAttribute('for');
  if (forId) {
    const linked = document.getElementById(forId);
    if (
      linked instanceof HTMLInputElement ||
      linked instanceof HTMLSelectElement ||
      linked instanceof HTMLTextAreaElement
    ) {
      if (linked instanceof HTMLInputElement && (linked.type || '').toLowerCase() === 'hidden') {
        return null;
      }
      return linked;
    }
  }

  return null;
}

function describeInteractiveElement(el) {
  const role = (el.getAttribute('role') || '').toLowerCase();

  if (el instanceof HTMLButtonElement || el.tagName === 'SUMMARY' || role === 'button') {
    const text = getVisibleText(el);
    return {
      name: text ? `Button: ${text}` : 'Button',
      interactive: true,
      category: 'button',
    };
  }

  if (el instanceof HTMLAnchorElement || role === 'link') {
    const text = getVisibleText(el);
    return {
      name: text ? `Link: ${text}` : 'Link',
      interactive: true,
      category: 'link',
    };
  }

  if (el instanceof HTMLInputElement) {
    const type = (el.type || '').toLowerCase();

    if (type === 'submit' || type === 'button' || type === 'reset' || type === 'image') {
      const text = normalizeText(el.value) || getLabelText(el);
      return {
        name: text ? `Button: ${text}` : 'Button',
        interactive: true,
        category: 'button',
      };
    }

    if (type === 'checkbox') {
      const text = getLabelText(el) || normalizeText(el.value);
      return {
        name: text ? `Checkbox: ${text}` : 'Checkbox',
        interactive: true,
        category: 'checkbox',
      };
    }

    if (type === 'radio') {
      const text = getLabelText(el) || normalizeText(el.value);
      return {
        name: text ? `Radio: ${text}` : 'Radio',
        interactive: true,
        category: 'radio',
      };
    }

    const text = getLabelText(el) || normalizeText(el.placeholder);
    return {
      name: text ? `Input: ${text}` : 'Input',
      interactive: true,
      category: 'input',
    };
  }

  if (el instanceof HTMLSelectElement) {
    const selectedText = normalizeText(el.selectedOptions && el.selectedOptions[0]?.textContent);
    const labelText = getLabelText(el);

    return {
      name: selectedText ? `Select: ${selectedText}` : labelText ? `Select: ${labelText}` : 'Select',
      interactive: true,
      category: 'select',
    };
  }

  if (el instanceof HTMLTextAreaElement) {
    const text = getLabelText(el) || normalizeText(el.placeholder);
    return {
      name: text ? `Input: ${text}` : 'Input',
      interactive: true,
      category: 'input',
    };
  }

  if (role === 'checkbox') {
    const text = getVisibleText(el);
    return {
      name: text ? `Checkbox: ${text}` : 'Checkbox',
      interactive: true,
      category: 'checkbox',
    };
  }

  if (role === 'radio') {
    const text = getVisibleText(el);
    return {
      name: text ? `Radio: ${text}` : 'Radio',
      interactive: true,
      category: 'radio',
    };
  }

  if (role === 'tab') {
    const text = getVisibleText(el);
    return {
      name: text ? `Tab: ${text}` : 'Tab',
      interactive: true,
      category: 'tab',
    };
  }

  if (role === 'menuitem') {
    const text = getVisibleText(el);
    return {
      name: text ? `Menu item: ${text}` : 'Menu item',
      interactive: true,
      category: 'menuitem',
    };
  }

  const text = getVisibleText(el);
  return {
    name: text ? `Element: ${text}` : 'Element',
    interactive: true,
    category: 'element',
  };
}

function getLabelText(control) {
  if ('labels' in control && control.labels && control.labels.length) {
    for (const label of control.labels) {
      const text = getCleanLabelText(label);
      if (text) return text;
    }
  }

  const wrappingLabel = control.closest('label');
  if (wrappingLabel) {
    const text = getCleanLabelText(wrappingLabel);
    if (text) return text;
  }

  return '';
}

function getCleanLabelText(label) {
  const clone = label.cloneNode(true);

  clone
    .querySelectorAll('input, select, textarea, button, svg, img, [aria-hidden="true"]')
    .forEach((node) => node.remove());

  return shortenText(normalizeText(clone.innerText || clone.textContent), 80);
}

function getVisibleText(el) {
  const text = normalizeText(el.innerText || el.textContent);
  return shortenText(text, 80);
}

function getClosestReadableText(start) {
  let current = start;
  let depth = 0;

  while (current && current !== document.body && depth < 5) {
    const directText = getDirectText(current);
    if (directText) return directText;

    if (isTextLikeElement(current)) {
      const text = normalizeText(current.innerText || current.textContent);

      if (text) {
        if (text.length > 120) return 'Some text';
        return shortenText(text, 60);
      }
    }

    current = current.parentElement;
    depth += 1;
  }

  return '';
}

function getDirectText(el) {
  const parts = [];

  for (const node of el.childNodes) {
    if (typeof Node !== 'undefined' && node.nodeType === Node.TEXT_NODE) {
      const text = normalizeText(node.textContent);
      if (text) parts.push(text);
    }
  }

  const combined = normalizeText(parts.join(' '));
  if (!combined) return '';

  if (combined.length > 120) return 'Some text';
  return shortenText(combined, 60);
}

function isTextLikeElement(el) {
  const tag = el.tagName;
  return [
    'SPAN',
    'P',
    'DIV',
    'LI',
    'TD',
    'TH',
    'LABEL',
    'STRONG',
    'EM',
    'SMALL',
    'H1',
    'H2',
    'H3',
    'H4',
    'H5',
    'H6',
  ].includes(tag);
}

function normalizeText(value) {
  return (value || '').replace(/\s+/g, ' ').trim();
}

function shortenText(text, maxLength) {
  if (!text) return '';

  if (text.length <= maxLength) return text;

  return `${text.slice(0, maxLength - 1).trim()}…`;
}

function normalizeHref(rawHref) {
  if (!rawHref) return null;

  try {
    const url = new URL(rawHref, window.location.href);
    if (url.origin === window.location.origin) {
      return url.pathname || '/';
    }
    return url.origin + (url.pathname || '/');
  } catch (e) {
    return safeString(rawHref, 300);
  }
}

function getIndexWithinType(el) {
  if (!el || !el.parentElement) return 1;

  let index = 1;
  let sibling = el.previousElementSibling;
  while (sibling) {
    if (sibling.tagName === el.tagName) {
      index += 1;
    }
    sibling = sibling.previousElementSibling;
  }

  return index;
}

function buildDomPathKey(el) {
  const parts = [];
  let current = el;
  let depth = 0;

  while (current instanceof Element && depth < 4) {
    const tag = (current.tagName || '').toLowerCase();
    if (!tag) break;

    const id = safeString(current.id, 50);
    if (id) {
      parts.unshift(`${tag}#${id}`);
      break;
    }

    const classAttr = typeof current.className === 'string' ? current.className : '';
    const classPart = classAttr
      .trim()
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((cls) => cls.replace(/[^\w-]/g, ''))
      .filter(Boolean)
      .map((cls) => `.${cls}`)
      .join('');

    const nth = getIndexWithinType(current);
    parts.unshift(`${tag}${classPart}:nth-of-type(${nth})`);

    if (tag === 'body') break;
    current = current.parentElement;
    depth += 1;
  }

  if (!parts.length) return null;
  return safeString(`path:${parts.join('>')}`, 300);
}

function getElementKey(el) {
  if (!(el instanceof Element)) return null;

  const id = safeString(el.id, 150);
  if (id) return `id:${id}`;

  const href =
    el.tagName && el.tagName.toLowerCase() === 'a'
      ? normalizeHref(el.getAttribute('href'))
      : null;
  if (href) return `href:${href}`;

  const name = safeString(el.getAttribute('name'), 150);
  if (name) return `name:${name}`;

  const ariaLabel = safeString(el.getAttribute('aria-label'), 200);
  if (ariaLabel) return `aria:${ariaLabel}`;

  const title = safeString(el.getAttribute('title'), 200);
  if (title) return `title:${title}`;

  const dataTestId = safeString(el.getAttribute('data-testid'), 150);
  if (dataTestId) return `testid:${dataTestId}`;

  const dataCy = safeString(el.getAttribute('data-cy'), 150);
  if (dataCy) return `cy:${dataCy}`;

  const dataQa = safeString(el.getAttribute('data-qa'), 150);
  if (dataQa) return `qa:${dataQa}`;

  const role = safeString(el.getAttribute('role'), 100);
  if (role) return `role:${role}`;

  return buildDomPathKey(el);
}

function shouldIgnoreTarget(target) {
  if (!target) return true;

  return !!(
    target.matches('input[type="password"], textarea, [contenteditable="true"]') ||
    target.closest('input[type="password"], textarea, [contenteditable="true"]') ||
    target.closest('[data-hymetry-ignore]')
  );
}

function isUnmodifiedPrimaryClick(event) {
  if (!event) return true;
  if (event.defaultPrevented) return false;
  if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return false;
  if (typeof event.button === 'number' && event.button !== 0) return false;
  return true;
}

function isNavigationalAnchorClick(target, event) {
  if (!(target instanceof HTMLAnchorElement)) return false;
  if (!isUnmodifiedPrimaryClick(event)) return false;

  const rawHref = target.getAttribute('href');
  if (!rawHref) return false;

  const normalizedHref = rawHref.trim().toLowerCase();
  if (!normalizedHref) return false;
  if (normalizedHref.startsWith('#')) return false;
  if (normalizedHref.startsWith('javascript:')) return false;

  const targetAttr = safeString(target.getAttribute('target'), 20);
  if (targetAttr && targetAttr.toLowerCase() !== '_self') {
    return false;
  }

  if (target.getAttribute('download') != null) return false;

  return true;
}

function getAnalyticsTabId() {
  const existing = safeString(safeGet(window.sessionStorage, TAB_ID_KEY), 100);
  if (existing) return existing;

  const nextId = createId();
  safeSet(window.sessionStorage, TAB_ID_KEY, nextId);
  return nextId;
}

export function startAnalytics(runtime, bootstrapEvent) {
  const clickQueue = [];
  const batchSize = Math.max(1, Number(runtime.config.analyticsBatchSize) || 10);
  const flushIntervalMs = Math.max(500, Number(runtime.config.analyticsFlushIntervalMs) || 5000);
  const passiveThrottleMs = Math.max(100, Number(runtime.config.analyticsPassiveThrottleMs) || 500);
  const orphanedAnalyticsMaxAgeMs = Math.max(flushIntervalMs * 2, ORPHANED_ANALYTICS_MAX_AGE_MS);
  const tabId = getAnalyticsTabId();
  const ownStorageKey = `${ANALYTICS_STORAGE_PREFIX}${tabId}`;
  let flushTimerId = null;
  let isSendingPending = false;
  const pendingPassiveEvents = {};
  const lastPassiveCaptureAt = {};

  for (let i = 0; i < PASSIVE_EVENTS.length; i++) {
    pendingPassiveEvents[PASSIVE_EVENTS[i].type] = null;
    lastPassiveCaptureAt[PASSIVE_EVENTS[i].type] = 0;
  }

  function getEventTimestampMs(eventData) {
    if (!eventData) return 0;

    if (typeof eventData.ts === 'number') {
      return eventData.ts;
    }

    const parsed = Date.parse(eventData.ts);
    return Number.isFinite(parsed) ? parsed : 0;
  }

  function pickNewestEvent(currentEvent, restoredEvent) {
    if (!currentEvent) return restoredEvent;
    if (!restoredEvent) return currentEvent;

    return getEventTimestampMs(currentEvent) >= getEventTimestampMs(restoredEvent)
      ? currentEvent
      : restoredEvent;
  }

  function normalizeStoredSnapshot(rawSnapshot) {
    if (!rawSnapshot || typeof rawSnapshot !== 'object') {
      return null;
    }

    const normalized = {
      clickEvents: Array.isArray(rawSnapshot.clickEvents) ? rawSnapshot.clickEvents : [],
      updatedAt:
        typeof rawSnapshot.updatedAt === 'number' && Number.isFinite(rawSnapshot.updatedAt)
          ? rawSnapshot.updatedAt
          : 0,
    };

    // A snapshot written before one of these types existed carries no field
    // for it, which reads as no observation rather than as a parse failure.
    for (let i = 0; i < PASSIVE_EVENTS.length; i++) {
      const storageKey = PASSIVE_EVENTS[i].storageKey;
      normalized[storageKey] = rawSnapshot[storageKey] || null;
    }

    return normalized;
  }

  function hasPassiveEvent(snapshot) {
    for (let i = 0; i < PASSIVE_EVENTS.length; i++) {
      if (snapshot[PASSIVE_EVENTS[i].storageKey]) return true;
    }

    return false;
  }

  function readStoredSnapshot(storageKey) {
    const raw = safeGet(window.localStorage, storageKey);
    if (!raw) return null;

    try {
      return normalizeStoredSnapshot(JSON.parse(raw));
    } catch (e) {
      safeRemove(window.localStorage, storageKey);
      return null;
    }
  }

  function writeStoredSnapshot(storageKey, snapshot) {
    const normalized = normalizeStoredSnapshot(snapshot);
    if (!normalized) return false;

    if (!normalized.clickEvents.length && !hasPassiveEvent(normalized)) {
      safeRemove(window.localStorage, storageKey);
      return true;
    }

    return safeSet(window.localStorage, storageKey, JSON.stringify(normalized));
  }

  function mergeStoredSnapshots(currentSnapshot, nextSnapshot) {
    const current = normalizeStoredSnapshot(currentSnapshot) || normalizeStoredSnapshot({});
    const next = normalizeStoredSnapshot(nextSnapshot) || normalizeStoredSnapshot({});
    const merged = {
      clickEvents: current.clickEvents.concat(next.clickEvents),
      updatedAt: Date.now(),
    };

    for (let i = 0; i < PASSIVE_EVENTS.length; i++) {
      const storageKey = PASSIVE_EVENTS[i].storageKey;
      merged[storageKey] = pickNewestEvent(current[storageKey], next[storageKey]);
    }

    return merged;
  }

  function listPendingStorageKeys() {
    const keys = [];

    try {
      const storage = window.localStorage;
      const total = storage.length || 0;

      for (let i = 0; i < total; i++) {
        const key = storage.key(i);
        if (typeof key === 'string' && key.startsWith(ANALYTICS_STORAGE_PREFIX)) {
          keys.push(key);
        }
      }
    } catch (e) {
      return [];
    }

    return keys;
  }

  function createBaseEvent(type) {
    const identity = runtime.getIdentity();

    return {
      type,
      ts: nowIso(),
      app: runtime.config.app,
      visitor_id: runtime.visitorId,
      user_id: identity.user.id ?? null,
      company_id: identity.company.id ?? null,
      user: {
        id: identity.user.id ?? null,
        traits: identity.user.traits || {},
      },
      company: {
        id: identity.company.id ?? null,
        traits: identity.company.traits || {},
      },
      page: getPageContext(),
    };
  }

  function createClickEvent(target) {
    const elementKey = safeString(getReadableElementName(target), 300);

    return {
      ...createBaseEvent('click'),
      elementKey,
    };
  }

  function createPassiveEvent(type) {
    return createBaseEvent(type);
  }

  function sendPayload(payload, useBeacon) {
    const json = JSON.stringify(payload);

    return fetch(runtime.config.analyticsEndpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: json,
      keepalive: !!useBeacon,
    }).then((response) => {
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
    });
  }

  function buildQueueSnapshot() {
    const clickEvents = clickQueue.slice();
    const snapshot = {
      clickEvents,
      updatedAt: Date.now(),
    };
    let carriesPassiveEvent = false;

    for (let i = 0; i < PASSIVE_EVENTS.length; i++) {
      const pending = pendingPassiveEvents[PASSIVE_EVENTS[i].type];
      snapshot[PASSIVE_EVENTS[i].storageKey] = pending;
      if (pending) carriesPassiveEvent = true;
    }

    if (!clickEvents.length && !carriesPassiveEvent) return null;

    clickQueue.length = 0;
    for (let i = 0; i < PASSIVE_EVENTS.length; i++) {
      pendingPassiveEvents[PASSIVE_EVENTS[i].type] = null;
    }

    return snapshot;
  }

  function restoreFlushSnapshot(snapshot) {
    if (!snapshot) return;

    for (let i = snapshot.clickEvents.length - 1; i >= 0; i--) {
      clickQueue.unshift(snapshot.clickEvents[i]);
    }

    for (let i = 0; i < PASSIVE_EVENTS.length; i++) {
      const type = PASSIVE_EVENTS[i].type;
      pendingPassiveEvents[type] = pickNewestEvent(
        pendingPassiveEvents[type],
        snapshot[PASSIVE_EVENTS[i].storageKey],
      );
    }
  }

  function persistSnapshotToStorage(snapshot, storageKey) {
    const existingSnapshot = readStoredSnapshot(storageKey);
    const mergedSnapshot = mergeStoredSnapshots(existingSnapshot, snapshot);

    if (!writeStoredSnapshot(storageKey, mergedSnapshot)) {
      throw new Error('analytics localStorage write failed');
    }
  }

  function persistQueueToStorage() {
    const snapshot = buildQueueSnapshot();
    if (!snapshot) return;

    try {
      persistSnapshotToStorage(snapshot, ownStorageKey);
    } catch (e) {
      restoreFlushSnapshot(snapshot);
      runtime.log('analytics persist failed');
    }
  }

  function buildBatchToSend(snapshot) {
    const normalized = normalizeStoredSnapshot(snapshot);
    if (!normalized) return [];

    const batchToSend = normalized.clickEvents.slice();
    for (let i = 0; i < PASSIVE_EVENTS.length; i++) {
      const passiveRecord = normalized[PASSIVE_EVENTS[i].storageKey];
      if (passiveRecord) batchToSend.push(passiveRecord);
    }
    batchToSend.sort((first, second) => getEventTimestampMs(first) - getEventTimestampMs(second));
    return batchToSend;
  }

  function claimStoredSnapshot(storageKey) {
    const snapshot = readStoredSnapshot(storageKey);
    if (!snapshot) {
      safeRemove(window.localStorage, storageKey);
      return null;
    }

    const batchToSend = buildBatchToSend(snapshot);
    if (!batchToSend.length) {
      safeRemove(window.localStorage, storageKey);
      return null;
    }

    safeRemove(window.localStorage, storageKey);

    return {
      storageKey,
      snapshot,
      batchToSend,
    };
  }

  function restoreClaimedSnapshot(claimedSnapshot) {
    if (!claimedSnapshot) return;

    try {
      persistSnapshotToStorage(claimedSnapshot.snapshot, claimedSnapshot.storageKey);
    } catch (e) {
      runtime.log('analytics storage restore failed');
    }
  }

  function isOrphanedStorageKey(storageKey, snapshot) {
    if (storageKey === ownStorageKey) return false;
    if (!snapshot) return false;
    return Date.now() - snapshot.updatedAt >= orphanedAnalyticsMaxAgeMs;
  }

  async function processPendingStorage() {
    if (isSendingPending) return;
    isSendingPending = true;

    try {
      const pendingKeys = [ownStorageKey];
      const knownKeys = new Set(pendingKeys);
      const storageKeys = listPendingStorageKeys();

      for (let i = 0; i < storageKeys.length; i++) {
        const storageKey = storageKeys[i];
        if (knownKeys.has(storageKey)) continue;

        const snapshot = readStoredSnapshot(storageKey);
        if (isOrphanedStorageKey(storageKey, snapshot)) {
          pendingKeys.push(storageKey);
          knownKeys.add(storageKey);
        }
      }

      for (let i = 0; i < pendingKeys.length; i++) {
        const claimedSnapshot = claimStoredSnapshot(pendingKeys[i]);
        if (!claimedSnapshot) continue;

        const payload = {
          api_key: runtime.config.apiKey,
          app: runtime.config.app,
          sentAt: nowIso(),
          visitor_id: runtime.visitorId,
          batch: claimedSnapshot.batchToSend,
        };

        try {
          await sendPayload(payload, false);
        } catch (e) {
          restoreClaimedSnapshot(claimedSnapshot);
          runtime.log('analytics send failed');
        }
      }
    } finally {
      isSendingPending = false;
    }
  }

  function flushCycle() {
    persistQueueToStorage();
    processPendingStorage();
  }

  function enqueueClickEvent(eventData, options) {
    clickQueue.push(eventData);
    if (options && options.flushImmediately) {
      persistQueueToStorage();
      return;
    }

    if (clickQueue.length >= batchSize) {
      flushCycle();
    }
  }

  function capturePassiveEvent(type) {
    const now = Date.now();
    if (now - lastPassiveCaptureAt[type] < passiveThrottleMs) return;

    lastPassiveCaptureAt[type] = now;
    pendingPassiveEvents[type] = createPassiveEvent(type);
  }

  function handleScroll() {
    capturePassiveEvent('scroll');
  }

  function handleMouseMove() {
    capturePassiveEvent('mouse_move');
  }

  // Records that a key went down and nothing else: no key identity, no
  // modifier state, no target, no value.  Typing is the one signal a visitor
  // working through a long form produces, and it produces neither a click nor
  // a scroll, so without this such a visitor reads as idle.
  function handleKeyPress() {
    capturePassiveEvent('key_press');
  }

  // The touch counterpart of pointer movement, and the reason `touchstart` is
  // not recorded: a touch device synthesizes a click after a tap, so taps
  // already arrive as clicks and a start-of-touch record would store every one
  // of them twice for nothing.  Movement is different.  A drag that neither
  // clicks nor scrolls -- panning a map, drawing on a canvas, working a custom
  // slider -- leaves no event at all today and so reads as idle time.  A
  // drag that does scroll is already covered by `scroll`; this adds nothing
  // there and costs nothing either, being capped at one record per flush.
  function handleTouchMove() {
    capturePassiveEvent('touch_move');
  }

  function handleClick(event) {
    const eventTarget = getEventTargetElement(event);
    const target = pickClickTarget(eventTarget);
    if (!target || shouldIgnoreTarget(target)) return;

    enqueueClickEvent(createClickEvent(target), {
      flushImmediately: isNavigationalAnchorClick(target, event),
    });
  }

  function captureBootstrapActivity(event) {
    if (!event || !event.type) return;

    if (event.type === 'scroll') {
      handleScroll();
      return;
    }

    if (event.type === 'click') {
      handleClick(event);
      return;
    }

    if (event.type === 'keydown') {
      handleKeyPress();
      return;
    }

    if (event.type === 'mousemove') {
      handleMouseMove();
    }

    // A bootstrapping `touchstart` records nothing, deliberately: see
    // handleTouchMove.  The `touchmove` that follows a real gesture reaches
    // the live listener below.
  }

  function scheduleFlush() {
    if (flushTimerId) clearInterval(flushTimerId);
    flushTimerId = setInterval(() => flushCycle(), flushIntervalMs);
  }

  document.addEventListener('click', handleClick, true);
  document.addEventListener('scroll', handleScroll, true);
  document.addEventListener('mousemove', handleMouseMove, { passive: true });
  document.addEventListener('keydown', handleKeyPress, { passive: true, capture: true });
  document.addEventListener('touchmove', handleTouchMove, { passive: true, capture: true });
  window.addEventListener('scroll', handleScroll, { passive: true });
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') {
      persistQueueToStorage();
    }
  });
  window.addEventListener('pagehide', () => persistQueueToStorage());
  scheduleFlush();
  captureBootstrapActivity(bootstrapEvent);

  runtime.log('analytics started');

  return {
    flush() {
      flushCycle();
    },
    onIdentify() {},
  };
}
