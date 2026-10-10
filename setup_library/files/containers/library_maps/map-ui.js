/* Toggle presentation only: GPS tracking, routes and map state keep running. */
(function () {
  'use strict';
  const button = document.getElementById('map-ui-toggle');
  const panels = document.getElementById('map-panels');
  const preference = 'library-map-controls-visible';
  let visible = !window.matchMedia('(max-width: 700px)').matches;
  try {
    const saved = window.localStorage.getItem(preference);
    if (saved === 'true' || saved === 'false') visible = saved === 'true';
  } catch (_) { /* Storage can be unavailable in private browsing. */ }

  function render() {
    // Move focus before hiding a control reached with the keyboard.
    if (!visible && panels.contains(document.activeElement)) button.focus();
    panels.hidden = !visible;
    document.body.classList.toggle('map-ui-hidden', !visible);
    button.textContent = visible ? 'Hide controls' : 'Show controls';
    button.setAttribute('aria-expanded', String(visible));
    button.setAttribute('aria-label', visible ? 'Hide map controls' : 'Show map controls');
  }
  button.addEventListener('click', () => {
    visible = !visible;
    render();
    try { window.localStorage.setItem(preference, String(visible)); } catch (_) {}
  });
  render();
})();
