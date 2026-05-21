/**
 * Test scroll independiente con PDF abierto.
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
  await page.waitForTimeout(3000);

  // Click sobre el primer documento PDF para abrirlo
  const firstPdfRow = await page.locator('.cursor-pointer:has-text(".pdf"), [class*="cursor-pointer"]:has-text("FalloTutela")').first();
  if (await firstPdfRow.count() > 0) {
    await firstPdfRow.click();
    await page.waitForTimeout(2500);
    log('PDF abierto');
  } else {
    log('No se pudo encontrar PDF');
  }

  await page.screenshot({ path: `${DIR}/03-pdf-open-initial.png`, fullPage: false });

  // Identificar elementos scrolleables con altura fija
  const scrollables = await page.evaluate(() => {
    const els = Array.from(document.querySelectorAll('*'));
    return els
      .filter((el) => {
        const cs = getComputedStyle(el);
        return ['auto', 'scroll'].includes(cs.overflowY) && el.scrollHeight > el.clientHeight;
      })
      .slice(0, 5)
      .map((el) => ({
        tag: el.tagName,
        className: (el.className || '').toString().slice(0, 80),
        scrollH: el.scrollHeight,
        clientH: el.clientHeight,
        x: Math.round(el.getBoundingClientRect().left),
        w: Math.round(el.getBoundingClientRect().width),
      }));
  });
  log(`Scrolleables:`);
  scrollables.forEach((s, i) => log(`  ${i}: ${s.tag}.${s.className.slice(0,40)} x=${s.x} w=${s.w} scroll=${s.scrollH}/${s.clientH}`));

  // Buscar iframe del PDF (pdf-viewer)
  const iframes = await page.frames();
  log(`Iframes: ${iframes.length}`);
  for (const f of iframes) log(`  - ${f.url().slice(0, 60)}`);

  // Scroll panel izquierdo (form)
  const leftPanel = page.locator('.overflow-y-auto.p-6.space-y-3').first();
  const leftBox = await leftPanel.boundingBox();
  log(`Panel izq: ${JSON.stringify(leftBox)}`);
  await page.mouse.move(leftBox.x + leftBox.width / 2, leftBox.y + leftBox.height / 2);
  await page.mouse.wheel(0, 800);
  await page.waitForTimeout(800);
  const leftTop = await leftPanel.evaluate((el) => el.scrollTop);
  log(`Después wheel sobre izq: leftPanel.scrollTop=${leftTop}`);
  const allScrolls = await page.evaluate(() => ({
    body: document.body.scrollTop,
    html: document.documentElement.scrollTop,
    main: document.getElementById('main-content')?.scrollTop,
  }));
  log(`Otros scrolls: ${JSON.stringify(allScrolls)}`);

  await page.screenshot({ path: `${DIR}/04-after-scroll-left.png`, fullPage: false });

  await ctx.close();
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
