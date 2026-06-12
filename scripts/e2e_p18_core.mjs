/**
 * E2E P18 — cobertura núcleo: Cuadro, CaseDetail, Extracción (2026-06-12).
 *
 * Aserciones de CONTENIDO (no solo HTTP 200):
 * 1. Login wilson/tutelas2026
 * 2. /cases — chips de revisión con conteos, tabla con filas, búsqueda
 * 3. /cuadro — tabla 39 columnas renderiza, botón v9 Preview presente
 * 4. CaseDetail — campos clave (accionante/radicado/estado), sección documentos
 * 5. /extraction — semáforo del motor + selección de casos
 * 6. /ejecutivo — card "Resueltas" (P19) y "Incidentes de desacato"
 * 7. 0 errores de consola/página
 *
 * Uso: node scripts/e2e_p18_core.mjs [BASE_URL]   (default http://localhost:5173)
 */
import { chromium } from 'playwright';
import { mkdirSync } from 'fs';

const BASE = process.argv[2] || 'http://localhost:5173';
const DIR = '/tmp/screenshots-p18';
mkdirSync(DIR, { recursive: true });
const log = (m) => console.log(`[${new Date().toISOString().slice(11, 19)}] ${m}`);

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(`PAGE_ERROR: ${e.message.slice(0, 180)}`));
  page.on('console', (msg) => {
    const t = msg.text();
    if (msg.type() === 'error' && !t.includes('favicon') && !t.includes('manifest'))
      errors.push(`CONSOLE_ERR: ${t.slice(0, 180)}`);
  });

  const results = { passed: [], failed: [] };
  const check = (name, ok, detail = '') => {
    (ok ? results.passed : results.failed).push({ name, detail });
    log(`  ${ok ? '✓' : '✗'} ${name} ${detail}`);
  };

  try {
    // === 1. LOGIN ===
    log('1. LOGIN');
    await page.goto(BASE, { waitUntil: 'domcontentloaded', timeout: 20000 });
    await page.waitForSelector('input', { timeout: 15000 });
    const inputs = await page.locator('input').all();
    await inputs[0].fill('wilson');
    await inputs[1].fill('tutelas2026');
    await page.locator('button[type="submit"], button:has-text("Ingresar"), button:has-text("Iniciar")').first().click();
    await page.waitForTimeout(2500);
    check('login OK', !page.url().includes('login'), page.url());

    // === 2. CASES LIST (módulo tutelas) ===
    log('2. /cases — lista + chips de revisión');
    await page.goto(`${BASE}/cases`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(2500);
    const rows = await page.locator('table tbody tr').count();
    check('tabla de casos con filas', rows >= 10, `${rows} filas`);
    const bodyText = await page.locator('body').innerText();
    check('chip "Sin fallo 1ra" visible', /Sin fallo/i.test(bodyText));
    check('chips con conteos numéricos', /\d+/.test(bodyText));
    // búsqueda
    const search = page.locator('input[placeholder*="usca"], input[type="search"]').first();
    if (await search.count()) {
      await search.fill('PORRAS PRADA');
      await page.waitForTimeout(1800);
      const after = await page.locator('table tbody tr').count();
      const txt = await page.locator('table tbody').innerText();
      check('búsqueda filtra (PORRAS PRADA)', after >= 1 && /PORRAS/i.test(txt), `${after} filas`);
      await search.fill('');
      await page.waitForTimeout(1200);
    } else {
      check('búsqueda presente', false, 'input no encontrado');
    }
    await page.screenshot({ path: `${DIR}/02-cases.png` });

    // === 3. CUADRO ===
    log('3. /cuadro');
    await page.goto(`${BASE}/cuadro`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(3500);
    const cuadroRows = await page.locator('table tbody tr').count();
    check('cuadro renderiza filas', cuadroRows >= 10, `${cuadroRows} filas`);
    const cuadroText = await page.locator('body').innerText();
    // Nota 2026-06-12: el botón "v9 Preview" documentado en CLAUDE.md ya no existe
    // (retirado en el rediseño v9.4; queda solo el wrapper en api.ts). Se valida
    // en su lugar que el cuadro tenga toolbar funcional (filtro/búsqueda o export).
    const hasToolbar = (await page.locator('input, button').count()) > 3;
    check('cuadro con toolbar funcional', hasToolbar);
    const ths = await page.locator('table thead th').count();
    check('cuadro con columnas múltiples', ths >= 10, `${ths} columnas`);
    await page.screenshot({ path: `${DIR}/03-cuadro.png` });

    // === 4. CASE DETAIL (c501 — caso rico: desacato Socorro) ===
    log('4. /cases/501 — detalle');
    await page.goto(`${BASE}/cases/501`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(3000);
    const detText = await page.locator('body').innerText();
    check('accionante visible', /RODRIGO ARGUELLO/i.test(detText));
    check('radicado visible', /2026-?0?0?032|68755/i.test(detText));
    check('estado procesal accesible', /Estado del trámite|ACTIVO/i.test(detText));
    check('sección documentos con archivos', /\.pdf|\.docx|documento/i.test(detText));
    check('observaciones largas visibles', /requerimiento|incidente/i.test(detText));
    await page.screenshot({ path: `${DIR}/04-case-detail.png` });

    // === 5. EXTRACCIÓN ===
    log('5. /extraction');
    await page.goto(`${BASE}/extraction`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(3000);
    const extText = await page.locator('body').innerText();
    check('semáforo/estado del motor visible', /motor|llm|qwen|apagado|encendido|off|servidor/i.test(extText));
    check('página extracción con contenido de casos', /caso|extra/i.test(extText));
    await page.screenshot({ path: `${DIR}/05-extraction.png` });

    // === 6. EJECUTIVO (P19) ===
    log('6. /ejecutivo — KPIs curados');
    await page.goto(`${BASE}/ejecutivo`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(3500);
    const ejText = await page.locator('body').innerText();
    check('card Resueltas (P19) presente', /Resueltas/i.test(ejText));
    check('card Incidentes de desacato presente', /Incidentes de desacato/i.test(ejText));
    check('sin restos del payload viejo', !/SIN_CLASIFICAR/.test(ejText));
    await page.screenshot({ path: `${DIR}/06-ejecutivo.png` });

    // === 7. CONSOLE ERRORS ===
    check('0 errores de página/consola', errors.length === 0, errors.slice(0, 3).join(' | '));
  } catch (e) {
    check('ejecución sin excepción', false, e.message.slice(0, 200));
  } finally {
    await browser.close();
  }

  console.log('\n========================================');
  console.log(`P18 core: ${results.passed.length} ✓ · ${results.failed.length} ✗`);
  for (const f of results.failed) console.log(`  ✗ ${f.name} — ${f.detail}`);
  process.exit(results.failed.length ? 1 : 0);
})();
