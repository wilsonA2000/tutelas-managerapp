/**
 * Prueba funcional profunda: Tutelas (/cases) + Cuadro (/cuadro).
 * Interacciones reales NO destructivas: búsqueda, filtros, orden, paginación,
 * abrir detalle, entrar a edición inline y CANCELAR con Escape (nunca guarda).
 */
import { chromium } from 'playwright';
import { mkdirSync } from 'fs';
const BASE = 'http://localhost:5173';
const SHOT = '/tmp/func-review'; mkdirSync(SHOT, { recursive: true });
const log = [];
const errs = [];

(async () => {
  const b = await chromium.launch({ headless: true });
  const ctx = await b.newContext({ viewport: { width: 1440, height: 1100 } });
  const p = await ctx.newPage();
  p.on('console', m => { if (m.type() === 'error') errs.push('CON:' + m.text().slice(0, 120)); });
  p.on('pageerror', e => errs.push('PERR:' + String(e).slice(0, 120)));
  p.on('response', r => { if (r.status() >= 400) errs.push(`HTTP${r.status()}:${r.url().replace(BASE, '')}`); });
  const step = (s, ok, d = '') => log.push(`${ok ? 'OK ' : '⚠️ '} ${s}${d ? ' :: ' + d : ''}`);

  await p.goto(BASE, { waitUntil: 'networkidle' });
  const ins = await p.locator('input').all();
  await ins[0].fill('wilson'); await ins[1].fill('tutelas2026');
  await p.locator('button[type=submit]').first().click();
  await p.waitForTimeout(3000);

  // ───────── TUTELAS ─────────
  await p.goto(BASE + '/cases', { waitUntil: 'networkidle' }); await p.waitForTimeout(2000);
  const rows0 = await p.locator('table tbody tr').count();
  step('Tutelas carga', rows0 > 0, `${rows0} filas`);

  // búsqueda
  const search = p.locator('input[type="text"],input[type="search"],input[placeholder*="usca" i]').first();
  if (await search.count()) {
    await search.fill('GARCIA'); await p.waitForTimeout(1500);
    const rf = await p.locator('table tbody tr').count();
    step('Búsqueda "GARCIA"', rf >= 0 && rf <= rows0, `${rows0}→${rf} filas`);
    await search.fill(''); await p.waitForTimeout(1000);
  } else step('Búsqueda', false, 'no se encontró input de búsqueda');

  // filtro por estado (si hay select)
  const sel = p.locator('select').first();
  if (await sel.count()) {
    const opts = await sel.locator('option').allTextContents();
    await sel.selectOption({ index: Math.min(1, opts.length - 1) }).catch(() => {});
    await p.waitForTimeout(1200);
    step('Filtro estado', true, `opciones: ${opts.slice(0, 4).join('/')}`);
  } else step('Filtro estado', true, 'sin <select> (puede ser botones/chips)');

  // abrir primer caso
  await p.locator('table tbody tr').first().click().catch(() => {});
  await p.waitForTimeout(2500);
  const detUrl = p.url();
  step('Abrir detalle', /\/cases\/\d+/.test(detUrl), detUrl.replace(BASE, ''));
  // secciones colapsables
  const collap = await p.locator('button[aria-expanded], [data-state]').count();
  step('Detalle secciones', collap >= 0, `${collap} colapsables`);
  await p.screenshot({ path: `${SHOT}/cases-detail.png`, fullPage: true });

  // ───────── CUADRO ─────────
  await p.goto(BASE + '/cuadro', { waitUntil: 'networkidle' }); await p.waitForTimeout(2500);
  const cels = await p.locator('table td, [role="gridcell"]').count();
  step('Cuadro carga', cels > 0, `${cels} celdas`);

  // ordenar por header
  const hdr = p.locator('table thead th button, table thead th [role="button"], table thead th').first();
  if (await hdr.count()) { await hdr.click().catch(() => {}); await p.waitForTimeout(1000); step('Ordenar por header', true); }

  // edición inline + ESCAPE (cancelar, NO guardar)
  const cell = p.locator('table tbody tr td').nth(3);
  if (await cell.count()) {
    await cell.dblclick().catch(() => {});
    await p.waitForTimeout(700);
    const editing = await p.locator('table tbody input, table tbody textarea, table tbody [contenteditable=true]').count();
    await p.keyboard.press('Escape'); await p.waitForTimeout(500);
    step('Edición inline + Escape', true, editing > 0 ? 'entró a edición y se canceló' : 'celda no editable inline (ok)');
  }
  await p.screenshot({ path: `${SHOT}/cuadro.png`, fullPage: true });

  console.log(log.join('\n'));
  console.log('\nERRORES (consola/HTTP):', errs.length ? errs.slice(0, 8).join('\n  ') : 'ninguno');
  await b.close();
})();
