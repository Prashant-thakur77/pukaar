#!/usr/bin/env node
// Fails if React logs "Maximum update depth" (a render loop) on /live or
// /village/:id. React only prints that warning in development, so this starts
// the Vite dev server itself and drives it with Playwright. Usage:
//   npm run check:loops -- [--api http://127.0.0.1:8000] [--seconds 5]
// Never runs `playwright install`; uses /opt/pw-browsers.
import { existsSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { createServer } from 'vite';
import { chromium } from 'playwright';

const arg = (name, dflt) => {
  const i = process.argv.indexOf(`--${name}`);
  return i > 0 ? process.argv[i + 1] : dflt;
};
const API = arg('api', process.env.VITE_API_BASE ?? 'http://127.0.0.1:8000');
const SECONDS = Number(arg('seconds', '5'));

function executablePath() {
  const root = process.env.PLAYWRIGHT_BROWSERS_PATH ?? '/opt/pw-browsers';
  const dir = existsSync(root) ? readdirSync(root).find((d) => /^chromium-\d+$/.test(d)) : null;
  const p = dir ? `${root}/${dir}/chrome-linux/chrome` : undefined;
  return p && existsSync(p) ? p : undefined;
}

// 1x1 transparent PNG.
const TILE = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=', 'base64');

let village = 'thunag';
try {
  const o = await (await fetch(`${API}/public/overview`)).json();
  village = o.villages?.[0]?.id ?? village;
} catch {
  /* the pages still render (with an error state) without the API */
}

process.env.VITE_API_BASE = API;
const server = await createServer({
  root: fileURLToPath(new URL('..', import.meta.url)),
  server: { port: 5199, strictPort: false, host: '127.0.0.1' },
  logLevel: 'error',
});
await server.listen();
const base = server.resolvedUrls.local[0].replace(/\/$/, '');
const browser = await chromium.launch({ executablePath: executablePath() });
const failures = [];
try {
  for (const path of ['/live', `/village/${village}`]) {
    for (const width of [390, 1440]) {
      const ctx = await browser.newContext({ viewport: { width, height: 900 } });
      // Map tiles are not needed to find a render loop: answer with an empty tile.
      await ctx.route('https://tile.openstreetmap.org/**', (r) => r.fulfill({ status: 200, contentType: 'image/png', body: TILE }));
      // Fetch the API from Playwright so the dev server's origin needs no CORS entry.
      await ctx.route(`${API}/**`, async (r) => {
        const cors = { 'access-control-allow-origin': '*', 'access-control-allow-headers': '*', 'access-control-allow-methods': '*' };
        if (r.request().method() === 'OPTIONS') return r.fulfill({ status: 204, headers: cors });
        const res = await r.fetch({ headers: { ...r.request().headers(), origin: API } });
        return r.fulfill({ response: res, headers: { ...res.headers(), ...cors } });
      });
      const page = await ctx.newPage();
      await page.addInitScript(() => sessionStorage.setItem('pukaar.intro', '1'));
      let n = 0;
      page.on('console', (m) => {
        if (/Maximum update depth/.test(m.text())) n += 1;
      });
      await page.goto(`${base}${path}`, { waitUntil: 'load' });
      await page.waitForSelector('main#main', { timeout: 30000 });
      await page.waitForTimeout(SECONDS * 1000);
      const markers = await page.locator('.mk').count();
      console.log(`${path} @${width}: ${markers} map marker(s), ${n} "Maximum update depth" message(s)`);
      if (n) failures.push(`${path} @${width}`);
      await ctx.close();
    }
  }
} finally {
  await browser.close();
  await server.close();
}
if (failures.length) {
  console.error(`FAIL: render loop on ${failures.join(', ')}`);
  process.exit(1);
}
console.log('OK: no render loops');
