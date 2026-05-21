/**
 * Smoke test rápido: verificar que otras páginas siguen funcionando tras
 * el cambio de PageShell + main.
 */
import { chromium } from 'playwright';
import { mkdirSync } from 'fs';
const BASE = 'http://localhost:5173';
const DIR = '/tmp/screenshots-smoke';
mkdirSync(DIR, { recursive: true });
const log = (m) => console.log(`[${new Date().toISOString().slice(11, 19)}] ${m}`);

(async () => {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(`PAGE_ERROR: ${e.message.slice(0, 200)}`));

  await page.goto(`${BASE}/login`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(800);
  const inputs = await page.locator('input').all();
  await inputs[0].fill('wilson');
  await inputs[1].fill('tutelas2026');
  await page.locator('button[type="submit"]').first().click();
  await page.waitForTimeout(2500);

  for (const path of ['/', '/cases', '/seguimiento', '/auditoria', '/alertas', '/reports']) {
    await page.goto(`${BASE}${path}`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(1500);
    // Verificar que se cargó algo
    const text = await page.locator('main').innerText().catch(() => '');
    const truncated = text.replace(/\s+/g, ' ').slice(0, 80);
    log(`${path}: ${truncated || '(vacío)'}`);
    await page.screenshot({ path: `${DIR}/${path.replace(/\//g, '_') || 'root'}.png`, fullPage: false });
  }
  if (errors.length) {
    log('ERRORES:');
    errors.forEach((e) => log(`  ${e}`));
  } else {
    log('Sin errores de página');
  }
  await ctx.close();
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
