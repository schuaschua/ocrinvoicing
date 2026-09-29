#!/usr/bin/env bash
#
# AD-17 step 1 (part 1): resource providers, the four resource groups, Terraform
# state containers, the two private-key vaults (OCR-129) and the three deploy identities
# with their role assignments. The identities have no federated credentials: the CI VM
# (ci-vm.sh) carries the shared and Dev ones as user-assigned managed identities
# (Dj, 2026-09-29). Idempotent: re-running skips what exists and re-applies settings
# and tags.

# shellcheck source-path=SCRIPTDIR source=lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

usage() {
  cat <<'EOF'
Usage: state-backend.sh [--dry-run]

Required environment variables:
  ARM_SUBSCRIPTION_ID        target subscription
  TAG_OWNER, TAG_COST_CENTRE, TAG_APPLICATION, TAG_DATA_CLASSIFICATION
                             P-17 tag values (environment is set per resource group)
EOF
}

parse_common_args "$@"
require_env ARM_SUBSCRIPTION_ID
require_tag_inputs

select_subscription
verify_role_ids

# Resource providers used by the stacks (azurerm sets resource_provider_registrations = "none").
step "Register resource providers"
for namespace in \
  Microsoft.AlertsManagement \
  Microsoft.App \
  Microsoft.CognitiveServices \
  Microsoft.Communication \
  Microsoft.Consumption \
  Microsoft.DBforPostgreSQL \
  Microsoft.Insights \
  Microsoft.KeyVault \
  Microsoft.ManagedIdentity \
  Microsoft.OperationalInsights \
  Microsoft.Storage \
  Microsoft.Web; do
  run az provider register --namespace "$namespace" --wait
done

# Resource groups: shared (21), dev (01), prod (11) and the bootstrap-only state
# group (22), each with the 5 tags. An existing group only has its tags re-applied.
# No deploy identity gets Contributor on the state group (plan Design Notes).
for pair in "shared:$(rg_name shared)" "dev:$(rg_name dev)" "prod:$(rg_name prod)" "shared:$STATE_RG"; do
  env="${pair%%:*}"
  group="${pair#*:}"
  step "Resource group $group"
  set_tags "$env"
  if exists az group show --name "$group"; then
    run az group update --name "$group" --tags "${TAGS[@]}"
  else
    run az group create --name "$group" --location "$LOCATION" --tags "${TAGS[@]}"
  fi
done

# Terraform state: Dj's existing account stdjtfstatesea (Dj, 2026-09-30), which this
# script does not own and never changes. It only checks that the account is Entra-auth
# only with versioning on, then adds this project's containers.
set_tags shared
shared_tags=("${TAGS[@]}")
step "State storage account $TFSTATE_ACCOUNT (existing, checked only)"
if ((!DRY_RUN)); then
  exists az storage account show --name "$TFSTATE_ACCOUNT" --resource-group "$TFSTATE_RG" ||
    die "state account $TFSTATE_ACCOUNT not found in $TFSTATE_RG"
  [[ "$(az storage account show --name "$TFSTATE_ACCOUNT" --resource-group "$TFSTATE_RG" \
    --query allowSharedKeyAccess -o tsv)" == false ]] ||
    die "$TFSTATE_ACCOUNT allows shared-key access; state must be Entra auth only"
  [[ "$(az storage account blob-service-properties show --account-name "$TFSTATE_ACCOUNT" \
    --resource-group "$TFSTATE_RG" --query isVersioningEnabled -o tsv)" == true ]] ||
    die "$TFSTATE_ACCOUNT has blob versioning off; state needs it on"
fi

# Containers through the management plane, so no data-plane role is needed.
for owner in shared dev prod; do
  container="$(state_container_name "$owner")"
  step "State container $container"
  if exists az storage container-rm show --storage-account "$TFSTATE_ACCOUNT" \
    --resource-group "$TFSTATE_RG" --name "$container"; then
    log "exists: container $container"
  else
    run az storage container-rm create --storage-account "$TFSTATE_ACCOUNT" \
      --resource-group "$TFSTATE_RG" --name "$container" --public-access off
  fi
done

# Private-key vaults (OCR-129): kv-22 (dev) and kv-23 (prod) in rg-22 hold only each
# environment's pgp-private-key. RBAC mode, purge protection, 7-day soft delete and
# public network access, like the environment vaults. Nobody gets a role here: the
# operator adds pgp-private-key and staff-api's secret-scoped read in step 4b.
for env in dev prod; do
  pk_vault="$(private_key_vault_name "$env")"
  step "Private-key vault $pk_vault ($env)"
  set_tags "$env"
  if exists az keyvault show --name "$pk_vault" --resource-group "$STATE_RG"; then
    # Soft delete is always on and its retention is fixed at creation.
    run az keyvault update --name "$pk_vault" --resource-group "$STATE_RG" \
      --enable-rbac-authorization true --enable-purge-protection true \
      --public-network-access Enabled --default-action Allow --bypass AzureServices --output none
    run az resource tag --resource-group "$STATE_RG" --name "$pk_vault" \
      --resource-type Microsoft.KeyVault/vaults --tags "${TAGS[@]}" --output none
  else
    run az keyvault create --name "$pk_vault" --resource-group "$STATE_RG" \
      --location "$LOCATION" --sku standard \
      --enable-rbac-authorization true --enable-purge-protection true --retention-days 7 \
      --public-network-access Enabled --default-action Allow --bypass AzureServices \
      --tags "${TAGS[@]}" --output none
  fi
done

# Deploy identities (id-21 shared, id-22 dev, id-23 prod).
for owner in shared dev prod; do
  identity="$(deploy_identity_name "$owner")"
  step "Deploy identity $identity ($owner)"
  if exists az identity show --name "$identity" --resource-group "$STATE_RG"; then
    # The az CLI has no "identity update"; tags go through the generic resource command.
    run az resource tag --resource-group "$STATE_RG" --name "$identity" \
      --resource-type Microsoft.ManagedIdentity/userAssignedIdentities --tags "${shared_tags[@]}" --output none
  else
    run az identity create --name "$identity" --resource-group "$STATE_RG" \
      --location "$LOCATION" --tags "${shared_tags[@]}"
  fi
done

# Deploy identity rights (azure.md rule 31 + AD-17 "Deploy identity rights").
# Runtime roles an environment deploy identity may assign in its own resource group
# (azure.md rule 9 and the AD-17 runtime role table; Key Vault Secrets Officer is for
# its own vault, AD-17 step 4).
env_assignable_roles=(
  "$ROLE_BLOB_DATA_CONTRIBUTOR"
  "$ROLE_BLOB_DATA_OWNER"
  "$ROLE_QUEUE_DATA_CONTRIBUTOR"
  "$ROLE_QUEUE_DATA_MESSAGE_SENDER"
  "$ROLE_TABLE_DATA_CONTRIBUTOR"
  "$ROLE_KV_SECRETS_USER"
  "$ROLE_KV_SECRETS_OFFICER"
  "$ROLE_MONITORING_METRICS_PUBLISHER"
)
env_condition="$(rbac_admin_condition "${env_assignable_roles[@]}")"

for owner in shared dev prod; do
  identity="$(deploy_identity_name "$owner")"
  step "Role assignments for $identity"
  principal_id="$(identity_principal_id "$identity" "$STATE_RG")"
  ensure_role_assignment "$principal_id" ServicePrincipal "$ROLE_CONTRIBUTOR" "$(rg_scope "$(rg_name "$owner")")"
  ensure_role_assignment "$principal_id" ServicePrincipal "$ROLE_BLOB_DATA_CONTRIBUTOR" "$(state_container_scope "$owner")"
  if [[ "$owner" != "shared" ]]; then
    ensure_role_assignment "$principal_id" ServicePrincipal "$ROLE_RBAC_ADMIN" \
      "$(rg_scope "$(rg_name "$owner")")" "$env_condition"
    ensure_role_assignment "$principal_id" ServicePrincipal "$ROLE_BLOB_DATA_READER" "$(state_container_scope shared)"
  fi
done

step "Done"
log "State: $TFSTATE_ACCOUNT in $TFSTATE_RG (containers: $(state_container_name shared) $(state_container_name dev) $(state_container_name prod))."
log "Private-key vaults: $(private_key_vault_name dev) (dev), $(private_key_vault_name prod) (prod) in $STATE_RG."
log "Next: app-registrations.sh, then budget-and-roles.sh, then ci-vm.sh (see README.md)."
