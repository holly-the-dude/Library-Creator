// Optional real-browser integration test; requires Playwright and a running
// reader with a StreetZim map. GPS responses are synthetic, never hardware.
const assert = require('node:assert/strict');
const { chromium } = require('playwright');

(async () => {
  const base = process.env.STREET_ZIM_URL || 'http://localhost:8093';
  const allowedOrigin = new URL(base).origin;
  const browser = await chromium.launch({
    headless: true,
    ...(process.env.STREET_ZIM_BROWSER ? { executablePath: process.env.STREET_ZIM_BROWSER } : {}),
    args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader']
  });
  try {
    const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    // Prove the archive can render without internet/CDN dependencies.
    await context.route('**/*', route => new URL(route.request().url()).origin === allowedOrigin ?
      route.continue() : route.abort());
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(base);
    await page.waitForFunction(() => document.querySelector('#archive-status').textContent.includes('ready to explore'));
    const health = await page.request.get(`${base}/health`);
    assert.equal(health.status(), 200);
    await page.getByRole('link', { name: 'Open map library' }).click();
    const mapLink = page.locator('a.book__link').first();
    await mapLink.waitFor();
    let live = true;
    await page.route('**/api/gps', route => route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({ connected: true, gps_detected: true, fix_valid: live,
        latitude: 38.8895, longitude: -77.0353, fix_age_seconds: live ? 0.5 : 30,
        satellites_used: 8, message: live ? 'Synthetic test GPS fix' : 'Synthetic test fix is stale' })
    }));
    const tileLoaded = page.waitForResponse(r => /\/tiles\/.*\.pbf/.test(r.url()) && r.status() === 200);
    await mapLink.click();
    await page.waitForURL('**/content/**');
    await tileLoaded;
    await page.waitForSelector('#streetzim-library-gps[data-live="true"]');
    assert.equal(await page.evaluate(async () => (await navigator.permissions.query({name:'geolocation'})).state), 'granted');
    await page.locator('.maplibregl-ctrl-geolocate').click();
    await page.waitForFunction(() => window.__streetzimLastLoc?.lat === 38.8895);
    const initial = await page.evaluate(() => new Promise(resolve => navigator.geolocation.getCurrentPosition(resolve)));
    assert.equal(initial.coords.longitude, -77.0353);
    live = false;
    await page.waitForSelector('#streetzim-library-gps[data-live="false"]');
    const stale = await page.evaluate(() => new Promise(resolve => navigator.geolocation.getCurrentPosition(
      () => resolve('unexpected live fix'), error => resolve(error.code), { timeout: 1200 })));
    assert.equal(stale, 3);
    live = true;
    await page.waitForSelector('#streetzim-library-gps[data-live="true"]');
    await page.setViewportSize({ width: 390, height: 844 });
    assert.equal(await page.locator('#streetzim-library-gps').isVisible(), true);
    await page.goto(base);
    await page.waitForFunction(() => document.querySelector('#gps-state').textContent === 'Live fix');
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    assert.deepEqual(errors, []);
    console.log('PASS: real ZIM catalog/map/tiles, offline assets, MapLibre GPS, stale-fix rejection, recovery, mobile home.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
