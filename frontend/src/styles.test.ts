import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { transform } from 'lightningcss';
import { describe, expect, it } from 'vitest';

// Every stylesheet must parse the way the production build parses it: a merge that leaves a marker or loses a brace
// passes type-checks and unit tests but fails `vite build`.
const dir = join(__dirname);
const walk = (d: string): string[] =>
  readdirSync(d).flatMap((f) => {
    const p = join(d, f);
    return statSync(p).isDirectory() ? walk(p) : p.endsWith('.css') ? [p] : [];
  });
const sheets = walk(dir).map((p) => relative(dir, p));

describe('stylesheets', () => {
  it.each(sheets)('%s parses', (name) => {
    const code = readFileSync(join(dir, name));
    expect(() => transform({ filename: name, code, minify: true })).not.toThrow();
    expect(code.toString()).not.toMatch(/^(<<<<<<<|=======|>>>>>>>)/m);
  });
});

// The token lint (scripts/check-tokens.mjs): raw values stay in tokens.css, and Hindi is never clipped or slanted.
describe('design tokens', () => {
  const load = async () => {
    const path = join(__dirname, '..', 'scripts', 'check-tokens.mjs');
    return (await import(/* @vite-ignore */ path)) as {
      lintCss: (code: string, file?: string) => string[];
      contrastReport: () => { theme: string; fg: string; bg: string; ratio: number; ok: boolean }[];
    };
  };

  it('every stylesheet but tokens.css passes the lint', async () => {
    const { lintCss } = await load();
    const findings = sheets.filter((f) => f !== 'tokens.css' && f !== 'water.css').flatMap((f) => lintCss(readFileSync(join(dir, f), 'utf8'), f));
    expect(findings).toEqual([]);
  });

  it('flags raw colours, sizes, gradients, clipped text, italics and tracking', async () => {
    const { lintCss } = await load();
    const bad = `.a { color: #fff; font-size: 13px; background: linear-gradient(red, blue); }
      .b { -webkit-background-clip: text; background-clip: text; font-style: italic; letter-spacing: 0.2em; }
      .c { box-shadow: 0 10px 30px var(--ink); transition: color 300ms; border-radius: 14px; }`;
    const msgs = lintCss(bad).join('\n');
    for (const want of ['raw colour', 'font size', 'gradient', 'background-clip', 'italic', 'letter-spacing', 'shadow', 'duration', 'radius']) {
      expect(msgs).toContain(want);
    }
    expect(lintCss('.ok { color: var(--ink); font-size: var(--t-body); box-shadow: inset 4px 0 0 var(--lv); }')).toEqual([]);
  });

  it('every text and level pair in the tokens meets its contrast', async () => {
    const { contrastReport } = await load();
    expect(contrastReport().filter((r) => !r.ok)).toEqual([]);
  });
});
