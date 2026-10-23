# Voice calls with "press 1"

Telegram reaches smartphones. Many households in the villages Pukaar watches have a feature phone,
or a smartphone that an older person cannot read. A phone call reaches both. Pukaar can call each
registered number when an alert is approved, play the Hindi alert in the Polly voice, and ask for
one key:

| Key | Means | What Pukaar does |
|---|---|---|
| 1 | मिल गया (heard it) | The delivery is acknowledged, exactly like the Telegram "मिल गया" button: the alert's acknowledged count, the live counters, the after-action report's time to ear and the re-send logic all see it |
| 2 | मदद चाहिए (need help) | Acknowledged too (they heard the alert), plus a need-help item: the roll-call answer if the person was asked in an open roll-call, otherwise an SOS report (severity high, no location, flagged `voice_need_help`) in the officers' queue, an audit row, a timeline entry and a Telegram note to the village's officers |
| 3 | दोबारा सुनें (repeat) | The alert plays again, at most twice per call |
| other | | Asked again once, then the call ends |
| none | | The menu asks once more by itself, then the call ends |

The call is off until the owner opens a provider account and turns it on. Nothing on this page is
live yet.

Code: [delivery/voice.py](../backend/src/Pukaar/delivery/voice.py) (provider-neutral side),
[delivery/exotel.py](../backend/src/Pukaar/delivery/exotel.py),
[delivery/plivo.py](../backend/src/Pukaar/delivery/plivo.py),
[delivery/ivr.py](../backend/src/Pukaar/delivery/ivr.py) (what a key or a status means),
[api/routers/voice.py](../backend/src/Pukaar/api/routers/voice.py) (webhooks),
[delivery/dispatch.py](../backend/src/Pukaar/delivery/dispatch.py) (who is called, retries),
[scripts/voice.py](../backend/src/Pukaar/scripts/voice.py) (registering numbers).
Tests: [tests/test_voice.py](../backend/tests/test_voice.py).

## Why not AWS

No AWS service places calls to Indian numbers: Amazon Connect, AWS End User Messaging voice and
Amazon Chime SDK all lack an India outbound route. So the call goes through an Indian provider:
**Exotel** first, **Plivo** as the fallback. Both are called with plain HTTPS (`httpx`); there is no
SDK dependency. The audio still comes from Amazon Polly, and everything else (Step Functions, the
records, the alarms) stays on AWS.

## How it works

```
officer approves ─► Step Functions: deliver ─► workflow Lambda
                                                 ├─ Telegram recipients: sendAudio + "मिल गया" button
                                                 └─ voice recipients: Polly 8 kHz MP3 (once per alert)
                                                    and one call each, through the provider
provider calls the phone ─► the person answers ─► the API's /voice/* webhooks
                                                 ├─ the alert audio, then the menu
                                                 ├─ the key pressed  ─► acknowledge / need help / repeat
                                                 └─ how the call ended ─► the two retry counters
wait AckWaitSeconds ─► recall: Telegram once more, voice again for whoever has not pressed 1 or 2
wait VoiceRetrySeconds ─► recall (voice only) ─► ... at most 3 calls per person ─► close
```

Recipients have a `channel`: `telegram`, `voice`, `both` (a Telegram user who also takes calls) or
`stub` (demo). A voice or both recipient has a `phone` in E.164 form (`+919812345678`) and a
`consent` note. A both recipient has two delivery rows per alert, one per channel; every counter
counts people, so they count once, and a key press or a Telegram tap from them stops re-sends on
both channels.

A voice delivery row is `pending` while the call rings, `sent` once the call is answered (its
`sent_at` is the first answer: the moment the voice reached the ear), `acknowledged` after key 1 or
2, and `failed` when the call was not connected or not placed. Officers see the row in the console,
with `attempts`, `not_connected`, `no_key`, `error_category` and `unreachable`.

### The two retry counters

From Newfies-Dialer and RapidPro: a call that never connected and a call that was answered but got
no key are different problems, so they are counted apart.

| Counter | Counts | Categories |
|---|---|---|
| `not_connected` | Calls that did not connect | `busy`, `no_answer`, `failed`, `machine` (answering machine, Plivo), `no_status` (no result from the provider 3 minutes after the call was placed), `provider_error` |
| `no_key` | Calls that were answered with no valid key | `no_key` |

Each person gets at most `PUKAAR_VOICE_MAX_ATTEMPTS` calls per alert (3), counting the first:

1. the first call when the alert is delivered;
2. the second after `AckWaitSeconds` (the same wait as the Telegram re-send; use `600` for a voice pilot);
3. the third after `VoiceRetrySeconds` (default `600`).

So the calls are 10 to 15 minutes apart in the field. The state machine loops on the recall step
while it says `again: true`, and the step counts its rounds on the alert, so the loop ends even if a
provider never sends a status. A person who pressed 1 or 2, or tapped "मिल गया" on Telegram, is
never called again.

Some outcomes are not retried: `invalid_number`, `blocked` (the provider refused, for example a
trial account calling an unverified number) and `provider_off`.

**Unreachable numbers.** When a number was never answered after the last attempt, or the provider
says it does not exist, the voice row is marked `unreachable`, the alert's timeline gets a
`voice_unreachable` entry with the first name only, the `VoiceUnreachable` metric counts it, and
every pradhan of the village who is registered on Telegram gets a Hindi note: "<name> तक चेतावनी
की कॉल 3 बार कोशिश के बाद भी नहीं पहुँची (...)। कृपया किसी को घर भेजकर बताएँ।" The number itself
never leaves the table.

### Honest records

- **Provider off** (`VoiceProvider=off`, the default), **credentials missing** or the **webhook key
  missing**: the voice row is `failed` with the reason (`voice provider is off ...`,
  `Exotel credentials unavailable ...`) and `error_category: provider_off`. It counts in
  `DeliveryFailed` (alarmed). It is never recorded as a call that went out, and never retried.
- **Replays never dial.** A replay alert's recipients get the stub channel, as before. For a voice
  recipient the stub voice provider answers instead of a real one and says so: the row has
  `provider: stub` and `call_status: simulated`. The Cedar policy `no-replay-to-phones` forbids any
  channel but the stub for a replay, and `voice.place_call()` itself never uses a real provider for
  a replay alert. The stub provider refuses a live alert.
- A busy or unanswered phone is not a system fault: it counts in `VoiceNotConnected`, not in
  `DeliveryFailed`.

### Webhook authentication

Call providers carry no Cognito token, so the voice routes are public in API Gateway and every
request is checked in the app before anything is read or written:

1. **A key in the URL:** `?k=` must equal the SSM SecureString `/pukaar/voice_webhook_key`. With no
   key in SSM, every voice webhook is refused.
2. **A signed per-call token:** Exotel's `CustomField`, or `?c=` on the callback URLs Pukaar gives
   the provider. It names the alert, the person and the attempt, carries an expiry (48 hours) and
   an HMAC-SHA256 tag keyed from `/pukaar/link_secret`. It is at most 128 characters, Exotel's limit.
3. **Plivo's signature:** `X-Plivo-Signature-V3` over the URL, the sorted POST parameters and the
   nonce, keyed with the Plivo auth token. Exotel does not sign its webhooks, so 1, 2 and 4 carry
   the weight there.
4. **The call id** in the webhook (`CallSid`, Plivo's `RequestUUID` or `CallUUID`) must be one Pukaar
   placed for that person and that alert.

A request that fails any check gets a 403 and changes nothing (tested: no key, wrong key, tampered
token, made-up token, a real token for a person with no call, a call id Pukaar did not place, a bad
Plivo signature). Key presses are idempotent on (call id, digit): a provider retrying the same
webhook acts once.

| Route | Provider | Answers |
|---|---|---|
| `GET`, `HEAD /voice/exotel/flow?k=..&part=greeting` | Exotel Greeting applet | `text/plain`: the alert's 8 kHz MP3 URL (a presigned S3 link, 2 hours), or the Hindi text if Polly was unavailable |
| `GET /voice/exotel/flow?k=..&part=menu` | Exotel Gather applet | JSON: the menu prompt, `max_input_digits: 1`, `input_timeout: 8`, `repeat_menu: 1` |
| `GET /voice/exotel/gather?k=..` | Exotel Passthru applet | `200` to end the call, `302` to play the alert again |
| `POST /voice/exotel/status?k=..&c=..` | Exotel StatusCallback | JSON |
| `POST /voice/plivo/answer?k=..&c=..` | Plivo answer URL | XML: `<GetDigits numDigits="1" retries="1" validDigits="123">` with the alert and the menu |
| `POST /voice/plivo/digits?k=..&c=..` | Plivo GetDigits action | XML: a closing line and `<Hangup/>`, or `<Redirect>` back to the answer for 3 |
| `POST /voice/plivo/hangup?k=..&c=..` | Plivo hangup URL | JSON |

### Phone numbers and privacy

Phone numbers are stored the same way as the Telegram chat ids: as an attribute of the recipient
item in the DynamoDB table, which is encrypted at rest with server-side encryption
(`SSESpecification: SSEEnabled`, an AWS-managed key). Neither is encrypted field by field. Before
the list grows past a consented pilot, move the table to a customer-managed KMS key or encrypt the
`phone` attribute in the app.

Beyond that:

- No public route returns a phone number, a voice recipient id or a call id
  ([tests/test_public_privacy.py](../backend/tests/test_public_privacy.py) seeds a voice recipient and a
  voice delivery and walks every public route). Delivery rows, which officers see, hold no number.
- Numbers are never written to a log: provider error messages pass through `voice.mask()`, and the
  scripts print numbers masked (`+91******78`).
- The need-help report, the timeline entries and the pradhan's note carry a first name only.

## Turning it on with Exotel

### 1. Open an Exotel account

1. Sign up at [exotel.com](https://exotel.com/) ("Try for free"). Choose the Singapore or Mumbai
   cluster and note it: Mumbai accounts use the API host `api.in.exotel.com`.
2. **KYC.** Exotel verifies the account holder before anything beyond the trial. For an
   organisation it asks for the PAN and the GSTIN (with incorporation or registration documents);
   for an individual or a sole proprietor, the PAN and an address proof. The list changes, so
   follow the dashboard's KYC page.
3. **Trial limits.** A trial account can call only numbers you have verified in the dashboard.
   Verify the one test phone first (step 5). A call to any other number fails, and Pukaar records
   it as `blocked`.
4. Note the **Account SID**, the **API key** and **API token** (Dashboard, API settings). Older
   accounts sign in with the SID itself as the API key; then leave `exotel_api_key` unset.

### 2. ExoPhone and the call flow

1. Get an **ExoPhone** (Exotel's virtual number) for the account. This is the caller id people see.
2. In **App Bazaar**, create a new flow with these applets, in this order:
   1. **Greeting**, "Configure dynamic text/URL": the Greeting URL from `make voice-urls`
      (`.../voice/exotel/flow?k=<key>&part=greeting`). It plays the alert MP3 (8 kHz mono, which is
      what Exotel accepts).
   2. **Gather**, "Configure parameters dynamically", Primary URL: the Gather URL from
      `make voice-urls` (`...&part=menu`). Its next applet is the Passthru.
   3. **Passthru**: the Passthru URL from `make voice-urls` (`.../voice/exotel/gather?k=<key>`),
      "Make Passthru Async" **off**. Two transitions:
      - *If the URL returns 200*: a closing **Greeting** with the text "धन्यवाद। आपात स्थिति में
        112 पर कॉल करें।", then **Hangup**;
      - *If the URL returns 302*: back to the first Greeting (the alert plays again).
3. Save, then note the flow's **App ID** (App Bazaar, My Apps). Pukaar dials
   `http://my.exotel.com/<sid>/exoml/start_voice/<app id>` with `Calls/connect`.

### 3. The SSM parameters

All SecureString, in the stack's region, under `/pukaar/`:

```
REGION=us-east-1
put() { aws ssm put-parameter --region "$REGION" --type SecureString --overwrite --name "/pukaar/$1" --value "$2"; }

put voice_webhook_key "$(openssl rand -hex 24)"   # the ?k= key in every voice URL
put exotel_sid        "<Account SID>"
put exotel_api_key    "<API key>"                 # skip if the account signs in with the SID
put exotel_token      "<API token>"
put exotel_caller_id  "<ExoPhone, e.g. 08047112345>"
put exotel_app_id     "<App ID of the flow>"
```

Do not paste these into the shell history on a shared machine; `read -s` them first. The functions
already read `/pukaar/*` (no new IAM grant is needed), and successful reads are cached for 5 minutes,
so a change takes up to 5 minutes to reach a warm Lambda.

### 4. Deploy with voice on

```
sam deploy --parameter-overrides $(sed -n 's/^parameter_overrides = "\(.*\)"$/\1/p' samconfig.toml) \
  VoiceProvider=exotel ExotelApiHost=api.exotel.com AckWaitSeconds=600 VoiceRetrySeconds=600
make voice-urls     # paste the three URLs into the flow (step 2); the output contains the key
```

To keep it on across `make deploy`, add `VoiceProvider=exotel` to `parameter_overrides` in
`samconfig.toml`. To turn it off, deploy with `VoiceProvider=off`: voice deliveries are then
recorded as failed with the reason, and Telegram carries on.

### 5. Test with one verified phone

1. In the Exotel dashboard, verify your own phone (trial accounts call verified numbers only).
2. Register it for the test village, with your own consent:
   ```
   make voice-add VILLAGE=gohar NAME="Owner test" PHONE=+919812345678 CONSENT="owner test, 2026-10-25"
   make voice-list VILLAGE=gohar
   ```
3. Send a labelled drill to voice numbers only, then approve it in the console:
   ```
   make drill VILLAGE=gohar LEVEL=watch CHANNEL=voice
   ```
4. The phone rings from the ExoPhone. You should hear "अभ्यास (DRILL), असली चेतावनी नहीं।" and the
   alert, then the menu. Press **3** once (it plays again), then **1** ("धन्यवाद, दर्ज हो गया").
5. In the console, the alert's delivery row for "Owner test" shows `voice`, `acknowledged`,
   `attempts: 1`, `digit: 1`, and the alert's acknowledged count is 1. Run it again and let it ring
   out: the row shows `failed`, `not_connected: 1`, `busy` or `no_answer`, and a second call comes
   after `AckWaitSeconds`. Run it once more and answer without pressing: `no_key: 1`.
6. Check the logs (`/aws/lambda/pukaar-api-dev`): every voice webhook is logged, refusals as
   `voice webhook refused` with the reason. No number appears.
7. Remove the test number when done: `make voice-remove VILLAGE=gohar ID=v_...`.

## The Plivo fallback

1. Open an account at [plivo.com](https://www.plivo.com/), complete its KYC, and read Plivo's
   "Requirements for Calling in India" (linked from the India pricing page) before buying a number:
   calls to Indian numbers need an Indian caller id.
2. Rent an Indian number in the console.
3. SSM:
   ```
   put plivo_auth_id    "<Auth ID>"
   put plivo_auth_token "<Auth Token>"
   put plivo_caller_id  "<the number, e.g. +918035000000>"
   ```
4. Deploy with `VoiceProvider=plivo`. There is no flow to build: Pukaar gives each call its own
   answer, digits and hangup URLs, and the answer is a `GetDigits` XML built when Plivo asks for
   it. `machine_detection: hangup` ends calls an answering machine picks up (category `machine`).
5. Test as in step 5 above. The signature check follows plivo-python's `validate_v3_signature`;
   confirm it with the first real call: a refused Plivo webhook is logged as
   `voice webhook refused`, reason `plivo signature`.

## Production: DLT and the 1600 series

A consented pilot can call from an ExoPhone with `CallType=trans` (transactional). Going beyond
that is a regulatory question, not a code change:

- TRAI's commercial-communication rules (TCCCPR) apply to calls to people who have not asked for
  them. Every number Pukaar calls must have given consent (the `consent` field records how and
  when), and the household can withdraw it at any time (`make voice-remove`).
- Service and transactional calls from government bodies and regulated entities are moving to the
  **1600xx** number series, which DoT allots to those senders only, and the TCCCPR amendment of
  12 February 2025 exempts government senders from the consent rules that bind a private sender.
  A disaster warning sent at scale should come from the district or state authority
  (DDMA Mandi or HPSDMA) on its own 1600xx number, with Pukaar as the system behind it. The
  authority's provider then gives it the caller id; nothing in Pukaar changes but `exotel_caller_id`.
- Ask Exotel whether the account must register as a Principal Entity on a DLT platform before
  going past a pilot. DLT registration (PAN, TAN, GSTIN, CIN and a letter of authorisation, about
  2 to 3 weeks) is certainly needed for SMS, which Pukaar does not send yet.

## Cost

Checked on **22 October 2026**:

- **Plivo**, India pricing page (<https://www.plivo.com/voice/pricing/in/>): outbound calls
  **₹0.38 per minute**, billed in **30-second pulses**; an Indian number **₹200 per month**.
- **Exotel**, pricing page (<https://exotel.com/pricing/>): no per-minute call rate is published.
  Plans are prepaid credit packs sold through sales (+91-808 8919 888). Exotel's support article
  "Why am I charged for incoming calls?" says an outbound call from an ExoPhone is billed at twice
  the plan's incoming rate. Ask for the rate card and the pulse length (30 or 60 seconds) when
  opening the account.

A Pukaar call is about 60 to 75 seconds (the alert, the menu, one key). On Plivo that is two or three
30-second pulses, ₹0.38 to ₹0.57 per answered call; unanswered calls are normally not billed. A
40-household drill with every household needing all three calls costs at most about ₹70 in calls,
plus the number's rent.

## The consented field drill

The goal: measure, with real households and a labelled drill, whether a call reaches people who
Telegram cannot.

**Who.** 20 to 40 households in one village, chosen with the pradhan, mixing feature phones,
shared phones and older people living alone. Each household agrees in person; nobody is added
from a list.

**Consent script (Hindi, read aloud; English below).**

> नमस्ते। मैं पुकार की ओर से आया/आई हूँ। पुकार बाढ़ की चेतावनी देने वाली एक प्रणाली है। हम जाँचना चाहते हैं
> कि फ़ोन कॉल से चेतावनी आप तक पहुँचती है या नहीं। अगर आप हाँ कहें, तो अगले दो हफ़्तों में किसी दिन आपके
> इस नंबर पर एक अभ्यास कॉल आएगी। कॉल की शुरुआत में "अभ्यास, असली चेतावनी नहीं" बोला जाएगा। संदेश सुनकर
> 1 दबाएँ। मदद चाहिए तो 2 दबाएँ। दोबारा सुनना हो तो 3 दबाएँ। कॉल न उठे तो 10–15 मिनट में दो बार और आ सकती
> है। आपका नंबर केवल चेतावनी के लिए रखा जाएगा, किसी और को नहीं दिया जाएगा, और आप कभी भी मना करके इसे
> हटवा सकते हैं। क्या आप सहमत हैं?

> Hello. I am here for Pukaar, a flood warning system. We want to check whether a phone call
> reaches you with a warning. If you agree, one practice call will come to this number on a day in
> the next two weeks. It starts with "practice, not a real warning". After the message press 1. If
> you need help, press 2. To hear it again, press 3. If you do not pick up, it may come twice more,
> 10 to 15 minutes apart. Your number is kept only for warnings, never shared, and you can ask for
> it to be removed at any time. Do you agree?

Record the answer for each household with `make voice-add ... CONSENT="verbal, <date>, <who
asked>"`. `make drill CHANNEL=voice` refuses to run while any voice number in the village has no
recorded consent.

**Before the day.** Tell the pradhan the day and the hour, and make the pradhan a relay so the
unreachable list reaches them. Sending `/start <village>` to the bot registers anyone, the pradhan
included, as an ordinary villager. Then set the role in one of three ways:

- `make recipient-role VILLAGE=<id> ID=<their Telegram chat id> ROLE=pradhan`;
- if they also take calls, `make voice-add VILLAGE=<id> NAME=... PHONE=+91... CONSENT=... CHAT=<chat
  id> ROLE=pradhan`;
- an officer, or the pradhan of that village signed in to the console, calls
  `POST /villages/<id>/recipients/<chat id>/role` with `{"role": "pradhan"}`.

Each change goes to the audit trail as `recipient_role_changed`. `gauge_reader` and `task_force`
work the same way, and `villager` undoes the change. Deploy with `AckWaitSeconds=600`
(10 minutes to the second call; `VoiceRetrySeconds=600` to the third).

**On the day.** `make drill VILLAGE=<id> LEVEL=watch CHANNEL=voice`, approve in the console, and
note the approval time. A field volunteer stays in the village to help anyone who pressed 2 or
who is upset by the call. Do not run it during real bad weather.

**What to measure** (from the alert's delivery rows in the console, `GET /alerts/{id}`, and the
after-action report):

| Measure | From the voice rows |
|---|---|
| % reached | rows with `sent_at` set (answered at least once) ÷ households called |
| % pressed 1 | rows with `digit: "1"` (or `acknowledged_at` set) ÷ households called; report 2 separately |
| Median minutes to confirm | median of `acknowledged_at` − the alert's `decided_at`, over acknowledged rows |
| Calls needed | the spread of `attempts` among acknowledged rows (1, 2 or 3) |
| Why not reached | counts of `error_category` among the rest; `not_connected` and `no_key` |
| Unreachable | rows with `unreachable: true`; did the pradhan's note arrive, and did someone go to the house? |

Afterwards, ask five or six households what they heard and whether the Hindi was clear, and whether
anyone pressed a key by mistake. Remove the numbers of anyone who asks (`make voice-remove`).

## The duty officer's wake-up call

Web Push and Telegram stay silent on a phone in silent mode, so the approval nudge also phones the
officer (`delivery/officer_call.py`). `OfficerWakeSeconds` (3 minutes) into an officer's approval
window, if they have not opened the one-tap link, Pukaar calls the number set with
`make officer-phone OFFICER=<username> PHONE=+91...`, through the same provider and webhooks as the
alert calls:

> पुकार: थुनाग को अभी आपकी मंज़ूरी चाहिए, गंभीर ख़तरा। Pukaar: Thunag needs your approval now, Critical.
> मंज़ूरी का लिंक टेलीग्राम पर पाने के लिए 1 दबाएँ। Press 1 to get your approval link on Telegram.

Pressing 1 sends the same one-tap approval link again to the officer's Telegram and Web Push, and
the call says so ("Opening your approval link ..."; on Exotel the Passthru answers 302, so the
Greeting speaks the confirmation before the closing Greeting). No key approves or declines: for
liability, the decision stays a deliberate tap in the app with the alert in front of the officer.
The call is placed once per officer per alert, at the same moment as the Web Push and Telegram
reminders. The record (`OfficerCall`, on the alert timeline) says `placed`, then `answered`,
`completed`, `not_connected` or `link_sent`; with voice off, no number on file, or a replay, it says
the call was `not_possible` and why, and the reminders still go. The provider's own text-to-speech
speaks the words (no Polly audio is made for it). The call token names the person
`o_<username, base64url>` and attempt -1, so it can never act on an alert call's counters.

## Inbound calls: joining and reporting by phone

EWS1294 in Cambodia grew mainly by people calling a short code and choosing their place on the keypad
(61% of its subscribers in 2022 signed up that way, and registration calls used about ten times the
minutes of the alerts). Pukaar's inbound menu (`delivery/inbound.py`) does the same on the same
provider, behind the same switch: with `VoiceProvider=off` every inbound route refuses (403).

One number, one menu, all in Hindi:

| Key | What happens |
|---|---|
| 1 | Join: the notice is read (what is kept: the number and the village; why: alerts, the all-clear and "are you safe?"; how long; how to leave). "1" agrees; nothing is stored before it. Then the village code on the keypad and `#` (the code is `ivr_code` in `data/villages.json`, on the village card and in the console's Enrol page; `scripts/add_village.py` gives a new village the next free code), then "1" to confirm. Stored: the caller id as the number, channel voice, `enrolled_via` "ivr", by "self", and the consent record (`ivr-notice-v1`, the key press and when). A number already enrolled there is told so. |
| 2 | Water rising: the village code, then a 20-second recording after the beep. |
| 3 | A road or bridge blocked: the same. |
| 9 | Leave: the village code and "1"; the number is taken off that village (a "both" person keeps Telegram) and erased later (`privacy.py`). |

A report by phone is made with the caller's verified role: the caller id matched to a number enrolled
in that village. A relay's (pradhan, gauge reader, task force) report is auto-verified
(`verified_by` "auto:ivr-relay:<role>") and the village is evaluated at once, so the officer is asked
without waiting for a second report or the next sweep; the duty officers hear of every phone report on
Telegram and Web Push. An unknown caller's report waits in the officers' queue like any unverified
report. The recording is fetched into the report (Plivo's public URL; Exotel's with the account key);
a caller who hangs up during the recording still leaves a report, flagged `no_recording`. Reports by
phone count against the same per-source and per-village limits as the web form (the source is a salted
hash of the caller id).

**Missed calls.** With `PUKAAR_IVR_MISSED_CALL_CALLBACK=true` (off by default: each callback is a billed
call, so the DDMA decides), a call that arrives with no session is rejected unanswered (free for the
caller) and Pukaar calls back into the same menu, at most once per number a day. Exotel needs the
secret `exotel_inbound_app_id` (the inbound flow's app id) for the callback.

**Plivo.** Point the inbound number's application at `POST <api>/voice/plivo/inbound?k=<key>` (answer)
and `POST <api>/voice/plivo/inbound-hangup?k=<key>` (hangup). Each step answers with `<GetDigits>`, a
`<Record maxLength="20">` or the closing words; every request's `X-Plivo-Signature-V3` is checked.

**Exotel.** Build a second flow for the ExoPhone that people call, with the key in each URL:

1. Gather, dynamic URL `GET <api>/voice/exotel/inbound/prompt?k=<key>` (the words and keypad for this step);
2. Passthru `GET <api>/voice/exotel/inbound/key?k=<key>`: 302 goes back to step 1, 200 goes on to step 3;
3. Passthru `GET <api>/voice/exotel/inbound/next?k=<key>`: 200 goes to step 4, 302 to step 6;
4. Record (voicemail), 20 seconds; its prompt: "बीप के बाद बीस सेकंड में बताइए आप क्या देख रहे हैं और कहाँ।";
5. Passthru `GET <api>/voice/exotel/inbound/recorded?k=<key>` (it sends RecordingUrl);
6. Greeting, dynamic URL `GET <api>/voice/exotel/inbound/closing?k=<key>`, then Hangup.

For missed calls, a separate missed-call flow: Passthru `GET <api>/voice/exotel/inbound/missed?k=<key>`
then Hangup. Tested with the local fakes in `backend/tests/test_inbound_ivr.py`; not yet on a real
number.

## Known limits

- The safety roll-call is not asked by call yet. A voice-only person is recorded as asked with the
  note "no roll-call by voice call yet", so the board shows them as not answered. Pressing 2 on an
  alert call does answer an open roll-call.
- Exotel's Passthru branches only on 200 or 302, so a wrong key replays the whole alert, not just
  the menu.
- One Polly voice (Hindi). Pahadi or Nepali recordings are a separate step.
- No SMS fallback yet (needs DLT registration).
- The inbound menu has not run on a real number; the Exotel flow above is built from Exotel's applet
  behaviour (Passthru branches on 200 or 302) and needs a test call before a district relies on it.
