import { afterEach, describe, expect, it, vi } from 'vitest';
import { dict as core, enumLabels, format, langReady, loadLang, scopeFor, translate } from './i18n';
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

  it('translates from the loaded tables', async () => {
    await loadLang('hi');
    await loadLang('en');
    expect(langReady('hi') && langReady('en')).toBe(true);
    expect(translate('hi', 'nav.status')).toBe(strings['nav.status'].hi);
    expect(translate('en', 'level.critical')).toBe('Critical');
    expect(translate('en', 'village.do')).toBe(strings['village.do'].en);
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
    sessionStorage.clear();
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

  /** A new tab opened on `path`: no language for this tab yet. */
  async function firstVisit(path: string) {
    sessionStorage.clear();
    return (await import('./store')).initialLang(path);
  }

  it('starts a first visit in the entry page\'s default: Hindi for villagers, the browser on public pages, English for officers', async () => {
    await freshPrefs(['en-US']);
    expect(await firstVisit('/report')).toBe('hi');
    expect(await firstVisit('/t/PK42')).toBe('hi');
    expect(await firstVisit('/')).toBe('en');
    expect(await firstVisit('/console/inbox')).toBe('en');
    await freshPrefs(['hi-IN']);
    expect(await firstVisit('/village/thunag')).toBe('hi');
    expect(await firstVisit('/a/tok123')).toBe('en');
  });

  it('holds one language for the whole site: the store has a single value, not one per area', async () => {
    const prefs = await freshPrefs(['en-US']);
    expect(typeof prefs.lang).toBe('string');
  });

  it('keeps a visit in the language it started in, even after a reload on another page', async () => {
    sessionStorage.clear();
    window.history.replaceState(null, '', '/report');
    expect((await freshPrefs(['en-US'])).lang).toBe('hi');
    // The villager taps through to the home page and reloads it: a public page, whose default would be English.
    window.history.replaceState(null, '', '/');
    expect((await freshPrefs(['en-US'])).lang).toBe('hi');
    window.history.replaceState(null, '', '/');
  });

  it('a switch on any page sets every area, so no page flips back on the next visit', async () => {
    const prefs = await freshPrefs(['en-US']);
    prefs.setLang('hi');
    for (const scope of ['villager', 'public', 'staff']) expect(localStorage.getItem(`pukaar.lang.${scope}`), scope).toBe('hi');
    expect((await import('./store')).usePrefs.getState().lang).toBe('hi');
    for (const p of ['/report', '/', '/console', '/a/x']) expect(await firstVisit(p), p).toBe('hi');
  });

  it('remembers an older per-area choice for the page a visit starts on', async () => {
    localStorage.setItem('pukaar.lang.villager', 'en');
    localStorage.setItem('pukaar.lang.public', 'hi');
    await freshPrefs(['en-US']);
    expect(await firstVisit('/report')).toBe('en');
    expect(await firstVisit('/live')).toBe('hi');
  });
});
