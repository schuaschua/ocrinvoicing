#!/usr/bin/env bash
#
# The commit the dev chain last deployed, which is the only commit the Prod job may
# deploy (Dj, 2026-10-02). One file, <state-dir>/dev-commit, in jenkins_home: the
# controller is the only node, so both jobs see it.
#   record  the dev chain (Jenkinsfile): writes HEAD, atomically, once Dev is deployed
#   verify  the Prod job (ci/jenkins/Jenkinsfile.prod): prints HEAD if it is the
#           recorded commit; otherwise fails, naming both commits

# shellcheck source-path=SCRIPTDIR source=lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

usage() {
  cat <<'USAGE'
Usage: ci/deploy-state.sh <record|verify>

The state folder is $JENKINS_HOME/deploy-state.
USAGE
}

[[ "${1:-}" == "-h" || "${1:-}" == "--help" ]] && {
  usage
  exit 0
}
(($# == 1)) || {
  usage >&2
  exit 2
}
# CI_DEPLOY_COMMIT_DIR is a test seam only (ci/tests point it at a scratch folder).
if [[ -n "${CI_DEPLOY_COMMIT_DIR:-}" ]]; then
  state_dir="$CI_DEPLOY_COMMIT_DIR"
else
  [[ -n "${JENKINS_HOME:-}" ]] || die "JENKINS_HOME is not set: the deploy state lives in jenkins_home"
  state_dir="$JENKINS_HOME/deploy-state"
fi
marker="$state_dir/dev-commit"
head="$(git -C "$REPO_ROOT" rev-parse HEAD)"

case "$1" in
  record)
    mkdir -p "$state_dir"
    printf '%s\n' "$head" >"$marker.new"
    mv "$marker.new" "$marker"
    log "recorded $head as the commit deployed to Dev" >&2
    ;;
  verify)
    recorded=""
    [[ -f "$marker" ]] && recorded="$(tr -d '[:space:]' <"$marker")"
    [[ "$head" == "$recorded" ]] ||
      die "main is at $head, but the last commit the dev chain deployed is '${recorded:-none recorded}': let the dev chain deploy main first, then start this job again"
    printf '%s\n' "$head"
    ;;
  *) die "unknown command '$1' (record or verify)" ;;
esac
