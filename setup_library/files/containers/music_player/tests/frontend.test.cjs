const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

const html = fs.readFileSync(path.join(__dirname, '../music.html'), 'utf8');
// Exercise the actual helpers in the bundled component without a browser runtime.
function source(name) {
  const start = html.indexOf(`function ${name}(`);
  assert.ok(start >= 0);
  return html.slice(start, html.indexOf('\n}', start) + 2);
}
function setup(extra = {}) {
  const context = vm.createContext({
    Xl: new WeakMap(),
    yn: () => [{ action: 'info', title: 'No Music' }],
    _l: (rows) => rows.length ? rows : [{ action: 'info', title: 'No Music' }],
    ...extra,
  });
  vm.runInContext(['ao', 'an', 'nn', 'localFolderItems', 'Sh'].map(source).join('\n'), context);
  return context;
}

test('folder menu distinguishes navigation from playable songs, including duplicate names', () => {
  const data = {
    songs: [{ id: 's1', name: 'Same title' }, { id: 's2', name: 'Same title' }],
    folders: [
      { id: 'root', parentId: null, name: 'Folders', songIds: ['s1'] },
      { id: 'child', parentId: 'root', name: '<Album & café>', songIds: ['s2'] },
      { id: 'empty', parentId: 'child', name: 'Empty', songIds: [] },
    ],
  };
  const ctx = setup();
  const root = ctx.localFolderItems({ data, contextId: 'root' });
  assert.equal(root[0].target, 'folders');
  assert.equal(root[0].contextId, 'child');
  assert.equal(root[0].title, '<Album & café>');
  assert.equal(root[1].songId, 's1');
  const child = ctx.localFolderItems({ data, contextId: root[0].contextId });
  assert.equal(child[1].songId, 's2');
  assert.equal(ctx.nn('folders', 'child', data)[0].id, 's2');
  assert.equal(ctx.localFolderItems({ data, contextId: 'empty' })[0].action, 'info');
});

test('main menu offers folders and no playlists', () => {
  const ctx = setup({ Ee: key => ({ id: key }) });
  const rows = ctx.Sh({ i18n: {}, hasNowPlaying: true });
  assert.equal(rows[0].target, 'folders');
  assert.equal(rows.some(row => row.id === 'playlists'), false);
  assert.equal(rows.some(row => row.id === 'now-playing'), true);
});

test('local library requests bypass cache and reject HTTP, schema and file URL failures', async () => {
  const ctx = setup({
    document: { baseURI: 'http://localhost:2001/' },
    location: { protocol: 'http:' }, URL,
    fetch: async (url, options) => {
      assert.equal(String(url), 'http://localhost:2001/api/library');
      assert.equal(options.cache, 'no-store');
      return { ok: true, json: async () => ({ schemaVersion: 3, songs: [{}], folders: [{}, {}], artists: [] }) };
    },
  });
  vm.runInContext('async ' + source('yr'), ctx);
  assert.equal((await ctx.yr()).data.songs.length, 1);
  ctx.fetch = async () => ({ ok: true, json: async () => ({ schemaVersion: 3, songs: [], folders: [{}], artists: [] }) });
  assert.equal((await ctx.yr()).data.songs.length, 0);
  ctx.fetch = async () => ({ ok: false });
  await assert.rejects(ctx.yr(), /could not be read/);
  ctx.fetch = async () => ({ ok: true, json: async () => ({ schemaVersion: 3 }) });
  await assert.rejects(ctx.yr(), /Unsupported library format/);
  ctx.location.protocol = 'file:';
  await assert.rejects(ctx.yr(), /server.py/);
});

// Load the real settings store/schema without mounting the compiled UI.
function settings(saved = null, unavailable = false, legacy = null) {
  const storage = new Map();
  if (saved !== null) storage.set('library-music:settings', saved);
  if (legacy !== null) storage.set('apple-ipod:settings', legacy);
  const ctx = vm.createContext({
    localStorage: {
      getItem(key) { if (unavailable) throw new Error('Storage blocked'); return storage.get(key) ?? null; },
      setItem(key, value) { if (unavailable) throw new Error('Storage blocked'); storage.set(key, value); },
    },
    le: () => ({ error() {} }),
    Ue: [],
  });
  const skins = html.match(/const PLAYER_SKINS = .*;/)[0];
  const schema = html.slice(html.indexOf('var Li ='), html.indexOf('function Za('));
  vm.runInContext([skins, ...['J', 'bt', 'Ot'].map(source), schema].join('\n'), ctx);
  return { storage, ctx, run: code => vm.runInContext(code, ctx) };
}

test('Purple is the first-run and migrated default without losing other preferences', () => {
  const fresh = settings();
  assert.equal(fresh.run('Pe.skin'), 'purple');
  assert.equal(JSON.parse(fresh.storage.get('library-music:settings')).skin, 'purple');
  const old = settings(JSON.stringify({volume: 73, shuffle: 'songs', repeat: 'all'}));
  const migrated = JSON.parse(old.storage.get('library-music:settings'));
  assert.equal(migrated.skin, 'purple');
  assert.equal(migrated.volume, 73);
  assert.equal(migrated.shuffle, 'songs');
  assert.equal(migrated.repeat, 'all');
});

test('legacy preferences migrate once and never override newer choices or reset', () => {
  const legacy = JSON.stringify({skin: 'classic', volume: 73, shuffle: 'songs',
    repeat: 'all', clicker: 'off', backlight: '3sec', backlightChosen: true});
  const migrated = settings(null, false, legacy);
  assert.deepEqual(JSON.parse(migrated.storage.get('library-music:settings')), JSON.parse(legacy));
  const next = JSON.stringify({skin: 'purple', volume: 20});
  const current = settings(next, false, legacy);
  assert.equal(current.run('_s().skin'), 'purple');
  assert.equal(current.run('_s().volume'), 20);
  migrated.run('Hs()');
  const reset = settings(migrated.storage.get('library-music:settings'), false, legacy);
  assert.equal(reset.run('_s().skin'), 'purple');
  assert.equal(reset.run('_s().volume'), 50);
  const invalidLegacy = settings(null, false, '{broken');
  assert.equal(invalidLegacy.run('_s().skin'), 'purple');
});

test('Classic persists across reload and Reset All Settings returns to Purple', () => {
  const first = settings();
  first.run('ie.update(current => ({...current, skin: PLAYER_SKINS.CLASSIC}))');
  const reloaded = settings(first.storage.get('library-music:settings'));
  assert.equal(reloaded.run('_s().skin'), 'classic');
  reloaded.run('Hs()');
  assert.equal(JSON.parse(reloaded.storage.get('library-music:settings')).skin, 'purple');
});

test('invalid, malformed, and inaccessible saved settings fall back to Purple', () => {
  for (const value of ['{', 'null', '{"skin":"unknown"}', '{"skin":4}']) {
    assert.equal(settings(value).run('_s().skin'), 'purple');
  }
  assert.equal(settings(null, true).run('_s().skin'), 'purple');
});

test('Settings offers a skin toggle with Purple and Classic', () => {
  const s = settings();
  s.ctx.Ee = id => ({id});
  s.run('const kh = Object.values(Li), Ph = Object.values(Re), Eh = Object.values(zi);');
  s.run([source('ol'), source('xh')].join('\n'));
  const rows = s.ctx.xh({i18n: {t: key => key}});
  const skin = rows.find(row => row.id === 'skin');
  assert.equal(skin.action, 'inline-toggle');
  assert.equal(skin.toggleKey, 'skin');
  assert.deepEqual(Array.from(skin.values), ['purple', 'classic']);
});

test('skin updates the connected host without remounting and unsubscribes on removal', () => {
  const s = settings();
  s.ctx.l1 = class {
    constructor() { this.dataset = {}; this.shadowRoot = {prepend() {}}; this.mounts = 0; }
    connectedCallback() { this.mounts++; }
    disconnectedCallback() {}
  };
  s.ctx.document = {createElement: () => ({})};
  s.ctx.Tn = '';
  s.ctx.PLAYER_SKIN_STYLES = '';
  s.run(html.slice(html.indexOf('class a1 extends l1'), html.indexOf('customElements.define("library-music-player"')));
  s.run('const host = new a1(); host.connectedCallback();');
  assert.equal(s.run('host.dataset.skin'), 'purple');
  s.run('ie.update(current => ({...current, skin: "classic"}))');
  assert.equal(s.run('host.dataset.skin'), 'classic');
  assert.equal(s.run('host.mounts'), 1);
  s.run('host.disconnectedCallback(); Hs();');
  assert.equal(s.run('host.dataset.skin'), 'classic');
  s.run('host.connectedCallback();');
  assert.equal(s.run('host.dataset.skin'), 'purple');
});

// Exercise the actual button handler, loader, and store as a unit. Server tests
// separately verify that each /api/library request rereads the music directory.
function rescanPlayer() {
  const listeners = new Map();
  const button = {
    disabled: true,
    addEventListener(event, handler) { listeners.set(event, handler); },
    removeEventListener(event, handler) { if (listeners.get(event) === handler) listeners.delete(event); },
    click() { return listeners.get('click')?.(); },
  };
  const status = { setAttribute() {} };
  let response = {schemaVersion: 3, language: 'en-US', songs: [], folders: [{id: 'root', songIds: []}], artists: []};
  let requests = 0;
  const ctx = setup({
    Ue: [], URL, location: {protocol: 'http:'},
    document: {baseURI: 'http://localhost:2001/', getElementById: id => id === 'rescan' ? button : status},
    fetch: async () => {
      requests++;
      if (response instanceof Error) throw response;
      return {ok: true, json: async () => response};
    },
  });
  vm.runInContext([...['J', 'bt', 'Ot', 'gr', 'bindLibraryControls'].map(source), 'async ' + source('yr')].join('\n'), ctx);
  const {libraryData, loadLibraryData} = ctx.gr();
  let state;
  libraryData.subscribe(value => { state = value; });
  const cleanup = ctx.bindLibraryControls(libraryData, loadLibraryData);
  return {button, status, loadLibraryData, cleanup, ctx, get state() {return state;},
    get requests() {return requests;}, set response(value) {response = value;}};
}

test('rescan button fetches and publishes new tracks, showing progress and completion', async () => {
  const player = rescanPlayer();
  assert.equal(player.button.disabled, true);
  await player.loadLibraryData();
  assert.match(player.status.textContent, /Scan complete.*No music found/);
  assert.equal(player.button.disabled, false);
  const next = {schemaVersion: 3, songs: [{id: 'new', name: 'New song'}],
    folders: [{id: 'root', songIds: ['new']}], artists: []};
  player.response = next;
  const scanning = player.button.click();
  assert.equal(player.button.disabled, true);
  assert.match(player.button.textContent, /Scanning/);
  assert.match(player.status.textContent, /Scanning your music/);
  assert.equal(player.state.status, 'ready'); // Existing menu data stays visible.
  assert.equal(player.button.click(), undefined); // Double-click does not scan twice.
  await scanning;
  assert.equal(player.requests, 2);
  assert.equal(player.state.data, next);
  assert.equal(player.ctx.localFolderItems({data: player.state.data})[0].songId, 'new');
  assert.match(player.status.textContent, /Scan complete · 1 songs · 0 folders/);
  assert.equal(player.button.disabled, false);
  player.cleanup();
  assert.equal(player.button.click(), undefined);
  assert.equal(player.requests, 2);
});

test('rescan errors preserve the prior catalog and permit retry without reloading', async () => {
  const player = rescanPlayer();
  await player.loadLibraryData();
  const previous = player.state.data;
  player.response = new Error('Connection lost');
  assert.equal(await player.button.click(), false);
  assert.equal(player.state.data, previous);
  assert.match(player.status.textContent, /Scan failed: Connection lost/);
  assert.match(player.status.textContent, /previous library is still available/);
  assert.equal(player.button.disabled, false);
  player.response = {schemaVersion: 3, songs: [], folders: [{}], artists: []};
  assert.equal(await player.button.click(), true);
  assert.match(player.status.textContent, /Scan complete/);
  assert.equal(player.state.error, undefined);
});

test('initial failures are retryable and concurrent loads share one request', async () => {
  const player = rescanPlayer();
  player.response = new Error('Folder unavailable');
  const first = player.loadLibraryData();
  assert.equal(player.loadLibraryData(), first);
  await first;
  assert.equal(player.requests, 1);
  assert.equal(player.state.status, 'error');
  assert.equal(player.button.disabled, false);
  assert.match(player.status.textContent, /Folder unavailable/);
  player.response = {schemaVersion: 3, songs: [], folders: [{}], artists: []};
  await player.button.click();
  assert.equal(player.state.status, 'ready');
  assert.equal(player.requests, 2);
});
