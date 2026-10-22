// Typed client for every route in docs/CONTRACT.md.
import { afterActionPath } from './lib/afterAction';
import { deviceId, sessionId } from './lib/reporter';
import { useAuth, useNet } from './store';
import type {
  AlertOutcome,
  AgentRegistry,
  AgentTrace,
  Alert,
  AlertAudio,
  AlertDetail,
  AlertStatus,
  ApprovalView,
  AskResponse,
  Audit,
  Backtest,
  Checklist,
  CreateReportResponse,
  DevApprovalLink,
  DevLoginResponse,
  Directive,
  DirectiveType,
  GaugeProposal,
  GaugeThresholdSet,
  Health,
  Me,
  PilotMetrics,
  PublicOverview,
  ReplayStatus,
  PushSubscriptionView,
  PushTestResult,
  Report,
  ReportState,
  RollCall,
  RollCallBoard,
  RollCallRemind,
  RosterShift,
  RosterShiftInput,
  RosterView,
  SafeView,
  ShiftId,
  SensorBoard,
  SafePlacesView,
  ShelterState,
  StaffGauge,
  Stats,
  TelegramLink,
  TrackView,
  VapidKey,
  NewStaffGauge,
  Village,
  VillageDetail,
} from './types';

export const API_BASE: string = (import.meta.env.VITE_API_BASE ?? 'http://localhost:8000').replace(/\/$/, '');

/** Error from the API (status > 0) or the network (status 0). */
export class ApiError extends Error {
  status: number;
  detail: unknown;
  code: string | null;
  messageEn: string;
  messageHi: string | null;

  constructor(status: number, detail: unknown) {
    const { code, en, hi } = readDetail(status, detail);
    super(en);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
    this.code = code;
    this.messageEn = en;
    this.messageHi = hi;
  }

  get isNetwork() {
    return this.status === 0;
  }
  get isDenied() {
    return this.status === 403;
  }
  get isLate() {
    return this.status === 409;
  }
  /** 503 {code:"retry"}: the approval workflow was briefly unreachable. */
  get isRetry() {
    return this.status === 503;
  }
}

function readDetail(status: number, detail: unknown): { code: string | null; en: string; hi: string | null } {
  if (status === 0) return { code: 'network', en: 'Cannot reach the Pukaar server.', hi: 'सर्वर से संपर्क नहीं हो पा रहा।' };
  if (typeof detail === 'string' && detail) return { code: null, en: detail, hi: null };
  if (detail && typeof detail === 'object') {
    const d = detail as Record<string, unknown>;
    const en = [d.message_en, d.reason, d.message, d.detail].find((v) => typeof v === 'string' && v) as string | undefined;
    const hi = typeof d.message_hi === 'string' ? d.message_hi : null;
    const code = typeof d.code === 'string' ? d.code : null;
    if (en || hi) return { code, en: en ?? hi ?? '', hi };
    if (Array.isArray(detail) && detail.length) {
      const first = detail[0] as Record<string, unknown>;
      if (typeof first?.msg === 'string') return { code: 'validation', en: first.msg, hi: null };
    }
  }
  return { code: null, en: `Request failed (${status}).`, hi: null };
}

function noteSample(body: unknown) {
  if (!body || typeof body !== 'object') return;
  const flagged = Array.isArray(body)
    ? body.length > 0 && (body[0] as { _sample?: boolean })?._sample === true
    : (body as { _sample?: boolean })._sample === true;
  if (flagged) useNet.getState().markSample();
}

interface RequestOpts {
  method?: string;
  body?: unknown;
  form?: FormData;
  auth?: boolean;
  signal?: AbortSignal;
}

export async function request<T>(path: string, opts: RequestOpts = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' };
  const token = useAuth.getState().token;
  if (token && opts.auth !== false) headers.Authorization = `Bearer ${token}`;
  let body: BodyInit | undefined;
  if (opts.form) body = opts.form;
  else if (opts.body !== undefined) {
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify(opts.body);
  }
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, { method: opts.method ?? 'GET', headers, body, signal: opts.signal });
  } catch (err) {
    if ((err as Error)?.name === 'AbortError') throw err;
    throw new ApiError(0, null);
  }
  const text = await res.text();
  let parsed: unknown = null;
  if (text) {
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = text;
    }
  }
  if (!res.ok) {
    const detail = parsed && typeof parsed === 'object' && 'detail' in parsed ? (parsed as { detail: unknown }).detail : parsed;
    if (res.status === 401 && token) useAuth.getState().signOut();
    throw new ApiError(res.status, detail);
  }
  noteSample(parsed);
  return parsed as T;
}

/** A signed-in GET that returns the body as a Blob (HTML reports): the token rides in a header, never a URL. */
export async function requestBlob(path: string): Promise<Blob> {
  const headers: Record<string, string> = { Accept: 'text/html' };
  const token = useAuth.getState().token;
  if (token) headers.Authorization = `Bearer ${token}`;
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, { headers });
  } catch {
    throw new ApiError(0, null);
  }
  if (!res.ok) {
    let detail: unknown = null;
    try {
      const parsed = JSON.parse(await res.text()) as { detail?: unknown };
      detail = parsed && typeof parsed === 'object' && 'detail' in parsed ? parsed.detail : parsed;
    } catch {
      /* not JSON */
    }
    if (res.status === 401 && token) useAuth.getState().signOut();
    throw new ApiError(res.status, detail);
  }
  return res.blob();
}

function qs(params: Record<string, string | undefined | null>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v) p.set(k, v);
  const s = p.toString();
  return s ? `?${s}` : '';
}

const enc = encodeURIComponent;

export interface NewReport {
  village_id: string;
  text?: string;
  audio?: Blob | null;
  photo?: Blob | null;
  lat?: number | null;
  lon?: number | null;
  reporter_name?: string;
  offline_created?: boolean;
  /** "Compare with the marked rock": the staff gauge and the mark's value the villager chose. */
  staff_gauge_id?: string | null;
  staff_mark?: number | null;
  /** Random ids (lib/reporter.ts); filled in when not given. The server keeps salted hashes only. */
  device_id?: string;
  session_id?: string;
}

/** Multipart body for POST /reports, exactly the CONTRACT field names. */
export function reportForm(r: NewReport): FormData {
  const f = new FormData();
  f.append('village_id', r.village_id);
  if (r.text) f.append('text', r.text);
  if (r.audio) f.append('audio', r.audio, fileName(r.audio, 'voice'));
  if (r.photo) f.append('photo', r.photo, fileName(r.photo, 'photo'));
  if (r.lat != null && r.lon != null) {
    f.append('lat', String(r.lat));
    f.append('lon', String(r.lon));
  }
  if (r.reporter_name) f.append('reporter_name', r.reporter_name);
  if (r.offline_created) f.append('offline_created', 'true');
  if (r.staff_gauge_id && r.staff_mark != null && r.photo) {
    f.append('staff_gauge_id', r.staff_gauge_id);
    f.append('staff_mark', String(r.staff_mark));
  }
  // Lets the server tell two phones apart, so one phone's two reports never confirm each other.
  f.append('device_id', r.device_id ?? deviceId());
  f.append('session_id', r.session_id ?? sessionId());
  return f;
}

function fileName(blob: Blob, base: string): string {
  if (blob instanceof File && blob.name) return blob.name;
  const t = blob.type;
  const ext = t.includes('webm') ? 'webm' : t.includes('ogg') ? 'ogg' : t.includes('mp4') ? 'm4a' : t.includes('jpeg') ? 'jpg' : t.includes('png') ? 'png' : 'bin';
  return `${base}.${ext}`;
}

export const api = {
  health: () => request<Health>('/health'),
  me: () => request<Me>('/me'),
  telegramLink: () => request<TelegramLink>('/me/telegram-link', { method: 'POST', body: {} }),
  vapidKey: () => request<VapidKey>('/push/vapid-public-key', { auth: false }),
  pushSubscriptions: () => request<PushSubscriptionView[]>('/me/push-subscriptions'),
  addPushSubscription: (sub: PushSubscriptionJSON) =>
    request<PushSubscriptionView>('/me/push-subscriptions', { method: 'POST', body: sub }),
  removePushSubscription: (id: string) =>
    request<{ ok: boolean; id: string }>(`/me/push-subscriptions/${enc(id)}`, { method: 'DELETE' }),
  pushTest: () => request<PushTestResult>('/me/push-test', { method: 'POST', body: {} }),
  devLogin: (username: string) => request<DevLoginResponse>('/auth/dev-login', { method: 'POST', body: { username }, auth: false }),

  villages: () => request<Village[]>('/villages'),
  village: (id: string) => request<VillageDetail>(`/villages/${enc(id)}`),
  setChecklist: (villageId: string, item: string, done: boolean) =>
    request<Checklist>(`/villages/${enc(villageId)}/checklist/${enc(item)}`, { method: 'POST', body: { done } }),
  safePlaces: (id: string) => request<SafePlacesView>(`/villages/${enc(id)}/safe-places`, { auth: false }),
  setShelter: (villageId: string, placeId: string, body: { status: ShelterState; capacity?: number | null; note?: string }) =>
    request<SafePlacesView>(`/villages/${enc(villageId)}/shelters/${enc(placeId)}`, { method: 'POST', body }),
  addRoadblock: (villageId: string, body: { lat: number; lon: number; note: string; label?: string }) =>
    request<SafePlacesView>(`/villages/${enc(villageId)}/roadblocks`, { method: 'POST', body }),
  renewRoadblock: (villageId: string, blockId: string) =>
    request<SafePlacesView>(`/villages/${enc(villageId)}/roadblocks/${enc(blockId)}/renew`, { method: 'POST' }),
  clearRoadblock: (villageId: string, blockId: string) =>
    request<SafePlacesView>(`/villages/${enc(villageId)}/roadblocks/${enc(blockId)}/clear`, { method: 'POST' }),
  gaugeProposal: (villageId: string) => request<GaugeProposal>(`/villages/${enc(villageId)}/gauge/proposal`),
  setGaugeThresholds: (villageId: string, t: GaugeThresholdSet & { from_proposal: boolean; note?: string }) =>
    request<{ village_id: string; current: GaugeThresholdSet; previous: GaugeThresholdSet }>(
      `/villages/${enc(villageId)}/gauge/thresholds`,
      { method: 'POST', body: t },
    ),
  staffGauges: (villageId: string) => request<StaffGauge[]>(`/villages/${enc(villageId)}/staff-gauges`, { auth: false }),
  createStaffGauge: (villageId: string, meta: NewStaffGauge, photo: Blob) => {
    const f = new FormData();
    f.append('meta', JSON.stringify(meta));
    f.append('photo', photo, fileName(photo, 'reference'));
    return request<StaffGauge>(`/villages/${enc(villageId)}/staff-gauges`, { method: 'POST', form: f });
  },
  updateStaffGauge: (villageId: string, gaugeId: string, patch: Partial<Pick<StaffGauge, 'name' | 'name_hi' | 'where' | 'watch_at' | 'warning_at' | 'critical_at' | 'active'>>) =>
    request<StaffGauge>(`/villages/${enc(villageId)}/staff-gauges/${enc(gaugeId)}`, { method: 'PATCH', body: patch }),
  confirmStaffReading: (reportId: string, body: { value?: number | null; unreadable?: boolean }) =>
    request<Report>(`/reports/${enc(reportId)}/staff-reading`, { method: 'POST', body }),

  alerts: (p: { status?: AlertStatus; village_id?: string } = {}) => request<Alert[]>(`/alerts${qs(p)}`),
  alert: (id: string) => request<AlertDetail>(`/alerts/${enc(id)}`),
  devApprovalLink: (id: string) => request<DevApprovalLink>(`/dev/approval-link/${enc(id)}`),
  approve: (id: string) => request<Alert>(`/alerts/${enc(id)}/approve`, { method: 'POST', body: {} }),
  /** "Was this real?" after a live alert closed (officer only, Cedar set_alert_outcome). */
  setAlertOutcome: (id: string, outcome: AlertOutcome) =>
    request<Alert>(`/alerts/${enc(id)}/outcome`, { method: 'POST', body: { outcome } }),
  decline: (id: string, reason?: string) =>
    request<Alert>(`/alerts/${enc(id)}/decline`, { method: 'POST', body: reason ? { reason } : {} }),
  afterAction: (id: string) => requestBlob(afterActionPath(id)),
  alertAudio: (id: string) => request<AlertAudio>(`/alerts/${enc(id)}/audio`, { auth: false }),
  ack: (id: string, token: string) =>
    request<{ ok: boolean; acknowledged_at: string }>(`/alerts/${enc(id)}/ack`, { method: 'POST', body: { token }, auth: false }),

  approval: (token: string) => request<ApprovalView>(`/approval/${enc(token)}`, { auth: false }),
  decideApproval: (token: string, decision: 'approve' | 'decline') =>
    request<Alert>(`/approval/${enc(token)}`, { method: 'POST', body: { decision }, auth: false }),

  createReport: (r: NewReport) => request<CreateReportResponse>('/reports', { method: 'POST', form: reportForm(r), auth: false }),
  reports: (p: { village_id?: string; state?: ReportState } = {}) => request<Report[]>(`/reports${qs(p)}`),
  setReportState: (id: string, state: ReportState) =>
    request<Report>(`/reports/${enc(id)}/state`, { method: 'PATCH', body: { state } }),

  directives: (village_id?: string) => request<Directive[]>(`/directives${qs({ village_id })}`),
  createDirective: (d: { village_id: string; type: DirectiveType; note_en?: string }) =>
    request<Directive>('/directives', { method: 'POST', body: d }),

  replayStart: (opts: { scenario?: string; speed_seconds_per_hour?: number } = {}) =>
    request<ReplayStatus>('/replay/start', { method: 'POST', body: opts }),
  replayReset: () => request<ReplayStatus>('/replay/reset', { method: 'POST', body: {} }),
  replayStatus: () => request<ReplayStatus>('/replay/status', { auth: false }),
  audit: (p: { date?: string; resource?: string } = {}) => request<Audit[]>(`/audit${qs(p)}`),
  stats: () => request<Stats>('/stats'),
  ask: (question: string) => request<AskResponse>('/ask/officer', { method: 'POST', body: { question } }),

  overview: () => request<PublicOverview>('/public/overview', { auth: false }),
  pilotMetrics: () => request<PilotMetrics>('/public/pilot-metrics', { auth: false }),
  track: (code: string) => request<TrackView>(`/track/${enc(code)}`, { auth: false }),

  rollcalls: (village_id?: string) => request<RollCall[]>(`/rollcalls${qs({ village_id })}`),
  rollcall: (id: string) => request<RollCallBoard>(`/rollcalls/${enc(id)}`),
  openRollcall: (village_id: string, exercise = false) =>
    request<RollCallBoard>('/rollcalls', { method: 'POST', body: { village_id, exercise } }),
  remindRollcall: (id: string) => request<RollCallRemind>(`/rollcalls/${enc(id)}/remind`, { method: 'POST', body: {} }),
  safe: (token: string) => request<SafeView>(`/safe/${enc(token)}`, { auth: false }),
  agents: () => request<AgentRegistry>('/agents', { auth: false }),
  agentTraces: (limit = 5) => request<AgentTrace[]>(`/agents/traces?limit=${limit}`, { auth: false }),
  sensors: () => request<SensorBoard>('/sensors', { auth: false }),
  // Duty roster (officers only, under Cedar "officer-roster").
  roster: (p: { district?: string; start?: string } = {}) => request<RosterView>(`/roster${qs(p)}`),
  setRosterShift: (district: string, date: string, shift: ShiftId, body: RosterShiftInput) =>
    request<RosterShift>(`/roster/${enc(district)}/${enc(date)}/${shift}`, { method: 'POST', body }),
  clearRosterShift: (district: string, date: string, shift: ShiftId) =>
    request<{ cleared: boolean }>(`/roster/${enc(district)}/${enc(date)}/${shift}`, { method: 'DELETE' }),
  takeOver: (district: string) => request<RosterShift>(`/roster/${enc(district)}/take-over`, { method: 'POST', body: {} }),
};

/** Static back-test results served by the web host, not the API. Null when absent. */
export async function loadBacktest(): Promise<Backtest | null> {
  try {
    const res = await fetch('/backtest.json', { headers: { Accept: 'application/json' } });
    if (!res.ok) return null;
    const type = res.headers.get('content-type') ?? '';
    if (!type.includes('json')) return null;
    const data = (await res.json()) as Backtest;
    return Array.isArray(data?.scenarios) ? data : null;
  } catch {
    return null;
  }
}

/** The hand-kept pilot-readiness checklist, served by the web host (data/pilot_readiness.json). Null when absent. */
export async function loadPilotReadiness(): Promise<unknown> {
  try {
    const res = await fetch('/pilot_readiness.json', { headers: { Accept: 'application/json' } });
    if (!res.ok || !(res.headers.get('content-type') ?? '').includes('json')) return null;
    return await res.json();
  } catch {
    return null;
  }
}

interface CognitoReply {
  AuthenticationResult?: { IdToken?: string };
  ChallengeName?: string;
  ChallengeParameters?: Record<string, string>;
  Session?: string;
  SecretCode?: string;
  Status?: string;
  message?: string;
}

/** One Cognito user-pool call by plain fetch (no SDK). */
async function cognitoCall(target: string, body: Record<string, unknown>): Promise<CognitoReply> {
  const region = import.meta.env.VITE_COGNITO_REGION;
  let res: Response;
  try {
    res = await fetch(`https://cognito-idp.${region}.amazonaws.com/`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-amz-json-1.1',
        'X-Amz-Target': `AWSCognitoIdentityProviderService.${target}`,
      },
      body: JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, null);
  }
  const data = (await res.json().catch(() => ({}))) as CognitoReply;
  if (!res.ok) throw new ApiError(res.status, data.message ?? 'Sign-in failed.');
  return data;
}

function idToken(data: CognitoReply): string {
  const token = data.AuthenticationResult?.IdToken;
  if (!token) throw new ApiError(500, 'Cognito returned no ID token.');
  return token;
}

/**
 * Where a sign-in stands. With MFA (RequireMfa=true on the prod stack, optional on dev) Cognito asks for a
 * code from an authenticator app: `totp` when the account already has one, `setup` the first time (scan
 * `uri` as a QR code, or type `secret`), then cognitoTotp() with the 6-digit code finishes it.
 */
export type CognitoStep =
  | { kind: 'done'; token: string }
  | { kind: 'totp'; username: string; session: string }
  | { kind: 'setup'; username: string; session: string; secret: string; uri: string };

/** Cognito InitiateAuth (USER_PASSWORD_AUTH) by plain fetch: the ID token, or the TOTP step to finish. */
export async function cognitoSignIn(username: string, password: string): Promise<CognitoStep> {
  const clientId = import.meta.env.VITE_COGNITO_CLIENT_ID;
  const data = await cognitoCall('InitiateAuth', {
    AuthFlow: 'USER_PASSWORD_AUTH',
    ClientId: clientId,
    AuthParameters: { USERNAME: username, PASSWORD: password },
  });
  // Cognito's own name for the user (sign-in is case-insensitive) answers each challenge.
  const user = data.ChallengeParameters?.USER_ID_FOR_SRP ?? username;
  if (data.ChallengeName === 'SOFTWARE_TOKEN_MFA' && data.Session) return { kind: 'totp', username: user, session: data.Session };
  if (data.ChallengeName === 'MFA_SETUP' && data.Session) {
    const assoc = await cognitoCall('AssociateSoftwareToken', { Session: data.Session });
    if (!assoc.SecretCode || !assoc.Session) throw new ApiError(500, 'Cognito returned no authenticator key.');
    const uri = `otpauth://totp/Pukaar:${encodeURIComponent(user)}?secret=${assoc.SecretCode}&issuer=Pukaar`;
    return { kind: 'setup', username: user, session: assoc.Session, secret: assoc.SecretCode, uri };
  }
  if (data.ChallengeName) throw new ApiError(400, `Cognito asks for ${data.ChallengeName}; finish it in the AWS console first.`);
  return { kind: 'done', token: idToken(data) };
}

/** Finish a TOTP step with the app's 6-digit code (and, the first time, register the app). Returns the ID token. */
export async function cognitoTotp(step: Exclude<CognitoStep, { kind: 'done' }>, code: string): Promise<string> {
  const clientId = import.meta.env.VITE_COGNITO_CLIENT_ID;
  const digits = code.replace(/\s/g, '');
  if (step.kind === 'totp') {
    return idToken(
      await cognitoCall('RespondToAuthChallenge', {
        ChallengeName: 'SOFTWARE_TOKEN_MFA',
        ClientId: clientId,
        Session: step.session,
        ChallengeResponses: { USERNAME: step.username, SOFTWARE_TOKEN_MFA_CODE: digits },
      }),
    );
  }
  const verified = await cognitoCall('VerifySoftwareToken', { Session: step.session, UserCode: digits, FriendlyDeviceName: 'Pukaar' });
  if (verified.Status !== 'SUCCESS' || !verified.Session) throw new ApiError(400, 'That code did not match. Check the phone clock and try the next code.');
  return idToken(
    await cognitoCall('RespondToAuthChallenge', {
      ChallengeName: 'MFA_SETUP',
      ClientId: clientId,
      Session: verified.Session,
      ChallengeResponses: { USERNAME: step.username },
    }),
  );
}

export const cognitoEnabled = Boolean(import.meta.env.VITE_COGNITO_CLIENT_ID && import.meta.env.VITE_COGNITO_REGION);
