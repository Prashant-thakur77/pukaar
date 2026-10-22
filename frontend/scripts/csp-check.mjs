#!/usr/bin/env node
// Serves the built app (dist/) with the exact headers Amplify sends (infra/template.yaml AmplifyApp
// CustomHeaders, ${AWS::Region} filled in), opens the main pages in headless Chromium and fails on any
// Content-Security-Policy violation. API calls to the stack's execute-api host are answered by a local
// backend, so pages render real data. Usage:
//   VITE_API_BASE=https://abc123defg.execute-api.us-east-1.amazonaws.com \
//   VITE_EVENTS_HTTP_DOMAIN=x.appsync-api.us-east-1.amazonaws.com \
//   VITE_EVENTS_REALTIME_DOMAIN=x.appsync-realtime-api.us-east-1.amazonaws.com VITE_EVENTS_API_KEY=da2-x \
//   VITE_COGNITO_REGION=us-east-1 npm run build
//   (cd ../backend && PUKAAR_MODE=local PUKAAR_CORS_ORIGINS=http://127.0.0.1:4180 PYTHONPATH=src python -m uvicorn Pukaar.main:app --port 8000) &
//   node scripts/csp-check.mjs [--api http://127.0.0.1:8000] [--port 4180]
// Never runs `playwright install`.
import { readFileSync, existsSync, readdirSync, statSync } from 'node:fs';
import http from 'node:http';
import { homedir } from 'node:os';
import { extname, join, normalize } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

const arg = (name, dflt) => {
  const i = process.argv.indexOf(`--${name}`);
  return i > 0 ? process.argv[i + 1] : dflt;
};
const API = arg('api', 'http://127.0.0.1:8000');
const PORT = Number(arg('port', '4180'));
const REGION = arg('region', 'us-east-1');
const DIST = fileURLToPath(new URL('../dist/', import.meta.url));
const TEMPLATE = fileURLToPath(new URL('../../infra/template.yaml', import.meta.url));

/** The headers block of AmplifyApp.CustomHeaders, as Amplify would send them. */
export function amplifyHeaders(templateText, region) {
  // `!Sub |` (a plain string) or `!Sub [ |, {vars} ]` (the string plus variables such as ${EdgeConnect}).
  const start = templateText.indexOf('CustomHeaders: !Sub');
  if (start < 0) throw new Error('AmplifyApp CustomHeaders not found in the template');
  const block = templateText.slice(start, templateText.indexOf('CustomRules:', start));
  const out = {};
  for (const m of block.matchAll(/- key: (\S+)\s*\n\s*value: "(.*)"/g)) {
    // Template variables other than the region (the prod-only edge host) are empty here, as on the dev stack.
    out[m[1]] = m[2].replaceAll('${AWS::Region}', region).replace(/\$\{[A-Za-z]+\}/g, '');
  }
  return out;
}

const HEADERS = amplifyHeaders(readFileSync(TEMPLATE, 'utf8'), REGION);
// Negative control: CSP_OVERRIDE="default-src 'self'" must make this script fail.
if (process.env.CSP_OVERRIDE) HEADERS['Content-Security-Policy'] = process.env.CSP_OVERRIDE;
const seen = { api: 0, tiles: 0 };

const TYPES = {
  '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json',
  '.svg': 'image/svg+xml', '.png': 'image/png', '.jpg': 'image/jpeg', '.webp': 'image/webp', '.woff2': 'font/woff2',
  '.webmanifest': 'application/manifest+json', '.bin': 'application/octet-stream', '.mp3': 'audio/mpeg', '.txt': 'text/plain',
};

const server = http.createServer((req, res) => {
  const path = decodeURIComponent(new URL(req.url, 'http://x').pathname);
  let file = normalize(join(DIST, path));
  if (!file.startsWith(DIST)) file = join(DIST, 'index.html');
  if (!existsSync(file) || statSync(file).isDirectory()) file = extname(path) ? '' : join(DIST, 'index.html');
  if (!file) {
    res.writeHead(404, HEADERS).end('not found');
    return;
  }
  res.writeHead(200, { ...HEADERS, 'Content-Type': TYPES[extname(file)] ?? 'application/octet-stream' });
  res.end(readFileSync(file));
});
await new Promise((r) => server.listen(PORT, '127.0.0.1', r));
const BASE = `http://127.0.0.1:${PORT}`;

async function devToken(username) {
  const r = await fetch(`${API}/auth/dev-login`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username }) });
  return r.ok ? (await r.json()).token : null;
}
const token = await devToken('officer1');
const reports = token ? await (await fetch(`${API}/reports`, { headers: { Authorization: `Bearer ${token}` } })).json() : [];
const code = reports[0]?.track_code ?? 'UNKNOWN';

const PAGES = [
  ['/', false], ['/live', false], ['/report', false], ['/village/thunag', false], ['/how', false], ['/sensors', false],
  ['/agents', false], ['/impact', false], ['/pilot', false], [`/t/${code}`, false], ['/login', false],
  ['/console', true], ['/audit', true], ['/roster', true], ['/status.html', false],
];
const PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==', 'base64');

/** An already installed Chromium (PLAYWRIGHT_BROWSERS_PATH, /opt/pw-browsers or ~/.cache/ms-playwright). */
function executablePath() {
  for (const root of [process.env.PLAYWRIGHT_BROWSERS_PATH, '/opt/pw-browsers', join(homedir(), '.cache/ms-playwright')]) {
    if (!root || !existsSync(root)) continue;
    for (const dir of readdirSync(root).filter((d) => /^chromium-\d+$/.test(d)).sort().reverse()) {
      for (const sub of ['chrome-linux64/chrome', 'chrome-linux/chrome']) {
        const p = join(root, dir, sub);
        if (existsSync(p)) return p;
      }
    }
  }
  return undefined;
}

const browser = await chromium.launch({ executablePath: executablePath() });
const ctx = await browser.newContext({ serviceWorkers: 'block' });
// The stack's API host is answered by the local backend; map tiles get a 1x1 PNG. CSP is checked by
// the browser before a request is made, so routing hides no violation.
await ctx.route(/https:\/\/[a-z0-9]+\.execute-api\.[a-z0-9-]+\.amazonaws\.com\/.*/, async (route) => {
  const u = new URL(route.request().url());
  seen.api++;
  const resp = await route.fetch({ url: `${API}${u.pathname}${u.search}` }).catch(() => null);
  if (resp) await route.fulfill({ response: resp });
  else await route.abort();
});
await ctx.route(/https:\/\/(tile\.openstreetmap\.org|s3\.amazonaws\.com\/elevation-tiles-prod)\/.*/, (route) => {
  seen.tiles++;
  return route.fulfill({ status: 200, contentType: 'image/png', body: PNG });
});

let failures = 0;
for (const [path, auth] of PAGES) {
  const page = await ctx.newPage();
  await page.addInitScript(
    ({ auth: a, tok }) => {
      window.__csp = [];
      document.addEventListener('securitypolicyviolation', (e) =>
        window.__csp.push(`${e.violatedDirective} blocked ${e.blockedURI || '(inline)'} at ${e.sourceFile || ''}:${e.lineNumber || ''}`),
      );
      sessionStorage.setItem('pukaar.intro', '1');
      if (a && tok) {
        localStorage.setItem('pukaar.token', tok);
        localStorage.setItem('pukaar.user', JSON.stringify({ username: 'officer1', role: 'officer', village_ids: [] }));
      }
    },
    { auth, tok: token },
  );
  const consoleCsp = [];
  page.on('console', (m) => {
    const t = m.text();
    if (/Content[- ]Security[- ]Policy|Refused to/i.test(t)) consoleCsp.push(t);
  });
  const resp = await page.goto(`${BASE}${path}`, { waitUntil: 'networkidle', timeout: 30000 }).catch((e) => ({ err: e }));
  await page.waitForTimeout(1500);
  // Maps load only once they scroll into view (LazyVillageMap): bring each one in so MapLibre, its worker
  // and the tiles are checked too.
  if (!resp?.err && (await page.locator('.map-gate').count())) {
    await page.locator('.map-gate').first().scrollIntoViewIfNeeded().catch(() => {});
    await page.waitForSelector('.maplibregl-canvas', { state: 'attached', timeout: 20000 }).catch(() => {});
    await page.waitForTimeout(2000);
  }
  const events = await page.evaluate(() => window.__csp ?? []);
  const csp = resp?.headers?.()['content-security-policy'];
  const problems = [...new Set([...consoleCsp, ...events])];
  const status = resp?.err ? `load error ${resp.err.message.split('\n')[0]}` : `${resp.status()}`;
  console.log(`${problems.length ? 'FAIL' : 'ok  '} ${path} (${status}${csp ? ', CSP header present' : ', NO CSP HEADER'})`);
  for (const p of problems) console.log(`     ${p}`);
  if (problems.length || !csp) failures++;
  await page.close();
}
// The console opens the after-action report (static HTML with inline style attributes, its own CSP meta)
// from a blob: URL, the way AfterActionLinks does. A blob document inherits this page's policy, so the
// report's styles must survive it.
{
  const page = await ctx.newPage();
  await page.goto(`${BASE}/console`, { waitUntil: 'domcontentloaded' });
  const popupPromise = page.waitForEvent('popup');
  await page.evaluate(() => {
    const html = '<!doctype html><html><head><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; ' +
      'style-src \'unsafe-inline\'; img-src data:"></head><body><p id="x" style="color: rgb(200, 23, 63)">report</p></body></html>';
    const url = URL.createObjectURL(new Blob([html], { type: 'text/html;charset=utf-8' }));
    const win = window.open('', '_blank');
    win.location.href = url;
  });
  const popup = await popupPromise;
  await popup.waitForLoadState('load');
  await popup.waitForSelector('#x');
  const colour = await popup.evaluate(() => getComputedStyle(document.getElementById('x')).color);
  const ok = colour === 'rgb(200, 23, 63)';
  console.log(`${ok ? 'ok  ' : 'FAIL'} after-action report from a blob: URL keeps its inline styles (${colour})`);
  if (!ok) failures++;
  await page.close();
}

await browser.close();
server.close();
console.log(`${seen.api} API calls answered by ${API}, ${seen.tiles} map tiles requested`);
console.log(failures ? `${failures} page(s) with CSP problems` : `No CSP violations on ${PAGES.length} pages`);
process.exit(failures ? 1 : 0);
