# Runbook

What the on-call person does when an alarm fires, and the routine work that keeps a pilot honest:
drills, phone-number hygiene, consent records, secret rotation and the pre-monsoon checklist.

`<stage>` is the stack's stage (`dev` today; `prod` for a pilot stack). Every alarm below is in
`infra/template.yaml`; `backend/tests/test_docs_consistency.py` fails if an alarm has no section here
or a section names an alarm that no longer exists.

## Where to look

| What | Where |
|---|---|
| Dashboard | CloudWatch, dashboard `pukaar-<stage>` (sweep, model, delivery, approvals, API, DLQs) |
| Logs | `/aws/lambda/pukaar-api-<stage>`, `pukaar-sweep-<stage>`, `pukaar-workflow-<stage>`, `pukaar-worker-<stage>`, `pukaar-gauge-ingest-<stage>`, `pukaar-canary-<stage>`; Step Functions `/aws/vendedlogs/states/pukaar-approval-<stage>` |
| Console | `/console/inbox` (approvals, and what was sent), `/console/villages`, `/console/reports`, `/console/rollcall`, `/console/roster`, `/console/audit`; `/how#sensors` |
| Queues | `pukaar-sweep-dlq-<stage>`, `pukaar-worker-dlq-<stage>` |
| Alarm topic | SNS `pukaar-alarms-<stage>`; subscribe the on-call phone (SMS) and e-mail. With no subscriber nobody hears an alarm. The worker Lambda is subscribed too and pages the primary and backup officer on duty on Telegram and Web Push (below, "The duty officer's day") |

A quick Logs Insights query that answers most first questions (pick the function's log group):

```
fields @timestamp, level, msg, village_id, alert_id, error
| filter level in ["WARNING", "ERROR"]
| sort @timestamp desc
| limit 50
```

## Who to call

Fill this in before the pilot starts and print it for the DEOC wall. Never commit real numbers.

| Role | Who | How |
|---|---|---|
| On-call engineer (Pukaar) | | phone, Telegram |
| Backup engineer | | |
| DEOC duty officer (district control room) | from the duty roster, `/roster` | DEOC landline |
| DDMO / ADM (escalation officer on the roster) | | |
| Pradhans of pilot villages | | `make voice-list VILLAGE=<id>` shows who is registered (masked) |
| AWS support | account's support plan | console, "Create case" |
| Exotel support | account manager | support e-mail, dashboard ticket |

**Waking the duty officer.** Three minutes into an officer's approval window (`OfficerWakeSeconds`),
an officer who has not opened the link is reminded on Web Push and Telegram and phoned, if voice is on
and their number is set: `make officer-phone OFFICER=<username> PHONE=+91...` (`PHONE=show` prints it
masked, `PHONE=remove` stops the calls). Pressing 1 on the call sends the approval link again; the
call never approves. Set a phone for everyone on the roster before the monsoon; the alert timeline
says "call=not possible (no phone number on file ...)" otherwise. A critical alert waits 5 minutes
per officer (`CriticalApprovalTimeoutSeconds`), not 10. When nobody in the chain answers, everyone on
duty and the ADM or DM get a last call with a fresh link, and the ADM or DM is phoned
(`pukaar-<stage>-alert-unanswered` below): put the ADM's or DM's number on file too.

"Tell the DDMA" below means the DEOC duty officer or the DDMO, by phone, in the same hour. Anything
that could mean a village is not being watched, or a warning did not reach people, is their business,
not only ours.

## Alarms

Each section: what it means, the first three checks, how to fix it, who to call, and whether to tell
the DDMA.

### pukaar-<stage>-model-errors

**What it means.** Bedrock calls failed in both regions three or more times in 5 minutes. Alert
drafts fall back to the fixed Hindi template, report structuring to the keyword parser, and Ask
Pukaar to its keyword router. Levels are set by code and are not affected.

**First 3 checks.**
1. Dashboard "Model" widget: is `ModelError` still rising, and is `ModelFailover` also firing?
2. Worker and workflow logs: `msg = "model call failed"`, its region and the error name
   (`AccessDeniedException`, `ThrottlingException`, `ValidationException`).
3. `GET /health/deep` (officer token) for a one-token probe of the configured model.

**Fix.** Throttling: wait, it clears; if it lasts, ask AWS for a quota raise. Access denied: the model
access grant was removed or the model id changed; re-enable access in the Bedrock console or deploy with
the previous `PUKAAR_BEDROCK_MODEL_ID`. Nothing needs to be re-run: drafts already went out with the
fixed template.

**Who to call.** On-call engineer. AWS support if both regions fail for more than an hour.

**Tell the DDMA?** No. Alerts still go out, with the fixed text.

### pukaar-<stage>-model-failover

**What it means.** At least one Bedrock call failed in the home region and was retried in the second
region (`us-west-2`). A warning sign, not an outage.

**First 3 checks.**
1. AWS Health Dashboard for Bedrock in the home region.
2. Whether `model-errors` is also in alarm (both regions failing).
3. Worker logs for the error name of the first failure.

**Fix.** Usually nothing; it clears when the home region recovers. If it fires every day, look at
quotas in the home region.

**Who to call.** On-call engineer, next working day unless `model-errors` fires too.

**Tell the DDMA?** No.

### pukaar-<stage>-api-5xx

**What it means.** Five or more server errors from the HTTP API in 5 minutes. Officers may not be able
to approve in the console, villagers' reports may be failing (the report page queues them and retries),
and Telegram's webhook may be failing (Telegram retries for a while).

**First 3 checks.**
1. Dashboard "API" widget: `5xx` against `Count`. A spike with normal traffic is a code or dependency
   fault; a spike with a traffic surge may be throttling.
2. API logs: the newest `ERROR` lines and the route.
3. DynamoDB console: throttled requests on table `pukaar-<stage>`, and S3 errors on the bucket.

**Fix.** A bad deploy: roll back by deploying the previous image tag (see docs/DEPLOY.md). A DynamoDB or
S3 incident: wait and watch; nothing is lost because the report page queues and Telegram retries. If
approvals are blocked, officers can still approve with the one-tap Telegram link (it goes through the
same API, so check that first) or decide by phone and record it afterwards.

**Who to call.** On-call engineer at once. AWS support if a service is degraded.

**Tell the DDMA?** Yes, if it lasts more than 15 minutes during a Watch or above: the console may be
down and approvals may need to go by phone.

### pukaar-<stage>-approval-failed

**What it means.** A Step Functions approval execution failed outright: even Failsafe or Close did not
finish. Every task already routes errors to Failsafe, so this is rare and serious: an alert may have
stopped half way.

**First 3 checks.**
1. Step Functions console, state machine `pukaar-approval-<stage>`: the failed execution, the last
   state and its error.
2. The alert in the console (`/console/inbox`, waiting or sent): its status and timeline.
3. Workflow logs for that `alert_id`.

**Fix.** If the alert was approved but not delivered, deliver it with the fixed template from the
console (an officer re-approves a fresh alert; the sweep re-asks after the cooldown while the level
holds). If the cause is a code fault, roll back. Never edit the alert item by hand.

**Who to call.** On-call engineer at once.

**Tell the DDMA?** Yes, always. Tell them which village and level, and confirm by phone that the
village was warned.

### pukaar-<stage>-sweep-dlq

**What it means.** A scheduled sweep invocation failed and went to the dead-letter queue. The sweep
does not retry (a retry could alert twice), so that 15-minute window was not checked for some or all
villages.

**First 3 checks.**
1. SQS `pukaar-sweep-dlq-<stage>`: how many messages, and their age.
2. Sweep logs around the failure time: the exception.
3. Whether `sweep-heartbeat` or `village-data-stale` is also in alarm (is it still failing?).

**Fix.** Fix the cause first (a deploy, a permission, a provider timeout). Then purge the DLQ; do not
redrive old sweep events, because the next sweep reads fresh data anyway and an old window would only
be skipped by the window claim. If the cause is unclear, keep the messages and attach them to the incident.

**Who to call.** On-call engineer.

**Tell the DDMA?** Only if the sweep is still failing (heartbeat in alarm); see that section.

### pukaar-<stage>-worker-dlq

**What it means.** A background task failed after its retries: processing a villager report,
synthesising audio, a gauge reading, or an IoT rule error. A report in it may be stuck at
`transcribing` or unscreened; it is still stored and visible to officers.

**First 3 checks.**
1. SQS `pukaar-worker-dlq-<stage>`: read one message (`task`, `report_id`).
2. Worker logs for that id.
3. The report in the console feed: is it there, and in what state?

**Fix.** After fixing the cause, redrive: `aws sqs start-message-move-task --source-arn <dlq arn>`
moves them back for one more try, or re-run one report by invoking the worker with
`{"task": "process_report", "report_id": "<id>"}`. A report that keeps failing: an officer reads it
and sets its state by hand.

**Who to call.** On-call engineer.

**Tell the DDMA?** Only if reports from a village under Watch or above are stuck: tell them to read
the console feed directly.

### pukaar-<stage>-sweep-heartbeat

**What it means.** No sweep completed in 30 minutes. Pukaar is not watching any village: no level can
rise and no alert can start.

**First 3 checks.**
1. EventBridge Scheduler: is the sweep schedule enabled?
2. Sweep logs: did it run, and why did it not complete (timeout, error)?
3. `GET /health` and the console header: does the system say "data unavailable" everywhere?

**Fix.** Re-enable the schedule; roll back a bad deploy; if Open-Meteo is down for everyone, the
village pages already say "data unavailable", and the DEOC must rely on IMD and CWC bulletins until it
returns.

**Who to call.** On-call engineer at once, day or night.

**Tell the DDMA?** Yes, at once: "Pukaar is not watching any village since <time>; use IMD and CWC
bulletins and the gauge readers by phone until we confirm it is back." Tell them again when it clears.

### pukaar-<stage>-village-data-stale

**What it means.** At least one village has had no complete forecast for 45 minutes. Its level is held,
never lowered, and its public page says "data unavailable". The alarm sends an OK message when the
data returns.

**First 3 checks.**
1. Dashboard: `VillageDataStale` grouped by Village, to see which.
2. Sweep logs for that `village_id`: fetch failed, or values missing?
3. The village page `/village/<id>`: data status and the time of the last good data.

**Fix.** A provider outage clears by itself; check the Open-Meteo status page. A wrong coordinate or
river cell after a data change: revert `data/villages.json` and reseed. If it lasts more than two
hours in the monsoon, ask the gauge reader or pradhan for a reading by phone.

**Who to call.** On-call engineer.

**Tell the DDMA?** Yes, if the village is at Watch or above, or rain is forecast: name the village and
ask the DEOC to watch it by other means.

### pukaar-<stage>-delivery-failed

**What it means.** A delivery to a real phone failed: a Telegram error, a voice call that could not
be placed, an unreadable token, or a send blocked by policy. Nothing is ever recorded as a stub send
instead.

**First 3 checks.**
1. The alert in the console: Deliveries list, the error on each failed row.
2. Workflow logs for `DeliveryFailed` and the reason (`token unreadable`, HTTP 403 "bot was blocked",
   429, voice `provider_error`).
3. `SecretReadFailed` on the dashboard (SSM throttled or down).

**Fix.** Token unreadable: check SSM `/pukaar/telegram_token` exists and the function can read it.
Blocked by the user: nothing to fix; remove them at the next number review. 429: the worker waits
out Telegram's `retry_after`; sends it could not fit in the step are rows with "queued, not sent" and
`deferred`, and the next pass sends them (`DeliveryDeferred`, timeline "delivery pass"). A row still
"not sent: the delivery stopped before this person" after the last pass is retried by the recall.
Two villages alerting at once share Telegram's 30 a second, so some 429s are expected then. Voice provider errors: check
the Exotel dashboard (balance, KYC, caller id). Then re-send from the console if the alert is still
relevant.

**Who to call.** On-call engineer. Exotel support for voice provider errors.

**Tell the DDMA?** Yes, if more than a few people in one village were not reached on a live Warning or
Critical: the pradhan should be phoned to pass the warning on.

### pukaar-<stage>-unacknowledged-alerts

**What it means.** Delivered alerts are still unacknowledged across two sweeps: people got the message
but nobody pressed "मिल गया".

**First 3 checks.**
1. The alert's Deliveries: who has not acknowledged, and on which channel.
2. Whether the recall round ran (timeline "re-sent").
3. Whether the village relays (pradhan, gauge reader, task force) acknowledged: they pass it on by siren
   and megaphone.

**Fix.** Phone the relays first. If it was a drill, note it in the drill log; repeated silence from
the same people is a number-hygiene task.

**Who to call.** DEOC duty officer (this is an operations alarm more than a technical one).

**Tell the DDMA?** Yes for a live alert: they decide whether to send someone.

### pukaar-<stage>-rollcall-need-help

**What it means.** Someone answered "मदद चाहिए" (need help) in a safety roll-call, or pressed 2 on a
voice call.

**First 3 checks.**
1. Console, Roll-call board: need-help comes first, with a first name and time.
2. The village's report feed for a need-help report with a note.
3. Who is on duty (`/roster`).

**Fix.** This is a person, not a fault: the duty officer calls back or sends the task force. Record the
outcome on the board.

**Who to call.** DEOC duty officer at once.

**Tell the DDMA?** Yes, always.

### pukaar-<stage>-report-surge

**What it means.** Villager reports are arriving over a rate limit: more than 5 from one source (a
salted IP hash) or more than 30 from one village in 10 minutes. Every report is kept; the excess is
held for an officer, never auto-verified and never sent to a model. It is either abuse (a script) or a
real event with many people reporting at once.

**First 3 checks.**
1. Console report feed: the banner "possible duplicate or flood of reports", the held cards and their
   flags (many from one source, same phone or network, sudden flood from this village).
2. Is the village at Watch or above, or raining hard? Many genuine reports in a real event look like this.
3. API logs: `msg = "report held: over rate limit"` with `reason` and the counts (no IPs are logged).

**Fix.** A real event: officers read the held reports and verify the true ones (that is what makes
them count). Abuse: mark the junk `false`; nothing else is needed because held reports never raise a
level. A sustained attack: raise the API Gateway route throttle only if villagers are being refused
(429s); the lasting fix is AWS WAF rate-based rules in front of the API (CloudFront), see
docs/SECURITY.md. Limits are `PUKAAR_REPORT_LIMIT_PER_SOURCE`, `PUKAAR_REPORT_LIMIT_PER_VILLAGE` and
`PUKAAR_REPORT_WINDOW_MINUTES` on the API function.

**Who to call.** DEOC duty officer to read the reports; on-call engineer if it looks like abuse.

**Tell the DDMA?** Yes, if it is a real event (they will want the reports); no for obvious junk.

### pukaar-<stage>-nobody-on-duty

**What it means.** A district has no officer on the duty roster for the shift running now (IST).
Approvals go to the village's fallback officer list instead, which may be people who are asleep or away.

**First 3 checks.**
1. `/roster` for the district: today's day and night shifts.
2. Whether a handover was missed ("taking over" in the audit trail).
3. Whether anything is pending approval right now.

**Fix.** An officer fills the shift in `/roster` (or takes it over). The alarm sends an OK message when
the shift is filled.

**Who to call.** DEOC duty officer or the DDMO, who owns the roster.

**Tell the DDMA?** Yes: the roster is theirs.

### pukaar-<stage>-alert-unanswered

**What it means.** Nobody in the duty chain answered a live alert: every officer timed out (a Watch or
Warning, or a Critical with critical auto-send off). Nothing has gone to the village. Pukaar has just
sent the last call: every officer on duty for the district and the ADM or DM got "nobody approved; it
was not sent" on Telegram and Web Push with a fresh one-tap link, and the ADM or DM was phoned if voice
is on and their number is set. The link works for one more window (5 minutes for a Critical, 10
otherwise); then the alert expires and the sweep asks again (a Critical on the next sweep, a Warning
after 30 minutes, a Watch after 60).

**First 3 checks.**
1. The console: is the alert back on the approval card, and has anyone opened it? The timeline's
   "unanswered" line says who was told, on which channel, and whether the ADM or DM was phoned
   ("call=not possible (...)" says why not).
2. `/roster`: who is on duty now, and is an ADM or DM named? "no ADM or DM on the roster" in the
   timeline means nobody above the chain was told.
3. The officers' channels: is each officer's Telegram linked and a phone turned on for approval
   alerts in the console? Is there a number on file for the wake-up call (`make officer-phone OFFICER=<name>
   PHONE=show`)?

**Fix.** Phone the DEOC landline now and read out the village and level: the officer on duty approves
or declines from the console or the link. Afterwards, find out why nobody answered (asleep, phone
silent, wrong person on the roster) and fix the roster or the officer's channels. Repeated alarms in
one shift mean the chain is not real; take it to the DDMO.

**Who to call.** The DEOC duty officer, then the ADM or DM, by phone, at once, day or night.

**Tell the DDMA?** Yes, every time: a warning nobody approved is the failure the shadow pilot exists to
find. Note it in the after-action review.

### pukaar-<stage>-gauge-unhealthy

**What it means.** An installed river gauge has been unhealthy for two sweeps in a row (30 minutes):
silent, low on battery, or sending mostly bad readings. Simulated gauges never count. The village is
still watched on the forecast, but the observed river level is missing or untrustworthy. The alarm
sends an OK message when the gauge recovers.

**First 3 checks.**
1. `/how#sensors`: which gauge, and its reasons (`silent`, `low_battery`, `bad_quality`), last reading time,
   battery voltage and firmware.
2. Gauge-ingest logs (`/aws/lambda/pukaar-gauge-ingest-<stage>`) and the IoT topic rule's errors in the
   worker DLQ: are readings arriving and being refused, or not arriving at all?
3. The local network: is the SIM topped up, is there mobile signal at the site?

**Fix.** Refused readings: check the device's clock and certificate (`make gauge-provision`). Silent:
ask the gauge reader to check power and the antenna; replace the battery or SIM. Bad readings: debris
under the sensor or a moved mount; clean or re-level it and re-survey the datum.

**Who to call.** The gauge reader of the village (phone), then the on-call engineer.

**Tell the DDMA?** Yes, in the monsoon or if the village is at Watch or above: its observed river level
is not available until the gauge is fixed.

### pukaar-<stage>-siren-offline

**What it means.** An installed siren node or pradhan box has not been heard on any path (cell, LoRa or
SMS) for two sweeps in a row (30 minutes). A device counts as offline when nothing has arrived from it for
20 minutes; simulated devices (`-sim`) never count. The village is still warned by phone and relays, but
its outdoor siren may not sound. The alarm sends an OK message when the device is heard again. Nothing in
the alarm layer has been tested on hardware yet (docs/hardware/ALARM.md).

**First 3 checks.**
1. `/how#sensors`, "Sirens and devices": which device, its health and reasons, last seen and on which path,
   state of charge, faults, last test.
2. Are all devices in the area offline at once? Then it is the mobile tower or a LoRa relay, not the node
   (the FloodNet triage rule). Check the other devices of the village and its neighbours.
3. Device-ingest logs (`/aws/lambda/pukaar-gauge-ingest-<stage>`, "device" lines) and the worker DLQ:
   are heartbeats arriving and being refused (`DeviceRejected`), or not arriving at all? A presence
   "disconnected" on its own is not offline; 20 minutes of silence is.

**Fix.** Refused messages: check the device's certificate and thing (`make device-provision`), and its
clock. Silent: ask the pradhan to look at the box's link LED and the siren cabinet (power, solar panel,
battery, SIM balance, antenna); low state of charge means the panel is shaded or the battery is worn.
Replace the SIM, battery or controller from the district spares.

**Who to call.** The pradhan of the village (phone), then the local technician, then the on-call engineer.

**Tell the DDMA?** Yes, in the monsoon or if the village is at Watch or above: its siren may not sound
until the device is back. Tell the pradhan to use the hand-crank siren and megaphone.

### pukaar-<stage>-siren-test-failed

**What it means.** A siren node reported a failed self-test: the weekly silent test into the dummy load
(amplifier current, SD clip digests, audio player reply, LoRa self-loop, modem, microphone noise floor,
state of charge) or an audible test (current draw or the sound-level rise was outside the expected
range). Device ingest emits `SirenTestFailed`; the device's health becomes "fault" until a test passes.

**First 3 checks.**
1. `/how#sensors`: the device's last silent and audible test, their detail and measurements (amplifier
   current against its reference, SPL rise against the minimum).
2. The device's events (`GET /devices/{id}/events?type=test_result`): is it one failure or a run of
   them? Which part failed?
3. Its faults and state of charge in the last heartbeat (`amp_open`, `mic_dead`, `battery_low`, tamper).

**Fix.** One failed silent test with a good audible test since: watch the next weekly test. Amplifier
current out of range: check the fuse, the 24 V boost and the horn wiring; replace the amplifier board.
Clip digest mismatch: push the audio catalog again. Microphone dead with current fine: the siren still
counts as verified on current alone; replace the microphone on the next visit.

**Who to call.** The local technician, then the on-call engineer.

**Tell the DDMA?** Yes, if the audible path (amplifier or horns) failed: the village's siren may be
silent. No, for a microphone-only fault.

### pukaar-<stage>-siren-unconfirmed

**What it means.** A siren was commanded (an approved alert, the failsafe, a recall, an officer's manual
sound) and did not report "verified" (current draw plus sound rise) within 180 seconds. The siren check
runs in the workflow's Recall step and in every sweep; it marks the command `not_confirmed`, tells the
duty officer on Telegram and Web Push ("थुनाग का सायरन पुष्टि नहीं कर पाया: प्रधान को फ़ोन करें · SMS से
भेजें") and adds a timeline entry. Recall re-issues the command with a new id and counter.

**First 3 checks.**
1. The alert's siren tier in the console (`GET /alerts/{id}/sirens`): commanded, started or nothing?
   A command that never started means the node did not get it; started but not verified means it got it
   and the evidence was missing.
2. The device on `/how#sensors`: last seen, path, faults. An offline node explains it
   (`pukaar-<stage>-siren-offline`).
3. The device's events: `rejected` with `bad_sig`, `expired` or `replayed` means a key, clock or counter
   problem, not a dead siren.

**Fix.** Phone the pradhan first: is the siren sounding? If not, the officer sends the signed SMS from
the console's "SMS से भेजें · Send by SMS" button (their phone number must be allow-listed on the node),
and the pradhan uses the key switch, the hand-crank siren and the megaphone. Afterwards fix the cause
(see siren-offline and siren-test-failed).

**Who to call.** The pradhan, at once; then the local technician.

**Tell the DDMA?** Yes, every time it happens during a real alert: the village did not get its outdoor
warning from the siren. No, for a drill or test, but note it in the drill log.

### pukaar-<stage>-canary-failed

**What it means.** The 15-minute canary (`pukaar-canary-<stage>`) found the public face of Pukaar
broken, from outside: `/health` not ok, `/public/overview` malformed or with no forecasts stored in 24
hours, the CAP feed not an Atom feed, or the web app not served. Each check is tried twice before it
counts. The alarm also fires when no canary result arrived in 30 minutes (the canary or its schedule is
broken), and sends an OK message when it passes again.

**First 3 checks.**
1. Canary logs (`/aws/lambda/pukaar-canary-<stage>`): the "canary failed" line names each failed check
   and why (HTTP status, timeout, shape).
2. Dashboard: `CanaryFailed` and the API's 4xx and 5xx; `pukaar-<stage>-api-5xx` and
   `sweep-heartbeat` usually fire with it when the API or the sweep is the cause.
3. Open the site and `/public/overview` yourself; for the web app, check the Amplify branch's last
   deployment.

**Fix.** API errors: see `api-5xx`; roll back a bad deploy. `forecast_checks_24h` 0: the sweep is not
storing forecasts (see `sweep-heartbeat`). Web app: redeploy it (`make deploy-web`). No result at all:
check the `pukaar-canary-<stage>` schedule is enabled and the function's last error.

**Who to call.** On-call engineer.

**Tell the DDMA?** Yes, if the public pages or the CAP feed are down for more than 30 minutes in the
monsoon: villagers and SACHET cannot see the levels. No, for a canary that only stopped running.

## Report abuse: what officers see

- A report over a rate limit is kept and shown with "Held for review: too many reports from one
  source" (or "sudden flood of reports from this village"). The villager's tracking page says it is
  being checked. It counts towards a level only after an officer verifies it.
- "Same phone or network as a recent report" links to the earlier report.
- "Not confirmed by the nearby report: same network" (or same phone, sender unknown) says why two
  agreeing reports did not verify each other. Two genuine neighbours on one mobile network can get
  this; verify them by hand.
- A matching photo shows "Photo agrees, officer to confirm": a photo alone no longer verifies a report.

## After an alert: "was this real?"

When an alert closes, the officer who handled it answers "Was this real?" under the alert in the
console: **Real flood**, **No flood** or **Unknown**. Answer within 48 hours, after talking to the
pradhan or the gauge reader; change it later if news arrives (each change is on the timeline and in
the audit trail). The answer appears in the after-action report and feeds the false-alarm rate per
rule on `/pilot` and `GET /public/pilot-metrics` (counts only). Replays and drills cannot be answered.

Review the per-rule numbers monthly in the monsoon. A rule with a high false-alarm rate is a
threshold to recalibrate with the DDMA, not a rule to switch off quietly.

## The duty officer's day

**08:00 IST: the health digest.** The first sweep after 08:00 IST sends each district's digest once, on
Telegram and Web Push, to the officers on duty for the day shift (the roster; the village fallback list
when nobody is rostered): when the sweep last ran and which villages have stale or missing data, the
gauges and sirens that are unhealthy (simulators named as such), the open alerts, and the readiness gaps
(an empty shift in the next 24 hours, a village with nobody enrolled or no relay, an unacknowledged
handover). The roster page shows the same digest under "The 08:00 health digest"; the audit trail has
one `duty_digest_sent` row per district. Act on the gaps the same morning: fill the roster, ask the
pradhan to enrol households, test the siren that is overdue. `PUKAAR_DUTY_DIGEST=false` stops it;
`PUKAAR_DUTY_DIGEST_HOUR_IST` moves it.

**Each shift: the handover note.** Before leaving, the outgoing officer writes on the roster page what
the next shift must know (a silent gauge, a blocked road, an alert still open, a call to return). An
officer of the incoming shift reads it and presses "Read: acknowledge"; the writer cannot acknowledge
their own note, and an acknowledged note cannot be changed. Both are in the audit trail
(`handover_written`, `handover_acknowledged`). A note left unacknowledged shows as a gap in the next
digest.

**Paging beyond e-mail.** Every alarm on `pukaar-alarms-<stage>` (and its return to OK) also goes to the
primary and backup officer on duty, on Telegram and Web Push: in the district the alarm names (its
`District` dimension, as on `nobody-on-duty`), or in every district when it names none. The escalation
officer (ADM or DM) is not paged for an alarm; they are phoned for an unanswered alert. Each page is in
the audit trail (`alarm_paged`). Officers who have not linked Telegram (Console, Settings) and turned on
Web Push get only the e-mail.

## Valley-wide events: grouped approval

When several villages of one district wait together from the same cause (the July 2023 replay raised 4
of 5 at once), the inbox shows "N villages of <district> are waiting together" and "Review as a group".
The group page shows the evidence they share first, then each village's level and exact message, each
one approved unless you mark it declined. One hold-to-approve decides them all. Underneath, nothing is
merged: each village is checked by Cedar on its own (your district), audited on its own and decided with
its own approval token, so a village outside your district comes back "not allowed" and the others go
ahead; a village that timed out to the next officer comes back "too late". Open a village alone ("Open
alone") whenever its message needs an edit first. The audit trail has one `group_decision` row besides
each village's own.

## Asking HPSDMA for SACHET or cell broadcast

Pukaar cannot issue on SACHET or cell broadcast; only HPSDMA (and the national agencies) can. For an
approved Warning or Critical, the alert's record in the inbox has "Request SACHET / cell broadcast":
it prepares a CAP 1.2 file (a polygon of the chosen radius around the village, the LGD district code,
Hindi and English), the cell-broadcast text in Hindi (UCS-2) and English (GSM 7-bit), each within four
CBS pages, and the steps. Then:
1. Phone the HPSDMA State Emergency Operation Centre (1070) and say the request is coming.
2. Download the CAP file and e-mail it with the texts ("E-mail it" opens a ready e-mail; set the address
   HPSDMA agreed with `PUKAAR_SACHET_REQUEST_EMAIL`).
3. Ask HPSDMA to confirm when it went out, and write that in the handover note: Pukaar does not know
   whether or when a broadcast was sent, and never says it was.
4. Keep calling the households that did not confirm; cell broadcast does not say who heard.
5. When the village is back to normal, send HPSDMA the cancel the same way.
Every preparation (view, download, copy, e-mail) is in the audit trail (`sachet_request_prepared`) and
on the alert's timeline. SACHET's own alerts for Himachal come in as evidence: they show in the
decision's evidence as "SACHET (NDMA) alerts" and raise a level only when official data may
(`PUKAAR_OFFICIAL_RAISES_LEVEL`).

## Enrolling households

EWS1294's lesson (Cambodia): enrolment, not the phone, leaves people out. Four ways in, each with the
notice and an audited consent record:
- **Telegram**: `/start <village code>` and "I agree" (the person themselves).
- **The console's Enrol page** (officers for their district, the pradhan for their own village): read the
  notice aloud, then add the household: name (optional), mobile number, role, "assisted" (elderly,
  disabled, no phone of their own), how consent was given (in person, a signed or thumb-printed form, a
  phone call), by whom (the person, a family member, a guardian) and who took it. A number already
  enrolled in the village is refused. Removing a household erases what is left of it later.
- **A vetted list (CSV)** from the panchayat or patwari: paste or choose the file and press Preview: each
  row is checked (the number, duplicates in the file and in the village, the consent columns) and
  errors are shown per row. Tick "consent attested" only for households that agreed themselves, name the
  list, and enrol: nothing else is stored.
- **By phone** (when voice is on): the household calls the service number, hears the notice, presses 1
  and keys in the village code shown on the Enrol page (docs/VOICE.md, "Inbound calls").
Check coverage against the household list, not the count of numbers: the digest names villages with
nobody enrolled and villages with no pradhan, gauge reader or task force enrolled.

## Drills

| When | What | Who |
|---|---|---|
| Monthly, October to May | `make drill VILLAGE=<id> LEVEL=watch CHANNEL=all`, one village a month in rotation | On-call engineer and DEOC duty officer |
| Weekly, 1 June to 30 September | the same, rotating villages, plus `CHANNEL=voice` once a month for the consented voice households | same |
| Before the monsoon | a full drill in every village, Watch, all channels | with the pradhans |

Every drill is labelled "अभ्यास (DRILL)" on every channel and is never counted as a live alert.

**Sirens in a drill.** A drill alert sounds pattern **D1** only (the "अभ्यास" voice first, one W1 cycle,
then "यह अभ्यास था"); Cedar refuses `sound_siren` for a drill, so a drill can never play a real warning.
A monthly test is **T1** (three short beeps at half volume and the test clip) or D1, between 09:00 and
18:00 IST, and never C1. One C1 cycle inside D1 is played only at the announced pre-monsoon drill, with
the DDMA's consent. A replay never sounds a real siren (only `-sim` devices). Record in the drill log:
approval to siren started (target 60 s or less), siren verified (target 100%), the volunteer's SPL
reading at the farthest house, and how many of 5 or 6 households recognised the pattern
(docs/field/drill-plan.md).
Announce the day and hour to the pradhan in advance and never drill during real bad weather.

**Time it to acknowledgement.** The clock starts when the drill alert is created and stops at the
first "मिल गया". Read it from the after-action report ("Key times"): level rose, approved, first
voice on a phone, first acknowledgement. Record in the drill log:

| Date | Village | Channel | Approved after | First voice after | First ack after | Reached / acknowledged | Notes |
|---|---|---|---|---|---|---|---|

`/pilot` shows the same numbers for all drills (`drills` in `GET /public/pilot-metrics`). Targets for
the pilot, to agree with the DDMA: approval within 10 minutes, first voice within 2 minutes of
approval, half the reached phones acknowledged within 15 minutes.

## Restore drill (quarterly)

Point-in-time recovery is on for the table, but a backup nobody has restored is a hope. Once a quarter,
and before each monsoon, run:

```
make restore-drill                 # dev; STAGE=prod for the pilot stack
make restore-drill AT=2026-10-22T04:00:00Z   # a chosen moment instead of the latest restorable time
```

`scripts/restore_drill.py` restores `pukaar-<stage>` into a scratch table named
`pukaar-<stage>-restore-drill-<UTC time>`, waits until it is active, counts the items under each key
prefix (`VILLAGE#`, `ALERT#`, `REPORT#`, ...) in both tables, prints the counts side by side, and
deletes the scratch table, even if a step failed (`KEEP=1` keeps it for a look; then delete it by
hand). It only reads the live table. PASS means every prefix of the live table is in the copy, each
count within 10 % (new writes and TTL deletions since the restore point explain small differences).
Write the date, the restore time it printed and PASS or FAIL in the drill log. A FAIL, or a restore
that takes more than an hour, goes to the on-call engineer and AWS support.

To recover for real, restore the same way into a new table, check it, then point the stack at it: the
table name is `pukaar-<stage>`, so either restore under that name after deleting the broken table
(downtime) or change `PUKAAR_TABLE_NAME` on every function to the restored copy and deploy.

## Phone-number hygiene

**Quarterly (January, April, July, October), through the pradhan.**
1. `make voice-list VILLAGE=<id>` prints each registered number masked, with its consent note.
2. Go through the list with the pradhan by phone or in person: still this household? still this number?
   still willing?
3. Re-confirmed: write the date in the paper register, and update the note in Pukaar by removing and
   adding the number again with the new note, e.g. `CONSENT="verbal 2026-10-25, reconfirmed via pradhan
   2027-01-12"`. Wrong number or no longer willing: `make voice-remove VILLAGE=<id> ID=<recipient id>`
   only.
4. Telegram recipients who blocked the bot show a failed delivery with Telegram's "bot was blocked by
   the user"; remove them.

**After every alert or drill.** Numbers the voice call could not reach after three attempts are flagged
"unreachable" on the alert and sent to the pradhan. Within a week the pradhan checks each one. A number
unreachable on two alerts or drills in a row is removed until the household gives a new one.

Never collect numbers from a list or a third party without the household's own consent. A panchayat or
patwari list is only a starting point: it goes through the vetted import (below, "Enrolling households"),
and a row is stored only when the officer attests that the household itself agreed after hearing the notice.

## Consent records

Each recipient has a consent note (how, when, who asked). Keep the signed or witnessed register with
the pradhan as well; the note in Pukaar is a pointer to it, not a replacement.

**Notice to read or give before registering anyone** (Digital Personal Data Protection Act, 2023;
the DDMA is the data fiduciary. Have the DDMA's legal officer review this text before use; it is a
draft, not legal advice.)

> **पुकार: आपकी जानकारी के बारे में सूचना**
>
> ज़िला आपदा प्रबंधन प्राधिकरण (DDMA) बाढ़ की चेतावनी देने के लिए "पुकार" चलाता है। आपकी सहमति से हम
> ये जानकारी रखेंगे: आपका नाम, आपका फ़ोन नंबर या टेलीग्राम खाता, और आपका गाँव। अगर आप कोई सूचना भेजते हैं, तो
> उसमें लिखी बात, आवाज़, फ़ोटो और जगह भी रखी जाएगी।
>
> इसका इस्तेमाल सिर्फ़ इन कामों के लिए होगा: आपको बाढ़ की चेतावनी और "सब ठीक है" का संदेश भेजना, आपसे पूछना कि
> आप सुरक्षित हैं या नहीं, और आपकी भेजी सूचना पर कार्रवाई करना। यह जानकारी किसी को बेची या किसी और काम के
> लिए नहीं दी जाएगी। फ़ोन नंबर किसी सार्वजनिक पेज पर नहीं दिखता।
>
> आप कभी भी सहमति वापस ले सकते हैं: प्रधान को बताएँ या DDMA नियंत्रण कक्ष को फ़ोन करें। तब आपका नंबर
> हटा दिया जाएगा और आगे संदेश नहीं आएँगे। आप अपनी जानकारी देखने, सुधारने या मिटाने को भी कह सकते हैं। शिकायत
> के लिए: DDMA शिकायत अधिकारी ______ (फ़ोन ______)। संतुष्ट न हों तो आप भारत के डेटा संरक्षण बोर्ड से शिकायत
> कर सकते हैं।
>
> पायलट ख़त्म होने के 30 दिन के भीतर, या आपके कहने पर, आपकी जानकारी मिटा दी जाएगी।

> **Pukaar: notice about your information**
>
> The District Disaster Management Authority (DDMA) runs Pukaar to give flood warnings. With your
> consent we keep: your name, your phone number or Telegram account, and your village. If you send a
> report, we also keep its words, voice note, photo and location.
>
> We use them only to send you flood warnings and the all-clear, to ask whether you are safe, and to
> act on reports you send. They are never sold or used for anything else. Your number never appears
> on a public page.
>
> You can withdraw consent at any time: tell the pradhan or phone the DDMA control room. Your number
> is then removed and no more messages come. You can also ask to see, correct or erase your
> information. Grievances: DDMA grievance officer ______ (phone ______). If you are not satisfied you
> can complain to the Data Protection Board of India.
>
> Your information is erased within 30 days of the pilot ending, or sooner if you ask.

What the system does today, so the notice stays true: numbers and chat ids are in the encrypted table
and never on a public route (`tests/test_public_privacy.py`); report sources are kept only as salted
hashes; reports have no automatic expiry yet, so erasing at the end of the pilot is a manual task on
this list. The table is in `us-east-1`; a government pilot will likely require `ap-south-1`.

## Secret rotation

Rotate on a schedule (yearly) and at once if a secret may have leaked (a laptop lost, a log or
screenshot shared, someone leaves). All live in SSM SecureString under `/pukaar/`; functions cache
reads for 5 minutes, so a change reaches every warm Lambda within 5 minutes.

| Secret | How to rotate | What breaks meanwhile |
|---|---|---|
| Telegram bot token (`telegram_token`) | BotFather: `/revoke` the bot's token, then `make secrets` and paste the new one; it stores the token, a new webhook secret and calls `setWebhook` | Sends fail (DeliveryFailed) for up to 5 minutes; nobody else can send as Pukaar once revoked |
| Telegram webhook secret | `make secrets` (always makes a new one with the token) | None |
| Approval-link secret (`link_secret`) | `ROTATE_LINK_SECRET=1 make secrets` | Open one-tap approval links stop working; officers use the console |
| VAPID keys (Web Push) | `make vapid-keys ROTATE=1` | Officers' phones must turn approval alerts on again in the console |
| Voice webhook key (`voice_webhook_key`) | Put a new key (docs/VOICE.md, "The SSM parameters"), run `make voice-urls`, paste the three URLs into the Exotel flow, save | Calls placed in the gap fail their key check (403); rotate outside a Watch |
| Exotel API key and token | Exotel dashboard, API settings: generate new credentials, put `exotel_api_key` and `exotel_token`, then revoke the old ones | None if done in that order |
| Plivo auth token | Plivo console: rotate, then put `plivo_auth_token` | Plivo signature checks fail until updated |
| Report salt (`report_ip_salt`) | `ROTATE_REPORT_SALT=1 make secrets` | Rate windows restart; reports before and after cannot be matched as the same source (intended) |
| Device root secret (`device_root`) | Not by overwriting: every siren, box and gauge key is derived from it (docs/SECURITY.md, "Device signing"). Bump each device's `kid`, deliver the new keys (flash, or an IoT Job over TLS once firmware exists), then switch `config.kid`; only then put a new root | A root changed under live devices makes every signed command fail (`rejected: bad_sig`) until the devices hold keys from the new root |

Write each rotation in the incident log (date, who, why). Never paste a secret in chat, a ticket or a
commit.

## Monsoon pre-season checklist (by 15 May)

- [ ] The alarm topic has the on-call phone (SMS) and e-mail subscribed, and each was tested
      (`aws cloudwatch set-alarm-state --alarm-name pukaar-<stage>-sweep-heartbeat --state-value ALARM --state-reason test`).
- [ ] The "Who to call" table is filled in and on the DEOC wall.
- [ ] The duty roster is filled to the end of June, with the ADM or DM as escalation; `nobody-on-duty` is OK.
- [ ] Every village's thresholds and river cell reviewed with the DDMA; changes recorded with a date.
- [ ] Gauges: batteries, solar, mount height and datum checked on site; `/how#sensors` shows each healthy.
- [ ] Sirens and pradhan boxes (where installed): `/how#sensors` shows each `ok`; a silent test passed this
      week and an audible test this month; batteries, panels, earthing (10 ohm or less) and surge
      protectors checked; SPL at the farthest covered house re-measured (ambient + 10 dB, or the house is
      marked "phone and relay only"); the officers' numbers are on each node's SMS allow-list.
- [ ] `/pukaar/device_root` exists (`aws ssm get-parameter --name /pukaar/device_root`, without
      `--with-decryption`); without it no siren command can be signed.
- [ ] Quarterly number review done in every village (above); unreachable numbers resolved.
- [ ] Consent notice re-read to new households; register up to date.
- [ ] Secrets older than a year rotated.
- [ ] A restore drill passed this quarter (`make restore-drill STAGE=prod`, "Restore drill" above).
- [ ] A full drill in every village, timed to acknowledgement, and the numbers written in the drill log.
- [ ] Last season's alerts each have a "was this real?" answer; per-rule false-alarm rates reviewed with the DDMA.
- [ ] The pilot runs on the prod stack (`make deploy STAGE=prod`, docs/DEPLOY.md "Production stage"):
      `ReplayEnabled=false`, no demo accounts, TOTP MFA required, `RetentionDays` set, the DDMA's CAP sender.
- [ ] Report salt exists (`aws ssm get-parameter --name /pukaar/report_ip_salt`); without it no report auto-verifies.
- [ ] Security headers live: `curl -sI https://<web url> | grep -i -e content-security -e strict-transport`.
- [ ] AWS budget alarm set; Exotel balance topped up for the season.
