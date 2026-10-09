import type { Lang } from '../store';

const locale = (lang: Lang) => (lang === 'hi' ? 'hi-IN' : 'en-IN');

export function fmtNumber(n: number | null | undefined, lang: Lang, digits = 0): string {
  if (n == null || Number.isNaN(n)) return '—';
  return new Intl.NumberFormat(locale(lang), { maximumFractionDigits: digits }).format(n);
}

export function fmtTime(iso: string | null | undefined, lang: Lang): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return new Intl.DateTimeFormat(locale(lang), { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }).format(d);
}

export function fmtDate(iso: string | null | undefined, lang: Lang): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return new Intl.DateTimeFormat(locale(lang), { day: 'numeric', month: 'short', year: 'numeric' }).format(d);
}

export function fmtAgo(iso: string | null | undefined, lang: Lang, now = Date.now()): string {
  if (!iso) return '—';
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return iso;
  const sec = Math.round((t - now) / 1000);
  // Replay records carry archived timestamps; a date reads better than "1,187 days ago".
  if (Math.abs(sec) > 7 * 86400) return fmtTime(iso, lang);
  const rtf = new Intl.RelativeTimeFormat(locale(lang), { numeric: 'auto' });
  const abs = Math.abs(sec);
  if (abs < 60) return rtf.format(sec, 'second');
  if (abs < 3600) return rtf.format(Math.round(sec / 60), 'minute');
  if (abs < 86400) return rtf.format(Math.round(sec / 3600), 'hour');
  return rtf.format(Math.round(sec / 86400), 'day');
}

export function fmtDuration(ms: number): string {
  if (ms <= 0) return '0:00';
  const s = Math.floor(ms / 1000);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const r = s % 60;
  return h > 0 ? `${h}:${String(m).padStart(2, '0')}:${String(r).padStart(2, '0')}` : `${m}:${String(r).padStart(2, '0')}`;
}

/** expires_at may be an ISO string or epoch seconds (the backend sends seconds). */
export function expiryMs(v: string | number | null | undefined): number | null {
  if (v == null || v === '') return null;
  if (typeof v === 'number' || /^\d+(\.\d+)?$/.test(String(v))) {
    const n = Number(v);
    return n < 1e12 ? n * 1000 : n;
  }
  const t = new Date(v).getTime();
  return Number.isNaN(t) ? null : t;
}
