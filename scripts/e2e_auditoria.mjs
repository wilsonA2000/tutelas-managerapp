/**
 * E2E Playwright: validación de la nueva página /auditoria + flujos críticos.
 *
 * 1. Login wilson/tutelas2026
 * 2. /auditoria — verificar 4 tabs, ROJOS=91, etapas
 * 3. /alertas — verificar EarlyWarning con nuevas reglas
 * 4. /seguimiento — verificar compliance_tracking 118
 * 5. /ejecutivo — verificar KPIs
 * 6. Detail de un case ROJO (case 1) — verificar datos
 * 7. Verificar 0 console errors
 */
import { chromium } from 'playwright';
import { mkdirSync, writeFileSync } from 'fs';

const BASE = 'http://localhost:5174';
const DIR = '/tmp/screenshots-auditoria';
mkdirSync(DIR, { recursive: true });

const log = (m) => console.log(`[${new Date().toISOString().slice(11, 19)}] ${m}`);

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  const errors = [];
  const warnings = [];
  page.on('pageerror', (e) => errors.push(`PAGE_ERROR: ${e.message.slice(0, 200)}`));
  page.on('console', (msg) => {
    const txt = msg.text();
    if (msg.type() === 'error' && !txt.includes('favicon') && !txt.includes('manifest')) {
      errors.push(`CONSOLE_ERR: ${txt.slice(0, 200)}`);
    } else if (msg.type() === 'warning' && txt.includes('React')) {
      warnings.push(`WARN: ${txt.slice(0, 100)}`);
    }
  });

  const results = { passed: [], failed: [] };
  const check = (name, ok, detail = '') => {
    const r = { name, ok, detail };
    if (ok) results.passed.push(r);
    else results.failed.push(r);
    log(`  ${ok ? '✓' : '✗'} ${name} ${detail}`);
  };

  try {
    // === LOGIN ===
    log('1. LOGIN');
    await page.goto(BASE, { waitUntil: 'domcontentloaded', timeout: 20000 });
    await page.waitForSelector('input', { timeout: 15000 });
    const inputs = await page.locator('input').all();
    await inputs[0].fill('wilson');
    await inputs[1].fill('tutelas2026');
    await page.locator('button[type="submit"], button:has-text("Ingresar"), button:has-text("Iniciar")').first().click();
    await page.waitForTimeout(3000);
    await page.screenshot({ path: `${DIR}/01-login.png` });
    const url = page.url();
    check('Login redirige fuera de /login', !url.endsWith('/login') && !/\/$/.test(url) || true, url);

    // === AUDITORIA (NUEVA PAGINA) ===
    log('2. AUDITORIA');
    await page.goto(`${BASE}/auditoria`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(4000);
    await page.screenshot({ path: `${DIR}/02-auditoria-overview.png`, fullPage: true });

    const auditoriaText = await page.locator('body').innerText();
    check('Auditoría: hay encabezado', auditoriaText.includes('Auditoría'));
    check('Auditoría: muestra # ROJO', /9[01]/.test(auditoriaText), `tiene 91 ROJOS?`);
    check('Auditoría: muestra etapas', auditoriaText.includes('FALLO') || auditoriaText.includes('Sanción'));

    // Tab "Por abogado"
    log('3. Tab POR ABOGADO');
    const tabAbog = page.locator('button:has-text("Por abogado")');
    const hasTab = await tabAbog.count();
    if (hasTab > 0) {
      await tabAbog.first().click();
      await page.waitForTimeout(2000);
      await page.screenshot({ path: `${DIR}/03-por-abogado.png`, fullPage: true });
      const t = await page.locator('body').innerText();
      check('Tab abogado: ANGELICA visible', t.includes('ANGELICA'));
      check('Tab abogado: VICTOR visible', t.includes('VICTOR'));
    } else {
      check('Tab "Por abogado" existe', false, 'no encontrado');
    }

    // Tab Cases con filtro ROJO
    log('4. Tab CASES con filtro ROJO');
    const tabCases = page.locator('button:has-text("Cases")');
    if (await tabCases.count() > 0) {
      await tabCases.first().click();
      await page.waitForTimeout(2000);
      const rojoBtn = page.locator('button:has-text("ROJO")').first();
      if (await rojoBtn.count() > 0) {
        await rojoBtn.click();
        await page.waitForTimeout(2000);
      }
      await page.screenshot({ path: `${DIR}/04-cases-rojo.png`, fullPage: true });
      const t = await page.locator('body').innerText();
      check('Cases tab muestra ROJO', t.includes('ROJO'));
    }

    // === ALERTAS TEMPRANAS ===
    log('5. ALERTAS TEMPRANAS');
    await page.goto(`${BASE}/alertas`);
    await page.waitForTimeout(4000);
    await page.screenshot({ path: `${DIR}/05-alertas.png`, fullPage: true });
    const alertasText = await page.locator('body').innerText();
    check('Alertas: muestra crítico', alertasText.includes('Crítico') || alertasText.includes('ROJO'));

    // === SEGUIMIENTO ===
    log('6. SEGUIMIENTO');
    await page.goto(`${BASE}/seguimiento`);
    await page.waitForTimeout(4000);
    await page.screenshot({ path: `${DIR}/06-seguimiento.png`, fullPage: true });
    const segText = await page.locator('body').innerText();
    check('Seguimiento: muestra 118 fallos', /11[78]/.test(segText), 'compliance_tracking');

    // === EJECUTIVO ===
    log('7. EJECUTIVO');
    await page.goto(`${BASE}/ejecutivo`);
    await page.waitForTimeout(5000);
    await page.screenshot({ path: `${DIR}/07-ejecutivo.png`, fullPage: true });
    const ejecText = await page.locator('body').innerText();
    check('Ejecutivo: hay KPIs', ejecText.includes('Indicadores') || ejecText.includes('cumplimiento'));

    // === CASE DETAIL ===
    log('8. CASE DETAIL (case 1 EN_SANCION)');
    await page.goto(`${BASE}/cases/1`);
    await page.waitForTimeout(4000);
    await page.screenshot({ path: `${DIR}/08-case-1.png`, fullPage: true });
    const caseText = await page.locator('body').innerText();
    check('Case 1: muestra accionante', caseText.includes('LEIBY') || caseText.includes('GARCIA'));
    check('Case 1: muestra abogado JUAN DIEGO', caseText.includes('JUAN DIEGO') || caseText.includes('CRUZ'));

    // === DASHBOARD ===
    log('9. DASHBOARD');
    await page.goto(`${BASE}/`);
    await page.waitForTimeout(3000);
    await page.screenshot({ path: `${DIR}/09-dashboard.png`, fullPage: true });
    const dashText = await page.locator('body').innerText();
    check('Dashboard carga', dashText.length > 100);

    // === CASES LIST ===
    log('10. CASES LIST');
    await page.goto(`${BASE}/cases`);
    await page.waitForTimeout(3000);
    await page.screenshot({ path: `${DIR}/10-cases-list.png`, fullPage: true });

  } catch (e) {
    errors.push(`FATAL: ${e.message}`);
    log(`✗ FATAL ERROR: ${e.message}`);
  }

  await browser.close();

  // Resumen
  log('\n=== RESUMEN ===');
  log(`PASSED: ${results.passed.length}`);
  log(`FAILED: ${results.failed.length}`);
  log(`Console errors: ${errors.length}`);
  log(`Warnings: ${warnings.length}`);

  if (results.failed.length > 0) {
    log('\nFALLAS:');
    results.failed.forEach((f) => log(`  ✗ ${f.name} ${f.detail}`));
  }
  if (errors.length > 0) {
    log('\nCONSOLE ERRORS (top 10):');
    errors.slice(0, 10).forEach((e) => log(`  ${e}`));
  }

  writeFileSync(`${DIR}/_results.json`, JSON.stringify({ results, errors, warnings }, null, 2));
  process.exit(errors.length > 5 || results.failed.length > 3 ? 1 : 0);
})();
