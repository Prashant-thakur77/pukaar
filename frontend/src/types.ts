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
  /** Daily discharge from today up to 7 days ahead (the "get ready" outlook). */
  discharge_outlook?: { date: string; value: number }[];
  /** Root-zone soil moisture now (m³/m³), mean of the 9-27 and 27-81 cm layers. */
  soil_moisture_root?: number | null;
  rain_level: Level;
  river_level: Level;
  source: 'open-meteo' | 'replay';
  replay: boolean;
}

export interface SoilRange {
  dry: number;
  wet: number;
  source?: string;
}

/** Soft "get ready" trigger from the river outlook, days 2-7. Never changes the level. */
export interface Readiness {
  state: 'none' | 'get_ready';
  available?: boolean;
  horizon_days: number | null;
  peak_day: string | null;
  peak_vs_watch_ratio: number | null;
  peak_discharge?: number | null;
  watch?: number | null;
  source: string;
  window_days?: [number, number];
  days?: { date: string; days_ahead: number; value: number }[];
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
  /** What the guardrail said about the words; null on reports from before screening. */
  screen?: ReportScreen | null;
  /** Held for review: the guardrail stopped the words, so only an officer can verify it. */
  held?: boolean;
  /** "Compare with the marked rock": the mark the villager chose, and the officer's check. */
  staff_reading?: StaffReading | null;
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
}

export interface GaugeView {
  config: GaugeConfig;
  latest: SensorReading | null;
  /** Latest reading is recent enough (fresh_minutes) to count in the rules. */
  fresh: boolean;
  fresh_minutes: number;
  level: Level | null;
  series: { at: string; cm: number }[];
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
  checklist?: Checklist | null;
  /** An open safety roll-call: counts only, never names. */
  rollcall?: PublicRollCall | null;
  /** Virtual staff gauges: reference photos with their scales, and recent readings. */
  staff_gauges?: StaffGaugesView | null;
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
  rollcall?: PublicRollCall | null;
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
  readings_24h: number;
  simulated: boolean;
  series: { at: string; cm: number }[];
  findings: WatchFinding[];
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
