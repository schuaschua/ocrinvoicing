#!/usr/bin/env bash
#
# AD-17 step 3 (operator, after shared/foundation is applied): give each
# environment's deploy identity Role Based Access Control Administrator on the
# shared Document Intelligence resource, conditioned to assigning only Cognitive
# Services User, and only to service principals. Story 5.2 adds the same on the
# shared ACS (Communication Services), conditioned to assigning only the custom role
# ACS Email Sender; it is skipped, with a message, while ACS doesn't exist yet (no
# email domain set). Idempotent: re-run it after ACS is created.

# shellcheck source-path=SCRIPTDIR source=lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

usage() {
  cat <<'EOF'
Usage: rbac-step3.sh [--dry-run]

Required environment variables:
  ARM_SUBSCRIPTION_ID   target subscription
Run after infra/shared/foundation is applied, and again once it has created ACS Email
(email_custom_domain set, infra/bootstrap/README.md "Email domain").
EOF
}

parse_common_args "$@"
require_env ARM_SUBSCRIPTION_ID
select_subscription
verify_role_ids

shared_rg="$(rg_name shared)"
di_scope="$(rg_scope "$shared_rg")/providers/Microsoft.CognitiveServices/accounts/$(document_intelligence_name)"

step "Check the shared Document Intelligence resource exists"
if ((DRY_RUN)); then
  _print_cmd "[dry-run] (lookup)" az resource show --ids "$di_scope" >&2
else
  az resource show --ids "$di_scope" --output none || die "apply infra/shared/foundation first: $di_scope not found"
fi

di_condition="$(rbac_admin_condition "$ROLE_COGNITIVE_SERVICES_USER")"

for env in dev prod; do
  identity="$(deploy_identity_name "$env")"
  step "Conditioned RBAC Administrator for $identity ($env)"
  principal_id="$(identity_principal_id "$identity" "$STATE_RG")"
  ensure_role_assignment "$principal_id" ServicePrincipal "$ROLE_RBAC_ADMIN" "$di_scope" "$di_condition"
done

# --- Story 5.2 (AD-16): ACS Email Sender on the shared Communication Services ------------

acs_scope="$(rg_scope "$shared_rg")/providers/Microsoft.Communication/communicationServices/$(communication_service_name)"

step "Check the shared Communication Services resource exists"
acs_exists=1
if ((DRY_RUN)); then
  # The dry run shows the full grant path.
  _print_cmd "[dry-run] (lookup)" az resource show --ids "$acs_scope" >&2
elif ! exists az resource show --ids "$acs_scope"; then
  acs_exists=0
  log "skipped: $acs_scope does not exist yet. Set email_custom_domain in infra/shared/foundation, apply it, then re-run this script."
fi

if ((acs_exists)); then
  acs_role_id="$(acs_email_sender_role_id)"
  [[ -n "$acs_role_id" ]] || die "custom role '$ACS_EMAIL_SENDER_ROLE_NAME' not found: run budget-and-roles.sh first"
  acs_condition="$(rbac_admin_condition "$acs_role_id")"
  for env in dev prod; do
    identity="$(deploy_identity_name "$env")"
    step "Conditioned RBAC Administrator on ACS for $identity ($env)"
    principal_id="$(identity_principal_id "$identity" "$STATE_RG")"
    ensure_role_assignment "$principal_id" ServicePrincipal "$ROLE_RBAC_ADMIN" "$acs_scope" "$acs_condition"
  done
fi

step "Done"
log "Next: apply infra/dev/foundation and infra/prod/foundation, then pgp-step4b.sh (see README.md)."
