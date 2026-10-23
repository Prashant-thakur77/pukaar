#!/usr/bin/env node
// Measures every interactive element on the villager, public and officer pages at 390 px and fails if any is
// smaller than 44 x 44 CSS px (WCAG 2.5.5 Target Size, Apple HIG). Usage:
//   (cd ../backend && PUKAAR_MODE=local PUKAAR_CORS_ORIGINS=http://127.0.0.1:5173 PYTHONPATH=src python -m uvicorn Pukaar.main:app --port 8000) &
//   VITE_API_BASE=http://127.0.0.1:8000 npm run dev &
//   npm run check:taps -- [--base http://127.0.0.1:5173] [--api http://127.0.0.1:8000] [--width 390] [--only console,live,pilot] [--json out.json]
// What counts: links, buttons, form fields, summary, and anything with a button/link/tab/checkbox/switch role
// or a non-negative tabindex. A checkbox, radio or file input is measured by its label when it has one (the
// label is the hit area). WCAG 2.5.5 exempts links inside a sentence ("inline"); those are listed, not failed.
// Visually hidden elements (the skip link before focus) are measured again with focus. Never runs
// `playwright install`.
import { existsSync, readdirSync, writeFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';
import { chromium } from 'playwright';

const arg = (name, dflt) => {
  const i = process.argv.indexOf(`--${name}`);
  return i > 0 ? process.argv[i + 1] : dflt;
};
const BASE = arg('base', 'http://127.0.0.1:5173');
const API = arg('api', 'http://127.0.0.1:8000');
const WIDTH = Number(arg('width', '390'));
const MIN = 44;
const ONLY = arg('only', '')?.split(',').filter(Boolean);
const JSON_OUT = arg('json', '');

async function login(username = 'officer1') {
  const res = await fetch(`${API}/auth/dev-login`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username }) });
  if (!res.ok) throw new Error(`dev-login failed: ${res.status} (is the API running in local mode at ${API}?)`);
  const { token } = await res.json();
  const me = await (await fetch(`${API}/me`, { headers: { Authorization: `Bearer ${token}` } })).json();
  return { token, user: { username: me.username, role: me.role, village_ids: me.village_ids ?? [] } };
}

async function firstVillage() {
  const o = await (await fetch(`${API}/public/overview`)).json();
  return o.villages?.[0]?.id ?? 'thunag';
}

async function showMap(page) {
  // Scrolling it into view loads it; the button is the fallback.
  await page.locator('.map-gate').first().scrollIntoViewIfNeeded({ timeout: 5000 }).catch(() => {});
  await page.waitForTimeout(500);
  const gate = page.locator('.map-gate button').first();
  if (await gate.count()) await gate.click({ timeout: 5000 }).catch(() => {});
  const loaded = await page.waitForSelector('.maplibregl-canvas', { timeout: 30000 }).then(() => true, () => false);
  if (!loaded) console.log('   (the map did not load; its controls are not measured)');
  await page.waitForTimeout(2500);
}

const auth = await login();
const village = await firstVillage();
const PAGES = [
  // The console (spec 4.9): the inbox opens the first alert waiting, if any; the other sections one by one.
  { name: 'console', path: '/console/inbox', auth: true },
  // On a phone the decision is its own screen: open the first alert waiting (or sent) and measure it too.
  {
    name: 'console-decision',
    path: '/console/inbox',
    auth: true,
    prep: async (page) => {
      const row = page.locator('.ib-row').first();
      if (!(await row.count())) await page.goto(page.url().replace('/console/inbox', '/console/inbox?v=sent'));
      await page.locator('.ib-row').first().click({ timeout: 5000 }).catch(() => {});
      await page.waitForTimeout(1200);
    },
  },
  { name: 'console-sent', path: '/console/inbox?v=sent', auth: true },
  { name: 'villages', path: '/console/villages', auth: true },
  { name: 'reports', path: '/console/reports', auth: true },
  { name: 'rollcall', path: '/console/rollcall', auth: true },
  { name: 'directives', path: '/console/directives', auth: true },
  { name: 'ask', path: '/console/ask', auth: true },
  { name: 'settings', path: '/console/settings', auth: true },
  { name: 'replay', path: '/console/replay', auth: true },
  { name: 'system', path: '/console/system', auth: true },
  { name: 'roster', path: '/console/roster', auth: true },
  { name: 'enrol', path: '/console/enrol', auth: true },
  { name: 'group', path: '/console/group?d=Mandi&c=rain&s=replay', auth: true },
  { name: 'audit', path: '/console/audit?all=1', auth: true },
  { name: 'village', path: `/village/${village}` },
  { name: 'live', path: '/live' },
  // The map waits behind "Show map" until it scrolls into view; measure its controls and markers too.
  { name: 'live-map', path: '/live', prep: showMap },
  // Thunag has mapped safe places and walking routes, so its page draws a map.
  { name: 'village-map', path: '/village/thunag', prep: showMap },
  { name: 'home', path: '/' },
  { name: 'how', path: '/how' },
  { name: 'proof', path: '/proof' },
  { name: 'pilot', path: '/pilot' },
  { name: 'report', path: '/report' },
  // The compose step shows more controls (staff gauge, photo, voice) once a village is picked.
  {
    name: 'report-village',
    path: '/report',
    prep: async (page) => {
      const sel = page.locator('.report-where select').first();
      const value = await sel.locator('option').nth(1).getAttribute('value');
      if (value) await sel.selectOption(value);
      await page.waitForTimeout(800);
    },
  },
].filter((p) => !ONLY?.length || ONLY.some((o) => p.name === o || p.name.startsWith(`${o}-`)));

/** Runs in the page: every interactive element, its hit-area size and whether WCAG exempts it. */
function measure(min) {
  const SEL = [
    'a[href]', 'button', 'input:not([type=hidden])', 'select', 'textarea', 'summary',
    '[role=button]', '[role=link]', '[role=tab]', '[role=checkbox]', '[role=switch]', '[role=radio]', '[role=menuitem]',
    '[tabindex]:not([tabindex="-1"])',
  ].join(',');
  const shown = (el) => {
    if (el.closest('[aria-hidden="true"], [inert]')) return false;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none') return false;
    const closed = el.closest('details:not([open])');
    if (closed && !el.closest('summary') && closed.querySelector(':scope > summary') !== el) return false;
    return el.getClientRects().length > 0;
  };
  const labelOf = (el) => el.closest('label') ?? (el.id ? document.querySelector(`label[for="${CSS.escape(el.id)}"]`) : null);
  const describe = (el) => {
    const txt = (el.getAttribute('aria-label') || el.innerText || el.value || el.getAttribute('title') || el.getAttribute('placeholder') || '').trim().replace(/\s+/g, ' ');
    const cls = typeof el.className === 'string' && el.className ? `.${el.className.trim().split(/\s+/).slice(0, 2).join('.')}` : '';
    return `${el.tagName.toLowerCase()}${cls} "${txt.slice(0, 40)}"`;
  };
  /** A link inside running text: inline display and sibling text in the same block. */
  const inline = (el) => {
    if (el.tagName !== 'A') return false;
    if (getComputedStyle(el).display !== 'inline') return false;
    const block = el.parentElement;
    const own = (el.innerText || '').trim().length;
    return block ? (block.innerText || '').trim().length > own + 12 : false;
  };
  const seen = new Set();
  const out = [];
  for (const el of document.querySelectorAll(SEL)) {
    if (seen.has(el) || !shown(el)) continue;
    seen.add(el);
    let target = el;
    const type = (el.getAttribute('type') || '').toLowerCase();
    if (el.tagName === 'INPUT' && ['checkbox', 'radio', 'file'].includes(type)) {
      const lab = labelOf(el);
      if (lab) {
        target = lab;
        seen.add(lab);
      }
    }
    let r = target.getBoundingClientRect();
    if (r.width <= 2 || r.height <= 2) {
      // Visually hidden until focused (skip link), or a hidden native input behind a styled label.
      el.focus({ preventScroll: true });
      r = target.getBoundingClientRect();
      el.blur();
      if (r.width <= 2 || r.height <= 2) continue;
    }
    const w = Math.round(r.width * 10) / 10;
    const h = Math.round(r.height * 10) / 10;
    out.push({ what: describe(el), w, h, small: w < min || h < min, inline: inline(el) });
  }
  return out;
}

/** An already installed Chromium (PLAYWRIGHT_BROWSERS_PATH, /opt/pw-browsers or ~/.cache/ms-playwright). */
function executablePath() {
  for (const root of [process.env.PLAYWRIGHT_BROWSERS_PATH, '/opt/pw-browsers', join(homedir(), '.cache/ms-playwright')]) {
    if (!root || !existsSync(root)) continue;
    for (const dir of readdirSync(root).filter((d) => /^chromium-\d+$/.test(d)).sort().reverse()) {
      for (const sub of ['chrome-linux64/chrome', 'chrome-linux/chrome']) {
        if (existsSync(join(root, dir, sub))) return join(root, dir, sub);
      }
    }
  }
  return undefined;
}

const browser = await chromium.launch({ executablePath: executablePath() });
const ctx = await browser.newContext({ viewport: { width: WIDTH, height: 844 }, deviceScaleFactor: 1, isMobile: true, hasTouch: true });
const results = {};
let failed = 0;
for (const pg of PAGES) {
  const page = await ctx.newPage();
  await page.addInitScript(
    ({ on, a }) => {
      sessionStorage.setItem('pukaar.intro', '1');
      if (on) {
        localStorage.setItem('pukaar.token', a.token);
        localStorage.setItem('pukaar.user', JSON.stringify(a.user));
      } else {
        localStorage.removeItem('pukaar.token');
        localStorage.removeItem('pukaar.user');
      }
    },
    { on: Boolean(pg.auth), a: auth },
  );
  await page.goto(`${BASE}${pg.path}`, { waitUntil: 'load' });
  await page.waitForSelector('main#main', { timeout: 20000 });
  await page.waitForLoadState('networkidle').catch(() => {});
  await page.waitForTimeout(2000);
  if (pg.prep) await pg.prep(page);
  const items = await page.evaluate(measure, MIN);
  const small = items.filter((i) => i.small && !i.inline);
  const inline = items.filter((i) => i.small && i.inline);
  results[pg.name] = { total: items.length, under: small.length, inlineExempt: inline.length, small, inline };
  failed += small.length;
  console.log(`${pg.name.padEnd(14)} ${String(items.length).padStart(4)} targets  ${String(small.length).padStart(3)} under ${MIN} px  (${inline.length} inline links exempt)`);
  for (const s of small) console.log(`   ${s.w} x ${s.h}  ${s.what}`);
  await page.close();
}
await browser.close();
if (JSON_OUT) writeFileSync(JSON_OUT, JSON.stringify(results, null, 1));
if (failed) {
  console.error(`\n${failed} tap target(s) under ${MIN} x ${MIN} px at ${WIDTH} px`);
  process.exit(1);
}
console.log(`\nAll tap targets are at least ${MIN} x ${MIN} px at ${WIDTH} px`);
