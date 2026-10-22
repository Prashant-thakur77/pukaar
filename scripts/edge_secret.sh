#!/usr/bin/env bash
# Prod with CloudFront and AWS WAF in front of the API (make waf-edge, docs/DEPLOY.md "AWS WAF on prod"):
# store the origin-verify value CloudFront adds as X-Pukaar-Edge and the API checks (api/edge.py).
#   /pukaar/edge_origin_secret   random; a String parameter, because CloudFormation can resolve only a
#                                String into the CloudFront origin header ({{resolve:ssm:...}}).
# It proves a request came through CloudFront; it is not a credential to anything. Kept if present
# (ROTATE=1 replaces it; then deploy the stack again so CloudFront sends the new value).
# The value never appears on a command line.
set -euo pipefail
REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-ap-south-1}}"
NAME=/pukaar/edge_origin_secret

if [[ "${ROTATE:-0}" != "1" ]] && aws ssm get-parameter --region "$REGION" --name "$NAME" >/dev/null 2>&1; then
  echo "kept $NAME ($REGION)"
  exit 0
fi
tmp="$(mktemp -p "$( [[ -d /dev/shm ]] && echo /dev/shm || echo "${TMPDIR:-/tmp}" )")"
trap 'rm -f "$tmp"' EXIT
chmod 600 "$tmp"
python3 -c 'import json, secrets, sys; print(json.dumps({"Name": sys.argv[1], "Value": secrets.token_hex(32), "Type": "String", "Overwrite": True}))' "$NAME" >"$tmp"
aws ssm put-parameter --region "$REGION" --cli-input-json "file://$tmp" >/dev/null
echo "stored $NAME ($REGION)"
