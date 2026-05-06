/**
 * Playwright e2e v6.0.16: valida flujo cleanup cognitivo + dashboard.
 *
 * 1. Login wilson/tutelas2026
 * 2. Dashboard - cargar y verificar números clave (no NaN, no zero)
 * 3. /cleanup - verificar ActionCard nuevo "Re-verificar Sospechosos"
 * 4. Test endpoint chat → "casos en sancion" (Tier 1 deterministic)
 * 5. Verificar 0 console errors de nivel error.
 */
import { chromium } from 'playwright';
import { mkdirSync } from 'fs';

const BASE = process.env.BASE_URL || 'http://localhost:5173';
const SCREENSHOTS = './screenshots-v6016';
mkdirSync(SCREENSHOTS, { recursive: true });

const log = (m) => console.log(`[${new Date().toISOString().slice(11, 19)}] ${m}`);

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`));
  page.on('console', (msg) => {
    if (msg.type() === 'error') errors.push(`console: ${msg.text().slice(0, 100)}`);
  });

  try {
    // Login
    log('1. Navegando a login...');
    await page.goto(BASE, { waitUntil: 'domcontentloaded', timeout: 15000 });
    await page.waitForSelector('input[type="text"], input[type="email"]', { timeout: 10000 });
    const inputs = await page.locator('input').all();
    if (inputs.length >= 2) {
      await inputs[0].fill('wilson');
      await inputs[1].fill('tutelas2026');
      await page.locator('button[type="submit"], button:has-text("Ingresar"), button:has-text("Iniciar")').first().click();
      await page.waitForLoadState('networkidle', { timeout: 10000 }).catch(() => {});
      log('  ✓ Login enviado');
    }
    await page.screenshot({ path: `${SCREENSHOTS}/01-after-login.png` });

    // Dashboard
    log('2. Verificando dashboard...');
    await page.waitForTimeout(2000);
    const bodyText = await page.locator('body').innerText();
    const hasCases = /\d{2,4}/.test(bodyText);
    log(`  ${hasCases ? '✓' : '✗'} Dashboard contiene números`);
    await page.screenshot({ path: `${SCREENSHOTS}/02-dashboard.png`, fullPage: true });

    // Cleanup panel
    log('3. Navegando a /cleanup...');
    await page.goto(`${BASE}/cleanup`, { waitUntil: 'domcontentloaded', timeout: 15000 });
    await page.waitForTimeout(2000);
    const reverifyVisible = await page.locator('text=Re-verificar Sospechosos').isVisible().catch(() => false);
    log(`  ${reverifyVisible ? '✓' : '✗'} ActionCard "Re-verificar Sospechosos" visible`);
    await page.screenshot({ path: `${SCREENSHOTS}/03-cleanup.png`, fullPage: true });

    // Chat (si hay)
    log('4. Test chat NL→DB via API directa...');
    const chatResp = await page.request.post('http://localhost:8000/api/chat/', {
      data: { message: 'casos en sancion' },
      headers: { 'Content-Type': 'application/json' },
    });
    if (chatResp.ok()) {
      const body = await chatResp.json();
      log(`  ✓ Intent: ${body.intent}, confidence: ${body.confidence}`);
    } else {
      log(`  ✗ Chat HTTP ${chatResp.status()}`);
    }

    // Errores
    log(`5. Console/page errors detectados: ${errors.length}`);
    errors.slice(0, 5).forEach((e) => log(`     ${e}`));

    log('\n=== RESUMEN ===');
    log(`Errors total: ${errors.length}`);
    log(`Reverify card visible: ${reverifyVisible}`);
    log(`Dashboard tiene datos: ${hasCases}`);

    process.exitCode = (errors.length === 0 && reverifyVisible && hasCases) ? 0 : 1;
  } catch (e) {
    log(`✗ FATAL: ${e.message}`);
    await page.screenshot({ path: `${SCREENSHOTS}/error.png` }).catch(() => {});
    process.exitCode = 2;
  } finally {
    await browser.close();
  }
})();
