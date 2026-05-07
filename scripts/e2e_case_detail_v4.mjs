/**
 * Abre todas las secciones colapsables y verifica abogado_canonical visible.
 */
import { chromium } from 'playwright';
import { mkdirSync } from 'fs';
const BASE = 'http://localhost:5174';
mkdirSync('/tmp/screenshots-cases-v4', { recursive: true });

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
  for (const cid of cases) {
    await page.goto(`${BASE}/cases/${cid}`);
    await page.waitForTimeout(5000);

    // Click en TODAS las section headers (button con clase específica)
    await page.evaluate(() => {
      document.querySelectorAll('button').forEach(b => {
        const span = b.querySelector('span.text-sm');
        if (span && span.textContent.match(/Gestión|Fallo|Recurso|Incidente|Identificación/)) {
          // Si está colapsada (icono ChevronDown), abrir
          const chevron = b.querySelector('svg');
          // Click siempre, idempotente: si ya está abierta abrirá segunda vez (cierra)
          // Mejor: solo si vemos chevronDown
        }
      });
    });

    // Estrategia: todos los botones con texto "Gestión interna SED"
    const gestionBtn = page.locator('button:has-text("Gestión interna SED")');
    if (await gestionBtn.count() > 0) {
      await gestionBtn.first().click();
      await page.waitForTimeout(800);
    }

    // Inspeccionar
    const data = await page.evaluate(() => {
      const labels = document.querySelectorAll('label');
      const result = [];
      labels.forEach(label => {
        const text = label.innerText.trim();
        const parent = label.closest('div');
        const input = parent ? parent.querySelector('input, textarea, select') : null;
        const value = input ? (input.value || '') : '';
        if (text.match(/Abogado|Dependencia|Oficina|Firmante/i)) {
          result.push({ label: text, value });
        }
      });
      return result;
    });

    const abogCan = data.find(d => /Abogado de tutelas/i.test(d.label));
    const depCan = data.find(d => /Dependencia/i.test(d.label));
    const ok = abogCan && abogCan.value && depCan && depCan.value;
    if (ok) passed++;
    console.log(`case=${cid}: ${ok ? '✓' : '✗'}`);
    data.forEach(d => console.log(`    ${d.label.padEnd(45)} = "${d.value}"`));
    await page.screenshot({ path: `/tmp/screenshots-cases-v4/case-${cid}.png`, fullPage: true });
  }

  console.log(`\nRESULT: ${passed}/${cases.length} cases muestran abogado/dependencia canonical`);
  await browser.close();
})();
