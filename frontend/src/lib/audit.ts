import type { Lang } from '../store';
import type { Audit } from '../types';

/*
 * The audit trail (spec 4.11, C27): changes and decisions first, the routine reads hidden and, when shown,
 * repeated reads folded into one line ("judge viewed the roster ×14 · 19:44–23:10"); filters by type, village
 * and person (all kept in the URL); a plain sentence for every action; and a CSV of exactly what is shown.
 */

/** Routine page reads: allowed ones are hidden on /audit unless "Show reads" is on. */
export const ROUTINE_READS = ['view_console', 'read_audit', 'view_reports'] as const;

/** Audit rows name alerts as `alert:<id>`. */
export const alertResource = (alertId: string) => `alert:${alertId}`;
export const auditLinkForAlert = (alertId: string) => `/console/audit?q=${encodeURIComponent(alertResource(alertId))}&all=1`;

/** A bare alert id typed into the filter box is turned into the audit resource. */
export function normaliseResource(q: string): string {
  const s = q.trim();
  return /^alr_[a-z0-9]+$/i.test(s) ? alertResource(s) : s;
}

export const isRoutineRead = (a: Pick<Audit, 'action'>) => (ROUTINE_READS as readonly string[]).includes(a.action);

/** Every read: the console, the trail itself, reports, recipients, rosters, devices, and the health probe. */
export const isRead = (action: string) => /^(view|read)_/.test(action) || action === 'health_deep' || action === 'ask_analyst' || action === 'use_tool';

export interface AuditView {
  rows: Audit[];
  hiddenReads: number;
  denies: number;
}

/** Hides allowed routine reads (denied reads always stay visible) and counts denies. */
export function filterAudit(rows: Audit[], showReads: boolean): AuditView {
  const visible = showReads ? rows : rows.filter((a) => a.decision === 'deny' || !isRoutineRead(a));
  return { rows: visible, hiddenReads: rows.length - visible.length, denies: rows.filter((a) => a.decision === 'deny').length };
}

/* ---------- kinds and words ---------- */

export type AuditKind = 'alerts' | 'reports' | 'field' | 'devices' | 'duty' | 'demo' | 'reads';
export const AUDIT_KINDS: Exclude<AuditKind, 'reads'>[] = ['alerts', 'reports', 'field', 'devices', 'duty', 'demo'];

const KIND: Record<string, AuditKind> = {
  approve: 'alerts', decline: 'alerts', edit_alert: 'alerts', snooze_alert: 'alerts', deliver: 'alerts', auto_send: 'alerts',
  failsafe: 'alerts', all_clear: 'alerts', set_alert_outcome: 'alerts', issue_directive: 'alerts', send_drill: 'alerts',
  set_report_state: 'reports', set_recipient_role: 'reports',
  set_shelter_status: 'field', block_road: 'field', open_rollcall: 'field', remind_rollcall: 'field', tick_checklist: 'field',
  set_gauge_thresholds: 'field', manage_staff_gauge: 'field', confirm_staff_reading: 'field',
  sound_siren: 'devices', stop_siren: 'devices', test_siren: 'devices', manage_device: 'devices', pour_test: 'devices',
  edit_roster: 'duty', take_over_duty: 'duty', subscribe_push: 'duty',
  start_replay: 'demo', dev_link: 'demo',
};

export function auditKind(action: string): AuditKind {
  return isRead(action) ? 'reads' : (KIND[action] ?? 'alerts');
}

/** What was done, in plain words: "मंज़ूर किया" / "approved an alert". */
const WORDS: Record<string, [string, string]> = {
  approve: ['चेतावनी मंज़ूर की', 'approved an alert'],
  decline: ['चेतावनी नामंज़ूर की', 'declined an alert'],
  edit_alert: ['चेतावनी के शब्द बदले', 'changed what an alert says'],
  snooze_alert: ['चेतावनी 10 मिनट के लिए अलग रखी', 'set an alert aside for 10 minutes'],
  deliver: ['चेतावनी भेजी', 'sent an alert'],
  auto_send: ['बिना मंज़ूरी भेजी', 'sent without approval'],
  failsafe: ['सुरक्षा संदेश भेजा', 'sent the failsafe message'],
  all_clear: ['ख़तरा टलने का संदेश भेजा', 'sent the all-clear'],
  set_alert_outcome: ['बताया कि चेतावनी असली थी या नहीं', 'recorded whether an alert was real'],
  issue_directive: ['निर्देश जारी किया', 'issued a directive'],
  send_drill: ['अभ्यास भेजा', 'sent a drill'],
  set_report_state: ['सूचना की स्थिति बदली', 'changed a report’s state'],
  set_recipient_role: ['किसी की भूमिका बदली', 'changed a person’s role'],
  set_shelter_status: ['आश्रय की स्थिति बदली', 'changed a shelter’s status'],
  block_road: ['सड़क बंद या खुली बताई', 'marked a road blocked or open'],
  open_rollcall: ['हाज़िरी शुरू की', 'opened a roll-call'],
  remind_rollcall: ['हाज़िरी की याद दिलाई', 'sent a roll-call reminder'],
  tick_checklist: ['तैयारी की सूची बदली', 'changed the readiness checklist'],
  set_gauge_thresholds: ['गेज की सीमाएँ बदलीं', 'changed gauge thresholds'],
  manage_staff_gauge: ['निशान वाला गेज बदला', 'changed a staff gauge'],
  confirm_staff_reading: ['गेज रीडिंग पक्की की', 'confirmed a gauge reading'],
  sound_siren: ['सायरन बजाया', 'sounded a siren'],
  stop_siren: ['सायरन बंद किया', 'stopped a siren'],
  test_siren: ['सायरन जाँचा', 'tested a siren'],
  manage_device: ['उपकरण की सेटिंग बदली', 'changed a device'],
  pour_test: ['वर्षामापी जाँचा', 'ran a rain-gauge pour test'],
  edit_roster: ['रोस्टर बदला', 'changed the roster'],
  take_over_duty: ['ड्यूटी सँभाली', 'took over a shift'],
  subscribe_push: ['फ़ोन पर सूचना चालू की', 'turned on phone notifications'],
  start_replay: ['रीप्ले चलाया या रोका', 'started or reset a replay'],
  dev_link: ['डेमो मंज़ूरी लिंक खोला', 'opened a demo approval link'],
  view_console: ['कंसोल देखा', 'viewed the console'],
  read_audit: ['ऑडिट देखा', 'read the audit trail'],
  view_reports: ['सूचनाएँ देखीं', 'viewed reports'],
  view_recipients: ['देखा कि चेतावनी किस तक पहुँची', 'viewed who an alert reached'],
  view_rollcall: ['हाज़िरी देखी', 'viewed a roll-call'],
  view_roster: ['रोस्टर देखा', 'viewed the roster'],
  view_devices: ['उपकरण देखे', 'viewed devices'],
  view_after_action: ['बाद की रिपोर्ट देखी', 'viewed an after-action report'],
  view_gauge_proposal: ['गेज का प्रस्ताव देखा', 'viewed a gauge proposal'],
  health_deep: ['सिस्टम जाँचा', 'checked the system'],
  ask_analyst: ['पुकार से पूछा', 'asked Pukaar'],
  use_tool: ['एजेंट ने औज़ार चलाया', 'an agent used a tool'],
};

export function actionWords(action: string, lang: Lang): string {
  const w = WORDS[action];
  return w ? w[lang === 'hi' ? 0 : 1] : action.replace(/_/g, ' ');
}

/** "village:gohar" -> gohar; an alert's village from the alerts the console knows. */
export function villageOf(row: Pick<Audit, 'resource'>, alertVillage: (alertId: string) => string | undefined): string | null {
  const [type, id = ''] = row.resource.split(/:(.*)/);
  if (type === 'village') return id;
  if (type === 'alert') return alertVillage(id) ?? null;
  return null;
}

/* ---------- filters (all in the URL) ---------- */

export interface AuditFilters {
  /** "Changes and decisions" (the default): reads hidden. */
  all: boolean;
  kind: AuditKind | 'denied' | '';
  village: string;
  person: string;
  q: string;
}

export function readFilters(p: URLSearchParams): AuditFilters {
  const kind = p.get('type') ?? '';
  return {
    all: p.get('all') === '1',
    kind: ([...AUDIT_KINDS, 'denied'] as string[]).includes(kind) ? (kind as AuditFilters['kind']) : '',
    village: p.get('village') ?? '',
    person: p.get('person') ?? '',
    q: normaliseResource(p.get('q') ?? p.get('resource') ?? ''),
  };
}

export function writeFilters(f: AuditFilters, date: string): Record<string, string> {
  const out: Record<string, string> = {};
  if (f.all) out.all = '1';
  if (f.kind) out.type = f.kind;
  if (f.village) out.village = f.village;
  if (f.person) out.person = f.person;
  if (f.q) out.q = f.q;
  if (date) out.date = date;
  return out;
}

export function applyFilters(rows: Audit[], f: AuditFilters, alertVillage: (alertId: string) => string | undefined): { rows: Audit[]; hiddenReads: number } {
  let hiddenReads = 0;
  const out = rows.filter((r) => {
    if (f.q && !r.resource.includes(f.q)) return false;
    if (f.person && r.actor !== f.person) return false;
    if (f.village && villageOf(r, alertVillage) !== f.village) return false;
    if (f.kind === 'denied' && r.decision !== 'deny') return false;
    if (f.kind && f.kind !== 'denied' && auditKind(r.action) !== f.kind) return false;
    // A denied read is never routine: it stays in "changes and decisions".
    if (!f.all && isRead(r.action) && r.decision === 'allow') {
      hiddenReads++;
      return false;
    }
    return true;
  });
  return { rows: out, hiddenReads };
}

/* ---------- repeated reads, folded ---------- */

export interface AuditLine {
  key: string;
  row: Audit;
  /** How many identical rows in a row (1 for a single). */
  count: number;
  /** The span they cover, oldest to newest. */
  from: string;
  to: string;
  rows: Audit[];
}

/**
 * Folds runs of the same event (same person, action, resource and decision) into one line: the reads, and repeats
 * such as a siren tested again and again. A decision about an alert never folds: each one stands on its own line.
 */
export function groupReads(rows: Audit[]): AuditLine[] {
  const out: AuditLine[] = [];
  for (const r of rows) {
    const last = out[out.length - 1];
    const same =
      last && auditKind(r.action) !== 'alerts' && last.row.actor === r.actor && last.row.action === r.action && last.row.resource === r.resource && last.row.decision === r.decision;
    if (same) {
      last.count++;
      last.rows.push(r);
      if (r.at < last.from) last.from = r.at;
      if (r.at > last.to) last.to = r.at;
    } else out.push({ key: r.id, row: r, count: 1, from: r.at, to: r.at, rows: [r] });
  }
  return out;
}

/* ---------- CSV ---------- */

const cell = (s: string) => (/[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s);

export function auditCsv(rows: Audit[]): string {
  const head = ['at', 'actor', 'role', 'action', 'resource', 'decision', 'reason'];
  return [head.join(','), ...rows.map((r) => [r.at, r.actor, r.role, r.action, r.resource, r.decision, r.reason].map((v) => cell(String(v ?? ''))).join(','))].join('\n') + '\n';
}
