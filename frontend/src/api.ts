// Typed client for every route in docs/CONTRACT.md.
import { useAuth, useNet } from './store';
import type {
  Alert,
  AlertAudio,
  AlertDetail,
  AlertStatus,
  ApprovalView,
  AskResponse,
  Audit,
  Backtest,
  CreateReportResponse,
  DevLoginResponse,
  Directive,
  DirectiveType,
  Health,
  Me,
  PublicOverview,
  ReplayStatus,
  Report,
  ReportState,
  Stats,
  TelegramLink,
  TrackView,
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
  devLogin: (username: string) => request<DevLoginResponse>('/auth/dev-login', { method: 'POST', body: { username }, auth: false }),

  villages: () => request<Village[]>('/villages'),
  village: (id: string) => request<VillageDetail>(`/villages/${enc(id)}`),

  alerts: (p: { status?: AlertStatus; village_id?: string } = {}) => request<Alert[]>(`/alerts${qs(p)}`),
  alert: (id: string) => request<AlertDetail>(`/alerts/${enc(id)}`),
  approve: (id: string) => request<Alert>(`/alerts/${enc(id)}/approve`, { method: 'POST', body: {} }),
  decline: (id: string, reason?: string) =>
    request<Alert>(`/alerts/${enc(id)}/decline`, { method: 'POST', body: reason ? { reason } : {} }),
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
  track: (code: string) => request<TrackView>(`/track/${enc(code)}`, { auth: false }),
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

/** Cognito InitiateAuth (USER_PASSWORD_AUTH) by plain fetch. Returns the ID token. */
export async function cognitoSignIn(username: string, password: string): Promise<string> {
  const region = import.meta.env.VITE_COGNITO_REGION;
  const clientId = import.meta.env.VITE_COGNITO_CLIENT_ID;
  let res: Response;
  try {
    res = await fetch(`https://cognito-idp.${region}.amazonaws.com/`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-amz-json-1.1',
        'X-Amz-Target': 'AWSCognitoIdentityProviderService.InitiateAuth',
      },
      body: JSON.stringify({
        AuthFlow: 'USER_PASSWORD_AUTH',
        ClientId: clientId,
        AuthParameters: { USERNAME: username, PASSWORD: password },
      }),
    });
  } catch {
    throw new ApiError(0, null);
  }
  const data = (await res.json().catch(() => ({}))) as {
    AuthenticationResult?: { IdToken?: string };
    ChallengeName?: string;
    message?: string;
  };
  if (!res.ok) throw new ApiError(res.status, data.message ?? 'Sign-in failed.');
  if (data.ChallengeName) throw new ApiError(400, `Cognito asks for ${data.ChallengeName}; finish it in the AWS console first.`);
  const token = data.AuthenticationResult?.IdToken;
  if (!token) throw new ApiError(500, 'Cognito returned no ID token.');
  return token;
}

export const cognitoEnabled = Boolean(import.meta.env.VITE_COGNITO_CLIENT_ID && import.meta.env.VITE_COGNITO_REGION);
