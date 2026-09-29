#!/usr/bin/env bash
#
# AD-17 step 1 (part 3): the custom role "ACS Email Sender". Idempotent: the role is
# updated in place. The $8 subscription budget this script used to create is dropped
# (Dj, 2026-09-30: the subscription holds other projects; the resource-group budgets
# track this project). The file keeps its name so the run order stays the same.

# shellcheck source-path=SCRIPTDIR source=lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

usage() {
  cat <<'EOF'
Usage: budget-and-roles.sh [--dry-run]

Required environment variables:
  ARM_SUBSCRIPTION_ID   target subscription
EOF
}

parse_common_args "$@"
require_env ARM_SUBSCRIPTION_ID
select_subscription

work_dir=""
cleanup() {
  if [[ -n "$work_dir" ]]; then rm -rf "$work_dir"; fi
}
trap cleanup EXIT
if ((DRY_RUN)); then
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

step "Done"
log "Next: apply infra/shared/foundation, then rbac-step3.sh (see README.md)."
