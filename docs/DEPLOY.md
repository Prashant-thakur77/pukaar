# Deploying Pukaar to AWS

Everything runs in one account, region `us-east-1`, stack `pukaar-dev`. The
infrastructure is `infra/template.yaml` (AWS SAM) plus the approval state
machine `infra/approval.asl.json`; settings are in `samconfig.toml`.

## 0. Tools on the deploying machine

- AWS CLI v2, AWS SAM CLI 1.120 or later
- Docker (or Finch) running: the four Lambda functions are container images
- Python 3.12 with `uv`, Node 20 or later with `npm`, `zip`, `curl`, `openssl`
- `make install` installs the backend and frontend dependencies.

Build on the same CPU type you deploy. The default is `x86_64`; on an Apple
Silicon or Graviton machine deploy with `Architecture=arm64` (see section 4) so
Docker does not emulate.

## 1. IAM user and keys

1. In the IAM console create a user, for example `pukaar-deployer`, without
   console access.
2. Attach a policy. For a dedicated hackathon account `AdministratorAccess` is
   simplest. Otherwise the user needs CloudFormation, IAM (create and pass
   roles), Lambda, ECR, S3, DynamoDB, Step Functions, EventBridge Scheduler,
   SQS, SNS, CloudWatch and Logs, Cognito, API Gateway, Amplify, SSM and
   Bedrock permissions.
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
`BedrockModelId=us.amazon.nova-lite-v1:0` and note it in `DECISIONS.md`.

## 3. Telegram bot

1. In Telegram, talk to **@BotFather**, send `/newbot`, and copy the token.
2. `make secrets` and paste the token at the prompt (input is hidden). It
   stores three SSM SecureString parameters:
   `/pukaar/telegram_token`, `/pukaar/telegram_webhook_secret` (random) and
   `/pukaar/link_secret` (random HMAC key for approval links; kept on reruns
   unless `ROTATE_LINK_SECRET=1`).
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
| `ApprovalTimeoutSeconds` | `600` | Per officer. Use `60` for filming and `make it` |
| `AckWaitSeconds` | `300` | Before the one re-send. Use `30` for `make it` |
| `WebOrigin` | empty | CORS origin; empty means the Amplify URL |
| `BedrockModelId` | `us.amazon.nova-2-lite-v1:0` | |
| `BedrockFallbackRegion` | `us-west-2` | Second region on throttling or 5xx |
| `Architecture` | `x86_64` | `arm64` when building on ARM |
| `ReplayEnabled` | `true` | |
| `AlarmEmail` | empty | Confirm the SNS e-mail after deploy |
| `AfterActionFrom` | empty | Verified SES sender for after-action reports (section 5a). Empty = no e-mail, no SES permission |

Stack outputs: `ApiUrl`, `WebUrl`, `AmplifyAppId`, `UserPoolId`,
`UserPoolClientId`, `TableName`, `BucketName`, `StateMachineArn`. Print them
with `scripts/stack_env.sh`.

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
written to the repository.

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
| `VITE_COGNITO_REGION` | `us-east-1` |
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
- CloudWatch: nine alarms and one dashboard; the free tier covers ten alarms
  and three dashboards. X-Ray traces past the free tier.
- DynamoDB point-in-time recovery is billed per GB stored (tiny here).
- Amplify Hosting bandwidth and build minutes beyond the free tier.

Set an AWS Budget with an e-mail alert (for example 10 USD) before the demo.

## 9. Teardown

```
eval "$(scripts/stack_env.sh)"
aws s3 rm "s3://$STACK_BucketName" --recursive   # the bucket must be empty
sam delete --stack-name pukaar-dev --region us-east-1
for p in telegram_token telegram_webhook_secret link_secret; do
  aws ssm delete-parameter --name "/pukaar/$p"
done
```

`sam delete` also offers to delete the ECR repositories and the SAM artifacts
bucket it created. Log groups are deleted with the stack. Delete the Telegram
bot in BotFather (`/deletebot`) if it is no longer needed, and deactivate the
IAM user's access key.

## Fallback: S3 and CloudFront instead of Amplify

If Amplify Hosting is not available in the account, remove `AmplifyApp` and
`AmplifyBranch` from the template, set `WebOrigin` to the CloudFront URL, and
serve `frontend/dist` from a private S3 bucket behind CloudFront with an
origin access control and a custom error response that maps 403 and 404 to
`/index.html` (status 200) for the single-page app.
