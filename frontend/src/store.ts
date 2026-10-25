import { create } from 'zustand';
import type { Role } from './types';

/* Small zustand stores. This module must not import api.ts (api.ts imports it). */

function readLS(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeLS(key: string, value: string | null) {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch {
    /* storage blocked: keep in memory only */
  }
}

/* ---------- auth ---------- */

export interface AuthUser {
  username: string;
  role: Role;
  village_ids: string[];
}

interface AuthState {
  token: string | null;
  user: AuthUser | null;
  signIn: (token: string, user: AuthUser) => void;
  signOut: () => void;
}

function initialUser(): AuthUser | null {
  const raw = readLS('pukaar.user');
  if (!raw) return null;
  try {
    return JSON.parse(raw) as AuthUser;
  } catch {
    return null;
  }
}

export const useAuth = create<AuthState>((set) => ({
  token: readLS('pukaar.token'),
  user: initialUser(),
  signIn: (token, user) => {
    writeLS('pukaar.token', token);
    writeLS('pukaar.user', JSON.stringify(user));
    set({ token, user });
  },
  signOut: () => {
    writeLS('pukaar.token', null);
    writeLS('pukaar.user', null);
    set({ token: null, user: null });
  },
}));

/* ---------- preferences: one language for the whole site, theme ---------- */

export type Lang = 'hi' | 'en';
/** villager: /report and /t; public: the open pages; staff: the officer tools. Only the first-visit default differs. */
export type LangScope = 'villager' | 'public' | 'staff';
export type ThemePref = 'system' | 'light' | 'dark';
export const LANG_SCOPES: LangScope[] = ['villager', 'public', 'staff'];

interface PrefState {
  /** The one language every page shows. */
  lang: Lang;
  theme: ThemePref;
  /** Sets the language everywhere: every page and area, now and on the next visit. */
  setLang: (lang: Lang) => void;
  setTheme: (theme: ThemePref) => void;
}

/** The officer tools: the console, audit, roster, sign-in and the one-tap approval link. */
const STAFF_PATH = /^\/(console|audit|roster|login)(\/|$)|^\/a\//;

/**
 * Which area a page belongs to. It only picks the first-visit default: villager pages (report, tracking) start
 * in Hindi, the officer tools in English, the public pages in the browser's language.
 */
export function scopeFor(pathname: string): LangScope {
  if (pathname.startsWith('/report') || pathname.startsWith('/t/') || pathname === '/t') return 'villager';
  return STAFF_PATH.test(pathname) ? 'staff' : 'public';
}

/** The browser's first language: any Hindi locale (hi, hi-IN, hi-Latn) reads Hindi, everything else English. */
export function browserLang(): Lang {
  if (typeof navigator === 'undefined') return 'en';
  const first = navigator.languages?.[0] ?? navigator.language ?? '';
  return /^hi(-|$)/i.test(first) ? 'hi' : 'en';
}

const SCOPE_DEFAULT: Record<LangScope, () => Lang> = { villager: () => 'hi', public: browserLang, staff: () => 'en' };

/** This tab's language, so a reload on another page keeps the visit in one language (sessionStorage). */
export const VISIT_LANG_KEY = 'pukaar.lang.visit';

function readSession(key: string): string | null {
  try {
    return sessionStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeSession(key: string, value: string) {
  try {
    sessionStorage.setItem(key, value);
  } catch {
    /* storage blocked: the store still holds it for this page */
  }
}

/**
 * The language of the whole visit, decided on the page it starts on: this tab's language if it has one, else
 * the remembered choice, else that area's default (Hindi for a villager arriving from an SMS link, the browser's
 * language on the public pages, English for officers). It then holds on every page until the visitor switches,
 * so the site never changes language between pages. A choice is stored under every area's key (the pre-JS
 * painter reads them) and as this tab's language.
 */
export function initialLang(pathname = typeof location === 'undefined' ? '/' : location.pathname): Lang {
  const visit = readSession(VISIT_LANG_KEY);
  if (visit === 'hi' || visit === 'en') return visit;
  const scope = scopeFor(pathname);
  const v = readLS(`pukaar.lang.${scope}`);
  return v === 'hi' || v === 'en' ? v : SCOPE_DEFAULT[scope]();
}

function startLang(): Lang {
  const lang = initialLang();
  writeSession(VISIT_LANG_KEY, lang);
  return lang;
}

function initialTheme(): ThemePref {
  const v = readLS('pukaar.theme');
  return v === 'light' || v === 'dark' ? v : 'system';
}

/**
 * Pages a villager opens (home, a village, report, tracking, the family link, the map) are light unless the
 * visitor chose dark: light reads better outdoors on a cheap screen. Officer pages follow the system.
 * index.html's pre-paint script applies the same rule before the first frame.
 */
export const VILLAGER_THEME_PATH = /^\/(?:$|village\/|report|t\/|safe\/|live)/;

export function applyTheme(theme: ThemePref, pathname = typeof location === 'undefined' ? '/' : location.pathname) {
  if (typeof document === 'undefined') return;
  const root = document.documentElement;
  const resolved = theme === 'system' && VILLAGER_THEME_PATH.test(pathname) ? 'light' : theme;
  if (resolved === 'system') root.removeAttribute('data-theme');
  else root.setAttribute('data-theme', resolved);
}

export const usePrefs = create<PrefState>((set) => ({
  lang: startLang(),
  theme: initialTheme(),
  setLang: (lang) => {
    for (const scope of LANG_SCOPES) writeLS(`pukaar.lang.${scope}`, lang);
    writeSession(VISIT_LANG_KEY, lang);
    set({ lang });
  },
  setTheme: (theme) => {
    writeLS('pukaar.theme', theme === 'system' ? null : theme);
    applyTheme(theme);
    set({ theme });
  },
}));

/* ---------- network, offline queue, sample data ---------- */

interface NetState {
  online: boolean;
  queued: number;
  sample: boolean;
  /** Offline-queue id -> tracking code, for reports the queue has since sent. */
  flushed: Record<number, string>;
  setOnline: (online: boolean) => void;
  setQueued: (n: number) => void;
  markFlushed: (id: number, code: string) => void;
  markSample: () => void;
}

export const useNet = create<NetState>((set, get) => ({
  online: typeof navigator === 'undefined' ? true : navigator.onLine,
  queued: 0,
  sample: false,
  flushed: {},
  setOnline: (online) => set({ online }),
  setQueued: (queued) => set({ queued }),
  markFlushed: (id, code) => set({ flushed: { ...get().flushed, [id]: code } }),
  markSample: () => {
    if (!get().sample) set({ sample: true });
  },
}));

/* ---------- tracking codes the villager has received on this phone ---------- */

export interface MyReport {
  code: string;
  at: number;
}

export function rememberTrackCode(code: string) {
  const list = myTrackCodes().filter((r) => r.code !== code);
  list.unshift({ code, at: Date.now() });
  writeLS('pukaar.myReports', JSON.stringify(list.slice(0, 10)));
}

export function myTrackCodes(): MyReport[] {
  const raw = readLS('pukaar.myReports');
  if (!raw) return [];
  try {
    const v = JSON.parse(raw) as MyReport[];
    return Array.isArray(v) ? v : [];
  } catch {
    return [];
  }
}

export { readLS, writeLS };
