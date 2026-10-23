#!/usr/bin/env node
// The font-size floor (redesign spec 3.1 and 8.3): no visible text under 16 px on a public page, none under 14 px
// in the officer console. Walks every text node of each page at 390 and 1440 px, Hindi and English.
//   npm run build && npm run check:fonts                    serves dist/ itself, answers the API with scripts/mock-api.mjs
//   npm run check:fonts -- --base http://127.0.0.1:5173 --api http://127.0.0.1:8000   a running app and a local backend
//   [--only /,/how] [--langs hi] [--widths 390]
// The mock answers with sample data (every page says so); the floor does not depend on the numbers. The built app's
// API base (its <meta name="pk-api">) is routed to the API given. Never runs `playwright install`.
import { spawn } from 'node:child_process';
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import http from 'node:http';
import { homedir } from 'node:os';
import { extname, join, normalize } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

const arg = (name, dflt) => {
  const i = process.argv.indexOf(`--${name}`);
  return i > 0 ? process.argv[i + 1] : dflt;
};
const HERE = fileURLToPath(new URL('.', import.meta.url));
const DIST = join(HERE, '../dist');
const ONLY = arg('only', '').split(',').filter(Boolean);
const LANGS = arg('langs', 'hi,en').split(',');
const WIDTHS = arg('widths', '390,1440').split(',').map(Number);

export const PUBLIC_MIN = 16;
export const CONSOLE_MIN = 14;
const PUBLIC = ['/', '/live', '/how', '/proof', '/pilot', '/report', '/village/gohar', '/t/PK0000', '/login'];
const CONSOLE = ['/console/inbox', '/console/villages', '/console/reports', '/console/rollcall', '/console/roster', '/console/audit', '/console/settings', '/console/enrol', '/console/group?d=Mandi&c=rain&s=replay', '/console/demo'];

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

const TYPES = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json', '.svg': 'image/svg+xml', '.png': 'image/png', '.webp': 'image/webp', '.woff2': 'font/woff2', '.webmanifest': 'application/manifest+json' };

/** dist/ as Amplify serves it: a file when there is one, index.html for any route. */
function serveDist() {
  if (!existsSync(join(DIST, 'index.html'))) throw new Error('no dist/index.html: run npm run build first');
  const server = http.createServer((req, res) => {
    const path = normalize(decodeURIComponent(new URL(req.url, 'http://x').pathname)).replace(/^(\.\.[/\\])+/, '');
    let file = join(DIST, path);
    if (!existsSync(file) || statSync(file).isDirectory()) file = join(DIST, 'index.html');
    res.writeHead(200, { 'Content-Type': TYPES[extname(file)] ?? 'application/octet-stream' });
    res.end(readFileSync(file));
  });
  return new Promise((ok) => server.listen(0, '127.0.0.1', () => ok({ server, base: `http://127.0.0.1:${server.address().port}` })));
}

/** scripts/mock-api.mjs on a free port, until we are done. */
async function startMock() {
  const port = 18787 + Math.floor(Math.random() * 1000);
  const child = spawn(process.execPath, [join(HERE, 'mock-api.mjs')], { env: { ...process.env, MOCK_PORT: String(port) }, stdio: 'ignore' });
  const api = `http://127.0.0.1:${port}`;
  for (let i = 0; i < 50; i++) {
    try {
      if ((await fetch(`${api}/public/overview`)).ok) return { child, api };
    } catch {
      /* not up yet */
    }
    await new Promise((r) => setTimeout(r, 100));
  }
  child.kill();
  throw new Error('the mock API did not start');
}

/** A signed-in officer: the local backend's dev-login, or the mock's "dev-<user>" token. */
async function officer(api, mock) {
  if (mock) return { token: 'dev-officer1', user: { username: 'officer1', role: 'officer', village_ids: [] } };
  const res = await fetch(`${api}/auth/dev-login`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username: 'officer1' }) });
  if (!res.ok) throw new Error(`dev-login failed: ${res.status} (is the API running in local mode at ${api}?)`);
  const { token } = await res.json();
  const me = await (await fetch(`${api}/me`, { headers: { Authorization: `Bearer ${token}` } })).json();
  return { token, user: { username: me.username, role: me.role, village_ids: me.village_ids ?? [] } };
}

/** Every visible text node under `min` px, as "14px span.lv-word: 'text'" (one line per style). */
function smallText(min) {
  const out = new Map();
  let seen = 0;
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const text = n.textContent.trim();
    if (!text) continue;
    const el = n.parentElement;
    // Text hidden from screen readers but on screen (a chart's numbers) is read by eyes, so it counts too.
    if (!el || el.closest('.sr-only, noscript, script, style, .maplibregl-ctrl-attrib')) continue;
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height) continue;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none' || Number(cs.opacity) === 0) continue;
    seen += 1;
    const fs = parseFloat(cs.fontSize);
    if (fs < min - 0.01) {
      const key = `${fs}px ${el.tagName.toLowerCase()}.${(el.getAttribute('class') || '').split(' ')[0]}`;
      if (!out.has(key)) out.set(key, text.slice(0, 40));
    }
  }
  return { small: [...out.entries()], seen, path: location.pathname };
}

const own = !arg('base');
const dist = own ? await serveDist() : null;
const BASE = arg('base') ?? dist.base;
const mock = !arg('api');
const mocked = mock ? await startMock() : null;
const API = arg('api') ?? mocked.api;
// The built app calls the API base it was built with; send those calls to the API we have.
const html = await (await fetch(`${BASE}/`)).text();
const BUILT_API = (html.match(/<meta name="pk-api" content="([^"]+)"/)?.[1] ?? '').replace(/&amp;/g, '&');
const auth = await officer(API, mock);

const browser = await chromium.launch({ executablePath: executablePath() });
let bad = 0;
try {
  const pages = [...PUBLIC.map((p) => [p, PUBLIC_MIN, false]), ...CONSOLE.map((p) => [p, CONSOLE_MIN, true])].filter(([p]) => !ONLY.length || ONLY.includes(p));
  for (const lang of LANGS)
    for (const width of WIDTHS)
      for (const [path, min, signedIn] of pages) {
        const ctx = await browser.newContext({ viewport: { width, height: 900 }, serviceWorkers: 'block', reducedMotion: 'reduce' });
        if (BUILT_API && BUILT_API !== API) {
          await ctx.route((u) => u.href.startsWith(BUILT_API), async (route) => {
            const u = route.request().url().slice(BUILT_API.length);
            const resp = await route.fetch({ url: `${API}${u}` }).catch(() => null);
            if (resp) await route.fulfill({ response: resp });
            else await route.abort();
          });
        }
        await ctx.route(/https:\/\/(tile\.openstreetmap\.org|s3\.amazonaws\.com)\/.*/, (r) => r.abort());
        await ctx.addInitScript(
          ({ l, a }) => {
            try {
              for (const s of ['public', 'villager', 'staff']) localStorage.setItem(`pukaar.lang.${s}`, l);
              if (a) {
                localStorage.setItem('pukaar.token', a.token);
                localStorage.setItem('pukaar.user', JSON.stringify(a.user));
              }
            } catch {
              /* storage blocked */
            }
          },
          { l: lang, a: signedIn ? auth : null },
        );
        const page = await ctx.newPage();
        await page.goto(`${BASE}${path}`, { waitUntil: 'networkidle', timeout: 60000 }).catch(() => {});
        await page.waitForTimeout(1200);
        const { small, seen, path: landed } = await page.evaluate(smallText, min);
        // A page that did not render (or bounced to sign-in) proves nothing: count it as a failure.
        const blank = seen < 8 || (signedIn && landed === '/login');
        if (small.length || blank) bad += small.length || 1;
        console.log(`${small.length || blank ? 'FAIL' : 'ok  '} ${path} ${width} ${lang} (floor ${min} px, ${seen} text nodes${landed !== path.split('?')[0] ? `, landed on ${landed}` : ''})`);
        for (const [k, v] of small.slice(0, 8)) console.log(`     ${k}  "${v}"`);
        await ctx.close();
      }
} finally {
  await browser.close();
  mocked?.child.kill();
  dist?.server.close();
}
console.log(bad ? `\n${bad} text styles under the floor` : '\nno text under the floor (16 px public, 14 px console)');
process.exit(bad ? 1 : 0);
