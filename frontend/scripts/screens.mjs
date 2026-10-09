#!/usr/bin/env node
// Screenshots every page at 390x844 and 1440x900, light and dark, into
// ../docs/screens/, and runs axe-core on each. Usage:
//   npm run build && npx vite preview --port 4173 &   (VITE_API_BASE set at build)
//   npm run screens -- [--base http://127.0.0.1:4173] [--api http://127.0.0.1:8000] [--only landing,live]
// Approval-link pages use a real signed link from GET /dev/approval-link/{id}
// (local mode, needs a pending alert: start a replay first). Without one they
// fall back to the dev mock (npm run mock), which shows the SAMPLE DATA ribbon.
// Exits non-zero if any page logs "Maximum update depth" (a render loop).
// Never runs `playwright install`; uses /opt/pw-browsers.
import { mkdirSync, writeFileSync, existsSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';
import AxeBuilder from '@axe-core/playwright';

const arg = (name, dflt) => {
  const i = process.argv.indexOf(`--${name}`);
  return i > 0 ? process.argv[i + 1] : dflt;
};
const BASE = arg('base', 'http://127.0.0.1:4173');
const API = arg('api', 'http://127.0.0.1:8000');
const MOCK = arg('mock', 'http://127.0.0.1:8787');
const ONLY = arg('only', '')?.split(',').filter(Boolean);
const OUT = fileURLToPath(new URL('../../docs/screens/', import.meta.url));
mkdirSync(OUT, { recursive: true });

function executablePath() {
  const root = process.env.PLAYWRIGHT_BROWSERS_PATH ?? '/opt/pw-browsers';
  const dir = existsSync(root) ? readdirSync(root).find((d) => /^chromium-\d+$/.test(d)) : null;
  const p = dir ? `${root}/${dir}/chrome-linux/chrome` : undefined;
  return p && existsSync(p) ? p : undefined;
}

async function officerToken() {
  const res = await fetch(`${API}/auth/dev-login`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username: 'officer1' }) });
  if (!res.ok) throw new Error(`dev-login failed: ${res.status}`);
  return (await res.json()).token;
}

async function firstVillage() {
  const res = await fetch(`${API}/public/overview`);
  const o = await res.json();
  const order = ['critical', 'warning', 'watch', 'normal'];
  return [...o.villages].sort((a, b) => order.indexOf(a.level) - order.indexOf(b.level))[0]?.id ?? 'thunag';
}

async function trackCode() {
  if (process.env.SCREENS_TRACK) return process.env.SCREENS_TRACK;
  const tok = await officerToken();
  const res = await fetch(`${API}/reports`, { headers: { Authorization: `Bearer ${tok}` } });
  const list = res.ok ? await res.json() : [];
  return list[0]?.track_code ?? 'UNKNOWN';
}

const token = await officerToken();
const village = await firstVillage();
const code = await trackCode();

/** Real one-tap links for the first two pending alerts; the second one is decided so its link is "late". */
async function approvalLinks() {
  const h = { Authorization: `Bearer ${token}` };
  try {
    const pending = await (await fetch(`${API}/alerts?status=pending`, { headers: h })).json();
    if (!Array.isArray(pending) || pending.length < 2) return null;
    const link = async (id) => {
      const r = await fetch(`${API}/dev/approval-link/${id}`, { headers: h });
      return r.ok ? (await r.json()).token : null;
    };
    const live = await link(pending[0].id);
    const late = await link(pending[pending.length - 1].id);
    if (!live || !late) return null;
    await fetch(`${API}/approval/${late}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ decision: 'decline' }) });
    return { live, late };
  } catch {
    return null;
  }
}
const wantsApprove = !ONLY?.length || ONLY.some((n) => n.startsWith('approve'));
const links = wantsApprove ? await approvalLinks() : null;
if (wantsApprove) console.log(links ? 'approval pages: real signed links' : 'approval pages: dev mock (no pending alerts)');

const PAGES = [
  { name: 'landing', path: '/' },
  { name: 'live', path: '/live', wait: '.mk, .map-fail' },
  { name: 'report', path: '/report' },
  { name: 'track', path: `/t/${code}` },
  links ? { name: 'approve', path: `/a/${links.live}` } : { name: 'approve', path: '/a/demo', mock: true },
  links ? { name: 'approve-late', path: `/a/${links.late}` } : { name: 'approve-late', path: '/a/late', mock: true },
  { name: 'approve-invalid', path: '/a/not-a-real-link' },
  { name: 'village', path: `/village/${village}` },
  { name: 'console', path: '/console', auth: true },
  { name: 'audit', path: '/audit', auth: true },
  { name: 'impact', path: '/impact' },
  { name: 'login', path: '/login' },
].filter((p) => !ONLY?.length || ONLY.includes(p.name));

const VIEWPORTS = [
  { w: 390, h: 844, mobile: true },
  { w: 1440, h: 900, mobile: false },
];
const THEMES = ['light', 'dark'];

const browser = await chromium.launch({ executablePath: executablePath() });

// Map tiles are fetched from Node (which honours HTTPS_PROXY when run with
// NODE_USE_ENV_PROXY=1) so the browser itself never needs a proxy.
const tileCache = new Map();
async function routeTiles(ctx) {
  await ctx.route('https://tile.openstreetmap.org/**', async (route) => {
    const url = route.request().url();
    try {
      if (!tileCache.has(url)) {
        const r = await fetch(url, { headers: { 'User-Agent': 'pukaar-dev-screenshots/1.0' } });
        tileCache.set(url, { status: r.status, contentType: r.headers.get('content-type') ?? 'image/png', body: Buffer.from(await r.arrayBuffer()) });
      }
      await route.fulfill(tileCache.get(url));
    } catch {
      await route.abort();
    }
  });
}

const axeSummary = [];
const loops = [];

async function settle(page) {
  // Scroll through so IntersectionObserver reveals fire, then return to top.
  const height = await page.evaluate(() => document.body.scrollHeight);
  for (let y = 0; y < height; y += 500) {
    await page.evaluate((yy) => window.scrollTo(0, yy), y);
    await page.waitForTimeout(90);
  }
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(900);
}

for (const vp of VIEWPORTS) {
  for (const theme of THEMES) {
    const ctx = await browser.newContext({
      viewport: { width: vp.w, height: vp.h },
      deviceScaleFactor: 1,
      isMobile: vp.mobile,
      hasTouch: vp.mobile,
      colorScheme: theme,
      ignoreHTTPSErrors: true,
    });
    await routeTiles(ctx);
    for (const pg of PAGES) {
      const page = await ctx.newPage();
      await page.addInitScript(
        ({ auth, tok }) => {
          sessionStorage.setItem('pukaar.intro', '1');
          if (auth) {
            localStorage.setItem('pukaar.token', tok);
            localStorage.setItem('pukaar.user', JSON.stringify({ username: 'officer1', role: 'officer', village_ids: [] }));
          } else {
            localStorage.removeItem('pukaar.token');
            localStorage.removeItem('pukaar.user');
          }
        },
        { auth: Boolean(pg.auth), tok: token },
      );
      if (pg.mock) {
        await page.route(`${API}/**`, async (route) => {
          const u = new URL(route.request().url());
          const res = await route.fetch({ url: `${MOCK}${u.pathname}${u.search}` });
          await route.fulfill({ response: res });
        });
      }
      const errors = [];
      page.on('pageerror', (e) => errors.push(e.message));
      page.on('console', (m) => {
        if (m.type() === 'error' && /Maximum update depth/.test(m.text())) loops.push(`${pg.name}-${vp.w}-${theme}`);
      });
      await page.goto(`${BASE}${pg.path}`, { waitUntil: 'load' });
      await page.waitForSelector('main#main', { timeout: 15000 });
      await page.waitForTimeout(1200);
      if (pg.wait) await page.waitForSelector(pg.wait, { timeout: 15000 }).catch(() => {});
      if (pg.name === 'live' || pg.name === 'village') await page.waitForTimeout(1500); // map tiles
      await settle(page);
      const file = `${pg.name}-${vp.w}-${theme}.png`;
      await page.screenshot({ path: `${OUT}${file}`, fullPage: true });
      const hscroll = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      const axe = await new AxeBuilder({ page }).disableRules(['region']).analyze();
      const bad = axe.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical');
      axeSummary.push({ page: pg.name, viewport: vp.w, theme, serious_or_critical: bad.map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.slice(0, 4).map((n) => n.target.join(' ') + ' :: ' + (n.failureSummary ?? '').split('\n')[1]) })), hscroll, errors });
      console.log(`${file}  axe:${bad.length}  hscroll:${hscroll}${errors.length ? `  errors:${errors.join(' | ')}` : ''}`);
      await page.close();
    }
    await ctx.close();
  }
}

// Extra states: the intro mid-animation and the Ask Pukaar answer.
if (!ONLY?.length || ONLY.includes('extras')) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, colorScheme: 'dark', ignoreHTTPSErrors: true });
  await routeTiles(ctx);
  const page = await ctx.newPage();
  await page.goto(`${BASE}/`, { waitUntil: 'load' });
  await page.waitForSelector('.intro', { timeout: 10000 }).catch(() => {});
  await page.waitForTimeout(900);
  await page.screenshot({ path: `${OUT}landing-intro-1440.png` });
  await page.close();

  const p2 = await ctx.newPage();
  await p2.addInitScript((tok) => {
    localStorage.setItem('pukaar.token', tok);
    localStorage.setItem('pukaar.user', JSON.stringify({ username: 'officer1', role: 'officer', village_ids: [] }));
  }, token);
  await p2.goto(`${BASE}/console#ask`, { waitUntil: 'load' });
  await p2.waitForTimeout(1500);
  const chip = p2.locator('.suggest .chip-btn').first();
  if (await chip.count()) {
    await chip.click();
    await p2.waitForSelector('.ask-answer, .state-error, .denied', { timeout: 30000 }).catch(() => {});
    await p2.waitForTimeout(1200);
    const toggle = p2.locator('#ask .trace-toggle');
    if (await toggle.count()) await toggle.click();
    // The sticky header would otherwise sit on top of the element screenshot.
    await p2.addStyleTag({ content: '.site-header, .replay-banner { position: static !important; }' });
    await p2.locator('#ask').screenshot({ path: `${OUT}console-ask-1440-dark.png` });
  }
  await p2.close();
  await ctx.close();
}

await browser.close();
writeFileSync(`${OUT}axe-summary.json`, JSON.stringify(axeSummary, null, 2));
const total = axeSummary.reduce((n, r) => n + r.serious_or_critical.length, 0);
console.log(`\naxe serious/critical total: ${total}`);
for (const r of axeSummary) if (r.serious_or_critical.length) console.log(JSON.stringify(r, null, 1));
if (loops.length) {
  console.error(`render loop ("Maximum update depth") on: ${[...new Set(loops)].join(', ')}`);
  process.exitCode = 1;
}
