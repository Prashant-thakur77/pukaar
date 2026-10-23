import { afterEach, describe, expect, it, vi } from 'vitest';
import { both, dict as core, enumLabels, format, langReady, loadLang, scopeFor, translate } from './i18n';
import { strings } from './i18n/strings';
import { LEVEL_WORDS } from './lib/answerText';
import hiTable from 'virtual:pk-strings/hi';
import enTable from 'virtual:pk-strings/en';

// Every string: the split tables' source and the few kept in the main bundle.
const dict = { ...strings, ...core };

describe('i18n', () => {
  it('every key has non-empty Hindi and English', () => {
    for (const [key, entry] of Object.entries(dict)) {
      expect(entry.hi.trim(), `${key}.hi`).not.toBe('');
      expect(entry.en.trim(), `${key}.en`).not.toBe('');
    }
  });

  it('Hindi strings are actually Devanagari (or numbers/names)', () => {
    const latinOnly = Object.entries(dict).filter(([, e]) => {
      const text = e.hi.replace(/\{\w+\}/g, '');
      return !/[\u0900-\u097F]/.test(text) && /[a-z]{4,}/i.test(text);
    });
    // A few entries legitimately keep a Latin brand or code word only.
    expect(latinOnly.map(([k]) => k)).toEqual([]);
  });

  it('placeholders match between languages', () => {
    const vars = (s: string) => (s.match(/\{\w+\}/g) ?? []).sort().join(',');
    for (const [key, e] of Object.entries(dict)) expect(vars(e.hi), key).toBe(vars(e.en));
  });

  it('every enum label has both languages', () => {
    for (const group of Object.values(enumLabels))
      for (const [k, e] of Object.entries(group)) {
        expect(e.hi, k).toBeTruthy();
        expect(e.en, k).toBeTruthy();
      }
  });

  it('splits the strings into one table per language, nothing lost or mixed', () => {
    expect(Object.keys(hiTable).sort()).toEqual(Object.keys(strings).sort());
    expect(Object.keys(enTable).sort()).toEqual(Object.keys(strings).sort());
    for (const [k, e] of Object.entries(strings)) {
      expect(hiTable[k], k).toBe(e.hi);
      expect(enTable[k], k).toBe(e.en);
    }
    // The few strings kept in the main bundle are not also in the tables.
    for (const k of Object.keys(core)) expect(k in strings, k).toBe(false);
  });

  it('translates from the loaded tables, and both() gives the two languages', async () => {
    await loadLang('hi');
    await loadLang('en');
    expect(langReady('hi') && langReady('en')).toBe(true);
    expect(translate('hi', 'nav.status')).toBe(strings['nav.status'].hi);
    expect(translate('en', 'level.critical')).toBe('Critical');
    expect(both('village.do')).toEqual(strings['village.do']);
  });

  it('says the level words the boot painter says (lib/answerText.ts)', () => {
    for (const [lv, w] of Object.entries(LEVEL_WORDS)) expect(core[`level.${lv}` as keyof typeof core], lv).toEqual(w);
  });

  it('formats placeholders and picks Hindi-first scope for villager pages', () => {
    expect(format('{n} delivered', { n: 3 })).toBe('3 delivered');
    expect(scopeFor('/report')).toBe('villager');
    expect(scopeFor('/t/PK42')).toBe('villager');
    expect(scopeFor('/console')).toBe('staff');
  });

  it('splits pages into villager, public and staff language scopes', () => {
    for (const p of ['/report', '/t/PK42', '/t']) expect(scopeFor(p), p).toBe('villager');
    for (const p of ['/console', '/audit', '/roster', '/login', '/a/tok123']) expect(scopeFor(p), p).toBe('staff');
    for (const p of ['/', '/live', '/village/thunag', '/pilot', '/how', '/proof', '/safe/x', '/agents', '/consoles', '/auditor', '/nope'])
      expect(scopeFor(p), p).toBe('public');
  });
});

describe('default language', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.resetModules();
    localStorage.clear();
  });

  async function freshPrefs(languages: string[]) {
    vi.spyOn(navigator, 'languages', 'get').mockReturnValue(languages);
    vi.spyOn(navigator, 'language', 'get').mockReturnValue(languages[0] ?? '');
    vi.resetModules();
    return (await import('./store')).usePrefs.getState();
  }

  it('follows the browser on public pages: any hi-* locale reads Hindi, anything else English', async () => {
    const { browserLang } = await import('./store');
    vi.spyOn(navigator, 'languages', 'get').mockReturnValue(['hi-IN', 'en']);
    expect(browserLang()).toBe('hi');
    vi.spyOn(navigator, 'languages', 'get').mockReturnValue(['hi']);
    expect(browserLang()).toBe('hi');
    vi.spyOn(navigator, 'languages', 'get').mockReturnValue(['en-IN', 'hi']);
    expect(browserLang()).toBe('en');
    vi.spyOn(navigator, 'languages', 'get').mockReturnValue(['hil-PH']);
    expect(browserLang()).toBe('en');
  });

  it('starts villager pages in Hindi, public pages in the browser language and staff pages in English', async () => {
    expect((await freshPrefs(['en-US'])).lang).toEqual({ villager: 'hi', public: 'en', staff: 'en' });
    expect((await freshPrefs(['hi-IN'])).lang).toEqual({ villager: 'hi', public: 'hi', staff: 'en' });
  });

  it('remembers a choice per scope over the default', async () => {
    localStorage.setItem('pukaar.lang.villager', 'en');
    localStorage.setItem('pukaar.lang.public', 'hi');
    expect((await freshPrefs(['en-US'])).lang).toEqual({ villager: 'en', public: 'hi', staff: 'en' });
    const prefs = await freshPrefs(['en-US']);
    prefs.setLang('public', 'en');
    expect(localStorage.getItem('pukaar.lang.public')).toBe('en');
  });
});
