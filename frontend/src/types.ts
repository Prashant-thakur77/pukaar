// Shapes mirror docs/CONTRACT.md. Change the contract first, then this file.

export type Level = 'normal' | 'watch' | 'warning' | 'critical';
export const LEVELS: Level[] = ['normal', 'watch', 'warning', 'critical'];

export type AlertStatus =
  | 'drafting'
  | 'pending'
  | 'approved'
  | 'declined'
  | 'expired'
  | 'delivering'
  | 'delivered'
  | 'auto_sent_unapproved'
  | 'failsafe'
  | 'closed';

export type ReportState =
  | 'received'
  | 'transcribing'
  | 'unverified'
  | 'verified_auto'
  | 'verified'
  | 'reviewed'
  | 'actioned'
  | 'resolved'
  | 'duplicate'
  | 'false';

export type ReportType =
  | 'water_rising'
  | 'road_cut'
  | 'bridge_unsafe'
  | 'landslide'
  | 'homes_affected'
  | 'people_trapped'
  | 'other';

export type Severity = 'low' | 'medium' | 'high' | 'critical';
export type DirectiveType = 'evacuate' | 'shelter_in_place' | 'advisory' | 'all_clear';
export type Role = 'officer' | 'pradhan';

/** Any response may carry `_sample: true` when it comes from the dev mock. */
export interface SampleFlag {
  _sample?: boolean;
}

export interface Thresholds {
  watch: number;
  warning: number;
  critical: number;
  source?: string;
}

export interface Reading {
  village_id: string;
  at: string;
  rain_24h_mm: number | null;
  rain_hourly: { t: string; mm: number }[];
  discharge: number | null;
  discharge_forecast: { date: string; value: number }[];
  discharge_peak: number | null;
  rain_level: Level;
  river_level: Level;
  source: 'open-meteo' | 'replay';
  replay: boolean;
}

export interface Village extends SampleFlag {
  id: string;
  name: string;
  name_hi: string;
  district: string;
  lat: number;
  lon: number;
  coords_verified: boolean;
  population: number | null;
  level: Level;
  level_since: string | null;
  calm_sweeps: number;
  thresholds: Thresholds | null;
  latest_reading: Reading | null;
  open_alert_id: string | null;
  /** True while a replay owns this village's level. */
  replay?: boolean;
}

export interface DraftCheck {
  passed: boolean;
  reason: string;
}

/** decision_trace is produced by services/risk_rules.py; fields are optional on purpose. */
export interface DecisionTrace {
  level?: Level;
  /** Level the rules gave before hysteresis held it up. */
  raw_level?: Level;
  previous_level?: Level;
  hysteresis?: { calm_sweeps: number; needed_to_drop: number };
  rain_level?: Level;
  river_level?: Level;
  report_level?: Level;
  rules_fired?: string[];
  contradictions?: string[];
  evidence?: TraceEvidence[];
  rules_version?: string;
  [key: string]: unknown;
}

export interface TraceEvidence {
  kind: 'reading' | 'report' | string;
  at?: string;
  source?: string;
  rain_24h_mm?: number | null;
  rain_level?: Level;
  rain_bands_mm?: Partial<Record<Level, number>>;
  discharge_peak?: number | null;
  river_level?: Level;
  thresholds?: Thresholds | null;
  report_id?: string;
  type?: ReportType;
  severity?: Severity;
  state?: ReportState;
  verified?: boolean;
  weight?: number;
  replay?: boolean;
  [key: string]: unknown;
}

export interface Alert extends SampleFlag {
  id: string;
  village_id: string;
  village_name: string;
  village_name_hi: string;
  level: Level;
  previous_level: Level;
  status: AlertStatus;
  created_at: string;
  updated_at: string;
  text_hi: string;
  text_en: string;
  reason_en: string;
  reasoning_model: string;
  draft_check: DraftCheck;
  decision_trace: DecisionTrace;
  recipients_count: number;
  officer_index: number;
  decided_by: string | null;
  decided_at: string | null;
  approved: boolean;
  delivered_count: number;
  acknowledged_count: number;
  replay: boolean;
  /** Present on the real backend; false when no Polly MP3 exists (local mode). */
  has_audio?: boolean;
}

export interface Delivery {
  alert_id: string;
  recipient_id: string;
  name: string;
  channel: 'telegram' | 'stub';
  status: string;
  sent_at: string | null;
  attempts: number;
  acknowledged_at: string | null;
  error: string | null;
}

export interface Report extends SampleFlag {
  id: string;
  village_id: string;
  created_at: string;
  text: string;
  transcript: string;
  report_type: ReportType;
  severity: Severity;
  summary_en: string;
  reply_hi: string;
  lat: number | null;
  lon: number | null;
  photo_url: string | null;
  audio_url: string | null;
  state: ReportState;
  previous_state: ReportState | null;
  parser_source: string;
  flags: string[];
  track_code: string;
  replay: boolean;
}

export interface Directive extends SampleFlag {
  id: string;
  village_id: string;
  type: DirectiveType;
  text_hi: string;
  text_en: string;
  issued_by: string;
  issued_at: string;
  active: boolean;
}

export interface Audit {
  at: string;
  id: string;
  actor: string;
  role: string;
  action: string;
  resource: string;
  decision: 'allow' | 'deny';
  reason: string;
}

export interface TimelineEvent {
  at: string;
  step: string;
  detail: string;
}

export interface Health extends SampleFlag {
  status: string;
  mode: 'aws' | 'local';
  /** e.g. "Step Functions" or "local runner (same states as Step Functions)". */
  workflow?: string;
  model?: string;
  services: Partial<Record<'dynamodb' | 'bedrock' | 'polly' | 'transcribe' | 'telegram', string>> & Record<string, unknown>;
  replay_active: boolean;
}

export interface DevApprovalLink {
  url: string;
  token: string;
  officer: string;
}

export interface Me extends SampleFlag {
  username: string;
  role: Role;
  village_ids: string[];
}

export interface DevLoginResponse {
  token: string;
  username: string;
  role: Role;
}

export interface Nowcast {
  likely_level: Level;
  hours: number;
  text_en: string;
  text_hi: string;
}

/** past_events shape is not pinned in CONTRACT.md; render what is present. */
export interface PastEvent {
  date?: string;
  at?: string;
  level?: Level;
  text_en?: string;
  text_hi?: string;
  note_en?: string;
  note_hi?: string;
  title?: string;
  source?: string;
  source_url?: string;
  [key: string]: unknown;
}

export interface VillageDetail extends SampleFlag {
  village: Village;
  readings: Reading[];
  alerts: Alert[];
  reports: Report[];
  past_events: PastEvent[];
  nowcast: Nowcast | null;
  directives?: Directive[];
}

export interface AlertDetail extends SampleFlag {
  alert: Alert;
  deliveries: Delivery[];
  timeline: TimelineEvent[];
  audit: Audit[];
}

export interface ApprovalView extends SampleFlag {
  alert: Alert;
  /** ISO time or epoch seconds. */
  expires_at: string | number;
  officer?: string;
  valid: boolean;
}

export interface AlertAudio {
  url: string | null;
  text_hi: string;
}

export interface CreateReportResponse extends SampleFlag {
  report: Report;
  track_code: string;
}

export interface TelegramLink extends SampleFlag {
  code: string;
  command: string;
  expires_in_seconds: number;
}

export interface ReplayStatus extends SampleFlag {
  active: boolean;
  /** True when the replay worker stopped updating. */
  stale?: boolean;
  started_at?: string | null;
  updated_at?: string | null;
  /** CONTRACT says boolean; the backend sends the list of scenario names. */
  available: boolean | string[];
  clock: string | null;
  hours_total: number;
  hours_done: number;
  source: string | null;
  scenario?: string | null;
  title?: string | null;
  title_hi?: string | null;
}

export interface Stats extends SampleFlag {
  villages_watched: number;
  alerts_sent: number;
  phones_acknowledged: number;
  reports_received: number;
  alerts_by_status: Record<string, number>;
  levels: Record<string, number>;
}

export interface ChartSpec {
  type: 'bar' | 'line';
  title: string;
  x_label: string;
  y_label: string;
  series: { name: string; points: { x: string | number; y: number }[] }[];
}

export interface MapSpec {
  village_ids: string[];
  points: { lat: number; lon: number; label: string }[];
}

export interface ToolCall {
  name: string;
  input: unknown;
  output_summary: string;
  decision: string;
}

export interface AskResponse extends SampleFlag {
  answer: string;
  chart: ChartSpec | null;
  map: MapSpec | null;
  tools: ToolCall[];
  model: string;
}

export interface Counters {
  villages_watched: number;
  alerts_sent: number;
  phones_acknowledged: number;
  reports_received: number;
}

export interface PublicVillage {
  id: string;
  name: string;
  name_hi: string;
  lat: number;
  lon: number;
  level: Level;
  coords_verified: boolean;
}

export interface PublicAlert {
  id: string;
  village_name: string;
  village_name_hi: string;
  level: Level;
  status: AlertStatus;
  created_at: string;
  approved: boolean;
  delivered_count: number;
  acknowledged_count: number;
  replay: boolean;
}

export interface PublicOverview extends SampleFlag {
  counters: Counters;
  villages: PublicVillage[];
  recent_alerts: PublicAlert[];
  replay: { active: boolean };
}

export interface TrackStep {
  key: 'received' | 'verified' | 'acted_on';
  done: boolean;
  at: string | null;
}

export interface TrackView extends SampleFlag {
  code: string;
  village_name: string;
  village_name_hi: string;
  created_at: string;
  report_type: ReportType;
  state: ReportState;
  steps: TrackStep[];
}

/** /backtest.json is copied from data/backtest.json at build time (not in CONTRACT). */
export interface BacktestVillage {
  village_id: string;
  village: string;
  first_watch: string | null;
  first_warning: string | null;
  first_critical: string | null;
  peak_discharge_day: string | null;
  peak_discharge: number | null;
  thresholds: Thresholds | null;
  max_rain_24h_mm: number | null;
  lead_hours_watch_to_peak_day: number | null;
  outcome: string;
}

export interface BacktestScenario {
  name: string;
  title: string;
  title_hi?: string;
  start: string;
  end: string;
  sources?: Record<string, string>;
  villages: BacktestVillage[];
}

export interface Backtest {
  rules?: string;
  scenarios: BacktestScenario[];
}
