/*
 * One controller owns the page's location controls, diagnostic dialog and marker.
 * The local service reads the serial receiver; GET /api/gps supplies snapshots.
 * In that contract, detected means a serial candidate exists, connected means
 * its port is open, and gps_detected means supported, checksummed NMEA was seen.
 * Coordinates are the last accepted position; only fix_valid plus a fresh age
 * makes them a current fix. Unknown receiver measurements arrive as null.
 *
 * Construct after the control markup exists, start polling, then attach the map
 * after tile discovery. This lets diagnostics work even when no maps are stored.
 */
(function (root) {
  'use strict';

  // Match the service's freshness window, with a local check between responses.
  const FRESH_FIX_SECONDS = 10;
  const STATUS_LABELS = {
    no_device: 'No serial device found',
    ambiguous: 'Choose a serial device',
    waiting: 'Waiting for GPS data',
    fix: 'GPS fix acquired',
    no_fix: 'GPS has no position fix',
    stale: 'GPS position is stale',
    disconnected: 'GPS disconnected',
    error: 'GPS receiver error'
  };

  function hasCoordinates(data) {
    // Strict numeric checks reject null and malformed service/manual coordinates;
    // latitude or longitude of zero is a legitimate location.
    return Number.isFinite(data.latitude) && Math.abs(data.latitude) <= 90 &&
      Number.isFinite(data.longitude) && Math.abs(data.longitude) <= 180;
  }

  class LibraryGpsControl {
    constructor(options = {}) {
      // Injectable browser dependencies let tests exercise failures and timers
      // without a DOM, WebGL context, receiver, or real network connection.
      this.document = options.document || root.document;
      this.maplibre = options.maplibre || root.maplibregl;
      this.fetch = options.fetch || root.fetch.bind(root);
      this.now = options.now || (() => performance.now());
      this.setTimeout = options.setTimeout || root.setTimeout.bind(root);
      this.clearTimeout = options.clearTimeout || root.clearTimeout.bind(root);
      this.AbortController = options.AbortController || root.AbortController;
      this.pollMs = options.pollMs || 2000;
      this.timeoutMs = options.timeoutMs || 5000;
      this.data = null;
      this.available = false;
      // Camera following and marker source are independent: panning pauses the
      // camera while GPS keeps moving the pin; manual Go also selects a manual
      // pin, which subsequent GPS polls must not overwrite.
      this.following = true;
      this.positionSource = 'gps';
      this.map = null;
      this.marker = null;
      this.lastCameraPosition = null;
      this.receivedAt = 0;
      this.elements = {};
      [
        'gps-lat', 'gps-lon', 'gps-go', 'gps-error', 'gps-locate', 'gps-status',
        'gps-summary', 'gps-status-dialog', 'gps-status-close', 'gps-detail-status',
        'gps-detail-message', 'gps-detail-detected', 'gps-detail-connected',
        'gps-detail-nmea', 'gps-detail-current', 'gps-detail-last', 'gps-detail-age',
        'gps-detail-used', 'gps-detail-view', 'gps-detail-hdop', 'gps-detail-altitude',
        'gps-detail-port', 'gps-detail-baud', 'gps-detail-data-age',
        'gps-detail-ports', 'gps-detail-sentence', 'gps-detail-follow'
      ].forEach(id => { this.elements[id] = this.document.getElementById(id); });

      this.elements['gps-go'].addEventListener('click', () => this.goToCoordinates());
      ['gps-lat', 'gps-lon'].forEach(id => {
        this.elements[id].addEventListener('keydown', event => {
          if (event.key === 'Enter') this.goToCoordinates();
        });
      });
      this.elements['gps-locate'].addEventListener('click', () => this.useGps());
      this.elements['gps-status'].addEventListener('click', () => {
        this.render();
        this.elements['gps-status-dialog'].showModal();
      });
      this.elements['gps-status-close'].addEventListener('click', () => {
        this.elements['gps-status-dialog'].close();
      });
      this.onVisibility = () => this.render();
      this.document.addEventListener('visibilitychange', this.onVisibility);
      this.onUserMove = event => {
        // GPS flyTo/easeTo also emit movement events. Only user-originated
        // events should stop following; dragstart covers direct map panning.
        if (event.originalEvent) this.pauseFollowing();
      };
      this.onDrag = () => this.pauseFollowing();
      this.render();
    }

    attachMap(map) {
      // Called once for the page's map. Replay any snapshot received while its
      // PMTiles files were being discovered, including the initial camera move.
      this.map = map;
      map.on('movestart', this.onUserMove);
      map.on('dragstart', this.onDrag);
      this.render();
      this.updateCamera();
    }

    start() {
      // Polling and the expiry watchdog share the page/controller lifetime.
      if (this.running) return;
      this.running = true;
      this.poll();
      // Expire a fix even while a request hangs or after a suspended tab resumes.
      const tick = () => {
        if (!this.running) return;
        this.render();
        this.watchdog = this.setTimeout(tick, 1000);
      };
      this.watchdog = this.setTimeout(tick, 1000);
    }

    stop() {
      // Stop background work and invalidate the live indicator, retaining the
      // last position/details for inspection. DOM/map listeners remain attached.
      this.running = false;
      this.clearTimeout(this.pollTimer);
      this.clearTimeout(this.watchdog);
      if (this.request) this.request.abort();
      this.available = false;
      this.render();
    }

    async poll() {
      // A recursive timeout starts the next poll only after this one finishes;
      // the request guard also rejects extra calls while work is in flight.
      if (!this.running || this.request) return;
      const controller = new this.AbortController();
      this.request = controller;
      let timeout;
      try {
        // The race also bounds response.json(), not just the initial headers.
        const result = await Promise.race([
          (async () => {
            const response = await this.fetch('/api/gps', {
              cache: 'no-store', signal: controller.signal
            });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data = await response.json();
            // Reject a wrong endpoint/response shape before replacing the last
            // good snapshot; individual coordinate/measurement fields are
            // checked where used below.
            if (!data || typeof data.detected !== 'boolean' ||
                typeof data.fix_valid !== 'boolean' || typeof data.status !== 'string') {
              throw new Error('Invalid GPS service response');
            }
            return data;
          })(),
          new Promise((resolve, reject) => {
            timeout = this.setTimeout(() => {
              controller.abort();
              reject(new Error('Request timed out'));
            }, this.timeoutMs);
          })
        ]);
        if (!this.running) return;
        this.data = result;
        this.receivedAt = this.now();
        this.available = true;
        this.serviceError = '';
        this.render();
        this.updateCamera();
      } catch (error) {
        if (!this.running) return;
        // A failed request must immediately remove live status. Preserve data
        // so a disconnect still leaves useful last-known receiver diagnostics.
        this.available = false;
        this.serviceError = error.name === 'AbortError' ? 'Request timed out' : error.message;
        this.render();
      } finally {
        this.clearTimeout(timeout);
        this.request = null;
        if (this.running) this.pollTimer = this.setTimeout(() => this.poll(), this.pollMs);
      }
    }

    elapsedSeconds() {
      // performance.now measures browser elapsed time independently of wall
      // clock corrections; the service supplies the original age, not a date
      // that would require the browser and receiver clocks to be synchronized.
      return Math.max(0, (this.now() - this.receivedAt) / 1000);
    }

    fixAge() {
      // Advance the backend's snapshot age locally between polls. A response
      // can be valid when received and become stale before another arrives.
      return this.data && Number.isFinite(this.data.fix_age_seconds)
        ? this.data.fix_age_seconds + this.elapsedSeconds() : null;
    }

    validFix() {
      // Never infer a current fix merely from coordinates left in a snapshot.
      // Both service validity and the browser's age/connection checks must pass.
      const age = this.fixAge();
      return !!(this.available && this.data && this.data.fix_valid &&
        this.data.connected && this.data.gps_detected && hasCoordinates(this.data) &&
        age !== null && age <= FRESH_FIX_SECONDS);
    }

    pauseFollowing() {
      // Used for map gestures and explicit search/route/map-selection changes.
      // Forgetting the camera position makes the next Use GPS fully recenter.
      this.following = false;
      this.lastCameraPosition = null;
      this.render();
    }

    useGps() {
      // Explicitly return from either a paused camera or a manual location to
      // GPS tracking. An unavailable fix can only be inspected, not navigated to.
      this.elements['gps-error'].hidden = true;
      if (!this.map) return this.showError('The map is not available yet.');
      if (!this.validFix()) {
        this.elements['gps-status-dialog'].showModal();
        return;
      }
      this.positionSource = 'gps';
      this.following = true;
      this.lastCameraPosition = null;
      this.render();
      this.updateCamera();
    }

    showError(message) {
      this.text('gps-error', message);
      this.elements['gps-error'].hidden = false;
    }

    goToCoordinates() {
      const latText = this.elements['gps-lat'].value.trim();
      const lonText = this.elements['gps-lon'].value.trim();
      const latitude = Number(latText);
      const longitude = Number(lonText);
      this.elements['gps-error'].hidden = true;
      // Number('') is zero, so reject empty fields separately from range checks.
      if (!latText || !lonText || !hasCoordinates({ latitude, longitude })) {
        return this.showError('Enter latitude from −90 to 90 and longitude from −180 to 180.');
      }
      if (!this.map) return this.showError('The map is not available yet.');
      this.following = false;
      this.positionSource = 'manual';
      // The form and status use latitude, longitude; MapLibre expects [lon, lat].
      this.manualPosition = [longitude, latitude];
      this.lastCameraPosition = null;
      this.render();
      this.map.flyTo({ center: this.manualPosition, zoom: 14 });
    }

    updateCamera() {
      // Only tracking moves the camera. A fresh but stationary fix still updates
      // diagnostics without restarting an animation every polling interval.
      if (!this.map || !this.following || this.positionSource !== 'gps' || !this.validFix()) return;
      const position = [this.data.longitude, this.data.latitude];
      if (this.lastCameraPosition && position.every((v, i) => v === this.lastCameraPosition[i])) return;
      if (this.lastCameraPosition) {
        this.map.easeTo({ center: position, duration: 800 });
      } else {
        // Initial acquisition/resume zooms close enough to inspect the position;
        // later movement retains the user's current zoom.
        this.map.flyTo({ center: position, zoom: Math.max(this.map.getZoom(), 14) });
      }
      this.lastCameraPosition = position;
    }

    text(id, value) {
      // Receiver sentences, device names and service errors are untrusted text.
      // Never interpolate them into HTML; avoid rewriting unchanged text nodes.
      const text = String(value);
      if (this.elements[id].textContent !== text) this.elements[id].textContent = text;
    }

    renderMarker(live) {
      // A DOM Marker survives map style changes, unlike a style-owned layer.
      // Its position source and live state are separate from camera following.
      if (!this.map) return;
      const manual = this.positionSource === 'manual';
      const position = manual ? this.manualPosition :
        (this.data && hasCoordinates(this.data) ? [this.data.longitude, this.data.latitude] : null);
      // Keep the last plotted position through service restarts with no coordinates.
      const point = position || this.lastGpsPosition;
      if (!point) return;
      if (!manual && position) this.lastGpsPosition = position;
      if (!this.marker) {
        this.markerElement = this.document.createElement('div');
        this.markerElement.className = 'gps-marker';
        const pin = this.document.createElement('span');
        pin.className = 'gps-marker-pin';
        pin.setAttribute('aria-hidden', 'true');
        this.markerLabel = this.document.createElement('span');
        this.markerLabel.className = 'gps-marker-label';
        this.markerElement.append(pin, this.markerLabel);
        this.markerPopup = new this.maplibre.Popup({ offset: 32 });
        this.marker = new this.maplibre.Marker({ element: this.markerElement, anchor: 'bottom' })
          .setLngLat(point).setPopup(this.markerPopup).addTo(this.map);
      }
      const usingGps = !manual && live;
      // Color is reinforced by visible text, an accessible name and the popup,
      // so a stale fix cannot be mistaken for GPS solely from pin appearance.
      const label = manual ? 'Manual location' : usingGps ? 'Live GPS location' : 'Last GPS location — no current fix';
      this.markerElement.classList.toggle('is-live', usingGps);
      this.markerElement.title = label;
      this.markerElement.setAttribute('aria-label', label);
      this.markerLabel.textContent = manual ? 'Manual' : usingGps ? 'GPS' : 'Last GPS';
      this.markerPopup.setText(`${label}: ${point[1].toFixed(6)}, ${point[0].toFixed(6)}`);
      this.marker.setLngLat(point);
    }

    render() {
      // Render from the latest snapshot plus current local age. The watchdog,
      // poll completion and user actions all use this same validity decision.
      const data = this.data || {};
      const live = this.validFix();
      const unavailable = !this.available;
      const status = unavailable ? (this.data || this.serviceError ? 'GPS service unavailable' : 'Checking GPS…') :
        live ? STATUS_LABELS.fix : data.status === 'fix' ? STATUS_LABELS.stale :
          (STATUS_LABELS[data.status] || data.status);
      const following = this.following && this.positionSource === 'gps';
      this.text('gps-summary', `${status}${live ? (following ? ' · Following' : ' · Map paused') : ''}`);
      this.elements['gps-locate'].hidden = !data.detected;
      this.elements['gps-locate'].disabled = !live || !this.map;
      this.elements['gps-locate'].setAttribute('aria-pressed', String(following && live));
      this.elements['gps-locate'].title = live ? 'Center on the receiver and follow GPS updates' : 'Waiting for a current GPS fix; open GPS status for details';
      this.text('gps-locate', following && live ? 'Following GPS' : 'Use GPS');
      this.text('gps-detail-status', status);
      this.text('gps-detail-message', unavailable ?
        (this.serviceError ? `Cannot reach the local GPS service: ${this.serviceError}. Retrying automatically.` : 'Contacting the local GPS service…') :
        (data.message || '—'));
      this.text('gps-detail-detected', unavailable ? 'Unknown (service unavailable)' : data.detected ? 'Yes' : 'No');
      this.text('gps-detail-connected', unavailable ? 'Unknown (service unavailable)' : data.connected ? 'Yes' : 'No');
      this.text('gps-detail-nmea', unavailable ? 'Unknown (service unavailable)' : data.gps_detected ? 'Yes' : 'No');
      // Keep current and historical coordinates distinct, including after a
      // service restart whose new snapshot has no accepted position yet.
      const coordinates = hasCoordinates(data) ? `${data.latitude.toFixed(6)}, ${data.longitude.toFixed(6)}` : null;
      const last = coordinates || (this.lastGpsPosition ? `${this.lastGpsPosition[1].toFixed(6)}, ${this.lastGpsPosition[0].toFixed(6)}` : 'None received');
      this.text('gps-detail-current', live ? coordinates : 'No current valid fix');
      this.text('gps-detail-last', last);
      const formatAge = age => age === null ? 'Unknown' : `${Math.floor(age)} seconds ago`;
      this.text('gps-detail-age', formatAge(this.fixAge()));
      const value = (v, unit = '') => Number.isFinite(v) ? `${v}${unit}` : 'Unknown';
      this.text('gps-detail-used', value(data.satellites_used));
      // Preserve per-talker counts: combined GN and individual constellation
      // reports can overlap, so summing all reports would overcount satellites.
      const satellites = data.satellites_in_view && typeof data.satellites_in_view === 'object'
        ? Object.entries(data.satellites_in_view).filter(([, count]) => Number.isFinite(count)) : [];
      this.text('gps-detail-view', satellites.length ? satellites.map(([talker, count]) => `${talker}: ${count}`).join(' · ') : 'Unknown');
      this.text('gps-detail-hdop', value(data.hdop));
      this.text('gps-detail-altitude', value(data.altitude_m, ' m'));
      this.text('gps-detail-port', data.port || 'None selected');
      this.text('gps-detail-baud', value(data.baud));
      this.text('gps-detail-data-age', formatAge(Number.isFinite(data.last_data_age_seconds) ? data.last_data_age_seconds + this.elapsedSeconds() : null));
      this.text('gps-detail-ports', Array.isArray(data.ports) && data.ports.length ?
        data.ports.map(port => `${port.device}${port.description ? ` — ${port.description}` : ''}`).join('\n') : 'None found');
      this.text('gps-detail-sentence', data.last_sentence || 'No valid sentence received');
      this.text('gps-detail-follow', this.positionSource === 'manual' ? 'Manual coordinates (red pin). Use GPS to resume.' :
        following ? 'Following GPS when a current fix is available. Pan the map to pause.' : 'Paused. Use GPS to recenter and follow.');
      this.renderMarker(live);
    }
  }

  // Use the same controller in the offline page and dependency-free Node tests.
  if (typeof module !== 'undefined' && module.exports) module.exports = { LibraryGpsControl, hasCoordinates };
  else root.LibraryGpsControl = LibraryGpsControl;
})(typeof window !== 'undefined' ? window : globalThis);
