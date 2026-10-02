#!/usr/bin/env bash
#
# Deploy pipeline, last step for a stack owner (the Jenkinsfiles' "Tag sweep" stages).
# Azure creates some resources in an environment's resource group by itself, outside
# Terraform: Application Insights adds the "Application Insights Smart Detection"
# action group and the "Failure Anomalies - <appi>" alert rule, without the P-17 tags.
# This copies the tag keys of the owner's resource group (read from its foundation
# stack's output resource_group_name) onto every resource in it that lacks them, with
# `az tag update --operation merge` and only the missing keys. It never overwrites an
# existing value and never removes a tag; a fully tagged group gets no update call.
# Only the group of infra/<owner>/foundation is ever swept (never rg-tfstate-sea or the
# bootstrap-only rg-22 and rg-23, which the bootstrap scripts tag).

# shellcheck source-path=SCRIPTDIR source=lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

usage() {
  cat <<'USAGE'
Usage: ci/tag-sweep.sh <shared|dev|prod>

Run with `az` signed in as that owner's deploy identity and CI_MSI_CLIENT_ID set to its
client id (the Jenkinsfiles do both; ci/lib.sh export_arm_context), after the owner's
stacks are applied.
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
owner="$1"
[[ "$owner" =~ ^(shared|dev|prod)$ ]] || die "owner must be shared, dev or prod, got '$owner'"
dir="$(stack_dir "$owner/foundation")"
[[ -d "$dir" ]] || die "infra/$owner/foundation does not exist"

export_arm_context
export TF_IN_AUTOMATION=1 TF_INPUT=0

terraform -chdir="$dir" init -input=false -lockfile=readonly >/dev/null
rg="$(terraform -chdir="$dir" output -raw resource_group_name)"
# The output must be the owner's own group, named by the bootstrap naming helpers.
# shellcheck disable=SC2016  # expanded by the inner bash
expected="$(bash -c 'source "$1/infra/bootstrap/lib.sh" && rg_name "$2"' bash "$REPO_ROOT" "$owner")"
[[ "$rg" == "$expected" ]] || die "infra/$owner/foundation names resource group '$rg', expected '$expected'; nothing swept"

group_tags="$(az group show --name "$rg" --query tags -o json)"
resources="$(az resource list --resource-group "$rg" --query "[].{id:id, tags:tags}" -o json)"

# One line per resource that lacks a group tag key: its id, then each missing
# key=value, tab-separated. Existing keys (whatever their value) are left alone.
# shellcheck disable=SC2016  # Python, not shell
missing="$(python3 -c '
import json, sys
group = json.loads(sys.argv[1]) or {}
for resource in json.loads(sys.argv[2]) or []:
    # Azure tag keys are case-insensitive (and so is the merge): compare them lowercased.
    present = {key.lower() for key in (resource.get("tags") or {})}
    add = [f"{key}={value}" for key, value in sorted(group.items()) if key.lower() not in present]
    if add:
        print("\t".join([resource["id"], *add]))
' "$group_tags" "$resources")"

count=0
while IFS=$'\t' read -r -a fields; do
  ((${#fields[@]})) || continue
  log "tagging ${fields[0]}: ${fields[*]:1}"
  az tag update --resource-id "${fields[0]}" --operation merge --tags "${fields[@]:1}" --output none
  count=$((count + 1))
done <<<"$missing"
log "tag sweep of $rg done; $count resource(s) given missing tags"
