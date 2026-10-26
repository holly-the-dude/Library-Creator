'use strict';
const put = (id, value) => { document.getElementById(id).textContent = value; };
async function loadStatus() {
  try {
    const response = await fetch('/api/status', { cache: 'no-store' });
    if (!response.ok) throw new Error('Status unavailable');
    const data = await response.json();
    put('archive-status', !data.ready ? 'The map server is starting. Try again shortly.' : data.archives.length ?
      `${data.archives.length} map archive${data.archives.length === 1 ? '' : 's'} ready to explore.` :
      'No maps loaded yet. Add StreetZim .zim files to the configured ZIM folder, then restart this container.');
    const list = document.getElementById('archives');
    list.replaceChildren();
    for (const name of data.archives) {
      const item = document.createElement('li'); item.textContent = name; list.append(item);
    }
    put('gps-source', data.gps_mode === 'serial' ? 'USB receiver connected directly to StreetZim' : `Shared GPS feed · ${data.gps_upstream}`);
  } catch (_) { put('archive-status', 'Cannot reach the map service. Refresh to try again.'); }
}
async function loadGps() {
  try {
    const response = await fetch('/api/gps', { cache: 'no-store', signal: AbortSignal.timeout(5000) });
    if (!response.ok) throw new Error('GPS unavailable');
    const data = await response.json();
    const live = data.fix_valid === true && data.connected === true && data.gps_detected === true &&
      Number.isFinite(data.fix_age_seconds) && data.fix_age_seconds >= 0 && data.fix_age_seconds <= 10 &&
      Number.isFinite(data.latitude) && Number.isFinite(data.longitude);
    put('gps-state', live ? 'Live fix' : 'Waiting for GPS');
    document.getElementById('gps-state').dataset.live = String(live);
    put('gps-message', data.message || 'Waiting for receiver data.');
    put('coordinates', live ? `${data.latitude.toFixed(6)}, ${data.longitude.toFixed(6)}` : 'No current position');
    put('satellites', data.satellites_used ?? '—');
    put('fix-age', Number.isFinite(data.fix_age_seconds) ? `${data.fix_age_seconds.toFixed(1)} seconds` : '—');
  } catch (_) {
    put('gps-state', 'Unavailable'); document.getElementById('gps-state').dataset.live = 'false';
    put('gps-message', 'Cannot reach the GPS source. In shared mode, check that Maps is running. In direct USB mode, check the receiver connection.');
    put('coordinates', 'No current position'); put('satellites', '—'); put('fix-age', '—');
  } finally { setTimeout(loadGps, 2000); }
}
loadStatus();
loadGps();
