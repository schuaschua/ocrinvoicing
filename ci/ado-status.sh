#!/usr/bin/env bash
#
# Story 1.2: posts a branch build's result as a status on the branch's active pull
# request into main (genre "jenkins", name "checks"), on the pull request iteration of
# the built commit. The branch policy on main requires that status to merge. Called by
# the Jenkinsfile with the Azure DevOps token in ADO_PAT (Jenkins credential "ado-pat");
# the token goes to curl on its standard input only, never on a command line or in the
# log. A branch with no active pull request gets no status.

# shellcheck source-path=SCRIPTDIR source=lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

usage() {
  cat <<'USAGE'
Usage: ci/ado-status.sh <pending|succeeded|failed|error>

Environment: ADO_ORG, ADO_PROJECT, ADO_REPO (default ADO_PROJECT), ADO_PAT (the token),
BRANCH_NAME and GIT_COMMIT (set by Jenkins), BUILD_URL (optional, the status link).
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
state="$1"
case "$state" in
  pending | succeeded | failed | error) ;;
  *) die "state must be pending, succeeded, failed or error, got '$state'" ;;
esac
for name in ADO_ORG ADO_PROJECT ADO_PAT BRANCH_NAME GIT_COMMIT; do
  [[ -n "${!name:-}" ]] || die "$name is not set"
done

repo="${ADO_REPO:-$ADO_PROJECT}"
api="https://dev.azure.com/$ADO_ORG/$ADO_PROJECT/_apis/git/repositories/$repo"
source_ref="refs/heads/$BRANCH_NAME"

# ado METHOD URL [JSON] - one REST call; the token reaches curl through --config on stdin.
ado() {
  local args=(--fail-with-body --silent --show-error --retry 3 --config - -X "$1"
    -H "Accept: application/json")
  if (($# == 3)); then
    args+=(-H "Content-Type: application/json" --data "$3")
  fi
  printf 'user = ":%s"\n' "$ADO_PAT" | curl "${args[@]}" "$2"
}

query="$(python3 -c 'import sys, urllib.parse
print(urllib.parse.urlencode({
    "searchCriteria.sourceRefName": sys.argv[1],
    "searchCriteria.targetRefName": "refs/heads/main",
    "searchCriteria.status": "active",
    "api-version": "7.1",
}))' "$source_ref")"
pr_id="$(ado GET "$api/pullrequests?$query" |
  python3 -c 'import json, sys; prs = json.load(sys.stdin)["value"]; print(prs[0]["pullRequestId"] if prs else "")')"
if [[ -z "$pr_id" ]]; then
  log "no active pull request from $source_ref into main; no status posted"
  exit 0
fi

iteration="$(ado GET "$api/pullRequests/$pr_id/iterations?api-version=7.1" | python3 -c 'import json, sys
ids = [i["id"] for i in json.load(sys.stdin)["value"] if i.get("sourceRefCommit", {}).get("commitId") == sys.argv[1]]
print(ids[-1] if ids else "")' "$GIT_COMMIT")"
if [[ -z "$iteration" ]]; then
  # A newer push is being built already; its build posts the status that counts.
  log "pull request $pr_id has no iteration for $GIT_COMMIT; no status posted"
  exit 0
fi

body="$(python3 -c 'import json, sys
state, iteration, url = sys.argv[1], int(sys.argv[2]), sys.argv[3]
status = {
    "state": state,
    "description": f"Jenkins ci/checks.sh: {state}",
    "context": {"genre": "jenkins", "name": "checks"},
    "iterationId": iteration,
}
if url:
    status["targetUrl"] = url
print(json.dumps(status))' "$state" "$iteration" "${BUILD_URL:-}")"
ado POST "$api/pullRequests/$pr_id/statuses?api-version=7.1" "$body" >/dev/null
log "posted '$state' (jenkins/checks) on pull request $pr_id, iteration $iteration"
