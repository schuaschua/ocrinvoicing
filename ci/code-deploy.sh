#!/usr/bin/env bash
#
# AD-17 step 9: code deploy for one environment (pipelines/templates/code-deploy.yml).
# Nothing to deploy until Story 1.3 adds infra/<env>/app and the Function apps;
# `--check` then reports hasWork=true and Story 1.3 must implement the deploy below
# (build each app's package, SPA included, and publish it to its Flex app's
# deployment container).

# shellcheck source-path=SCRIPTDIR source=lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

usage() {
  cat <<'USAGE'
Usage: ci/code-deploy.sh [--check] <dev|prod>

  --check   only report whether there is anything to deploy (sets hasWork)
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

if [[ ! -d "$REPO_ROOT/infra/$env/app" ]]; then
  log "skipped: nothing to deploy (infra/$env/app does not exist yet)"
  ((check_only)) && set_output hasWork false
  exit 0
fi
if ((check_only)); then
  set_output hasWork true
  exit 0
fi

# Fails loudly rather than reporting a deploy that did not happen.
die "infra/$env/app exists but the code deploy is not implemented yet (Story 1.3)"
