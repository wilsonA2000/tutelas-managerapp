/**
 * Red de seguridad — smoke test del frontend (Fase 1 del plan de modernización).
 *
 * Hace login en la SPA, navega cada ruta de App.tsx, captura errores de consola /
 * pageerror, y prueba el endpoint del asistente jurídico (POST /api/chat/) — el
 * botón flotante se retiró. Reporta OK/FAIL por ruta. Exit 1 si hay algún FAIL.
 *
 * Requiere backend (:8000) y frontend (:5173) levantados, y el navegador de Playwright:
 *     cd frontend && npx playwright install chromium      # una sola vez
 *     node scripts/smoke_frontend.mjs
 *
 * Variables de entorno opcionales: FRONT_BASE (default http://localhost:5173),
 * SMOKE_USER (default wilson), SMOKE_PASS (default tutelas2026).
 */
import { chromium } from 'playwright';

const BASE = process.env.FRONT_BASE || 'http://localhost:5173';
const USER = process.env.SMOKE_USER || 'wilson';
const PASS = process.env.SMOKE_PASS || 'tutelas2026';

// Rutas de frontend/src/App.tsx. {caseId} se sustituye por un id real descubierto en runtime.
const ROUTES = [
  '/', '/cases', '/cuadro', '/seguimiento', '/auditoria', '/emails', '/intelligence',
  '/reports', '/agent', '/settings', '/cleanup', '/alertas', '/ejecutivo', '/extraction',
  '/cases/{caseId}',
];

// Errores de consola que son ruido conocido y no cuentan como FAIL.
const IGNORE_CONSOLE = [
  /favicon/i, /Failed to load resource.*404.*favicon/i, /\[vite\]/i,
  /Download the React DevTools/i, /ResizeObserver loop/i,
  // Aviso de accesibilidad de Base UI (componente que actúa como botón sin <button> nativo) —
  // nit pre-existente en algunas páginas (p.ej. Reportes), no es un error funcional.
  /Base UI:.*acts as a button.*native <button>/i,
];

// Si el login no redirige por sí solo (a veces la SPA se queda en "/" sin cambiar la ruta de
// inmediato), basta con que haya un token de auth en localStorage para considerarlo OK.
async function isAuthenticated(page) {
  try {
    return await page.evaluate(() =>
      Object.values(localStorage).some((v) => /"access_token"|"token"\s*:/.test(String(v))));
  } catch { return false; }
}

const log = (m) => console.log(`[${new Date().toISOString().slice(11, 19)}] ${m}`);
const isIgnored = (msg) => IGNORE_CONSOLE.some((re) => re.test(msg));

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
  const page = await context.newPage();

  let currentRoute = '(boot)';
  const failures = []; // {route, kind, msg}
  page.on('pageerror', (e) => {
    const msg = String(e.message).slice(0, 240);
    if (!isIgnored(msg)) failures.push({ route: currentRoute, kind: 'pageerror', msg });
  });
  page.on('console', (m) => {
    if (m.type() !== 'error') return;
    const msg = m.text().slice(0, 240);
    if (!isIgnored(msg)) failures.push({ route: currentRoute, kind: 'console', msg });
  });
  page.on('response', (r) => {
    if (r.status() >= 500) failures.push({ route: currentRoute, kind: 'http5xx', msg: `${r.status()} ${r.url()}` });
  });

  const results = []; // {route, status, detail}

  // ── login ──
  try {
    currentRoute = '/login';
    await page.goto(`${BASE}/login`, { waitUntil: 'domcontentloaded', timeout: 20000 });
    // intenta los selectores más comunes; ajusta si la página de login usa otros
    const userSel = 'input[name="username"], input[type="text"], input[placeholder*="usuario" i]';
    const passSel = 'input[name="password"], input[type="password"]';
    await page.waitForSelector(userSel, { timeout: 10000 });
    await page.fill(userSel, USER);
    await page.fill(passSel, PASS);
    await Promise.all([
      page.waitForURL((u) => !u.pathname.includes('/login'), { timeout: 15000 }).catch(() => {}),
      page.click('button[type="submit"], button:has-text("Ingresar"), button:has-text("Entrar"), button:has-text("Login")'),
    ]);
    await page.waitForTimeout(1500);
    if (!page.url().includes('/login') || (await isAuthenticated(page))) {
      results.push({ route: '/login', status: 'OK', detail: `→ ${new URL(page.url()).pathname}` });
    } else {
      results.push({ route: '/login', status: 'FAIL', detail: 'no autenticó (revisa los selectores del form en smoke_frontend.mjs)' });
    }
  } catch (e) {
    results.push({ route: '/login', status: 'FAIL', detail: `${e.message.slice(0, 160)}` });
    log('Login falló — el resto de rutas probablemente fallará. Revisa los selectores del formulario en smoke_frontend.mjs.');
  }

  // ── descubrir un caseId real ──
  let caseId = '1';
  try {
    const r = await page.evaluate(async () => {
      try {
        const tok = JSON.parse(localStorage.getItem('auth') || '{}').token
          || localStorage.getItem('token') || localStorage.getItem('access_token');
        const res = await fetch('/api/cases/table', { headers: tok ? { Authorization: `Bearer ${tok}` } : {} });
        const j = await res.json();
        const real = (Array.isArray(j) ? j : []).find((x) => x && x.id && x.folder_name !== '__SIN_RADICADO__');
        return (real || (Array.isArray(j) ? j[0] : null))?.id ?? null;
      } catch { return null; }
    });
    if (r) caseId = String(r);
  } catch { /* ignore */ }

  // ── navegar cada ruta ──
  for (const tmpl of ROUTES) {
    const route = tmpl.replace('{caseId}', caseId);
    currentRoute = route;
    const before = failures.length;
    try {
      await page.goto(`${BASE}${route}`, { waitUntil: 'networkidle', timeout: 25000 });
      await page.waitForTimeout(1200);
      const newFails = failures.slice(before).filter((f) => f.route === route);
      if (newFails.length) {
        results.push({ route, status: 'FAIL', detail: newFails.map((f) => `[${f.kind}] ${f.msg}`).join(' | ').slice(0, 300) });
      } else {
        results.push({ route, status: 'OK', detail: '' });
      }
    } catch (e) {
      results.push({ route, status: 'FAIL', detail: `navegación: ${e.message.slice(0, 160)}` });
    }
  }

  // ── endpoint del asistente jurídico (el botón flotante se retiró; el endpoint sigue vivo) ──
  currentRoute = '(asistente)';
  try {
    const r = await page.evaluate(async () => {
      const tok = localStorage.getItem('token') || localStorage.getItem('access_token') || '';
      const res = await fetch('/api/chat/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(tok ? { Authorization: `Bearer ${tok}` } : {}) },
        body: JSON.stringify({ message: '¿cuántas tutelas hay?' }),
      });
      return { ok: res.ok, status: res.status, text: (await res.text()).slice(0, 200) };
    });
    const errored = !r.ok || /no pude procesar|error al|algo salió mal/i.test(r.text);
    results.push({ route: '(asistente — endpoint)', status: errored ? 'FAIL' : 'OK', detail: errored ? `HTTP ${r.status}` : 'respondió' });
  } catch (e) {
    results.push({ route: '(asistente — endpoint)', status: 'FAIL', detail: `${e.message.slice(0, 160)}` });
  }

  await browser.close();

  // ── reporte ──
  const w = Math.max(...results.map((r) => r.route.length), 12);
  console.log(`\n${'='.repeat(70)}\nSMOKE FRONTEND — ${results.length} rutas\n${'='.repeat(70)}`);
  let nFail = 0;
  for (const { route, status, detail } of results) {
    if (status === 'FAIL') nFail++;
    console.log(`  ${status === 'OK' ? '✓' : '✗'} ${route.padEnd(w)}  ${status.padEnd(5)} ${detail}`);
  }
  console.log('='.repeat(70));
  if (nFail) { console.log(`❌ ${nFail} ruta(s) con error`); process.exit(1); }
  console.log(`✅ ${results.length} rutas OK · endpoint asistente OK`);
})().catch((e) => { console.error('smoke_frontend crashed:', e); process.exit(1); });
