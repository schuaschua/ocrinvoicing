#!/usr/bin/env bash
#
# AD-17 step 1 (part 3): the custom role "ACS Email Sender" and the $8 subscription
# budget alert (AD-12). Idempotent: the role is updated in place. An existing budget
# keeps its amount and start date (which cannot be moved); the only change ever made
# to it is adding the shared action group (ag-21) to its notifications once
# SHARED_ACTION_GROUP_ID is given (Story 1.5).

# shellcheck source-path=SCRIPTDIR source=lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

usage() {
  cat <<'EOF'
Usage: budget-and-roles.sh [--dry-run]

Required environment variables:
  ARM_SUBSCRIPTION_ID   target subscription
  ALERT_EMAIL           where the subscription budget alert is sent (Dj)

Optional:
  SHARED_ACTION_GROUP_ID  resource id of the shared action group ag-21
                          (terraform output action_group_id of infra/shared/foundation).
                          The budget then notifies through it as well as by email. The
                          first run (step 1) comes before shared/foundation exists, so
                          re-run this script with it after step 2.
EOF
}

parse_common_args "$@"
require_env ARM_SUBSCRIPTION_ID ALERT_EMAIL
SHARED_ACTION_GROUP_ID="${SHARED_ACTION_GROUP_ID:-}"
if [[ -n "$SHARED_ACTION_GROUP_ID" ]]; then
  # Case-insensitive, as ARM ids are (bash 3.2 has no ${var,,}). Each segment is
  # limited to ARM name characters, so nothing else can reach the budget JSON.
  if ! printf '%s\n' "$SHARED_ACTION_GROUP_ID" |
    grep -Eiq '^/subscriptions/[A-Za-z0-9._()-]+/resourceGroups/[A-Za-z0-9._()-]+/providers/microsoft\.insights/actionGroups/[A-Za-z0-9._()-]+$'; then
    die "SHARED_ACTION_GROUP_ID must be an action group resource id (/subscriptions/.../providers/microsoft.insights/actionGroups/<name>)"
  fi
else
  warn "SHARED_ACTION_GROUP_ID is not set: the subscription budget alerts by email only. Re-run with it once infra/shared/foundation is applied (README.md, step 2)."
fi
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
  if [[ -z "$SHARED_ACTION_GROUP_ID" ]]; then
    log "exists: $SUBSCRIPTION_BUDGET_NAME (left unchanged)"
  else
    # Add ag-21 to every notification and keep everything else (amount, start date,
    # thresholds, emails) exactly as it is.
    az rest --method get --url "$budget_url" --output json >"$out_dir/subscription-budget-current.json"
    attach_status=0
    python3 - "$out_dir/subscription-budget-current.json" "$out_dir/subscription-budget.json" \
      "$SHARED_ACTION_GROUP_ID" <<'PY' || attach_status=$?
import json, sys
current_path, update_path, group = sys.argv[1], sys.argv[2], sys.argv[3]
with open(current_path, encoding="utf-8") as handle:
    budget = json.load(handle)
properties = budget.get("properties") or {}
notifications = properties.get("notifications") or {}
if not notifications:
    print("ERROR: the existing budget has no notifications", file=sys.stderr)
    sys.exit(1)
changed = False
for notification in notifications.values():
    groups = notification.get("contactGroups") or []
    if group.lower() not in (g.lower() for g in groups):
        notification["contactGroups"] = [*groups, group]
        changed = True
if not changed:
    sys.exit(3)
# Read-only fields are not sent back; the eTag is, so a concurrent change is refused.
for key in ("currentSpend", "forecastSpend"):
    properties.pop(key, None)
update = {"properties": properties}
if budget.get("eTag"):
    update["eTag"] = budget["eTag"]
with open(update_path, "w", encoding="utf-8") as handle:
    json.dump(update, handle)
PY
    case "$attach_status" in
      0) run az rest --method put --url "$budget_url" --body "@$out_dir/subscription-budget.json" --output none ;;
      3) log "exists: $SUBSCRIPTION_BUDGET_NAME (already notifies ${SHARED_ACTION_GROUP_ID##*/})" ;;
      *) die "could not add the action group to the existing budget $SUBSCRIPTION_BUDGET_NAME" ;;
    esac
  fi
else
  contact_groups=""
  if [[ -n "$SHARED_ACTION_GROUP_ID" ]]; then
    contact_groups=",
        \"contactGroups\": [\"$SHARED_ACTION_GROUP_ID\"]"
  fi
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
        "contactEmails": ["$ALERT_EMAIL"]$contact_groups
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
if [[ -n "$SHARED_ACTION_GROUP_ID" ]]; then
  log "Next: ./test-alerts.sh, then check that Dj received each test email (see README.md)."
else
  log "Next: apply infra/shared/foundation, then rbac-step3.sh, then re-run this script with SHARED_ACTION_GROUP_ID (see README.md)."
fi
