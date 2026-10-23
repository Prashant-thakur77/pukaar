/*
 * The siren layer in plain words (slice S, docs/hardware/ALARM.md): device health chips, the public
 * "siren last tested" line, the alert's siren tier ("Sirens 1/1 verified"), the two-person reply and the
 * signed-SMS fallback link. Pure helpers plus the typed calls; the components only render them.
 *
 * Strings live here, Hindi and English side by side, so the shared i18n table stays untouched.
 * NEEDS NATIVE-SPEAKER REVIEW, as for i18n.ts.
 */
import type { HealthSignals } from './deviceHealth';
import { request } from '../api';
import { format } from '../i18n';
import type { Lang } from '../store';

export type DeviceKind = 'siren' | 'gauge' | 'box' | 'relay' | 'rain';
export type DeviceHealth = 'ok' | 'degraded' | 'offline' | 'fault' | 'unknown';
export type SirenRowStatus = 'commanded' | 'started' | 'verified' | 'not_confirmed' | 'rejected' | 'failed' | 'skipped';

export interface SirenMeas {
  amp_a?: number | null;
  spl_rise_db?: number | null;
}

export interface DeviceTest {
  at: string;
  ok: boolean | null;
  detail?: string | null;
  amp_a?: number | null;
  spl_rise_db?: number | null;
}

/** GET /sensors `devices`: no ids of alerts, owners, radio addresses or numbers. */
export interface PublicDevice {
  device_id: string;
  village_id: string;
  kind: DeviceKind | string;
  installed: boolean;
  simulated: boolean;
  fw?: string | null;
  health: DeviceHealth | string;
  health_reasons?: string[];
  /** FloodNet checks (services/devices/floodnet.py); absent on an older API. */
  health_signals?: HealthSignals;
  state?: string | null;
  state_since?: string | null;
  last_seen?: string | null;
  last_seen_path?: string | null;
  connected?: boolean | null;
  soc?: number | null;
  last_test_silent?: DeviceTest | null;
  last_test_audible?: DeviceTest | null;
  last_sound?: { at?: string | null; pattern?: string | null; verified?: boolean | null } | null;
}

/** GET /villages/{id}/devices: the signed-in view. */
export interface DeviceView extends PublicDevice {
  pending_cmd?: { cmd_id: string; pattern: string; at: string; state: string } | null;
}

export interface SirenRequest {
  request_id?: string;
  id?: string;
  level?: string;
  requested_by?: string;
  expires_at?: string;
}

export interface VillageDevices {
  village_id: string;
  devices: DeviceView[];
  can: { test_siren: boolean; sound_siren: boolean; stop_siren: boolean };
  requests?: SirenRequest[];
}

export interface SirenRow {
  device_id: string;
  round: number;
  cmd_id: string;
  pattern: string;
  level: string;
  src: string;
  status: SirenRowStatus | string;
  commanded_at?: string | null;
  started_at?: string | null;
  verified_at?: string | null;
  meas?: SirenMeas | null;
  error?: string | null;
  simulated?: boolean;
}

export interface SirenTier {
  total: number;
  started: number;
  verified: number;
  pattern?: string | null;
  note?: string | null;
  rows: SirenRow[];
}

/** Public village detail `sirens`: counts and the last test only. */
export interface VillageSirens {
  count: number;
  sounding: number;
  last_test_at: string | null;
  last_test_ok: boolean | null;
  overdue: boolean;
  simulated?: boolean;
}

/** The alert fields the tier line reads (store/models.Alert). */
export interface AlertSirenFields {
  sirens_total?: number;
  sirens_started?: number;
  sirens_verified?: number;
  siren_first_started_at?: string | null;
  siren_first_verified_at?: string | null;
  siren_pattern?: string | null;
  siren_note?: string | null;
}

export type SoundReply =
  | { commanded: number; cmd_ids: string[]; pattern: string }
  | { request_id: string; needs_second_officer: true; expires_at: string };

// -- strings --------------------------------------------------------------------------------------
type Entry = { hi: string; en: string };

export const sirenText = {
  'list.title': { hi: 'सायरन और उपकरण', en: 'Sirens and devices' },
  'list.eyebrow': { hi: 'गाँव तक की आख़िरी कड़ी', en: 'The last mile' },
  'list.honest': {
    hi: 'अभी कोई सायरन हार्डवेयर नहीं लगा है। यहाँ के उपकरण साफ़ लिखे सिम्युलेटर हैं।',
    en: 'No siren hardware is installed yet. Devices here are labelled simulators.',
  },
  'list.empty': { hi: 'अभी कोई उपकरण दर्ज नहीं है', en: 'No devices registered yet' },
  'kind.siren': { hi: 'सायरन', en: 'Siren' },
  'kind.gauge': { hi: 'नदी गेज', en: 'River gauge' },
  'kind.box': { hi: 'प्रधान बॉक्स', en: 'Pradhan box' },
  'kind.relay': { hi: 'LoRa रिले', en: 'LoRa relay' },
  'kind.rain': { hi: 'वर्षा मापक', en: 'Rain gauge' },
  'health.ok': { hi: 'ठीक', en: 'OK' },
  'health.degraded': { hi: 'कमज़ोर', en: 'Degraded' },
  'health.offline': { hi: 'बंद / संपर्क नहीं', en: 'Offline' },
  'health.fault': { hi: 'ख़राबी', en: 'Fault' },
  'health.unknown': { hi: 'पता नहीं (कभी सुना नहीं)', en: 'Unknown (never heard)' },
  simulated: { hi: 'सिम्युलेटर', en: 'Simulated' },
  'seen.label': { hi: 'आख़िरी संपर्क', en: 'Last heartbeat' },
  'seen.never': { hi: 'कभी नहीं', en: 'never' },
  'path.cell': { hi: 'मोबाइल', en: 'cell' },
  'path.lora': { hi: 'LoRa रेडियो', en: 'LoRa' },
  'path.sms': { hi: 'SMS', en: 'SMS' },
  'test.label': { hi: 'आख़िरी जाँच', en: 'Last test' },
  'test.none': { hi: 'अभी तक नहीं', en: 'none yet' },
  'test.silent': { hi: 'चुप जाँच', en: 'silent' },
  'test.audible': { hi: 'आवाज़ वाली जाँच', en: 'audible' },
  'test.ok': { hi: 'ठीक', en: 'OK' },
  'test.failed': { hi: 'नाकाम', en: 'failed' },
  'sound.label': { hi: 'आख़िरी बार बजा', en: 'Last sounded' },
  'sound.verified': { hi: 'पुष्टि हुई', en: 'verified' },
  'sound.unverified': { hi: 'पुष्टि नहीं', en: 'not verified' },
  'state.label': { hi: 'हालत', en: 'State' },
  // public village page
  'tested.at': { hi: 'सायरन आखिरी बार जाँचा गया {date}', en: 'Siren last tested {date}' },
  'tested.never': { hi: 'सायरन अभी तक जाँचा नहीं गया', en: 'Siren never tested' },
  'tested.passed': { hi: 'ठीक', en: 'passed' },
  'tested.failed': { hi: 'नाकाम', en: 'failed' },
  'tested.overdue': { hi: 'जाँच बाकी है', en: 'test overdue' },
  sounding: { hi: 'सायरन बज रहा है', en: 'Siren sounding' },
  // console
  'tier.line': { hi: 'सायरन {v}/{n} पुष्टि', en: 'Sirens {v}/{n} verified' },
  'tier.started': { hi: '{s} बजना शुरू', en: '{s} started' },
  'tier.toggle': { hi: 'सायरन', en: 'Sirens' },
  'tier.none': { hi: 'इस चेतावनी पर कोई सायरन नहीं', en: 'No siren for this alert' },
  'row.commanded': { hi: 'आदेश गया', en: 'commanded' },
  'row.started': { hi: 'बजना शुरू', en: 'started' },
  'row.verified': { hi: 'पुष्टि', en: 'verified' },
  'row.not_confirmed': { hi: 'पुष्टि नहीं हुई', en: 'not confirmed' },
  'row.rejected': { hi: 'उपकरण ने मना किया', en: 'rejected by the device' },
  'row.failed': { hi: 'भेजा नहीं जा सका', en: 'could not be sent' },
  'row.skipped': { hi: 'छोड़ा गया', en: 'skipped' },
  'btn.test.silent': { hi: 'चुप जाँच', en: 'Test silent' },
  'btn.test.audible': { hi: 'आवाज़ वाली जाँच', en: 'Test audible' },
  'btn.test.window': { hi: 'आवाज़ वाली जाँच सिर्फ़ 09:00–18:00 IST', en: 'Audible tests only 09:00–18:00 IST' },
  'btn.sound.warning': { hi: 'चेतावनी सायरन बजाएँ', en: 'Sound Warning' },
  'btn.sound.critical': { hi: 'गंभीर सायरन बजाएँ', en: 'Sound Critical' },
  'btn.stop': { hi: 'सायरन बंद करें', en: 'Stop sirens' },
  'btn.sms': { hi: 'SMS से भेजें', en: 'Send by SMS' },
  'btn.confirm': { hi: 'दूसरे अधिकारी के रूप में पक्का करें', en: 'Confirm as second officer' },
  'confirm.sound.title': { hi: '{village} में सायरन बजाएँ?', en: 'Sound the sirens in {village}?' },
  'confirm.sound.body': {
    hi: 'यह असली सायरन बजाता है और ऑडिट में दर्ज होता है। पहले प्रधान को फ़ोन करें।',
    en: 'This sounds the real sirens and is written to the audit trail. Phone the pradhan first.',
  },
  'confirm.stop.title': { hi: '{village} के सायरन बंद करें?', en: 'Stop the sirens in {village}?' },
  'confirm.stop.body': {
    hi: 'बंद करने से पहले प्रधान को फ़ोन करें। यह ऑडिट में दर्ज होता है।',
    en: 'Phone the pradhan before stopping. This is written to the audit trail.',
  },
  'reason.manual': { hi: 'कंसोल से अधिकारी ने', en: 'officer from the console' },
  'reply.commanded': { hi: '{n} सायरन को आदेश गया ({p})', en: '{n} siren(s) commanded ({p})' },
  'reply.second': {
    hi: 'गंभीर सायरन के लिए दूसरे अधिकारी की पुष्टि चाहिए ({t} तक)। तब तक चेतावनी सायरन चलता है।',
    en: 'Critical needs a second officer to confirm (until {t}). The Warning pattern sounds meanwhile.',
  },
  'reply.stopped': { hi: '{n} सायरन बंद किए', en: '{n} siren(s) stopped' },
  'reply.test': { hi: 'जाँच का आदेश गया ({p})', en: 'Test commanded ({p})' },
  'request.open': { hi: 'गंभीर सायरन पुष्टि का इंतज़ार ({t} तक)', en: 'Critical siren waiting for a second officer (until {t})' },
  'sms.text': { hi: 'यह संदेश सायरन के नंबर पर अपने फ़ोन से भेजें:', en: 'Send this from your own phone to the siren SIM:' },
  'sms.open': { hi: 'SMS ऐप में खोलें', en: 'Open in the SMS app' },
  error: { hi: 'नहीं हो सका', en: 'Could not do that' },
} satisfies Record<string, Entry>;

export type SirenKey = keyof typeof sirenText;

export function st(lang: Lang, key: SirenKey, vars?: Record<string, string | number>): string {
  return format(sirenText[key][lang], vars);
}

// -- health ---------------------------------------------------------------------------------------
const HEALTH_CHIP: Record<DeviceHealth, string> = {
  ok: 'chip-good',
  degraded: 'chip-warn',
  offline: 'chip-bad',
  fault: 'chip-bad',
  unknown: 'chip-muted',
};

/**
 * Chip class and word for a device's health. Fails closed: anything but the exact string "ok" is never
 * shown as OK; a value the UI does not know reads as unknown.
 */
export function healthChip(health: string | null | undefined, lang: Lang): { cls: string; label: string; ok: boolean } {
  const h = (health && health in HEALTH_CHIP ? health : 'unknown') as DeviceHealth;
  return { cls: HEALTH_CHIP[h], label: st(lang, `health.${h}` as SirenKey), ok: h === 'ok' };
}

export function kindWord(kind: string, lang: Lang): string {
  const key = `kind.${kind}` as SirenKey;
  return key in sirenText ? st(lang, key) : kind;
}

export function pathWord(path: string | null | undefined, lang: Lang): string {
  if (!path) return '';
  const key = `path.${path}` as SirenKey;
  return key in sirenText ? st(lang, key) : path;
}

/** "3.1 A · +24 dB" (either part may be missing). */
export function measText(meas: SirenMeas | null | undefined): string {
  if (!meas) return '';
  const parts: string[] = [];
  if (meas.amp_a != null) parts.push(`${meas.amp_a.toFixed(1)} A`);
  if (meas.spl_rise_db != null) parts.push(`${meas.spl_rise_db >= 0 ? '+' : ''}${Math.round(meas.spl_rise_db)} dB`);
  return parts.join(' · ');
}

export function rowStatusWord(status: string, lang: Lang): string {
  const key = `row.${status}` as SirenKey;
  return key in sirenText ? st(lang, key) : status;
}

export function rowTone(status: string): 'good' | 'bad' | 'pending' {
  if (status === 'verified') return 'good';
  if (status === 'commanded' || status === 'started') return 'pending';
  return 'bad';
}

// -- public village line --------------------------------------------------------------------------
export interface TestedLine {
  text: string;
  tone: 'good' | 'bad';
}

/**
 * The village page's one line, or null when the village has no siren. Red (bad) when the last test failed,
 * is overdue or never happened; a missing result is never shown as passed.
 */
export function lastTestedLine(
  s: VillageSirens | null | undefined,
  lang: Lang,
  fmtDate: (iso: string, lang: Lang) => string,
): TestedLine | null {
  if (!s || !s.count) return null;
  const parts: string[] = [];
  let tone: TestedLine['tone'] = 'good';
  if (!s.last_test_at) {
    parts.push(st(lang, 'tested.never'));
    tone = 'bad';
  } else {
    const ok = s.last_test_ok === true;
    parts.push(`${st(lang, 'tested.at', { date: fmtDate(s.last_test_at, lang) })}: ${st(lang, ok ? 'tested.passed' : 'tested.failed')}`);
    if (!ok) tone = 'bad';
  }
  if (s.overdue) {
    parts.push(st(lang, 'tested.overdue'));
    tone = 'bad';
  }
  if (s.sounding > 0) parts.push(st(lang, 'sounding'));
  if (s.simulated) parts.push(st(lang, 'simulated'));
  return { text: parts.join(' · '), tone };
}

// -- the alert's siren tier -----------------------------------------------------------------------
/** "Sirens 1/1 verified" (and "· 1 started" while some have started but not yet verified), or null. */
export function tierSummary(a: AlertSirenFields | null | undefined, lang: Lang): string | null {
  const n = a?.sirens_total ?? 0;
  if (!n) return null;
  const v = a?.sirens_verified ?? 0;
  const s = a?.sirens_started ?? 0;
  const line = st(lang, 'tier.line', { v, n });
  return s > v ? `${line} · ${st(lang, 'tier.started', { s })}` : line;
}

// -- the two-person reply -------------------------------------------------------------------------
export type SoundOutcome =
  | { kind: 'commanded'; n: number; pattern: string }
  | { kind: 'needs_second'; requestId: string; expiresAt: string };

/** POST /villages/{id}/sirens/sound answers 200 (commanded) or 202 (a second officer must confirm Critical). */
export function readSoundReply(r: SoundReply): SoundOutcome {
  if ('needs_second_officer' in r && r.needs_second_officer && r.request_id) {
    return { kind: 'needs_second', requestId: r.request_id, expiresAt: r.expires_at };
  }
  const c = r as { commanded?: number; pattern?: string };
  return { kind: 'commanded', n: c.commanded ?? 0, pattern: c.pattern ?? '' };
}

export function requestId(r: SirenRequest): string {
  return r.request_id ?? r.id ?? '';
}

// -- audible test window and SMS ------------------------------------------------------------------
/** Audible tests run 09:00 to 18:00 IST only (the server checks too). */
export function audibleAllowed(now: Date = new Date()): boolean {
  const ist = (now.getUTCHours() * 60 + now.getUTCMinutes() + 330) % 1440;
  return ist >= 9 * 60 && ist < 18 * 60;
}

/** An sms: link prefilled with the signed text (RFC 5724): the officer sends it from their own phone. */
export function smsLink(simNumber: string | null | undefined, text: string): string {
  const to = (simNumber ?? '').replace(/[^\d+]/g, '');
  return `sms:${to}?body=${encodeURIComponent(text)}`;
}

// -- calls ----------------------------------------------------------------------------------------
const enc = encodeURIComponent;

export const sirenApi = {
  villageDevices: (villageId: string) => request<VillageDevices>(`/villages/${enc(villageId)}/devices`),
  alertSirens: (alertId: string) => request<SirenTier>(`/alerts/${enc(alertId)}/sirens`),
  test: (deviceId: string, kind: 'silent' | 'audible', reason: string) =>
    request<{ cmd_id: string; pattern: string; kind: string }>(`/devices/${enc(deviceId)}/test`, {
      method: 'POST',
      body: { kind, reason },
    }),
  sound: (villageId: string, level: 'warning' | 'critical', reason: string) =>
    request<SoundReply>(`/villages/${enc(villageId)}/sirens/sound`, { method: 'POST', body: { level, reason } }),
  confirm: (rid: string) =>
    request<{ commanded: number; cmd_ids: string[]; pattern: string }>(`/siren-requests/${enc(rid)}/confirm`, {
      method: 'POST',
      body: {},
    }),
  stop: (villageId: string, reason: string) =>
    request<{ stopped: number; cmd_ids: string[] }>(`/villages/${enc(villageId)}/sirens/stop`, {
      method: 'POST',
      body: { reason },
    }),
  smsFallback: (deviceId: string, cmdId: string) =>
    request<{ text: string; sms_uri: string; sim_number: string | null }>(`/devices/${enc(deviceId)}/sms-fallback`, {
      method: 'POST',
      body: { cmd_id: cmdId },
    }),
};
