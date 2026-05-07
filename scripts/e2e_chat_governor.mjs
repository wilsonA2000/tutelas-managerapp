/**
 * Simula al gobernador haciendo preguntas en el chat IA del frontend.
 */
import { chromium } from 'playwright';
import { mkdirSync } from 'fs';
const BASE = 'http://localhost:5174';
mkdirSync('/tmp/screenshots-chat', { recursive: true });

const QUESTIONS = [
  'ayuda',
  'cuántos casos hay',
  'cuántos casos rojos',
  'casos en sanción',
  'qué tiene Angelica',
  'casos de talento humano',
  'distribución de fallos',
  'top temas',
];

(async () => {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();

  await page.goto(BASE);
  await page.waitForSelector('input', { timeout: 15000 });
  const inputs = await page.locator('input').all();
  await inputs[0].fill('wilson');
  await inputs[1].fill('tutelas2026');
  await page.locator('button[type="submit"]').first().click();
  await page.waitForTimeout(3000);

  // Abrir chat (botón flotante "Asistente jurídico")
  const chatBtn = page.locator('button:has-text("Asistente jurídico")').first();
  if (await chatBtn.count() === 0) {
    console.log('✗ No se encontró botón del chat');
    await browser.close();
    return;
  }
  await chatBtn.click();
  await page.waitForTimeout(1500);
  await page.screenshot({ path: '/tmp/screenshots-chat/00-open.png' });

  // Selector del input del chat
  const chatInput = page.locator('textarea, input[placeholder*="Pregunta" i], input[placeholder*="escrib" i]').last();
  if (await chatInput.count() === 0) {
    console.log('✗ No se encontró input de chat');
    await browser.close();
    return;
  }

  let passed = 0, failed = 0;
  for (let i = 0; i < QUESTIONS.length; i++) {
    const q = QUESTIONS[i];
    console.log(`\n[${i+1}/${QUESTIONS.length}] Q: ${q}`);
    await chatInput.fill(q);
    await chatInput.press('Enter');
    // Esperar respuesta
    await page.waitForTimeout(8000);
    await page.screenshot({ path: `/tmp/screenshots-chat/q${i+1}-${q.replace(/\s+/g,'_').slice(0,30)}.png` });

    // Verificar que la respuesta apareció
    const respText = await page.evaluate(() => {
      // Buscar el último mensaje del asistente
      const messages = document.querySelectorAll('[class*="message"], [class*="bubble"], [role="log"] > div, .markdown');
      let last = '';
      messages.forEach(m => {
        const t = m.innerText || m.textContent || '';
        if (t.length > 30 && !t.includes('Pregunt')) last = t;
      });
      return last.slice(0, 200);
    });

    const has_data = /\d+/.test(respText) || respText.includes('•') || respText.includes('🚨') || respText.includes('📊');
    if (has_data) {
      passed++;
      console.log(`  ✓ ${respText.slice(0, 100)}`);
    } else {
      failed++;
      console.log(`  ✗ respuesta vacía o sin datos: "${respText.slice(0, 80)}"`);
    }
  }

  await page.screenshot({ path: '/tmp/screenshots-chat/99-final.png', fullPage: true });
  console.log(`\nRESULT: ${passed}/${QUESTIONS.length} preguntas con respuesta válida`);
  await browser.close();
})();
