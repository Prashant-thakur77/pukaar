// Design-token lint: every stylesheet except src/tokens.css uses the tokens, never raw values.
//   node scripts/check-tokens.mjs             lint src/**/*.css (exit 1 on any finding)
//   node scripts/check-tokens.mjs --contrast  also print and check the WCAG contrast of the token pairs
// Rules (docs: the redesign spec, section 3):
//   - no raw colour (hex, rgb(), hsl(), named) anywhere, custom properties included;
//   - font-size is a --t-* token (or inherit / 1em / 100%);
//   - no gradient except in a mask; no background-clip: text; no italic; letter-spacing only var(--track-label);
//   - box-shadow is none, var(--elev-overlay) or an unblurred ring or bar (a border drawn with a shadow);
//   - transition and animation times are --dur-* tokens; radii are --r-1, --r-2, --r-pill, 0 or 50%.
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { dirname, join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';
import postcss from 'postcss';

// Under vitest import.meta.url may be a plain path rather than a file: URL.
const HERE = import.meta.url.startsWith('file:') ? dirname(fileURLToPath(import.meta.url)) : dirname(import.meta.url.replace(/^\/@fs/, ''));
const ROOT = join(HERE, '..');
const SRC = join(ROOT, 'src');
const TOKENS = join(SRC, 'tokens.css');
// The water skin holds its own palette, gradients and blurs, like tokens.css.
const WATER = join(SRC, 'water.css');

const NAMED = /\b(white|black|red|green|blue|yellow|orange|gray|grey|silver|navy|teal|purple|crimson|gold|maroon)\b/i;
const RAW_COLOUR = /#[0-9a-f]{3,8}\b|\b(rgba?|hsla?|hwb|lab|lch|oklab|oklch)\(/i;

function walk(dir) {
  return readdirSync(dir).flatMap((f) => {
    const p = join(dir, f);
    return statSync(p).isDirectory() ? walk(p) : p.endsWith('.css') ? [p] : [];
  });
}

/** The findings for one stylesheet's source. Exported for tests. */
export function lintCss(code, file = 'x.css') {
  const out = [];
  const root = postcss.parse(code, { from: file });
  const bad = (d, msg) => out.push(`${file}:${d.source?.start?.line ?? 0}  ${d.prop}: ${d.value}  (${msg})`);
  root.walkDecls((d) => {
    const prop = d.prop.toLowerCase();
    const v = d.value;
    const inMask = /^(-webkit-)?mask/.test(prop);
    const noVars = v.replace(/var\([^()]*\)/g, '');
    if (RAW_COLOUR.test(noVars) || (NAMED.test(noVars) && !/^(font|grid|animation|transition|will-change|content|counter)/.test(prop) && !prop.startsWith('--'))) {
      bad(d, 'raw colour: use a colour token');
    }
    if (/gradient\(/.test(v) && !inMask) bad(d, 'gradient: flat colours only');
    if (prop === 'font-size' && !/^(var\(--t-[a-z0-9-]+\)|inherit|1em|100%)$/.test(v.trim())) bad(d, 'font size: use a --t-* token');
    if (/^(-webkit-)?background-clip$/.test(prop) && /text/.test(v)) bad(d, 'background-clip: text clips Devanagari matras');
    if (prop === '-webkit-text-fill-color') bad(d, 'text fill: no clipped text');
    if (prop === 'font-style' && /italic|oblique/.test(v)) bad(d, 'italic: emphasis is weight or colour');
    if (prop === 'letter-spacing' && !/^(0|normal|var\(--track-label\))$/.test(v.trim())) bad(d, 'letter-spacing: var(--track-label) on Latin labels only');
    if (prop === 'box-shadow' && !/^(none|var\(--elev-overlay\))$/.test(v.trim())) {
      const layers = v.split(/,(?![^(]*\))/);
      const blurred = layers.some((l) => {
        const nums = l.replace(/var\([^)]*\)|color-mix\([^)]*\)\)?|inset/g, '').trim().split(/\s+/).filter(Boolean);
        return nums.length >= 3 && parseFloat(nums[2]) > 0;
      });
      if (blurred) bad(d, 'shadow: none on content; var(--elev-overlay) on overlays');
    }
    if (/^(transition|transition-duration|transition-delay|animation|animation-duration|animation-delay)$/.test(prop) && /(?<![\w-])\d*\.?\d+(ms|s)\b/.test(v.replace(/var\([^)]*\)/g, '')) && !/^0m?s$/.test(v.trim())) {
      bad(d, 'duration: use a --dur-* token');
    }
    if (/^border(-[a-z]+)*-radius$/.test(prop) && v.split(/\s+/).some((p) => !/^(var\(--r-(1|2|pill)\)|0|50%|inherit|\/)$/.test(p))) {
      bad(d, 'radius: --r-1, --r-2 or --r-pill');
    }
  });
  return out;
}

/* ---------- contrast of the token pairs ---------- */
function rgb(hex) {
  const h = hex.replace('#', '');
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255);
}
function lum(hex) {
  const [r, g, b] = rgb(hex).map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
export function contrast(a, b) {
  const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
}

/** The light (`:root`) and dark (`[data-theme='dark']`) values of every plain-hex token in tokens.css. */
export function tokenValues(code = readFileSync(TOKENS, 'utf8')) {
  const block = (sel) => {
    const i = code.indexOf(sel);
    const j = code.indexOf('}', i);
    return Object.fromEntries([...code.slice(i, j).matchAll(/--([a-z0-9-]+):\s*(#[0-9a-f]{6})\b/gi)].map((m) => [m[1], m[2].toLowerCase()]));
  };
  const light = block(':root {');
  return { light, dark: { ...light, ...block(":root[data-theme='dark'] {") } };
}

/** The water skin's two palettes, over the token values they do not set (the level colours). */
export function waterValues(code = readFileSync(WATER, 'utf8')) {
  const base = tokenValues();
  const block = (sel) => {
    const i = code.indexOf(sel);
    const j = code.indexOf('}', i);
    return Object.fromEntries([...code.slice(i, j).matchAll(/--([a-z0-9-]+):\s*(#[0-9a-f]{6})\b/gi)].map((m) => [m[1], m[2].toLowerCase()]));
  };
  return {
    'water-light': { ...base.light, ...block('/* ---------- day:') },
    'water-dark': { ...base.dark, ...block('/* ---------- night:') },
  };
}

// [foreground, background, minimum]: 4.5 for text, 3 for large text and non-text (lines, bars, outlines).
const PAIRS = [
  ['ink', 'bg', 4.5], ['ink', 'surface', 4.5], ['ink-2', 'bg', 4.5], ['ink-3', 'bg', 4.5], ['ink-3', 'surface', 4.5], ['ink-3', 'surface-2', 4.5],
  ['accent-text', 'bg', 4.5], ['accent-text', 'surface', 4.5], ['on-accent', 'accent', 4.5], ['line-strong', 'bg', 3], ['focus-ring', 'focus', 4.5],
  ...['normal', 'watch', 'warning', 'critical', 'nodata'].flatMap((l) => [[`lv-${l}-on`, `lv-${l}-fill`, 4.5], [`lv-${l}-ink`, 'bg', 4.5], [`lv-${l}-ink`, 'surface', 4.5]]),
  ...['normal', 'watch', 'warning', 'critical'].map((l) => [`lv-${l}-line`, 'bg', 3]),
];
export function contrastReport(values = tokenValues()) {
  const rows = [];
  for (const [theme, t] of Object.entries(values)) {
    for (const [fg, bg, min] of PAIRS) {
      if (!t[fg] || !t[bg]) continue;
      const r = contrast(t[fg], t[bg]);
      rows.push({ theme, fg, bg, ratio: Math.round(r * 100) / 100, min, ok: r >= min });
    }
  }
  return rows;
}

const isMain = Boolean(process.argv[1]) && import.meta.url.startsWith('file:') && fileURLToPath(import.meta.url) === process.argv[1];
if (isMain) {
  const files = walk(SRC).filter((f) => f !== TOKENS && f !== WATER);
  const findings = files.flatMap((f) => lintCss(readFileSync(f, 'utf8'), relative(ROOT, f)));
  let failed = findings.length > 0;
  for (const f of findings) console.log(f);
  if (process.argv.includes('--contrast')) {
    for (const r of [...contrastReport(), ...contrastReport(waterValues())]) {
      console.log(`${r.ok ? 'ok  ' : 'FAIL'} ${r.theme.padEnd(5)} ${r.fg.padEnd(16)} on ${r.bg.padEnd(16)} ${r.ratio.toFixed(2)} (min ${r.min})`);
      if (!r.ok) failed = true;
    }
  }
  console.log(failed ? `check:tokens: ${findings.length} finding(s)` : `check:tokens: ${files.length} stylesheets use the tokens`);
  process.exit(failed ? 1 : 0);
}
