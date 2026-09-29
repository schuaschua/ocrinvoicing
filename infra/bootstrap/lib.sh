#!/usr/bin/env bash
# shellcheck shell=bash
# shellcheck disable=SC2034  # constants and TAGS are used by the scripts that source this file
#
# Shared helpers for the operator bootstrap scripts (spine AD-17 steps 1, 3, 4b, 5).
# Sourced, never executed. Every script supports --dry-run, which prints each planned
# az/psql/gpg call and never calls Azure: read-only lookups are skipped and treated
# as "absent", so the dry run shows the full create path.

set -Eeuo pipefail

BOOTSTRAP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$BOOTSTRAP_DIR/../.." && pwd)"
export BOOTSTRAP_DIR REPO_ROOT

DRY_RUN=0
CURRENT_STEP="startup"

# ---------------------------------------------------------------------------
# Naming (P-16) - mirrors infra/modules/naming. Keep the two in step.
#   babaloo-sea-lng-<type>-<nn>; Dev 01-09, Prod 11-19, shared 21-29.
#   Storage accounts drop the hyphens.
# ---------------------------------------------------------------------------
readonly NAME_PREFIX="babaloo-sea-lng"
readonly STORAGE_PREFIX="babaloosealng"
LOCATION="${LOCATION:-southeastasia}"

env_base() {
  case "$1" in
    dev) echo 1 ;;
    prod) echo 11 ;;
    shared) echo 21 ;;
    *) die "unknown environment '$1' (expected dev, prod or shared)" ;;
  esac
}

# resource_name <type> <number>
resource_name() { printf '%s-%s-%02d' "$NAME_PREFIX" "$1" "$2"; }
# storage_name <type> <number>
storage_name() { printf '%s%s%02d' "$STORAGE_PREFIX" "$1" "$2"; }

rg_name() { resource_name rg "$(env_base "$1")"; }

# Terraform state and the deploy identities live in a bootstrap-only resource group
# (rg-22, shared range). No Terraform stack manages it and no deploy identity holds
# Contributor on it, so one stack's identity cannot alter another's identity or state.
STATE_RG="$(resource_name rg 22)"
STATE_ACCOUNT="$(storage_name st 21)"
readonly STATE_RG STATE_ACCOUNT
readonly STATE_CONTAINERS=(shared dev prod)

# Deploy identities: id-21 shared, id-22 dev, id-23 prod (plan Design Notes).
deploy_identity_name() {
  case "$1" in
    shared) resource_name id 21 ;;
    dev) resource_name id 22 ;;
    prod) resource_name id 23 ;;
    *) die "unknown stack owner '$1'" ;;
  esac
}

# Position of each app in naming-module order (identities, plans and function apps).
app_offset() {
  case "$1" in
    supplier-api) echo 0 ;;
    staff-api) echo 1 ;;
    pipeline) echo 2 ;;
    accounts-sim) echo 3 ;;
    *) die "unknown app '$1'" ;;
  esac
}

# Runtime identities per environment, in naming-module order.
app_identity_name() { resource_name id "$(($(env_base "$1") + $(app_offset "$2")))"; }
# Flex Function apps (AD-1), numbered like their identities (naming module app_names).
function_app_name() { resource_name func "$(($(env_base "$1") + $(app_offset "$2")))"; }

key_vault_name() { resource_name kv "$(env_base "$1")"; }
# Private-key vaults (OCR-129): one per environment in the bootstrap-only rg-22, kv-22 Dev
# and kv-23 Prod. They hold only pgp-private-key, which only the environment's staff-api
# identity may read. No Terraform stack manages them (infra/modules/naming only names them).
private_key_vault_name() {
  case "$1" in
    dev) resource_name kv 22 ;;
    prod) resource_name kv 23 ;;
    *) die "unknown environment '$1' (expected dev or prod)" ;;
  esac
}
# The Azure Monitor action group of each stack (ag-01 dev, ag-11 prod, ag-21 shared).
action_group_name() { resource_name ag "$(env_base "$1")"; }
env_storage_name() { storage_name st "$(env_base "$1")"; }
env_database_name() { echo "invoicing_$1"; }

postgres_server_name() { resource_name psql 21; }
postgres_fqdn() { echo "$(postgres_server_name).postgres.database.azure.com"; }
document_intelligence_name() { resource_name di 21; }

# Entra security groups (Dj, 2026-09-29: his guest UPN is over PostgreSQL's 63-character
# role-name limit and holds '#', so groups are the database logins he uses). `grp` is
# this project's type code. They are Entra objects, not Azure resources: app-registrations.sh
# creates them and infra/modules/naming does not name them. A member signs in to
# PostgreSQL with the group name as the user and their own Entra token.
# loaders_group_name <dev|prod> - the supplier load script's login (grp-01 dev, grp-11 prod).
loaders_group_name() {
  case "$1" in
    dev | prod) resource_name grp "$(env_base "$1")" ;;
    *) die "unknown environment '$1' (expected dev or prod)" ;;
  esac
}
# The PostgreSQL Entra admin (grp-21, shared), set in infra/shared/foundation.
pg_admins_group_name() { resource_name grp "$(env_base shared)"; }

# ---------------------------------------------------------------------------
# Built-in role definition ids (identical in every tenant). verify_role_ids
# checks them against Azure before any assignment is made.
# ---------------------------------------------------------------------------
readonly ROLE_CONTRIBUTOR="b24988ac-6180-42a0-ab88-20f7382dd24c"
readonly ROLE_RBAC_ADMIN="f58310d9-a9f6-439a-9e8d-f62e7b41a168"
readonly ROLE_BLOB_DATA_CONTRIBUTOR="ba92f5b4-2d11-453d-a403-e96b0029c9fe"
readonly ROLE_BLOB_DATA_OWNER="b7e6dc6d-f1e8-4753-8033-0f276bb0955b"
readonly ROLE_BLOB_DATA_READER="2a2b9908-6ea1-4ae2-8e65-a410df84e7d1"
readonly ROLE_QUEUE_DATA_CONTRIBUTOR="974c5e8b-45b9-4653-ba55-5f855dd0fb88"
readonly ROLE_QUEUE_DATA_MESSAGE_SENDER="c6a89b2d-59bc-44d0-9896-0f6e12d7b80a"
readonly ROLE_TABLE_DATA_CONTRIBUTOR="0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3"
readonly ROLE_KV_SECRETS_USER="4633458b-17de-408a-b874-0445c86b69e6"
readonly ROLE_KV_SECRETS_OFFICER="b86a8fe4-44ce-4948-aee5-eccb2c155cd7"
readonly ROLE_MONITORING_METRICS_PUBLISHER="3913510d-42f4-4e42-8a64-420c390055eb"
readonly ROLE_COGNITIVE_SERVICES_USER="a97b65f3-24c7-4388-baec-2e87135dc908"

readonly ACS_EMAIL_SENDER_ROLE_NAME="ACS Email Sender"

# ---------------------------------------------------------------------------
# Logging, errors and argument handling
# ---------------------------------------------------------------------------
log() { printf '%s\n' "$*"; }
warn() { printf 'WARNING: %s\n' "$*" >&2; }
die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

step() {
  CURRENT_STEP="$*"
  printf '\n==> %s\n' "$*"
}

_on_error() {
  local status=$?
  printf 'ERROR: step "%s" failed (exit %s). Fix the cause and re-run; completed steps are skipped.\n' \
    "$CURRENT_STEP" "$status" >&2
  exit "$status"
}
trap _on_error ERR

# parse_common_args "$@" - handles --dry-run and --help (the script defines usage()).
parse_common_args() {
  while (($#)); do
    case "$1" in
      --dry-run) DRY_RUN=1 ;;
      -h | --help)
        usage
        exit 0
        ;;
      *)
        usage >&2
        die "unknown argument: $1"
        ;;
    esac
    shift
  done
  if ((DRY_RUN)); then
    log "DRY RUN: printing planned calls only; nothing is sent to Azure."
  fi
}

# require_env VAR... - stop before any change when a required input is missing.
require_env() {
  local name
  for name in "$@"; do
    if [[ -z "${!name:-}" ]]; then
      die "required environment variable $name is not set (see infra/bootstrap/README.md)"
    fi
  done
}

require_env_choice() {
  local name="$1"
  shift
  require_env "$name"
  local value="${!name}" choice
  for choice in "$@"; do
    [[ "$value" == "$choice" ]] && return 0
  done
  die "$name must be one of: $* (got '$value')"
}

require_tools() {
  ((DRY_RUN)) && return 0
  local tool
  for tool in "$@"; do
    command -v "$tool" >/dev/null 2>&1 || die "required tool '$tool' is not on PATH"
  done
}

# The 5 P-17 tag inputs, shared by every script that tags resources.
require_tag_inputs() {
  require_env TAG_OWNER TAG_COST_CENTRE TAG_APPLICATION TAG_DATA_CLASSIFICATION
}

# set_tags <environment> - fills the TAGS array with the az --tags values.
# (Plain arrays only: the scripts must run on macOS's bash 3.2.)
TAGS=()
set_tags() {
  TAGS=(
    "owner=$TAG_OWNER"
    "costCentre=$TAG_COST_CENTRE"
    "environment=$1"
    "application=$TAG_APPLICATION"
    "dataClassification=$TAG_DATA_CLASSIFICATION"
  )
}

# ---------------------------------------------------------------------------
# Command execution
# ---------------------------------------------------------------------------
_print_cmd() {
  local prefix="$1"
  shift
  local out="$prefix" arg escaped_quote="'\\''"
  for arg in "$@"; do
    if [[ "$arg" =~ ^[A-Za-z0-9_@%+=:,./-]+$ ]]; then
      out+=" $arg"
    else
      out+=" '${arg//\'/$escaped_quote}'"
    fi
  done
  printf '%s\n' "$out"
}

# run CMD... - a call that changes something. Printed only in dry-run.
run() {
  if ((DRY_RUN)); then
    _print_cmd "[dry-run]" "$@"
    return 0
  fi
  _print_cmd "+" "$@"
  "$@"
}

# query CMD... - a read-only lookup. In dry-run it is printed to stderr and
# fails (treated as "absent"), so the create path is shown.
query() {
  if ((DRY_RUN)); then
    _print_cmd "[dry-run] (lookup)" "$@" >&2
    return 1
  fi
  "$@"
}

# is_not_found TEXT - true when an az error means "the resource does not exist".
is_not_found() {
  grep -Eqi '[A-Za-z]*NotFound|could not be found|does not exist|was not found' <<<"$1"
}

# exists CMD... - true when the read-only lookup succeeds, false only when it fails
# with a NotFound-style error. Any other failure (403, throttling, network) stops
# the script: guessing "absent" could, for example, regenerate live keys.
exists() {
  if ((DRY_RUN)); then
    _print_cmd "[dry-run] (lookup)" "$@" >&2
    return 1
  fi
  local err
  if err="$("$@" 2>&1 >/dev/null)"; then
    return 0
  fi
  if is_not_found "$err"; then
    return 1
  fi
  die "lookup failed, and not with NotFound: $(_print_cmd "" "$@")
$err"
}

# value_or_placeholder PLACEHOLDER CMD... - prints the lookup's output, or the
# placeholder in dry-run.
value_or_placeholder() {
  local placeholder="$1"
  shift
  if ((DRY_RUN)); then
    _print_cmd "[dry-run] (lookup)" "$@" >&2
    printf '%s\n' "$placeholder"
    return 0
  fi
  "$@"
}

# scratch_dir - a private temp dir inside the gitignored .work/ folder.
scratch_dir() {
  mkdir -p "$REPO_ROOT/.work/bootstrap"
  local dir
  dir="$(mktemp -d "$REPO_ROOT/.work/bootstrap/tmp.XXXXXX")"
  chmod 700 "$dir"
  printf '%s\n' "$dir"
}

# ---------------------------------------------------------------------------
# Azure helpers
# ---------------------------------------------------------------------------
select_subscription() {
  require_env ARM_SUBSCRIPTION_ID
  require_tools az
  step "Select subscription"
  run az account set --subscription "$ARM_SUBSCRIPTION_ID"
}

subscription_scope() { echo "/subscriptions/$ARM_SUBSCRIPTION_ID"; }
rg_scope() { echo "$(subscription_scope)/resourceGroups/$1"; }
state_container_scope() {
  echo "$(rg_scope "$STATE_RG")/providers/Microsoft.Storage/storageAccounts/$STATE_ACCOUNT/blobServices/default/containers/$1"
}

verify_role_ids() {
  ((DRY_RUN)) && return 0
  step "Verify built-in role definition ids"
  local pair id expected actual
  for pair in \
    "$ROLE_CONTRIBUTOR|Contributor" \
    "$ROLE_RBAC_ADMIN|Role Based Access Control Administrator" \
    "$ROLE_BLOB_DATA_CONTRIBUTOR|Storage Blob Data Contributor" \
    "$ROLE_BLOB_DATA_OWNER|Storage Blob Data Owner" \
    "$ROLE_BLOB_DATA_READER|Storage Blob Data Reader" \
    "$ROLE_QUEUE_DATA_CONTRIBUTOR|Storage Queue Data Contributor" \
    "$ROLE_QUEUE_DATA_MESSAGE_SENDER|Storage Queue Data Message Sender" \
    "$ROLE_TABLE_DATA_CONTRIBUTOR|Storage Table Data Contributor" \
    "$ROLE_KV_SECRETS_USER|Key Vault Secrets User" \
    "$ROLE_KV_SECRETS_OFFICER|Key Vault Secrets Officer" \
    "$ROLE_MONITORING_METRICS_PUBLISHER|Monitoring Metrics Publisher" \
    "$ROLE_COGNITIVE_SERVICES_USER|Cognitive Services User"; do
    id="${pair%%|*}"
    expected="${pair#*|}"
    actual="$(az role definition list --name "$id" --query '[0].roleName' -o tsv)"
    [[ "$actual" == "$expected" ]] || die "role id $id is '$actual', expected '$expected'"
  done
}

# rbac_admin_condition ROLE_ID... - ABAC condition limiting RBAC Administrator to
# assigning or removing only the listed roles, and only for service principals.
rbac_admin_condition() {
  local list
  list="$(printf '%s, ' "$@")"
  list="${list%, }"
  printf '%s' \
    "((!(ActionMatches{'Microsoft.Authorization/roleAssignments/write'})) OR " \
    "(@Request[Microsoft.Authorization/roleAssignments:RoleDefinitionId] ForAnyOfAnyValues:GuidEquals {$list} " \
    "AND @Request[Microsoft.Authorization/roleAssignments:PrincipalType] ForAnyOfAnyValues:StringEqualsIgnoreCase {'ServicePrincipal'})) " \
    "AND ((!(ActionMatches{'Microsoft.Authorization/roleAssignments/delete'})) OR " \
    "(@Resource[Microsoft.Authorization/roleAssignments:RoleDefinitionId] ForAnyOfAnyValues:GuidEquals {$list} " \
    "AND @Resource[Microsoft.Authorization/roleAssignments:PrincipalType] ForAnyOfAnyValues:StringEqualsIgnoreCase {'ServicePrincipal'}))"
}

# ensure_role_assignment PRINCIPAL_ID PRINCIPAL_TYPE ROLE_ID SCOPE [CONDITION]
ensure_role_assignment() {
  local principal_id="$1" principal_type="$2" role_id="$3" scope="$4" condition="${5:-}"
  local count
  if ((DRY_RUN)); then
    count=0
    _print_cmd "[dry-run] (lookup)" az role assignment list --assignee-object-id "$principal_id" \
      --fill-principal-name false --role "$role_id" --scope "$scope" >&2
  else
    # --assignee-object-id skips the Graph lookup, which lags for new identities.
    count="$(az role assignment list --assignee-object-id "$principal_id" --fill-principal-name false \
      --role "$role_id" --scope "$scope" --query "length([?scope=='$scope'])" -o tsv)"
  fi
  if [[ "$count" != "0" ]]; then
    log "exists: role $role_id for $principal_id at $scope"
    if [[ -n "$condition" ]]; then
      log "  (condition not re-applied; delete the assignment and re-run to change it)"
    fi
    return 0
  fi
  local args=(az role assignment create
    --assignee-object-id "$principal_id"
    --assignee-principal-type "$principal_type"
    --role "$role_id"
    --scope "$scope")
  if [[ -n "$condition" ]]; then
    args+=(--condition "$condition" --condition-version "2.0")
  fi
  run "${args[@]}"
}

# remove_role_assignment PRINCIPAL_ID ROLE_ID SCOPE - deletes the assignment made at
# exactly SCOPE, if there is one (assignments inherited from a parent scope are untouched).
remove_role_assignment() {
  local principal_id="$1" role_id="$2" scope="$3"
  local ids
  if ((DRY_RUN)); then
    ids=""
    _print_cmd "[dry-run] (lookup)" az role assignment list --assignee-object-id "$principal_id" \
      --fill-principal-name false --role "$role_id" --scope "$scope" >&2
  else
    ids="$(az role assignment list --assignee-object-id "$principal_id" --fill-principal-name false \
      --role "$role_id" --scope "$scope" --query "[?scope=='$scope'].id" -o tsv)"
  fi
  if [[ -z "$ids" ]]; then
    log "absent: role $role_id for $principal_id at $scope"
    return 0
  fi
  local id
  for id in $ids; do
    run az role assignment delete --ids "$id"
  done
}

identity_principal_id() {
  local name="$1" rg="$2"
  value_or_placeholder "<principalId-of-$name>" \
    az identity show --name "$name" --resource-group "$rg" --query principalId -o tsv
}
