/**
 * Verifica que TODOS los filtros muestren datos consistentes.
 * Para cada filtro, lee el conteo en la card + número de filas en la tabla.
 */
import { chromium } from 'playwright';
import { mkdirSync } from 'fs';
const BASE = 'http://localhost:5173';
const DIR = '/tmp/screenshots-filtros';
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
  await page.waitForTimeout(2500);

  const filtros = ['Todos', 'Vencido', 'Urgente', 'Por Vencer', 'En Plazo', 'En Proceso', 'Condicional', 'Sin Plazo', 'Impugnado', 'Cumplido', 'No Aplica'];
  for (const f of filtros) {
    await page.locator(`button:has-text("${f}")`).first().click();
    await page.waitForTimeout(800);
    const rows = await page.locator('table tbody tr').count();
    const radicados = await page.$$eval('table tbody tr', (els) =>
      els.slice(0, 3).map((tr) => {
        const radEl = tr.querySelector('.font-mono.font-bold');
        return radEl ? radEl.textContent : '?';
      })
    );
    log(`  Filtro "${f}": ${rows} filas. Primeros 3 rad: ${JSON.stringify(radicados)}`);
    await page.screenshot({ path: `${DIR}/${f.replace(/\s+/g, '_')}.png`, fullPage: false });
  }
  await ctx.close();
  await browser.close();
  log(`Screenshots: ${DIR}`);
})().catch((e) => { console.error(e); process.exit(1); });
