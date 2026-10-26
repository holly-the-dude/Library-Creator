const test = require('node:test');
const assert = require('node:assert/strict');
const { positionFromSnapshot, createAdapter, install } = require('../static/streetzim-gps.js');

const fix = { fix_valid: true, connected: true, gps_detected: true,
  latitude: 39.74, longitude: -104.99, fix_age_seconds: 1, altitude_m: 1600 };

function fixture() {
  const timers = new Map();
  let timerId = 1;
  let snapshot = { ...fix };
  let fail = false;
  const statuses = [];
  const adapter = createAdapter({
    fetch: async (url, options) => {
      assert.equal(url, '/api/gps'); assert.equal(options.cache, 'no-store');
      if (fail) throw new Error('Disconnected');
      return { ok: true, json: async () => snapshot };
    },
    now: () => 100000,
    setTimer: (callback, duration) => { const id = timerId++; timers.set(id, { callback, duration }); return id; },
    clearTimer: id => timers.delete(id),
    onStatus: (...args) => statuses.push(args)
  });
  return { adapter, timers, statuses, setSnapshot: value => { snapshot = value; },
    disconnect: () => { fail = true; } };
}
const flush = () => new Promise(resolve => setImmediate(resolve));

test('converts a real fix with source timestamp and no fabricated speed/heading', () => {
  const p = positionFromSnapshot(fix, 100000);
  assert.equal(p.timestamp, 99000);
  assert.equal(p.coords.latitude, 39.74);
  assert.equal(p.coords.altitude, 1600);
  assert.equal(p.coords.heading, null);
  assert.equal(p.coords.speed, null);
});

test('never reports stale, invalid, disconnected or malformed data as a live location', () => {
  for (const patch of [{ fix_valid: false }, { connected: false }, { gps_detected: false },
    { fix_age_seconds: 10.1 }, { fix_age_seconds: null }, { fix_age_seconds: -1 },
    { latitude: null }, { latitude: '39' }, { latitude: 91 }, { longitude: 181 }, { longitude: NaN }]) {
    assert.equal(positionFromSnapshot({ ...fix, ...patch }), null, JSON.stringify(patch));
  }
});

test('shares updates, clears watches, and recovers after a lost fix', async () => {
  const f = fixture(); const positions = []; const errors = [];
  const id = f.adapter.api.watchPosition(p => positions.push(p), e => errors.push(e));
  await flush();
  assert.equal(positions.length, 1);
  f.setSnapshot({ ...fix, fix_age_seconds: 20 });
  await f.adapter.poll();
  assert.equal(positions.length, 1);
  assert.equal(errors.at(-1).code, 2);
  f.setSnapshot({ ...fix, latitude: 40 });
  await f.adapter.poll();
  assert.equal(positions.at(-1).coords.latitude, 40);
  f.adapter.api.clearWatch(id);
  await f.adapter.poll();
  assert.equal(positions.length, 2);
  f.adapter.stop();
});

test('one-shot requests wait for a fix and time out without returning old coordinates', async () => {
  const f = fixture(); f.setSnapshot({ ...fix, fix_valid: false });
  const positions = []; const errors = [];
  f.adapter.api.getCurrentPosition(p => positions.push(p), e => errors.push(e), { timeout: 500 });
  await flush();
  assert.equal(positions.length, 0);
  [...f.timers.values()].find(t => t.duration === 500).callback();
  assert.equal(errors[0].code, 3);
  f.setSnapshot(fix);
  await f.adapter.poll();
  assert.equal(positions.length, 0);
  f.adapter.stop();
});

test('one-shot succeeds once; a network failure invalidates the status', async () => {
  const f = fixture(); const positions = []; const errors = [];
  f.adapter.api.getCurrentPosition(p => positions.push(p), e => errors.push(e));
  await flush();
  await f.adapter.poll();
  assert.equal(positions.length, 1);
  f.adapter.api.watchPosition(() => {}, e => errors.push(e));
  f.disconnect(); await f.adapter.poll();
  assert.equal(errors.at(-1).code, 2);
  assert.equal(f.statuses.at(-1)[1], false);
  f.adapter.stop();
});

test('installs on HTTP without native geolocation and preserves unrelated permissions', async () => {
  const nav = { permissions: { query: async desc => ({ state: desc.name }) } };
  const api = {};
  install(nav, api);
  assert.equal(nav.geolocation, api);
  assert.equal((await nav.permissions.query({ name: 'geolocation' })).state, 'granted');
  assert.equal((await nav.permissions.query({ name: 'notifications' })).state, 'notifications');
});
