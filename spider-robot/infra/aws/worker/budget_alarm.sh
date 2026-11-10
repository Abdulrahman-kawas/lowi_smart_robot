#!/usr/bin/env bash
# Required before first use of the worker: e-mail at 80% of a small monthly budget.
#   ACCOUNT_ID=123456789012 EMAIL=you@example.com LIMIT_USD=20 bash budget_alarm.sh
set -euo pipefail
: "${ACCOUNT_ID:?set ACCOUNT_ID}" "${EMAIL:?set EMAIL}"
LIMIT_USD="${LIMIT_USD:-20}"
aws budgets create-budget --account-id "$ACCOUNT_ID" \
  --budget "{\"BudgetName\":\"spider-worker\",\"BudgetLimit\":{\"Amount\":\"$LIMIT_USD\",\"Unit\":\"USD\"},\"TimeUnit\":\"MONTHLY\",\"BudgetType\":\"COST\"}" \
  --notifications-with-subscribers "[{\"Notification\":{\"NotificationType\":\"ACTUAL\",\"ComparisonOperator\":\"GREATER_THAN\",\"Threshold\":80,\"ThresholdType\":\"PERCENTAGE\"},\"Subscribers\":[{\"SubscriptionType\":\"EMAIL\",\"Address\":\"$EMAIL\"}]}]"
