/**
 * Verifica que el modal de notas:
 * - muestre historial visible.
 * - se quede abierto al guardar (no cierre).
 * - apile la nota nueva en el historial visible.
 * - El botón "Nota" en la fila muestre conteo "(N)".
 */
import { chromium } from 'playwright';
import { mkdirSync } from 'fs';
const BASE = 'http://localhost:5173';
const DIR = '/tmp/screenshots-notas';
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

  // Buscar fila con "Notas (N)" — debería haber al menos una con notas existentes
  const notasBtns = await page.locator('button:has-text("Notas (")').count();
  log(`Botones "Notas (N)" visibles (con historial): ${notasBtns}`);

  // Click sobre primer botón "Notas (N)"
  if (notasBtns > 0) {
    await page.locator('button:has-text("Notas (")').first().click();
  } else {
    // Fallback: cualquier botón Nota
    await page.locator('button:has-text("Nota")').first().click();
  }
  await page.waitForTimeout(800);
  await page.screenshot({ path: `${DIR}/01-modal-abierto.png`, fullPage: false });
  log('Modal abierto');

  // Verificar header
  const titulo = await page.locator('h2:has-text("Notas del expediente")').textContent().catch(() => 'no encontrado');
  log(`Título: ${titulo}`);

  // Contar notas en historial inicial
  const historialEntries = await page.locator('pre').first().textContent().catch(() => '');
  const entriesCount = (historialEntries.match(/\[\d{2}\/\d{2}\/\d{4}\]/g) || []).length;
  log(`Historial: ${entriesCount} entradas`);

  // Escribir y guardar
  const textarea = page.locator('textarea');
  await textarea.fill('TEST E2E — nota guardada desde Playwright');
  await page.waitForTimeout(300);
  await page.locator('button:has-text("Guardar nota")').click();
  await page.waitForTimeout(2000);
  await page.screenshot({ path: `${DIR}/02-despues-guardar.png`, fullPage: false });

  // Verificar que el modal SIGA abierto
  const modalAbierto = await page.locator('h2:has-text("Notas del expediente")').count();
  log(`Modal sigue abierto: ${modalAbierto > 0 ? 'SÍ ✓' : 'NO ✗'}`);

  // Verificar que el historial creció
  const historialDespues = await page.locator('pre').first().textContent().catch(() => '');
  const entriesDespues = (historialDespues.match(/\[\d{2}\/\d{2}\/\d{4}\]/g) || []).length;
  log(`Historial post-guardar: ${entriesDespues} entradas (esperado: ${entriesCount + 1})`);

  // Verificar que el textarea quedó vacío
  const textareaValue = await textarea.inputValue();
  log(`Textarea limpio: ${textareaValue === '' ? 'SÍ ✓' : `NO, valor="${textareaValue}"`}`);

  // Cerrar el modal y verificar el botón "Notas (N)" actualizado
  await page.locator('button:has-text("Cerrar")').click();
  await page.waitForTimeout(1500);
  const notasBtnsAfter = await page.locator('button:has-text("Notas (")').count();
  log(`Botones "Notas (N)" después: ${notasBtnsAfter}`);

  await page.screenshot({ path: `${DIR}/03-cerrado.png`, fullPage: false });

  // REVERTIR: borrar la nota de prueba (sql directo no posible, así que dejamos)
  log('NOTE: Test agregó una nota real al expediente. Revisar después si se quiere limpiar.');

  await ctx.close();
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
