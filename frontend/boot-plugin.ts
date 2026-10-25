// The answer before the app (redesign spec 4.2, 7). In a production build index.html carries:
//   - the boot painter (src/boot/boot.ts) as one inline script: it asks the API for the answer and paints it
//     with the page's own markup and words before React arrives;
//   - the critical CSS as one inline <style>: every rule of the shipped stylesheets that applies to what the
//     painter can draw. The painter runs here in jsdom over sample answers at every level and in both languages,
//     and a rule is kept when one of its selectors matches (state pseudo-classes ignored, so :hover and focus
//     come too). It is cut from the real build in cascade order and sits in a cascade layer below the real
//     stylesheets, so the hand-over to React changes nothing on screen;
//   - no render-blocking stylesheet and no module script: Vite's tags become <script type="application/json"
//     id="pk-assets">, and the painter loads them once the answer is painted (src/boot/assets.ts). A deferred
//     external pk-fallback-*.js starts the app the usual way if the inline painter never ran.
// The API base reaches the painter in <meta name="pk-api">, so the painter's hash is the same on every stack.
// dist/csp-inline.json lists the hashes the Content-Security-Policy must allow; scripts/csp-sync.mjs writes
// them into infra/template.yaml, and deploy_web.sh refuses to publish a build the template does not allow.
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import postcss, { type AtRule, type ChildNode, type Container, type Root, type Rule } from 'postcss';
import { transform as lightningTransform } from 'lightningcss';
import { loadEnv, type Plugin, type ResolvedConfig } from 'vite';
import type { OutputAsset, OutputBundle, OutputChunk } from 'rolldown';
import type { PkAssets } from './src/boot/pk-assets';

const BOOT_ENTRY = fileURLToPath(new URL('./src/boot/boot.ts', import.meta.url));
const FALLBACK_ENTRY = fileURLToPath(new URL('./src/boot/fallback.ts', import.meta.url));
/** The painter's budget, gzipped: the village answer, and on / the hero with the status under it. */
const BOOT_MAX_GZ = 10 * 1024;
/** The critical CSS budget, gzipped (spec 7: HTML + CSS about 14 kB). */
const CRITICAL_MAX_GZ = 12 * 1024;
/** The pages the painter draws: their CSS joins the entry's in the critical cut. */
const ANSWER_PAGES = { village: /\/src\/pages\/VillagePage\.tsx$/, home: /\/src\/pages\/Landing\.tsx$/ };

export const sha256 = (s: string) => `'sha256-${createHash('sha256').update(s, 'utf8').digest('base64')}'`;

/** One small script, bundled on its own as a minified IIFE. */
async function bundle(input: string): Promise<string> {
  const { rolldown } = await import('rolldown');
  const b = await rolldown({ input, platform: 'browser', logLevel: 'silent' });
  try {
    const { output } = await b.generate({ format: 'iife', minify: true });
    return output[0].code.trim();
  } finally {
    await b.close();
  }
}

const escAttr = (s: string) => s.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');

/** The <head> additions: the API base, the app's files (build only), the critical CSS (build only), the painter. */
function headTags(api: string, boot: string, critical: string | null, assets: PkAssets | null): string {
  return [
    `<meta name="pk-api" content="${escAttr(api)}" />`,
    // A data block: never executed, so the CSP does not apply to it. "<" is escaped so it cannot close the tag.
    assets ? `<script type="application/json" id="pk-assets">${JSON.stringify(assets).replace(/</g, '\\u003c')}</script>` : '',
    critical ? `<style>${critical}</style>` : '',
    `<script>${boot}</script>`,
  ]
    .filter(Boolean)
    .join('\n    ');
}

/** Puts the tags right after the theme script, before any stylesheet or module script. */
function inject(html: string, tags: string): string {
  const marker = '<!-- pk:boot -->';
  if (!html.includes(marker)) throw new Error('index.html has no <!-- pk:boot --> marker for the boot painter');
  return html.replace(marker, tags);
}

/* ---------- the critical cut ---------- */

interface Variant {
  url: string;
  storage: Record<string, string>;
  /** The API's answer for the painter's request, or null for no network. */
  answer: unknown;
}

const ACT = [
  { hi: 'क', en: 'a' },
  { hi: 'ख', en: 'b' },
  { hi: 'ग', en: 'c' },
];
const PLACE = { id: 'p', name: 'Hospital', name_hi: 'अस्पताल', kind_en: 'Hospital', kind_hi: 'अस्पताल', walk_min: 25, route_length_m: 1200, headroom_m: 17, status: 'OPEN', route_blocked: true };
const LEVELS = ['normal', 'watch', 'warning', 'critical'] as const;

function variants(): Variant[] {
  const out: Variant[] = [];
  const recent = new Date(Date.now() - 4 * 60_000).toISOString();
  const old = new Date(Date.now() - 3 * 3600_000).toISOString();
  for (const lang of ['hi', 'en']) {
    const storage = { 'pukaar.lang.public': lang };
    for (const level of LEVELS) {
      for (const [known, place, at] of [
        [true, PLACE, recent],
        [false, null, old],
      ] as const) {
        out.push({
          url: 'https://pukaar.local/village/gohar',
          storage: { ...storage, ...(level === 'critical' ? { 'pukaar.token': 'x' } : {}) },
          answer: { id: 'gohar', name: 'Gohar', name_hi: 'गोहर', district: 'Mandi', level, level_known: known, checked_at: at, means: ACT[0], actions: ACT, safe_place: place },
        });
      }
    }
    // The phone's copy with no network, and nothing at all.
    out.push({
      url: 'https://pukaar.local/village/gohar',
      storage: { ...storage, 'pukaar.now.gohar': JSON.stringify({ now: { id: 'gohar', name: 'G', name_hi: 'ग', district: 'Mandi', level: 'watch', level_known: true, checked_at: recent, means: ACT[0], actions: ACT, safe_place: null }, fetchedAt: 1 }) },
      answer: null,
    });
    out.push({ url: 'https://pukaar.local/village/gohar', storage, answer: null });
    const v = (id: string, level: string, data_status = 'ok') => ({ id, name: id, name_hi: id, level, data_status, data_ok_at: recent });
    for (const villages of [
      [v('gohar', 'normal'), v('thunag', 'normal')],
      [v('gohar', 'critical'), v('thunag', 'watch'), v('pandoh', 'warning'), v('sujanpur', 'normal'), v('janjehli', 'normal', 'stale')],
      [v('gohar', 'normal', 'unavailable'), v('thunag', 'normal')],
    ]) {
      out.push({ url: 'https://pukaar.local/', storage, answer: { villages } });
    }
    out.push({ url: 'https://pukaar.local/', storage, answer: null });
    out.push({ url: 'https://pukaar.local/report', storage, answer: null });
  }
  return out;
}

/** Runs the painter in jsdom for each variant and returns what it drew (the #pk-boot subtrees). */
async function paintedMarkup(boot: string, shell: string): Promise<string[]> {
  // @ts-expect-error jsdom ships no types here; only JSDOM is used.
  const { JSDOM } = await import('jsdom');
  const out: string[] = [];
  for (const v of variants()) {
    const dom = new JSDOM(shell, { url: v.url, runScripts: 'outside-only', pretendToBeVisual: true });
    const w = dom.window;
    for (const [k, val] of Object.entries(v.storage)) w.localStorage.setItem(k, val);
    w.fetch = () => (v.answer == null ? Promise.reject(new TypeError('offline')) : Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(v.answer) }));
    // The cut paints what any width can show (the home page's valley is drawn on desks only).
    w.__pkCut = true;
    w.eval(boot);
    await new Promise((r) => setTimeout(r, 10));
    const el = w.document.getElementById('pk-boot');
    if (!el || !el.querySelector('header')) throw new Error(`the boot painter drew nothing for ${v.url}`);
    out.push(el.outerHTML);
    w.close();
  }
  return out;
}

/** The little of the DOM this file asks jsdom for (tsconfig.node has no DOM library). */
interface Doc {
  querySelector(s: string): unknown;
  querySelectorAll(s: string): Iterable<{ classList: Iterable<string>; id: string }>;
  documentElement: { matches(s: string): boolean };
}

const STATE_PSEUDO = /::?(hover|focus-visible|focus-within|focus|active|visited|target|checked|disabled|enabled|placeholder-shown|before|after|placeholder|marker|selection|first-letter|first-line|-webkit-[a-z-]+|-moz-[a-z-]+)(\([^)]*\))?/g;

/** Every class and id in the painted markup: a selector naming any other cannot match, so jsdom is not asked. */
const known = { classes: new Set<string>(), ids: new Set<string>() };

function selectorUsed(sel: string, docs: Doc[]): boolean {
  const s = sel.replace(STATE_PSEUDO, '').trim() || '*';
  // Only the classes and ids outside :not(...) must be present.
  const positive = s.replace(/:not\((?:[^()]|\([^()]*\))*\)/g, '');
  const alternatives = /:(is|where|has|matches)\(/.test(positive);
  if (!alternatives) for (const m of positive.matchAll(/\.(-?[_a-zA-Z][\w-]*)/g)) if (!known.classes.has(m[1])) return false;
  if (!alternatives) for (const m of positive.matchAll(/#(-?[_a-zA-Z][\w-]*)/g)) if (!known.ids.has(m[1])) return false;
  for (const d of docs) {
    try {
      if (d.querySelector(s.replace(/^(html|:root)\b/, ':root')) || d.documentElement.matches(s)) return true;
    } catch {
      return true; // a selector jsdom cannot read: keep the rule
    }
  }
  return false;
}

/** Keeps the rules (and the at-rules around them) that the painted markup uses; drops the rest. */
function prune(container: Container, docs: Doc[]): void {
  container.each((node: ChildNode) => {
    if (node.type === 'rule') {
      const r = node as Rule;
      if (r.parent && (r.parent as AtRule).name === 'keyframes') return;
      if (!r.selectors.some((s) => selectorUsed(s, docs))) r.remove();
    } else if (node.type === 'atrule') {
      const a = node as AtRule;
      if (a.name === 'font-face' || a.name === 'keyframes' || a.name === 'property' || a.name === 'charset') return;
      if (a.nodes) {
        prune(a, docs);
        if (!a.nodes.length) a.remove();
      }
    } else if (node.type === 'comment') node.remove();
  });
}

/** Drops @keyframes no kept rule animates, and font faces of families no kept rule names. */
function dropUnused(root: Root): void {
  const used = new Set<string>();
  root.walkDecls(/^animation(-name)?$/, (d) => d.value.split(/[\s,]+/).forEach((w) => used.add(w)));
  root.walkAtRules('keyframes', (a) => {
    if (!used.has(a.params.trim())) a.remove();
  });
}

async function criticalCss(css: string, boot: string, shell: string): Promise<string> {
  // @ts-expect-error jsdom ships no types here
  const { JSDOM } = await import('jsdom');
  const markup = [...new Set(await paintedMarkup(boot, shell))];
  const docs: Doc[] = [];
  // Every root state the stylesheet tells apart: theme chosen light, dark, or left to the system; the story serif.
  for (const attrs of ['lang="hi" data-theme="light"', 'lang="en" data-theme="dark"', 'lang="hi"', 'lang="hi" data-story=""']) {
    docs.push(new JSDOM(`<!doctype html><html ${attrs}><head></head><body>${markup.join('')}<div id="root"></div></body></html>`).window.document);
  }
  known.classes.clear();
  known.ids.clear();
  for (const el of docs[0].querySelectorAll('*')) {
    for (const c of el.classList) known.classes.add(c);
    if (el.id) known.ids.add(el.id);
  }
  const root = postcss.parse(css);
  prune(root, docs);
  dropUnused(root);
  // The rules go in a cascade layer, under every unlayered rule: once the full stylesheets arrive they win
  // outright, so the inline copy can never reorder the real cascade. Font faces and keyframes stay outside.
  const layer = postcss.atRule({ name: 'layer', params: 'boot' });
  const out = postcss.root();
  root.each((n) => {
    const keep = n.type === 'atrule' && ['font-face', 'keyframes', 'property', 'charset'].includes((n as AtRule).name);
    (keep ? out : layer).append(n.clone());
  });
  out.append(layer);
  const { code } = lightningTransform({ filename: 'critical.css', code: Buffer.from(out.toString()), minify: true });
  return code.toString();
}

/** The CSS files a chunk needs, its static imports' first, in the order the browser applies them. */
function cssOf(bundle: OutputBundle, chunk: OutputChunk, seen = new Set<string>()): string[] {
  const out: string[] = [];
  for (const imp of chunk.imports) {
    const c = bundle[imp];
    if (c && c.type === 'chunk' && !seen.has(imp)) {
      seen.add(imp);
      out.push(...cssOf(bundle, c, seen));
    }
  }
  const meta = (chunk as OutputChunk & { viteMetadata?: { importedCss: Set<string> } }).viteMetadata;
  for (const f of meta?.importedCss ?? []) if (!out.includes(f)) out.push(f);
  return out;
}

const gz = async (s: string) => (await import('node:zlib')).gzipSync(s).length;
const short = (s: string) => createHash('sha256').update(s).digest('hex').slice(0, 10);

export function bootPlugin(): Plugin {
  let config: ResolvedConfig;
  let api = 'http://localhost:8000';
  let boot = '';
  let fallback = '';
  return {
    name: 'pukaar-boot',
    enforce: 'post',
    configResolved(c) {
      config = c;
      const env = loadEnv(c.mode, c.envDir || c.root, 'VITE_');
      api = (process.env.VITE_API_BASE ?? env.VITE_API_BASE ?? 'http://localhost:8000').replace(/\/$/, '');
    },
    async buildStart() {
      boot = await bundle(BOOT_ENTRY);
      const size = await gz(boot);
      if (config.command === 'build' && size > BOOT_MAX_GZ) this.error(`boot painter is ${size} B gzipped; the budget is ${BOOT_MAX_GZ}`);
      if (config.command === 'build') fallback = await bundle(FALLBACK_ENTRY);
    },
    transformIndexHtml: {
      order: 'post',
      async handler(html, ctx) {
        // Dev: the painter only (Vite's module script stays, and the styles arrive through the modules).
        if (ctx.bundle) return html;
        if (!boot) boot = await bundle(BOOT_ENTRY);
        return inject(html, headTags(api, boot, null, null));
      },
    },
    async generateBundle(_opts, out) {
      const html = out['index.html'] as OutputAsset | undefined;
      if (!html) return;
      const chunks = Object.values(out).filter((c): c is OutputChunk => c.type === 'chunk');
      const entry = chunks.find((c) => c.isEntry);
      if (!entry) return this.error('no entry chunk');
      const pageCss = (re: RegExp) => {
        const page = chunks.find((c) => Boolean(c.facadeModuleId && re.test(c.facadeModuleId)));
        if (!page) this.error(`no chunk for ${re}`);
        return cssOf(out, page);
      };
      const globalCss = cssOf(out, entry);
      const villageCss = pageCss(ANSWER_PAGES.village).filter((f) => !globalCss.includes(f));
      const homeCss = pageCss(ANSWER_PAGES.home).filter((f) => !globalCss.includes(f));
      const cut = [...globalCss, ...villageCss, ...homeCss.filter((f) => !villageCss.includes(f))];
      const css = cut.map((f) => String((out[f] as OutputAsset).source)).join('\n');

      let page = String(html.source);
      // Vite's tags for the app's code and styles leave the page; the painter loads them (boot/assets.ts).
      const tag = (re: RegExp) => [...page.matchAll(re)].map((m) => m[1]);
      const js = tag(/<script type="module" crossorigin src="([^"]+)"><\/script>/g);
      const pre = tag(/<link rel="modulepreload" crossorigin href="([^"]+)">/g);
      const sheets = tag(/<link rel="stylesheet" crossorigin href="([^"]+)">/g);
      if (js.length !== 1) this.error(`expected one module script in index.html, found ${js.length}`);
      page = page
        .replace(/\s*<script type="module" crossorigin src="[^"]+"><\/script>/g, '')
        .replace(/\s*<link rel="modulepreload" crossorigin href="[^"]+">/g, '')
        .replace(/\s*<link rel="stylesheet" crossorigin href="[^"]+">/g, '');
      const abs = (f: string) => `${config.base}${f}`;
      const assets: PkAssets = { js: js[0], pre, css: sheets, answer: { village: villageCss.map(abs), home: homeCss.map(abs) } };

      // The shell the painter paints into, for the critical cut: the page's own markup.
      const shell = page.replace('<!-- pk:boot -->', '');
      const critical = await criticalCss(css, boot, shell);
      const size = await gz(critical);
      if (size > CRITICAL_MAX_GZ) this.error(`critical CSS is ${size} B gzipped; the budget is ${CRITICAL_MAX_GZ}`);

      // The safety net, an ordinary deferred file: it starts the app if the inline painter never ran.
      const fallbackName = `assets/pk-fallback-${short(fallback)}.js`;
      this.emitFile({ type: 'asset', fileName: fallbackName, source: fallback });
      page = inject(page, headTags(api, boot, critical, assets));
      page = page.replace('</head>', `  <script defer src="${abs(fallbackName)}"></script>\n  </head>`);
      html.source = page;

      const scripts = [...page.matchAll(/<script>([\s\S]*?)<\/script>/g)].map((m) => sha256(m[1]));
      const styles = [...page.matchAll(/<style>([\s\S]*?)<\/style>/g)].map((m) => sha256(m[1]));
      this.emitFile({ type: 'asset', fileName: 'csp-inline.json', source: `${JSON.stringify({ script: scripts, style: styles }, null, 2)}\n` });
      config.logger.info(`pukaar-boot: painter ${await gz(boot)} B, critical CSS ${size} B gzipped (cut from ${cut.length} stylesheets)`);
    },
  };
}
