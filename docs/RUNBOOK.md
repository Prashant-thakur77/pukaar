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
| Logs | `/aws/lambda/pukaar-api-<stage>`, `pukaar-sweep-<stage>`, `pukaar-workflow-<stage>`, `pukaar-worker-<stage>`, `pukaar-gauge-ingest-<stage>`; Step Functions `/aws/vendedlogs/states/pukaar-approval-<stage>` |
| Console | `/console` (approvals, villages, reports, roll-call), `/roster`, `/audit`, `/sensors` |
| Queues | `pukaar-sweep-dlq-<stage>`, `pukaar-worker-dlq-<stage>` |
| Alarm topic | SNS `pukaar-alarms-<stage>`; subscribe the on-call phone (SMS) and e-mail. With no subscriber nobody hears an alarm |

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
2. The alert in the console (`/console`, Approvals and Recent alerts): its status and timeline.
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
Blocked by the user: nothing to fix; remove them at the next number review. 429: the recall step
retries; for large lists, see "Delivery does not scale" in the scorecard. Voice provider errors: check
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

## Drills

| When | What | Who |
|---|---|---|
| Monthly, October to May | `make drill VILLAGE=<id> LEVEL=watch CHANNEL=all`, one village a month in rotation | On-call engineer and DEOC duty officer |
| Weekly, 1 June to 30 September | the same, rotating villages, plus `CHANNEL=voice` once a month for the consented voice households | same |
| Before the monsoon | a full drill in every village, Watch, all channels | with the pradhans |

Every drill is labelled "अभ्यास (DRILL)" on every channel and is never counted as a live alert.
Announce the day and hour to the pradhan in advance and never drill during real bad weather.

**Time it to acknowledgement.** The clock starts when the drill alert is created and stops at the
first "मिल गया". Read it from the after-action report ("Key times"): level rose, approved, first
voice on a phone, first acknowledgement. Record in the drill log:

| Date | Village | Channel | Approved after | First voice after | First ack after | Reached / acknowledged | Notes |
|---|---|---|---|---|---|---|---|

`/pilot` shows the same numbers for all drills (`drills` in `GET /public/pilot-metrics`). Targets for
the pilot, to agree with the DDMA: approval within 10 minutes, first voice within 2 minutes of
approval, half the reached phones acknowledged within 15 minutes.

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

Never collect numbers from a list or a third party; every number comes from the household itself, with
consent recorded.

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

Write each rotation in the incident log (date, who, why). Never paste a secret in chat, a ticket or a
commit.

## Monsoon pre-season checklist (by 15 May)

- [ ] The alarm topic has the on-call phone (SMS) and e-mail subscribed, and each was tested
      (`aws cloudwatch set-alarm-state --alarm-name pukaar-<stage>-sweep-heartbeat --state-value ALARM --state-reason test`).
- [ ] The "Who to call" table is filled in and on the DEOC wall.
- [ ] The duty roster is filled to the end of June, with the ADM or DM as escalation; `nobody-on-duty` is OK.
- [ ] Every village's thresholds and river cell reviewed with the DDMA; changes recorded with a date.
- [ ] Gauges: batteries, solar, mount height and datum checked on site; `/sensors` shows each healthy.
- [ ] Quarterly number review done in every village (above); unreachable numbers resolved.
- [ ] Consent notice re-read to new households; register up to date.
- [ ] Secrets older than a year rotated.
- [ ] A full drill in every village, timed to acknowledgement, and the numbers written in the drill log.
- [ ] Last season's alerts each have a "was this real?" answer; per-rule false-alarm rates reviewed with the DDMA.
- [ ] `ReplayEnabled=false` on the pilot stack; demo accounts deleted; officers use MFA.
- [ ] Report salt exists (`aws ssm get-parameter --name /pukaar/report_ip_salt`); without it no report auto-verifies.
- [ ] Security headers live: `curl -sI https://<web url> | grep -i -e content-security -e strict-transport`.
- [ ] AWS budget alarm set; Exotel balance topped up for the season.
