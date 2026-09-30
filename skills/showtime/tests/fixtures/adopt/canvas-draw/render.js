// The driver a model writes next to its page (never run by the tests: adopt only reads it).
//   node render.js  -> story.mp4
const fs = require('fs');
const path = require('path');
const puppeteer = require('puppeteer-core');

const FPS = 30;
(async () => {
  const browser = await puppeteer.launch({ headless: true });
  const page = await browser.newPage();
  await page.setViewport({ width: 1280, height: 720, deviceScaleFactor: 1 });
  await page.goto('file://' + path.join(__dirname, 'story.html'));
  const rows = JSON.parse(fs.readFileSync(path.join(__dirname, 'data.json'), 'utf8'));
  await page.evaluate((r) => window.setData(r), rows);
  const duration = await page.evaluate(() => window.DURATION);
  for (let f = 0; f < Math.round(duration * FPS); f++) {
    await page.evaluate((t) => window.draw(t), f / FPS);
    await page.screenshot({ path: `frames/${String(f).padStart(5, '0')}.png` });
  }
  await browser.close();
})();
