#!/usr/bin/env bash
#
# AD-17 step 6: Alembic `upgrade head` for one environment, run by the deploy
# pipeline (pipelines/templates/migrate.yml) after <env>/foundation and before
# <env>/app, never at app start. It signs in to PostgreSQL as the environment's
# deploy identity with an Entra token (no password) and connects directly over TLS:
# the server firewall is open for the PoC, so no temporary firewall rule is added
# (terraform.md rule 36 exception).
#
# Contract for backend/migrations/env.py (Story 1.3): take the connection from the
# libpq variables PGHOST, PGPORT, PGUSER, PGPASSWORD, PGDATABASE and PGSSLMODE.

# shellcheck source-path=SCRIPTDIR source=lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

usage() {
  cat <<'USAGE'
Usage: ci/migrate.sh [--check] <dev|prod>

  --check   only report whether there are migrations (sets hasWork); no Azure call
Without --check, run inside an AzureCLI@2 task signed in with the environment's
service connection (azure-dev or azure-prod).
USAGE
}

[[ "${1:-}" == "-h" || "${1:-}" == "--help" ]] && {
  usage
  exit 0
}
check_only=0
if [[ "${1:-}" == "--check" ]]; then
  check_only=1
  shift
fi
(($# == 1)) || {
  usage >&2
  exit 2
}
env="$1"
[[ "$env" == dev || "$env" == prod ]] || die "environment must be dev or prod, got '$env'"

# CI_MIGRATIONS_DIR is a test seam only (ci/tests point it at a scratch folder).
migrations_dir="${CI_MIGRATIONS_DIR:-$REPO_ROOT/backend/migrations}"
if [[ ! -f "$migrations_dir/env.py" ]]; then
  log "no migrations (backend/migrations/env.py does not exist yet)"
  ((check_only)) && set_output hasWork false
  exit 0
fi
if ((check_only)); then
  log "migrations found in backend/migrations"
  set_output hasWork true
  exit 0
fi

# Names come from the bootstrap naming helpers, so they cannot drift from the logins
# that database-step5.sh created.
# shellcheck disable=SC2016  # expanded by the inner bash
names="$(bash -c 'source "$1/infra/bootstrap/lib.sh" && printf "%s %s %s" \
  "$(postgres_fqdn)" "$(deploy_identity_name "$2")" "$(env_database_name "$2")"' bash "$REPO_ROOT" "$env")"
read -r pg_host pg_user pg_database <<<"$names"

token="$(az account get-access-token --resource-type oss-rdbms --query accessToken -o tsv)"
[[ -n "$token" ]] || die "no Entra token for PostgreSQL"
if [[ -n "${TF_BUILD:-}" ]]; then
  echo "##vso[task.setsecret]$token"
fi

export PGHOST="$pg_host" PGPORT=5432 PGUSER="$pg_user" PGDATABASE="$pg_database" PGSSLMODE=require
export PGPASSWORD="$token"
log "alembic upgrade head on $PGDATABASE as $PGUSER"
uv run --directory "$REPO_ROOT/backend" --locked --no-dev alembic upgrade head
