# Deploying Pukaar to AWS

Everything runs in one account. The demo stack is `pukaar-dev` in `us-east-1`;
sections 1 to 9 describe it. A pilot runs on a separate stack, `pukaar-prod` in
`ap-south-1` (Mumbai), from the same template: see
[Production stage](#production-stage). The infrastructure is
`infra/template.yaml` (AWS SAM) plus the approval state machine
`infra/approval.asl.json`; settings for both stacks are in `samconfig.toml`.

## 0. Tools on the deploying machine

- AWS CLI v2, AWS SAM CLI 1.120 or later
- Docker (or Finch) running: the five Lambda functions are container images
- Python 3.12 with `uv`, Node 20 or later with `npm`, `zip`, `curl`, `openssl`
- `make install` installs the backend and frontend dependencies.

Build on the same CPU type you deploy. The default is `x86_64`; on an Apple
Silicon or Graviton machine deploy with `Architecture=arm64` (see section 4) so
Docker does not emulate.

## 1. IAM user and keys

1. In the IAM console create a user, for example `pukaar-deployer`, without
   console access.
2. Attach a policy. For a dedicated test account `AdministratorAccess` is
   simplest. Otherwise the user needs CloudFormation, IAM (create and pass
   roles), Lambda, ECR, S3, DynamoDB, Step Functions, EventBridge Scheduler,
   SQS, SNS, CloudWatch and Logs, X-Ray, Cognito, API Gateway, Amplify, SSM,
   Bedrock (including Guardrails), AWS IoT, AppSync and SES permissions.
3. Create an access key (Security credentials, "Command Line Interface").
4. `aws configure` with that key and region `us-east-1`. Check with
   `aws sts get-caller-identity`.

Never commit the keys; `.gitignore` already excludes `.env*` and `.aws/`.

## 2. Bedrock model access

In the Bedrock console for **us-east-1** and again for **us-west-2** (the
failover region), open "Model access" and make sure these are enabled:
Amazon **Nova 2 Lite**, **Nova Lite** and **Nova Pro**. If the console says
serverless models are enabled automatically, there is nothing to request.
The functions call the cross-region profile `us.amazon.nova-2-lite-v1:0`
(parameter `BedrockModelId`), which may run in us-east-1, us-east-2 or
us-west-2; the IAM policies allow exactly those Nova models.

Quick check:

```
aws bedrock-runtime converse --region us-east-1 \
  --model-id us.amazon.nova-2-lite-v1:0 \
  --messages '[{"role":"user","content":[{"text":"Say OK"}]}]'
```

If Nova 2 Lite is not available to the account, deploy with
`BedrockModelId=us.amazon.nova-lite-v1:0`.

## 3. Telegram bot

1. In Telegram, talk to **@BotFather**, send `/newbot`, and copy the token.
2. `make secrets` and paste the token at the prompt (input is hidden). It
   stores four SSM SecureString parameters:
   `/pukaar/telegram_token`, `/pukaar/telegram_webhook_secret` (random),
   `/pukaar/link_secret` (random HMAC key for approval links; kept on reruns
   unless `ROTATE_LINK_SECRET=1`) and `/pukaar/report_ip_salt` (random salt for
   the report-abuse hashes, docs/SECURITY.md; kept unless `ROTATE_REPORT_SALT=1`;
   without it no villager report can auto-verify).
3. The webhook needs the API URL, so on the very first run (before the stack
   exists) the script stores the secrets and says so; run `make secrets` again
   after `make deploy` to register the webhook at `<ApiUrl>/telegram/webhook`.

No token yet? Press Enter at the prompt: alerts then use the stub channel.

## 3a. Web Push keys (approval alerts on the officer's phone)

```
make vapid-keys
```

Run it once, before `make deploy` or after (the API reads the keys from SSM on
each request, cached for 5 minutes, so no redeploy is needed for the keys
alone). It makes a P-256 key pair in the script's memory and stores
`/pukaar/vapid_private_key` (SecureString, never printed) and
`/pukaar/vapid_public_key` (String, printed). A rerun keeps an existing pair.
`make vapid-keys ROTATE=1` replaces it; every officer must then open the
console and turn approval alerts on again (the console notices the new key and
drops the old subscription). Without keys, `GET /push/vapid-public-key` says
`configured: false` and the console card says push is not set up.

After the deploy, each officer opens the console **on their phone**, finds
"Get approval alerts on this phone", taps **Turn on**, allows notifications,
and taps **Send a test notification**. On iPhone and iPad (iOS 16.4 or later)
push works only after Share -> Add to Home Screen and opening Pukaar from the
home screen. When an alert waits for that officer, the phone shows it with
**✅ मंज़ूर** and **✖ नहीं**; the buttons work with the console closed.

## 4. Deploy

```
make deploy
```

This runs `sam build` (Docker images from `backend/Dockerfile`, targets `api`
and `worker`), `sam deploy` (creates ECR repositories automatically through
`resolve_image_repos`), and `scripts/deploy_web.sh`, which builds the front end
with the stack's outputs and uploads it to Amplify Hosting as a manual
deployment. The first deploy takes 10 to 15 minutes.

Parameters (override with
`sam deploy --parameter-overrides Name=value ...`, or edit `samconfig.toml`):

| Parameter | Default | Notes |
|---|---|---|
| `Stage` | `dev` | Suffix of every resource name |
| `ApprovalTimeoutSeconds` | `600` | Per officer. Use `60` for a demo and for `make it` |
| `CriticalApprovalTimeoutSeconds` | `300` | Per officer for a critical alert, never longer than `ApprovalTimeoutSeconds`: a chain of three holds a critical 15 minutes at most, not 30 |
| `OfficerWakeSeconds` | `180` | Into each officer's window: the reminder on Web Push and Telegram, and a voice call to an officer who has not opened the link (half-way through a shorter window; `0` = always half-way). Needs `VoiceProvider` on and the officer's phone (`make officer-phone`); the call never approves ([CONTRACT.md](CONTRACT.md), "Approval windows") |
| `AckWaitSeconds` | `300` | Before the one re-send (and the first voice re-call). Use `30` for `make it`, `600` for a voice pilot |
| `VoiceRetrySeconds` | `600` | Between later voice re-calls (three attempts in all) |
| `VoiceProvider` | `off` | `exotel` or `plivo` turns on voice calls with "press 1" ([VOICE.md](VOICE.md)); off records voice deliveries as failed |
| `ExotelApiHost` | `api.exotel.com` | `api.in.exotel.com` for an account on Exotel's Mumbai cluster |
| `WebOrigin` | empty | CORS origin; empty means the Amplify URL |
| `BedrockModelId` | `us.amazon.nova-2-lite-v1:0` | A Nova model or inference profile callable from the stack's region (prod: see [Production stage](#production-stage)) |
| `BedrockFallbackRegion` | `us-west-2` | Second region on throttling or 5xx; the model id must be callable there too |
| `Architecture` | `x86_64` | `arm64` when building on ARM |
| `ReplayEnabled` | `true` | A replay never touches live levels or live alerts, but a real pilot should still set `false` (prod must) |
| `CriticalAutoSend` | `false` | `true` sends a critical alert, flagged unapproved, when every officer timed out. Needs DDMA sign-off, so off unless set (see the migration note under [Production stage](#production-stage)) |
| `RequireMfa` | `false` | `true`: every sign-in needs a TOTP code (Cognito MFA ON; prod must). `false`: TOTP optional |
| `RetentionDays` | `0` | Villager reports, their photos and voice notes expire this many days after they were made; 0 keeps them (prod: 365) |
| `CapSender` | empty | CAP `<sender>`. Empty: `pukaar-<stage>@<web host>`. Prod must set the authority's |
| `CapSenderName` | empty | CAP `<senderName>`. Empty: the "(demo)" name and a not-official note. Prod must set the authority's |
| `CapSenderNameHi` | empty | The Hindi `<senderName>`; empty uses the English one |
| `AlarmEmail` | empty | `make deploy` passes `ALARM_EMAIL` from `.env.deploy.local`. Confirm the SNS e-mail after deploy. Empty means the alarms notify nobody |
| `AfterActionFrom` | empty | Verified SES sender for after-action reports (section 5a). Empty = no e-mail, no SES permission |
| `EventsApiKeyExpires` | a fixed date | Expiry (epoch seconds) of the public, subscribe-only live-push API key; `make deploy` passes now + 360 days |

Set the on-call address for the alarms before the first deploy. It is kept
out of git, like `AFTER_ACTION_FROM`:

```
echo "ALARM_EMAIL=duty-officer@example.org" >> .env.deploy.local   # gitignored; make deploy reads it
make deploy
```

SNS e-mails a confirmation link to that address, and nothing is delivered
until its owner clicks it. `make deploy` prints a warning when `ALARM_EMAIL`
is not set.

Stack outputs: `ApiUrl`, `WebUrl`, `AmplifyAppId`, `AmplifyBranch`,
`UserPoolId`, `UserPoolClientId`, `TableName`, `BucketName`,
`StateMachineArn`, `AlarmTopicArn`, `GaugePolicyName`, `GaugeTopicRuleName`,
`ReportGuardrailId`, `ReportGuardrailVersion`, `EventsHttpDomain`,
`EventsRealtimeDomain`, `EventsApiKey`. Print them with `scripts/stack_env.sh`.

## 5. Seed data and demo users

```
export PUKAAR_DEMO_PASSWORD='<12+ chars, upper, lower, digit>'
make seed
```

This loads the villages into the table (`python -m Pukaar.scripts.seed` with
`PUKAAR_MODE=aws`) and creates the Cognito users `officer1`, `officer2`
(group `officer`, all villages) and `pradhan_thunag` (group `pradhan`, Thunag).
Users are created with a temporary password (`PUKAAR_DEMO_TEMP_PASSWORD`, or a
random one) and then set to the permanent password, so the demo signs in
without a password-change screen. Share the password out of band; it is never
written to the repository. `make seed STAGE=prod` loads the villages only: a
production stack never gets these users (see [Production stage](#production-stage)).

`make reset-demo` clears demo state on the deployed stack.

## 5a. After-action report by e-mail (Amazon SES)

Every alert that closes gets an after-action report (`services/after_action.py`):
key times in IST with durations (level rose, approved, first voice, first
acknowledgement), the decision trace, the approval chain, deliveries by channel
(first names only, never a phone number or chat id), re-sends, roll-call
counts, Cedar allow/deny counts with every deny listed, and the Hindi and
English text. The close step stores it privately at
`s3://<bucket>/reports/after-action/<alert id>.html` (plus a `.json`
summary); officers open or download it from the console
(`GET /alerts/{id}/after-action`). It is always stored; e-mail is optional.

The account's SES in `us-east-1` is in the **sandbox**: it sends only from and
to verified addresses, at most 200 messages a day. To e-mail the report:

```
make ses-verify EMAIL=pukaar-sender@example.org   # the sender
make ses-verify EMAIL=duty-officer@example.org    # every recipient, while in the sandbox
```

Each address's owner must click the link in the verification e-mail from
Amazon (valid 24 hours). Check with
`aws sesv2 get-email-identity --email-identity <address>` (`VerifiedForSendingStatus: true`).
Then set the recipients (comma list) and the sender, and redeploy:

```
aws ssm put-parameter --region us-east-1 --name /pukaar/after_action_to --type SecureString \
  --value "duty-officer@example.org,sdm@example.org" --overwrite
echo "AFTER_ACTION_FROM=pukaar-sender@example.org" >> .env.deploy.local   # gitignored; make deploy reads it
make deploy
```

An officer's address can also be added as `"email"` on their entry in
`data/villages.json` (`officers`), but do not commit real addresses.
`AfterActionFrom` gives only the workflow Lambda `ses:SendEmail`, limited to
this account's SES identities with `ses:FromAddress` pinned to that sender (in
the sandbox SES also checks each recipient's identity; after production access
the `identity/*` line can be removed). One message goes to each recipient, so
an unverified address fails alone. Live alerts and drills are e-mailed;
replays are stored but never e-mailed. Failures are logged and counted as the
`AfterActionFailed` metric and never stop the alert from closing. Local mode
never sends e-mail. To leave the sandbox, request production access in the SES
console (Account dashboard).

## 6. Front end settings

`scripts/deploy_web.sh` builds with:

| Variable | Value |
|---|---|
| `VITE_API_BASE` | stack output `ApiUrl` |
| `VITE_COGNITO_REGION` | the stack's region (`us-east-1` for dev, `ap-south-1` for prod) |
| `VITE_COGNITO_USER_POOL_ID` | stack output `UserPoolId` |
| `VITE_COGNITO_CLIENT_ID` | stack output `UserPoolClientId` |

To redeploy only the web app: `make deploy-web`. For a custom domain, add it
in the Amplify console and redeploy the stack with `WebOrigin=https://<domain>`
so CORS and the links in alerts use it.

## 7. Smoke checks

```
eval "$(scripts/stack_env.sh)"
curl -s "$STACK_ApiUrl/health"                 # {"status": ..., "mode": "aws", ...}
curl -s "$STACK_ApiUrl/public/overview" | head -c 300
curl -s -o /dev/null -w '%{http_code}\n' "$STACK_ApiUrl/me"   # 401 without a token
curl -s "$STACK_ApiUrl/push/vapid-public-key"   # {"key": "B...", "configured": true} after make vapid-keys

TOKEN=$(aws cognito-idp initiate-auth --region us-east-1 --auth-flow USER_PASSWORD_AUTH \
  --client-id "$STACK_UserPoolClientId" \
  --auth-parameters USERNAME=officer1,PASSWORD="$PUKAAR_DEMO_PASSWORD" \
  --query AuthenticationResult.IdToken --output text)
curl -s -H "Authorization: Bearer $TOKEN" "$STACK_ApiUrl/me"   # role officer
aws lambda invoke --function-name pukaar-sweep-dev --payload '{}' \
  --cli-binary-format raw-in-base64-out /dev/stdout              # one sweep now
```

Then open `WebUrl`, sign in as `officer1`, and start the replay.

For the whole public surface at once, run `make smoke` (`scripts/smoke.mjs`, read-only). It loads every
public page at 390 px and 1440 px in Chromium and fails on a page error, sideways scroll or any axe
WCAG 2.1 A/AA violation. It also checks that each landing counter copies as one value and that the
service worker registers, that the public API routes return the expected shapes, and that protected
routes (`/overview`, `/stats`, `/alerts`, `/health/deep`, `POST /villages/{id}/roadblocks`) answer 401
without a token. Any page request to the API other than GET is aborted and counted as a failure.
Point it elsewhere with `SMOKE_SITE=... SMOKE_API=... make smoke`.

Workflow end to end (deploy with short timers first):

```
sam deploy --parameter-overrides ApprovalTimeoutSeconds=60 AckWaitSeconds=30
make it
```

`make it` runs real executions for approve, decline, timeout to the next
officer, critical auto-send and forced error to failsafe, and deletes its test
items afterwards. Redeploy with the normal timers when done.

Watch: CloudWatch dashboard `pukaar-dev`, alarms `pukaar-dev-*`, Step Functions
console for `pukaar-approval-dev`.

## 8. Cost notes

The stack has no NAT gateway, no VPC and nothing always on. At demo traffic
most pieces stay inside the free tier: Lambda, DynamoDB on-demand, SQS, SNS,
Cognito, HTTP API, EventBridge Scheduler (about 2,900 sweeps a month) and
Step Functions Standard (each approval run is about 10 state transitions).
Things that cost money even when small:

- Bedrock Nova tokens (per call; no model call at level `normal`).
- Polly generative voice, Transcribe minutes after the 12-month free tier.
- ECR storage for the images (two images, roughly 0.5 to 1 GB each).
- CloudWatch: thirteen alarms and one dashboard; the free tier covers ten alarms
  and three dashboards, so the eleventh is billed (cents a month). X-Ray
  traces past the free tier.
- DynamoDB point-in-time recovery is billed per GB stored (tiny here).
- Amplify Hosting bandwidth and build minutes beyond the free tier.

Set an AWS Budget with an e-mail alert (for example 10 USD) before the demo.

## 9. Teardown

```
eval "$(scripts/stack_env.sh)"
make gauge-provision VILLAGE=gohar DELETE=1      # once per provisioned gauge
aws s3 rm "s3://$STACK_BucketName" --recursive   # the bucket must be empty
sam delete --stack-name pukaar-dev --region us-east-1
for p in telegram_token telegram_webhook_secret link_secret report_ip_salt vapid_private_key vapid_public_key after_action_to; do
  aws ssm delete-parameter --name "/pukaar/$p"   # an error for one that was never set is harmless
done
```

`sam delete` also offers to delete the ECR repositories and the SAM artifacts
bucket it created. Log groups are deleted with the stack. Delete the Telegram
bot in BotFather (`/deletebot`) if it is no longer needed, and deactivate the
IAM user's access key.

## Production stage

A pilot never runs on `pukaar-dev`: that stack has the published judge
password, replays and optional MFA. `make deploy STAGE=prod` builds and deploys
a separate stack, `pukaar-prod`, in `ap-south-1` (Mumbai) from the same
template, with the `[prod.*]` settings in `samconfig.toml`. Nothing is shared
with dev: the table, bucket, user pool, alarms and SSM secrets are all in the
other region.

### What differs from dev

| Setting | dev | prod | Where it is enforced |
|---|---|---|---|
| Stack, region | `pukaar-dev`, `us-east-1` | `pukaar-prod`, `ap-south-1` | `samconfig.toml` `[prod.global.parameters]` |
| `ReplayEnabled` | `true` | `false` | template rule `ProductionStage` refuses `true` |
| `RequireMfa` | `false` (TOTP optional) | `true` (TOTP for every sign-in) | template rule; Cognito `MfaConfiguration ON` |
| `RetentionDays` | `0` (kept) | `365` | template rule refuses `0` |
| `CapSender`, `CapSenderName` | empty: the "(demo)" sender | the issuing authority's | template rule and `make deploy` refuse them empty; `make` also refuses a name with "(demo)" |
| `CriticalAutoSend` | `false` | `false` | turn on only after the DDMA signs off |
| `VoiceProvider` | `.env.deploy.local` | `.env.deploy.prod.local` | as configured; `off` until a provider account exists |
| `BedrockModelId` | `us.amazon.nova-2-lite-v1:0` | `global.amazon.nova-2-lite-v1:0` | see the region table below |
| `BedrockFallbackRegion` | `us-west-2` | `ap-southeast-1` | |
| `ALARM_EMAIL` | a warning when unset | required | `make deploy STAGE=prod` stops without it |
| Demo and judge users | `make seed` creates them | never | `make seed STAGE=prod` seeds villages only; `scripts/seed_users.py` refuses a `-prod` stack |
| `make reset-demo` | allowed | refused | `Makefile` |
| Change set | applied at once | shown, and waits for `y` | `confirm_changeset = true` |

### What changes in ap-south-1

Checked from the account on 22 Oct 2026 with read-only calls
(`aws bedrock list-inference-profiles`, `list-foundation-models`,
`aws polly describe-voices`, and a list call on each other service in
`ap-south-1`).

| Service | In ap-south-1 | What the stack does |
|---|---|---|
| Bedrock Nova | No Nova model runs on demand in the region (inference type `INFERENCE_PROFILE` only). The profiles there are `global.amazon.nova-2-lite-v1:0` (any commercial region in the world) and `apac.amazon.nova-lite-v1:0`, `-micro-`, `-pro-` (Tokyo, Seoul, Osaka, Mumbai, Singapore, Sydney). The `us.` profile cannot be called from Mumbai | Prod uses `global.amazon.nova-2-lite-v1:0`, the model the drafts were tested with. The IAM grants allow any Nova inference profile of the stack's region and of `BedrockFallbackRegion`, and the Nova foundation models in any region, because a profile may run the call in any region it covers |
| Bedrock Guardrails | available | the report guardrail is created in the region |
| Polly | `Kajal` neural, `hi-IN`, available | unchanged |
| Transcribe | available; batch `hi-IN` | unchanged |
| Cognito, TOTP MFA | available | unchanged |
| AppSync Events, IoT Core, EventBridge Scheduler, SES, Amplify Hosting | available | unchanged; endpoints come from `${AWS::Region}` |
| CSP `connect-src` | | built from `${AWS::Region}` in the Amplify headers, so it names the Mumbai hosts |

Data residency, honestly: the table, the bucket, the logs and Cognito stay in
India. A model call does not. With the `global.` profile a draft, a report's
words for structuring, or an analyst question may be processed in any
commercial AWS region. To keep model calls in the Asia Pacific regions instead,
set `BedrockModelId=apac.amazon.nova-lite-v1:0` (Nova Lite, an older model than
the one the drafts were tuned on: check a few drafts before the season). No
setting keeps Bedrock inside India today. Without any model the rules and the
fixed templates still work (drafts fall back to the template). Request model
access for Nova in `ap-south-1` and `ap-southeast-1` (section 2) before the first
deploy, and check with:

```
aws bedrock-runtime converse --region ap-south-1 \
  --model-id global.amazon.nova-2-lite-v1:0 \
  --messages '[{"role":"user","content":[{"text":"Say OK"}]}]'
```

### Officer accounts and MFA

`RequireMfa=true` sets the user pool's MFA to ON with TOTP only (no SMS). Cognito
sets MFA per pool, so pradhans need an authenticator app too. Set it when the
stack is created: Cognito may refuse to change an existing pool to required.

There are no demo users on prod. Add each real person by hand, with a password
you give them in person:

```
POOL=$(aws cloudformation describe-stacks --region ap-south-1 --stack-name pukaar-prod \
  --query "Stacks[0].Outputs[?OutputKey=='UserPoolId'].OutputValue" --output text)
aws cognito-idp admin-create-user --region ap-south-1 --user-pool-id "$POOL" \
  --username dso_mandi --message-action SUPPRESS \
  --user-attributes Name=custom:village_ids,Value=thunag,janjehli,gohar,pandoh,sujanpur
aws cognito-idp admin-set-user-password --region ap-south-1 --user-pool-id "$POOL" \
  --username dso_mandi --password '<12+ chars>' --permanent
aws cognito-idp admin-add-user-to-group --region ap-south-1 --user-pool-id "$POOL" \
  --username dso_mandi --group-name officer     # or pradhan, with that pradhan's villages only
```

At the first sign-in the web app shows a QR code (and the key as text). The
person scans it with an authenticator app (Google Authenticator, Microsoft
Authenticator or any TOTP app) and enters the 6-digit code; after that every
sign-in asks for the current code. For a lost phone, delete the user and create
them again with the same groups and villages; they enrol the new phone at the
next sign-in. Never name a prod user `judge` or `judge_pradhan`: Cedar holds
those names to replay data on every stack.

### Retention (DPDP)

`RetentionDays=365` gives every villager report a DynamoDB TTL of its creation
time plus 365 days (the report, its reference and its tracking code expire
together; a state change never extends it), and an S3 lifecycle rule expires
`audio/reports/` and `photos/` after the same number of days. DynamoDB deletes
an expired item within a few days, and the API never serves a report past its
expiry meanwhile. Reports stored before the setting carry no TTL: delete them
by hand at the end of the pilot, as the RUNBOOK's consent section says.
Alerts, deliveries and the audit trail are the authority's record and are not
expired by this setting.

### CAP sender

Put the authority's values in `.env.deploy.prod.local` (gitignored):

```
ALARM_EMAIL=deoc-mandi@example.gov.in
CAP_SENDER=ddma-mandi@hp.gov.in
CAP_SENDER_NAME=District Disaster Management Authority, Mandi
CAP_SENDER_NAME_HI=ज़िला आपदा प्रबंधन प्राधिकरण, मंडी
VOICE_PROVIDER=off
```

`make deploy STAGE=prod` passes each name to SAM as one quoted value. The feed
then carries them in `<sender>` and both `<senderName>` blocks, and the "Demo
deployment" note is left out (a replay or drill still says so). Use the values
the DDMA gives, and the same sender code it uses in SACHET.

### Migration note: CriticalAutoSend

`CriticalAutoSend` now defaults to `false` in the template and in the app, and
`samconfig.toml` sets it to `false` for dev as well. The next `make deploy` on
dev therefore turns critical auto-send off there too: when every officer times
out, a critical alert expires unsent and the sweep asks again after the
cooldown. To keep the old behaviour on dev, change `CriticalAutoSend=false` to
`true` in `[default.deploy.parameters]`. Never set it on prod without the
DDMA's written sign-off.

### Checklist

Before the first deploy:

- [ ] AWS credentials for the pilot account; `aws sts get-caller-identity` names it.
- [ ] Bedrock model access for Nova in `ap-south-1` and `ap-southeast-1`; the `converse` check above answers.
- [ ] `.env.deploy.prod.local` has `ALARM_EMAIL`, `CAP_SENDER`, `CAP_SENDER_NAME` (and `CAP_SENDER_NAME_HI`) as the DDMA gave them.
- [ ] A second Telegram bot for prod (one bot has one webhook), from @BotFather.

Deploy:

- [ ] `make deploy STAGE=prod`; read the change set and answer `y`.
- [ ] `make secrets STAGE=prod` (the prod bot's token), then again after the deploy to register its webhook.
- [ ] `make vapid-keys STAGE=prod`.
- [ ] `make seed STAGE=prod` (villages only), then add each officer and pradhan by hand (above).
- [ ] Each person signs in once, enrols TOTP, and turns on approval alerts on their phone.

After:

- [ ] The alarm e-mail is confirmed, and an SMS subscriber added and tested (RUNBOOK, pre-season checklist).
- [ ] The duty roster is filled from the DEOC's chart, with the ADM or DM as escalation.
- [ ] `curl -s "$STACK_ApiUrl/health"` says `"mode": "aws"`; `/replay/status` is inactive and `POST /replay/start` is refused.
- [ ] `/cap/alerts.atom` names the authority, not "(demo)".
- [ ] `aws cognito-idp describe-user-pool --region ap-south-1 --user-pool-id "$POOL" --query UserPool.MfaConfiguration` says `ON`.
- [ ] `aws s3api get-bucket-lifecycle-configuration --bucket "$STACK_BucketName"` lists the two report rules.
- [ ] `SMOKE_SITE=<prod web url> SMOKE_API=<prod api url> make smoke` passes.
- [ ] `CriticalAutoSend` stays `false` until the DDMA signs off.

Before the first live day ([docs/field/](field/)):

- [ ] Every officer has read the [duty officer's guide](field/officer-guide.md), and the [night checklist](field/print/night-checklist.pdf) is on the DEOC desk with its blanks filled.
- [ ] Every pradhan has the [pradhan's guide](field/pradhan-guide-hi.md), reviewed by a Hindi speaker from Mandi, and households are registered with consent as it describes.
- [ ] The [villager card](field/print/villager-card.pdf) is printed with the prod report address, the prod bot and each village's safe places filled in, and handed out.
- [ ] The first drill in each village is booked as in the [drill plan](field/drill-plan.md).

## Fallback: S3 and CloudFront instead of Amplify

If Amplify Hosting is not available in the account, remove `AmplifyApp` and
`AmplifyBranch` from the template, set `WebOrigin` to the CloudFront URL, and
serve `frontend/dist` from a private S3 bucket behind CloudFront with an
origin access control and a custom error response that maps 403 and 404 to
`/index.html` (status 200) for the single-page app.
