// Run with: node --test test_gps_control.js (no npm dependencies required).
// These behavioral tests drive API snapshots and user actions through the real
// controller. Small browser/MapLibre fakes record observable state; they do not
// test layout, WebGL rendering or NMEA parsing (the service owns that parsing).
const test = require('node:test');
const assert = require('node:assert/strict');
const { LibraryGpsControl } = require('./gps-control.js');

// Model only the DOM features used by this controller. Status strings stay in
// textContent, so tests can inspect literal receiver text without HTML parsing.
class Element {
  constructor() {
    this.textContent = '';
    this.value = '';
    this.listeners = {};
    this.attributes = {};
    this.classes = new Set();
    this.classList = { toggle: (name, active) => active ? this.classes.add(name) : this.classes.delete(name) };
  }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  setAttribute(name, value) { this.attributes[name] = value; }
  append() {}
  showModal() { this.open = true; }
  close() { this.open = false; }
}

// Preserve MapLibre's fluent API while recording coordinates and popup content.
class Marker {
  constructor({ element }) { this.element = element; }
  setLngLat(position) { this.position = position; return this; }
  setPopup(popup) { this.popup = popup; return this; }
  addTo() { return this; }
}

class Popup {
  setText(text) { this.text = text; return this; }
}

function fixture({ attachMap = true } = {}) {
  // A controllable clock makes freshness and timeout boundaries deterministic.
  // Timer callbacks run only when a test advances them; no test sleeps or polls
  // a real endpoint. Camera commands are recorded separately from marker moves.
  let now = 0;
  let nextTimer = 1;
  const timers = new Map();
  const elements = {};
  const document = {
    getElementById: id => elements[id] || (elements[id] = new Element()),
    createElement: () => new Element(),
    addEventListener() {}
  };
  const camera = [];
  const handlers = {};
  const map = {
    on: (name, callback) => { handlers[name] = callback; },
    getZoom: () => 7,
    flyTo: options => camera.push({ type: 'fly', ...options }),
    easeTo: options => camera.push({ type: 'ease', ...options })
  };
  const control = new LibraryGpsControl({
    document, maplibre: { Marker, Popup }, now: () => now,
    setTimeout: (callback, delay) => {
      const id = nextTimer++;
      timers.set(id, { callback, due: now + delay });
      return id;
    },
    clearTimeout: id => timers.delete(id),
    fetch: async () => { throw new Error('No test response set'); }
  });
  if (attachMap) control.attachMap(map);
  // Enable explicit poll calls without starting the repeating watchdog. Each
  // receive() still executes the controller's complete response/render path.
  control.running = true;
  const receive = async data => {
    control.fetch = async () => ({ ok: true, json: async () => data });
    await control.poll();
  };
  return {
    control, map, camera, handlers, elements, receive,
    setNow: value => { now = value; },
    fireAfter: delay => {
      // Run a snapshot of due timers once. Timers scheduled by those callbacks
      // belong to the next advance, avoiding an accidental unbounded poll loop.
      now += delay;
      for (const [id, timer] of [...timers]) {
        if (timer.due <= now) {
          timers.delete(id);
          timer.callback();
        }
      }
    }
  };
}

// A representative /api/gps snapshot; each scenario changes only the fields
// relevant to its transition. The sentence is display data, not parser input.
function fix(overrides = {}) {
  return {
    detected: true, connected: true, gps_detected: true, status: 'fix', message: 'GPS fix',
    latitude: 40, longitude: -105, fix_valid: true, fix_age_seconds: 0,
    satellites_used: 8, satellites_in_view: { GP: 10, GL: 6 }, hdop: 0.9,
    altitude_m: 1600, port: '/dev/ttyUSB0', baud: 9600,
    last_data_age_seconds: 0, last_sentence: '$GPGGA,test*00',
    ports: [{ device: '/dev/ttyUSB0', description: 'USB GPS' }], ...overrides
  };
}

test('first fresh fix follows automatically, uses lon/lat order and does not animate stationary GPS', async () => {
  const f = fixture();
  await f.receive(fix());
  assert.deepEqual(f.control.marker.position, [-105, 40]);
  assert.equal(f.control.markerElement.classes.has('is-live'), true);
  assert.deepEqual(f.camera, [{ type: 'fly', center: [-105, 40], zoom: 14 }]);
  await f.receive(fix());
  assert.equal(f.camera.length, 1);
  await f.receive(fix({ longitude: -104.9 }));
  assert.deepEqual(f.camera[1], { type: 'ease', center: [-104.9, 40], duration: 800 });
  assert.equal(f.elements['gps-locate'].hidden, false);
  assert.equal(f.elements['gps-detail-view'].textContent, 'GP: 10 · GL: 6');
});

test('user pan pauses camera but updates live marker, and Use GPS resumes', async () => {
  const f = fixture();
  await f.receive(fix());
  f.handlers.dragstart();
  await f.receive(fix({ latitude: 41 }));
  assert.equal(f.camera.length, 1);
  assert.deepEqual(f.control.marker.position, [-105, 41]);
  assert.equal(f.control.markerElement.classes.has('is-live'), true);
  f.control.useGps();
  assert.equal(f.camera.length, 2);
  assert.equal(f.control.following, true);
});

test('manual coordinates stay red through GPS polls until Use GPS resumes', async () => {
  const f = fixture();
  await f.receive(fix());
  // Zero is valid in both fields and also catches truthiness-based validation.
  f.elements['gps-lat'].value = '0';
  f.elements['gps-lon'].value = '0';
  f.control.goToCoordinates();
  await f.receive(fix({ latitude: 41 }));
  assert.deepEqual(f.control.marker.position, [0, 0]);
  assert.equal(f.control.markerElement.classes.has('is-live'), false);
  assert.equal(f.control.markerLabel.textContent, 'Manual');
  assert.equal(f.camera.length, 2);
  f.control.useGps();
  assert.deepEqual(f.control.marker.position, [-105, 41]);
  assert.equal(f.control.markerElement.classes.has('is-live'), true);
});

test('blank, partial or out-of-range manual input leaves location unchanged', async () => {
  const f = fixture();
  await f.receive(fix());
  for (const [lat, lon] of [['', '0'], ['40junk', '-105'], ['91', '0'], ['0', '-181']]) {
    f.elements['gps-lat'].value = lat;
    f.elements['gps-lon'].value = lon;
    f.control.goToCoordinates();
    assert.equal(f.elements['gps-error'].hidden, false);
    assert.deepEqual(f.control.marker.position, [-105, 40]);
  }
  assert.equal(f.camera.length, 1);
});

test('invalid or aging fixes turn red and retain last position without recentering', async () => {
  const f = fixture();
  await f.receive(fix({ fix_age_seconds: 9 }));
  // Cross ten seconds without another response, as the watchdog would observe.
  f.setNow(1001);
  f.control.render();
  assert.equal(f.control.markerElement.classes.has('is-live'), false);
  assert.equal(f.elements['gps-detail-current'].textContent, 'No current valid fix');
  await f.receive(fix({ fix_valid: false, status: 'no_fix' }));
  assert.equal(f.control.markerElement.classes.has('is-live'), false);
  assert.deepEqual(f.control.marker.position, [-105, 40]);
  await f.receive(fix({ detected: false, connected: false, gps_detected: false, status: 'no_device', fix_valid: false, latitude: null, longitude: null }));
  assert.deepEqual(f.control.marker.position, [-105, 40]);
  assert.equal(f.elements['gps-locate'].hidden, true);
  assert.equal(f.camera.length, 1);
});

test('HTTP errors immediately invalidate green GPS and preserve troubleshooting data safely', async () => {
  const f = fixture();
  // HTML-looking receiver text must be displayed literally, never injected.
  await f.receive(fix({ message: '<img src=x onerror=alert(1)>', last_sentence: '<script>bad()</script>' }));
  assert.equal(f.elements['gps-detail-message'].textContent, '<img src=x onerror=alert(1)>');
  assert.equal(f.elements['gps-detail-sentence'].textContent, '<script>bad()</script>');
  f.control.fetch = async () => ({ ok: false, status: 502 });
  await f.control.poll();
  assert.equal(f.control.markerElement.classes.has('is-live'), false);
  assert.match(f.elements['gps-summary'].textContent, /service unavailable/);
  assert.match(f.elements['gps-detail-message'].textContent, /HTTP 502/);
  assert.equal(f.elements['gps-detail-last'].textContent, '40.000000, -105.000000');
});

test('hung response body times out and a pending request cannot overlap another poll', async () => {
  const f = fixture();
  await f.receive(fix());
  let calls = 0;
  let signal;
  f.control.fetch = async (url, options) => {
    calls++;
    signal = options.signal;
    // Headers arrive but the body never completes or cooperates with abort.
    // Promise.race must still release the controller and invalidate the fix.
    return { ok: true, json: () => new Promise(() => {}) };
  };
  const pending = f.control.poll();
  await f.control.poll();
  assert.equal(calls, 1);
  f.fireAfter(5000);
  await pending;
  assert.equal(signal.aborted, true);
  assert.equal(f.control.markerElement.classes.has('is-live'), false);
  assert.match(f.elements['gps-detail-message'].textContent, /timed out/);
});

test('status dialog is available before a receiver or map is available', async () => {
  const f = fixture({ attachMap: false });
  await f.receive(fix({ detected: false, connected: false, gps_detected: false, status: 'no_device', fix_valid: false, latitude: null, longitude: null }));
  assert.equal(f.elements['gps-locate'].hidden, true);
  assert.equal(f.control.marker, null);
  f.elements['gps-status'].listeners.click();
  assert.equal(f.elements['gps-status-dialog'].open, true);
  assert.equal(f.elements['gps-detail-status'].textContent, 'No serial device found');
});

test('a fix received before map discovery is displayed when the map attaches', async () => {
  const f = fixture({ attachMap: false });
  await f.receive(fix());
  assert.equal(f.control.marker, null);
  f.control.attachMap(f.map);
  assert.deepEqual(f.control.marker.position, [-105, 40]);
  assert.equal(f.control.markerElement.classes.has('is-live'), true);
  assert.equal(f.camera.length, 1);
});
