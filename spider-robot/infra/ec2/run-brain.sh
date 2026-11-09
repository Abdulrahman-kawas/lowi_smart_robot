#!/usr/bin/env bash
# Run spider-brain with its keys from SSM Parameter Store (never stored on disk).
#   aws ssm put-parameter --name /spider/anthropic_api_key --type SecureString --value 'sk-ant-...'
# The instance role needs ssm:GetParameter (+ kms:Decrypt) on that parameter.
#   ./run-brain.sh run "walk to the orange box"
set -euo pipefail
cd "$(dirname "$0")/../../brain"
ANTHROPIC_API_KEY="$(aws ssm get-parameter --name "${SSM_KEY_NAME:-/spider/anthropic_api_key}" \
  --with-decryption --query Parameter.Value --output text)"
export ANTHROPIC_API_KEY
# Optional keys (Part 2): voice (Gemini) and the Telegram bot. Missing ones are skipped.
for pair in GEMINI_API_KEY:/spider/gemini_api_key TELEGRAM_BOT_TOKEN:/spider/telegram_token; do
  value="$(aws ssm get-parameter --name "${pair#*:}" --with-decryption \
    --query Parameter.Value --output text 2>/dev/null || true)"
  [[ -n "$value" ]] && export "${pair%%:*}=$value"
done
export SB_ENV_FILE="${SB_ENV_FILE:-/etc/spider-brain/brain.env}"
exec uv run spider-brain "$@"
