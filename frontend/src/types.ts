import type { HealthSignals } from './lib/deviceHealth';
// Shapes mirror docs/CONTRACT.md. Change the contract first, then this file.
import type { AlertSirenFields, PublicDevice, SirenTier, VillageSirens } from './lib/sirens';

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
  /** "return_period": watch, warning, critical are the 2-, 5- and 20-year discharges. */
  method?: string;
  return_period_years?: { watch: number; warning: number; critical: number } | null;
  /** Get-ready line: the 90th percentile of daily flow at the river cell. Never a level. */
  early?: number | null;
  river?: string | null;
  cell_verified?: boolean;
  cell_lat?: number | null;
  cell_lon?: number | null;
}

/** One official source beside the level (services/official_data.py). Evidence only. */
export interface OfficialItem {
  source: 'cwc' | 'imd' | 'flood_hub' | 'bipad' | string;
  name: string;
  status: 'ok' | 'unavailable' | 'off';
  level?: Level | null;
  detail?: string;
  error?: string;
  /** CWC: stations above warning level in India, and whether this village has codes mapped. */
  stations_above_warning?: number;
  matched?: unknown[];
  mapped?: boolean;
  /** IMD: the district colour for today and tomorrow. */
  colour?: 'none' | 'green' | 'yellow' | 'orange' | 'red' | string;
  issued?: string;
  gauges?: unknown[];
  readings?: unknown[];
}

/** Share of ensemble members at or above each threshold, one lead day. */
export interface EnsembleDay {
  date: string;
  lead: number;
  members: number;
  p: { watch: number; warning: number; critical: number };
}

/** GET /villages/{id} river: the return-period lines, the early line and the ensemble's odds. */
export interface RiverView {
  level: Level;
  mode: 'ensemble' | 'deterministic' | 'none';
  p_min: number;
  ensemble_status: 'ok' | 'unavailable' | 'off' | null;
  p_max?: { watch: number; warning: number; critical: number } | null;
  members?: number | null;
  lead_days: EnsembleDay[];
  run_date?: string | null;
  today?: number | null;
  peak?: number | null;
  thresholds: Thresholds;
  at: string | null;
  replay?: boolean;
}

export interface Reading {
  village_id: string;
  at: string;
  rain_24h_mm: number | null;
  rain_hourly: { t: string; mm: number }[];
  discharge: number | null;
  discharge_forecast: { date: string; value: number }[];
  discharge_peak: number | null;
  /** Daily discharge from today up to 7 days ahead (the "get ready" outlook). */
  discharge_outlook?: { date: string; value: number }[];
  /** Root-zone soil moisture now (m³/m³), mean of the 9-27 and 27-81 cm layers. */
  soil_moisture_root?: number | null;
  rain_level: Level;
  river_level: Level;
  source: 'open-meteo' | 'replay';
  replay: boolean;
  /** Official sources (CWC, IMD, Flood Hub, BIPAD): evidence, never lowers a level. */
  official?: OfficialItem[];
  discharge_ensemble?: { status: string; members?: number; run_date?: string } | null;
}

export interface SoilRange {
  dry: number;
  wet: number;
  source?: string;
}

/** Soft "get ready" outlook: the river flow for day 1-7 at or over the early line. Never changes the level. */
export interface Readiness {
  state: 'none' | 'get_ready';
  available?: boolean;
  horizon_days: number | null;
  peak_day: string | null;
  peak_vs_watch_ratio: number | null;
  peak_vs_early_ratio?: number | null;
  peak_discharge?: number | null;
  watch?: number | null;
  /** The early line (m³/s): 90th percentile of daily flow at the river cell. */
  early?: number | null;
  line?: 'early' | 'watch';
  basis?: 'ensemble_median' | 'single_forecast' | 'mixed' | null;
  first_day_over?: string | null;
  days_over?: number;
  reaches_watch?: boolean;
  source: string;
  window_days?: [number, number];
  days?: { date: string; days_ahead: number; value: number; basis?: string; over?: boolean }[];
  never_sets_level?: boolean;
  from_reading?: string | null;
  replay?: boolean;
}

/** Soil-moisture state for the evidence card (services/soil.py). */
export interface SoilView {
  moisture_root: number | null;
  saturation: number | null;
  dry: number;
  wet: number;
  range_source: string;
  calibrated: boolean;
  factor: number;
  factor_if_on: number;
  enabled: boolean;
  applied: boolean;
  state: 'no_reading' | 'off' | 'applied' | 'below_threshold';
  saturated_at: number;
  at: string | null;
  replay?: boolean;
}

export interface ChecklistItem {
  village_id: string;
  item: string;
  label_en: string;
  label_hi: string;
  order: number;
  done: boolean;
  done_by: string | null;
  done_at: string | null;
}

export interface Checklist {
  items: ChecklistItem[];
  done: number;
  total: number;
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
  soil?: SoilRange | null;
  readiness?: Readiness | null;
  /** True while a replay owns this village's level. */
  replay?: boolean;
  /** The live level, always: `level` shows a replay's level only while the live one is Normal. */
  live_level?: Level;
  live_level_since?: string | null;
  replay_level?: Level | null;
  /** Forecast data freshness: "stale" carries the last complete values forward; "unavailable" holds the level. */
  data_status?: DataStatus;
  data_ok_at?: string | null;
  data_missing_sweeps?: number;
  data_note?: string;
}

export type DataStatus = 'ok' | 'stale' | 'unavailable';

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
  gauge_level?: Level;
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

export interface Alert extends SampleFlag, AlertSirenFields {
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
  /** "Was this real?", set by an officer after the alert closed (POST /alerts/{id}/outcome). */
  outcome?: AlertOutcome | null;
  outcome_by?: string | null;
  outcome_at?: string | null;
}

export type AlertOutcome = 'real_flood' | 'no_flood' | 'unknown';

export interface Delivery {
  alert_id: string;
  recipient_id: string;
  name: string;
  channel: 'telegram' | 'stub' | 'voice';
  status: string;
  sent_at: string | null;
  attempts: number;
  acknowledged_at: string | null;
  error: string | null;
  /** Set when the person is a village relay, contacted first (GET /alerts/{id}). */
  relay_role?: RelayRole | null;
  /** The all-clear on this row's channel, once the alert was stood down. */
  all_clear_status?: 'sent' | 'failed' | 'stub' | null;
  all_clear_at?: string | null;
}

export type RelayRole = 'pradhan' | 'gauge_reader' | 'task_force';

// -- duty roster (GET /roster) --------------------------------------------------------------------
export type ShiftId = 'day' | 'night';
export type EscalationTitle = 'ADM' | 'DM';

export interface RosterShift {
  district: string;
  date: string;
  shift: ShiftId;
  primary: string;
  backup: string | null;
  escalation: string | null;
  escalation_title: EscalationTitle;
  note: string;
  updated_by: string;
  updated_at: string;
  taken_over_from: string | null;
  taken_over_at: string | null;
}

export interface RosterSlot {
  starts_at: string;
  ends_at: string;
  entry: RosterShift | null;
}

export interface RosterDay {
  date: string;
  weekday: string;
  shifts: Record<ShiftId, RosterSlot>;
}

export interface OnDuty {
  district: string;
  date: string;
  shift: ShiftId;
  starts_at: string;
  ends_at: string;
  source: 'roster' | 'fallback' | 'none';
  chain: string[];
  roles: string[];
  primary: string | null;
  backup: string | null;
  escalation: string | null;
  escalation_title: EscalationTitle | null;
  taken_over_from: string | null;
  taken_over_at: string | null;
}

export interface RosterView extends SampleFlag {
  district: string;
  districts: string[];
  timezone: string;
  shifts: { id: ShiftId; start: string; end: string }[];
  start: string;
  days: RosterDay[];
  now: OnDuty[];
  officers: string[];
  critical_auto_send: boolean;
  critical_auto_send_label: string;
  approval_timeout_seconds: number;
  /** A Critical's approval window per officer (PUKAAR_APPROVAL_TIMEOUT_CRITICAL_SECONDS), when sent. */
  approval_timeout_critical_seconds?: number;
  /** When the reminder and wake-up call go to an officer who has not opened the link, when sent. */
  officer_wake_seconds?: number;
}

export interface RosterShiftInput {
  primary: string;
  backup?: string | null;
  escalation?: string | null;
  escalation_title: EscalationTitle;
  note?: string;
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
  /** What the guardrail said about the words; null on reports from before screening. */
  screen?: ReportScreen | null;
  /** Held for review: the guardrail stopped the words, or it came in over a rate limit; only an officer can verify it. */
  held?: boolean;
  /** Why it is held when it came in over a rate limit: source_rate_limit or village_surge (backend report_guard.py). */
  hold_reason?: string | null;
  /** "Compare with the marked rock": the mark the villager chose, and the officer's check. */
  staff_reading?: StaffReading | null;
  /** Public pages get the coarse facts only: no words, GPS or media, just whether they were sent. */
  has_location?: boolean;
  has_photo?: boolean;
  has_audio?: boolean;
}

export interface ReportScreen {
  allowed: boolean;
  action: string;
  /** prompt_attack, instruction_to_system, hate, insults, violence, misconduct, pii:phone, ... */
  reasons: string[];
  engine: 'bedrock-guardrail' | 'local-heuristic';
  at: string;
  field: 'text' | 'transcript';
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
  source?: 'rain' | 'river';
  /** "ensemble": a share of the GloFAS members agrees; "single_forecast": one forecast, no ensemble. */
  basis?: 'ensemble' | 'single_forecast';
  p?: number | null;
  members?: number | null;
  agree?: number | null;
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

/** Village river gauge (services/gauge.py). Thresholds are stage in cm above the gauge zero. */
export interface GaugeConfig {
  device_id: string;
  watch_cm: number;
  warning_cm: number;
  critical_cm: number;
  installed: boolean;
  note?: string;
  /** Where the stage thresholds came from: seeded, learned from the record, or set by hand. */
  thresholds_source?: string;
  thresholds_set_by?: string | null;
  thresholds_set_at?: string | null;
}

/* ---------- learned gauge thresholds (services/gauge_learn.py) ---------- */

export interface GaugeFault {
  kind: 'flatline' | 'jump' | 'clock_offset' | 'clock_drift' | 'battery_trend' | 'battery_low' | 'gaps' | string;
  severity: 'warn' | 'info';
  count: number;
  first_at: string | null;
  last_at: string | null;
  value: number | null;
  message_en: string;
  message_hi: string;
}

export interface GaugeThresholdSet {
  watch_cm: number;
  warning_cm: number;
  critical_cm: number;
}

export interface GaugeProposal {
  village_id: string;
  device_id: string;
  status: 'ready' | 'insufficient';
  basis: {
    readings: number;
    days: number;
    from: string | null;
    to: string | null;
    min_days: number;
    min_readings: number;
    simulated: boolean;
    used?: number;
    excluded?: number;
  };
  current: (GaugeThresholdSet & { source: string; set_by: string | null; set_at: string | null }) | null;
  faults: GaugeFault[];
  percentiles: { watch: number; warning: number; critical: number };
  never_auto_applied: true;
  note_en?: string;
  note_hi?: string;
  baseline_cm?: number;
  baseline_rule?: string;
  min_separation_cm?: number;
  raw?: { watch: number; warning: number; critical: number };
  proposed?: GaugeThresholdSet;
  adjustments?: { level: 'watch' | 'warning' | 'critical'; from: number; to: number; rule: string }[];
  curve?: { p: number; cm: number }[];
  daily?: { date: string; min: number; median: number; max: number }[];
}

/* ---------- virtual staff gauges (services/staff_gauge.py) ---------- */

export interface StaffPoint {
  x: number;
  y: number;
}

export interface StaffMark extends StaffPoint {
  label: string;
  value: number;
  height_cm?: number | null;
}

export interface StaffGauge {
  id: string;
  village_id: string;
  name: string;
  name_hi: string;
  where: string;
  photo_url: string | null;
  scale_top: StaffPoint;
  scale_bottom: StaffPoint;
  unit: 'class' | 'cm';
  marks: StaffMark[];
  watch_at: number | null;
  warning_at: number | null;
  critical_at: number | null;
  active: boolean;
  created_by: string;
  created_at: string;
  vision_note_en: string;
  vision_note_hi: string;
}

export interface NewStaffGauge {
  name: string;
  name_hi?: string;
  where?: string;
  scale_top: StaffPoint;
  scale_bottom: StaffPoint;
  unit: 'class' | 'cm';
  marks: StaffMark[];
  watch_at?: number | null;
  warning_at?: number | null;
  critical_at?: number | null;
}

export interface StaffReading {
  gauge_id: string;
  gauge_name: string;
  mark: string;
  value: number;
  height_cm?: number | null;
  chosen_at: string;
  status: 'unconfirmed' | 'confirmed' | 'unreadable';
  confirmed_mark?: string | null;
  confirmed_value?: number | null;
  confirmed_height_cm?: number | null;
  confirmed_level?: Level | null;
  confirmed_by?: string | null;
  confirmed_at?: string | null;
}

/** Public village page: mark, time, whether an officer confirmed it (no names). */
export interface PublicStaffReading {
  report_id: string;
  gauge_id: string;
  gauge_name: string;
  at: string;
  mark: string;
  villager_mark: string;
  status: StaffReading['status'];
  level: Level | null;
  confirmed_at: string | null;
  replay: boolean;
}

export interface StaffGaugesView {
  gauges: StaffGauge[];
  readings: PublicStaffReading[];
}

export interface SensorReading {
  village_id: string;
  device_id: string;
  at: string;
  water_level_cm: number;
  rain_mm_1h?: number | null;
  battery_v?: number | null;
  rssi?: number | null;
  /** True for the labelled simulator; never real hardware. */
  simulated: boolean;
  received_at?: string | null;
  origin?: 'live' | 'backfill';
  /** Set at ingest: only "good" readings count toward a level. */
  quality?: GaugeQuality;
  quality_reasons?: string[];
  /** This reading's stage band on its own. */
  measured_level?: Level | null;
  /** 2 of the last 3 good live readings at or above. */
  confirmed_level?: Level | null;
  rising_fast?: boolean;
  rise_cm?: number | null;
}

export type GaugeQuality = 'good' | 'suspect' | 'spike' | 'out_of_range';

/** Gauge health from its last 24 h (services/gauge.py health). */
export interface GaugeHealth {
  status: 'ok' | 'gauge_unhealthy';
  unhealthy: boolean;
  reasons: ('silent' | 'low_battery' | 'bad_quality' | string)[];
  last_seen: string | null;
  minutes_since: number | null;
  silent_after_minutes?: number;
  battery_v: number | null;
  battery_low: boolean;
  readings_24h: number;
  bad_24h: number;
  bad_share_24h: number | null;
  by_quality?: Record<string, number>;
  backfilled_24h?: number;
  /** FloodNet checks (services/devices/floodnet.py): battery slope, packet loss, stuck values. */
  signals?: HealthSignals;
}

export interface GaugeView {
  config: GaugeConfig;
  latest: SensorReading | null;
  /** Latest reading is recent enough (fresh_minutes) to count in the rules. */
  fresh: boolean;
  fresh_minutes: number;
  /** The level the rules count: 2 of the last 3 good readings, one step up when rising fast. */
  level: Level | null;
  /** The newest reading's band on its own. */
  measured_level?: Level | null;
  rising_fast?: boolean;
  health?: GaugeHealth | null;
  series: { at: string; cm: number; q?: string; backfill?: boolean }[];
}

export interface VillageDetail extends SampleFlag {
  village: Village;
  readings: Reading[];
  alerts: Alert[];
  reports: Report[];
  past_events: PastEvent[];
  nowcast: Nowcast | null;
  directives?: Directive[];
  gauge?: GaugeView | null;
  soil?: SoilView | null;
  river?: RiverView | null;
  checklist?: Checklist | null;
  /** An open safety roll-call: counts only, never names. */
  rollcall?: PublicRollCall | null;
  /** Virtual staff gauges: reference photos with their scales, and recent readings. */
  staff_gauges?: StaffGaugesView | null;
  /** The village's sirens: count and last test only (no ids, numbers or keys). */
  sirens?: VillageSirens | null;
}

/** "Surakshit Hoon" safety roll-call, public shape: counts only. */
export interface PublicRollCall {
  open: boolean;
  exercise: boolean;
  asked: number;
  safe: number;
  need_help: number;
  not_answered: number;
  opened_at: string;
  closes_at: string;
}

export interface RollCall extends SampleFlag {
  id: string;
  village_id: string;
  village_name: string;
  village_name_hi: string;
  alert_id: string | null;
  level: Level | null;
  opened_at: string;
  closes_at: string;
  opened_by: 'system' | 'officer';
  opened_by_user: string | null;
  exercise: boolean;
  asked: number;
  safe: number;
  need_help: number;
  not_answered: number;
  open: boolean;
  last_reminded_at: string | null;
  reminders: number;
}

/** Officer board: names and times only (no phone numbers or chat ids). */
export interface RollCallBoard extends SampleFlag {
  rollcall: RollCall;
  need_help: { name: string; at: string; note: string | null; simulated: boolean }[];
  safe: { name: string; at: string; simulated: boolean }[];
  not_answered: { name: string; demo: boolean; asked_at: string; reminded_at: string | null; failed: boolean }[];
  remind_every_seconds: number;
}

export interface RollCallRemind {
  reminded: number;
  waiting: number;
  demo_without_phone: number;
  last_reminded_at: string | null;
  board: RollCallBoard;
}

/** GET /safe/{token}: what a family link shows. */
export interface SafeView extends SampleFlag {
  first_name: string | null;
  village_name: string;
  village_name_hi: string;
  at: string;
  status: 'safe';
  exercise: boolean;
  simulated: boolean;
}

export interface AlertDetail extends SampleFlag {
  alert: Alert;
  deliveries: Delivery[];
  timeline: TimelineEvent[];
  audit: Audit[];
  /** The siren tier, kept apart from people reached. */
  sirens?: SirenTier;
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

/** GET /push/vapid-public-key: the applicationServerKey (null until `make vapid-keys` ran). */
export interface VapidKey {
  key: string | null;
  configured: boolean;
}

/** One of the signed-in user's Web Push subscriptions (never the endpoint or keys). */
export interface PushSubscriptionView {
  id: string;
  user_agent: string;
  created_at: string;
  last_sent_at: string | null;
}

export interface PushTestResult {
  sent: number;
  failed: number;
  removed: number;
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

export interface Stats extends SampleFlag, Counters {
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

/** Public counters, each counted from stored records (docs/CONTRACT.md "Counters"). */
export interface Counters {
  villages_watched: number;
  /** Live flood alerts that went out. Never replays, never drills. */
  alerts_sent: number;
  /** "मिल गया" taps on those live alerts. */
  phones_acknowledged: number;
  reports_received: number;
  /** Drill alerts (labelled tests) that reached at least one real phone. */
  drills_delivered: number;
  /** Replay alerts an officer approved through the approval workflow. */
  replay_alerts_approved: number;
  /** Forecast readings the sweep stored in the last 24 h: one per village per sweep. */
  forecast_checks_24h: number;
  gauge_readings_24h: number;
  gauge_readings_24h_simulated: number;
}

export interface PublicVillage {
  id: string;
  name: string;
  name_hi: string;
  lat: number;
  lon: number;
  level: Level;
  coords_verified: boolean;
  rollcall?: PublicRollCall | null;
  replay?: boolean;
  live_level?: Level;
  data_status?: DataStatus;
  data_ok_at?: string | null;
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

/** GET /public/pilot-metrics (api/pilot.py). Null means not measured yet; nothing is estimated. */
export interface PilotGroup {
  alerts: number;
  /** Everyone the alerts reached, demo stub recipients included: the alerts' delivered_count summed. */
  delivered?: number;
  /** Of them, people reached on a real phone (never the stub channel), each once per alert. */
  reached: number;
  /** delivered - reached: demo recipients without a phone. */
  demo_recipients?: number;
  acknowledged: number;
  /** 0..1 */
  ack_share: number | null;
  /** Per alert: first send to the first "मिल गया"; the median over alerts. */
  median_minutes_first_ack: number | null;
  /** Per person: their send to their "मिल गया"; the median over people. */
  median_minutes_to_ack: number | null;
}

export interface PilotBacktestScenario {
  name: string;
  title: string;
  title_hi: string | null;
  villages_scored: number;
  villages_alerted: number;
  median_lead_hours: number | null;
  max_lead_hours: number | null;
  villages_get_ready?: number;
  median_get_ready_lead_hours?: number | null;
  villages: {
    village_id: string;
    village: string;
    outcome: string;
    /** The alert: first Watch to the river's peak day. */
    lead_hours: number | null;
    lead_is_lower_bound?: boolean;
    /** The get-ready outlook (never an alert) to the same day. */
    get_ready_lead_hours?: number | null;
    get_ready_is_lower_bound?: boolean;
  }[];
}

/** "Was this real?" counts over closed live alerts; false_alarm_rate = no_flood / (real_flood + no_flood). */
export interface OutcomeCounts {
  real_flood: number;
  no_flood: number;
  unknown: number;
  not_set: number;
  false_alarm_rate: number | null;
}

export interface PilotFalseAlarms extends OutcomeCounts {
  closed_alerts: number;
  /** Per rule family ("rain_24h", "discharge", "gauge", ...); an alert counts under each rule that fired. */
  by_rule: (OutcomeCounts & { rule: string; alerts: number })[];
}

export interface PilotMetrics extends SampleFlag {
  counters: Counters;
  drills: PilotGroup;
  live: PilotGroup;
  backtest: { rules: string | null; scenarios: PilotBacktestScenario[] } | null;
  /** Absent on an older API. */
  false_alarms?: PilotFalseAlarms;
  /** The ten pilot metrics, pooled (services/pilot_metrics.py). Absent on an older API. */
  ten?: TenMetrics;
  as_of: string;
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
  held?: boolean;
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
  watch_from_first_hour?: boolean;
  first_get_ready?: string | null;
  get_ready_from_first_hour?: boolean;
  lead_hours_get_ready_to_peak_day?: number | null;
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

/* ---- GET /agents, /agents/traces, /sensors (public, read-only) ---- */
export type AgentState = 'live' | 'fallback' | 'pending' | 'deterministic' | 'unknown';

export interface AgentStatus {
  state: AgentState;
  label_en: string;
  label_hi: string;
  /** What the status is based on (the last draft, or the cached model-access probe). */
  evidence: string;
  evidence_hi?: string;
}

export interface AgentTool {
  name: string;
  description: string;
  description_hi?: string;
  read_only: boolean;
  aws: string;
}

export interface AgentNever {
  action: string;
  en: string;
  hi: string;
  source: string;
}

export interface WatchFinding {
  village_id: string;
  kind: string; // stale | no_data | flatline | jump | battery
  severity: string; // warn | info
  at: string | null;
  value: number | null;
  message_en: string;
  message_hi: string;
}

export interface AgentCard {
  id: string;
  name_en: string;
  name_hi: string;
  kicker: string;
  role_en: string;
  role_hi: string;
  primitives: string[];
  tools: AgentTool[];
  output_fields: string[];
  never: AgentNever[];
  policies: { id: string; desc: string }[];
  max_turns: number;
  budget_seconds: number | null;
  fallback_en: string;
  fallback_hi: string;
  access_en?: string;
  access_hi?: string;
  status: AgentStatus;
  findings?: WatchFinding[];
}

export interface AgentRegistry {
  generated_at: string;
  model: { id: string; label: string; enabled: boolean; status: AgentStatus };
  guardrail: { present: boolean; configured: boolean; status: AgentStatus };
  agents: AgentCard[];
  counters: {
    agents: number;
    read_only_tools: number;
    cedar_policies: number;
    tool_calls_today: number;
    tool_calls_denied_today: number;
    drafts: number;
    drafts_by_model: number;
    drafts_by_template: number;
    watch_findings: number;
  };
}

export type TraceKind = 'sense' | 'rules' | 'tools' | 'draft' | 'approve' | 'deliver';

export interface TraceRound {
  n: number;
  kind: TraceKind;
  actor: 'code' | 'agent' | 'template' | 'person' | 'system';
  title_en: string;
  title_hi: string;
  aws: string;
  state: 'ok' | 'fallback' | 'pending' | 'skipped' | 'deny';
  facts: { en: string; hi: string; v: string | number }[];
  note_en: string;
  note_hi: string;
}

export interface AgentTrace {
  alert_id: string;
  village_id: string;
  village_name: string;
  village_name_hi: string;
  level: Level;
  previous_level: Level;
  status: AlertStatus;
  created_at: string;
  replay: boolean;
  drill: boolean;
  reasoning_model: string;
  rounds: TraceRound[];
}

export interface SensorReadingView {
  at: string;
  water_level_cm: number;
  battery_v: number | null;
  rssi: number | null;
  simulated: boolean;
  transport: string | null;
  received_at: string | null;
  origin?: 'live' | 'backfill';
  quality?: GaugeQuality;
  quality_reasons?: string[];
  measured_level?: Level | null;
  confirmed_level?: Level | null;
  rising_fast?: boolean;
  rise_cm?: number | null;
}

export interface SensorVillage {
  id: string;
  name: string;
  name_hi: string;
  level: Level;
  gauge: { device_id: string; watch_cm: number; warning_cm: number; critical_cm: number; installed: boolean };
  latest: SensorReadingView | null;
  age_minutes: number | null;
  fresh: boolean;
  gauge_level: Level | null;
  measured_level?: Level | null;
  rising_fast?: boolean;
  health?: GaugeHealth | null;
  readings_24h: number;
  simulated: boolean;
  series: { at: string; cm: number }[];
  findings: WatchFinding[];
}

export interface RainObsDevice {
  device_id: string;
  source: string;
  at: string;
  fresh: boolean;
  simulated: boolean;
  quality: string;
  quality_reasons: string[];
  stuck: boolean;
  /** mm in each window: "15min", "1h", "3h". */
  windows: Record<string, number | null>;
  eval_level: Level;
  confirmed_level: Level;
  critical_like: boolean;
  rate_mm_h: number | null;
}

export interface RainObsView {
  devices: RainObsDevice[];
  /** "watch_15min", "warning_1h", …: the mm that raise a level in each window. */
  bands: Record<string, number>;
  thresholds_source?: string;
  level?: Level;
  simulated_level?: Level;
}

export interface SensorBoard {
  generated_at: string;
  window_start: string;
  fresh_minutes: number;
  readings_24h: number;
  by_transport: Record<string, number>;
  gauges: number;
  fresh_gauges: number;
  installed_gauges: number;
  villages: SensorVillage[];
  /** Sirens, pradhan boxes, relays and gauges in the device registry (health fails closed). */
  devices?: PublicDevice[];
  /** Observed rain per village from tipping buckets (services/rain_obs.py); a village with none is absent. */
  rain_obs?: Record<string, RainObsView>;
  watch: {
    checks: { kind: string; en: string; hi: string }[];
    findings: WatchFinding[];
    thresholds: { stale_minutes: number; flat_min_readings: number; jump_cm_per_min: number; low_battery_v: number };
  };
}

/* ---------- safe places (GET /villages/{id}/safe-places) ---------- */

export type ShelterState = 'OPEN' | 'STANDBY' | 'FULL' | 'CLOSED';
/** UNCONFIRMED: no pradhan or officer has said anything about this place yet. */
export type ShelterLedgerState = ShelterState | 'UNCONFIRMED';

export interface ShelterLedger {
  status: ShelterLedgerState;
  capacity: number | null;
  note: string;
  updated_by: string | null;
  updated_at: string | null;
}

export interface SafePlace {
  id: string;
  osm_url: string;
  name: string;
  name_hi: string;
  kind: string;
  kind_en: string;
  kind_hi: string;
  lat: number;
  lon: number;
  elevation_m: number;
  /** Height above the river near the village (and above the nearest mapped stream), whichever is less. */
  headroom_m: number;
  route_length_m: number;
  off_network_m: number;
  climb_m: number;
  max_grade: number;
  steep_m: number;
  near_water_m: number;
  walk_min: number;
  rank: number;
  ledger: ShelterLedger;
  /** An active road block crosses this place's baked route (absent on older servers). */
  route_blocked?: boolean;
  route_blocks?: { id: string; label: string; note: string }[];
  /** The first baked route, by rank, that no block crosses. */
  best_open_route?: boolean;
}

export interface RouteFeature {
  type: 'Feature';
  geometry: { type: 'LineString'; coordinates: [number, number][] } | { type: 'Point'; coordinates: [number, number] };
  properties: {
    feature: 'route' | 'start';
    rank?: number;
    place_id?: string;
    steep?: boolean;
    name?: string;
    blocked?: boolean;
    best?: boolean;
    block_note?: string;
  };
}

/** A road or bridge on a baked route that a pradhan or officer marked blocked (7 days unless renewed). */
export interface RoadBlock {
  id: string;
  lat: number;
  lon: number;
  label: string;
  note: string;
  created_by: string;
  created_at: string;
  renewed_by: string | null;
  renewed_at: string | null;
  expires_at: string;
  /** Places whose baked route passes through this block. */
  place_ids: string[];
}

export interface SafePlacesView extends SampleFlag {
  village_id: string;
  available: boolean;
  places: SafePlace[];
  routes: { type: 'FeatureCollection'; features: RouteFeature[] };
  roadblocks?: RoadBlock[];
  route_limit_en?: string;
  route_limit_hi?: string;
  river_level_m?: number | null;
  river_level_method?: string | null;
  candidates?: Record<string, number> | null;
  notes: string[];
  attribution: string | null;
  terrain_attribution?: string | null;
  license?: string | null;
  limits_en: string;
  limits_hi: string;
}

/* ---------- the ten pilot metrics (services/pilot_metrics.py, docs/PILOT_PROTOCOL.md) ---------- */
/** Null means not measured; nothing is estimated. */
export interface TenReach {
  targeted: number;
  confirmed: number;
  share_15?: number | null;
  share_30?: number | null;
  share_60?: number | null;
}

export interface TenGroup {
  alerts: number;
  confirmed_reach: TenReach;
  assisted_reach: { targeted: number; confirmed: number; share_30: number | null; checked_by_neighbour: number; confirmed_or_checked_share: number | null };
  time_chain_median_minutes: Record<string, number | null>;
  lead_time: { measured: number; median_minutes: number | null };
  outcomes: { real_flood: number; no_flood: number; unknown: number; not_set: number; false_alarm_rate: number | null; hit_rate: number | null };
  siren: { commanded: number; verified: number; verified_share: number | null };
  data_health: { alerts_with_data_ok: number; alerts_with_status: number; alerts_with_gauge_silent: number };
  protective_action: { rollcalls: number; asked: number; safe: number; need_help: number; answered_share: number | null };
}

export interface ReadinessChecklist {
  items: number;
  done: number | null;
  in_progress: number | null;
  not_started: number | null;
  updated: string | null;
}

export interface TenMetrics {
  coverage: { villages: number; villages_with_household_list: number; registered_phones: number; households_listed: number | null; share: number | null };
  readiness: { checklist: ReadinessChecklist; villages_with_two_observers: number; assisted_households: number; assisted_without_neighbour: number };
  data_health_now: { forecast_checks_24h: number | null; expected_24h: number; share: number | null };
  live: TenGroup;
  drill: TenGroup;
  replay: TenGroup;
  as_of: string;
}

/** GET /alerts/{id}/metrics: one alert's ten metrics, counts and times only. */
export interface AlertMetrics {
  alert_id: string;
  kind: 'live' | 'drill' | 'replay';
  coverage: { registered: number; households: number | null; share: number | null; per_1000_people: number | null; observers: number; targeted: number };
  confirmed_reach: TenReach & { reached: number; confirmed_share: number | null; within_15: number; within_30: number; within_60: number };
  assisted_reach: TenReach & { escalated: number; checked_by_neighbour: number; confirmed_or_checked: number; confirmed_or_checked_share: number | null };
  time_chain: { at: Record<string, string | null>; minutes: Record<string, number | null> };
  lead_time: { onset_at: string | null; from_first_delivery: number | null; from_first_ack: number | null };
  outcome: { outcome: AlertOutcome | null; recorded_at: string | null };
  siren: { commanded: number; started: number; verified: number; verified_share: number | null };
  data_health: { forecast: string | null; stale_minutes: number | null; gauge: 'fresh' | 'silent' | 'none' | 'not_fresh'; unknown: string[] };
  protective_action: { asked: number; safe: number; need_help: number; answered_share: number | null; exercise: boolean } | null;
  readiness: { checklist: ReadinessChecklist; observers: number; observers_needed: number; gaps: string[] };
  followup: { at: string | null; trigger: string | null; sent: number };
}

/** GET /care/villages: observers, assisted households and coverage per village (services/assisted.py). */
export interface VillageCare {
  village_id: string;
  name: string;
  name_hi: string;
  district: string;
  observers: number;
  observers_needed: number;
  observer_roles: string[];
  women_observers: number;
  observers_gender_known: number;
  women_share_goal: number;
  assisted: number;
  assisted_without_neighbour: string[];
  registered_phones: number;
  households: number | null;
  coverage: number | null;
  gaps: string[];
}
