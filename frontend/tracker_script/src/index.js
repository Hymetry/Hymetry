import { STARTING_EVENTS, createDeferredApiBridge, createRuntime } from './init';
import { startRecording } from './recording';
import { hasPendingAnalyticsStorage, startAnalytics } from './analytics';

(function () {
  let initialized = false;
  let runtime = null;
  let hasLoggedStart = false;
  let appliedSettingsIdentity = false;
  const apiBridge = createDeferredApiBridge();
  const activeModules = {
    recording: null,
    analytics: null,
  };

  function getBootstrapTarget(eventName) {
    if (eventName === 'scroll' || eventName === 'click') {
      return document;
    }

    return window;
  }

  function getBootstrapListenerOptions(eventName) {
    if (eventName === 'scroll' || eventName === 'click') {
      return { once: true, capture: true };
    }

    return { once: true };
  }

  function removeBootstrapListener(eventName, handler) {
    const target = getBootstrapTarget(eventName);
    const options = eventName === 'scroll' || eventName === 'click' ? true : undefined;
    target.removeEventListener(eventName, handler, options);
  }

  function flushAll() {
    activeModules.recording?.flush?.();
    activeModules.analytics?.flush?.();
  }

  function applySettingsIdentity(nextRuntime) {
    if (appliedSettingsIdentity) return;
    appliedSettingsIdentity = true;

    try {
      const payload = window.hymetrySettings?.identify;
      if (!payload) {
        if (nextRuntime.config.captureModes.analytics) {
          console.error(
            'Hymetry: identity is not configured. Add window.hymetrySettings.identify before loading main.js.',
          );
        }
        return;
      }

      nextRuntime.setIdentity(payload);
    } catch (error) {
      console.warn('Hymetry identify failed', error);
    }
  }

  function ensureRuntime() {
    if (runtime) return runtime;

    runtime = createRuntime();
    if (!runtime) return null;

    applySettingsIdentity(runtime);

    apiBridge.bind({
      identify(payload) {
        applyIdentity(payload);
      },
      flush() {
        flushAll();
      },
    });

    return runtime;
  }

  function logStarted() {
    if (hasLoggedStart) return;
    hasLoggedStart = true;
    console.info('Hymetry started');
  }

  function applyIdentity(payload) {
    const nextRuntime = ensureRuntime();
    if (!nextRuntime) return;

    nextRuntime.setIdentity(payload || {});
    activeModules.analytics?.onIdentify?.();
  }

  function startRecordingModule() {
    if (activeModules.recording) return;

    const nextRuntime = ensureRuntime();
    if (!nextRuntime || !nextRuntime.config.captureModes.recording) return;

    activeModules.recording = startRecording(nextRuntime);
    logStarted();
  }

  function startAnalyticsModule(event) {
    if (activeModules.analytics) return;

    const nextRuntime = ensureRuntime();
    if (!nextRuntime || !nextRuntime.config.captureModes.analytics) return;

    activeModules.analytics = startAnalytics(nextRuntime, event);
    logStarted();
  }

  function bootstrap(event) {
    if (initialized) return;
    initialized = true;

    for (let i = 0; i < STARTING_EVENTS.length; i++) {
      removeBootstrapListener(STARTING_EVENTS[i], bootstrap);
    }

    startRecordingModule();
    startAnalyticsModule(event);
  }

  for (let i = 0; i < STARTING_EVENTS.length; i++) {
    const eventName = STARTING_EVENTS[i];
    getBootstrapTarget(eventName).addEventListener(
      eventName,
      bootstrap,
      getBootstrapListenerOptions(eventName),
    );
  }

  if (hasPendingAnalyticsStorage()) {
    startAnalyticsModule(null);
  }
})();
