#!/usr/bin/env bash
#
# Deploy pipeline, plan half of one stack (pipelines/templates/terraform-stack.yml).
# Runs `terraform plan -out=tfplan -detailed-exitcode`, then the P-17 tag gate on
# `terraform show -json` of that plan. When the plan has changes it copies the saved
# plan to PLAN_OUT for the apply stage and sets hasWork=true; otherwise the apply
# stage (and its approval) is skipped.

# shellcheck source-path=SCRIPTDIR source=lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

usage() {
  cat <<'USAGE'
Usage: ci/terraform-plan.sh <env>/<stack> <plan-out-dir> [--optional]

  --optional   a missing stack folder (e.g. infra/dev/app before Story 1.3) is
               skipped instead of failing
Run inside an AzureCLI@2 task signed in with the stack owner's service connection.
USAGE
}

[[ "${1:-}" == "-h" || "${1:-}" == "--help" ]] && {
  usage
  exit 0
}
(($# == 2 || $# == 3)) || {
  usage >&2
  exit 2
}
stack="$1"
plan_out="$2"
optional=0
if (($# == 3)); then
  [[ "$3" == "--optional" ]] || die "unknown argument: $3"
  optional=1
fi
dir="$(stack_dir "$stack")"

if [[ ! -d "$dir" ]]; then
  if ((optional)); then
    log "skipped: infra/$stack does not exist yet"
    set_output hasWork false
    exit 0
  fi
  die "infra/$stack does not exist"
fi

export_arm_context
export TF_IN_AUTOMATION=1 TF_INPUT=0

terraform -chdir="$dir" init -input=false -lockfile=readonly
status=0
terraform -chdir="$dir" plan -input=false -lock-timeout=5m -out=tfplan -detailed-exitcode || status=$?
case "$status" in
  0) changes=false ;;
  2) changes=true ;;
  *) die "terraform plan failed for infra/$stack (exit $status)" ;;
esac

# Plan JSON holds sensitive values: keep it under the gitignored .work/ folder and
# delete it after the gate (infra/bootstrap/README.md, "Tag gate").
mkdir -p "$CI_WORK"
plan_json="$CI_WORK/${stack//\//-}.plan.json"
trap 'rm -f "$plan_json"' EXIT
terraform -chdir="$dir" show -json tfplan >"$plan_json"
python3 "$REPO_ROOT/infra/scripts/check_tags.py" "$plan_json" || die "tag gate failed for infra/$stack; nothing is applied"

if [[ "$changes" == true ]]; then
  mkdir -p "$plan_out"
  cp "$dir/tfplan" "$plan_out/tfplan"
  log "infra/$stack has changes; the saved plan goes to the apply stage"
else
  log "infra/$stack has no changes; apply skipped"
fi
set_output hasWork "$changes"
