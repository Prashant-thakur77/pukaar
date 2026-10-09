import { describe, expect, it } from 'vitest';
import { dict, enumLabels, format, scopeFor } from './i18n';

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

  it('formats placeholders and picks Hindi-first scope for villager pages', () => {
    expect(format('{n} delivered', { n: 3 })).toBe('3 delivered');
    expect(scopeFor('/report')).toBe('villager');
    expect(scopeFor('/t/PK42')).toBe('villager');
    expect(scopeFor('/console')).toBe('staff');
  });
});
