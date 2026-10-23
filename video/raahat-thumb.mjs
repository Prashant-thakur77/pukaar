#!/usr/bin/env node
// The YouTube thumbnail for the Raahat film (1280×720 JPEG): the Sentinel-2 image after the July 2023 flood, as the
// live site serves it, under the film's headline and wordmark; and a square logo for the DoraHacks BUIDL page (the
// app's own mark, frontend/public/favicon.svg, over the wordmark).
//   node video/raahat-thumb.mjs   -> docs/media/pukaar-raahat-thumbnail.jpg, docs/media/pukaar-raahat-logo.png
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { CHROME, ROOT, chromium, log } from "./lib/engine.mjs";
import { facts } from "./raahat.mjs";

const f = await facts(ROOT);
const html = `<!doctype html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Anton&family=Inter:wght@700;800&family=Noto+Sans+Devanagari:wght@900&display=block">
<style>
  html, body { margin: 0; width: 1280px; height: 720px; overflow: hidden; background: #0f1530; }
  .bg { position: absolute; inset: 0; background: url("${f.liveUrl}/satellite/2023/${f.sat.date}.jpg") center/cover; filter: saturate(1.15); }
  .shade { position: absolute; inset: 0; background: linear-gradient(90deg, rgb(15 21 48 / 94%) 0%, rgb(15 21 48 / 82%) 52%, rgb(15 21 48 / 10%) 100%); }
  .t { position: absolute; left: 64px; top: 70px; width: 760px; color: #fff; font: 400 118px/0.95 Anton, sans-serif; text-transform: uppercase; }
  .t mark { background: #f2a93b; color: #141a33; padding: 0 12px; }
  .wm { position: absolute; left: 64px; bottom: 64px; display: flex; align-items: baseline; gap: 22px; color: #f2a93b; }
  .wm .hi { font: 900 92px/1 "Noto Sans Devanagari", sans-serif; }
  .wm .en { font: 400 46px/1 Anton, sans-serif; letter-spacing: 0.14em; color: #fff; }
  .chip { position: absolute; right: 44px; bottom: 52px; font: 800 26px/1 Inter, sans-serif; color: #141a33; background: #fff; border: 3px solid #141a33; box-shadow: 7px 7px 0 #141a33; border-radius: 10px; padding: 14px 18px; }
</style></head><body>
<div class="bg"></div><div class="shade"></div>
<div class="t">Relief <mark>before</mark> the river</div>
<div class="wm"><span class="hi">पुकार राहत</span><span class="en">Pukaar Raahat</span></div>
<div class="chip">Live demo · Base Sepolia</div>
</body></html>`;
const browser = await chromium.launch({ executablePath: CHROME });
const page = await browser.newPage({ viewport: { width: 1280, height: 720 } });
await page.setContent(html, { waitUntil: "networkidle" });
await page.evaluate(() => document.fonts.ready);
const out = join(ROOT, "docs/media/pukaar-raahat-thumbnail.jpg");
await page.screenshot({ path: out, type: "jpeg", quality: 90 });
log(`thumbnail: ${out}`);

const mark = readFileSync(join(ROOT, "frontend/public/favicon.svg"), "utf8");
await page.setViewportSize({ width: 480, height: 480 });
await page.setContent(`<!doctype html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Anton&family=Noto+Sans+Devanagari:wght@900&display=block">
<style>
  html, body { margin: 0; width: 480px; height: 480px; background: #0B1026; overflow: hidden; }
  .m { position: absolute; left: 140px; top: 46px; width: 200px; height: 200px; }
  .hi { position: absolute; left: 0; right: 0; top: 262px; text-align: center; color: #F5A524; font: 900 84px/1 "Noto Sans Devanagari", sans-serif; }
  .en { position: absolute; left: 0; right: 0; top: 388px; text-align: center; color: #fff; font: 400 38px/1 Anton, sans-serif; letter-spacing: 0.16em; text-transform: uppercase; }
</style></head><body><div class="m">${mark}</div><div class="hi">पुकार राहत</div><div class="en">Pukaar Raahat</div></body></html>`, { waitUntil: "networkidle" });
await page.evaluate(() => document.fonts.ready);
const logo = join(ROOT, "docs/media/pukaar-raahat-logo.png");
await page.screenshot({ path: logo });
await browser.close();
log(`logo: ${logo}`);
