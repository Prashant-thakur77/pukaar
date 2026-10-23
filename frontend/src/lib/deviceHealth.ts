/*
 * FloodNet-style device health in plain words (services/devices/floodnet.py): a battery that empties within a week
 * at its slope, more than 20% of readings missing from the sequence numbers, and a value stuck while it rains.
 * Shared by the gauge rows and the siren list on /how#sensors and by the console's siren panel.
 */
import type { Lang } from '../store';

const num = (v: number, lang: Lang) => new Intl.NumberFormat(lang === 'hi' ? 'hi-IN' : 'en-IN').format(v);

/** Words for a FloodNet reason ("battery_empty_in_3d", "packet_loss_31pct", "stuck_6_readings"), else null. */
export function floodnetReason(reason: string, lang: Lang): string | null {
  const hi = lang === 'hi';
  let m = /^battery_empty_in_(\d+)d$/.exec(reason);
  if (m) {
    const d = Number(m[1]);
    if (d === 0) return hi ? 'बैटरी आज ख़त्म हो सकती है' : 'battery may run out today';
    return hi ? `बैटरी लगभग ${num(d, lang)} दिन में ख़त्म` : `battery empty in about ${num(d, lang)} day${d === 1 ? '' : 's'}`;
  }
  m = /^packet_loss_(\d+)pct$/.exec(reason);
  if (m) return hi ? `${num(Number(m[1]), lang)}% रीडिंग नहीं पहुँचीं` : `${num(Number(m[1]), lang)}% of readings lost`;
  m = /^stuck_(\d+)_readings$/.exec(reason);
  if (m) return hi ? `बारिश में ${num(Number(m[1]), lang)} बार एक ही माप` : `same value ${num(Number(m[1]), lang)} times while raining`;
  return null;
}

const OTHER: Record<string, { en: string; hi: string }> = {
  never_heard: { en: 'never heard from', hi: 'कभी संपर्क नहीं' },
  test_overdue: { en: 'test overdue', hi: 'जाँच बाकी' },
  test_failed: { en: 'test failed', hi: 'जाँच विफल' },
  audible_test_failed: { en: 'audible test failed', hi: 'आवाज़ वाली जाँच विफल' },
  lora_only: { en: 'heard over LoRa only', hi: 'केवल LoRa से संपर्क' },
  mic_dead: { en: 'microphone dead', hi: 'माइक्रोफ़ोन बंद' },
  tamper: { en: 'door opened', hi: 'दरवाज़ा खोला गया' },
};

/** Any registry health reason in words; unknown ones are shown as sent. */
export function reasonWord(reason: string, lang: Lang): string {
  const f = floodnetReason(reason, lang);
  if (f) return f;
  if (OTHER[reason]) return OTHER[reason][lang];
  let m = /^silent_(\d+)_min$/.exec(reason);
  if (m) return lang === 'hi' ? `${num(Number(m[1]), lang)} मिनट से चुप` : `silent ${num(Number(m[1]), lang)} min`;
  m = /^late_(\d+)_min$/.exec(reason);
  if (m) return lang === 'hi' ? `${num(Number(m[1]), lang)} मिनट देर` : `late ${num(Number(m[1]), lang)} min`;
  m = /^soc_(\d+)$/.exec(reason);
  if (m) return lang === 'hi' ? `बैटरी ${num(Number(m[1]), lang)}%` : `battery ${num(Number(m[1]), lang)}%`;
  return reason.replace(/_/g, ' ');
}

export interface HealthSignals {
  battery?: { unit: 'mv' | 'soc'; latest: number; slope_per_day: number; days_to_empty: number | null; samples: number } | null;
  packet_loss?: { expected: number; received: number; loss: number | null } | null;
  stuck?: { run: number; limit: number; raining: boolean } | null;
}

/** One line of what was measured, or null when nothing was: "battery −40 mV/day · 3% lost (29 of 30)". */
export function signalsLine(s: HealthSignals | null | undefined, lang: Lang): string | null {
  if (!s) return null;
  const hi = lang === 'hi';
  const parts: string[] = [];
  const b = s.battery;
  if (b) {
    const unit = b.unit === 'soc' ? '%' : hi ? ' mV' : ' mV';
    const slope = `${b.slope_per_day > 0 ? '+' : ''}${num(Math.round(b.slope_per_day), lang)}${unit}`;
    parts.push(hi ? `बैटरी ${slope}/दिन` : `battery ${slope}/day`);
  }
  const p = s.packet_loss;
  if (p && p.loss != null) {
    const pct = num(Math.round(p.loss * 100), lang);
    parts.push(hi ? `${pct}% खोईं (${num(p.received, lang)}/${num(p.expected, lang)})` : `${pct}% lost (${num(p.received, lang)} of ${num(p.expected, lang)})`);
  }
  return parts.length ? parts.join(' · ') : null;
}
