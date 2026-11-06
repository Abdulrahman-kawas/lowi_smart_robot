#!/usr/bin/env bash
# Run spider-brain with the Anthropic key from SSM Parameter Store (never stored on disk).
#   aws ssm put-parameter --name /spider/anthropic_api_key --type SecureString --value 'sk-ant-...'
# The instance role needs ssm:GetParameter (+ kms:Decrypt) on that parameter.
#   ./run-brain.sh run "walk to the orange box"
set -euo pipefail
cd "$(dirname "$0")/../../brain"
ANTHROPIC_API_KEY="$(aws ssm get-parameter --name "${SSM_KEY_NAME:-/spider/anthropic_api_key}" \
  --with-decryption --query Parameter.Value --output text)"
export ANTHROPIC_API_KEY
export SB_ENV_FILE="${SB_ENV_FILE:-/etc/spider-brain/brain.env}"
exec uv run spider-brain "$@"
