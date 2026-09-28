#!/usr/bin/env bash
#
# AD-17 step 1 (part 3): the custom role "ACS Email Sender" and the $8 subscription
# budget alert (AD-12). Idempotent: the role is updated in place; an existing budget
# is left unchanged (its start date cannot be moved).

# shellcheck source-path=SCRIPTDIR source=lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

usage() {
  cat <<'EOF'
Usage: budget-and-roles.sh [--dry-run]

Required environment variables:
  ARM_SUBSCRIPTION_ID   target subscription
  ALERT_EMAIL           where the subscription budget alert is sent (Dj)
EOF
}

parse_common_args "$@"
require_env ARM_SUBSCRIPTION_ID ALERT_EMAIL
select_subscription

readonly SUBSCRIPTION_BUDGET_AMOUNT=8
# Shared range (21-29); budget-21 is the shared resource-group budget in shared/foundation.
SUBSCRIPTION_BUDGET_NAME="$(resource_name budget 22)"
readonly SUBSCRIPTION_BUDGET_NAME
readonly BUDGET_API_VERSION="2024-08-01"

work_dir=""
cleanup() {
  if [[ -n "$work_dir" ]]; then rm -rf "$work_dir"; fi
}
trap cleanup EXIT
if ((DRY_RUN)); then
  work_dir=""
  out_dir="<scratch>"
else
  work_dir="$(scratch_dir)"
  out_dir="$work_dir"
fi

# The email send action only. [ASSUMPTION] Microsoft documents this pair for sending
# with Entra auth; the exact minimum is an open question in the spine ("To test early").
role_json="$(
  cat <<EOF
{
  "Name": "$ACS_EMAIL_SENDER_ROLE_NAME",
  "IsCustom": true,
  "Description": "Send email through Azure Communication Services only (AD-16, AD-17 step 1).",
  "Actions": [
    "Microsoft.Communication/CommunicationServices/Read",
    "Microsoft.Communication/EmailServices/write"
  ],
  "NotActions": [],
  "DataActions": [],
  "NotDataActions": [],
  "AssignableScopes": ["/subscriptions/$ARM_SUBSCRIPTION_ID"]
}
EOF
)"

step "Custom role $ACS_EMAIL_SENDER_ROLE_NAME"
if ((DRY_RUN)); then
  log "$role_json"
else
  printf '%s\n' "$role_json" >"$out_dir/acs-email-sender.json"
fi
existing_role_id="$(value_or_placeholder "" az role definition list --custom-role-only true \
  --name "$ACS_EMAIL_SENDER_ROLE_NAME" --scope "/subscriptions/$ARM_SUBSCRIPTION_ID" --query '[0].name' -o tsv)"
if [[ -n "$existing_role_id" ]]; then
  if ((DRY_RUN)); then
    run az role definition update --role-definition "@$out_dir/acs-email-sender.json"
  else
    # Update needs the existing id in the definition.
    python3 - "$out_dir/acs-email-sender.json" "$existing_role_id" <<'PY'
import json, sys
path, role_id = sys.argv[1], sys.argv[2]
with open(path, encoding="utf-8") as handle:
    role = json.load(handle)
role["Id"] = role_id
with open(path, "w", encoding="utf-8") as handle:
    json.dump(role, handle)
PY
    run az role definition update --role-definition "@$out_dir/acs-email-sender.json" --output none
  fi
else
  run az role definition create --role-definition "@$out_dir/acs-email-sender.json" --output none
fi

step "Subscription budget $SUBSCRIPTION_BUDGET_NAME (\$$SUBSCRIPTION_BUDGET_AMOUNT)"
budget_url="https://management.azure.com/subscriptions/$ARM_SUBSCRIPTION_ID/providers/Microsoft.Consumption/budgets/$SUBSCRIPTION_BUDGET_NAME?api-version=$BUDGET_API_VERSION"
if exists az rest --method get --url "$budget_url"; then
  log "exists: $SUBSCRIPTION_BUDGET_NAME (left unchanged)"
else
  start_date="$(date -u +%Y-%m-01T00:00:00Z)"
  budget_json="$(
    cat <<EOF
{
  "properties": {
    "category": "Cost",
    "amount": $SUBSCRIPTION_BUDGET_AMOUNT,
    "timeGrain": "Monthly",
    "timePeriod": { "startDate": "$start_date" },
    "notifications": {
      "actual_gt_100_percent": {
        "enabled": true,
        "operator": "GreaterThanOrEqualTo",
        "threshold": 100,
        "thresholdType": "Actual",
        "contactEmails": ["$ALERT_EMAIL"]
      }
    }
  }
}
EOF
  )"
  if ((DRY_RUN)); then
    log "$budget_json"
  else
    printf '%s\n' "$budget_json" >"$out_dir/subscription-budget.json"
  fi
  run az rest --method put --url "$budget_url" --body "@$out_dir/subscription-budget.json" --output none
fi

step "Done"
log "Next: apply infra/shared/foundation, then rbac-step3.sh (see README.md)."
