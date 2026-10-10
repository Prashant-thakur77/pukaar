#!/usr/bin/env bash
# Store Pukaar secrets in SSM SecureString parameters and register the
# Telegram webhook. Secret values never appear on a command line or in a file.
#   /pukaar/telegram_token           from BotFather (prompted)
#   /pukaar/telegram_webhook_secret  random; Telegram echoes it in X-Telegram-Bot-Api-Secret-Token
#   /pukaar/link_secret              random HMAC key for signed approval links
# Set ROTATE_LINK_SECRET=1 to replace an existing link secret (voids open links).
set -euo pipefail
REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-us-east-1}}"
STACK="${PUKAAR_STACK:-pukaar-dev}"

put_secret() {  # name; value on stdin
  # Newer AWS CLI versions cannot read --cli-input-json from a pipe, so the JSON
  # goes to an owner-only file in memory (/dev/shm when present) and is removed
  # at once. The value never appears on a command line.
  local tmp
  tmp="$(mktemp -p "$( [[ -d /dev/shm ]] && echo /dev/shm || echo "${TMPDIR:-/tmp}" )")"
  chmod 600 "$tmp"
  python3 -c 'import json,sys; print(json.dumps({"Name": sys.argv[1], "Value": sys.stdin.read().rstrip("\n"), "Type": "SecureString", "Overwrite": True}))' "$1" >"$tmp"
  aws ssm put-parameter --region "$REGION" --cli-input-json "file://$tmp" >/dev/null || { rm -f "$tmp"; return 1; }
  rm -f "$tmp"
  echo "stored $1"
}

exists() { aws ssm get-parameter --region "$REGION" --name "$1" >/dev/null 2>&1; }

if [[ "${ROTATE_LINK_SECRET:-0}" == "1" ]] || ! exists /pukaar/link_secret; then
  openssl rand -hex 32 | put_secret /pukaar/link_secret
else
  echo "kept /pukaar/link_secret"
fi

read -r -s -p "Telegram bot token from BotFather (empty to skip Telegram): " TELEGRAM_TOKEN; echo
if [[ -z "$TELEGRAM_TOKEN" ]]; then
  exists /pukaar/telegram_webhook_secret || openssl rand -hex 32 | put_secret /pukaar/telegram_webhook_secret
  echo "No bot token: alerts use the stub channel until you rerun this with a token."
  exit 0
fi
put_secret /pukaar/telegram_token <<<"$TELEGRAM_TOKEN"

# A new webhook secret is only useful together with setWebhook below.
WEBHOOK_SECRET="$(openssl rand -hex 32)"
put_secret /pukaar/telegram_webhook_secret <<<"$WEBHOOK_SECRET"

API_URL="$(aws cloudformation describe-stacks --region "$REGION" --stack-name "$STACK" \
  --query "Stacks[0].Outputs[?OutputKey=='ApiUrl'].OutputValue" --output text 2>/dev/null || true)"
if [[ -z "$API_URL" || "$API_URL" == "None" ]]; then
  echo "Stack $STACK is not deployed yet: run 'make deploy', then 'make secrets' again to register the webhook."
  exit 0
fi

# curl reads its arguments from stdin so the token and secret stay out of `ps`.
curl -fsS --config - <<EOC
url = "https://api.telegram.org/bot$TELEGRAM_TOKEN/setWebhook"
data-urlencode = "url=$API_URL/telegram/webhook"
data-urlencode = "secret_token=$WEBHOOK_SECRET"
data-urlencode = "allowed_updates=[\"message\",\"callback_query\"]"
EOC
echo
echo "Telegram webhook set to $API_URL/telegram/webhook"
