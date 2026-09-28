#!/usr/bin/env bash
#
# AD-17 step 9: code deploy for one environment (pipelines/templates/code-deploy.yml),
# run as the environment's deploy identity after <env>/app.
#
# Builds one flat package per Function app (Story 1.3 Design Notes):
#   function_app.py, host.json      from backend/src/invoicing/apps/<app>/
#   invoicing/                      the back-end package
#   requirements.txt                `uv export --no-dev` of backend/uv.lock (hashes kept)
#   static/                         the built SPA, for supplier-api and staff-api once
#                                   web/supplier or web/staff is scaffolded (AD-14)
# then publishes each zip with one deploy; Flex stores it in the app's deployment
# container and runs the remote build (pip install).

# shellcheck source-path=SCRIPTDIR source=lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

usage() {
  cat <<'USAGE'
Usage: ci/code-deploy.sh [--check | --build-only] <dev|prod>

  --check       only report whether there is anything to deploy (sets hasWork)
  --build-only  build the four packages under .work/ci/code-deploy/<env>/, publish nothing
Without a flag, run inside an AzureCLI@2 task signed in with the environment's
service connection (azure-dev or azure-prod).
USAGE
}

[[ "${1:-}" == "-h" || "${1:-}" == "--help" ]] && {
  usage
  exit 0
}
mode=deploy
case "${1:-}" in
  --check)
    mode=check
    shift
    ;;
  --build-only)
    mode=build
    shift
    ;;
esac
(($# == 1)) || {
  usage >&2
  exit 2
}
env="$1"
[[ "$env" == dev || "$env" == prod ]] || die "environment must be dev or prod, got '$env'"

# Test seams only (ci/tests point them at scratch folders under .work/).
infra_dir="${CI_INFRA_DIR:-$REPO_ROOT/infra}"
web_dir="${CI_WEB_DIR:-$REPO_ROOT/web}"
build_dir="${CI_DEPLOY_BUILD_DIR:-$CI_WORK/code-deploy/$env}"
backend_dir="${CI_BACKEND_DIR:-$REPO_ROOT/backend}"
# Post-deploy health check: attempts and seconds between them (tests set the wait to 0).
health_attempts="${CI_HEALTH_ATTEMPTS:-30}"
health_wait="${CI_HEALTH_WAIT:-10}"

if [[ ! -d "$infra_dir/$env/app" ]]; then
  log "skipped: nothing to deploy (infra/$env/app does not exist yet)"
  [[ "$mode" == check ]] && set_output hasWork false
  exit 0
fi
if [[ "$mode" == check ]]; then
  set_output hasWork true
  exit 0
fi

# The four apps (AD-1), and the SPA each API serves (AD-14).
readonly APPS=(supplier-api staff-api pipeline accounts-sim)
spa_for() {
  case "$1" in
    supplier-api) echo supplier ;;
    staff-api) echo staff ;;
    *) echo "" ;;
  esac
}

# A web app is scaffolded (Story 1.4) once its package.json defines scripts. A
# package.json that doesn't parse stops the deploy instead of shipping without the SPA.
web_scaffolded() {
  local file="$1/package.json" status=0
  [[ -f "$file" ]] || return 1
  python3 -c '
import json, sys
try:
    data = json.load(open(sys.argv[1], encoding="utf-8"))
except ValueError:
    sys.exit(2)
sys.exit(0 if isinstance(data, dict) and data.get("scripts") else 1)' "$file" || status=$?
  ((status != 2)) || die "${file#"$REPO_ROOT"/} is not valid JSON"
  return "$status"
}

# build_spa APP_DIR - build the SPA and print the folder holding index.html.
build_spa() {
  local app_dir="$1"
  npm ci --prefix "$app_dir" --no-audit --no-fund >&2
  rm -rf "$app_dir/dist" # never package a stale build
  npm run --prefix "$app_dir" build >&2
  [[ -f "$app_dir/dist/index.html" ]] || die "$(basename "$app_dir"): npm run build produced no dist/index.html"
  printf '%s' "$app_dir/dist"
}

# build_package APP - lay out one app's package and zip it to <build dir>/APP.zip.
build_package() {
  local app="$1" module="${1//-/_}" package spa spa_dist
  package="$build_dir/$app"
  rm -rf "$package" "$package.zip"
  mkdir -p "$package"
  # Only git-tracked files: no local scratch, caches or untracked modules ship.
  local file
  while IFS= read -r -d '' file; do
    mkdir -p "$package/$(dirname "${file#src/}")"
    cp "$backend_dir/$file" "$package/${file#src/}"
  done < <(git -C "$backend_dir" ls-files -z -- src/invoicing)
  [[ -f "$package/invoicing/apps/$module/function_app.py" ]] ||
    die "backend/src/invoicing/apps/$module/function_app.py is not tracked by git"
  cp "$package/invoicing/apps/$module/function_app.py" "$package/invoicing/apps/$module/host.json" "$package/"
  cp "$build_dir/requirements.txt" "$package/requirements.txt"

  spa="$(spa_for "$app")"
  if [[ -n "$spa" ]] && web_scaffolded "$web_dir/$spa"; then
    spa_dist="$(build_spa "$web_dir/$spa")"
    cp -R "$spa_dist" "$package/static"
    log "$app: packaged web/$spa"
  elif [[ -n "$spa" ]]; then
    log "$app: web/$spa is not scaffolded yet; no SPA packaged"
  fi

  # Flat zip: function_app.py and host.json at the root (python3 is on every agent).
  (cd "$package" && python3 -m zipfile -c "../$app.zip" ./*)
}

mkdir -p "$build_dir"
rm -f "$build_dir/requirements.txt"
# Runtime dependencies only, with hashes; the remote build installs them.
uv export --directory "$backend_dir" --locked --no-dev --no-emit-project --format requirements-txt \
  --no-header --quiet -o "$build_dir/requirements.txt"
[[ -s "$build_dir/requirements.txt" ]] || die "uv export wrote no requirements.txt"

for app in "${APPS[@]}"; do
  build_package "$app"
  log "built ${build_dir#"$REPO_ROOT"/}/$app.zip"
done

if [[ "$mode" == build ]]; then
  log "build only: nothing published"
  exit 0
fi

# naming NAME ARGS... - a name from the bootstrap naming helpers, which mirror
# infra/modules/naming (run in their own shell: they bring their own traps).
naming() {
  # shellcheck disable=SC2016  # expanded by the inner bash
  bash -c 'source "$1/infra/bootstrap/lib.sh" && "$2" "${@:3}"' bash "$REPO_ROOT" "$@"
}

resource_group="$(naming rg_name "$env")"
published=()
for app in "${APPS[@]}"; do
  function_app="$(naming function_app_name "$env" "$app")"
  log "publishing $app to $function_app in $resource_group"
  az functionapp deployment source config-zip --resource-group "$resource_group" \
    --name "$function_app" --src "$build_dir/$app.zip" --build-remote true ||
    die "publishing $app failed; already published: ${published[*]:-none}"
  published+=("$app")
  log "published $app ($function_app)"
done

# health_ok APP HOST VERSION - GET /api/health until it returns 200 with VERSION.
health_ok() {
  local app="$1" url="https://$2/api/health" version="$3" body code attempt
  body="$build_dir/$app.health.json"
  for ((attempt = 1; attempt <= health_attempts; attempt++)); do
    code="$(curl -sS --max-time 10 -o "$body" -w '%{http_code}' "$url" || true)"
    if [[ "$code" == 200 ]] && python3 -c '
import json, sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
sys.exit(0 if data.get("status") == "ok" and data.get("version") == sys.argv[2] else 1)' "$body" "$version" 2>/dev/null; then
      log "$app is healthy at $url (version $version)"
      return 0
    fi
    log "$app not healthy yet (attempt $attempt/$health_attempts, HTTP ${code:-none})"
    ((attempt == health_attempts)) || sleep "$health_wait"
  done
  return 1
}

# The HTTP apps must answer with the version just packaged (pipeline and accounts-sim
# have no routes).
for app in supplier-api staff-api; do
  version="$(python3 -c '
import re, sys
print(re.search(r"^__version__ = \"([^\"]+)\"", open(sys.argv[1], encoding="utf-8").read(), re.M).group(1))' \
    "$build_dir/$app/invoicing/__init__.py")"
  function_app="$(naming function_app_name "$env" "$app")"
  host="$(az functionapp show --resource-group "$resource_group" --name "$function_app" --query defaultHostName -o tsv)"
  health_ok "$app" "$host" "$version" ||
    die "$app did not report healthy version $version; published: ${published[*]}"
done
log "code deploy to $env done; published: ${published[*]}"
