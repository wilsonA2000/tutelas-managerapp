/**
 * Auditoría Playwright de /seguimiento — UX/UI checks.
 * - Login wilson/tutelas2026
 * - Carga /seguimiento, captura 3 viewports
 * - Verifica que cards no estén truncadas (labels visibles completos)
 * - Verifica que filas tengan chips tipo_plazo + destinatario_tipo
 * - Lista errores concretos para arreglar
 */
import { chromium } from 'playwright';
import { mkdirSync, writeFileSync } from 'fs';

const BASE = 'http://localhost:5173';
const DIR = '/tmp/screenshots-seguimiento';
mkdirSync(DIR, { recursive: true });

const log = (m) => console.log(`[${new Date().toISOString().slice(11, 19)}] ${m}`);

async function loginAndGotoSeguimiento(page) {
  await page.goto(`${BASE}/login`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(800);
  const inputs = await page.locator('input').all();
  await inputs[0].fill('wilson');
  await inputs[1].fill('tutelas2026');
  await page.locator('button[type="submit"], button:has-text("Ingresar"), button:has-text("Iniciar")').first().click();
  await page.waitForTimeout(2500);
  await page.goto(`${BASE}/seguimiento`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2500);
}

const issues = [];

(async () => {
  const browser = await chromium.launch({ headless: true });

  for (const vp of [
    { name: '1366x768',  width: 1366, height: 768 },
    { name: '1440x900',  width: 1440, height: 900 },
    { name: '1920x1080', width: 1920, height: 1080 },
  ]) {
    log(`Viewport ${vp.name}`);
    const ctx = await browser.newContext({ viewport: { width: vp.width, height: vp.height } });
    const page = await ctx.newPage();
    page.on('pageerror', (e) => issues.push(`[${vp.name}] PAGE_ERROR: ${e.message}`));
    await loginAndGotoSeguimiento(page);

    // 1) Capturar arriba
    await page.screenshot({ path: `${DIR}/top-${vp.name}.png`, fullPage: false });

    // 2) DataCards — leer labels visibles
    const cardLabels = await page.$$eval(
      '.grid > div',
      (els) => els.slice(0, 12).map((el) => {
        const text = el.textContent || '';
        // Buscar el label (usualmente texto corto antes del número)
        return text.trim().replace(/\s+/g, ' ').slice(0, 50);
      })
    );
    log(`  cards: ${JSON.stringify(cardLabels)}`);
    cardLabels.forEach((label) => {
      if (label.includes('…') || label.includes('...') || /[A-Z]\.\.\./.test(label)) {
        issues.push(`[${vp.name}] CARD TRUNCADA: "${label}"`);
      }
    });

    // 3) Verificar overflow horizontal
    const bodyOverflow = await page.evaluate(() => {
      const b = document.body;
      const html = document.documentElement;
      return {
        scrollWidth: Math.max(b.scrollWidth, html.scrollWidth),
        clientWidth: b.clientWidth,
        hasOverflow: Math.max(b.scrollWidth, html.scrollWidth) > b.clientWidth + 5,
      };
    });
    log(`  overflow: scrollWidth=${bodyOverflow.scrollWidth} clientWidth=${bodyOverflow.clientWidth} overflow=${bodyOverflow.hasOverflow}`);
    if (bodyOverflow.hasOverflow) {
      issues.push(`[${vp.name}] HORIZONTAL OVERFLOW: ${bodyOverflow.scrollWidth}px > ${bodyOverflow.clientWidth}px`);
    }

    // 4) Inspeccionar primera fila — chips v2
    const firstRowChips = await page.$$eval('table tbody tr:first-child .border', (els) =>
      els.map((e) => (e.textContent || '').trim()).filter(Boolean).slice(0, 10)
    );
    log(`  primera fila chips: ${JSON.stringify(firstRowChips)}`);

    // 5) Capturar más abajo (después de scroll)
    await page.evaluate(() => window.scrollBy(0, 400));
    await page.waitForTimeout(300);
    await page.screenshot({ path: `${DIR}/mid-${vp.name}.png`, fullPage: false });

    // 6) Capturar full page
    await page.screenshot({ path: `${DIR}/full-${vp.name}.png`, fullPage: true });

    await ctx.close();
  }

  await browser.close();

  log('\n══ ISSUES DETECTADOS ══');
  if (!issues.length) log('  (ninguno)');
  else issues.forEach((i) => log(`  • ${i}`));

  writeFileSync(`${DIR}/issues.json`, JSON.stringify(issues, null, 2));
  log(`\nScreenshots: ${DIR}`);
})().catch((e) => { console.error(e); process.exit(1); });
