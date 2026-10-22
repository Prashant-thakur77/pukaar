# Security: report abuse and browser headers

Two protections for a public pilot: the anonymous report page cannot be used to raise a public level
or to crowd villagers out, and the web app tells browsers what it may load. Operations (what to do
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
Lambda need AWS WAF rate-based rules, which HTTP APIs do not support directly; the next step is
CloudFront with WAF in front of the API (or a REST API stage with WAF).

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
| `script-src` | `'self' 'sha256-82ey…'` | the bundle, and the one inline snippet in `frontend/index.html` that applies the saved theme before first paint. No `'unsafe-inline'`, no `'unsafe-eval'` |
| `style-src` | `'self'` | the bundled CSS; no `<style>` element from anywhere else |
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

If you change the theme snippet in `frontend/index.html`, the template test fails until the hash in
the template is updated to match.

### How it was checked

`frontend/scripts/csp-check.mjs` serves the production build with exactly these headers (read from the
template, region filled in), answers the stack's API host from a local backend, gives map tiles a
1×1 PNG, and opens 14 pages in headless Chromium: `/`, `/live`, `/report`, `/village/thunag`, `/how`,
`/sensors`, `/agents`, `/impact`, `/pilot`, a tracking page, `/login`, and signed in, `/console`,
`/audit` and `/roster`. It fails on any `securitypolicyviolation` event or CSP console message, and
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
