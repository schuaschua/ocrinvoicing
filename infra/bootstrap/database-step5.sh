#!/usr/bin/env bash
#
# AD-17 step 5 (operator, once per environment, as the PostgreSQL Entra admin):
#   - the AD-11 database logins, ownership and CONNECT rules, and the pgcrypto
#     extension in the environment's database (database-step5.sql);
#   - Dj's user gets Key Vault Secrets User on pgp-public-key and hmac-key only (never
#     the private key, which is in another vault: OCR-129) and Storage Table Data
#     Contributor on the environment's storage account, for the supplier load script.
#     A vault-wide Secrets User assignment from an earlier run is removed.
# Connects directly over TLS with an Entra token (the firewall is open for the PoC).
# Idempotent. Run verify-db-isolation.sh afterwards.

# shellcheck source-path=SCRIPTDIR source=lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

usage() {
  cat <<'EOF'
Usage: database-step5.sh [--dry-run]

Required environment variables:
  ARM_SUBSCRIPTION_ID   target subscription
  ENVIRONMENT           dev or prod
  DJ_USER_UPN           Dj's Entra user principal name (the load-script login)
  PG_ADMIN_USER         the server's Entra admin used to connect; must be a separate
                        principal (e.g. an Entra group) from DJ_USER_UPN
EOF
}

parse_common_args "$@"
require_env ARM_SUBSCRIPTION_ID DJ_USER_UPN PG_ADMIN_USER
require_env_choice ENVIRONMENT dev prod
require_tools az psql
# The load script must not run as the server admin (least privilege, AD-11).
[[ "$PG_ADMIN_USER" != "$DJ_USER_UPN" ]] ||
  die "PG_ADMIN_USER must be a separate principal from DJ_USER_UPN (the load-script login)"
select_subscription

if [[ "$ENVIRONMENT" == "dev" ]]; then other_env="prod"; else other_env="dev"; fi
env_db="$(env_database_name "$ENVIRONMENT")"
other_db="$(env_database_name "$other_env")"

step "Get an Entra token for PostgreSQL"
if ((DRY_RUN)); then
  _print_cmd "[dry-run] (lookup)" az account get-access-token --resource-type oss-rdbms --query accessToken -o tsv >&2
else
  PGPASSWORD="$(az account get-access-token --resource-type oss-rdbms --query accessToken -o tsv)"
  export PGPASSWORD
fi

step "Logins, ownership and CONNECT for $env_db"
run psql "host=$(postgres_fqdn) port=5432 dbname=postgres user=$PG_ADMIN_USER sslmode=require" \
  --no-psqlrc --quiet \
  -v "env_db=$env_db" \
  -v "other_db=$other_db" \
  -v "pipeline_login=$(app_identity_name "$ENVIRONMENT" pipeline)" \
  -v "staff_login=$(app_identity_name "$ENVIRONMENT" staff-api)" \
  -v "accounts_login=$(app_identity_name "$ENVIRONMENT" accounts-sim)" \
  -v "deploy_login=$(deploy_identity_name "$ENVIRONMENT")" \
  -v "dj_login=$DJ_USER_UPN" \
  -f "$BOOTSTRAP_DIR/database-step5.sql"

step "Load-script rights for $DJ_USER_UPN"
dj_object_id="$(value_or_placeholder "<objectId-of-$DJ_USER_UPN>" \
  az ad user show --id "$DJ_USER_UPN" --query id -o tsv)"
env_rg_scope="$(rg_scope "$(rg_name "$ENVIRONMENT")")"
vault_scope="$env_rg_scope/providers/Microsoft.KeyVault/vaults/$(key_vault_name "$ENVIRONMENT")"
for secret in pgp-public-key hmac-key; do
  ensure_role_assignment "$dj_object_id" User "$ROLE_KV_SECRETS_USER" "$vault_scope/secrets/$secret"
done
remove_role_assignment "$dj_object_id" "$ROLE_KV_SECRETS_USER" "$vault_scope"
ensure_role_assignment "$dj_object_id" User "$ROLE_TABLE_DATA_CONTRIBUTOR" \
  "$env_rg_scope/providers/Microsoft.Storage/storageAccounts/$(env_storage_name "$ENVIRONMENT")"

step "Done"
log "Next: verify-db-isolation.sh (see README.md)."
