# Pukaar API and interface contract

The shared interface between the backend (`backend/src/Pukaar/`), the
front end (`frontend/`) and the infrastructure (`infra/`).

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
`GET /villages/{id}/staff-gauges`,
`POST /reports`, `POST /alerts/{id}/ack`, `GET /approval/{token}`,
`POST /approval/{token}`, `POST /telegram/webhook`, `GET /public/overview`, `GET /public/pilot-metrics`,
`GET /track/{code}`, `GET /replay/status`, `GET /alerts/{id}/audio`, `GET /safe/{token}`,
`POST /sensors/{id}/readings` and `POST /sensors/{id}/backfill` (river gauge, HMAC-signed body, see docs/hardware/README.md),
`GET /cap/alerts.atom` and `GET /cap/alerts/{id}.xml` (CAP 1.2 feed of published alerts, XML),
`GET /agents`, `GET /agents/traces?limit=5`, `GET /sensors` (read-only, no personal data),
`GET /push/vapid-public-key` (the Web Push applicationServerKey; `{key: null, configured: false}` until `make vapid-keys`),
the voice-call webhooks (`GET`/`HEAD /voice/exotel/flow`, `GET /voice/exotel/gather`, `POST /voice/exotel/status`,
`POST /voice/plivo/answer`, `POST /voice/plivo/digits`, `POST /voice/plivo/hangup`: each needs the SSM
`voice_webhook_key` in `?k=`, an HMAC-signed per-call token and a call id Pukaar placed, plus Plivo's
`X-Plivo-Signature-V3`; anything else is a 403, see docs/VOICE.md),
`POST /auth/dev-login` (local only). Everything else needs an officer or
pradhan token and passes `policy.guard.authorize()`.

## Shapes (JSON)

```
Village   {id, name, name_hi, district, lat, lon, coords_verified, population|null,
           level, level_since, calm_sweeps, thresholds{watch,warning,critical,method,
             return_period_years, cell_lat, cell_lon, river, cell_verified}|null,
           latest_reading: Reading|null, open_alert_id|null, soil{dry,wet,source}|null,
           readiness: Readiness, replay, live_level, live_level_since|null, replay_level|null,
           data_status: "ok"|"stale"|"unavailable", data_ok_at|null, data_missing_sweeps, data_note}
          (no officer usernames. While a replay runs, level/replay show the replay's copy only
           when the live level is normal with no open live alert; live_level is always the live one.
           data_status "stale": the last complete forecast is carried forward; "unavailable": none for
           more than PUKAAR_STALE_MAX_SWEEPS sweeps, level held. Neither is ever a calm sweep.)
Reading   {village_id, at, rain_24h_mm|null, rain_hourly[{t,mm}], discharge|null,
           discharge_forecast[{date,value}], discharge_peak|null,
           discharge_outlook[{date,value}] (today..+7 days), soil_moisture_root|null (m³/m³),
           rain_level, river_level, source: "open-meteo"|"replay", replay,
           missing["rain"|"discharge"] (unknown, never read as 0), carried_from|null,
           discharge_ensemble{status: "ok"|"unavailable"|"off", members, run_date,
             days[{date,lead,values[]}] (lead 1-7: days 1-3 set a level, 1-7 give the outlook its
             median), fetched_at}|null (GloFAS ensemble at the river cell, once a day),
           official[{source: "cwc"|"imd"|"flood_hub"|"bipad", name, status: "ok"|"unavailable"|"off",
             level|null, detail, ...}] (evidence; never lowers a level)}
Readiness {state: "none"|"get_ready", available, line: "early"|"watch", early|null, watch|null,
           basis: "ensemble_median"|"single_forecast"|"mixed"|null, horizon_days|null,
           first_day_over|null, days_over, reaches_watch, peak_day|null, peak_discharge|null,
           peak_vs_watch_ratio|null, peak_vs_early_ratio|null, source, window_days[1,7],
           days[{date,days_ahead,value,basis,single_forecast,over}], never_sets_level: true,
           from_reading|null, replay}
           (soft trigger, "Get ready: the river is forecast to run high": a day 1-7 flow, the ensemble
           median when there is one, at or over `early` = the 90th percentile of daily flow at the
           river cell. Never sends, never creates an alert, never changes the level; the decision
           trace carries it as evidence {kind: "outlook", ...})
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
          (signed-in routes. On a public page (GET /villages/{id}) an alert has no officer usernames:
           decided_by, officer_chain, officers_asked, all_clear_by and outcome_by are left out and
           decided_by_role "officer"|"system"|null says who decided. Every other public answer puts
           "staff" ("system" for the system) where a *_by field held a username: views.scrub_people.)
Delivery  {alert_id, recipient_id, name, channel: "telegram"|"voice"|"stub", status,
           sent_at|null, attempts, acknowledged_at|null, error|null,
           provider|null, call_ids[], call_status|null, last_attempt_at|null, not_connected, no_key,
           error_category|null, digit|null, repeats, reprompts, unreachable}
          (officer routes only. One row per person per channel: a "both" recipient has a telegram and
           a voice row, and delivered_count/acknowledged_count count people. A voice row is "pending"
           while the call rings, "sent" once answered (sent_at = first answer), "acknowledged" after
           key 1 or 2, "failed" when not connected or not placed. No phone number in any shape.
           Who it reached is Cedar view_recipients: a public demo account on a live alert gets each row
           with recipient_id "hidden-<n>", name "Recipient <n>", no call_ids, error or digit, and
           masked: true.)
Report    {id, village_id, created_at, text, transcript, report_type, severity,
           summary_en, reply_hi, lat|null, lon|null, photo_url|null, audio_url|null,
           state, previous_state|null, parser_source, flags[], track_code, replay}
          (officer routes only. Public pages get PublicReport.)
PublicReport {id, village_id, created_at, report_type, severity, state, held, replay,
           has_location, has_photo, has_audio}   (never words, GPS, media links, names or codes)
Directive {id, village_id, type, text_hi, text_en, issued_by, issued_at, active}
          (signed out: no issued_by)
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
                              services{dynamodb,bedrock,polly,transcribe,telegram,guardrail}, replay_active}
GET  /dev/approval-link/{id} local mode only, officer: {url, token, officer} (demo of the one-tap link)
GET  /media/{key}            local mode only: a stored file (AWS mode uses presigned S3 URLs; 404 here)
GET  /agents                 public: agent registry, model and guardrail status (services/agents.py)
GET  /agents/traces?limit=5  public: round-by-round traces of recent alert drafts (limit 1-10)
GET  /sensors                public: gauge board, latest readings (with quality, quality_reasons,
                             measured_level, confirmed_level, rising_fast, rise_cm), counted gauge_level,
                             measured_level, rising_fast, health (as on GET /villages/{id}), 24 h series
                             and sensor findings
POST /sensors/{id}/readings  public, HMAC-signed body, payload v1 or v2 (docs/hardware/README.md) -> 202
                             {status, kind, gauge_level, quality, confirmed_level, effective_level, rising_fast, ...}
POST /sensors/{id}/backfill  public, HMAC-signed {device_id, readings[<=60]} buffered readings, each stored once
                             per (device, boot, seq); never alerts -> 202 {stored, duplicate, rejected[]}
GET  /cap/alerts.atom        public: ATOM index of the latest 50 published alerts and all-clear Cancels
GET  /cap/alerts/{id}.xml    public: one CAP 1.2 <alert> (application/cap+xml); 404 if not published.
                             id allclear-{village}-{UTC stamp}: the village's current all-clear Cancel
GET  /health/deep            officer: one 1-token Converse call now; {bedrock: "ok"|"pending model access"|"failed"|"disabled", model, detail}; refreshes the cached model-access flag
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
                              river: River|null, checklist: Checklist,
                              staff_gauges: {gauges[StaffGauge], readings[<=10]}}
                             nowcast = {likely_level, hours, source: "rain"|"river",
                               basis: "ensemble"|"single_forecast", p|null, members|null, agree|null,
                               text_en, text_hi, from_reading, replay}  (a river line from the
                               ensemble only when P >= p_min; otherwise labelled "single forecast")
                             River = {level, mode: "ensemble"|"deterministic"|"none", p_min,
                               ensemble_status|null, p_max{watch,warning,critical}|null, members|null,
                               lead_days[{date, lead, members, p{watch,warning,critical}}], run_date|null,
                               today|null, peak|null, thresholds (watch/warning/critical = 2/5/20-year,
                               early, return_period_years, river, cell_*), at|null, replay}
                             gauge = {config, latest: SensorReading|null, fresh, fresh_minutes,
                               level|null (counted: 2 of the last 3 good readings, +1 rising fast),
                               measured_level|null (newest reading alone), rising_fast,
                               health{status, unhealthy, reasons["silent"|"low_battery"|"bad_quality"],
                               last_seen, minutes_since, battery_v, battery_low, readings_24h, bad_24h,
                               bad_share_24h, by_quality, backfilled_24h, ...}, series[{at, cm, q?, backfill?}]}
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
                             The safe-places view also carries roadblocks[{id, lat, lon, label, note, created_by,
                             created_at, renewed_by, renewed_at, expires_at, place_ids}], each place's route_blocked,
                             route_blocks[{id,label,note}] and best_open_route, each route line's blocked, best and
                             block_note, and route_limit_en/route_limit_hi (routes are baked, never recomputed)
POST /villages/{id}/roadblocks  officer (any village) or pradhan (own village), Cedar block_road:
                             {lat, lon, note, label?} -> the safe-places view; 400 when the note is empty or the
                             point is more than 60 m from every baked route of the village; every baked route within
                             30 m of the point counts as blocked; lapses after 7 days; audited ("road_blocked")
POST /villages/{id}/roadblocks/{bid}/renew  same Cedar: 7 more days from now; audited ("road_block_renewed")
POST /villages/{id}/roadblocks/{bid}/clear  same Cedar: the road is open again; audited ("road_block_cleared");
                             404 for a block that is cleared, expired or unknown
GET  /alerts?status=&village_id=   [Alert]
GET  /alerts/{id}            {alert, deliveries[], timeline[Event], audit[Audit]}
GET  /alerts/{id}/after-action?fresh=&format=   officer, or pradhan of the alert's village (Cedar
                             view_after_action; 403 otherwise, and for a public demo account on a live
                             alert): text/html after-action report (the copy stored
                             at close, else built now; fresh=true rebuilds); format=json -> the small summary.
                             No phone numbers or chat ids; first names only
POST /alerts/{id}/outcome    officer (Cedar set_alert_outcome): {outcome: "real_flood"|"no_flood"|"unknown"}
                             -> Alert (outcome, outcome_by, outcome_at); "was this real?" after a live alert
                             closed; 409 while open or for a replay or drill; can be corrected later
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
                             photo), device_id?, session_id? (random ids the report page keeps in
                             localStorage and sessionStorage) -> {report, track_code}. Never drops a report:
                             one over the per-source or per-village rate limit is stored with held: true and
                             hold_reason "source_rate_limit" | "village_surge" (services/report_guard.py).
                             The IP, network range, device and session are kept only as salted hashes and
                             never returned
GET  /reports?village_id=&state=   officer/pradhan: [Report]. A pradhan's list without village_id is
                             checked once per own village (no Cedar policy matches an empty village). The
                             public demo accounts (judge, judge_pradhan) get replay reports only
                             (Cedar public-demo-accounts-replay-only); GET /rollcalls likewise
PATCH /reports/{id}/state    officer: {state} -> Report (undo = PATCH back to previous_state)
GET  /directives?village_id= [Directive]
POST /directives             officer: {village_id, type, note_en?} -> Directive (+ stood_down when
                             type is all_clear: the all-clear to everyone contacted for the village's alerts)
GET  /roster?district=&start=   officer: {district, districts[], shifts[], start, days[{date, weekday,
                             shifts{day|night: {starts_at, ends_at, entry: RosterShift|null}}}],
                             now[{district, date, shift, source: roster|fallback|none, chain[], roles[],
                             primary, backup, escalation, escalation_title, taken_over_from}],
                             officers[], critical_auto_send, critical_auto_send_label}   (IST shifts:
                             day 08:00-20:00, night 20:00-08:00, dated the day it starts)
POST /roster/{district}/{date}/{day|night}   officer: {primary, backup?, escalation?, escalation_title:
                             "ADM"|"DM", note?} -> RosterShift   (audited: roster_changed)
DELETE /roster/{district}/{date}/{day|night} officer: {cleared}
POST /roster/{district}/take-over   officer: the caller becomes the primary of the shift running now
                             -> RosterShift   (audited: duty_taken_over)
POST /replay/start           officer: {scenario?: "himachal_2023_07"|"mandi_2025", speed_seconds_per_hour?: number}
                             -> ReplayStatus (speed capped so the run fits one worker invocation)
POST /replay/reset           officer: {} -> ReplayStatus
GET  /replay/status          {active, stale, available[], scenario, title, title_hi, clock|null,
                              hours_total, hours_done, source, started_at, updated_at}
GET  /audit?date=&resource=  officer: [Audit]
GET  /stats                  officer: {...Counters, alerts_by_status{}, levels{}}
POST /ask/officer            officer: {question} -> {answer, chart|null, map|null, tools[], model}
                             chart = {type:"bar"|"line", title, x_label, y_label,
                                      series[{name, points[{x, y}]}]}
                             map   = {village_ids[], points[{lat, lon, label}]}
                             tools = [{name, input, output_summary, decision}]
GET  /public/overview        {counters: Counters, villages[{id,name,name_hi,lat,lon,level,live_level,replay,
                              coords_verified,data_status,data_ok_at,rollcall}],
                              recent_alerts[{id,village_name,village_name_hi,level,status,created_at,
                              approved,delivered_count,acknowledged_count,replay}], replay{active}}
Counters  every one counted from stored records, nothing estimated (api/views.py counters()):
          villages_watched              villages in the registry
          alerts_sent                   live flood alerts that went out: delivered, auto_sent_unapproved,
                                        failsafe when critical or approved, closed when approved.
                                        Never replays, never drills (decision_trace.drill)
          phones_acknowledged           "मिल गया" taps on those alerts
          reports_received              villager reports, replay reports excluded
          drills_delivered              drill alerts (scripts/drill.py) that reached at least one real phone
                                        (a Telegram delivery sent or acknowledged); tests, not warnings
          replay_alerts_approved        replay alerts an officer approved through the approval workflow
          forecast_checks_24h           forecast readings the sweep stored in the last 24 h (one per village
                                        per sweep), replay rows excluded
          gauge_readings_24h            river-gauge readings received in the last 24 h (as GET /sensors)
          gauge_readings_24h_simulated  how many of those came from the labelled simulator
GET  /public/pilot-metrics   {counters: Counters, drills: Group, live: Group, backtest|null, false_alarms, as_of}
                             (api/pilot.py). false_alarms = {closed_alerts, real_flood, no_flood, unknown,
                             not_set, false_alarm_rate|null, by_rule: [{rule, alerts, real_flood, no_flood,
                             unknown, not_set, false_alarm_rate|null}]}: counts of "was this real?" over
                             closed live alerts, per rule family; no ids, no people
          Group = {alerts, reached, acknowledged, ack_share|null, median_minutes_first_ack|null,
                   median_minutes_to_ack|null}; drills = drill alerts that reached a real phone, live = live
                   alerts that went out. reached counts real-phone deliveries only (never the stub channel).
                   Null means not measured yet; nothing is estimated.
          backtest = {rules, scenarios[{name, title, title_hi, villages_scored, villages_alerted,
                     median_lead_hours|null, max_lead_hours|null, villages_get_ready,
                     median_get_ready_lead_hours|null, villages[{village_id, village, outcome,
                     lead_hours|null, lead_is_lower_bound, get_ready_lead_hours|null,
                     get_ready_is_lower_bound}]}]}  from data/backtest.json; lead_hours = the alert
                     (first Watch) to the river's peak day, get_ready_lead_hours = the get-ready
                     outlook (never an alert) to the same day
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
| Lambda `workflow` | CMD `Pukaar.handlers.workflow.handler`; 1024 MB, 120 s |
| Lambda `worker` | CMD `Pukaar.handlers.worker.handler`; 1024 MB, 900 s (transcription, replay, delivery retries); DLQ |
| Lambda `gauge-ingest` | CMD `Pukaar.handlers.gauge_ingest.handler`; 512 MB, 60 s; invoked by the IoT topic rule; 0 async retries; the worker's DLQ |
| Bedrock Guardrail | `pukaar-report-screen-<stage>` plus a published version; only the worker may call `ApplyGuardrail` on it |
| AWS IoT Core | policy `pukaar-gauge-<stage>`, topic rule `pukaar_gauge_<stage>` on `pukaar/gauge/+/+/reading` and `.../backfill` |
| AppSync Events | API `pukaar-events-<stage>`, namespaces `public` (API key, subscribe only) and `officer` (Cognito); publish `AWS_IAM` only |
| Step Functions | Standard, `infra/approval.asl.json`, execution name = alert id |
| Scheduler | `rate(15 minutes)` -> `sweep`, retries 0, DLQ |
| Cognito | user pool, groups `officer`, `pradhan`, attribute `custom:village_ids`, app client without secret, `USER_PASSWORD_AUTH` |
| HTTP API | JWT authorizer on `$default`, public routes above, CORS to the web origin, throttling |
| SSM | SecureString `/pukaar/telegram_token`, `/pukaar/telegram_webhook_secret`, `/pukaar/link_secret`, `/pukaar/vapid_private_key`, `/pukaar/after_action_to`, `/pukaar/gauge/<device>/key` and `/cert`, and for voice calls `/pukaar/voice_webhook_key`, `/pukaar/exotel_sid`, `/pukaar/exotel_api_key` (optional), `/pukaar/exotel_token`, `/pukaar/exotel_caller_id`, `/pukaar/exotel_app_id`, `/pukaar/plivo_auth_id`, `/pukaar/plivo_auth_token`, `/pukaar/plivo_caller_id`; String `/pukaar/vapid_public_key` |
| Metrics | namespace `Pukaar`, EMF: `SweepCompleted`, `ModelLatencyMs`, `ModelError`, `ModelFailover`, `DeliverySent`, `DeliveryFailed`, `UnacknowledgedAlerts`, `ApprovalDecision`, `RollCallNeedHelp`, `GaugeReading`, `GaugeRejected`, `GaugeBadReading`, `GaugeBackfill`, `GaugeUnhealthy`, `ReportScreened`, `GuardrailFallback`, `PushSent`, `PushFailed`, `EventPublishFailed`, `AfterActionSent`, `AfterActionFailed`, `VoiceCallPlaced`, `VoiceNotConnected`, `VoiceNoKey`, `VoiceUnreachable`, `VoiceNeedHelp` |

Environment variables of every function: `PUKAAR_MODE=aws`,
`PUKAAR_TABLE_NAME`, `PUKAAR_BUCKET`, `PUKAAR_STATE_MACHINE_ARN`,
`PUKAAR_AWS_REGION`, `PUKAAR_BEDROCK_MODEL_ID`, `PUKAAR_BEDROCK_FALLBACK_REGION`,
`PUKAAR_APPROVAL_TIMEOUT_SECONDS`, `PUKAAR_ACK_WAIT_SECONDS`,
`PUKAAR_WEB_URL`, `PUKAAR_API_URL`, `PUKAAR_WORKER_FUNCTION`,
`PUKAAR_REPLAY_ENABLED`, `PUKAAR_SSM_PREFIX=/pukaar`, `PUKAAR_STAGE`,
`PUKAAR_DATA_DIR`, `PUKAAR_GUARDRAIL_ID`, `PUKAAR_GUARDRAIL_VERSION`,
`PUKAAR_EVENTS_HTTP_DOMAIN`.

## Workflow Lambda (`Pukaar.handlers.workflow.handler`)

Event `{"step": <name>, ...}`; returns a dict. Execution input:
`{"alert_id", "village_id", "level"}`.

| Step | Input | Output |
|---|---|---|
| `draft` | `alert_id` | `{alert_id, level, officer_count, recipients_count, nudge_after_seconds, nudge_wait_seconds}` (freezes the duty-roster chain on the alert) |
| `ask_officer` | `alert_id, officer_index, task_token` | (callback) task success output `{decision: "approved"\|"declined", by}` |
| `nudge_officer` | `alert_id, officer_index, task_token` | half-way reminder to the same officer (Telegram, Web Push), then the same callback as `ask_officer` |
| `next_officer` | `alert_id, officer_index` | `{has_next, officer_index, level}` |
| `auto_send` | `alert_id` | `{alert_id, mode: "auto"}` (marks `auto_sent_unapproved` after Cedar allows `System`), or `{alert_id, mode: "off"}` when `PUKAAR_CRITICAL_AUTO_SEND=false` (needs DDMA sign-off; the alert expires unsent) |
| `expire` | `alert_id` | `{alert_id, outcome: "expired"}` |
| `deliver` | `alert_id` | `{alert_id, sent, failed}` |
| `recall` | `alert_id` | `{alert_id, resent}` |
| `close` | `alert_id, outcome` | `{alert_id, status}` |
| `failsafe` | `alert_id, error` | `{alert_id, sent}` |

Worker Lambda (`Pukaar.handlers.worker.handler`) events:
`{"task": "transcribe_report", "report_id", "village_id"}`,
`{"task": "replay", "speed_seconds_per_hour"}`.
