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

Public routes (no token): `GET /health`, `GET /villages`, `GET /villages/{id}`,
`POST /reports`, `POST /alerts/{id}/ack`, `GET /approval/{token}`,
`POST /approval/{token}`, `POST /telegram/webhook`, `GET /public/overview`,
`GET /track/{code}`, `GET /replay/status`, `GET /alerts/{id}/audio`,
`POST /auth/dev-login` (local only). Everything else needs an officer or
pradhan token and passes `policy.guard.authorize()`.

## Shapes (JSON)

```
Village   {id, name, name_hi, district, lat, lon, coords_verified, population|null,
           level, level_since, calm_sweeps, thresholds{watch,warning,critical}|null,
           latest_reading: Reading|null, open_alert_id|null}
Reading   {village_id, at, rain_24h_mm, rain_hourly[{t,mm}], discharge|null,
           discharge_forecast[{date,value}], discharge_peak|null, rain_level, river_level,
           source: "open-meteo"|"replay", replay}
Alert     {id, village_id, village_name, village_name_hi, level, previous_level, status,
           created_at, updated_at, text_hi, text_en, reason_en, reasoning_model,
           draft_check{passed, reason}, decision_trace{...}, recipients_count,
           officer_index, decided_by|null, decided_at|null, approved: bool,
           delivered_count, acknowledged_count, replay}
Delivery  {alert_id, recipient_id, name, channel: "telegram"|"stub", status,
           sent_at|null, attempts, acknowledged_at|null, error|null}
Report    {id, village_id, created_at, text, transcript, report_type, severity,
           summary_en, reply_hi, lat|null, lon|null, photo_url|null, audio_url|null,
           state, previous_state|null, parser_source, flags[], track_code, replay}
Directive {id, village_id, type, text_hi, text_en, issued_by, issued_at, active}
Audit     {at, id, actor, role, action, resource, decision: "allow"|"deny", reason}
Event     {at, step, detail}          (alert timeline)
```

## Routes

```
GET  /health                 {status, mode: "aws"|"local", services{dynamodb,bedrock,polly,transcribe,telegram}, replay_active}
GET  /health/deep            officer: one tiny model call
GET  /me                     {username, role, village_ids}
POST /auth/dev-login         local only: {username} -> {token, username, role}
GET  /villages               [Village]
GET  /villages/{id}          {village, readings[<=96], alerts[], reports[], past_events[], nowcast|null}
                             nowcast = {likely_level, hours, text_en, text_hi}
GET  /alerts?status=&village_id=   [Alert]
GET  /alerts/{id}            {alert, deliveries[], timeline[Event], audit[Audit]}
POST /alerts/{id}/approve    officer: {} -> Alert; 409 {detail{code,message_en,message_hi}} when late
POST /alerts/{id}/decline    officer: {reason?} -> Alert; 409 as above
GET  /approval/{token}       signed link: {alert, expires_at, valid}
POST /approval/{token}       signed link: {decision: "approve"|"decline"} -> Alert; 409 when late or reused
GET  /alerts/{id}/audio      {url|null, text_hi}   (presigned S3 URL; never synthesises client text)
POST /alerts/{id}/ack        {token} -> {ok, acknowledged_at}
POST /reports                multipart: village_id, text?, audio?, photo?, lat?, lon?,
                             reporter_name?, offline_created? -> {report, track_code}
GET  /reports?village_id=&state=   officer/pradhan: [Report]
PATCH /reports/{id}/state    officer: {state} -> Report (undo = PATCH back to previous_state)
GET  /directives?village_id= [Directive]
POST /directives             officer: {village_id, type, note_en?} -> Directive
POST /replay/start           officer: {speed_seconds_per_hour?: number} -> ReplayStatus
POST /replay/reset           officer: {} -> ReplayStatus
GET  /replay/status          {active, available, clock|null, hours_total, hours_done, source}
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
