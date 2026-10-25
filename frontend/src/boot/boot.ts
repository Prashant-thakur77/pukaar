/*
 * The boot painter: inlined into index.html's <head> (boot-plugin.ts) and run before any other script, so a
 * phone on slow 3G sees the answer seconds before React and the app's code have arrived.
 *
 *   - It asks the API for the answer at once: /public/villages/{id}/now on a village page, /public/overview on
 *     the home page. The app takes these requests over (api.ts, takeBoot) instead of asking again.
 *   - It paints the phone's last copy straight away (stamped with its time), then the fresh answer when it
 *     lands. It never shows a level it has not been told: until an answer arrives it says it is checking.
 *   - It paints the same markup, classes and words as the React page (components/Answer.tsx, Landing,
 *     VillagePage, Shell's header; the words from lib/answerText.ts), styled by the critical CSS inlined beside
 *     it. React renders into #root, hidden until the page has its data (boot/handoff.ts), then this is removed.
 *   - It attaches the full stylesheet without blocking the first paint.
 *
 * If this script is blocked or throws, nothing breaks: the app boots as it would without it.
 * No imports at runtime beyond the pure modules below; keep it small (the plugin fails the build over 9 kB gzip).
 */
import { LEAD, MEANS, type ActionLine } from '../lib/actions';
import { districtLine, freshnessText, istClock, LEVEL_WORDS, levelStep, meterLabel, placeFacts, placeLine, shelterWord, type AnswerLang, type AnswerLevel } from '../lib/answerText';
import { loadApp, readAssets } from './assets';
import { BOOT_KEY, type BootResult, type BootState } from './protocol';

type Lang = AnswerLang;
type Level = AnswerLevel;

interface Place {
  name: string | null;
  name_hi: string | null;
  kind_en: string | null;
  kind_hi: string | null;
  walk_min: number | null;
  route_length_m: number | null;
  headroom_m: number | null;
  status: string;
  route_blocked: boolean;
}
interface Now {
  id: string;
  name: string;
  name_hi: string;
  district: string;
  level: Level;
  level_known: boolean;
  checked_at: string | null;
  means: ActionLine;
  actions: ActionLine[];
  safe_place: Place | null;
}
interface OvVillage {
  id: string;
  name: string;
  name_hi: string;
  level: Level;
  data_status?: string;
  data_ok_at?: string | null;
}

const W = window as unknown as Record<string, BootState | undefined>;
const doc = document;
const path = location.pathname;
const villageMatch = path.match(/^\/village\/([^/]+)\/?$/);
const villageId = villageMatch ? safeDecode(villageMatch[1]) : null;
const isHome = path === '/';

function safeDecode(s: string): string | null {
  try {
    return decodeURIComponent(s);
  } catch {
    return null;
  }
}

function ls(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}
function lsSet(key: string, v: string): void {
  try {
    localStorage.setItem(key, v);
  } catch {
    /* storage blocked */
  }
}

/** The language the React page will use (store.ts initialLang): this tab's choice, the remembered one, else the default. */
function pickLang(): Lang {
  // A choice made earlier in this tab holds across a reload (store.ts VISIT_LANG_KEY).
  let visit: string | null = null;
  try {
    visit = sessionStorage.getItem('pukaar.lang.visit');
  } catch {
    /* storage blocked */
  }
  if (visit === 'hi' || visit === 'en') return visit;
  const scope = /^\/(report|t\/|t$)/.test(path) ? 'villager' : /^\/(console|audit|roster|login)(\/|$)|^\/a\//.test(path) ? 'staff' : 'public';
  const v = ls(`pukaar.lang.${scope}`);
  if (v === 'hi' || v === 'en') return v;
  if (scope === 'villager') return 'hi';
  if (scope === 'staff') return 'en';
  return /^hi(-|$)/i.test(navigator.languages?.[0] ?? navigator.language ?? '') ? 'hi' : 'en';
}

let lang = pickLang();
const api = (doc.querySelector('meta[name="pk-api"]')?.getAttribute('content') ?? '').replace(/\/$/, '');

/* ---------- the requests, started now; the app takes them over ---------- */

const started = new Map<string, { at: number; p: Promise<BootResult> }>();
function get(p: string): Promise<BootResult> {
  const pr = fetch(api + p, { headers: { Accept: 'application/json' } }).then(async (r) => {
    let body: unknown = null;
    try {
      body = await r.json();
    } catch {
      /* not JSON */
    }
    return { ok: r.ok, status: r.status, body };
  });
  pr.catch(() => {});
  started.set(p, { at: Date.now(), p: pr });
  return pr;
}

const state: BootState = {
  take(p) {
    const e = started.get(p);
    started.delete(p);
    return e && Date.now() - e.at < 30_000 ? e.p : null;
  },
  has: (p) => started.has(p),
  menu: false,
};
W[BOOT_KEY] = state;

/* ---------- tiny DOM helpers (text is always textContent: names come from the network) ---------- */

type Kid = Node | string | null | false | undefined;
function h(tag: string, attrs: Record<string, string> | null, ...kids: Kid[]): HTMLElement {
  const el = doc.createElement(tag);
  if (attrs) for (const k in attrs) el.setAttribute(k, attrs[k]);
  for (const k of kids) if (k) el.append(k);
  return el;
}

const ICONS: Record<string, string> = {
  'circle-check': '<circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/>',
  eye: '<path d="M2.062 12.348a1 1 0 0 1 0-.696 10.75 10.75 0 0 1 19.876 0 1 1 0 0 1 0 .696 10.75 10.75 0 0 1-19.876 0"/><circle cx="12" cy="12" r="3"/>',
  'triangle-alert': '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
  siren: '<path d="M7 18v-6a5 5 0 1 1 10 0v6"/><path d="M5 21a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-1a2 2 0 0 0-2-2H7a2 2 0 0 0-2 2z"/><path d="M21 12h1"/><path d="M18.5 4.5 18 5"/><path d="M2 12h1"/><path d="M12 2v1"/><path d="m4.929 4.929.707.707"/><path d="M12 12v6"/>',
  'cloud-off': '<path d="M10.94 5.274A7 7 0 0 1 15.71 10h1.79a4.5 4.5 0 0 1 4.222 6.057"/><path d="M18.796 18.81A4.5 4.5 0 0 1 17.5 19H9A7 7 0 0 1 5.79 5.78"/><path d="m2 2 20 20"/>',
  'chevron-right': '<path d="m9 18 6-6-6-6"/>',
  'chevron-down': '<path d="m6 9 6 6 6-6"/>',
  'arrow-left': '<path d="m12 19-7-7 7-7"/><path d="M19 12H5"/>',
  mountain: '<path d="m8 3 4 8 5-5 5 15H2L8 3z"/>',
  'arrow-up-right': '<path d="M7 7h10v10"/><path d="M7 17 17 7"/>',
  'arrow-down': '<path d="M12 5v14"/><path d="m19 12-7 7-7-7"/>',
  compass: '<path d="m16.24 7.76-1.804 5.411a2 2 0 0 1-1.265 1.265L7.76 16.24l1.804-5.411a2 2 0 0 1 1.265-1.265z"/><circle cx="12" cy="12" r="10"/>',
  phone: '<path d="M13.832 16.568a1 1 0 0 0 1.213-.303l.355-.465A2 2 0 0 1 17 15h3a2 2 0 0 1 2 2v3a2 2 0 0 1-2 2A18 18 0 0 1 2 4a2 2 0 0 1 2-2h3a2 2 0 0 1 2 2v3a2 2 0 0 1-.8 1.6l-.468.351a1 1 0 0 0-.292 1.233 14 14 0 0 0 6.392 6.384"/>',
  mic: '<path d="M12 19v3"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><rect x="9" y="2" width="6" height="13" rx="3"/>',
  map: '<path d="M14.106 5.553a2 2 0 0 0 1.788 0l3.659-1.83A1 1 0 0 1 21 4.619v12.764a1 1 0 0 1-.553.894l-4.553 2.277a2 2 0 0 1-1.788 0l-4.212-2.106a2 2 0 0 0-1.788 0l-3.659 1.83A1 1 0 0 1 3 19.381V6.618a1 1 0 0 1 .553-.894l4.553-2.277a2 2 0 0 1 1.788 0z"/><path d="M15 5.764v15"/><path d="M9 3.236v15"/>',
  menu: '<path d="M4 5h16"/><path d="M4 12h16"/><path d="M4 19h16"/>',
  'sun-moon': '<path d="M12 2v2"/><path d="M14.837 16.385a6 6 0 1 1-7.223-7.222c.624-.147.97.66.715 1.248a4 4 0 0 0 5.26 5.259c.589-.255 1.396.09 1.248.715"/><path d="M16 12a4 4 0 0 0-4-4"/><path d="m19 5-1.256 1.256"/><path d="M20 12h2"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/>',
  moon: '<path d="M20.985 12.486a9 9 0 1 1-9.473-9.472c.405-.022.617.46.402.803a6 6 0 0 0 8.268 8.268c.344-.215.825-.004.803.401"/>',
};
const LEVEL_ICON: Record<Level, string> = { normal: 'circle-check', watch: 'eye', warning: 'triangle-alert', critical: 'siren' };

/** A lucide icon, as lucide-react draws it. */
function icon(name: string, cls = ''): Element {
  const s = doc.createElementNS('http://www.w3.org/2000/svg', 'svg');
  const a: Record<string, string> = {
    xmlns: 'http://www.w3.org/2000/svg', width: '24', height: '24', viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor',
    'stroke-width': '2', 'stroke-linecap': 'round', 'stroke-linejoin': 'round', class: `lucide lucide-${name}${cls ? ` ${cls}` : ''}`, 'aria-hidden': 'true',
  };
  for (const k in a) s.setAttribute(k, a[k]);
  s.innerHTML = ICONS[name];
  return s;
}

const T = {
  status: ['गाँवों का हाल', 'Village status'],
  report: ['सूचना दें', 'Report'],
  how: ['कैसे काम करता है', 'How it works'],
  proof: ['सबूत और पायलट', 'Proof and pilot'],
  officer: ['अधिकारी', 'Officers'],
  console: ['अधिकारी', 'Console'],
  langAria: ['अंग्रेज़ी में देखें', 'Switch to Hindi'],
  menu: ['मेन्यू खोलें', 'Open menu'],
  call: ['112 पर आपातकालीन कॉल करें', 'Call emergency number 112'],
  skip: ['सीधे सामग्री पर जाएँ', 'Skip to content'],
  theme: ['रंग-रूप बदलें', 'Change theme'],
  system: ['सिस्टम', 'System'],
  light: ['हल्का', 'Light'],
  dark: ['गहरा', 'Dark'],
};
const tr = (k: keyof typeof T) => T[k][lang === 'hi' ? 0 : 1];

function call112(): HTMLElement {
  return h('a', { href: 'tel:112', class: 'call112', 'aria-label': tr('call') }, icon('phone'), h('span', { class: 'c112-hi' }, lang === 'hi' ? 'आपातकाल' : 'Emergency'), h('span', { class: 'c112-num' }, '112'));
}

/* ---------- the header (Shell.tsx's, without what needs React) ---------- */

function header(): HTMLElement {
  const signedIn = Boolean(ls('pukaar.token'));
  const navLink = (href: string, label: string, caret = false) =>
    h('a', { href, class: `hd-link${(href === '/' ? path === '/' : path.startsWith(href)) ? ' is-active' : ''}`, ...(href === path ? { 'aria-current': 'page' } : {}) }, label, caret && ' ', caret && icon('chevron-down', 'hd-caret'));
  const other: Lang = lang === 'hi' ? 'en' : 'hi';
  const langBtn = h('button', { type: 'button', class: 'hd-icon hd-lang', 'aria-label': tr('langAria'), title: tr('langAria') }, h('span', { lang: other, 'aria-hidden': 'true' }, lang === 'hi' ? 'EN' : 'हि'));
  langBtn.addEventListener('click', () => {
    lang = other;
    for (const scope of ['public', 'villager', 'staff']) lsSet(`pukaar.lang.${scope}`, other);
    try {
      sessionStorage.setItem('pukaar.lang.visit', other);
    } catch {
      /* storage blocked */
    }
    paint();
  });
  // The theme, as Shell's ThemeButton: system, light, dark, round again (store.ts applyTheme's rule).
  const pref = ((t) => (t === 'light' || t === 'dark' ? t : 'system'))(ls('pukaar.theme'));
  const themeLabel = `${tr('theme')}: ${tr(pref)}`;
  const themeBtn = h('button', { type: 'button', class: 'hd-icon', 'aria-label': themeLabel, title: themeLabel }, icon(pref === 'light' ? 'sun' : pref === 'dark' ? 'moon' : 'sun-moon'));
  themeBtn.addEventListener('click', () => {
    const next = pref === 'system' ? 'light' : pref === 'light' ? 'dark' : 'system';
    try {
      if (next === 'system') localStorage.removeItem('pukaar.theme');
      else localStorage.setItem('pukaar.theme', next);
    } catch {
      /* storage blocked */
    }
    const villager = /^\/(?:$|village\/|report|t\/|safe\/|live)/.test(path);
    const resolved = next === 'system' && villager ? 'light' : next;
    if (resolved === 'system') doc.documentElement.removeAttribute('data-theme');
    else doc.documentElement.setAttribute('data-theme', resolved);
    paint();
  });
  const menu = h('button', { type: 'button', class: 'hd-icon hd-menu', 'aria-expanded': 'false', 'aria-label': tr('menu') }, icon('menu'));
  // The sheet needs the app: remember the tap and the header opens it as soon as React has drawn.
  menu.addEventListener('click', () => {
    state.menu = true;
    menu.setAttribute('aria-busy', 'true');
  });
  return h(
    'header',
    { class: 'hd' },
    h(
      'div',
      { class: 'hd-inner' },
      h('a', { href: '/', class: 'hd-brand', 'aria-label': lang === 'hi' ? 'पुकार: गाँवों का हाल' : 'Pukaar: village status' }, brand()),
      h('nav', { class: 'hd-nav', 'aria-label': lang === 'hi' ? 'मुख्य' : 'Main' }, navLink('/', tr('status')), navLink('/report', tr('report')), navLink('/how', tr('how')), navLink('/proof', tr('proof'), true)),
      h(
        'div',
        { class: 'hd-tools' },
        signedIn ? h('span', { class: 'hd-desk hd-user' }, navLink('/console', tr('console'))) : h('a', { href: '/login', class: 'hd-link hd-desk' }, tr('officer')),
        langBtn,
        h('span', { class: 'hd-desk' }, themeBtn),
        call112(),
        menu,
      ),
    ),
  );
}

function brand(): HTMLElement {
  const s = doc.createElementNS('http://www.w3.org/2000/svg', 'svg');
  for (const [k, v] of [['class', 'pk-mark'], ['width', '28'], ['height', '28'], ['viewBox', '0 0 32 32'], ['aria-hidden', 'true'], ['focusable', 'false']]) s.setAttribute(k, v);
  s.innerHTML =
    '<circle cx="16" cy="16" r="16" fill="var(--accent)"/><path d="M4.5 22.5 11 12.5l3.6 5.2L19 10l8.5 12.5z" fill="var(--on-accent)"/><path d="M4 25.6c2 0 2-1.2 4-1.2s2 1.2 4 1.2 2-1.2 4-1.2 2 1.2 4 1.2 2-1.2 4-1.2 2 1.2 4 1.2" fill="none" stroke="var(--on-accent)" stroke-width="1.6" stroke-linecap="round"/><path d="M8.2 9.6a4 4 0 0 1 0-4.6M5.6 11.4a7.2 7.2 0 0 1 0-8.2" fill="none" stroke="var(--on-accent)" stroke-width="1.6" stroke-linecap="round"/>';
  return h('span', { class: 'wordmark' }, s, lang === 'hi' ? h('span', { class: 'wm-hi' }, 'पुकार') : h('span', { class: 'wm-hi' }, 'Pukaar'));
}

/* ---------- the answer pieces (components/Answer.tsx) ---------- */

function meter(level: Level, unknown: boolean): HTMLElement {
  const m = h('span', { class: 'lv-meter', role: 'img', 'aria-label': meterLabel(level, unknown, lang) });
  for (let i = 0; i < 4; i++) m.append(h('i', !unknown && i < levelStep(level) ? { class: 'is-on' } : null));
  return m;
}

function freshness(at: string | null, offline: boolean, opts: { every?: boolean; next?: boolean }): HTMLElement {
  const f = freshnessText(at, lang, { offline, ...opts });
  if (!istClock(at)) return h('p', { class: 'fresh' }, f.line);
  return h(
    'p',
    { class: `fresh${f.stale ? ' is-stale' : ''}${f.offline ? ' is-offline' : ''}` },
    f.chip && h('span', { class: 'fresh-chip' }, ...(f.offline ? [icon('cloud-off'), ` ${f.chip}`] : [f.chip])),
    h('span', null, f.line),
  );
}

function banner(level: Level, unknown: boolean, means: ActionLine, title: Kid[], heading: 'h1' | 'h2', id: string | null, extra: Kid[]): HTMLElement {
  const shown = unknown ? 'nodata' : level;
  const hi = lang === 'hi';
  const word = unknown ? (hi ? 'डेटा नहीं मिल रहा' : 'No data') : LEVEL_WORDS[level][lang];
  const sub = h('p', { class: 'lvb-sub' }, unknown ? (hi ? '‘सामान्य’ पर भरोसा न करें' : 'Do not rely on “Normal”') : means[lang]);
  return h(
    'section',
    { class: `lvb lv-${shown}`, ...(id ? { 'aria-labelledby': id } : {}), 'aria-live': level === 'critical' ? 'assertive' : 'polite', 'aria-atomic': 'true' },
    h('div', { class: 'lvb-head' }, icon(unknown ? 'cloud-off' : LEVEL_ICON[level], 'lvb-icon'), h('p', { class: 'lvb-word' }, word), meter(level, unknown)),
    sub,
    h(heading, { class: 'lvb-place', ...(id ? { id } : {}) }, ...title),
    ...extra,
  );
}

function goLink(href: string, ic: string, label: string): HTMLElement {
  return h('a', { href, class: 'go-link' }, icon(ic), ` ${label} `, icon('chevron-right'));
}

/* ---------- /village/:id ---------- */

function villageAnswer(now: Now, offline: boolean): HTMLElement {
  const hi = lang === 'hi';
  const unknown = !now.level_known;
  const shown = unknown ? 'nodata' : now.level;
  const urgent = now.level === 'warning' || now.level === 'critical';
  const place = now.safe_place;
  const lines = (now.actions ?? []).slice(0, 3);
  const top = h(
    'div',
    { class: 'wrap vtop' },
    h('nav', { class: 'vcrumb', 'aria-label': hi ? 'आप यहाँ हैं' : 'You are here' }, h('a', { href: '/', class: 'go-link' }, icon('arrow-left'), ` ${tr('status')}`)),
    h(
      'div',
      { class: 'vtop-main' },
      banner(
        now.level,
        unknown,
        now.means ?? MEANS[now.level],
        [h('span', null, hi ? now.name_hi : now.name), h('span', { class: 'lvb-en' }, ` · ${districtLine(now.district, lang)}`)],
        'h1',
        'v-title',
        [freshness(now.checked_at, offline, { every: true })],
      ),
      h(
        'section',
        { class: `acts lv-${shown}`, 'aria-labelledby': 'acts-h' },
        h('h2', { id: 'acts-h', class: 'acts-h' }, hi ? 'अभी क्या करें' : 'What to do now'),
        h('ol', { class: 'acts-list' }, ...lines.map((l) => h('li', null, h('span', { class: 'acts-hi' }, l[lang])))),
        h('div', { class: 'acts-more' }, urgent ? h('span', { class: 'vtop-112' }, call112()) : goLink('#where', 'mountain', hi ? 'ऊँची जगह और रास्ता देखें' : 'See the high place and the route')),
      ),
    ),
    place &&
      h(
        'aside',
        { class: 'vtop-aside', 'aria-labelledby': 'vwhere-h' },
        h('h2', { id: 'vwhere-h', class: 'vside-h' }, hi ? 'कहाँ जाएँ' : 'Where to go'),
        h('p', { class: 'vside-name' }, (hi ? place.name_hi || place.name : place.name || place.name_hi) ?? ''),
        h(
          'p',
          { class: 'vside-line' },
          h('span', { class: `vside-status s-${place.status.toLowerCase()}` }, shelterWord(place.status, lang)),
          place.route_blocked && h('span', { class: 'vside-status s-closed' }, hi ? 'रास्ता बंद' : 'Route closed'),
        ),
        h('p', { class: 'vside-facts' }, placeFacts(place, lang)),
        h('a', { href: '#where', class: 'go-link' }, `${hi ? 'नक्शा और रास्ता' : 'Map and route'} `, icon('chevron-right')),
      ),
  );
  const page = h('div', { class: `village-page${urgent ? ' is-urgent' : ''}` }, top);
  if (urgent && !unknown) {
    const line = placeLine(place, lang);
    page.append(
      h('div', { class: 'sab-spacer', 'aria-hidden': 'true' }),
      h(
        'nav',
        { class: `sab lv-${now.level}`, 'aria-label': hi ? 'अभी के लिए' : 'Right now' },
        now.level === 'critical' && h('a', { href: 'tel:112', class: 'sab-btn sab-112', 'aria-label': tr('call') }, icon('phone'), ' ', h('span', null, hi ? '112 पर कॉल करें' : 'Call 112')),
        h('a', { href: '#where', class: 'sab-btn sab-where' }, icon('mountain'), h('span', { class: 'sab-text' }, h('span', null, hi ? 'कहाँ जाएँ' : 'Where to go'), line && now.level === 'warning' && h('span', { class: 'sab-place' }, ` · ${line}`)), icon('chevron-right', 'sab-go')),
      ),
    );
  }
  return page;
}

function villageWait(): HTMLElement {
  const hi = lang === 'hi';
  return h(
    'div',
    { class: 'wrap village-page vtop-wait' },
    h('p', { class: 'vwait-title' }, hi ? 'गाँव का हाल आ रहा है…' : 'Getting the village’s level…'),
    h('p', { class: 'vwait-body' }, hi ? 'ख़तरा दिखे तो इंतज़ार न करें: ऊँची जगह जाएँ और ' : 'If you see danger, do not wait: go to high ground and ', h('a', { href: 'tel:112', class: 'go-link' }, hi ? '112 पर कॉल करें' : 'call 112'), '.'),
  );
}

/* ---------- / (Landing.tsx's status block) ---------- */

const SPOTS: Record<string, [number, number]> = { janjehli: [96, 112], thunag: [190, 146], gohar: [318, 168], pandoh: [420, 150], sujanpur: [566, 196] };
const known = (v: OvVillage) => !(v.level === 'normal' && (v.data_status === 'stale' || v.data_status === 'unavailable'));

function valley(villages: OvVillage[]): HTMLElement {
  const placed = villages.filter((v) => SPOTS[v.id]);
  const s = doc.createElementNS('http://www.w3.org/2000/svg', 'svg');
  for (const [k, v] of [['viewBox', '0 0 640 260'], ['aria-hidden', 'true'], ['focusable', 'false'], ['preserveAspectRatio', 'xMidYMid meet']]) s.setAttribute(k, v);
  s.innerHTML =
    '<path class="valley-ridge" d="M0 92 L58 50 L104 78 L160 30 L214 66 L276 38 L330 74 L392 28 L452 70 L506 44 L560 80 L604 58 L640 76"/><path class="valley-ridge is-far" d="M0 128 L70 96 L132 118 L198 82 L262 112 L330 90 L398 120 L470 92 L540 124 L640 104"/><path class="valley-river" d="M20 98 C 60 104, 76 116, 96 112 S 150 138, 190 146 S 268 176, 318 168 S 390 146, 420 150 S 520 196, 566 196 S 620 214, 640 218"/>' +
    placed.map((v) => `<circle class="valley-dot lv-${known(v) ? v.level : 'nodata'}" cx="${SPOTS[v.id][0]}" cy="${SPOTS[v.id][1]}" r="8"/>`).join('');
  const fig = h('figure', { class: 'valley', 'aria-label': lang === 'hi' ? 'पाँच गाँव, ब्यास घाटी' : 'The five villages in the Beas valley' }, s);
  for (const v of placed) {
    const [x, y] = SPOTS[v.id];
    const label = h('span', { 'aria-hidden': 'true', class: `valley-label${y > 160 ? ' is-below' : ''}` }, h('span', null, lang === 'hi' ? v.name_hi : v.name));
    if (v.level !== 'normal') label.append(h('span', { class: `valley-level lv-${v.level}` }, ` · ${LEVEL_WORDS[v.level][lang]}`));
    if (!known(v)) label.append(h('span', { class: 'valley-level lv-nodata' }, lang === 'hi' ? ' · डेटा नहीं' : ' · No data'));
    label.style.left = `${(x / 640) * 100}%`;
    label.style.top = `${(y / 260) * 100}%`;
    fig.append(label);
  }
  return fig;
}

/** The kicker's wave mark (components/Art.tsx Lehar), so the hero's first line does not move at the hand-over. */
function lehar(): Element {
  const s = doc.createElementNS('http://www.w3.org/2000/svg', 'svg');
  for (const [k, v] of [['class', 'lehar'], ['viewBox', '0 0 160 32'], ['width', '80'], ['height', '16'], ['aria-hidden', 'true'], ['focusable', 'false']]) s.setAttribute(k, v);
  s.innerHTML =
    '<g fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path class="lehar-line" d="M3 27 H40 M120 27 H157"/><path d="M30 27 C 40 27, 46 23, 48 17 C 50 11, 58 9, 62 13 C 65 16, 63 21, 59 21 C 56 21, 55 18, 57 16"/><path d="M130 27 C 120 27, 114 23, 112 17 C 110 11, 102 9, 98 13 C 95 16, 97 21, 101 21 C 104 21, 105 18, 103 16"/><path d="M68 27 L80 10 L92 27"/><path d="M75 17.5 L78 19.5 L80 16.8 L82 19.5 L85 17.5"/><path class="lehar-call" d="M75 6.5 A6 6 0 0 1 85 6.5 M71.5 3.5 A11 11 0 0 1 88.5 3.5"/></g>';
  return s;
}

function home(villages: OvVillage[] | null, offline: boolean): HTMLElement {
  const hi = lang === 'hi';
  const vs = villages ?? [];
  const n = vs.length;
  const rank = (l: Level) => levelStep(l);
  const name = (v: OvVillage) => (hi ? v.name_hi : v.name);
  const raised = vs.filter((v) => rank(v.level) >= 2).sort((a, b) => rank(b.level) - rank(a.level));
  const unknown = vs.filter((v) => !known(v));
  const checkedAt = vs.reduce<string | null>((m, v) => (v.data_ok_at && (!m || v.data_ok_at > m) ? v.data_ok_at : m), null);

  // The hero (Landing.tsx's): the promise, the two actions and the live line. The floating cards wait
  // for the app; the cards sit beside the copy on a desk and are not drawn on a phone.
  const live = !villages
    ? ['lv-nodata', hi ? 'गाँवों की जाँच हो रही है…' : 'Checking the villages…']
    : raised.length > 0
      ? [`lv-${raised[0].level}`, hi ? `${name(raised[0])}: ${LEVEL_WORDS[raised[0].level].hi}${raised.length > 1 ? ` और ${raised.length - 1} गाँव` : ''}` : `${name(raised[0])}: ${LEVEL_WORDS[raised[0].level].en}${raised.length > 1 ? ` and ${raised.length - 1} more` : ''}`]
      : unknown.length > 0
        ? ['lv-nodata', hi ? `${unknown.length} गाँव का डेटा नहीं मिल रहा` : `No data for ${unknown.length} ${unknown.length === 1 ? 'village' : 'villages'}`]
        : ['lv-normal', hi ? `सभी ${n} गाँव सामान्य` : `All ${n} villages at Normal`];
  const hero = h(
    'section',
    { class: 'home-hero', 'aria-labelledby': 'hero-h' },
    h(
      'div',
      { class: 'wrap-wide home-hero-in' },
      h(
        'div',
        { class: 'home-hero-copy', 'data-tour': 'hero' },
        h('p', { class: 'kicker home-kicker' }, lehar(), hi ? 'हिमाचल प्रदेश · मंडी और हमीरपुर' : 'Himachal Pradesh · Mandi and Hamirpur'),
        h(
          'h1',
          { id: 'hero-h', class: 'home-hero-h1' },
          h('span', null, hi ? 'नदी से पहले,' : 'The call that'),
          ' ',
          h('span', null, hi ? 'गाँव तक पहुँचने' : 'reaches the village'),
          ' ',
          h('span', { class: 'home-hero-blue' }, hi ? 'वाली पुकार।' : 'before the river.'),
        ),
        h(
          'p',
          { class: 'home-hero-lead' },
          hi
            ? 'पुकार हर 15 मिनट बारिश और नदी का पूर्वानुमान पढ़ता है। ख़तरा दिखे तो एक अधिकारी एक टैप में चेतावनी मंज़ूर करता है, और गाँव के लिए जुड़े हर फ़ोन पर वह हिंदी में बोलकर पहुँचती है।'
            : 'Every 15 minutes Pukaar reads the rain and river forecasts. When danger shows, an officer approves the alert with one tap, and every phone registered for the village hears it spoken in Hindi.',
        ),
        h(
          'div',
          { class: 'home-hero-ctas' },
          h('a', { href: '/report', class: 'home-report' }, icon('mic'), h('span', null, hi ? 'पानी बढ़ रहा है? सूचना दें' : 'Water rising? Report it')),
          h('a', { href: '/live', class: 'home-ghost' }, h('span', null, hi ? 'लाइव नक्शा' : 'Live map'), icon('arrow-up-right')),
        ),
        h(
          'div',
          { class: 'home-hero-row' },
          h('a', { href: '#villages', class: `home-live ${live[0]}` }, h('span', { class: 'home-live-dot', 'aria-hidden': 'true' }), h('span', null, live[1]), icon('arrow-down')),
          // The tour needs the app: its pill holds its place until React draws the real button.
          h('span', { class: 'tour-pill home-tour', 'aria-hidden': 'true' }, icon('compass'), hi ? '60 सेकंड का टूर देखें' : 'Take the 60-second tour'),
        ),
      ),
    ),
  );

  const now = h('div', { class: 'home-now' }, h('p', { class: 'home-region' }, tr('status')));
  if (!villages) {
    now.append(h('h2', { id: 'home-h', class: 'home-h1' }, tr('status')), h('p', { class: 'home-wait' }, hi ? 'हर गाँव का हाल आ रहा है…' : 'Getting each village’s level…'));
  } else if (raised.length === 0) {
    const ok = () => h('span', { class: 'home-ok' }, icon('circle-check'), hi ? 'सामान्य' : 'Normal');
    const h2 = h('h2', { id: 'home-h', class: 'home-h1' });
    if (unknown.length > 0) h2.append(hi ? `${unknown.length} गाँव का डेटा नहीं मिल रहा` : `No data for ${unknown.length} ${unknown.length === 1 ? 'village' : 'villages'}`);
    else if (hi) h2.append(`आज सब ${n} गाँव `, ok(), ' हैं।');
    else h2.append(`All ${n} villages are at `, ok(), '.');
    now.append(h2);
    if (unknown.length > 0) now.append(h('p', { class: 'home-lead' }, hi ? '‘सामान्य’ पर भरोसा न करें; नदी पर ख़ुद नज़र रखें।' : 'Do not rely on “Normal”; watch the river yourself.'));
    now.append(freshness(checkedAt, offline, { next: true }));
  } else {
    now.append(
      h('h2', { id: 'home-h', class: 'sr-only' }, tr('status')),
      h(
        'div',
        { class: 'home-banners' },
        ...raised.map((v) =>
          banner(
            v.level,
            false,
            MEANS[v.level],
            [h('a', { href: `/village/${encodeURIComponent(v.id)}`, class: 'home-banner-link' }, h('span', null, name(v)), h('span', { class: 'home-banner-go' }, `${hi ? 'क्या करें' : 'What to do'} `, icon('chevron-right')))],
            'h2',
            null,
            [h('p', { class: 'lvb-why' }, h('span', null, LEAD[v.level][lang]))],
          ),
        ),
      ),
    );
    if (raised.length < n) now.append(h('p', { class: 'home-lead' }, hi ? `बाक़ी ${n - raised.length} गाँव सामान्य हैं।` : `The other ${n - raised.length} villages are at Normal.`));
    now.append(freshness(checkedAt, offline, { next: true }));
  }
  const sorted = [...vs].sort((a, b) => rank(b.level) - rank(a.level) || a.name.localeCompare(b.name));
  const rows = n
    ? h(
        'ul',
        { class: 'vrows', 'aria-label': hi ? 'पाँच गाँव' : 'The villages' },
        ...sorted.map((v) => {
          const k = known(v);
          return h(
            'li',
            null,
            h(
              'a',
              { href: `/village/${encodeURIComponent(v.id)}`, class: `vrow lv-${k ? v.level : 'nodata'}` },
              h('span', { class: 'vrow-name' }, h('span', null, name(v))),
              h('span', { class: 'vrow-level' }, icon(k ? LEVEL_ICON[v.level] : 'cloud-off'), h('span', null, k ? LEVEL_WORDS[v.level][lang] : hi ? 'डेटा नहीं' : 'No data')),
              icon('chevron-right', 'vrow-go'),
            ),
          );
        }),
      )
    : h('p', { class: 'vrows vrows-wait' }, hi ? 'गाँवों की सूची आ रही है…' : 'Loading the villages…');
  const pick = h(
    'div',
    { class: 'home-pick' },
    h('h3', { class: 'home-h2' }, hi ? 'अपना गाँव चुनें' : 'Choose your village'),
    rows,
    h('div', { class: 'home-acts' }, goLink('/live', 'map', hi ? 'नक्शे पर देखें' : 'See on the map')),
  );
  // The valley sits beside the status on a desk; on a phone it is below the fold, so the app draws it.
  const wide = W.__pkCut != null || (typeof matchMedia === 'function' && matchMedia('(min-width: 1024px)').matches);
  return h(
    'div',
    { class: 'home' },
    hero,
    h('section', { class: 'home-status wrap', id: 'villages', 'aria-labelledby': 'home-h' }, now, pick, wide && h('div', { class: 'home-lede' }, valley(vs))),
  );
}

/* ---------- painting ---------- */

interface Shown {
  data: unknown;
  offline: boolean;
}
let shown: Shown | null = null;

function body(): HTMLElement {
  if (villageId) return shown?.data ? villageAnswer(shown.data as Now, shown.offline) : villageWait();
  if (isHome) return home(shown?.data ? (shown.data as { villages: OvVillage[] }).villages : null, Boolean(shown?.offline));
  return h('p', { class: 'boot-wait' }, lang === 'hi' ? 'पुकार खुल रहा है…' : 'Opening Pukaar…');
}

function paint(): void {
  const root = doc.getElementById('pk-boot');
  if (!root) return;
  doc.documentElement.lang = lang;
  root.replaceChildren(h('a', { href: '#main', class: 'skip-link' }, tr('skip')), header(), h('main', { id: 'main', class: 'page', tabindex: '-1' }, body()));
}

function show(data: unknown, offline: boolean): void {
  shown = { data, offline };
  if (doc.readyState !== 'loading') paint();
}

/**
 * The app's code and full styles (boot/assets.ts). On a page with an answer to paint and nothing on the phone
 * yet, they wait until the answer is on screen (at most 2.5 s), so they do not queue in front of it on 3G.
 */
const route = villageId ? 'village' : isHome ? 'home' : null;
function startApp(): void {
  const a = readAssets();
  if (a) loadApp(a, route);
}

function onParsed(): void {
  paint();
}

if (villageId) {
  const raw = ls(`pukaar.now.${villageId}`);
  try {
    const c = raw ? (JSON.parse(raw) as { now?: Now }) : null;
    if (c?.now?.id === villageId && Array.isArray(c.now.actions)) shown = { data: c.now, offline: false };
  } catch {
    /* a broken copy is ignored */
  }
  get(`/public/villages/${encodeURIComponent(villageId)}/now`).then(
    (r) => {
      if (r.ok && r.body && (r.body as Now).id === villageId) {
        lsSet(`pukaar.now.${villageId}`, JSON.stringify({ now: r.body, fetchedAt: Date.now() }));
        lsSet('pukaar.lastVillage', villageId);
        show(r.body, false);
      }
    },
    () => shown && show(shown.data, true),
  ).finally(startApp);
} else if (isHome) {
  const raw = ls('pukaar.overview');
  try {
    const c = raw ? (JSON.parse(raw) as { villages?: OvVillage[] }) : null;
    if (Array.isArray(c?.villages)) shown = { data: c, offline: false };
  } catch {
    /* ignored */
  }
  get('/public/overview').then(
    (r) => {
      if (r.ok && Array.isArray((r.body as { villages?: unknown })?.villages)) {
        lsSet('pukaar.overview', JSON.stringify(r.body));
        show(r.body, false);
      }
    },
    () => shown && show(shown.data, true),
  ).finally(startApp);
}

// A page with no answer to paint, or with one already on the phone: the app starts now. Otherwise once the
// answer has landed (above), and never later than 2.5 s.
if (!route || shown) startApp();
else setTimeout(startApp, 2500);

if (doc.readyState === 'loading') {
  doc.addEventListener('readystatechange', function once() {
    doc.removeEventListener('readystatechange', once);
    onParsed();
  });
} else onParsed();
