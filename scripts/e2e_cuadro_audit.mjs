/**
 * E2E v8.3: Cuadro con bandas + Seguimiento mini-timeline + Export-audit XLSX.
 *
 * Requiere backend (8000) y frontend (5173) levantados.
 * Uso:
 *     bash start.sh   # en otra terminal
 *     node scripts/e2e_cuadro_audit.mjs
 */
import { chromium } from 'playwright';
import { mkdirSync, existsSync, statSync } from 'fs';

const BASE = 'http://localhost:5173';
const DIR = '/tmp/screenshots-v83';
mkdirSync(DIR, { recursive: true });

const log = (m) => console.log(`[${new Date().toISOString().slice(11, 19)}] ${m}`);

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1600, height: 1000 },
    acceptDownloads: true,
  });
  const page = await context.newPage();

  const errors = [];
  page.on('pageerror', (e) => errors.push(`PAGE_ERROR: ${e.message.slice(0, 200)}`));
  page.on('console', (msg) => {
    if (msg.type() === 'error') errors.push(`CONSOLE_ERR: ${msg.text().slice(0, 200)}`);
  });

  const results = [];
  const check = (name, ok, detail = '') => {
    results.push({ name, ok, detail });
    log(`${ok ? '✓' : '✗'} ${name} ${detail ? '— ' + detail : ''}`);
  };

  try {
    // Login
    log('Login wilson/tutelas2026');
    await page.goto(`${BASE}/login`);
    await page.fill('input[name="username"], input[type="text"]', 'wilson');
    await page.fill('input[name="password"], input[type="password"]', 'tutelas2026');
    await page.click('button[type="submit"]');
    await page.waitForURL(/\/(dashboard|cases|$)/, { timeout: 10000 });

    // 1. /cuadro
    log('Navegando a /cuadro');
    await page.goto(`${BASE}/cuadro`);
    await page.waitForSelector('table', { timeout: 15000 });
    await page.screenshot({ path: `${DIR}/01_cuadro.png`, fullPage: false });

    const rowCount = await page.$$eval('tbody tr', (rows) => rows.length);
    check('Cuadro carga con filas', rowCount > 100, `${rowCount} filas`);

    // Banda de confianza visible (cells con borde amarillo o rojo)
    const yellowCells = await page.$$eval('td.bg-amber-50, td.bg-red-50', (els) => els.length);
    check('Bandas REVISAR/BAJO renderizadas', yellowCells > 0, `${yellowCells} celdas con banda`);

    // Filtro "Solo findings"
    log('Toggle "Solo findings"');
    await page.click('button:has-text("Solo findings")');
    await page.waitForTimeout(500);
    const filteredCount = await page.$$eval('tbody tr', (rows) => rows.length);
    check('Filtro Solo findings reduce filas', filteredCount > 0 && filteredCount <= rowCount,
          `${rowCount} -> ${filteredCount}`);
    await page.screenshot({ path: `${DIR}/02_cuadro_filtered.png`, fullPage: false });

    // 2. /seguimiento
    log('Navegando a /seguimiento');
    await page.goto(`${BASE}/seguimiento`);
    await page.waitForSelector('table', { timeout: 15000 });
    await page.screenshot({ path: `${DIR}/03_seguimiento.png`, fullPage: false });

    // Mini-timeline visible (los 5 stages: 1ra, Imp, 2da, Inc, OK)
    const timelineStages = await page.$$eval(
      'tbody span[title]',
      (els) => els.filter(e => /^(1ra|Imp|2da|Inc|OK)$/.test(e.textContent || '')).length,
    );
    check('Mini-timeline visible en filas', timelineStages > 0,
          `${timelineStages} marcadores de etapa`);

    // 3. Export-audit XLSX
    log('Descargando export-audit');
    const downloadPromise = page.waitForEvent('download', { timeout: 30000 });
    await page.evaluate(async () => {
      const res = await fetch('/api/cases/export-audit', { credentials: 'include' });
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'audit_test.xlsx';
      document.body.appendChild(a);
      a.click();
      a.remove();
    });
    const download = await downloadPromise;
    const path = await download.path();
    if (path && existsSync(path)) {
      const size = statSync(path).size;
      check('Export-audit XLSX descargable', size > 5000, `${size} bytes`);
    } else {
      check('Export-audit XLSX descargable', false, 'no se descargó');
    }

    // 4. Errores de consola
    check('Sin errores de consola', errors.length === 0,
          errors.length ? errors.slice(0, 3).join(' | ') : '0 errores');
  } catch (e) {
    check('E2E sin excepciones', false, String(e).slice(0, 200));
    await page.screenshot({ path: `${DIR}/error_state.png`, fullPage: true });
  }

  await browser.close();

  const passed = results.filter((r) => r.ok).length;
  const total = results.length;
  log(`\n=== RESULTADO ${passed}/${total} ===`);
  if (passed < total) {
    console.log('\nFALLAS:');
    for (const r of results.filter((r) => !r.ok)) {
      console.log(`  ✗ ${r.name} — ${r.detail}`);
    }
  }
  console.log(`\nCapturas en ${DIR}/`);
  process.exit(passed === total ? 0 : 1);
})();
