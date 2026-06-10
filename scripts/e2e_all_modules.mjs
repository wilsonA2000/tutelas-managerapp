/**
 * e2e_all_modules.mjs — Revisión de TODOS los módulos del sidebar en orden (1 login).
 * Por cada ruta: stats de contenido + errores consola/HTTP. Screenshots en /tmp/module-review/.
 */
import { chromium } from 'playwright';
import { mkdirSync } from 'fs';
const BASE = 'http://localhost:5173';
const SHOT = '/tmp/module-review';
mkdirSync(SHOT, { recursive: true });

const ROUTES = [
  ['/', 'Panel principal'], ['/cases', 'Tutelas'], ['/cuadro', 'Cuadro'],
  ['/seguimiento', 'Seguimiento'], ['/auditoria', 'Auditoría fallos'], ['/emails', 'Correos'],
  ['/intelligence', 'Inteligencia'], ['/reports', 'Reportes'], ['/ejecutivo', 'Tablero ejecutivo'],
  ['/alertas', 'Alertas tempranas'], ['/extraction', 'Procesamiento v9'], ['/cleanup', 'Mantenimiento'],
  ['/agent', 'Herramientas IA'], ['/settings', 'Configuración'],
];

(async () => {
  const b = await chromium.launch({ headless: true });
  const ctx = await b.newContext({ viewport: { width: 1440, height: 1100 } });
  const p = await ctx.newPage();
  let curRoute = '';
  const errByRoute = {};
  p.on('console', m => { if (m.type() === 'error') (errByRoute[curRoute] ??= []).push('CON:' + m.text().slice(0, 120)); });
  p.on('pageerror', e => (errByRoute[curRoute] ??= []).push('PERR:' + String(e).slice(0, 120)));
  p.on('response', r => { if (r.status() >= 400) (errByRoute[curRoute] ??= []).push(`HTTP${r.status()}:${r.url().replace(BASE, '')}`); });

  await p.goto(BASE, { waitUntil: 'networkidle', timeout: 20000 });
  const ins = await p.locator('input').all();
  await ins[0].fill('wilson'); await ins[1].fill('tutelas2026');
  await p.locator('button[type=submit]').first().click();
  await p.waitForTimeout(3500);

  const results = [];
  for (const [route, label] of ROUTES) {
    curRoute = route;
    let ok = true, detail = '';
    try {
      await p.goto(BASE + route, { waitUntil: 'networkidle', timeout: 25000 });
      await p.waitForTimeout(1800);
      const txt = await p.locator('body').innerText();
      const filas = await p.locator('table tbody tr').count();
      const charts = await p.locator('svg, canvas').count();
      const bad = /\bNaN\b|undefined|\[object Object\]/.test(txt);
      const errs = errByRoute[route] || [];
      ok = errs.length === 0 && !bad && txt.length > 300;
      detail = `len=${txt.length} filas=${filas} charts=${charts} bad=${bad} errs=${errs.length}`;
      await p.screenshot({ path: `${SHOT}${route.replace(/\//g, '_') || '_root'}.png`, fullPage: true });
    } catch (e) { ok = false; detail = 'NAV_FAIL: ' + e.message.slice(0, 80); }
    const flag = ok ? 'OK ' : '⚠️ ';
    results.push(`${flag} ${label.padEnd(20)} ${route.padEnd(14)} ${detail}`);
    console.log(results[results.length - 1]);
    if ((errByRoute[route] || []).length) console.log('      ' + errByRoute[route].slice(0, 4).join(' | '));
  }
  await b.close();
})();
