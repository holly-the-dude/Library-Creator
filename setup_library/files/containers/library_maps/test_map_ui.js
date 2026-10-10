// Run with: node --test test_map_ui.js
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(`${__dirname}/map-ui.js`, 'utf8');

function fixture({ mobile = false, saved = null, blockedStorage = false, focused = false } = {}) {
  const classes = new Set();
  const field = { value: '40,-105' };
  const panels = { contains: element => element === field };
  const button = {
    attributes: {},
    setAttribute(name, value) { this.attributes[name] = value; },
    addEventListener(name, callback) { this[name] = callback; },
    focus() { document.activeElement = this; }
  };
  const document = {
    activeElement: focused ? field : null,
    getElementById: id => id === 'map-panels' ? panels : button,
    body: { classList: { toggle: (name, on) => on ? classes.add(name) : classes.delete(name) } }
  };
  const storage = {
    getItem() { if (blockedStorage) throw Error('Unavailable'); return saved; },
    setItem(key, value) { if (blockedStorage) throw Error('Unavailable'); saved = value; }
  };
  vm.runInNewContext(source, { document, window: { matchMedia: () => ({ matches: mobile }), localStorage: storage } });
  return { panels, button, classes, document, field, saved: () => saved };
}

test('phones start collapsed with a working show button', () => {
  const f = fixture({ mobile: true });
  assert.equal(f.panels.hidden, true);
  assert.equal(f.button.textContent, 'Show controls');
  assert.equal(f.button.attributes['aria-expanded'], 'false');
  assert.equal(f.classes.has('map-ui-hidden'), true);
  f.button.click();
  assert.equal(f.panels.hidden, false);
  assert.equal(f.button.textContent, 'Hide controls');
  assert.equal(f.button.attributes['aria-expanded'], 'true');
  assert.equal(f.classes.has('map-ui-hidden'), false);
  assert.equal(f.saved(), 'true');
});

test('desktop starts expanded and hiding preserves entered coordinates', () => {
  const f = fixture();
  assert.equal(f.panels.hidden, false);
  f.button.click();
  assert.equal(f.panels.hidden, true);
  assert.equal(f.saved(), 'false');
  f.button.click();
  assert.equal(f.field.value, '40,-105');
});

test('saved choice overrides screen-size default on subsequent visits', () => {
  assert.equal(fixture({ mobile: true, saved: 'true' }).panels.hidden, false);
  assert.equal(fixture({ saved: 'false' }).panels.hidden, true);
  assert.equal(fixture({ mobile: true, saved: 'invalid' }).panels.hidden, true);
});

test('toggle still works when browser storage is unavailable', () => {
  const f = fixture({ blockedStorage: true });
  f.button.click();
  assert.equal(f.panels.hidden, true);
  f.button.click();
  assert.equal(f.panels.hidden, false);
});

test('focus returns to the toggle before a focused panel is hidden', () => {
  const f = fixture({ focused: true });
  f.button.click();
  assert.equal(f.document.activeElement, f.button);
});
