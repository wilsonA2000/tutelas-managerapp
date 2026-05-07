/**
 * Verifica visualmente case detail con scroll completo + nombre canonical.
 */
import { chromium } from 'playwright';
import { mkdirSync } from 'fs';
const BASE = 'http://localhost:5174';
mkdirSync('/tmp/screenshots-cases', { recursive: true });

(async () => {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 1200 } });
  const page = await ctx.newPage();

  // Login
  await page.goto(BASE);
  await page.waitForSelector('input', { timeout: 15000 });
  const inputs = await page.locator('input').all();
  await inputs[0].fill('wilson');
  await inputs[1].fill('tutelas2026');
  await page.locator('button[type="submit"]').first().click();
  await page.waitForTimeout(3000);

  // 5 cases ROJO críticos
  const cases = [1, 11, 22, 41, 142];
  for (const cid of cases) {
    await page.goto(`${BASE}/cases/${cid}`);
    await page.waitForTimeout(4000);
    await page.screenshot({ path: `/tmp/screenshots-cases/case-${cid}.png`, fullPage: true });
    const txt = await page.locator('body').innerText();
    const has = {
      accionante: /\bACCIONANTE/i.test(txt),
      abogado: /JUAN DIEGO|MARIA CRISTINA|VICTOR|ANGELICA|OTILIA|JHON|FERNANDO/i.test(txt),
      sentido: /CONCEDE|NIEGA|IMPROCEDENTE/i.test(txt),
      docs: /Documentos|\d+ docs/.test(txt),
    };
    console.log(`case=${cid}: accionante=${has.accionante} abogado=${has.abogado} sentido=${has.sentido} docs=${has.docs}`);
  }

  await browser.close();
})();
