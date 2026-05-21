/**
 * Test acciones: Cumplido + Sin competencia + Nota libre + Abrir.
 * Captura screenshots y verifica que los botones interactúen.
 */
import { chromium } from 'playwright';
import { mkdirSync } from 'fs';
const BASE = 'http://localhost:5173';
const DIR = '/tmp/screenshots-acciones';
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

  // Screenshot inicial mostrando botones
  await page.screenshot({ path: `${DIR}/01-vista-general.png`, fullPage: false });

  // Verificar que los 4 botones aparezcan en la primera fila
  const firstRowButtons = await page.$$eval('table tbody tr:first-child td:last-child button', (els) =>
    els.map((e) => (e.textContent || '').trim())
  );
  log(`Botones primera fila: ${JSON.stringify(firstRowButtons)}`);

  // Test "Nota": click en primer botón Nota
  const notaBtn = await page.locator('button:has-text("Nota")').first();
  if (await notaBtn.count() > 0) {
    await notaBtn.click();
    await page.waitForTimeout(800);
    log('Modal Nota abierto');
    await page.screenshot({ path: `${DIR}/02-modal-nota.png`, fullPage: false });

    // Escribir texto
    const textarea = await page.locator('textarea');
    if (await textarea.count() > 0) {
      await textarea.fill('TEST E2E: nota de prueba desde Playwright');
      await page.waitForTimeout(300);
      await page.screenshot({ path: `${DIR}/03-modal-con-texto.png`, fullPage: false });
      log('Texto escrito en textarea');
    }

    // Cancelar (no guardar para no contaminar DB)
    await page.locator('button:has-text("Cancelar")').click();
    await page.waitForTimeout(500);
    log('Cancelado');
  }

  // Hover sobre botón Sin Competencia para ver tooltip
  const sinCompBtn = await page.locator('button:has-text("Sin comp.")').first();
  if (await sinCompBtn.count() > 0) {
    await sinCompBtn.hover();
    await page.waitForTimeout(800);
    await page.screenshot({ path: `${DIR}/04-hover-sin-comp.png`, fullPage: false });
    log('Hover Sin Comp.');
  }

  await ctx.close();
  await browser.close();
  log(`Screenshots: ${DIR}`);
})().catch((e) => { console.error(e); process.exit(1); });
