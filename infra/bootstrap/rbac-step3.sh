#!/usr/bin/env bash
#
# AD-17 step 3 (operator, after shared/foundation is applied): give each
# environment's deploy identity Role Based Access Control Administrator on the
# shared Document Intelligence and ACS resources, conditioned to assigning only the
# runtime roles those resources need (Cognitive Services User on DI, ACS Email
# Sender on ACS), and only to service principals. Idempotent.

# shellcheck source-path=SCRIPTDIR source=lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

usage() {
  cat <<'EOF'
Usage: rbac-step3.sh [--dry-run]

Required environment variables:
  ARM_SUBSCRIPTION_ID   target subscription
Run after infra/shared/foundation is applied and budget-and-roles.sh has created
the "ACS Email Sender" role.
EOF
}

parse_common_args "$@"
require_env ARM_SUBSCRIPTION_ID
select_subscription
verify_role_ids

shared_rg="$(rg_name shared)"
di_scope="$(rg_scope "$shared_rg")/providers/Microsoft.CognitiveServices/accounts/$(document_intelligence_name)"
acs_scope="$(rg_scope "$shared_rg")/providers/Microsoft.Communication/communicationServices/$(communication_service_name)"

step "Check the shared resources exist"
if ((DRY_RUN)); then
  _print_cmd "[dry-run] (lookup)" az resource show --ids "$di_scope" >&2
  _print_cmd "[dry-run] (lookup)" az resource show --ids "$acs_scope" >&2
else
  az resource show --ids "$di_scope" --output none || die "apply infra/shared/foundation first: $di_scope not found"
  az resource show --ids "$acs_scope" --output none || die "apply infra/shared/foundation first: $acs_scope not found"
fi

step "Look up the $ACS_EMAIL_SENDER_ROLE_NAME role"
acs_sender_role_id="$(value_or_placeholder "<roleId-of-$ACS_EMAIL_SENDER_ROLE_NAME>" \
  az role definition list --custom-role-only true --name "$ACS_EMAIL_SENDER_ROLE_NAME" \
  --scope "$(subscription_scope)" --query '[0].name' -o tsv)"
[[ -n "$acs_sender_role_id" ]] || die "role '$ACS_EMAIL_SENDER_ROLE_NAME' not found; run budget-and-roles.sh first"

di_condition="$(rbac_admin_condition "$ROLE_COGNITIVE_SERVICES_USER")"
acs_condition="$(rbac_admin_condition "$acs_sender_role_id")"

for env in dev prod; do
  identity="$(deploy_identity_name "$env")"
  step "Conditioned RBAC Administrator for $identity ($env)"
  principal_id="$(identity_principal_id "$identity" "$STATE_RG")"
  ensure_role_assignment "$principal_id" ServicePrincipal "$ROLE_RBAC_ADMIN" "$di_scope" "$di_condition"
  ensure_role_assignment "$principal_id" ServicePrincipal "$ROLE_RBAC_ADMIN" "$acs_scope" "$acs_condition"
done

step "Done"
log "Next: apply infra/dev/foundation and infra/prod/foundation, then pgp-step4b.sh (see README.md)."
