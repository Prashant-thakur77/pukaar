import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { transform } from 'lightningcss';
import { describe, expect, it } from 'vitest';

// Every stylesheet must parse the way the production build parses it: a merge that leaves a marker or loses a brace
// passes type-checks and unit tests but fails `vite build`.
const dir = join(__dirname);
const sheets = readdirSync(dir).filter((f) => f.endsWith('.css'));

describe('stylesheets', () => {
  it.each(sheets)('%s parses', (name) => {
    const code = readFileSync(join(dir, name));
    expect(() => transform({ filename: name, code, minify: true })).not.toThrow();
    expect(code.toString()).not.toMatch(/^(<<<<<<<|=======|>>>>>>>)/m);
  });
});
