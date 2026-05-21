/**
 * Verifica que el botón atrás en CaseDetail respete el origen.
 * Flujo: /seguimiento → click Abrir → /cases/N → click atrás → debería volver a /seguimiento.
 */
import { chromium } from 'playwright';
const BASE = 'http://localhost:5173';
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

  // ── Flujo 1: desde /seguimiento ──
  await page.goto(`${BASE}/seguimiento`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2500);
  log(`Estoy en: ${page.url()}`);

  await page.locator('button:has-text("Abrir")').first().click();
  await page.waitForTimeout(2000);
  log(`Tras click Abrir: ${page.url()}`);

  // Click botón atrás (ArrowLeft icon, title="Volver")
  await page.locator('button[title="Volver"]').click();
  await page.waitForTimeout(1500);
  log(`Tras click atrás: ${page.url()}`);

  if (page.url().endsWith('/seguimiento')) {
    log('✓ Volvió a /seguimiento — correcto');
  } else {
    log(`✗ Esperaba /seguimiento, obtuve ${page.url()}`);
  }

  // ── Flujo 2: desde /cuadro ──
  await page.goto(`${BASE}/cuadro`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2500);
  log(`\nAhora en: ${page.url()}`);
  // Click en algún case desde Cuadro (no necesariamente igual pero probemos)
  await page.goto(`${BASE}/cases/311`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2000);
  log(`En case 311: ${page.url()}`);

  await page.locator('button[title="Volver"]').click();
  await page.waitForTimeout(1500);
  log(`Tras click atrás: ${page.url()}`);
  if (page.url().endsWith('/cuadro')) {
    log('✓ Volvió a /cuadro');
  } else {
    log(`Volvió a: ${page.url()}`);
  }

  await ctx.close();
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
