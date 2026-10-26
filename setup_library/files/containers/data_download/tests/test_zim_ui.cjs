// Run with node --test tests/test_zim_ui.cjs. No network or DOM dependency.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function ui() {
  const nodes = new Map();
  function node() {
    return {value: '', checked: false, dataset: {}, children: [],
      append(...children) { this.children.push(...children); },
      replaceChildren(...children) { this.children = children; },
      setAttribute() {}, addEventListener() {}};
  }
  const document = {
    getElementById(id) { if (!nodes.has(id)) nodes.set(id, node()); return nodes.get(id); },
    createElement: node,
    querySelectorAll() { return []; }
  };
  const context = vm.createContext({document, Intl, console, location: {protocol: 'http:', hostname: 'library'},
    window: {addEventListener() {}}, setTimeout() {}, setInterval() {}});
  const script = fs.readFileSync(path.join(__dirname, '../static/app.js'), 'utf8');
  vm.runInContext(script.replace(/poll\(\);\s*$/, ''), context);
  const run = code => vm.runInContext(code, context);
  const set = (id, value) => document.getElementById(id).value = value;
  run(`source = 'wiki'; state.storage = {ready: true, available: 1000}; state.internet = {status: 'online'};
    state.catalog = [
      {id:'map',source:'wiki',title:'Fiji',filename:'maps_en_fiji_2026-06.zim',description:'Roads and landmarks',languages:['eng'],category:'maps',size:50,destination:'wiki/map.zim'},
      {id:'fr',source:'wiki',title:'France',filename:'maps_fr_france_2026-06.zim',languages:['fra'],category:'maps',size:60},
      {id:'multi',source:'wiki',title:'Travel',filename:'travel_2026-06.zim',languages:['eng','fra'],category:'wikivoyage',size:2000},
      {id:'old',source:'wiki',title:'Wikipedia',filename:'wikipedia_en_all_nopic_2025-06.zim',languages:['eng'],category:'wikipedia',size:100},
      {id:'new',source:'wiki',title:'Wikipedia',filename:'wikipedia_en_all_nopic_2026-06.zim',languages:['eng'],category:'wikipedia',size:200},
      {id:'full',source:'wiki',title:'Wikipedia',filename:'wikipedia_en_all_maxi_2026-06.zim',languages:['eng'],category:'wikipedia',size:300}
    ];`);
  return {run, set, nodes, ids: () => Array.from(run('filteredRows().map(row => row.id)'))};
}

test('language and map collection filters combine; multilingual collections remain visible', () => {
  const u = ui();
  u.set('zim-language', 'eng'); u.set('zim-category', 'maps');
  assert.deepEqual(u.ids(), ['map']);
  u.set('zim-language', ''); assert.deepEqual(u.ids(), ['map', 'fr']);
  u.set('zim-language', 'fra'); u.set('zim-category', '');
  assert.deepEqual(u.ids(), ['fr', 'multi']);
});

test('plain English language names and descriptions are searchable', () => {
  const u = ui();
  u.set('search', 'landmarks'); assert.deepEqual(u.ids(), ['map']);
  u.set('search', 'French'); assert.deepEqual(u.ids(), ['fr', 'multi']);
  u.set('search', 'Books'); assert.deepEqual(u.ids(), []);
});

test('latest editions preserve different variants and space filtering still works', () => {
  const u = ui();
  u.run(`$('latest').checked = true;`);
  assert.deepEqual(u.ids(), ['map', 'fr', 'multi', 'new', 'full']);
  u.run(`$('fits').checked = true;`);
  assert.deepEqual(u.ids(), ['map', 'fr', 'new', 'full']);
});

test('legacy cached Wikipedia rows match the English language filter', () => {
  const u = ui();
  u.run(`state.catalog = [{source:'wiki',title:'wikipedia_en_all_2026-01.zim',filename:'wikipedia_en_all_2026-01.zim',id:'cached'}];`);
  u.set('zim-language', 'eng'); u.set('zim-category', 'wikipedia');
  assert.deepEqual(u.ids(), ['cached']);
});

test('StreetZim has a separate catalog, searches features and saves to the shared ZIM folder', () => {
  const u = ui();
  u.run(`source = 'streetzim'; state.catalog.push({id:'co',source:'streetzim',title:'Colorado',
    filename:'osm-colorado.zim',description:'Rocky Mountains',features:'Routing & Directions',
    size:100,destination:'wiki/osm-colorado.zim',date:'2026-10-25'});`);
  u.set('zim-language', 'fra'); // Kiwix-only filters must not hide map regions.
  u.set('search', 'Directions');
  assert.deepEqual(u.ids(), ['co']);
  u.run('renderFiles()');
  assert.equal(u.nodes.get('zim-filters').hidden, true);
  assert.match(u.nodes.get('destination').textContent, /\/Library\/wiki/);
  assert.match(u.nodes.get('source-hint').textContent, /Maps → StreetZim/);
});

test('metadata renders as text and collection filters survive refreshes', () => {
  const u = ui();
  u.run(`state.catalog[0].description = '<img src=x onerror=alert(1)>';`);
  u.set('zim-language', 'eng'); u.set('zim-category', 'maps');
  u.run('renderFiles()');
  const name = u.nodes.get('files').children[0].children[1];
  assert.equal(name.children[0].textContent, '<img src=x onerror=alert(1)>');
  assert.equal(u.nodes.get('zim-category').value, 'maps');
  assert.equal(u.nodes.get('zim-language').value, 'eng');
  u.run(`state.catalog = []; renderZimFilters();`);
  assert.equal(u.nodes.get('zim-category').value, 'maps');
});
