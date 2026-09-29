#!/usr/bin/env bash
#
# AD-17 step 5 check (AD-11): each environment's logins can connect only to their
# own database, and PUBLIC cannot connect to either. Prints PASS/FAIL per check and
# exits 1 on any FAIL.
#
# Mode 1 (default), run as the PostgreSQL Entra admin: checks the CONNECT
#   privileges of every environment login with has_database_privilege.
# Mode 2 (CONNECT_AS_LOGIN set): signs in as the current az identity (for example the
#   dev deploy identity inside the Jenkins container on the CI VM) and tries to open TARGET_DB;
#   PASS means the connection was refused.
#
# The load script's login is the environment's loaders group (Dj is a member; Dj,
# 2026-09-29: guest UPN over 63 characters), one per environment, so it is checked
# like the other logins.

# shellcheck source-path=SCRIPTDIR source=lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

usage() {
  cat <<'EOF'
Usage: verify-db-isolation.sh [--dry-run]

Mode 1 (default; run as the PostgreSQL Entra admin):
  PG_ADMIN_USER         Entra admin name used to connect
Mode 2 (a real connection attempt that must be refused):
  CONNECT_AS_LOGIN      login name of the signed-in az identity, e.g. babaloo-sea-lng-id-22
  TARGET_DB             database it must NOT reach, e.g. invoicing_prod
EOF
}

parse_common_args "$@"
require_tools az psql

failures=0
pass() { log "PASS $*"; }
fail() {
  log "FAIL $*"
  failures=$((failures + 1))
}

get_token() {
  if ((DRY_RUN)); then
    _print_cmd "[dry-run] (lookup)" az account get-access-token --resource-type oss-rdbms --query accessToken -o tsv >&2
  else
    PGPASSWORD="$(az account get-access-token --resource-type oss-rdbms --query accessToken -o tsv)"
    export PGPASSWORD
  fi
}

if [[ -n "${CONNECT_AS_LOGIN:-}" ]]; then
  require_env TARGET_DB
  step "Connection attempt: $CONNECT_AS_LOGIN -> $TARGET_DB (must be refused)"
  get_token
  conninfo="host=$(postgres_fqdn) port=5432 dbname=$TARGET_DB user=$CONNECT_AS_LOGIN sslmode=require connect_timeout=15"
  if ((DRY_RUN)); then
    run psql "$conninfo" --no-psqlrc -At -c "select 1"
    exit 0
  fi
  if output="$(psql "$conninfo" --no-psqlrc -At -c "select 1" 2>&1)"; then
    fail "$CONNECT_AS_LOGIN connected to $TARGET_DB"
  elif grep -qi "permission denied\|not permitted\|does not have CONNECT" <<<"$output"; then
    pass "$CONNECT_AS_LOGIN refused by $TARGET_DB"
  else
    fail "$CONNECT_AS_LOGIN could not connect to $TARGET_DB for another reason: $output"
  fi
  ((failures == 0)) || exit 1
  exit 0
fi

require_env PG_ADMIN_USER
get_token
admin_conninfo="host=$(postgres_fqdn) port=5432 dbname=postgres user=$PG_ADMIN_USER sslmode=require"

# pg_bool SQL - runs one boolean query as the admin; prints t or f.
pg_bool() {
  psql "$admin_conninfo" --no-psqlrc -At -v ON_ERROR_STOP=1 "$@"
}

role_exists() {
  pg_bool -v "login=$1" -f - <<'SQL'
SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'login');
SQL
}

can_connect() {
  pg_bool -v "login=$1" -v "db=$2" -f - <<'SQL'
SELECT has_database_privilege(:'login', :'db', 'CONNECT');
SQL
}

database_exists() {
  pg_bool -v "db=$1" -f - <<'SQL'
SELECT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'db');
SQL
}

public_can_connect() {
  pg_bool -v "db=$1" -f - <<'SQL'
SELECT EXISTS (
  SELECT 1
  FROM pg_database d, aclexplode(COALESCE(d.datacl, acldefault('d', d.datdba))) a
  WHERE d.datname = :'db' AND a.grantee = 0 AND a.privilege_type = 'CONNECT'
);
SQL
}

if ((DRY_RUN)); then
  step "Checks that would run"
  run psql "$admin_conninfo" --no-psqlrc -At -v ON_ERROR_STOP=1 -f "<has_database_privilege checks>"
  for env in dev prod; do
    for app in pipeline staff-api accounts-sim; do
      log "  $(app_identity_name "$env" "$app"): CONNECT invoicing_$env = yes, other = no"
    done
    log "  $(deploy_identity_name "$env"): CONNECT invoicing_$env = yes, other = no"
    log "  $(loaders_group_name "$env"): CONNECT invoicing_$env = yes, other = no"
  done
  exit 0
fi

for db in invoicing_dev invoicing_prod; do
  step "PUBLIC on $db"
  if [[ "$(database_exists "$db")" != "t" ]]; then
    fail "$db does not exist"
  elif [[ "$(public_can_connect "$db")" == "f" ]]; then
    pass "PUBLIC has no CONNECT on $db"
  else
    fail "PUBLIC can CONNECT to $db"
  fi
done

for env in dev prod; do
  if [[ "$env" == "dev" ]]; then other="prod"; else other="dev"; fi
  step "Logins of $env"
  for login in \
    "$(app_identity_name "$env" pipeline)" \
    "$(app_identity_name "$env" staff-api)" \
    "$(app_identity_name "$env" accounts-sim)" \
    "$(deploy_identity_name "$env")" \
    "$(loaders_group_name "$env")"; do
    if [[ "$(role_exists "$login")" != "t" ]]; then
      fail "$login does not exist (run database-step5.sh for $env)"
      continue
    fi
    if [[ "$(can_connect "$login" "invoicing_$env")" == "t" ]]; then
      pass "$login can CONNECT to invoicing_$env"
    else
      fail "$login cannot CONNECT to invoicing_$env"
    fi
    if [[ "$(can_connect "$login" "invoicing_$other")" == "f" ]]; then
      pass "$login refused on invoicing_$other"
    else
      fail "$login can CONNECT to invoicing_$other"
    fi
  done
done

step "Result"
if ((failures)); then
  log "$failures check(s) failed."
  exit 1
fi
log "All isolation checks passed."
