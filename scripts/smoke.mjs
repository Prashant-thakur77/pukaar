#!/usr/bin/env node
// Live smoke test of the deployed site and API. Read-only: it only sends GET requests, plus one
// unauthenticated POST with an empty body that the Cognito authorizer must refuse (401) before it
// reaches the code. In the browser, any page request to the API that is not GET/HEAD/OPTIONS is
// aborted and reported as a failure, so a page can never write live data during the run.
//
//   node scripts/smoke.mjs [--site URL] [--api URL] [--only /,/live]      (or: make smoke)
//
// Checks:
//   every public page loads at 390 px and 1440 px with no page errors and no sideways scroll
//   axe-core finds 0 WCAG 2.1 A/AA violations on each of them
//   the home page answers first: the status headline, the five villages as rows of at least 44 px,
//   and the report button above the fold; and the service worker registers
//   public API routes answer with the expected shape; protected routes answer 401 without a token
// Exits 1 on any failure, after printing every result.
//
// Uses Playwright and @axe-core/playwright from frontend/node_modules (never installs anything).
// Chromium: $SMOKE_CHROME, else the newest Playwright build in ~/.cache/ms-playwright, else Playwright's own.
import { existsSync, readdirSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';
import { createRequire } from 'node:module';

const require = createRequire(new URL('../frontend/package.json', import.meta.url));
const { chromium } = require('playwright');
const axeModule = require('@axe-core/playwright');
const AxeBuilder = axeModule.default ?? axeModule.AxeBuilder ?? axeModule;

const arg = (name, fallback) => {
  const i = process.argv.indexOf(`--${name}`);
  return i > 0 && process.argv[i + 1] ? process.argv[i + 1] : fallback;
};
const SITE = arg('site', process.env.SMOKE_SITE || 'https://main.d15r7ktz99l46x.amplifyapp.com').replace(/\/$/, '');
const API = arg('api', process.env.SMOKE_API || 'https://362iqe4oae.execute-api.us-east-1.amazonaws.com').replace(/\/$/, '');
const ONLY = arg('only', '').split(',').filter(Boolean);
// Any installed Playwright Chromium will do (newest first): a `playwright install` elsewhere replaces the build.
const PW_CACHE = join(homedir(), '.cache/ms-playwright');
const installedChromes = existsSync(PW_CACHE)
  ? readdirSync(PW_CACHE)
      .filter((d) => /^chromium-\d+$/.test(d))
      .sort((a, b) => Number(b.split('-')[1]) - Number(a.split('-')[1]))
      .map((d) => join(PW_CACHE, d, 'chrome-linux64/chrome'))
  : [];
const CHROME = [process.env.SMOKE_CHROME, ...installedChromes].find((p) => p && existsSync(p));
const VIEWPORTS = [
  { name: '390', width: 390, height: 844, mobile: true },
  { name: '1440', width: 1440, height: 900, mobile: false },
];
const AXE_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'];
const LEVELS = ['normal', 'watch', 'warning', 'critical'];
const COUNTER_KEYS = [
  'villages_watched', 'alerts_sent', 'phones_acknowledged', 'reports_received', 'drills_delivered',
  'replay_alerts_approved', 'forecast_checks_24h', 'gauge_readings_24h', 'gauge_readings_24h_simulated',
];

const results = [];
function record(group, name, ok, detail = '') {
  results.push({ group, name, ok, detail });
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${group.padEnd(9)} ${name}${detail ? `  (${detail})` : ''}`);
}
async function check(group, name, fn) {
  try {
    const detail = await fn();
    record(group, name, true, typeof detail === 'string' ? detail : '');
  } catch (e) {
    record(group, name, false, e instanceof Error ? e.message : String(e));
  }
}
function expect(cond, message) {
  if (!cond) throw new Error(message);
}

async function get(path, { json = true, headers = {} } = {}) {
  const res = await fetch(`${API}${path}`, { headers, signal: AbortSignal.timeout(25000) });
  const body = json ? await res.json().catch(() => null) : await res.text();
  return { res, body };
}
const isNum = (v) => typeof v === 'number' && Number.isFinite(v) && v >= 0;

// ---------------------------------------------------------------- API: public routes and shapes
async function apiChecks() {
  await check('api', 'GET /health', async () => {
    const { res, body } = await get('/health');
    expect(res.status === 200, `status ${res.status}`);
    expect(body.status === 'ok', `status field "${body.status}"`);
    expect(typeof body.mode === 'string' && typeof body.workflow === 'string', 'mode or workflow missing');
    expect(body.services && typeof body.services.dynamodb === 'string', 'services.dynamodb missing');
    return `mode ${body.mode}, ${body.workflow}`;
  });

  // The public overview is /public/overview; /overview itself is not a public route (checked below).
  await check('api', 'GET /public/overview: shape', async () => {
    const { res, body } = await get('/public/overview');
    expect(res.status === 200, `status ${res.status}`);
    expect(Array.isArray(body.villages) && body.villages.length > 0, 'no villages');
    for (const v of body.villages) expect(v.id && v.name && LEVELS.includes(v.level), `bad village ${JSON.stringify(v).slice(0, 80)}`);
    expect(Array.isArray(body.recent_alerts), 'recent_alerts missing');
    expect(typeof body.replay?.active === 'boolean', 'replay.active missing');
    expect(body.counters && typeof body.counters === 'object', 'counters missing');
    return `${body.villages.length} villages`;
  });
  await check('api', 'GET /public/overview: every counter present', async () => {
    const { body } = await get('/public/overview');
    const missing = COUNTER_KEYS.filter((k) => !isNum(body.counters?.[k]));
    expect(missing.length === 0, `missing or not a count: ${missing.join(', ')}`);
    expect(body.counters.villages_watched === body.villages.length, 'villages_watched differs from villages[]');
    expect(body.counters.gauge_readings_24h_simulated <= body.counters.gauge_readings_24h, 'more simulated than total');
    return COUNTER_KEYS.map((k) => `${k}=${body.counters[k]}`).join(' ');
  });

  await check('api', 'GET /agents', async () => {
    const { res, body } = await get('/agents');
    expect(res.status === 200, `status ${res.status}`);
    expect(Array.isArray(body.agents) && body.agents.length > 0, 'no agents');
    expect(body.counters && isNum(body.counters.agents), 'counters.agents missing');
    expect(typeof body.model?.id === 'string', 'model.id missing');
    return `${body.agents.length} agents`;
  });

  await check('api', 'GET /sensors', async () => {
    const { res, body } = await get('/sensors');
    expect(res.status === 200, `status ${res.status}`);
    expect(Array.isArray(body.villages), 'villages missing');
    expect(isNum(body.gauges) && isNum(body.readings_24h), 'gauges or readings_24h missing');
    expect(body.watch && Array.isArray(body.watch.findings), 'watch.findings missing');
    return `${body.gauges} gauges, ${body.readings_24h} readings in 24 h`;
  });

  await check('api', 'GET /villages/gohar', async () => {
    const { res, body } = await get('/villages/gohar');
    expect(res.status === 200, `status ${res.status}`);
    expect(body.village?.id === 'gohar' && LEVELS.includes(body.village.level), 'village block wrong');
    for (const k of ['readings', 'alerts', 'reports', 'past_events', 'directives']) expect(Array.isArray(body[k]), `${k} missing`);
    expect(body.nowcast !== undefined && body.soil !== undefined, 'nowcast or soil missing');
    return `level ${body.village.level}`;
  });

  await check('api', 'GET /villages/gohar/safe-places', async () => {
    const { res, body } = await get('/villages/gohar/safe-places');
    expect(res.status === 200, `status ${res.status}`);
    expect(body.village_id === 'gohar', 'village_id wrong');
    expect(Array.isArray(body.places) && Array.isArray(body.roadblocks), 'places or roadblocks missing');
    expect(body.routes && typeof body.routes === 'object', 'routes missing');
    expect(typeof body.attribution === 'string' && body.attribution.length > 0, 'attribution missing');
    return `${body.places.length} places`;
  });

  await check('api', 'GET /cap/alerts.atom', async () => {
    const { res, body } = await get('/cap/alerts.atom', { json: false });
    expect(res.status === 200, `status ${res.status}`);
    const type = res.headers.get('content-type') ?? '';
    expect(type.startsWith('application/atom+xml'), `content-type ${type}`);
    expect(body.includes('<feed xmlns="http://www.w3.org/2005/Atom">'), 'not an Atom feed');
    return `${(body.match(/<entry>/g) ?? []).length} entries`;
  });
}

// ---------------------------------------------------------------- API: protected routes refuse anonymous calls
async function authChecks() {
  // Everything not listed as public in infra/template.yaml goes through the Cognito authorizer.
  const protectedGets = ['/overview', '/stats', '/alerts', '/health/deep'];
  for (const path of protectedGets) {
    await check('auth', `GET ${path} without a token is 401`, async () => {
      const { res } = await get(path);
      expect(res.status === 401, `status ${res.status}`);
    });
  }
  // An empty body: even if the route were ever left open, validation would refuse it, so nothing is written.
  await check('auth', 'POST /villages/gohar/roadblocks without a token is 401', async () => {
    const res = await fetch(`${API}/villages/gohar/roadblocks`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{}',
      signal: AbortSignal.timeout(25000),
    });
    expect(res.status === 401, `status ${res.status}`);
  });
}

// ---------------------------------------------------------------- browser
async function trackCode() {
  // Public village pages no longer carry tracking codes (no personal data on public routes), so this
  // normally falls back to a code that does not exist; /t/<code> must still render its "not found" state.
  try {
    const { body } = await get('/public/overview');
    for (const v of body.villages ?? []) {
      const { body: d } = await get(`/villages/${v.id}`);
      const code = (d?.reports ?? []).map((r) => r.track_code).find(Boolean);
      if (code) return code;
    }
  } catch {
    /* fall through */
  }
  return 'PK0000';
}

async function settle(page) {
  // Scroll through so every reveal-on-scroll section is in its final state, then back to the top.
  const height = await page.evaluate(() => document.body.scrollHeight);
  for (let y = 0; y < height; y += 600) {
    await page.evaluate((yy) => window.scrollTo(0, yy), y);
    await page.waitForTimeout(80);
  }
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(800);
}

/** The pages that merged (redesign pass 3) still answer at their old addresses. */
async function movedChecks(page) {
  const moved = [
    ['/agents', '/how#agents'],
    ['/sensors', '/how#sensors'],
    ['/impact', '/proof'],
    ['/audit', '/console/audit'],
  ];
  for (const [from, to] of moved) {
    await check('moved', `${from} opens ${to}`, async () => {
      await page.goto(`${SITE}${from}`, { waitUntil: 'load', timeout: 45000 });
      await page.waitForFunction((want) => location.pathname + location.hash === want || location.pathname === '/login', to, { timeout: 20000 });
      const at = await page.evaluate(() => location.pathname + location.hash);
      expect(at === to || (to.startsWith('/console') && at === '/login'), `landed on ${at}`);
      return at;
    });
  }
}

async function landingChecks(page) {
  await check('landing', 'status headline loads', async () => {
    await page.waitForFunction(
      () => !document.querySelector('.home-wait') && (document.querySelector('#home-h')?.textContent ?? '').trim().length > 0,
      null,
      { timeout: 20000 },
    );
    return (await page.locator('#home-h').textContent()).trim().replace(/\s+/g, ' ');
  });
  await check('landing', 'five villages as rows, each at least 44 px tall', async () => {
    const rows = await page.locator('.home-pick a[href^="/village/"]').evaluateAll((els) =>
      els.map((e) => ({ href: e.getAttribute('href'), h: Math.round(e.getBoundingClientRect().height) })),
    );
    expect(rows.length === 5, `${rows.length} village rows`);
    const short = rows.filter((r) => r.h < 44);
    expect(short.length === 0, short.map((r) => `${r.href} ${r.h} px`).join('; '));
    return rows.map((r) => `${r.href.split('/').pop()} ${r.h}px`).join(' ');
  });
  await check('landing', 'report button above the fold', async () => {
    const box = await page.locator('.home-report').first().boundingBox();
    const vh = page.viewportSize().height;
    expect(box && box.y + box.height <= vh, box ? `bottom at ${Math.round(box.y + box.height)} px of ${vh}` : 'no report button');
    return `bottom at ${Math.round(box.y + box.height)} px of ${vh}`;
  });
  await check('landing', 'service worker registers', async () => {
    const sw = await page.evaluate(async () => {
      if (!('serviceWorker' in navigator)) return { error: 'no serviceWorker API' };
      const ready = navigator.serviceWorker.ready.then((r) => ({ scope: r.scope, active: !!r.active }));
      const timeout = new Promise((resolve) => setTimeout(() => resolve({ error: 'not ready after 20 s' }), 20000));
      return Promise.race([ready, timeout]);
    });
    expect(!sw.error, sw.error);
    expect(sw.active, 'registered but not active');
    return `scope ${sw.scope}`;
  });
}

async function browserChecks() {
  const code = await trackCode();
  const pages = ['/', '/live', '/how', '/proof', '/pilot', '/report', '/village/gohar', `/t/${code}`, '/login'].filter(
    (p) => !ONLY.length || ONLY.includes(p),
  );
  const browser = await chromium.launch({ headless: true, ...(CHROME ? { executablePath: CHROME } : {}) });
  try {
    for (const vp of VIEWPORTS) {
      const ctx = await browser.newContext({
        viewport: { width: vp.width, height: vp.height },
        isMobile: vp.mobile,
        hasTouch: vp.mobile,
        deviceScaleFactor: 1,
        colorScheme: 'light',
      });
      // Read-only guard: the pages may read the API, never write to it.
      const writes = [];
      await ctx.route(`${API}/**`, (route) => {
        const req = route.request();
        if (['GET', 'HEAD', 'OPTIONS'].includes(req.method())) return route.continue();
        writes.push(`${req.method()} ${new URL(req.url()).pathname}`);
        return route.abort();
      });
      for (const path of pages) {
        const page = await ctx.newPage();
        // Skip the once-per-session landing intro; signed out.
        await page.addInitScript(() => {
          sessionStorage.setItem('pukaar.intro', '1');
          localStorage.removeItem('pukaar.token');
          localStorage.removeItem('pukaar.user');
        });
        const errors = [];
        page.on('pageerror', (e) => errors.push(e.message.split('\n')[0]));
        const before = writes.length;
        const label = `${path} @${vp.name}`;
        try {
          await page.goto(`${SITE}${path}`, { waitUntil: 'load', timeout: 45000 });
          await page.waitForSelector('main#main', { timeout: 20000 });
          await page.waitForTimeout(1500);
          await settle(page);

          await check('page', `${label} loads without page errors`, async () => {
            expect(errors.length === 0, errors.slice(0, 3).join(' | '));
          });
          await check('page', `${label} has no sideways scroll`, async () => {
            const over = await page.evaluate(() => Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) - window.innerWidth);
            expect(over <= 0, `${over}px wider than the viewport`);
          });
          await check('axe', `${label} WCAG 2.1 A/AA`, async () => {
            const axe = await new AxeBuilder({ page }).withTags(AXE_TAGS).analyze();
            const v = axe.violations;
            expect(
              v.length === 0,
              v.map((x) => `${x.id} (${x.impact}, ${x.nodes.length}): ${x.nodes.slice(0, 2).map((n) => n.target.join(' ')).join(', ')}`).join('; '),
            );
            return `${axe.passes.length} rules passed`;
          });
          if (path === '/' && vp.name === '1440') await landingChecks(page);
          if (path === '/' && vp.name === '1440') await movedChecks(page);
        } catch (e) {
          record('page', `${label} loads`, false, e instanceof Error ? e.message.split('\n')[0] : String(e));
        }
        if (writes.length > before) record('readonly', `${label} made no writes`, false, writes.slice(before).join(', '));
        await page.close();
      }
      await ctx.close();
    }
  } finally {
    await browser.close();
  }
}

console.log(`Smoke test: site ${SITE}\n            api  ${API}\n            chromium ${CHROME ?? "Playwright's own"}\n`);
const t0 = Date.now();
await apiChecks();
await authChecks();
await browserChecks();

const failed = results.filter((r) => !r.ok);
console.log(`\n${'='.repeat(72)}`);
console.log(`${results.length - failed.length} passed, ${failed.length} failed, in ${Math.round((Date.now() - t0) / 1000)} s`);
if (failed.length) {
  console.log('\nFailures:');
  for (const f of failed) console.log(`  - [${f.group}] ${f.name}: ${f.detail}`);
}
process.exit(failed.length ? 1 : 0);
