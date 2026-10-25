import type { Lang } from '../store';

/**
 * The pilot villages' names in Devanagari (data/villages.json), for data that carries only the English name
 * (the back-test files, the story data). Live API data has its own name_hi.
 */
export const VILLAGE_HI: Record<string, string> = {
  thunag: 'थुनाग',
  janjehli: 'जंजैहली',
  gohar: 'गोहर',
  pandoh: 'पंडोह',
  sujanpur: 'सुजानपुर',
  karsog: 'करसोग',
};

/** A village's name in the page's language: its Devanagari name on a Hindi page when it is known. */
export function villageNameIn(id: string, name: string, lang: Lang): string {
  return lang === 'hi' ? (VILLAGE_HI[id] ?? VILLAGE_HI[name.toLowerCase()] ?? name) : name;
}
