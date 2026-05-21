/**
 * Verifica que cambiar estado actualice el badge ESTADO inmediatamente.
 */
import { chromium } from 'playwright';
import { mkdirSync } from 'fs';
const BASE = 'http://localhost:5173';
const DIR = '/tmp/screenshots-estado-update';
mkdirSync(DIR, { recursive: true });
const log = (m) => console.log(`[${new Date().toISOString().slice(11, 19)}] ${m}`);

(async () => {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  await page.goto(`${BASE}/login`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(800);
  const inputs = await page.locator('input').all();
  await inputs[0].fill('wilson');
  await inputs[1].fill('tutelas2026');
  await page.locator('button[type="submit"]').first().click();
  await page.waitForTimeout(2500);

  await page.goto(`${BASE}/seguimiento`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(3000);

  // Tomar el estado inicial del primer badge
  const initialBadge = await page.locator('table tbody tr:first-child td:first-child').textContent();
  log(`Badge inicial primer fila: ${initialBadge?.trim()}`);
  await page.screenshot({ path: `${DIR}/01-antes.png`, fullPage: false });

  // Click en dropdown "Estado" del primer fila
  await page.locator('table tbody tr:first-child button:has-text("Estado")').click();
  await page.waitForTimeout(800);
  await page.screenshot({ path: `${DIR}/02-dropdown-abierto.png`, fullPage: false });

  // Click "En proceso"
  await page.locator('[role="menuitem"]:has-text("En proceso")').click();
  await page.waitForTimeout(2000);
  await page.screenshot({ path: `${DIR}/03-despues-cambio.png`, fullPage: false });

  // Verificar el nuevo badge
  const newBadge = await page.locator('table tbody tr:first-child td:first-child').textContent();
  log(`Badge nuevo primer fila: ${newBadge?.trim()}`);
  log(`Cambió de "${initialBadge?.trim()}" a "${newBadge?.trim()}": ${initialBadge?.trim() !== newBadge?.trim() ? 'SÍ ✓' : 'NO ✗'}`);

  // REVERTIR para no contaminar — usar dropdown otra vez para volver al estado previo
  await page.locator('table tbody tr:first-child button:has-text("Estado")').click();
  await page.waitForTimeout(800);
  // Click "Vencido" para devolver al estado original (era Vencido)
  await page.locator('[role="menuitem"]:has-text("Vencido")').click();
  await page.waitForTimeout(2000);
  const finalBadge = await page.locator('table tbody tr:first-child td:first-child').textContent();
  log(`Badge final tras revertir: ${finalBadge?.trim()}`);

  await ctx.close();
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
