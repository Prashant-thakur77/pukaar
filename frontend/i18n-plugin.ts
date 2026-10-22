// One table per language (redesign spec 7: "i18n split by language"). src/i18n/strings.ts holds every UI
// string with its Hindi and English side by side; this plugin serves it as two modules, virtual:pk-strings/hi
// and virtual:pk-strings/en, each a plain { key: text } object, so the build emits one chunk per language and
// a phone downloads only the one it shows (src/i18n.ts, loadLang). Used by vite.config.ts and vitest.config.ts.
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import type { Plugin } from 'vite';

const STRINGS = fileURLToPath(new URL('./src/i18n/strings.ts', import.meta.url));
const PREFIX = 'virtual:pk-strings/';
const LANGS = ['hi', 'en'] as const;

type Strings = Record<string, { hi: string; en: string }>;

/** Evaluates strings.ts (plain literals only) and returns its `strings` object. */
export async function readStrings(file = STRINGS): Promise<Strings> {
  const ts = await import('typescript');
  const { outputText } = ts.transpileModule(readFileSync(file, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
  });
  const mod = (await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`)) as { strings?: Strings };
  if (!mod.strings) throw new Error(`${file} does not export \`strings\``);
  return mod.strings;
}

export function i18nStringsPlugin(): Plugin {
  return {
    name: 'pukaar-i18n-strings',
    resolveId(id) {
      if (id.startsWith(PREFIX) && (LANGS as readonly string[]).includes(id.slice(PREFIX.length))) return `\0${id}`;
      return null;
    },
    async load(id) {
      if (!id.startsWith(`\0${PREFIX}`)) return null;
      const lang = id.slice(PREFIX.length + 1) as (typeof LANGS)[number];
      this.addWatchFile(STRINGS);
      const strings = await readStrings();
      const table: Record<string, string> = {};
      for (const [k, v] of Object.entries(strings)) table[k] = v[lang];
      return `export default ${JSON.stringify(table)};`;
    },
  };
}
