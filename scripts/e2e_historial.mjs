/**
 * Verifica el botón Historial + modal de audit log.
 */
import { chromium } from 'playwright';
import { mkdirSync } from 'fs';
const BASE = 'http://localhost:5173';
const DIR = '/tmp/screenshots-historial';
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

  // Click sobre primer botón "Historial"
  await page.locator('button:has-text("Historial")').first().click();
  await page.waitForTimeout(1500);
  await page.screenshot({ path: `${DIR}/01-modal-historial.png`, fullPage: false });

  // Verificar título
  const titulo = await page.locator('h2:has-text("Historial del expediente")').textContent().catch(() => null);
  log(`Título: ${titulo}`);

  // Contar eventos
  const eventos = await page.locator('ol li').count();
  log(`Eventos visibles: ${eventos}`);

  // Probar filtros
  for (const f of ['Estado / Notas', 'Documentos', 'Extracción', 'Génesis']) {
    await page.locator(`button:has-text("${f}")`).first().click();
    await page.waitForTimeout(800);
    const n = await page.locator('ol li').count();
    log(`Filtro "${f}": ${n} eventos`);
  }
  await page.screenshot({ path: `${DIR}/02-filtros.png`, fullPage: false });

  // Cerrar
  await page.locator('button:has-text("Cerrar")').last().click();
  await page.waitForTimeout(500);

  // Probar también desde CaseDetail (icono History en top bar)
  await page.goto(`${BASE}/cases/317`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2500);
  // Botón History está en top bar — buscar por title
  const historyBtn = await page.locator('button[title*="historial"]').first();
  await historyBtn.click();
  await page.waitForTimeout(1500);
  await page.screenshot({ path: `${DIR}/03-historial-casedetail.png`, fullPage: false });
  const eventosCD = await page.locator('ol li').count();
  log(`Eventos en CaseDetail#317: ${eventosCD}`);

  await ctx.close();
  await browser.close();
  log(`Screenshots: ${DIR}`);
})().catch((e) => { console.error(e); process.exit(1); });
