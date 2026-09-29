#!/usr/bin/env bash
#
# Deploy pipeline, apply half of one stack (the Jenkinsfile's "Apply <stack>" stage).
# Applies only the saved plan from the same run's plan stage (terraform.md rule 26);
# Terraform refuses it if the state changed since the plan.

# shellcheck source-path=SCRIPTDIR source=lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

usage() {
  cat <<'USAGE'
Usage: ci/terraform-apply.sh <env>/<stack> <saved-plan-file>

Run with `az` signed in as the stack owner's deploy identity and CI_MSI_CLIENT_ID set
to its client id (the Jenkinsfile does both; ci/lib.sh export_arm_context).
USAGE
}

[[ "${1:-}" == "-h" || "${1:-}" == "--help" ]] && {
  usage
  exit 0
}
(($# == 2)) || {
  usage >&2
  exit 2
}
stack="$1"
plan_file="$2"
dir="$(stack_dir "$stack")"
[[ -d "$dir" ]] || die "infra/$stack does not exist"
[[ -f "$plan_file" ]] || die "saved plan $plan_file not found; a stack is applied only from its saved plan"

export_arm_context
export TF_IN_AUTOMATION=1 TF_INPUT=0

terraform -chdir="$dir" init -input=false -lockfile=readonly
cp "$plan_file" "$dir/tfplan"
terraform -chdir="$dir" apply -input=false -lock-timeout=5m tfplan
