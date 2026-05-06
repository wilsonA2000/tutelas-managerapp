/**
 * Captura específica: scroll hasta el botón "Re-verificar Sospechosos"
 * para validar que el ActionCard se ve correctamente en la UI.
 */
import { chromium } from 'playwright';
const BASE = 'http://localhost:5173';

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newContext({ viewport: { width: 1440, height: 900 } }).then(c => c.newPage());

  await page.goto(BASE);
  await page.locator('input[type="text"]').first().fill('wilson');
  await page.locator('input[type="password"]').first().fill('tutelas2026');
  await page.locator('button[type="submit"]').first().click();
  await page.waitForLoadState('domcontentloaded');
  await page.waitForTimeout(1500);

  await page.goto(`${BASE}/cleanup`);
  await page.waitForLoadState('domcontentloaded');
  await page.waitForTimeout(2500);

  // Scroll al ActionCard nuevo
  const reverify = page.locator('text=/Re-verificar Sospechosos/i').first();
  await reverify.waitFor({ timeout: 30000 });
  await reverify.scrollIntoViewIfNeeded();
  await page.waitForTimeout(500);

  await page.screenshot({ path: './screenshots-e2e/07_reverify_visible.png', fullPage: false });

  // Captura solo el ActionCard
  const card = reverify.locator('xpath=ancestor::div[contains(@class, "p-4")][1]');
  await card.screenshot({ path: './screenshots-e2e/08_reverify_card.png' }).catch(() => {
    console.log('no se pudo capturar solo el card, ok');
  });

  // Click Vista Previa real para mostrar resultado
  console.log('Click Vista Previa...');
  const cardFull = reverify.locator('..').locator('..').locator('..');
  await cardFull.locator('button:has-text("Vista Previa")').first().click();
  console.log('esperando resultado dry-run...');
  await page.waitForTimeout(8000);  // dry run de todos los 1355 toma tiempo

  await page.screenshot({ path: './screenshots-e2e/09_reverify_after_preview.png', fullPage: false });
  console.log('done');
  await browser.close();
})();
