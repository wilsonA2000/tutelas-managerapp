/**
 * Playwright e2e: simula al operador navegando la plataforma.
 *
 * Flujo:
 *  1. Login (wilson / tutelas2026)
 *  2. Dashboard - verificar números visibles
 *  3. /cleanup (Mantenimiento) - verificar todos los botones presentes
 *  4. Test botón "Re-verificar Sospechosos" en Vista Previa (dry_run)
 *  5. Test chat NL→DB ("resumen general")
 *  6. Screenshots en cada paso
 */
import { chromium } from 'playwright';
import { mkdirSync } from 'fs';

const BASE = process.env.BASE_URL || 'http://localhost:5173';
const SCREENSHOTS = './screenshots-e2e';
mkdirSync(SCREENSHOTS, { recursive: true });

const log = (msg) => console.log(`[${new Date().toISOString().slice(11, 19)}] ${msg}`);

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  const errors = [];
  const consoleMsgs = [];

  page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`));
  page.on('console', (m) => {
    if (m.type() === 'error') consoleMsgs.push(`[console.error] ${m.text()}`);
  });

  try {
    // 1. Login
    log('1️⃣  Login page');
    await page.goto(BASE);
    await page.waitForLoadState('networkidle');
    await page.screenshot({ path: `${SCREENSHOTS}/01_login.png`, fullPage: true });

    const userInput = await page.locator('input[type="text"], input[name="username"], input[placeholder*="usuario" i]').first();
    const pwdInput = await page.locator('input[type="password"]').first();
    await userInput.fill('wilson');
    await pwdInput.fill('tutelas2026');
    log('   credenciales rellenadas');

    const loginBtn = await page.locator('button[type="submit"], button:has-text("Iniciar"), button:has-text("Login")').first();
    await loginBtn.click();
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);
    await page.screenshot({ path: `${SCREENSHOTS}/02_post_login.png`, fullPage: true });

    const url1 = page.url();
    log(`   URL post-login: ${url1}`);
    if (url1.includes('/login')) throw new Error('Login falló — sigue en /login');

    // 2. Dashboard
    log('2️⃣  Dashboard');
    const dashboardText = await page.locator('body').innerText();
    const has403or409 = /409|403|casos/i.test(dashboardText);
    log(`   contiene "casos" o números: ${has403or409}`);
    await page.screenshot({ path: `${SCREENSHOTS}/03_dashboard.png`, fullPage: true });

    // 3. Mantenimiento — navegar directo via URL (más robusto que click sidebar)
    log('3️⃣  Navegar a /cleanup directamente');
    await page.goto(`${BASE}/cleanup`);
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);
    await page.screenshot({ path: `${SCREENSHOTS}/04_cleanup_panel.png`, fullPage: true });

    // 4. Verificar botones presentes
    log('4️⃣  Verificando ActionCards');
    const cardTitles = [
      'Verificar Integridad',
      'Fusionar Casos Duplicados',
      'Reubicar Documentos',
      'Re-verificar Sospechosos',  // ← el nuevo
      'Generar Resumen de Correos',
      'Purgar Documentos Duplicados',
      'Fusionar Fragmentos FOREST',
      'Completar Radicados',
    ];
    const found = {};
    for (const title of cardTitles) {
      const exists = await page.locator(`text=/${title}/i`).count();
      found[title] = exists > 0 ? '✓' : '✗';
    }
    log('   ActionCards encontradas:');
    for (const [k, v] of Object.entries(found)) log(`     ${v} ${k}`);

    // 5. Click Re-verificar Sospechosos > Vista Previa
    log('5️⃣  Click "Re-verificar Sospechosos" → Vista Previa');
    const reverifyCard = page.locator('text=/Re-verificar Sospechosos/i').first();
    await reverifyCard.scrollIntoViewIfNeeded();
    await page.waitForTimeout(500);

    // El botón Vista Previa está en el mismo Card
    const cardContainer = reverifyCard.locator('..').locator('..').locator('..');
    const previewBtn = cardContainer.locator('button:has-text("Vista Previa")').first();
    await previewBtn.click();
    log('   Vista Previa clicked, esperando respuesta...');
    await page.waitForTimeout(3000);

    // 6. Chat
    log('6️⃣  Test chat NL→DB');
    // El chat es un componente flotante (botón en esquina)
    const chatButtons = await page.locator('button[aria-label*="chat" i], button:has-text("Asistente"), button:has(svg)').count();
    log(`   botones potencialmente chat: ${chatButtons}`);
    await page.screenshot({ path: `${SCREENSHOTS}/05_after_preview.png`, fullPage: true });

    // Intentar abrir el chat — probar varios selectores
    const possibleChatTriggers = [
      'button:has(svg.lucide-message-circle)',
      'button:has(svg.lucide-bot)',
      '[data-testid*="chat"]',
      'button[aria-label*="agent" i]',
    ];
    let chatOpened = false;
    for (const sel of possibleChatTriggers) {
      try {
        const el = page.locator(sel).first();
        if (await el.count() > 0) {
          await el.click({ timeout: 2000 });
          await page.waitForTimeout(800);
          const inputs = await page.locator('input[placeholder*="escribe" i], textarea').count();
          if (inputs > 0) {
            chatOpened = true;
            log(`   chat abierto con selector: ${sel}`);
            break;
          }
        }
      } catch {}
    }

    if (chatOpened) {
      const input = page.locator('input[placeholder*="escribe" i], textarea').last();
      await input.fill('resumen general');
      await page.keyboard.press('Enter');
      await page.waitForTimeout(2500);
      await page.screenshot({ path: `${SCREENSHOTS}/06_chat_response.png`, fullPage: true });
      const ans = await page.locator('body').innerText();
      const hasAnswer = /403|409|TUTELA|COMPLETO/i.test(ans);
      log(`   chat respondió con datos: ${hasAnswer}`);
    } else {
      log('   no encontré chat abierto — capturo estado igual');
      await page.screenshot({ path: `${SCREENSHOTS}/06_chat_not_found.png`, fullPage: true });
    }

    // Final
    log('═══════════════════════════════════════');
    log('✅ FLOW COMPLETADO');
    log(`Screenshots en: ${SCREENSHOTS}/`);
    log(`Page errors: ${errors.length}`);
    if (errors.length) errors.forEach(e => log(`  ${e}`));
    log(`Console errors: ${consoleMsgs.length}`);
    if (consoleMsgs.length) consoleMsgs.slice(0, 5).forEach(m => log(`  ${m}`));

  } catch (e) {
    log(`❌ ERROR: ${e.message}`);
    await page.screenshot({ path: `${SCREENSHOTS}/ERROR.png`, fullPage: true });
  } finally {
    await browser.close();
  }
})();
