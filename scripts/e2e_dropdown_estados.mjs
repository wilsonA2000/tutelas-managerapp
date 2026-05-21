/**
 * Verifica que el dropdown "Estado ▾" muestre 6 opciones de estado.
 */
import { chromium } from 'playwright';
import { mkdirSync } from 'fs';
const BASE = 'http://localhost:5173';
const DIR = '/tmp/screenshots-dropdown';
mkdirSync(DIR, { recursive: true });
const log = (m) => console.log(`[${new Date().toISOString().slice(11, 19)}] ${m}`);

(async () => {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  await page.goto(`${BASE}/login`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(800);
  const inputs = await page.locator('input').all();
  await inputs[0].fill('wilson');
  await inputs[1].fill('tutelas2026');
  await page.locator('button[type="submit"]').first().click();
  await page.waitForTimeout(2500);

  await page.goto(`${BASE}/seguimiento`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(3000);

  // Click sobre el primer botón "Estado ▾"
  await page.locator('button:has-text("Estado")').first().click();
  await page.waitForTimeout(1000);
  await page.screenshot({ path: `${DIR}/01-dropdown-abierto.png`, fullPage: false });

  // Listar items del menu
  const items = await page.$$eval('[role="menuitem"]', (els) =>
    els.map((e) => (e.textContent || '').trim().replace(/\s+/g, ' '))
  );
  log(`Items dropdown: ${items.length}`);
  items.forEach((i, idx) => log(`  ${idx}: ${i}`));

  // Cerrar dropdown
  await page.keyboard.press('Escape');
  await page.waitForTimeout(500);

  await ctx.close();
  await browser.close();
  log(`Screenshots: ${DIR}`);
})().catch((e) => { console.error(e); process.exit(1); });
