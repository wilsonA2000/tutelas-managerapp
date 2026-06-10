/**
 * e2e_module_review.mjs — Revisión profunda de UN módulo (uso: node e2e_module_review.mjs /ruta)
 * Login real, navega, captura: errores consola JS, HTTP 4xx/5xx, stats de contenido,
 * elementos interactivos. Screenshots en /tmp/module-review/. NO dispara acciones destructivas.
 */
import { chromium } from 'playwright';
import { mkdirSync } from 'fs';

const ROUTE = process.argv[2] || '/seguimiento';
const BASE = 'http://localhost:5173';
const SHOT = '/tmp/module-review';
mkdirSync(SHOT, { recursive: true });
const slug = ROUTE.replace(/\//g, '_') || 'root';

const consoleErrors = [];
const httpErrors = [];

(async () => {
  const b = await chromium.launch({ headless: true });
  const ctx = await b.newContext({ viewport: { width: 1440, height: 1100 } });
  const p = await ctx.newPage();
  p.on('console', m => { if (m.type() === 'error') consoleErrors.push(m.text().slice(0, 200)); });
  p.on('response', r => { if (r.status() >= 400) httpErrors.push(`${r.status()} ${r.url().replace(BASE, '')}`); });
  p.on('pageerror', e => consoleErrors.push('PAGEERROR: ' + String(e).slice(0, 200)));

  // login
  await p.goto(BASE, { waitUntil: 'networkidle', timeout: 20000 });
  const ins = await p.locator('input').all();
  await ins[0].fill('wilson'); await ins[1].fill('tutelas2026');
  await p.locator('button[type=submit]').first().click();
  await p.waitForTimeout(3000);

  // navegar al módulo
  await p.goto(BASE + ROUTE, { waitUntil: 'networkidle', timeout: 25000 });
  await p.waitForTimeout(2500);

  const txt = (await p.locator('body').innerText());
  const stats = {
    route: ROUTE,
    url: p.url(),
    textLen: txt.length,
    tablas: await p.locator('table').count(),
    filas: await p.locator('table tbody tr').count(),
    botones: await p.locator('button').count(),
    inputs: await p.locator('input, select').count(),
    svg_charts: await p.locator('svg, canvas').count(),
    tabs: await p.locator('[role=tab]').count(),
    badValues: /\bNaN\b|undefined|\[object Object\]/.test(txt),
  };
  await p.screenshot({ path: `${SHOT}/${slug}.png`, fullPage: true });

  // primera porción de texto visible (para ver qué muestra)
  const head = txt.replace(/\s+/g, ' ').slice(0, 500);

  console.log(JSON.stringify({ stats, head, consoleErrors, httpErrors }, null, 2));
  await b.close();
})();
