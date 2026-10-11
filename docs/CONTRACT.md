# Pukaar build contract

The shared interface between the backend (`backend/src/Pukaar/`), the
front end (`frontend/`) and the infrastructure (`infra/`). Change it here
first, then in code.

## Levels and statuses

- Levels: `normal`, `watch`, `warning`, `critical` (in that order).
- Alert status: `drafting`, `pending`, `approved`, `declined`, `expired`,
  `delivering`, `delivered`, `auto_sent_unapproved`, `failsafe`, `closed`.
- Report state: `received`, `transcribing`, `unverified`, `verified_auto`,
  `verified`, `reviewed`, `actioned`, `resolved`, `duplicate`, `false`.
- Report type: `water_rising`, `road_cut`, `bridge_unsafe`, `landslide`,
  `homes_affected`, `people_trapped`, `other`.
- Severity: `low`, `medium`, `high`, `critical`.
- Directive type: `evacuate`, `shelter_in_place`, `advisory`, `all_clear`.

Every record that came from replay data carries `replay: true`.

## Auth

`Authorization: Bearer <token>`.

- AWS mode: a Cognito ID token. API Gateway's JWT authorizer checks it; the
  API reads `cognito:groups` (`officer`, `pradhan`), `cognito:username` and
  `custom:village_ids` (comma separated).
- Local mode (`PUKAAR_MODE=local`): `POST /auth/dev-login {username}` returns
  a token for one of the seeded demo users (`officer1`, `officer2`,
  `pradhan_thunag`). Not mounted in AWS mode.
- Front end: when `VITE_COGNITO_CLIENT_ID` and `VITE_COGNITO_REGION` are set,
  sign in with Cognito `InitiateAuth` (`USER_PASSWORD_AUTH`) by plain `fetch`
  to `https://cognito-idp.<region>.amazonaws.com/`; otherwise use dev login.

Public routes (no token): `GET /health`, `GET /villages`, `GET /villages/{id}`, `GET /villages/{id}/safe-places`,
`POST /reports`, `POST /alerts/{id}/ack`, `GET /approval/{token}`,
`POST /approval/{token}`, `POST /telegram/webhook`, `GET /public/overview`,
`GET /track/{code}`, `GET /replay/status`, `GET /alerts/{id}/audio`, `GET /safe/{token}`,
`POST /sensors/{id}/readings` (river gauge, HMAC-signed body, see docs/hardware/README.md),
`GET /cap/alerts.atom` and `GET /cap/alerts/{id}.xml` (CAP 1.2 feed of published alerts, XML),
`GET /agents`, `GET /agents/traces?limit=5`, `GET /sensors` (read-only, no personal data),
`GET /push/vapid-public-key` (the Web Push applicationServerKey; `{key: null, configured: false}` until `make vapid-keys`),
`POST /auth/dev-login` (local only). Everything else needs an officer or
pradhan token and passes `policy.guard.authorize()`.

## Shapes (JSON)

```
Village   {id, name, name_hi, district, lat, lon, coords_verified, population|null,
           level, level_since, calm_sweeps, thresholds{watch,warning,critical}|null,
           latest_reading: Reading|null, open_alert_id|null, soil{dry,wet,source}|null,
           readiness: Readiness}
Reading   {village_id, at, rain_24h_mm, rain_hourly[{t,mm}], discharge|null,
           discharge_forecast[{date,value}], discharge_peak|null,
           discharge_outlook[{date,value}] (today..+7 days), soil_moisture_root|null (m³/m³),
           rain_level, river_level, source: "open-meteo"|"replay", replay}
Readiness {state: "none"|"get_ready", available, horizon_days|null, peak_day|null,
           peak_vs_watch_ratio|null, peak_discharge|null, watch|null, source,
           window_days[2,7], days[{date,days_ahead,value}], from_reading|null, replay}
           (soft trigger: never sends an alert, never changes the level)
Soil      {moisture_root|null, saturation|null, dry, wet, range_source, calibrated, factor,
           factor_if_on, enabled, applied, state: "no_reading"|"off"|"applied"|"below_threshold",
           saturated_at, layers[], at|null, replay}
Checklist {items[{village_id, item, label_en, label_hi, order, done, done_by|null, done_at|null}],
           done, total}
Alert     {id, village_id, village_name, village_name_hi, level, previous_level, status,
           created_at, updated_at, text_hi, text_en, reason_en, reasoning_model,
           draft_check{passed, reason}, decision_trace{...}, recipients_count,
           officer_index, decided_by|null, decided_at|null, approved: bool,
           delivered_count, acknowledged_count, has_audio, replay}
Delivery  {alert_id, recipient_id, name, channel: "telegram"|"stub", status,
           sent_at|null, attempts, acknowledged_at|null, error|null}
Report    {id, village_id, created_at, text, transcript, report_type, severity,
           summary_en, reply_hi, lat|null, lon|null, photo_url|null, audio_url|null,
           state, previous_state|null, parser_source, flags[], track_code, replay}
Directive {id, village_id, type, text_hi, text_en, issued_by, issued_at, active}
Audit     {at, id, actor, role, action, resource, decision: "allow"|"deny", reason}
Event     {at, step, detail}          (alert timeline)
PastEvent {village_id, date, level, note_en, note_hi, source}
Error     401 {detail: "Sign in required."}
          403 {detail: {code: "denied", reason, action, role}}
          409 {detail: {code: "late", message_en, message_hi, reason}}
          503 {detail: {code: "retry", reason}}
```

## Routes

```
GET  /health                 {status, mode: "aws"|"local", workflow, model,
                              services{dynamodb,bedrock,polly,transcribe,telegram}, replay_active}
GET  /dev/approval-link/{id} local mode only, officer: {url, token, officer} (demo of the one-tap link)
GET  /health/deep            officer: one tiny model call
GET  /me                     {username, role, village_ids}
POST /me/telegram-link       officer: {} -> {code, command, expires_in_seconds}  (one-time; send the
                             command to the bot to receive approval links in Telegram)
GET  /push/vapid-public-key  public: {key: base64url P-256 point | null, configured}
GET  /me/push-subscriptions  officer or pradhan (Cedar subscribe_push): [{id, user_agent, created_at,
                             last_sent_at}]  (own phones only; never the endpoint or keys)
POST /me/push-subscriptions  PushSubscription.toJSON() {endpoint, keys{p256dh, auth}, expirationTime}
                             -> {id, user_agent, created_at, last_sent_at}; id = first 24 hex of
                             SHA-256(endpoint), so the same browser replaces its own row; endpoint must be
                             https on a browser push service; 400 bad subscription, 503 push not set up
DELETE /me/push-subscriptions/{id}  -> {ok, id}; 404 if not this user's
POST /me/push-test           -> {sent, failed, removed}; 404 no subscription; 429 more than one a minute
                             The approval push (ask_officer, live and drill alerts, never replay):
                             {kind:"approval", title, body, tag: alert id, renotify, requireInteraction,
                              actions[{action:"approve"|"decline", title}], data{url: /a/<token>,
                              alert_id, token, drill}}; the service worker POSTs {decision} to
                             /approval/{token}. 404/410 from the push service deletes the subscription.
POST /auth/dev-login         local only: {username} -> {token, username, role}
GET  /villages               [Village]
GET  /villages/{id}          {village, readings[<=96], alerts[], reports[], past_events[PastEvent],
                              directives[<=5 Directive], nowcast|null, gauge|null, soil: Soil,
                              checklist: Checklist, staff_gauges: {gauges[StaffGauge], readings[<=10]}}
                             nowcast = {likely_level, hours, text_en, text_hi}
GET  /villages/{id}/gauge/proposal  officer (any) or pradhan (own village), Cedar view_gauge_proposal:
                             {status: "ready"|"insufficient", basis{readings, days, used, excluded, simulated},
                              current, proposed{watch_cm, warning_cm, critical_cm}, raw, percentiles,
                              baseline_cm, adjustments[], curve[{p, cm}], daily[], faults[Fault], note_en, note_hi}
                             (services/gauge_learn.py; never applied by the system)
POST /villages/{id}/gauge/thresholds  officer only (Cedar set_gauge_thresholds): {watch_cm, warning_cm,
                             critical_cm, from_proposal=true, note?} -> {current, previous}; 409
                             proposal_changed when from_proposal and the values are not the current
                             proposal (5 cm tolerance); audit row set_gauge_thresholds old -> new
GET  /villages/{id}/staff-gauges  public: [StaffGauge] (active; photo_url presigned)
POST /villages/{id}/staff-gauges  officer or own pradhan (Cedar manage_staff_gauge): multipart meta (JSON:
                             name, name_hi, where, scale_top, scale_bottom, unit "class"|"cm", marks[{label,
                             value, height_cm?, x, y}], watch_at?, warning_at?, critical_at?) + photo -> StaffGauge
PATCH /villages/{id}/staff-gauges/{gid}  same Cedar: {name?, name_hi?, where?, watch_at?, warning_at?,
                             critical_at?, active?} -> StaffGauge (audited)
POST /reports/{id}/staff-reading  officer only (Cedar confirm_staff_reading): {value} confirms or adjusts,
                             {unreadable: true} rejects -> Report; audited old -> new; re-runs the village
POST /villages/{id}/checklist/{item}  officer (any village) or pradhan (own village only), Cedar
                             action tick_checklist: {done: bool} -> Checklist; 404 unknown village or item;
                             each change writes an Audit row (checklist_tick / checklist_untick)
GET  /villages/{id}/safe-places  {village_id, available, places[SafePlace], routes (GeoJSON FeatureCollection:
                             route lines {feature:"route", rank, place_id, steep} and the start point), notes[],
                             attribution "© OpenStreetMap contributors (ODbL)", limits_en, limits_hi, river_level_m}
                             SafePlace = baked OSM place {id, name, name_hi, kind, headroom_m, route_length_m, walk_min,
                             climb_m, max_grade, steep_m, rank, osm_url, lat, lon, ...} + ledger {status:
                             "UNCONFIRMED"|"OPEN"|"STANDBY"|"FULL"|"CLOSED", capacity, note, updated_by, updated_at}
POST /villages/{id}/shelters/{place_id}  officer (any village) or pradhan (own village):
                             {status: "OPEN"|"STANDBY"|"FULL"|"CLOSED", capacity?, note?} -> the safe-places view;
                             404 for a place that is not baked for that village; audited ("shelter_changed")
GET  /alerts?status=&village_id=   [Alert]
GET  /alerts/{id}            {alert, deliveries[], timeline[Event], audit[Audit]}
GET  /alerts/{id}/after-action?fresh=&format=   officer, or pradhan of the alert's village (Cedar
                             view_after_action; 403 otherwise): text/html after-action report (the copy stored
                             at close, else built now; fresh=true rebuilds); format=json -> the small summary.
                             No phone numbers or chat ids; first names only
POST /alerts/{id}/approve    officer: {} -> Alert; 409 {detail{code,message_en,message_hi}} when late;
                             503 {detail{code:"retry",reason}} when the workflow was briefly unreachable
POST /alerts/{id}/decline    officer: {reason?} -> Alert; 409 as above
GET  /approval/{token}       signed link: {alert, expires_at, valid, officer}; 409 late/expired;
                             400 {detail{code:"invalid",message_en,message_hi}} for a broken or forged link
POST /approval/{token}       signed link: {decision: "approve"|"decline"} -> Alert; 409 when late or reused
GET  /alerts/{id}/audio      {url|null, text_hi}   (presigned S3 URL; never synthesises client text)
POST /alerts/{id}/ack        {token} -> {ok, acknowledged_at}
POST /reports                multipart: village_id, text?, audio?, photo?, lat?, lon?,
                             reporter_name?, offline_created?, staff_gauge_id?, staff_mark? (needs the
                             photo) -> {report, track_code}
GET  /reports?village_id=&state=   officer/pradhan: [Report]
PATCH /reports/{id}/state    officer: {state} -> Report (undo = PATCH back to previous_state)
GET  /directives?village_id= [Directive]
POST /directives             officer: {village_id, type, note_en?} -> Directive
POST /replay/start           officer: {scenario?: "himachal_2023_07"|"mandi_2025", speed_seconds_per_hour?: number}
                             -> ReplayStatus (speed capped so the run fits one worker invocation)
POST /replay/reset           officer: {} -> ReplayStatus
GET  /replay/status          {active, stale, available[], scenario, title, title_hi, clock|null,
                              hours_total, hours_done, source, started_at, updated_at}
GET  /audit?date=&resource=  officer: [Audit]
GET  /stats                  {villages_watched, alerts_sent, phones_acknowledged, reports_received,
                              alerts_by_status{}, levels{}}
POST /ask/officer            officer: {question} -> {answer, chart|null, map|null, tools[], model}
                             chart = {type:"bar"|"line", title, x_label, y_label,
                                      series[{name, points[{x, y}]}]}
                             map   = {village_ids[], points[{lat, lon, label}]}
                             tools = [{name, input, output_summary, decision}]
GET  /public/overview        {counters{villages_watched, alerts_sent, phones_acknowledged,
                              reports_received}, villages[{id,name,name_hi,lat,lon,level,coords_verified}],
                              recent_alerts[{id,village_name,village_name_hi,level,status,created_at,
                              approved,delivered_count,acknowledged_count,replay}], replay{active}}
GET  /track/{code}           {code, village_name, village_name_hi, created_at, report_type, state,
                              steps[{key:"received"|"verified"|"acted_on", done, at|null}]}
POST /telegram/webhook       Telegram update; header X-Telegram-Bot-Api-Secret-Token
                             callbacks: ack:<alert_id>, safe:<rollcall_id>, help:<rollcall_id>

Safety roll-call ("Surakshit Hoon"); officer any village, pradhan own villages (Cedar view_rollcall,
open_rollcall, remind_rollcall). No chat id or phone number in any of these shapes.
RollCall  {id, village_id, village_name, village_name_hi, alert_id|null, level|null, opened_at, closes_at,
           opened_by: "system"|"officer", opened_by_user|null, exercise, asked, safe, need_help,
           not_answered, open, last_reminded_at|null, reminders}
Board     {rollcall: RollCall, need_help[{name, at, note|null, simulated}], safe[{name, at, simulated}],
           not_answered[{name, demo, asked_at, reminded_at|null, failed}], remind_every_seconds}
GET  /rollcalls?village_id=  [RollCall] newest first
GET  /rollcalls/{id}         Board
POST /rollcalls              {village_id, exercise?} -> Board; 409 {detail{code:"already_open", rollcall_id}}
POST /rollcalls/{id}/remind  {} -> {reminded, waiting, demo_without_phone, last_reminded_at, board};
                             429 {detail{code:"rate_limited", retry_after_seconds, message_en, message_hi}}
GET  /safe/{token}           public family link: {first_name|null, village_name, village_name_hi, at,
                             status:"safe", exercise, simulated}; 400 invalid, 410 expired | not_current
GET  /villages/{id} and /public/overview villages[] also carry
                             rollcall: {open, exercise, asked, safe, need_help, not_answered, opened_at,
                             closes_at} | null   (counts only, while one is open)
```

## AWS resources (stack `pukaar-dev`, region `us-east-1`)

| Resource | Name / detail |
|---|---|
| DynamoDB | table `pukaar-<stage>`; `pk`, `sk` strings; GSI `gsi1` on `gsi1pk`, `gsi1sk`; TTL attribute `ttl`; on-demand; PITR |
| S3 | bucket for `audio/`, `photos/`, `replay/`; private; presigned GETs |
| Lambda `api` | image target `api`: uvicorn `Pukaar.main:app` on 8080 behind the Lambda Web Adapter, readiness `/health`; 2048 MB, 29 s |
| Lambda `sweep` | image target `worker`, CMD `Pukaar.handlers.sweep.handler`; 1024 MB, 120 s; DLQ; 0 async retries |
| Lambda `workflow` | CMD `Pukaar.handlers.workflow.handler`; 1024 MB, 30 s |
| Lambda `worker` | CMD `Pukaar.handlers.worker.handler`; 1024 MB, 900 s (transcription, replay, delivery retries); DLQ |
| Step Functions | Standard, `infra/approval.asl.json`, execution name = alert id |
| Scheduler | `rate(15 minutes)` -> `sweep`, retries 0, DLQ |
| Cognito | user pool, groups `officer`, `pradhan`, attribute `custom:village_ids`, app client without secret, `USER_PASSWORD_AUTH` |
| HTTP API | JWT authorizer on `$default`, public routes above, CORS to the web origin, throttling |
| SSM SecureString | `/pukaar/telegram_token`, `/pukaar/telegram_webhook_secret`, `/pukaar/link_secret` |
| Metrics | namespace `Pukaar`, EMF: `SweepCompleted`, `ModelLatencyMs`, `ModelError`, `ModelFailover`, `DeliverySent`, `DeliveryFailed`, `UnacknowledgedAlerts`, `ApprovalDecision` |

Environment variables of every function: `PUKAAR_MODE=aws`,
`PUKAAR_TABLE_NAME`, `PUKAAR_BUCKET`, `PUKAAR_STATE_MACHINE_ARN`,
`PUKAAR_AWS_REGION`, `PUKAAR_BEDROCK_MODEL_ID`, `PUKAAR_BEDROCK_FALLBACK_REGION`,
`PUKAAR_APPROVAL_TIMEOUT_SECONDS`, `PUKAAR_ACK_WAIT_SECONDS`,
`PUKAAR_WEB_URL`, `PUKAAR_API_URL`, `PUKAAR_WORKER_FUNCTION`,
`PUKAAR_REPLAY_ENABLED`, `PUKAAR_SSM_PREFIX=/pukaar`.

## Workflow Lambda (`Pukaar.handlers.workflow.handler`)

Event `{"step": <name>, ...}`; returns a dict. Execution input:
`{"alert_id", "village_id", "level"}`.

| Step | Input | Output |
|---|---|---|
| `draft` | `alert_id` | `{alert_id, level, officer_count, recipients_count}` |
| `ask_officer` | `alert_id, officer_index, task_token` | (callback) task success output `{decision: "approved"\|"declined", by}` |
| `next_officer` | `alert_id, officer_index` | `{has_next, officer_index, level}` |
| `auto_send` | `alert_id` | `{alert_id, mode: "auto"}` (marks `auto_sent_unapproved` after Cedar allows `System`) |
| `expire` | `alert_id` | `{alert_id, outcome: "expired"}` |
| `deliver` | `alert_id` | `{alert_id, sent, failed}` |
| `recall` | `alert_id` | `{alert_id, resent}` |
| `close` | `alert_id, outcome` | `{alert_id, status}` |
| `failsafe` | `alert_id, error` | `{alert_id, sent}` |

Worker Lambda (`Pukaar.handlers.worker.handler`) events:
`{"task": "transcribe_report", "report_id", "village_id"}`,
`{"task": "replay", "speed_seconds_per_hour"}`.
