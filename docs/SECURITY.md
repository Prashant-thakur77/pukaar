# Security: report abuse, data protection, device signing and browser headers

Three protections for a public pilot: the anonymous report page cannot be used to raise a public level
or to crowd villagers out, nobody can sound a siren without a command signed for that one device, and
the web app tells browsers what it may load. Operations (what to do
when the report-surge alarm fires) are in [RUNBOOK.md](RUNBOOK.md).

## Report-abuse protection

The report page is anonymous and its GPS comes from the phone. Before this change two forged reports
300 m apart, posted by one script, verified each other and set the village to Warning on the public
site; and one shared throttle of 5 requests a second could be used up by that script.

Code: `backend/src/Pukaar/services/report_guard.py`, used by `services/reports.py`.
Tests: `backend/tests/test_report_abuse.py`.

### Who sent it, without keeping who sent it

The API takes the caller's IP from API Gateway's request context (never from a header the client can
set) and the two random ids the report page keeps (`device_id` in localStorage, `session_id` in
sessionStorage; `frontend/src/lib/reporter.ts`). It stores four HMAC-SHA256 values, cut to 64 bits:

| Field | Hash of |
|---|---|
| `source.ip` | the IP |
| `source.net` | its /24 (IPv4) or /64 (IPv6) |
| `source.device` | the device id |
| `source.session` | the session id |

The salt is SSM SecureString `/pukaar/report_ip_salt` (`make secrets` creates it). No raw IP is stored
or logged; the hashes are never returned by any route, officers' included; officers see only the
flags they produce. If the salt cannot be read the hashes are left empty, the report is flagged
"sender unknown", and it can never corroborate another report: missing configuration makes the
system stricter, not looser. Rotating the salt (`ROTATE_REPORT_SALT=1 make secrets`) unlinks old
hashes from new ones.

### Independent corroboration

A report raises a level only once it is verified. Code verifies it (`verified_auto`) only when a
second report of the same type, within 500 m and 30 minutes, is independent of it:

- a different IP **and** a different network range;
- a different device id **and** a different session id (both must be present);
- both GPS fixes plausible: inside the village radius (5 km), not 0,0, and not within 10 m of the
  village point the public API publishes (a forger's obvious copy).

When an agreeing nearby report fails one of these, the report carries
`corroboration_rejected:<why>` and the officer sees "Not confirmed by the nearby report: same
network". A photo the model says matches no longer verifies a report on its own (it is flagged
"Photo agrees, officer to confirm"): one forged report with a downloaded photo must not raise a
public level. Officer verification is unchanged and always counts.

A real limit: two genuine neighbours on the same mobile network can share a public IP range
(carrier-grade NAT). Their reports then wait for an officer instead of verifying each other. That is
the safe direction; the officer verifies them with one tap.

### Rate limits that hold, never drop

Two fixed-window counters in DynamoDB (`RATE#src#<ip hash>` and `RATE#village#<id>`, one atomic `ADD`
each, TTL one day):

| Limit | Default | Setting on the API function |
|---|---|---|
| Reports per source per window | 5 | `PUKAAR_REPORT_LIMIT_PER_SOURCE` |
| Reports per village per window | 30 | `PUKAAR_REPORT_LIMIT_PER_VILLAGE` |
| Window | 10 minutes | `PUKAAR_REPORT_WINDOW_MINUTES` |

A report over a limit is stored like any other and the villager gets a tracking code. It is
**held**: `hold_reason` is `source_rate_limit` or `village_surge`, it is never auto-verified, never
corroborates another report, never goes to Transcribe, a model or the photo describer (a script must
not run up the bill), and counts towards a level only after an officer verifies it. Officers see it
in the report feed with "Held for review: too many reports from one source", and the feed shows a
banner, "Possible duplicate or flood of reports", whenever reports in the last hour share a phone or
network or came in over a limit. `ReportSurge` is emitted and alarmed (`pukaar-<stage>-report-surge`).

The API Gateway throttle on `POST /reports` is now 10 a second (burst 20), still shared by everyone.
The web app treats a 429 like being offline: the report waits in the phone's queue and is sent again,
so a full throttle delays a villager's report but does not lose it. Per-client limits before the
Lambda need AWS WAF rate-based rules, which cannot be attached to an HTTP API. On prod, CloudFront
carries the WAF in front of the API (docs/DEPLOY.md, "AWS WAF on prod"): `POST /reports` 100 per IP
in 5 minutes, 2,000 other requests per IP in 5 minutes (not the signed voice and Telegram webhooks),
and the AWS managed common and IP-reputation rule sets. The API refuses requests that did not come
through CloudFront (the `X-Pukaar-Edge` origin header), so the WAF cannot be gone round, and the
report guard reads the caller's IP from `CloudFront-Viewer-Address`. Dev has no WAF: it bills by
the month. The CSP's `connect-src` gains `https://*.cloudfront.net` on that prod stack only.

## Who may read villagers' data

- **The published demo password.** The README gives the `judge` and `judge_pradhan` password so anyone
  can try the console. Cedar's `public-demo-accounts-replay-only` lets those names act on replays only,
  and read villagers' data from replays only: `view_reports` (words, transcript, exact GPS, photo and
  voice links, name), `view_recipients` (who an alert reached: names, chat ids, call ids),
  `view_rollcall` (names) and `view_after_action` (first names). Their report feed is served with
  replay reports only (`api/auth.py` `Allowed(replay_reads=True)`); a live alert's delivery rows come
  back with the person left out (`masked: true`); a live after-action report is refused.
  `backend/tests/test_public_privacy.py` signs in as both and checks it.
- **The live jury demo** (docs/DEMO_LIVE.md). Jurors join a separate, unlisted demo village by a 4-digit code
  that rotates and expires in 30 minutes, after a Hindi and English notice; nothing is stored before "I agree".
  Their first name and chat id are deleted within 24 hours (the sweep), or at once by "Reset demo". Cedar
  `demo-stays-in-demo` keeps a demo alert in the demo village and every other alert out of it; the public demo
  accounts may watch the presenter screen (counts only) but never see the code or run it
  (`public-demo-accounts-never-run-demo`). `backend/tests/test_live_demo.py`.
- **Pradhans.** No Cedar policy matches a request that names no village. A pradhan's list is asked
  once for each of their own villages, and an alert or report is checked against the village on its
  own record, so another village's alert is refused, not just hidden (`test_policy_tokens.py`).
- **Public pages** carry no officer usernames: an alert says `decided_by_role`, a directive drops
  `issued_by`, and any other "done by" field reads "staff" (`views.scrub_people`).
- **Ask Pukaar** never puts a report's GPS or a recipient's name into the model or the tool trace.
- **Sign-in.** The production stack requires a TOTP code at every sign-in (`RequireMfa=true`, Cognito
  MFA ON, no SMS) and has no demo users; dev keeps TOTP optional (docs/DEPLOY.md, "Production stage").
- **Retention.** With `RetentionDays` set (365 on prod), a report, its photo and its voice note
  expire that many days after they were made (DynamoDB TTL and an S3 lifecycle rule).
- **District scope.** An officer acts (approve, decline, edit, triage, directives, roll-calls, roads,
  shelters, gauges, sirens, the roster) only on villages of a district they are assigned to (their
  `SCOPE` row, `make staff-assign`; the village's officer list; the villages on their sign-in) or rostered
  on from yesterday to tomorrow (`services/scope.py`, Cedar `staff-own-district`). The district comes from
  the village record, never from the request, and a caller cannot claim scope in the context. A state
  (SDMA) operator (group `state_operator`) reads every district and acts only where assigned or
  rostered, never on sirens; a DDMA head (group `ddma_head`) reads their own districts' console, reports,
  roll-calls and roster, and changes their district's settings (critical auto-send), audited. Replays are
  not held to a district: they never reach a phone or a siren. `backend/tests/test_district_scope.py`
  holds the matrix.

## DPDP: consent, leaving and erasure of villagers' data

What the Digital Personal Data Protection Act 2023 asks of a data fiduciary (the DDMA, for a pilot), and
how Pukaar does it for the people it alerts. This is engineering, not legal advice; the notice text and
the retention period are for the DDMA to approve. The rules' core obligations commence about 13 May 2027.

**Notice before consent (Telegram).** `/start <village code>` stores nothing about the person. The bot
answers with a notice in Hindi and English (`templates/hi.enrol_notice`): what is kept (Telegram chat id,
Telegram name, village), why (flood alerts, the all-clear, "are you safe?"; nothing else), for how long
(while registered; erased as below) and how to leave (`/stop` or "बंद करें"). Under it are **✅ सहमत हूँ / I
agree** and **✖ नहीं / No**. Only "I agree" stores the recipient, with a consent record
(`telegram button, telegram-notice-v1, <time>` in `Recipient.consent`). Until then a one-day row holds the
village asked for, and "No" deletes it. Voice-only numbers are added by the operator with the household's
recorded consent (`make voice-add CONSENT=...`), as before.

**Leaving.** `/stop`, or the words "बंद करें" (also "बंद", "stop"), removes the person from every village
at once: the recipient records, the chat's village pointers and any waiting consent or help note. No alert,
all-clear or roll-call reaches them after that. `make voice-remove` does the same for a voice-only number
(for a Telegram-and-calls person it stops the calls and deletes the number from their record).

**Erasure.** What is left of a person after their last village link went is erased
`PUKAAR_UNLINKED_RETENTION_DAYS` days later (30 by default; 0 erases at the next sweep). The sweep runs it
(`services/privacy.run_due`, at most 50 people a run):

| Record | What happens |
|---|---|
| Recipient record (name, chat id, phone, consent) | Deleted at once, on `/stop` or removal |
| Delivery rows of every alert of their villages | Re-keyed under a random pseudonym; name, chat id, call ids and key presses removed. Kept: channel, status, attempts, sent and acknowledged times |
| Per-person counter markers of those alerts | Re-keyed under the same pseudonym, so the alert's counts stay exact |
| Roll-call rows (asked, answered, note) | Deleted (they expire after 30 days anyway) |
| Villager reports in their villages | Their phone number (+91…, 91…, the 10 digits) and chat id replaced by `[removed]` wherever the words, transcript or masked copy hold them; the report stays |
| Audit trail | Untouched (append-only); it never held a villager's chat id or number. One row records the erasure under the pseudonym |

The minimal record kept is the authority's: that an alert reached N people on a channel at a time, and how
many acknowledged. A person who joins again before their erasure runs keeps their history: the pending
erasure is cancelled. `backend/tests/test_telegram_enrolment.py` checks that no chat id is left anywhere in
the table after an erasure.

**Not covered yet.** A household's number given only on paper to the pradhan, a DPIA, a breach-response
plan and the grievance officer's name in the notice are the DDMA's (docs/RUNBOOK.md, consent section).
Officers' own accounts are staff data, managed in Cognito.

## Device signing (sirens, pradhan boxes, gauges)

The alarm layer (docs/hardware/ALARM.md) lets the cloud command outdoor sirens. A siren that sounds on a
forged command, or sounds a stale one hours late, is as harmful as one that stays silent, so every
command is signed for one device and carries a counter and an expiry. None of this has run on hardware
yet: the signing and checks are tested in Python and against a Python siren simulator, and the same
golden vectors (`firmware/test/vectors/protocol_vectors.json`, TEST ONLY keys) are what the firmware
will be tested against.

Code: `backend/src/Pukaar/services/devices/protocol.py` (the one codec and signer for the MQTT command,
the LoRa frame and the signed SMS), `services/devices/keys.py`, `services/devices/siren_model.py` (the
reference verifier), `services/sirens.py`.

**Keys.**
- One root secret, SSM SecureString `/pukaar/device_root` (32 random bytes), made by `make secrets`.
- Each device's key is derived from it, in memory, when needed:
  `K_dev = HKDF-SHA256(ikm=root, salt="pukaar-device-root-v1", info="pukaar-dev|<device id>|<kid>")`.
  Device keys are never stored server side and never logged. A real device gets its key flashed at
  provisioning (with flash encryption and Secure Boot v2 turned on for production); only a labelled
  `-sim` device's key is kept in SSM (`/pukaar/siren/<device>/hmac`), for the simulator.
- Only the API, the approval workflow and the device-ingest function (the gauge-ingest Lambda, which also
  takes device messages) can read the root. The worker function has an explicit Deny on it; the sweep
  has no SSM access at all. A mis-scoped role or a console write to a device shadow cannot sound a siren:
  the siren checks a signature that only these roles can make.
- Rotation and revocation: bump the device's `kid` and deliver the new key, then switch it; revoke a
  stolen device by deactivating its certificate and bumping the `kid` of every receiver that trusted it.

**Why no AWS KMS key.** The spec proposed a KMS HMAC key (`GenerateMac`), which keeps the root inside
KMS. A KMS key costs $1 a month whatever the traffic, and the dev stack must stay free
(`backend/tests/test_template_safety.py`). The SSM root with HKDF gives the same property that matters
here (no role outside the three named ones can make a valid signature) at no cost. Moving prod to a KMS
key behind the prod-only condition is a change to one function (`keys.derive`) and the key policy; it
is not built.

**What a device checks** (the reference verifier, and what the firmware must do):
- the signature: the command's canonical string signed with HMAC-SHA256, the first 16 bytes sent;
- replay: a per-path counter (MQTT, SMS, LoRa) that must go up, and the last 32 command ids. The
  receive counters (and each LoRa sender's) are written through to flash when a message is accepted,
  before the device acts on it, and restored exactly on boot, so a siren that lost power in a flood
  takes its gauge's very next alarm. Power lost between the accept and the write can let that one
  message in twice; its expiry (commands) or 15-minute time window (frames) bounds that. A device's
  own outgoing frame counter is written in batches and skips 16 on boot, so it is never reused;
- expiry: `exp` is at most 30 minutes after issue (sooner if the alert expires first); a command that
  arrives after `exp` is rejected and reported, never sounded late. With no synced clock, `exp` must
  fall within 12 hours of the last known time;
- LoRa frames carry an 8-byte HMAC with the sender's key, a per-sender counter and, when both clocks are
  synced, a timestamp within 15 minutes. A relay stores and forwards frames but holds no keys, so it
  cannot forge one; the cloud verifies every frame forwarded on `pukaar/mesh/...` with the origin's key,
  never the forwarder's;
- signed SMS (`PKR1 <device> <A><L> <ctr> <exp> <sig>`): the sender's number must be on the node's
  allow-list, which holds only salted SHA-256 hashes (no phone number sits in a shadow), then the
  signature, the counter and the expiry, in that order.

**Who can make the cloud sign** (Cedar, `policy/base.cedar`; every decision is written to the audit
trail, and a decision that cannot be audited is a deny):
- the approval workflow, for an approved Warning or Critical, or a Critical sent under the flagged
  critical auto-send. The Critical pattern C1 needs machine evidence at Critical in the decision trace
  or a second, different officer; without either the siren plays W1 (never silence);
- the failsafe, for a critical or already-approved alert;
- an officer by hand: Warning alone, Critical only with a second officer's confirmation within 120 s;
- a pradhan for their own village only; a pradhan's local trigger is propagated to the other sirens of
  the same village only;
- never a replay on a real siren (only `-sim` devices), never `sound_siren` for a drill (drills play D1
  through `test_siren`), never an external CAP alert, and at most 6 sound commands per village per hour.
- The published demo accounts (`judge`, `judge_pradhan`) may see devices but every siren action
  (sound, stop, test, manage) is forbidden to them, live or replay. A model agent can never sound,
  stop, test or manage a device.

**AWS IoT.** Each kind of device has its own IoT policy (`pukaar-siren-<stage>`, `pukaar-box-<stage>`,
`pukaar-relay-<stage>`): a certificate connects only as its own thing, publishes only to its own
`event`, `heartbeat`, `backfill` and mesh `relay` topics, and reads only its own named shadows and jobs.
No `iot:*`, no other thing's topics, no gauge topics. Thing name equals client id equals the device id
in the topic, so the topic is the identity.

## Browser security headers

Amplify sends these on every file (`infra/template.yaml`, `AmplifyApp.CustomHeaders`; checked by
`backend/tests/test_template_safety.py`):

| Header | Value |
|---|---|
| `Strict-Transport-Security` | `max-age=31536000; includeSubDomains` |
| `X-Content-Type-Options` | `nosniff` |
| `X-Frame-Options` | `DENY` (and `frame-ancestors 'none'` below): the approval page cannot be framed |
| `Referrer-Policy` | `strict-origin-when-cross-origin`: one-tap approval tokens in a URL path never leave as a referrer |
| `Permissions-Policy` | `camera=(), geolocation=(self), microphone=(self), payment=(), usb=()` |
| `Content-Security-Policy` | below |

### The Content-Security-Policy, source by source

| Directive | Sources | Why |
|---|---|---|
| `default-src` | `'self'` | everything else |
| `script-src` | `'self'` and two hashes | the bundle; the inline snippet in `frontend/index.html` that applies the saved theme (light on the villager pages unless dark was chosen) before first paint; and the boot painter (`frontend/src/boot/boot.ts`, inlined by `frontend/boot-plugin.ts`) that paints a village's answer before the app's code arrives. No `'unsafe-inline'`, no `'unsafe-eval'` |
| `style-src` | `'self'` and one hash | the bundled CSS, and the build's critical CSS inlined beside the painter; no other `<style>` element |
| `style-src-attr` | `'unsafe-inline'` | inline `style=""` attributes only: the after-action report is e-mail-safe HTML with inline styles, and the console opens it from a `blob:` URL, which inherits this policy. React's style props go through the CSSOM and need nothing |
| `img-src` | `'self' data: blob:`, `tile.openstreetmap.org`, `s3.amazonaws.com/elevation-tiles-prod/`, `*.s3.amazonaws.com`, `*.s3.<region>.amazonaws.com` | map tiles, terrain tiles, inline SVG textures, presigned report photos |
| `media-src` | `'self' blob:`, the two S3 patterns | presigned alert and report audio; a voice note played back before sending |
| `font-src` | `'self' data:` | self-hosted Noto Sans Devanagari, Inter and Tiro (no Google Fonts request) |
| `connect-src` | `'self'`, `*.execute-api.<region>`, `cognito-idp.<region>`, `*.appsync-api.<region>`, `wss://*.appsync-realtime-api.<region>`, the two tile hosts | the API, sign-in, live push, and MapLibre and the service worker fetching tiles |
| `worker-src` / `child-src` | `'self' blob:` | the service worker; MapLibre's blob worker |
| `manifest-src` | `'self'` | the PWA manifest |
| `frame-src` | `'none'` | nothing is embedded |
| `frame-ancestors` | `'none'` | nothing may embed Pukaar |
| `object-src`, `base-uri`, `form-action` | `'none'`, `'self'`, `'self'` | the usual hardening |
| `upgrade-insecure-requests` | | |

The API, AppSync and S3 hosts are region wildcards rather than exact names because naming them in
the Amplify app would make a dependency cycle (the API's CORS rule names the Amplify app).

The hashes come from the build: it lists them in `dist/csp-inline.json`, and `node scripts/csp-sync.mjs`
(in `frontend/`) writes them into the template and into `frontend/csp-hashes.json`, the copy the backend's
template test reads. Change the theme snippet, the painter or any stylesheet the critical cut takes from,
and the template test and `check:csp` fail until you run it; `scripts/deploy_web.sh` refuses to publish a
build the template does not allow. A stale template never blanks the site: the browser refuses the inline
painter and critical CSS, and the deferred `pk-fallback-*.js` starts the app the ordinary way.

### How it was checked

`frontend/scripts/csp-check.mjs` serves the production build with exactly these headers (read from the
template, region filled in), answers the stack's API host from a local backend, gives map tiles a
1×1 PNG, and opens 16 pages in headless Chromium: `/`, `/live`, `/report`, `/village/thunag`, `/how`,
`/proof`, `/pilot`, a tracking page, `/login`, `/status.html`, and signed in, the
console's inbox (waiting and sent), reports, settings, audit and roster. It fails on any `securitypolicyviolation` event or CSP console message, and
on a missing header. It also opens an after-action-style page from a `blob:` URL the way the console
does and checks its inline styles survive. With `CSP_OVERRIDE="default-src 'self'"` the same run
fails on every page, which shows the check catches violations.

```
cd frontend
VITE_API_BASE=https://abc123defg.execute-api.us-east-1.amazonaws.com \
VITE_EVENTS_HTTP_DOMAIN=x.appsync-api.us-east-1.amazonaws.com \
VITE_EVENTS_REALTIME_DOMAIN=x.appsync-realtime-api.us-east-1.amazonaws.com VITE_EVENTS_API_KEY=da2-x \
VITE_COGNITO_REGION=us-east-1 npm run build
(cd ../backend && PUKAAR_MODE=local PUKAAR_CORS_ORIGINS=http://127.0.0.1:4180 PYTHONPATH=src \
  .venv/bin/python -m uvicorn Pukaar.main:app --port 8000) &
node scripts/csp-check.mjs
```

Not covered by the run: the service worker (blocked in the check, so its own fetches are not
exercised; its tile and API fetches use the same `connect-src` hosts) and the live WebSocket's
handshake (allowed by the policy; the fake AppSync host does not resolve). After the next deploy,
check the real site once: `curl -sI <web url>` and the browser console on `/live` and `/console`.
