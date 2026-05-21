/**
 * Verifica que /cases/:id tenga scroll independiente en panel izq vs der.
 * - Login, abre case 311 (que tiene PDF).
 * - Scrollea con la rueda sobre cada panel y verifica que el OTRO no se mueva.
 */
import { chromium } from 'playwright';
import { mkdirSync } from 'fs';
const BASE = 'http://localhost:5173';
const DIR = '/tmp/screenshots-scroll';
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
  await page.goto(`${BASE}/cases/311`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2500);

  // Identificar elementos scrolleables
  const scrollables = await page.evaluate(() => {
    const els = Array.from(document.querySelectorAll('*'));
    return els
      .filter((el) => {
        const cs = getComputedStyle(el);
        return ['auto', 'scroll'].includes(cs.overflowY) && el.scrollHeight > el.clientHeight;
      })
      .slice(0, 10)
      .map((el) => ({
        tag: el.tagName,
        className: el.className.toString().slice(0, 80),
        scrollH: el.scrollHeight,
        clientH: el.clientHeight,
        rect: el.getBoundingClientRect ? { x: Math.round(el.getBoundingClientRect().left), w: Math.round(el.getBoundingClientRect().width) } : null,
      }));
  });
  log(`Elementos scrolleables (scrollHeight > clientHeight, overflow-y auto/scroll):`);
  scrollables.forEach((s, i) => log(`  ${i}: ${s.tag}.${s.className} scrollH=${s.scrollH} clientH=${s.clientH} x=${s.rect?.x} w=${s.rect?.w}`));

  // Capturar inicial
  await page.screenshot({ path: `${DIR}/01-initial.png`, fullPage: false });

  // Identificar panel izquierdo (form) y panel derecho (PDF)
  // El form section ".overflow-y-auto.p-6" debería ser el izquierdo
  const leftPanel = await page.locator('.overflow-y-auto.p-6.space-y-3').first();
  const leftBox = await leftPanel.boundingBox();
  log(`Panel izquierdo box: ${JSON.stringify(leftBox)}`);

  // Scroll en el panel izquierdo
  if (leftBox) {
    await page.mouse.move(leftBox.x + leftBox.width / 2, leftBox.y + leftBox.height / 2);
    await page.mouse.wheel(0, 500);
    await page.waitForTimeout(500);
    const leftScrollTop = await leftPanel.evaluate((el) => el.scrollTop);
    log(`Después de wheel sobre izquierdo: leftPanel.scrollTop=${leftScrollTop}`);
    await page.screenshot({ path: `${DIR}/02-scroll-left.png`, fullPage: false });
  }

  // Body scrollTop (no debería haberse movido)
  const bodyScroll = await page.evaluate(() => ({
    bodyTop: document.body.scrollTop,
    htmlTop: document.documentElement.scrollTop,
    mainTop: document.getElementById('main-content')?.scrollTop ?? 'no main',
  }));
  log(`Body/main scrollTop: ${JSON.stringify(bodyScroll)}`);

  await ctx.close();
  await browser.close();
  log(`Screenshots: ${DIR}`);
})().catch((e) => { console.error(e); process.exit(1); });
