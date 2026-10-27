// Run with node --test tests/test_zim_ui.cjs. No network or DOM dependency.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function ui() {
  const nodes = new Map();
  function node() {
    return {value: '', checked: false, dataset: {}, children: [], listeners: {},
      showModal() { this.open = true; },
      close(value) { if (value !== undefined) this.returnValue = value; this.open = false; this.listeners.close?.(); },
      append(...children) { this.children.push(...children); },
      replaceChildren(...children) { this.children = children; },
      setAttribute() {}, removeAttribute(name) { delete this[name]; }, addEventListener(name, callback) { this.listeners[name] = callback; }};
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


test('Clone tab works offline and reports used-data capacity and small destinations', () => {
  const u = ui();
  u.run(`source = 'clone'; state.internet.status = 'offline'; state.clone = {available:true,status:'idle',message:'Ready'};
    cloneScan = {source:{device:'/dev/sda1',used:100*1024**3,required:105*1024**3},targets:[
      {device:'/dev/sdb',model:'128 GB stick',size:128000000000,fits:true},
      {device:'/dev/sdc',model:'64 GB stick',size:64000000000,fits:false}]}; renderFiles();`);
  assert.equal(u.nodes.get('clone-panel').hidden, false);
  assert.equal(u.nodes.get('download-panel').hidden, true);
  assert.equal(u.nodes.get('upload-panel').hidden, true);
  assert.equal(Boolean(u.nodes.get('clone-scan').disabled), false);
  assert.match(u.nodes.get('clone-capacity').textContent, /Used: 100.0 GiB/);
  assert.equal(Boolean(u.nodes.get('clone-targets').children[0].children.at(-1).disabled), false);
  assert.equal(u.nodes.get('clone-targets').children[1].children.at(-1).disabled, true);
  u.run(`state.clone.status = 'running'; state.clone.message = 'Copying'; state.clone.copied = 1024; renderClone();`);
  assert.equal(u.nodes.get('clone-scan').disabled, true);
  assert.equal(u.nodes.get('clone-targets').children[0].children.at(-1).disabled, true);
  assert.match(u.nodes.get('clone-progress-text').textContent, /Copied 1.0 KiB/);
});

test('Clone controls explain missing host support and disable starting during transfers', () => {
  const u = ui();
  u.run(`source='clone'; state.clone={available:false,status:'unavailable',message:'Install host clone service'}; renderFiles();`);
  assert.equal(u.nodes.get('clone-scan').disabled, true);
  assert.match(u.nodes.get('clone-status').textContent, /Install host clone/);
  u.run(`state.clone.available=true; state.upload_active=true;
    cloneScan={source:{device:'/dev/sda1',used:100,required:200},targets:[{device:'/dev/sdb',model:'USB',size:300,fits:true}]}; renderClone();`);
  assert.equal(u.nodes.get('clone-targets').children[0].children.at(-1).disabled, true);
  assert.match(u.nodes.get('clone-status').textContent, /Wait for transfers/);
  assert.equal(u.nodes.get('clone-targets').children[0].children.at(-1).textContent, 'Waiting for transfers…');
});

test('Unknown SD media can be confirmed immediately while catalog discovery is running', () => {
  const u = ui();
  u.run(`state.clone={available:true,status:'idle'}; state.refreshing=true;
    cloneScan={source:{kind:'sd',device:'/dev/mmcblk0',used:100,required:200},targets:[
      {device:'/dev/sdb',model:'Reader',size:300,fits:true,eligible:true,media:'unknown',requires_sd_confirmation:true}]};
    renderClone();`);
  let button = u.nodes.get('clone-targets').children[0].children.at(-1);
  assert.equal(Boolean(button.disabled), false);
  assert.equal(button.textContent, 'Erase and clone…');
  u.run(`state.clone.status='unknown'; renderClone();`);
  button = u.nodes.get('clone-targets').children[0].children.at(-1);
  assert.equal(button.disabled, true);
  assert.equal(button.textContent, 'Waiting for clone service…');
});


test('Clone progress counts containers and estimates USB and SD copy stages', () => {
  const u = ui();
  u.run(`state.clone = {status:'running',phase:'stopping',containers_done:2,containers_total:4}; renderClone();`);
  assert.equal(u.nodes.get('clone-progress-panel').hidden, false);
  assert.equal(u.nodes.get('clone-progress').value, 50);
  assert.equal(u.nodes.get('clone-progress-text').textContent, '2 of 4 containers stopped');
  for (const phase of ['copying_usb', 'copying_root', 'copying_boot']) {
    u.run(`state.clone={status:'running',phase:'${phase}',copied:25*1024**3,copy_total:100*1024**3}; renderClone();`);
    assert.equal(u.nodes.get('clone-progress').value, 25);
    assert.match(u.nodes.get('clone-progress-text').textContent, /Copied 25.0 GiB of about 100.0 GiB.*25%/);
  }
  u.run(`state.clone.copied=0; renderClone();`);
  assert.equal(u.nodes.get('clone-progress').value, 0);
  u.run(`state.clone.copied=200*1024**3; renderClone();`);
  assert.equal(u.nodes.get('clone-progress').value, 99); // Metadata/sparse files may skew the estimate.
  u.run(`state.clone.copy_total=0; renderClone();`);
  assert.equal(u.nodes.get('clone-progress').value, undefined);
});

test('Clone progress waits for cleanup and supports older helpers that restart readers', () => {
  const u = ui();
  for (const phase of ['preparing', 'formatting', 'finalizing']) {
    u.run(`state.clone={status:'running',phase:'${phase}',copied:1000}; renderClone();`);
    assert.equal(u.nodes.get('clone-progress').value, undefined);
    assert.doesNotMatch(u.nodes.get('clone-progress-text').textContent, /Copied|100%/);
  }
  u.run(`state.clone={status:'running',phase:'restarting',containers_done:1,containers_total:2}; renderClone();`);
  assert.equal(u.nodes.get('clone-progress').value, 50);
  assert.match(u.nodes.get('clone-progress-text').textContent, /1 of 2 containers restarted/);
  u.run(`state.clone.status='complete'; renderClone();`);
  assert.equal(u.nodes.get('clone-progress').value, 100);
  assert.match(u.nodes.get('clone-progress-text').textContent, /Clone complete/);
  for (const status of ['idle', 'failed', 'unavailable']) {
    u.run(`state.clone.status='${status}'; renderClone();`);
    assert.equal(u.nodes.get('clone-progress-panel').hidden, true);
  }
});

test('Successful clones show removal and reboot instructions while keeping controls blocked', () => {
  const u = ui();
  for (const [phase, text] of [['awaiting_removal', /Unplug the destination/],
      ['rebooting', /Restarting the Library/], ['reboot_failed', /Manual restart needed/]]) {
    u.run(`state.clone={available:true,status:'running',copy_complete:true,phase:'${phase}'}; renderClone();`);
    assert.equal(u.nodes.get('clone-progress').value, 100);
    assert.match(u.nodes.get('clone-progress-text').textContent, text);
    assert.equal(u.nodes.get('clone-scan').disabled, true);
    assert.equal(u.nodes.get('clone-source').disabled, true);
    assert.equal(u.run('cloning()'), true);
  }
});


test('OS clone destinations allow verified unknown media but still block known USB sticks and old hosts', () => {
  const u = ui();
  u.run(`source='clone'; state.clone={available:true,status:'idle'};
    cloneScan={source:{kind:'sd',device:'/dev/mmcblk0',used:100,required:200},targets:[
      {device:'/dev/sdb',model:'Card',size:300,fits:true,eligible:true,media:'sd'},
      {device:'/dev/sdc',model:'USB stick',size:300,fits:true,eligible:false,media:'other',blocked_reason:'OS clones require SD'},
      {device:'/dev/sdd',model:'Generic Reader',size:300,fits:true,eligible:true,media:'unknown',requires_sd_confirmation:true},
      {device:'/dev/sde',model:'Old host response',size:300,fits:true}]}; renderClone();`);
  const rows = u.nodes.get('clone-targets').children;
  assert.equal(Boolean(rows[0].children.at(-1).disabled), false);
  assert.equal(rows[0].children[1].textContent, 'SD card detected');
  assert.equal(Boolean(rows[2].children.at(-1).disabled), false);
  assert.match(rows[2].children[2].textContent, /must verify/);
  for (const row of [rows[1], rows[3]]) {
    assert.equal(row.children.at(-1).disabled, true);
    assert.equal(row.children.at(-1).textContent, 'SD card required');
  }
  assert.match(rows[1].children[2].textContent, /OS clones require SD/);
  assert.match(rows[3].children[2].textContent, /Update the host clone service/);
});


test('Unknown media prompts for SD and OS verification before the separate erase confirmation', async () => {
  for (const [verified, erase] of [[false, '/dev/sdd'], [true, null], [true, '/dev/sdd']]) {
    const u = ui();
    u.run(`source='clone'; state.clone={available:true,status:'idle'};
      cloneScan={source:{kind:'sd',device:'/dev/mmcblk0',used:100,required:200},targets:[
        {device:'/dev/sdd',model:'Generic Reader',size:300,fits:true,eligible:true,media:'unknown',requires_sd_confirmation:true,token:'selection'}]};
      globalThis.confirmations=[]; globalThis.requests=[];
      globalThis.confirm=(message)=>{ confirmations.push(message); return ${verified}; };
      api=async (path,body)=>{ requests.push({path,body}); return {status:'running'}; };
      renderClone();`);
    const pending = u.nodes.get('clone-targets').children[0].children.at(-1).listeners.click();
    assert.equal(Boolean(u.nodes.get('clone-confirm')?.open), verified);
    assert.equal(u.run('requests.length'), 0);
    if (verified) {
      if (erase) {
        u.set('clone-confirm-input', erase);
        u.nodes.get('clone-confirm-form').onsubmit({preventDefault() {}});
      } else u.nodes.get('clone-confirm-cancel').onclick();
    }
    await pending;
    assert.equal(u.run('confirmations.length'), 1);
    assert.match(u.run('confirmations[0]'), /SD card in a reader, not a USB stick/);
    assert.match(u.run('confirmations[0]'), /OPERATING SYSTEM/);
    assert.equal(u.run('requests.length'), verified && erase ? 1 : 0);
    if (verified && erase) {
      assert.equal(u.run('requests[0].body.sd_confirmed'), true);
      assert.equal(u.run('requests[0].body.confirmation'), '/dev/sdd');
      assert.equal(u.run('requests[0].body.token'), 'selection');
    }
  }
});

test('Clone dialog highlights the actual device and requires an exact typed match', async () => {
  const u = ui();
  const pending = u.run(`confirmCloneDestination({device:'/dev/sdz',model:'USB <test>',size:1024}, false)`);
  const message = u.nodes.get('clone-confirm-message').children;
  assert.equal(message[1].textContent, '/dev/sdz');
  assert.equal(message[1].className, 'clone-device');
  assert.match(message[2], /USB <test>.*Library_USB/);
  assert.equal(u.nodes.get('clone-confirm-device').textContent, '/dev/sdz');
  const input = u.nodes.get('clone-confirm-input'), submit = u.nodes.get('clone-confirm-submit');
  assert.equal(submit.disabled, true);
  for (const value of ['/dev/sdb', '/dev/sdz ']) {
    input.value = value; input.oninput();
    assert.equal(submit.disabled, true);
    u.nodes.get('clone-confirm-form').onsubmit({preventDefault() {}});
    assert.equal(u.nodes.get('clone-confirm').open, true);
  }
  input.value = '/dev/sdz'; input.oninput();
  assert.equal(submit.disabled, false);
  u.nodes.get('clone-confirm-form').onsubmit({preventDefault() {}});
  assert.equal(await pending, '/dev/sdz');

  // Reopening resets approval and input; Escape closes without a return value.
  for (const cancel of ['button', 'escape']) {
    const next = u.run(`confirmCloneDestination({device:'/dev/sdc',model:'Card',size:1024}, true)`);
    assert.equal(input.value, '');
    assert.equal(submit.disabled, true);
    assert.match(u.nodes.get('clone-confirm-message').children[2], /SD card/);
    input.value = '/dev/sdc'; input.oninput();
    if (cancel === 'button') u.nodes.get('clone-confirm-cancel').onclick();
    else u.nodes.get('clone-confirm').close();
    assert.equal(await next, null);
  }
});
