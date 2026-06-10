/** Prueba funcional: Seguimiento, Auditoría, Correos, Inteligencia. Interacciones
 * seguras (pestañas, filtros, predictor). NUNCA "Escanear Fallos"/"Sincronizar Bandeja". */
import { chromium } from 'playwright';
import { mkdirSync } from 'fs';
const BASE = 'http://localhost:5173';
const SHOT = '/tmp/func-review'; mkdirSync(SHOT, { recursive: true });
const log = []; const errs = [];
const FORBIDDEN = /Escanear Fallos|Sincronizar|Revisar Bandeja|Revisar Gmail|Extraer|Eliminar|Generar Reporte/i;

(async () => {
  const b = await chromium.launch({ headless: true });
  const p = await (await b.newContext({ viewport: { width: 1440, height: 1100 } })).newPage();
  let route = '';
  p.on('console', m => { if (m.type() === 'error') errs.push(`[${route}] CON:` + m.text().slice(0, 100)); });
  p.on('pageerror', e => errs.push(`[${route}] PERR:` + String(e).slice(0, 100)));
  p.on('response', r => { if (r.status() >= 400) errs.push(`[${route}] HTTP${r.status()}:` + r.url().replace(BASE, '')); });
  const step = (s, ok, d = '') => log.push(`${ok ? 'OK ' : '⚠️ '} ${s}${d ? ' :: ' + d : ''}`);

  // helper: clic seguro en texto (pestaña/chip), bloquea acciones prohibidas
  async function safeClick(label) {
    if (FORBIDDEN.test(label)) { step('BLOQUEADO ' + label, false, 'acción prohibida'); return false; }
    const el = p.getByText(new RegExp(label, 'i')).first();
    if (await el.count()) { await el.click({ timeout: 4000 }).catch(() => {}); await p.waitForTimeout(1200); return true; }
    return false;
  }

  await p.goto(BASE, { waitUntil: 'networkidle' });
  const ins = await p.locator('input').all();
  await ins[0].fill('wilson'); await ins[1].fill('tutelas2026');
  await p.locator('button[type=submit]').first().click(); await p.waitForTimeout(3000);

  // ─── SEGUIMIENTO: filtrar por un estado del semáforo ───
  route = '/seguimiento'; await p.goto(BASE + route, { waitUntil: 'networkidle' }); await p.waitForTimeout(2000);
  const segFilas = await p.locator('table tbody tr').count();
  const clickedVenc = await safeClick('Vencidos|VENCIDOS');
  const segFilas2 = await p.locator('table tbody tr').count();
  step('Seguimiento filtro semáforo', true, `clickFiltro=${clickedVenc} filas ${segFilas}→${segFilas2}`);

  // ─── AUDITORÍA: 4 pestañas ───
  route = '/auditoria'; await p.goto(BASE + route, { waitUntil: 'networkidle' }); await p.waitForTimeout(2000);
  const tabsFound = [];
  for (const t of ['Cases', 'Por abogado', 'Por dependencia', 'Vista general']) {
    if (await safeClick(t)) tabsFound.push(t);
  }
  await p.screenshot({ path: `${SHOT}/auditoria-tabs.png`, fullPage: true });
  step('Auditoría pestañas', tabsFound.length >= 2, tabsFound.join('/'));

  // ─── CORREOS: filtros de estado ───
  route = '/emails'; await p.goto(BASE + route, { waitUntil: 'networkidle' }); await p.waitForTimeout(2000);
  const emClicked = [];
  for (const t of ['Pendiente', 'Asignado', 'Ignorado', 'Todos']) { if (await safeClick(t)) emClicked.push(t); }
  step('Correos filtros estado', emClicked.length >= 1, emClicked.join('/'));

  // ─── INTELIGENCIA: 3 pestañas + predictor ───
  route = '/intelligence'; await p.goto(BASE + route, { waitUntil: 'networkidle' }); await p.waitForTimeout(2000);
  const intelTabs = [];
  for (const t of ['Estadísticas', 'Calendario', 'Predicción']) { if (await safeClick(t)) intelTabs.push(t); }
  // probar predictor: input ciudad
  let predictor = 'no probado';
  const cityInput = p.locator('input[type="text"], input:not([type])').first();
  if (await cityInput.count()) {
    await cityInput.fill('Bucaramanga').catch(() => {});
    await p.waitForTimeout(800);
    // botón predecir (no es destructivo)
    const predBtn = p.getByRole('button', { name: /predec|calcular|consultar/i }).first();
    if (await predBtn.count()) { await predBtn.click().catch(() => {}); await p.waitForTimeout(2500); predictor = 'ejecutado'; }
    else predictor = 'input ok, sin botón claro';
  }
  await p.screenshot({ path: `${SHOT}/intelligence.png`, fullPage: true });
  step('Inteligencia pestañas+predictor', intelTabs.length >= 1, `tabs=${intelTabs.join('/')} predictor=${predictor}`);

  console.log(log.join('\n'));
  console.log('\nERRORES:', errs.length ? '\n  ' + errs.slice(0, 10).join('\n  ') : 'ninguno');
  await b.close();
})();
