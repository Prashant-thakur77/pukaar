/**
 * Random ids the report page sends with each report (POST /reports device_id and session_id).
 *
 * The backend never stores them as sent: it keeps salted hashes only (services/report_guard.py),
 * and uses them to tell two phones apart, so two reports from one phone cannot confirm each other.
 * They identify nobody: no name, number or hardware id goes into them, and clearing site data
 * makes new ones. When storage is blocked (private mode) each page load gets its own.
 */

const DEVICE_KEY = 'pukaar.device';
const SESSION_KEY = 'pukaar.session';
let pageFallback: string | null = null;

export function randomId(): string {
  try {
    if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') return crypto.randomUUID();
    if (typeof crypto !== 'undefined' && typeof crypto.getRandomValues === 'function') {
      const b = crypto.getRandomValues(new Uint8Array(16));
      return Array.from(b, (x) => x.toString(16).padStart(2, '0')).join('');
    }
  } catch {
    /* fall through */
  }
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

function kept(storage: () => Storage, key: string): string {
  try {
    const s = storage();
    const have = s.getItem(key);
    if (have) return have;
    const made = randomId();
    s.setItem(key, made);
    return made;
  } catch {
    pageFallback ??= randomId();
    return pageFallback;
  }
}

/** One per browser on this phone (localStorage). */
export const deviceId = (): string => kept(() => window.localStorage, DEVICE_KEY);

/** One per tab session (sessionStorage). */
export const sessionId = (): string => kept(() => window.sessionStorage, SESSION_KEY);
