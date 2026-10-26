/* Map location comes from the Library's USB receiver, never the client phone.
 * Installed before the ZIM's scripts, including MapLibre and driving mode.
 */
(function (root) {
  'use strict';
  const MAX_FIX_AGE = 10;

  function positionFromSnapshot(data, now = Date.now()) {
    if (!data || data.fix_valid !== true || data.connected !== true ||
        data.gps_detected !== true ||
        !Number.isFinite(data.fix_age_seconds) || data.fix_age_seconds < 0 ||
        data.fix_age_seconds > MAX_FIX_AGE ||
        !Number.isFinite(data.latitude) || Math.abs(data.latitude) > 90 ||
        !Number.isFinite(data.longitude) || Math.abs(data.longitude) > 180) return null;
    return {
      timestamp: now - data.fix_age_seconds * 1000,
      coords: {
        latitude: data.latitude, longitude: data.longitude,
        // The NMEA API has no measured horizontal uncertainty. This is a
        // display estimate, not an HDOP-to-metres conversion or guarantee.
        accuracy: 100,
        altitude: Number.isFinite(data.altitude_m) ? data.altitude_m : null,
        altitudeAccuracy: null, heading: null, speed: null
      }
    };
  }

  function createAdapter({ fetch, onStatus = () => {}, setTimer = setTimeout,
                           clearTimer = clearTimeout, now = Date.now }) {
    const watchers = new Map();
    const pending = new Map();
    let nextId = 1;
    let timer = null;
    let running = false;
    let lastMessage = 'Waiting for a current Library GPS fix.';
    const error = (code, message) => ({ code, message, PERMISSION_DENIED: 1,
                                      POSITION_UNAVAILABLE: 2, TIMEOUT: 3 });
    // Keep one caller's exception from interrupting the other subscribers.
    function notify(callback, value) {
      if (typeof callback !== 'function') return;
      try { callback(value); } catch (err) { console.error(err); }
    }
    async function poll() {
      const controller = new AbortController();
      const timeout = setTimer(() => controller.abort(), 3500);
      try {
        const response = await fetch('/api/gps', { cache: 'no-store', signal: controller.signal });
        if (!response.ok) throw new Error('Library GPS service is unavailable.');
        const data = await response.json();
        const position = positionFromSnapshot(data, now());
        lastMessage = typeof data.message === 'string' ? data.message : 'Waiting for a current Library GPS fix.';
        onStatus(position ? 'Library GPS · live' : `Library GPS · ${lastMessage}`, Boolean(position));
        if (position) {
          for (const [id, entry] of pending) {
            clearTimer(entry.timer);
            pending.delete(id);
            notify(entry.success, position);
          }
          for (const entry of watchers.values()) notify(entry.success, position);
        } else {
          for (const entry of watchers.values()) notify(entry.failure, error(2, lastMessage));
        }
      } catch (err) {
        lastMessage = 'Library GPS service is unavailable.';
        onStatus(`Library GPS · ${lastMessage}`, false);
        for (const entry of watchers.values()) notify(entry.failure, error(2, lastMessage));
      } finally {
        clearTimer(timeout);
        if (running) timer = setTimer(poll, 1000);
      }
    }
    const api = {
      getCurrentPosition(success, failure, options = {}) {
        if (typeof success !== 'function') throw new TypeError('A success callback is required');
        const id = nextId++;
        const duration = typeof options.timeout === 'number' && options.timeout >= 0 ? options.timeout : 15000;
        const entry = { success, failure, timer: null };
        pending.set(id, entry);
        if (Number.isFinite(duration)) entry.timer = setTimer(() => {
          if (pending.delete(id)) notify(failure, error(3, lastMessage));
        }, duration);
        start();
      },
      watchPosition(success, failure) {
        if (typeof success !== 'function') throw new TypeError('A success callback is required');
        const id = nextId++;
        watchers.set(id, { success, failure });
        start();
        return id;
      },
      clearWatch(id) { watchers.delete(id); }
    };
    function start() {
      if (running) return;
      running = true;
      void poll();
    }
    function stop() {
      running = false;
      clearTimer(timer);
      for (const entry of pending.values()) clearTimer(entry.timer);
      pending.clear();
      watchers.clear();
    }
    return { api, start, stop, poll };
  }

  function install(navigator, api) {
    Object.defineProperty(navigator, 'geolocation', { configurable: true, value: api });
    // MapLibre checks permission before enabling its location button. This
    // permission describes the appliance feed, not native device geolocation.
    if (navigator.permissions && navigator.permissions.query) {
      const query = navigator.permissions.query.bind(navigator.permissions);
      Object.defineProperty(navigator.permissions, 'query', {
        configurable: true,
        value(descriptor) {
          if (descriptor && descriptor.name === 'geolocation') {
            const status = new EventTarget();
            Object.defineProperty(status, 'state', { value: 'granted' });
            status.onchange = null;
            return Promise.resolve(status);
          }
          return query(descriptor);
        }
      });
    }
  }

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = { positionFromSnapshot, createAdapter, install };
    return;
  }
  if (root.__streetzimLibraryGps) return;
  root.__streetzimLibraryGps = true;
  let badge;
  let status = 'Library GPS · connecting';
  let live = false;
  const adapter = createAdapter({
    fetch: root.fetch.bind(root),
    onStatus(message, current) {
      status = message; live = current;
      if (badge) { badge.textContent = message; badge.dataset.live = String(current); }
    }
  });
  try {
    install(root.navigator, adapter.api);
  } catch (error) {
    status = 'Library GPS adapter could not load. Open StreetZim home for help.';
    console.error(error);
  }
  document.addEventListener('DOMContentLoaded', () => {
    badge = document.createElement('a');
    badge.id = 'streetzim-library-gps';
    badge.href = '/';
    badge.target = '_blank';
    badge.rel = 'noopener';
    badge.textContent = status;
    badge.dataset.live = String(live);
    badge.title = 'Using the Library device’s USB GPS. Open GPS status in a new tab.';
    document.body.append(badge);
  });
  adapter.start();
  root.addEventListener('pagehide', () => adapter.stop());
  root.addEventListener('pageshow', () => adapter.start());
})(typeof window === 'undefined' ? globalThis : window);
