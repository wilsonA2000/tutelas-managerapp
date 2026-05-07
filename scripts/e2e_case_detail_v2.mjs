/**
 * Verifica visualmente case detail buscando en INPUTS también (no solo innerText).
 */
import { chromium } from 'playwright';
import { mkdirSync } from 'fs';
const BASE = 'http://localhost:5174';
mkdirSync('/tmp/screenshots-cases-v2', { recursive: true });

(async () => {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 1200 } });
  const page = await ctx.newPage();

  await page.goto(BASE);
  await page.waitForSelector('input', { timeout: 15000 });
  const inputs = await page.locator('input').all();
  await inputs[0].fill('wilson');
  await inputs[1].fill('tutelas2026');
  await page.locator('button[type="submit"]').first().click();
  await page.waitForTimeout(3000);

  const cases = [1, 11, 22, 41, 142];
  let passed = 0;
  let failed = 0;
  for (const cid of cases) {
    await page.goto(`${BASE}/cases/${cid}`);
    await page.waitForTimeout(5000);
    await page.screenshot({ path: `/tmp/screenshots-cases-v2/case-${cid}.png`, fullPage: true });

    // Recoger todos los valores de inputs/textarea visibles
    const inputValues = await page.evaluate(() => {
      const els = document.querySelectorAll('input, textarea');
      return Array.from(els).map(el => el.value).join(' | ');
    });

    const txt = await page.locator('body').innerText() + ' ' + inputValues;
    const has = {
      accionante: /\bACCIONANTE|LEIBY|PERSONERO|FREDDY|DIDIER|ANA MILENA/i.test(txt),
      abogado_canonical: /JUAN DIEGO CRUZ|MARIA CRISTINA VILLAMIZAR|VICTOR ALFONSO|ANGELICA YADIRA/i.test(txt),
      sentido: /CONCEDE|NIEGA|IMPROCEDENTE/i.test(txt),
      docs: /Documentos.*\(\d+\)/.test(txt),
      dependencia_canonical: /DIRECCION_TALENTO|DIRECCION_ESTRATEGICA|DIRECCION_ADMIN|FINANCIERA|ATENCION_CIUDADANO/i.test(txt),
    };
    const allOk = Object.values(has).every(Boolean);
    if (allOk) passed++; else failed++;
    console.log(`case=${cid}: ${allOk ? '✓' : '✗'} ${JSON.stringify(has)}`);
  }
  console.log(`\nRESULT: ${passed}/${cases.length} cases passed all checks`);
  await browser.close();
})();
