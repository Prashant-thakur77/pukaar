#!/usr/bin/env bash
# Print `export NAME=value` lines for the deployed stack's outputs.
# Usage: eval "$(scripts/stack_env.sh)"
set -euo pipefail
STACK="${PUKAAR_STACK:-pukaar-dev}"
REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-us-east-1}}"

aws cloudformation describe-stacks --stack-name "$STACK" --region "$REGION" \
  --query 'Stacks[0].Outputs[].[OutputKey,OutputValue]' --output text |
while read -r key value; do
  printf 'export STACK_%s=%q\n' "$key" "$value"
done
cat <<EOV
export AWS_REGION=$REGION
export PUKAAR_MODE=aws
export PUKAAR_AWS_REGION=$REGION
export PUKAAR_TABLE_NAME=\$STACK_TableName
export PUKAAR_BUCKET=\$STACK_BucketName
export PUKAAR_STATE_MACHINE_ARN=\$STACK_StateMachineArn
EOV
