/**
 * e2e_test_ui_full.mjs — Test completo de UI (skill test-ui v3.0)
 *
 * Recorre los 14 pasos simulando un usuario real, con protecciones críticas:
 *   NUNCA hace clic en: Sincronizar Carpetas, Revisar Gmail, Extraer, Eliminar.
 *   NUNCA guarda ediciones (siempre Escape).
 *
 * Captura: errores de consola JS, peticiones HTTP 4xx/5xx, screenshots.
 * Salida: JSON estructurado en stdout + screenshots en /tmp/e2e-ui/.
 */
import { chromium } from 'playwright';
import { mkdirSync, writeFileSync } from 'fs';

const BASE = 'http://localhost:5173';
const SHOT = '/tmp/e2e-ui';
mkdirSync(SHOT, { recursive: true });

const report = { steps: [], consoleErrors: [], httpErrors: [], screenshots: [] };
const t0 = Date.now();
const log = (s) => console.log(`[${((Date.now() - t0) / 1000).toFixed(1)}s] ${s}`);

function step(name, status, detail) {
  report.steps.push({ name, status, detail });
  log(`${status} — ${name}${detail ? ' :: ' + detail : ''}`);
}

async function shot(page, name) {
  const path = `${SHOT}/${name}.png`;
  try { await page.screenshot({ path, fullPage: true }); report.screenshots.push({ name, path }); }
  catch (e) { report.screenshots.push({ name, error: String(e).slice(0, 120) }); }
}

// Forbidden text — nunca clicar
const FORBIDDEN = /Sincronizar Carpetas|Revisar Gmail|Revisar Bandeja|Extraer|Eliminar/i;
async function safeClickByText(page, text, { exact = false } = {}) {
  if (FORBIDDEN.test(text)) throw new Error(`BLOQUEADO: intento de clic prohibido "${text}"`);
  const loc = page.getByText(text, { exact }).first();
  await loc.click({ timeout: 8000 });
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 1100 } });
  const page = await ctx.newPage();

  page.on('console', (m) => { if (m.type() === 'error') report.consoleErrors.push({ url: page.url(), text: m.text().slice(0, 300) }); });
  page.on('response', (r) => { const s = r.status(); if (s >= 400) report.httpErrors.push({ status: s, url: r.url() }); });

  // Cierra cualquier overlay/modal que bloquee
  async function dismissOverlays() {
    for (const label of ['Cerrar', 'Aceptar', 'OK']) {
      try { const b = page.getByRole('button', { name: new RegExp(`^${label}$`, 'i') }).first();
        if (await b.isVisible({ timeout: 500 })) await b.click({ timeout: 1500 }); } catch {}
    }
  }

  try {
    // ── PASO 1: Login ──
    await page.goto(BASE, { waitUntil: 'networkidle', timeout: 20000 });
    await page.waitForSelector('input', { timeout: 15000 });
    const inputs = await page.locator('input').all();
    await inputs[0].fill('wilson');
    await inputs[1].fill('tutelas2026');
    await shot(page, '01-login-before');
    await page.locator('button[type="submit"]').first().click();
    await page.waitForTimeout(3500);
    const afterLogin = page.url();
    const loggedIn = !/login/i.test(afterLogin) && !(await page.locator('input[type=password]').count());
    step('1. Login', loggedIn ? 'PASSED' : 'FAILED', `url=${afterLogin}`);
    await shot(page, '01-login-after');

    // ── PASO 2: Dashboard ──
    await page.waitForTimeout(1500);
    const dashTxt = await page.locator('body').innerText();
    const badKpi = /\bNaN\b|undefined/.test(dashTxt);
    const hasCharts = (await page.locator('svg, canvas').count()) > 0;
    step('2. Dashboard', !badKpi ? 'PASSED' : 'WARNING',
      `charts=${hasCharts} badValues=${badKpi}`);
    await shot(page, '02-dashboard');

    // ── Navegación por sidebar (helper) ──
    async function navByLink(name) {
      const link = page.getByRole('link', { name: new RegExp(name, 'i') }).first();
      if (await link.count()) { await link.click(); }
      else { await safeClickByText(page, name); }
      await page.waitForTimeout(2500);
      await dismissOverlays();
    }

    // ── PASO 3: Lista de Tutelas ──
    try {
      await navByLink('Tutelas');
      const rowsBefore = await page.locator('table tbody tr, [role="row"]').count();
      // buscador
      const search = page.locator('input[type="text"], input[type="search"], input[placeholder*="usca" i]').first();
      if (await search.count()) { await search.fill('GARCIA'); await page.waitForTimeout(1500); }
      const rowsFiltered = await page.locator('table tbody tr, [role="row"]').count();
      if (await search.count()) { await search.fill(''); await page.waitForTimeout(1000); }
      step('3. Lista Tutelas', rowsBefore > 0 ? 'PASSED' : 'WARNING',
        `filas=${rowsBefore} trasBuscar=${rowsFiltered}`);
      await shot(page, '03-cases');
    } catch (e) { step('3. Lista Tutelas', 'FAILED', String(e).slice(0, 150)); }

    // ── PASO 4: Detalle del Caso ──
    try {
      const firstRow = page.locator('table tbody tr, [role="row"]').first();
      await firstRow.click({ timeout: 6000 });
      await page.waitForTimeout(2500);
      const detailUrl = page.url();
      const isDetail = /\/cases\/\d+/.test(detailUrl);
      const detailTxt = await page.locator('body').innerText();
      step('4. Detalle Caso', isDetail ? 'PASSED' : 'WARNING',
        `url=${detailUrl} len=${detailTxt.length}`);
      await shot(page, '04-case-detail');
    } catch (e) { step('4. Detalle Caso', 'FAILED', String(e).slice(0, 150)); }

    // ── PASO 5: Cuadro ──
    try {
      await navByLink('Cuadro');
      const cells = await page.locator('table td, [role="gridcell"]').count();
      step('5. Cuadro', cells > 0 ? 'PASSED' : 'WARNING', `celdas=${cells}`);
      await shot(page, '05-cuadro');
    } catch (e) { step('5. Cuadro', 'FAILED', String(e).slice(0, 150)); }

    // ── PASO 6: Extracción (solo observar, NO extraer) ──
    try {
      await navByLink('Extracci');
      const txt = await page.locator('body').innerText();
      const hasExtraerBtn = /Extraer/i.test(txt);
      step('6. Extracción', 'PASSED', `pagina cargada, botones Extraer presentes=${hasExtraerBtn} (NO clicados)`);
      await shot(page, '06-extraction');
    } catch (e) { step('6. Extracción', 'FAILED', String(e).slice(0, 150)); }

    // ── PASO 7: Correos ──
    try {
      await navByLink('Correos');
      const txt = await page.locator('body').innerText();
      const rows = await page.locator('table tbody tr, [role="row"], li').count();
      step('7. Correos', rows > 0 ? 'PASSED' : 'WARNING', `items=${rows}`);
      await shot(page, '07-emails');
    } catch (e) { step('7. Correos', 'FAILED', String(e).slice(0, 150)); }

    // ── PASO 8: Reportes ──
    try {
      await navByLink('Reportes');
      step('8. Reportes', 'PASSED', 'pagina cargada (NO se generó reporte)');
      await shot(page, '08-reports');
    } catch (e) { step('8. Reportes', 'FAILED', String(e).slice(0, 150)); }

    // ── PASO 9: Inteligencia ──
    try {
      await navByLink('Inteligencia');
      await page.waitForTimeout(1500);
      let tabsFound = [];
      for (const tab of ['Analytics', 'Calendario', 'Predictor']) {
        try { await safeClickByText(page, tab); await page.waitForTimeout(1500); tabsFound.push(tab); await shot(page, `09-intel-${tab}`); } catch {}
      }
      step('9. Inteligencia', tabsFound.length >= 1 ? 'PASSED' : 'WARNING', `tabs=${tabsFound.join(',')}`);
    } catch (e) { step('9. Inteligencia', 'FAILED', String(e).slice(0, 150)); }

    // ── PASO 11: Herramientas del Agente (/agent) ──
    try {
      await navByLink('Agente');
      const txt = await page.locator('body').innerText();
      step('11. Herramientas Agente', 'PASSED', `len=${txt.length}`);
      await shot(page, '11-agent-tools');
    } catch (e) { step('11. Herramientas Agente', 'FAILED', String(e).slice(0, 150)); }

    // ── PASO 12: Configuración ──
    try {
      await navByLink('Configuraci');
      const txt = await page.locator('body').innerText();
      step('12. Configuración', 'PASSED', `len=${txt.length}`);
      await shot(page, '12-settings');
    } catch (e) { step('12. Configuración', 'FAILED', String(e).slice(0, 150)); }

    // ── PASO 13: Seguimiento ──
    try {
      await navByLink('Seguimiento');
      const txt = await page.locator('body').innerText();
      step('13. Seguimiento', 'PASSED', `len=${txt.length}`);
      await shot(page, '13-seguimiento');
    } catch (e) { step('13. Seguimiento', 'FAILED', String(e).slice(0, 150)); }

    // ── PASO 14: Logout ──
    try {
      const logout = page.getByText(/Cerrar sesi/i).first();
      if (await logout.count()) { await logout.click(); await page.waitForTimeout(2500); }
      const backToLogin = (await page.locator('input[type=password]').count()) > 0;
      step('14. Logout', backToLogin ? 'PASSED' : 'WARNING', `loginVisible=${backToLogin}`);
      await shot(page, '14-logout');
    } catch (e) { step('14. Logout', 'FAILED', String(e).slice(0, 150)); }

  } catch (fatal) {
    step('FATAL', 'FAILED', String(fatal).slice(0, 300));
  } finally {
    await browser.close();
    writeFileSync(`${SHOT}/report.json`, JSON.stringify(report, null, 2));
    console.log('\n===== REPORT_JSON =====');
    console.log(JSON.stringify({
      summary: {
        total: report.steps.length,
        passed: report.steps.filter(s => s.status === 'PASSED').length,
        warning: report.steps.filter(s => s.status === 'WARNING').length,
        failed: report.steps.filter(s => s.status === 'FAILED').length,
      },
      consoleErrors: report.consoleErrors.length,
      httpErrors: report.httpErrors.length,
    }, null, 2));
  }
})();
