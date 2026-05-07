/**
 * Inspección detallada de inputs en CaseDetail.
 */
import { chromium } from 'playwright';
const BASE = 'http://localhost:5174';

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

  await page.goto(`${BASE}/cases/1`);
  await page.waitForTimeout(6000);

  // Forzar scroll en panel izquierdo
  await page.evaluate(() => {
    document.querySelectorAll('div').forEach(d => {
      if (d.scrollHeight > d.clientHeight) d.scrollTop = d.scrollHeight;
    });
  });
  await page.waitForTimeout(1000);

  // Listar TODOS los labels y los valores asociados
  const data = await page.evaluate(() => {
    const labels = document.querySelectorAll('label');
    const result = [];
    labels.forEach(label => {
      const text = label.innerText.trim().slice(0, 50);
      // Buscar el sibling input/textarea dentro del mismo div
      const parent = label.closest('div');
      let value = '';
      if (parent) {
        const input = parent.querySelector('input, textarea, select');
        if (input) value = input.value || '';
      }
      if (text || value) result.push({ label: text, value: value.slice(0, 60) });
    });
    return result;
  });

  console.log('=== Labels y valores en /cases/1 ===');
  for (const item of data) {
    if (item.label.toLowerCase().match(/aboga|oficina|depend|firmante|estado|canonical/)) {
      console.log(`  ${item.label.padEnd(40)} = "${item.value}"`);
    }
  }
  console.log(`\nTotal labels: ${data.length}`);

  await browser.close();
})();
