#!/usr/bin/env bash
# Build the front end against the deployed stack and publish it to Amplify
# Hosting with a manual (zip) deployment.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
eval "$("$ROOT/scripts/stack_env.sh")"

: "${STACK_AmplifyAppId:?stack output AmplifyAppId missing; run make deploy first}"
BRANCH="${STACK_AmplifyBranch:-main}"

echo "Building frontend for $STACK_ApiUrl"
(
  cd "$ROOT/frontend"
  [[ -d node_modules ]] || npm ci
  VITE_API_BASE="$STACK_ApiUrl" \
  VITE_COGNITO_REGION="$AWS_REGION" \
  VITE_COGNITO_USER_POOL_ID="$STACK_UserPoolId" \
  VITE_COGNITO_CLIENT_ID="$STACK_UserPoolClientId" \
    npm run build
)

ZIP="$(mktemp -d)/web.zip"
(cd "$ROOT/frontend/dist" && zip -qr "$ZIP" .)

read -r JOB_ID UPLOAD_URL < <(aws amplify create-deployment --region "$AWS_REGION" \
  --app-id "$STACK_AmplifyAppId" --branch-name "$BRANCH" \
  --query '[jobId,zipUploadUrl]' --output text)

curl -fsS -X PUT -H "Content-Type: application/zip" --upload-file "$ZIP" "$UPLOAD_URL"
aws amplify start-deployment --region "$AWS_REGION" \
  --app-id "$STACK_AmplifyAppId" --branch-name "$BRANCH" --job-id "$JOB_ID" >/dev/null

echo -n "Amplify job $JOB_ID"
for _ in $(seq 1 60); do
  STATUS="$(aws amplify get-job --region "$AWS_REGION" --app-id "$STACK_AmplifyAppId" \
    --branch-name "$BRANCH" --job-id "$JOB_ID" --query 'job.summary.status' --output text)"
  case "$STATUS" in
    SUCCEED) echo " done: $STACK_WebUrl"; exit 0 ;;
    FAILED|CANCELLED) echo " $STATUS" >&2; exit 1 ;;
  esac
  echo -n "."; sleep 5
done
echo " timed out waiting; check the Amplify console" >&2
exit 1
