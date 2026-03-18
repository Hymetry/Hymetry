(function () {

const startingEvents = ['mousemove', 'scroll', 'touchstart', 'keydown']
let initialized = false;

const mainFunc = function() {
    if (initialized) return;
    initialized = true;
    for (let startingEvent of startingEvents) {
        window.removeEventListener(startingEvent, mainFunc);
    }
    // Use a more robust initialization check
    const script = document.querySelector('script[data-api-key]');
    const API_KEY = script?.dataset.apiKey;
    if (!API_KEY) {
      // Optionally log error in dev
      console.error('Hymetry: data-api-key not set in <script> definition')
      return;
    } else {
      console.info('Hymetry started')
    }
    const TAB_ID_KEY = 'tracker_tab_id';
    const VISITOR_ID_KEY = 'tracker_visitor_id';
    const BATCH_INTERVAL = 5000;  // Send events every 5 seconds
    const MAX_BATCH_SIZE = 100;   // Maximum number of events per batch
    const CHANNEL_NAME = 'ppp_tab_id_claim';
    const HANDSHAKE_TIMEOUT = 300; // ms to wait for veto after claim broadcast

    // Configuration - auto-detect from script src or use data attributes
    function getBaseUrl() {
      // Check for explicit data attribute override
      if (script?.dataset.apiUrl) {
        return script.dataset.apiUrl.replace(/\/$/, '');
      }
      // Auto-detect from script src
      if (script?.src) {
        try {
          const url = new URL(script.src);
          return `${url.protocol}//${url.host}`;
        } catch (e) {}
      }
      // Fall back to current origin
      return window.location.origin;
    }
    function getLibUrl() {
      // Check for explicit data attribute override
      if (script?.dataset.libUrl) {
        return script.dataset.libUrl.replace(/\/$/, '');
      }

      const url = new URL(script.src);
      const path = url.pathname.replace(/\/[^\/]*$/, '');
      return getBaseUrl() + path;
    }
    const TRACKER_URL = getBaseUrl();
    const LIB_URL = getLibUrl();

    let stopFn = null;
    let batchTimeout = null;
    let currentBatch = [];
    
    // Global buffer to store all events
    let globalEventBuffer = [];

    let isRecording = false;

    let tabId = null;
    let visitorId = null;
    let hasAuthError = false;
    let who = crypto.randomUUID(); // Unique identifier for this tab instance

    initializeTracker();

    // Initialize IDs and setup
    function initializeTracker() {
        (async function() {
            await initializeIds();

            // Send any pending batches from previous sessions
            sendPendingBatches();

            // Wait for user to move mouse before starting recording
            //document.addEventListener('mousemove', loadRrwebAndStartRecording, { once: true });
            loadRrwebAndStartRecording();
        })();
    }

    function loadRrwebAndStartRecording() {
        // Load rrweb if not already loaded
        if (!document.querySelector('script[src*="lib.min.js"]')) {
            const script = document.createElement('script');
            script.src = `${LIB_URL}/lib.min.js`;
            script.onload = () => {
                if (typeof rrweb !== 'undefined') {
                    startRecording();
                }
            };
            script.onerror = (error) => {};
            document.head.appendChild(script);
        } else if (typeof rrweb !== 'undefined') {
            startRecording();
        }
    }

    function generateRandomId() {
        // Generate a proper UUID v4 format
        return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
            const r = Math.random() * 16 | 0;
            const v = c === 'x' ? r : (r & 0x3 | 0x8);
            return v.toString(16);
        });
    }

    async function claimTabId() {
          return new Promise((resolve) => {
            const channel = new BroadcastChannel(CHANNEL_NAME);
            let candidateId = sessionStorage.getItem(TAB_ID_KEY) || crypto.randomUUID();
            let vetoed = false;

            const send = (phase, target = undefined) => {
              channel.postMessage({ phase, id: candidateId, who, target });
            };

            const onMessage = (e) => {
              const { phase, id, who: otherWho, target } = e.data || {};
              if (otherWho === who) return; // ignore own messages
              if (id !== candidateId) return; // only care about current candidate id

              // if a message is targeted, ensure it's for us
              if (target && target !== who) return;

              switch (phase) {
                case 'claim':
                  // Another tab is claiming the same id we want; veto it.
                  send('veto', otherWho);
                  break;
                case 'veto':
                  // We have been vetoed; mark flag
                  vetoed = true;
                  break;
                default:
                  break;
              }
            };

            channel.onmessage = onMessage;

            const attempt = () => {
              vetoed = false;
              // broadcast claim
              send('claim');

              // wait for possible veto
              setTimeout(() => {
                if (vetoed) {
                  // generate new id and retry
                  candidateId = crypto.randomUUID();
                  attempt();
                } else {
                  // no veto received: we own the id
                  setTimeout(() => {
                    sessionStorage.setItem(TAB_ID_KEY, candidateId);
                    }, 500);

                 // channel.removeEventListener('message', onMessage);
                 // channel.close();
                  resolve(candidateId);
                }
              }, HANDSHAKE_TIMEOUT);
            };

            attempt();
          });
    }
    async function initializeIds() {
        // Initialize tab_id using BroadcastChannel for reliable uniqueness
        try {
            tabId = await claimTabId();
        } catch (error) {
            // Fallback to original method if BroadcastChannel fails
            tabId = sessionStorage.getItem(TAB_ID_KEY);
            if (!tabId) {
                tabId = generateRandomId();
                sessionStorage.setItem(TAB_ID_KEY, tabId);
            }
        }

        // Initialize visitor_id (persistent across sessions, stored in localStorage)
        visitorId = localStorage.getItem(VISITOR_ID_KEY);
        if (!visitorId) {
            visitorId = generateRandomId();
            localStorage.setItem(VISITOR_ID_KEY, visitorId);
        }
    }

    function sendBatch(events, isFinalBatch = false) {
        if (!events || !events.length) return;

        const batchSize = events.length;
        const batchTimestamp = new Date().toISOString();
        
        // Always get current page URL and title
        const pageUrl = window.location.href;
        const pageTitle = document.title || pageUrl;  // Use URL as title if no title

        // Prepare batch data
        const batchData = {
            type: 'batch',
            events: events,
            batch_size: batchSize,
            batch_timestamp: batchTimestamp,
            is_final_batch: isFinalBatch,
            page_url: pageUrl,
            page_title: pageTitle
        };

        const payload = JSON.stringify({
            api_key: API_KEY,
            tab_id: tabId,
            visitor_id: visitorId,
            event_data: batchData,
            page_url: pageUrl,
            page_title: pageTitle
        });

        // For final batches, try multiple strategies
        if (isFinalBatch) {
            // Strategy 1: Try sendBeacon first (most reliable for page unload)
            if (navigator.sendBeacon) {
                const success = navigator.sendBeacon(`${TRACKER_URL}/tracker/api/record-event/`, payload);
                if (success) return;
            }
            
            // Strategy 2: Try synchronous XMLHttpRequest (works in some browsers during unload)
            try {
                const xhr = new XMLHttpRequest();
                xhr.open('POST', `${TRACKER_URL}/tracker/api/record-event/`, false); // synchronous
                xhr.setRequestHeader('Content-Type', 'application/json');
                xhr.send(payload);
                if (xhr.status === 200) return;
            } catch (e) {
                // Fall through to next strategy
            }
            
            // Strategy 3: Store in localStorage as fallback for next page load
            try {
                const pendingBatches = JSON.parse(localStorage.getItem('tracker_pending_batches') || '[]');
                pendingBatches.push({
                    payload: payload,
                    timestamp: Date.now(),
                    url: pageUrl
                });
                // Keep only last 10 batches to avoid localStorage overflow
                if (pendingBatches.length > 10) {
                    pendingBatches.splice(0, pendingBatches.length - 10);
                }
                localStorage.setItem('tracker_pending_batches', JSON.stringify(pendingBatches));
            } catch (e) {
                // If localStorage fails, we can't do much more
            }
            
            return;
        }

        // Use fetch for regular batches
        fetch(`${TRACKER_URL}/tracker/api/record-event/`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: payload
        })
        .then(response => {
            if (!response.ok) {
                if (response.status === 403) {
                    handleAuthError();
                    return;
                }
                throw new Error(`HTTP error! status: ${response.statusText}`);
            }
            return response.json();
        })
        .then(data => {
            // Handle any response data if needed
        })
        .catch(error => {
            // Warn about data not being sent and remove failed events from global buffer
            // Events were already removed from global buffer when creating the batch,
            // so we don't need to remove them again
        });
    }

    function sendPendingBatches() {
        try {
            const pendingBatches = JSON.parse(localStorage.getItem('tracker_pending_batches') || '[]');
            if (pendingBatches.length > 0) {
                // Send each pending batch
                pendingBatches.forEach(batch => {
                    fetch(`${TRACKER_URL}/tracker/api/record-event/`, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                        },
                        body: batch.payload
                    }).catch(error => {

                    });
                });
                
                // Clear pending batches after sending
                localStorage.removeItem('tracker_pending_batches');
            }
        } catch (e) {
            // Clear corrupted data
            localStorage.removeItem('tracker_pending_batches');
        }
    }

    function handleAuthError() {
        if (hasAuthError) return; // Prevent multiple messages
        
        hasAuthError = true;

        // Stop recording if active
        if (stopFn) {
            stopFn();
            isRecording = false;
        }
        
        // Clear any pending batches
        globalEventBuffer = [];
        if (batchTimeout) {
            clearTimeout(batchTimeout);
        }
        
        console.info('Hymetry: Access denied.');
    }

    function startRecording() {
        if (isRecording || hasAuthError) return;
        
        // Initialize rrweb
        stopFn = rrweb.record({
            emit(event) {
                if (hasAuthError) return; // Stop recording events if auth error             
                globalEventBuffer.push(event);
            },
            inlineStylesheet: true,
            // Capture DOM snapshot + typing, clicks, and mouse movements
            recordCanvas: false,
            collectFonts: false,
            // Enable DOM snapshots to show webpage content
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
                scroll: true, // Disable scroll events
                input: 5,   // Record input events every 5ms (typing)
                mousemove: 50, // Record mouse movements every 1000ms
            },
        });
        isRecording = true;
        setInterval(() => {
            if (globalEventBuffer.length > 0 && !hasAuthError) {
                // Take up to MAX_BATCH_SIZE events from global buffer
                const batchSize = Math.min(globalEventBuffer.length, MAX_BATCH_SIZE);
                currentBatch = globalEventBuffer.splice(0, batchSize);
                sendBatch(currentBatch);
            }
        }, BATCH_INTERVAL);
        
        // Multiple strategies for reliable data sending on page unload
        document.addEventListener('visibilitychange', () => {
            if (document.visibilityState === 'hidden') {
                if (globalEventBuffer.length > 0 && !hasAuthError) {
                    // Take all remaining events from global buffer
                    const finalBatch = globalEventBuffer.splice(0, globalEventBuffer.length);
                    sendBatch(finalBatch, true);
                }
            } else {
              //const the_snapshot = rrwebSnapshot.snapshot(document);
              const the_snapshot = rrweb.record.takeFullSnapshot(true);
              //const snapshot_event = {type:2, timestamp: Date.now(), data: {initialOffset: {left: 0, top: 100}, node: the_snapshot }}
              //globalEventBuffer.push(snapshot_event);
            }

        });
        
        // Use multiple event listeners for maximum reliability
        window.addEventListener('beforeunload', () => {
            if (globalEventBuffer.length > 0 && !hasAuthError) {
                const finalBatch = globalEventBuffer.splice(0, globalEventBuffer.length);
                sendBatch(finalBatch, true);
            }
        });
        
        window.addEventListener('unload', () => {
            if (globalEventBuffer.length > 0 && !hasAuthError) {
                const finalBatch = globalEventBuffer.splice(0, globalEventBuffer.length);
                sendBatch(finalBatch, true);
            }
        });
        
        window.addEventListener('pagehide', () => {
            if (globalEventBuffer.length > 0 && !hasAuthError) {
                const finalBatch = globalEventBuffer.splice(0, globalEventBuffer.length);
                sendBatch(finalBatch, true);
            }
        });
        
    }
};

for (let startingEvent of startingEvents) {
    window.addEventListener(startingEvent, mainFunc, { once: true });
}
})()