#!/usr/bin/env bash
#
# AD-17 step 1 (part 2): per environment, the two Entra app registrations.
#   staff-api    - single tenant, app roles admin/finance/procurement/management/goods_in,
#                  "assignment required" on its service principal, ID tokens on, no secret (AD-14).
#   accounts-sim - single tenant, identifier URI api://<appId>, so the pipeline identity
#                  can request a token for it (AD-10).
# The staff-api redirect URI is added later (AD-17 step 8). Idempotent: existing
# registrations are updated in place, and missing app roles are added.

# shellcheck source-path=SCRIPTDIR source=lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

usage() {
  cat <<'EOF'
Usage: app-registrations.sh [--dry-run]

Required environment variables:
  ARM_TENANT_ID   the Entra tenant; the signed-in az session must be in it
EOF
}

parse_common_args "$@"
require_env ARM_TENANT_ID
require_tools az python3

readonly STAFF_ROLES=(admin finance procurement management goods_in)

step "Check tenant"
if ((DRY_RUN)); then
  _print_cmd "[dry-run] (lookup)" az account show --query tenantId -o tsv >&2
else
  current_tenant="$(az account show --query tenantId -o tsv)"
  [[ "$current_tenant" == "$ARM_TENANT_ID" ]] ||
    die "az is signed in to tenant $current_tenant, expected ARM_TENANT_ID"
fi

# app_id_by_name NAME - the appId of the one registration with this display name,
# or empty. Stops if the name matches more than one registration.
app_id_by_name() {
  local ids count
  ids="$(value_or_placeholder "" az ad app list --display-name "$1" --query '[].appId' -o tsv)"
  count="$(printf '%s' "$ids" | grep -c . || true)"
  if ((count > 1)); then
    die "display name '$1' matches $count app registrations; remove the duplicates first"
  fi
  printf '%s\n' "$ids"
}

# create_app ARGS... - runs az ad app create and prints the new appId from its own
# output (a list lookup right after create can miss it through replication lag).
create_app() {
  _print_cmd "+" az ad app create "$@" --query appId -o tsv >&2
  local app_id
  app_id="$(az ad app create "$@" --query appId -o tsv)"
  [[ -n "$app_id" ]] || die "az ad app create returned no appId"
  printf '%s\n' "$app_id"
}

# write_roles_json FILE EXISTING_JSON - desired app roles, keeping the ids of roles
# that already exist so re-runs never replace them.
write_roles_json() {
  local file="$1" existing="$2"
  EXISTING_ROLES="$existing" python3 - "$file" "${STAFF_ROLES[@]}" <<'PY'
import json, os, sys, uuid
path, wanted = sys.argv[1], sys.argv[2:]
existing = json.loads(os.environ.get("EXISTING_ROLES") or "[]")
by_value = {role.get("value"): role for role in existing}
roles = list(existing)
for value in wanted:
    if value not in by_value:
        roles.append({
            "allowedMemberTypes": ["User"],
            "description": f"Babaloo staff role {value}",
            "displayName": value,
            "id": str(uuid.uuid4()),
            "isEnabled": True,
            "value": value,
        })
with open(path, "w", encoding="utf-8") as handle:
    json.dump(roles, handle)
print("changed" if len(roles) != len(existing) else "unchanged")
PY
}

# Waits between service-principal checks; tests set SP_WAIT_SECONDS=0.
SP_WAIT_ATTEMPTS="${SP_WAIT_ATTEMPTS:-10}"
SP_WAIT_SECONDS="${SP_WAIT_SECONDS:-6}"

ensure_service_principal() {
  local app_id="$1" attempt
  if exists az ad sp show --id "$app_id"; then
    log "exists: service principal for $app_id"
    return 0
  fi
  run az ad sp create --id "$app_id"
  ((DRY_RUN)) && return 0
  # A new service principal can take a while to become visible to later calls.
  for ((attempt = 1; attempt <= SP_WAIT_ATTEMPTS; attempt++)); do
    if exists az ad sp show --id "$app_id"; then
      return 0
    fi
    sleep "$SP_WAIT_SECONDS"
  done
  die "service principal for $app_id not visible after $SP_WAIT_ATTEMPTS checks"
}

work_dir=""
cleanup() {
  if [[ -n "$work_dir" ]]; then rm -rf "$work_dir"; fi
}
trap cleanup EXIT

for env in dev prod; do
  staff_name="$NAME_PREFIX-staff-api-$env"
  step "App registration $staff_name"
  staff_app_id="$(app_id_by_name "$staff_name")"
  if ((DRY_RUN)); then
    run az ad app create --display-name "$staff_name" --sign-in-audience AzureADMyOrg \
      --enable-id-token-issuance true --app-roles "@<roles.json: ${STAFF_ROLES[*]}>"
    staff_app_id="<appId-of-$staff_name>"
  else
    [[ -n "$work_dir" ]] || work_dir="$(scratch_dir)"
    roles_file="$work_dir/staff-roles-$env.json"
    if [[ -z "$staff_app_id" ]]; then
      write_roles_json "$roles_file" "[]" >/dev/null
      staff_app_id="$(create_app --display-name "$staff_name" --sign-in-audience AzureADMyOrg \
        --enable-id-token-issuance true --app-roles "@$roles_file")"
    else
      log "exists: $staff_name ($staff_app_id)"
      run az ad app update --id "$staff_app_id" --enable-id-token-issuance true
      existing_roles="$(az ad app show --id "$staff_app_id" --query appRoles -o json)"
      if [[ "$(write_roles_json "$roles_file" "$existing_roles")" == "changed" ]]; then
        run az ad app update --id "$staff_app_id" --app-roles "@$roles_file"
      else
        log "app roles up to date"
      fi
    fi
  fi
  # No group claims (Story 2.7): staff-api reads only app roles, and a user in many
  # groups would otherwise swell the session and the X-MS-CLIENT-PRINCIPAL header.
  # Setting it again is harmless, so a re-run keeps it off.
  run az ad app update --id "$staff_app_id" --set groupMembershipClaims=None
  ensure_service_principal "$staff_app_id"
  run az ad sp update --id "$staff_app_id" --set appRoleAssignmentRequired=true

  sim_name="$NAME_PREFIX-accounts-sim-$env"
  step "App registration $sim_name"
  sim_app_id="$(app_id_by_name "$sim_name")"
  if [[ -z "$sim_app_id" ]]; then
    if ((DRY_RUN)); then
      run az ad app create --display-name "$sim_name" --sign-in-audience AzureADMyOrg --query appId -o tsv
      sim_app_id="<appId-of-$sim_name>"
    else
      sim_app_id="$(create_app --display-name "$sim_name" --sign-in-audience AzureADMyOrg)"
    fi
  else
    log "exists: $sim_name ($sim_app_id)"
  fi
  run az ad app update --id "$sim_app_id" --identifier-uris "api://$sim_app_id"
  ensure_service_principal "$sim_app_id"

  log "$env: staff-api client id $staff_app_id; accounts-sim client id $sim_app_id (needed by <env>/app, Story 1.3)"
done

step "Done"
log "Next: budget-and-roles.sh (see README.md)."
