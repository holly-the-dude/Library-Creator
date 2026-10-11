// Run with: node --test test_map_ui.js
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(`${__dirname}/map-ui.js`, 'utf8');

function fixture({ mobile = false, saved = null, blockedStorage = false, focused = false } = {}) {
  class Element {
    constructor(tag = 'div') {
      this.tag = tag;
      this.children = [];
      this.attributes = {};
      this.listeners = {};
      this.hidden = false;
      this.classList = new Set();
      this.classList.remove = name => this.classList.delete(name);
      this.classList.contains = name => this.classList.has(name);
      this.classList.toggle = (name, on) => on ? this.classList.add(name) : this.classList.delete(name);
    }
    setAttribute(name, value) { this.attributes[name] = value; }
    addEventListener(name, callback) { (this.listeners[name] ||= []).push(callback); }
    dispatchEvent(event) { for (const callback of this.listeners[event.type] || []) callback(event); }
    click() { this.dispatchEvent({ type: 'click' }); }
    focus() { document.activeElement = this; }
    blur() { document.activeElement = null; }
    contains(element) { return this === element || this.children.some(child => child.contains(element)); }
    get nextSibling() { return this.parentNode?.children[this.parentNode.children.indexOf(this) + 1] || null; }
    appendChild(child) { this.insertBefore(child, null); }
    prepend(child) { this.insertBefore(child, this.children[0] || null); }
    insertBefore(child, next) {
      if (next && !this.children.includes(next)) throw Error('Missing sibling');
      if (child.parentNode) child.parentNode.children.splice(child.parentNode.children.indexOf(child), 1);
      this.children.splice(next ? this.children.indexOf(next) : this.children.length, 0, child);
      child.parentNode = this;
    }
    querySelector(tag) {
      for (const child of this.children) {
        if (child.tag === tag) return child;
        const match = child.querySelector(tag);
        if (match) return match;
      }
      return null;
    }
    setPointerCapture() {}
  }
  const elements = {};
  const document = new Element();
  document.body = new Element();
  document.createElement = tag => new Element(tag);
  document.getElementById = id => elements[id] || null;
  function add(id, parent = document.body, tag = 'div') {
    const element = elements[id] = new Element(tag);
    parent.appendChild(element);
    return element;
  }
  const button = add('map-ui-toggle', document.body, 'button');
  const panels = add('map-panels');
  const toolbar = add('map-toolbar', panels);
  for (const [name, source] of [['map', 'controls'], ['search', 'search-control'], ['gps', 'gps-control'], ['route', 'route-control'], ['layers', 'layers-control']]) {
    add(`mnav-${name}`, document.body, 'button');
    add(`mpanel-${name}`);
    add(source, ['map', 'search', 'gps'].includes(name) ? toolbar : panels);
  }
  add('mobile-backdrop');
  const field = add('route-start', elements['route-control'], 'input');
  field.value = '40,-105';
  for (const id of ['route-start-pin', 'route-dest-pin', 'route-go']) add(id, elements['route-control'], 'button');
  document.activeElement = focused ? field : null;
  const classes = document.body.classList;
  const storage = {
    getItem() { if (blockedStorage) throw Error('Unavailable'); return saved; },
    setItem(key, value) { if (blockedStorage) throw Error('Unavailable'); saved = value; }
  };
  const window = new Element();
  window.innerWidth = mobile ? 390 : 1280;
  window.matchMedia = () => ({ matches: window.innerWidth <= 700 });
  window.localStorage = storage;
  vm.runInNewContext(source, { document, window });
  return { panels, button, classes, document, window, elements, field, saved: () => saved };
}

test('phones start with sheets closed and a working show button', () => {
  const f = fixture({ mobile: true });
  assert.equal(f.panels.hidden, false);
  assert.equal(f.button.textContent, 'Show');
  assert.equal(f.button.attributes['aria-expanded'], 'false');
  assert.equal(f.elements['mpanel-map'].classList.has('is-open'), false);
  f.button.click();
  assert.equal(f.panels.hidden, false);
  assert.equal(f.button.textContent, 'Hide');
  assert.equal(f.button.attributes['aria-expanded'], 'true');
  assert.equal(f.classes.has('map-ui-hidden'), false);
  assert.equal(f.elements['mpanel-map'].classList.has('is-open'), true);
  assert.equal(f.saved(), null);
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

test('saved choice controls desktop visibility without hiding mobile controls', () => {
  assert.equal(fixture({ saved: 'true' }).panels.hidden, false);
  assert.equal(fixture({ saved: 'false' }).panels.hidden, true);
  assert.equal(fixture({ mobile: true, saved: 'false' }).panels.hidden, false);
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

test('a route sheet dismissed by a downward swipe reopens from Route or Show', () => {
  const f = fixture({ mobile: true });
  const route = f.elements['mpanel-route'];
  const nav = f.elements['mnav-route'];
  const backdrop = f.elements['mobile-backdrop'];
  const handle = route.querySelector('button');
  nav.click();
  f.elements['route-go'].focus();
  handle.dispatchEvent({ type: 'pointerdown', isPrimary: true, pointerId: 1, clientX: 100, clientY: 100 });
  handle.dispatchEvent({ type: 'pointerup', pointerId: 1, clientX: 105, clientY: 180 });
  assert.equal(route.classList.has('is-open'), false);
  assert.equal(backdrop.classList.has('is-open'), false);
  assert.equal(f.document.activeElement, nav);
  assert.equal(f.button.textContent, 'Show');
  nav.click();
  assert.equal(route.classList.has('is-open'), true);
  f.button.click();
  assert.equal(route.classList.has('is-open'), false);
  f.button.click();
  assert.equal(route.classList.has('is-open'), true);
  backdrop.click();
  f.button.click();
  assert.equal(route.classList.has('is-open'), true);
  assert.equal(f.field.value, '40,-105');
  assert.notEqual(f.document.activeElement.tag, 'input');
});

test('picking each route point uncovers the map and restores a dismissible menu', () => {
  const f = fixture({ mobile: true });
  const route = f.elements['mpanel-route'];
  f.elements['mnav-route'].click();
  for (const [which, next] of [['start', 'route-dest-pin'], ['dest', 'route-go']]) {
    f.document.dispatchEvent({ type: 'library-route-pick-start' });
    assert.equal(route.classList.has('is-open'), false);
    assert.equal(f.elements['mobile-backdrop'].classList.has('is-open'), false);
    f.document.dispatchEvent({ type: 'library-route-pick-end', detail: { which } });
    assert.equal(route.classList.has('is-open'), true);
    assert.equal(f.document.activeElement, f.elements[next]);
  }
  route.querySelector('button').click();
  f.elements['mnav-route'].click();
  assert.equal(route.classList.has('is-open'), true);
});

test('rotation restores desktop controls and leaves mobile sheets reopenable', () => {
  const f = fixture({ mobile: true });
  f.elements['mnav-route'].click();
  f.window.innerWidth = 844;
  f.window.dispatchEvent({ type: 'resize' });
  assert.deepEqual(f.elements['map-toolbar'].children, [f.elements.controls, f.elements['search-control'], f.elements['gps-control']]);
  assert.equal(f.elements['route-control'].parentNode, f.panels);
  assert.equal(f.elements['mobile-backdrop'].classList.has('is-open'), false);
  f.window.innerWidth = 390;
  f.window.dispatchEvent({ type: 'resize' });
  f.elements['mnav-route'].click();
  assert.equal(f.elements['route-control'].parentNode, f.elements['mpanel-route']);
  assert.equal(f.elements['mpanel-route'].classList.has('is-open'), true);
  assert.equal(f.field.value, '40,-105');
});
