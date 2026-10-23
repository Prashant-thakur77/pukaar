// Reach, enrolment and the duty officer: the client for backend api/routers/reach.py (docs/CONTRACT.md), and the
// pure helpers the console pages use (tested in reach.test.ts).
import { request } from '../api';
import type { Level } from '../types';

const enc = encodeURIComponent;

/* ---------- grouped approval ---------- */

export interface GroupVillage {
  alert_id: string;
  village_id: string;
  village_name: string;
  village_name_hi: string;
  level: Level;
  previous_level: Level;
  text_hi: string;
  text_en: string;
  reason_en: string;
  created_at: string;
  recipients_count: number;
  drivers: Record<string, Level>;
  status: string;
}

export interface AlertGroup {
  id: string;
  key: string;
  district: string;
  stream: 'live' | 'replay' | 'drill';
  replay: boolean;
  cause: string;
  cause_en: string;
  cause_hi: string;
  count: number;
  shared: {
    drivers: string[];
    drivers_en: string[];
    drivers_hi: string[];
    rules: string[];
    official: { source: string; name: string; status: string; level?: Level | null; detail?: string }[];
    levels: Partial<Record<Level, number>>;
    first_at: string;
    last_at: string;
  };
  villages: GroupVillage[];
}

export type GroupOutcome = 'decided' | 'denied' | 'late' | 'retry' | 'missing';

export interface GroupResult {
  alert_id: string;
  village_id?: string;
  village_name?: string;
  decision: 'approved' | 'declined';
  outcome: GroupOutcome;
  reason?: string;
}

/** One decision per village: approved unless the officer marked it declined. */
export function groupDecisions(villages: Pick<GroupVillage, 'alert_id'>[], declined: ReadonlySet<string>) {
  return villages.map((v) => ({ alert_id: v.alert_id, decision: declined.has(v.alert_id) ? ('declined' as const) : ('approved' as const) }));
}

/** The query that names a group in the console URL (district, cause, stream). */
export function groupPath(g: Pick<AlertGroup, 'district' | 'cause' | 'stream'>): string {
  return `/console/group?${new URLSearchParams({ d: g.district, c: g.cause, s: g.stream }).toString()}`;
}

export function findGroup(groups: AlertGroup[], d: string | null, c: string | null, s: string | null): AlertGroup | null {
  return groups.find((g) => g.district === d && g.cause === c && g.stream === s) ?? null;
}

/* ---------- SACHET out ---------- */

export interface SachetLimit {
  chars: number;
  pages: number;
  encoding: string;
  max_chars: number;
}

export interface SachetPackage {
  alert_id: string;
  identifier: string;
  cap_xml: string;
  filename: string;
  text_hi: string;
  text_en: string;
  limits: { hi: SachetLimit; en: SachetLimit; target_pages: number; max_pages: number; page: string };
  radius_km: number;
  polygon: [number, number][];
  steps_en: string[];
  steps_hi: string[];
  mailto: string;
  email_to: string;
  exercise: boolean;
  not_sent_en: string;
  not_sent_hi: string;
}

export type SachetVia = 'view' | 'download' | 'copy' | 'email';

const SENT = new Set(['approved', 'delivering', 'delivered', 'auto_sent_unapproved', 'failsafe']);

/** The button shows on a published (approved, auto-sent or failsafe) Warning or Critical alert. */
export function canRequestSachet(a: { level: Level; status: string; approved?: boolean }): boolean {
  if (a.level !== 'warning' && a.level !== 'critical') return false;
  return SENT.has(a.status) || (a.status === 'closed' && Boolean(a.approved));
}

/** The texts to paste into an e-mail or SACHET's composer. */
export function sachetClipboard(p: SachetPackage): string {
  return [
    `Hindi (cell broadcast, ${p.limits.hi.pages} page${p.limits.hi.pages === 1 ? '' : 's'}):`,
    p.text_hi,
    '',
    `English (cell broadcast, ${p.limits.en.pages} page${p.limits.en.pages === 1 ? '' : 's'}):`,
    p.text_en,
    '',
    `Area: ${p.radius_km} km polygon around the village (in ${p.filename}).`,
    '',
    ...p.steps_en.map((s, i) => `${i + 1}. ${s}`),
    '',
    p.not_sent_en,
  ].join('\n');
}

/* ---------- enrolment ---------- */

export interface Household {
  id: string;
  village_id: string;
  name: string;
  role: string;
  channel: string;
  relay: boolean;
  phone_masked: string | null;
  assisted: boolean;
  consent: string | null;
  enrolled_via: string | null;
  enrolled_by: string | null;
}

export interface HouseholdList {
  village_id: string;
  village_name: string;
  village_name_hi: string;
  ivr_code: string | null;
  households: Household[];
  consent_methods: Record<string, string>;
  given_by: Record<string, string>;
  notice_version: string;
}

export interface ConsentInput {
  method: string;
  given_by: string;
  taken_by: string;
  date: string;
}

export interface HouseholdInput {
  recipient_id?: string;
  name?: string;
  phone?: string;
  channel?: string;
  role?: string;
  assisted?: boolean;
  consent?: ConsentInput;
}

export interface ImportRow {
  row: number;
  name: string;
  phone_masked: string;
  channel: string;
  role: string;
  assisted: boolean;
  status: 'ok' | 'duplicate' | 'exists' | 'error';
  errors: string[];
  duplicate_of: number | null;
  existing_id: string | null;
  consent_method: string;
  consent_given_by: string;
  consent_date: string;
}

export interface ImportPreview {
  rows: ImportRow[];
  counts: Record<'ok' | 'duplicate' | 'exists' | 'error', number>;
  result?: { stored: { row: number; recipient_id: string }[]; skipped: { row: number; reason: string }[]; rows: number };
}

/** Only rows that passed every check can be attested; anything else is never stored. */
export function attestable(rows: ImportRow[]): number[] {
  return rows.filter((r) => r.status === 'ok').map((r) => r.row);
}

/** Today in India (the consent date a form defaults to). */
export function todayIst(now: Date = new Date()): string {
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kolkata' }).format(now);
}

/* ---------- the duty officer ---------- */

export interface HandoverNote {
  district: string;
  date: string;
  shift: 'day' | 'night';
  text: string;
  written_by: string;
  written_at: string;
  for_date: string;
  for_shift: 'day' | 'night';
  acknowledged_by: string | null;
  acknowledged_at: string | null;
}

export interface HandoverView {
  district: string;
  shift: { date: string; shift: 'day' | 'night'; label: string };
  next: { date: string; shift: 'day' | 'night'; label: string };
  previous: { date: string; shift: 'day' | 'night'; label: string };
  outgoing: HandoverNote | null;
  incoming: HandoverNote | null;
  history: HandoverNote[];
}

export interface DutyDigest {
  district: string;
  at: string;
  text: string;
  sweep: { last_run: string | null; last_complete_data: string | null; villages: number; stale: { village_id: string; name: string; status: string }[] };
  gauges_unhealthy: { device_id: string; installed: boolean; reasons: string[] }[];
  sirens_unhealthy: { device_id: string; state: string; simulated: boolean; test_overdue: boolean }[];
  open_alerts: { alert_id: string; village_name: string; level: Level; status: string }[];
  gaps: { kind: string; en: string; hi: string }[];
}

/* ---------- the client ---------- */

export const reachApi = {
  groups: (district?: string) => request<AlertGroup[]>(`/alert-groups${district ? `?district=${enc(district)}` : ''}`),
  decideGroup: (body: { decisions: { alert_id: string; decision: 'approved' | 'declined' }[]; reason?: string; group_id?: string }) =>
    request<{ results: GroupResult[]; decided: number }>('/alert-groups/decide', { method: 'POST', body }),
  sachet: (alertId: string, via: SachetVia, radius_km?: number) =>
    request<SachetPackage>(`/alerts/${enc(alertId)}/sachet-request`, { method: 'POST', body: { via, ...(radius_km ? { radius_km } : {}) } }),
  households: (villageId: string) => request<HouseholdList>(`/villages/${enc(villageId)}/households`),
  saveHousehold: (villageId: string, body: HouseholdInput) =>
    request<{ household: Household; created: boolean }>(`/villages/${enc(villageId)}/households`, { method: 'POST', body }),
  removeHousehold: (villageId: string, id: string, reason = '') =>
    request<{ removed: boolean }>(`/villages/${enc(villageId)}/households/${enc(id)}${reason ? `?reason=${enc(reason)}` : ''}`, { method: 'DELETE' }),
  importHouseholds: (
    villageId: string,
    body: { csv: string; commit?: boolean; source?: string; attested_rows?: number[]; attestation?: Partial<ConsentInput> },
  ) => request<ImportPreview>(`/villages/${enc(villageId)}/households/import`, { method: 'POST', body }),
  digest: (district: string) => request<DutyDigest>(`/duty/digest?district=${enc(district)}`),
  handover: (district: string) => request<HandoverView>(`/duty/handover?district=${enc(district)}`),
  writeHandover: (district: string, text: string) =>
    request<HandoverView>(`/duty/handover/${enc(district)}`, { method: 'POST', body: { text } }),
  ackHandover: (district: string, date: string, shift: string) =>
    request<HandoverView>(`/duty/handover/${enc(district)}/${enc(date)}/${enc(shift)}/ack`, { method: 'POST', body: {} }),
};

/** Save text as a file (the CAP request) without leaving the page. */
export function saveFile(name: string, text: string, type = 'application/xml'): void {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
