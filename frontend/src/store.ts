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

/* ---------- preferences: language per area, theme ---------- */

export type Lang = 'hi' | 'en';
export type LangScope = 'villager' | 'staff';
export type ThemePref = 'system' | 'light' | 'dark';

interface PrefState {
  lang: Record<LangScope, Lang>;
  theme: ThemePref;
  setLang: (scope: LangScope, lang: Lang) => void;
  setTheme: (theme: ThemePref) => void;
}

function initialLang(scope: LangScope, fallback: Lang): Lang {
  const v = readLS(`pukaar.lang.${scope}`);
  return v === 'hi' || v === 'en' ? v : fallback;
}

function initialTheme(): ThemePref {
  const v = readLS('pukaar.theme');
  return v === 'light' || v === 'dark' ? v : 'system';
}

export function applyTheme(theme: ThemePref) {
  if (typeof document === 'undefined') return;
  const root = document.documentElement;
  if (theme === 'system') root.removeAttribute('data-theme');
  else root.setAttribute('data-theme', theme);
}

export const usePrefs = create<PrefState>((set, get) => ({
  // Hindi first for villagers; English first in the officer tools.
  lang: { villager: initialLang('villager', 'hi'), staff: initialLang('staff', 'en') },
  theme: initialTheme(),
  setLang: (scope, lang) => {
    writeLS(`pukaar.lang.${scope}`, lang);
    set({ lang: { ...get().lang, [scope]: lang } });
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
  setOnline: (online: boolean) => void;
  setQueued: (n: number) => void;
  markSample: () => void;
}

export const useNet = create<NetState>((set, get) => ({
  online: typeof navigator === 'undefined' ? true : navigator.onLine,
  queued: 0,
  sample: false,
  setOnline: (online) => set({ online }),
  setQueued: (queued) => set({ queued }),
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
