import { createId } from './init';

const TAB_ID_KEY = 'tracker_tab_id';
const BATCH_INTERVAL = 5000;
const MAX_BATCH_SIZE = 100;
const CHANNEL_NAME = 'ppp_tab_id_claim';
const HANDSHAKE_TIMEOUT = 300;
const PENDING_BATCHES_KEY = 'tracker_pending_batches';

function sendRecordingRequest(endpoint, payload) {
  return fetch(endpoint, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: payload,
  });
}

export function startRecording(runtime) {
  let stopFn = null;
  let intervalId = null;
  let hasAuthError = false;
  let isRecording = false;
  let tabId = null;
  let globalEventBuffer = [];
  const who = createId();

  function getPrivacySafePageUrl() {
    try {
      const url = new URL(window.location.href);
      url.search = '';
      url.hash = '';
      return url.toString();
    } catch (e) {
      return String(window.location.href || '').split('#', 1)[0].split('?', 1)[0];
    }
  }

  function buildPayload(events, isFinalBatch) {
    const batchTimestamp = new Date().toISOString();
    const pageUrl = getPrivacySafePageUrl();
    const pageTitle = document.title || pageUrl;

    return JSON.stringify({
      api_key: runtime.config.apiKey,
      tab_id: tabId,
      visitor_id: runtime.visitorId,
      event_data: {
        type: 'batch',
        events: events,
        batch_size: events.length,
        batch_timestamp: batchTimestamp,
        is_final_batch: !!isFinalBatch,
        page_url: pageUrl,
        page_title: pageTitle,
      },
      page_url: pageUrl,
      page_title: pageTitle,
    });
  }

  function rememberPendingBatch(payload) {
    try {
      const pendingBatches = JSON.parse(localStorage.getItem(PENDING_BATCHES_KEY) || '[]');
      pendingBatches.push({
        payload: payload,
        timestamp: Date.now(),
        url: getPrivacySafePageUrl(),
      });
      if (pendingBatches.length > 10) {
        pendingBatches.splice(0, pendingBatches.length - 10);
      }
      localStorage.setItem(PENDING_BATCHES_KEY, JSON.stringify(pendingBatches));
    } catch (e) {
      // ignore localStorage errors
    }
  }

  function sendBatch(events, isFinalBatch) {
    if (!events || !events.length || hasAuthError) return;

    const payload = buildPayload(events, isFinalBatch);
    const endpoint = runtime.config.recordingEndpoint;

    if (isFinalBatch) {
      if (navigator.sendBeacon) {
        const sent = navigator.sendBeacon(endpoint, payload);
        if (sent) return;
      }

      try {
        const xhr = new XMLHttpRequest();
        xhr.open('POST', endpoint, false);
        xhr.setRequestHeader('Content-Type', 'application/json');
        xhr.send(payload);
        if (xhr.status === 200) return;
      } catch (e) {
        // fall through to storage fallback
      }

      rememberPendingBatch(payload);
      return;
    }

    sendRecordingRequest(endpoint, payload)
      .then((response) => {
        if (!response.ok) {
          if (response.status === 403) {
            handleAuthError();
            return;
          }
          throw new Error(`HTTP ${response.status}`);
        }
      })
      .catch(() => {
        // If network request fails we currently drop this batch,
        // mirroring previous tracker behavior.
      });
  }

  function flushRemaining(isFinalBatch) {
    if (!globalEventBuffer.length || hasAuthError) return;
    const finalBatch = globalEventBuffer.splice(0, globalEventBuffer.length);
    sendBatch(finalBatch, !!isFinalBatch);
  }

  function sendPendingBatches() {
    try {
      const pendingBatches = JSON.parse(localStorage.getItem(PENDING_BATCHES_KEY) || '[]');
      if (!pendingBatches.length) return;

      for (let i = 0; i < pendingBatches.length; i++) {
        sendRecordingRequest(runtime.config.recordingEndpoint, pendingBatches[i].payload).catch(() => {
          // Keep going through pending list; failed entries are dropped.
        });
      }
      localStorage.removeItem(PENDING_BATCHES_KEY);
    } catch (e) {
      localStorage.removeItem(PENDING_BATCHES_KEY);
    }
  }

  function handleAuthError() {
    if (hasAuthError) return;
    hasAuthError = true;

    if (stopFn) {
      stopFn();
      stopFn = null;
    }
    isRecording = false;
    globalEventBuffer = [];

    if (intervalId) {
      clearInterval(intervalId);
      intervalId = null;
    }

    console.info('Hymetry: Access denied.');
  }

  function claimTabId() {
    return new Promise((resolve) => {
      const channel = new BroadcastChannel(CHANNEL_NAME);
      let candidateId = sessionStorage.getItem(TAB_ID_KEY) || createId();
      let vetoed = false;

      const send = (phase, target) => {
        channel.postMessage({ phase, id: candidateId, who, target });
      };

      channel.onmessage = (event) => {
        const data = event.data || {};
        if (data.who === who) return;
        if (data.id !== candidateId) return;
        if (data.target && data.target !== who) return;

        if (data.phase === 'claim') {
          send('veto', data.who);
        } else if (data.phase === 'veto') {
          vetoed = true;
        }
      };

      const attempt = () => {
        vetoed = false;
        send('claim');
        setTimeout(() => {
          if (vetoed) {
            candidateId = createId();
            attempt();
            return;
          }

          setTimeout(() => {
            sessionStorage.setItem(TAB_ID_KEY, candidateId);
          }, 500);
          resolve(candidateId);
        }, HANDSHAKE_TIMEOUT);
      };

      attempt();
    });
  }

  async function initializeIds() {
    try {
      tabId = await claimTabId();
    } catch (e) {
      tabId = sessionStorage.getItem(TAB_ID_KEY);
      if (!tabId) {
        tabId = createId();
        sessionStorage.setItem(TAB_ID_KEY, tabId);
      }
    }
  }

  function attachUnloadGuards() {
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'hidden') {
        flushRemaining(true);
      }
    });
    // `unload`/`beforeunload` can be blocked by modern Permissions Policy.
    // `visibilitychange` + `pagehide` are the reliable cross-browser path.
    window.addEventListener('pagehide', () => flushRemaining(true));
  }

  function startRrwebRecording() {
    if (isRecording || hasAuthError) return;
    if (!window.rrweb || typeof window.rrweb.record !== 'function') return;

    stopFn = window.rrweb.record({
      emit(event) {
        if (!hasAuthError) {
          globalEventBuffer.push(event);
        }
      },
      inlineStylesheet: false,
      recordCanvas: false,
      collectFonts: false,
      recordDOM: true,
      sampling: {
        mouseInteraction: {
          MouseUp: true,
          MouseDown: true,
          Click: true,
          ContextMenu: false,
          DblClick: true,
          Focus: false,
          Blur: false,
          TouchStart: true,
          TouchEnd: true,
        },
        scroll: true,
        input: 5,
        mousemove: 50,
      },
    });

    isRecording = true;
    intervalId = setInterval(() => {
      if (!globalEventBuffer.length || hasAuthError) return;
      const batchSize = Math.min(globalEventBuffer.length, MAX_BATCH_SIZE);
      const currentBatch = globalEventBuffer.splice(0, batchSize);
      sendBatch(currentBatch, false);
    }, BATCH_INTERVAL);
  }

  function loadRrwebAndStart() {
    if (!document.querySelector('script[src*="lib.min.js"]')) {
      const scriptEl = document.createElement('script');
      scriptEl.src = `${runtime.config.libUrl}/lib.min.js`;
      scriptEl.onload = () => startRrwebRecordingWhenPageIsReady();
      scriptEl.onerror = () => {
        runtime.log('rrweb library failed to load');
      };
      document.head.appendChild(scriptEl);
      return;
    }

    startRrwebRecordingWhenPageIsReady();
  }

  function startRrwebRecordingWhenPageIsReady() {
    if (document.readyState === 'complete') {
      startRrwebRecording();
      return;
    }

    window.addEventListener('load', startRrwebRecording, { once: true });
  }

  (async function initialize() {
    await initializeIds();
    sendPendingBatches();
    loadRrwebAndStart();
    attachUnloadGuards();
  })();

  return {
    flush() {
      flushRemaining(false);
    },
    stop() {
      if (intervalId) clearInterval(intervalId);
      intervalId = null;
      if (stopFn) stopFn();
      stopFn = null;
      isRecording = false;
    },
  };
}
