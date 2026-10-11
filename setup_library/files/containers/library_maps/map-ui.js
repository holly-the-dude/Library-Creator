/* Toggle presentation only: GPS tracking, routes and map state keep running. */
(function () {
  'use strict';

  const button  = document.getElementById('map-ui-toggle');
  const panels  = document.getElementById('map-panels');
  const preference = 'library-map-controls-visible';
  const mq = window.matchMedia('(max-width: 700px)');

  /* ── Desktop hide/show toggle ───────────────────────────────────────── */
  let visible = !mq.matches;
  try {
    const saved = window.localStorage.getItem(preference);
    if (saved === 'true' || saved === 'false') visible = saved === 'true';
  } catch (_) { /* Storage can be unavailable in private browsing. */ }

  function renderToggle() {
    if (!visible && panels.contains(document.activeElement)) button.focus();
    panels.hidden = !visible;
    document.body.classList.toggle('map-ui-hidden', !visible);
    button.textContent = visible ? 'Hide' : 'Show';
    button.setAttribute('aria-expanded', String(visible));
    button.setAttribute('aria-label', visible ? 'Hide map controls' : 'Show map controls');
  }

  button.addEventListener('click', () => {
    if (isMobile()) {
      routePanelSuspended = false;
      if (activePanel) closePanel();
      else openPanel(lastPanel.panelId, lastPanel.btnId);
      return;
    }
    visible = !visible;
    renderToggle();
    try { window.localStorage.setItem(preference, String(visible)); } catch (_) {}
  });

  /* ── Mobile bottom-nav panel system ────────────────────────────────── */
  //
  // On mobile (≤700 px) each control is *moved* into its dedicated sheet div
  // so the bottom nav bar can pop it up without duplicating markup.
  // On resize back to desktop the nodes are returned to their original parents.
  //
  const MOBILE_BREAKPOINT = 700;

  // Map of: nav button id → { panelId, sourceId }
  const NAV_MAP = [
    { btnId: 'mnav-map',    panelId: 'mpanel-map',    sourceId: 'controls'      },
    { btnId: 'mnav-search', panelId: 'mpanel-search', sourceId: 'search-control'},
    { btnId: 'mnav-gps',    panelId: 'mpanel-gps',    sourceId: 'gps-control'   },
    { btnId: 'mnav-route',  panelId: 'mpanel-route',  sourceId: 'route-control' },
    { btnId: 'mnav-layers', panelId: 'mpanel-layers', sourceId: 'layers-control'},
  ];

  // Track original parent/next-sibling so we can return nodes on resize.
  const origins = new Map(); // sourceId → { parent, nextSibling }

  const backdrop = document.getElementById('mobile-backdrop');
  let activePanel = null; // currently open mpanel-* id, or null
  let lastPanel = NAV_MAP[0];

  function isMobile() { return window.innerWidth <= MOBILE_BREAKPOINT; }

  function renderMobileToggle() {
    button.textContent = activePanel ? 'Hide' : 'Show';
    button.setAttribute('aria-expanded', String(Boolean(activePanel)));
    button.setAttribute('aria-controls', lastPanel.panelId);
    button.setAttribute('aria-label', activePanel ? 'Hide map controls' : 'Show map controls');
  }

  // Close whatever sheet is open.
  function closePanel() {
    if (!activePanel) return;
    const panel = document.getElementById(activePanel);
    if (panel && panel.contains(document.activeElement)) {
      document.getElementById(lastPanel.btnId).focus({ preventScroll: true });
    }
    if (panel) panel.classList.remove('is-open');
    backdrop.classList.remove('is-open');
    NAV_MAP.forEach(({ btnId }) => {
      const btn = document.getElementById(btnId);
      if (btn) btn.setAttribute('aria-pressed', 'false');
    });
    activePanel = null;
    if (isMobile()) renderMobileToggle();
  }

  // Open a specific sheet (or close if already open).
  function openPanel(panelId, btnId, focusTarget) {
    if (activePanel === panelId) { closePanel(); return; }
    closePanel();
    const panel = document.getElementById(panelId);
    if (!panel) return;
    panel.classList.add('is-open');
    backdrop.classList.add('is-open');
    const btn = document.getElementById(btnId);
    if (btn) btn.setAttribute('aria-pressed', 'true');
    activePanel = panelId;
    lastPanel = NAV_MAP.find(item => item.panelId === panelId);
    renderMobileToggle();
    // Opening a sheet must not summon the iPhone keyboard or scroll the page.
    const first = focusTarget || panel.querySelector('button');
    if (first) first.focus({ preventScroll: true });
  }

  // Let route point selection temporarily uncover the map on phones.
  let routePanelSuspended = false;
  document.addEventListener('library-route-pick-start', () => {
    if (!isMobile() || activePanel !== 'mpanel-route') return;
    routePanelSuspended = true;
    const panel = document.getElementById(activePanel);
    if (panel.contains(document.activeElement)) document.activeElement.blur();
    closePanel();
  });
  document.addEventListener('library-route-pick-end', (event) => {
    if (!routePanelSuspended) return;
    routePanelSuspended = false;
    if (!isMobile()) return;
    // Focus a button so iOS does not reopen the keyboard over the map.
    const nextButton = document.getElementById(
      event.detail.which === 'start' ? 'route-dest-pin' : 'route-go'
    );
    openPanel('mpanel-route', 'mnav-route', nextButton);
  });

  // Move source controls into their sheet panels for mobile.
  function attachMobile() {
    NAV_MAP.forEach(({ panelId, sourceId }) => {
      const src   = document.getElementById(sourceId);
      const dest  = document.getElementById(panelId);
      if (!src || !dest || dest.contains(src)) return;
      // Remember where to put it back.
      origins.set(sourceId, { parent: src.parentNode, nextSibling: src.nextSibling });
      dest.appendChild(src);
    });
    // Show the nav bar; make sure map-panels itself isn't blocking things.
    panels.hidden = false;
    document.body.classList.remove('map-ui-hidden');
    renderMobileToggle();
  }

  // Return controls to their original desktop positions.
  function detachMobile() {
    routePanelSuspended = false;
    closePanel();
    // Restore later siblings first so insertBefore always has a live anchor.
    [...NAV_MAP].reverse().forEach(({ sourceId }) => {
      const src = document.getElementById(sourceId);
      const origin = origins.get(sourceId);
      if (!src || !origin) return;
      if (origin.nextSibling) {
        origin.parent.insertBefore(src, origin.nextSibling);
      } else {
        origin.parent.appendChild(src);
      }
    });
    origins.clear();
    button.setAttribute('aria-controls', 'map-panels');
    renderToggle(); // restore desktop visible state
  }

  // Wire up nav tab buttons.
  NAV_MAP.forEach(({ btnId, panelId }) => {
    const btn = document.getElementById(btnId);
    if (!btn) return;
    btn.addEventListener('click', () => {
      if (!isMobile()) return;
      routePanelSuspended = false;
      openPanel(panelId, btnId);
    });
  });

  // A dedicated handle keeps dismissal separate from scrolling directions.
  NAV_MAP.forEach(({ panelId }) => {
    const panel = document.getElementById(panelId);
    if (!panel) return;
    const handle = document.createElement('button');
    handle.type = 'button';
    handle.className = 'mobile-panel-handle';
    handle.setAttribute('aria-label', 'Close menu');
    panel.prepend(handle);
    let swipe = null;
    handle.addEventListener('pointerdown', (event) => {
      if (!isMobile() || !event.isPrimary) return;
      swipe = { id: event.pointerId, x: event.clientX, y: event.clientY };
      handle.setPointerCapture(event.pointerId);
    });
    handle.addEventListener('pointerup', (event) => {
      if (!swipe || swipe.id !== event.pointerId) return;
      const dx = event.clientX - swipe.x;
      const dy = event.clientY - swipe.y;
      swipe = null;
      if (dy > 40 && dy > Math.abs(dx)) closePanel();
    });
    handle.addEventListener('pointercancel', () => { swipe = null; });
    handle.addEventListener('click', closePanel);
  });

  // Backdrop tap closes open panel.
  backdrop.addEventListener('click', closePanel);

  // Escape key closes open panel.
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && activePanel) closePanel();
  });

  // Respond to viewport changes (e.g. phone rotation, browser resize).
  let wasMobile = isMobile();
  function handleResize() {
    const nowMobile = isMobile();
    if (nowMobile === wasMobile) return;
    wasMobile = nowMobile;
    if (nowMobile) {
      attachMobile();
    } else {
      detachMobile();
    }
  }
  window.addEventListener('resize', handleResize);

  // Initial setup.
  if (isMobile()) {
    attachMobile();
  } else {
    renderToggle();
  }
})();
