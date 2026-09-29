#!/usr/bin/env bash
#
# AD-17 step 3 (operator, after shared/foundation is applied): give each
# environment's deploy identity Role Based Access Control Administrator on the
# shared Document Intelligence resource, conditioned to assigning only Cognitive
# Services User, and only to service principals. Idempotent. Story 5.2 adds the
# ACS part along with ACS Email itself (Dj, 2026-09-30).

# shellcheck source-path=SCRIPTDIR source=lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

usage() {
  cat <<'EOF'
Usage: rbac-step3.sh [--dry-run]

Required environment variables:
  ARM_SUBSCRIPTION_ID   target subscription
Run after infra/shared/foundation is applied.
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

step "Done"
log "Next: apply infra/dev/foundation and infra/prod/foundation, then pgp-step4b.sh (see README.md)."
