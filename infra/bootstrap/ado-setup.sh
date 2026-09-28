#!/usr/bin/env bash
#
# Story 1.2 operator step (after state-backend.sh): the Azure DevOps side of the
# pipeline (spine AD-17). Creates, in the ADO project:
#   - workload-identity-federation service connections azure-shared, azure-dev and
#     azure-prod, each bound to its deploy identity (id-21/22/23) whose federated
#     credential state-backend.sh created;
#   - environments shared, dev and prod, each with an exclusive lock, and an approval
#     check (ADO_APPROVER) on shared and prod: approvals live on environments, not in
#     YAML, so this script is what gates shared and Prod;
#   - a branch control check (refs/heads/main only) on every connection and environment;
#   - the pipelines pipelines/pr.yml, deploy.yml and weekly-scan.yml, with the deploy
#     pipeline authorised to use the connections and environments;
#   - a branch policy on main: the PR build (gitleaks included) must pass to merge.
# Idempotent: a re-run skips what exists and re-applies the check and policy settings.

# shellcheck source-path=SCRIPTDIR source=lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

usage() {
  cat <<'EOF'
Usage: ado-setup.sh [--dry-run]

Required environment variables:
  ARM_SUBSCRIPTION_ID   target subscription (the service connections' scope)
  ARM_TENANT_ID         Entra tenant of the deploy identities
  ADO_ORG               Azure DevOps organisation name
  ADO_PROJECT           Azure DevOps project name
  ADO_APPROVER          approver of the shared and prod environments (Dj's ADO sign-in)
Optional:
  ADO_REPO              Azure Repos repository (default: ADO_PROJECT)
  ADO_SC_SHARED, ADO_SC_DEV, ADO_SC_PROD
                        service connection names (default azure-shared, azure-dev,
                        azure-prod; must match state-backend.sh and pipelines/deploy.yml)
Needs the azure-devops extension (az extension add --name azure-devops) and an az
login with Project Administrator rights in the ADO project.
EOF
}

parse_common_args "$@"
require_env ARM_SUBSCRIPTION_ID ARM_TENANT_ID ADO_ORG ADO_PROJECT ADO_APPROVER
ADO_REPO="${ADO_REPO:-$ADO_PROJECT}"
ADO_SC_SHARED="${ADO_SC_SHARED:-azure-shared}"
ADO_SC_DEV="${ADO_SC_DEV:-azure-dev}"
ADO_SC_PROD="${ADO_SC_PROD:-azure-prod}"
ORG_URL="https://dev.azure.com/$ADO_ORG"
readonly INTEGRATION_BRANCH="main"
readonly API_VERSION="7.1-preview.1"
# Built-in check types (Azure DevOps "Approvals and checks").
readonly CHECK_APPROVAL_ID="8c6f20a7-a545-4486-9777-f762fafe0d4d"
readonly CHECK_EXCLUSIVE_LOCK_ID="2ef31ad6-baa0-403a-8b45-2cbc9b4e5563"
# Branch control is a "Task Check" running the evaluatebranchProtection task.
readonly CHECK_TASK_ID="fe1de3ee-a436-41b4-bb20-f6eb4cb879a7"
readonly BRANCH_CONTROL_TASK_ID="86b05a0c-73e6-4f7d-b3cf-e38f3b39a75b"
readonly CHECK_TIMEOUT_MINUTES=1440

service_connection_name() {
  case "$1" in
    shared) echo "$ADO_SC_SHARED" ;;
    dev) echo "$ADO_SC_DEV" ;;
    prod) echo "$ADO_SC_PROD" ;;
  esac
}

# Pipeline name|YAML path, in creation order.
readonly PIPELINES=(
  "ocrinvoicing-pr|pipelines/pr.yml"
  "ocrinvoicing-deploy|pipelines/deploy.yml"
  "ocrinvoicing-weekly-scan|pipelines/weekly-scan.yml"
)

require_tools az python3
select_subscription
if ((!DRY_RUN)); then
  az extension show --name azure-devops --output none 2>/dev/null ||
    die "the azure-devops az extension is missing: az extension add --name azure-devops"
fi

DEVOPS=(--organization "$ORG_URL")
PROJECT=(--organization "$ORG_URL" --project "$ADO_PROJECT")

work_dir=""
cleanup() {
  if [[ -n "$work_dir" ]]; then rm -rf "$work_dir"; fi
}
trap cleanup EXIT
if ((DRY_RUN)); then
  out_dir="<scratch>"
else
  work_dir="$(scratch_dir)"
  out_dir="$work_dir"
fi

# write_body NAME JSON - request bodies go to a private scratch file (printed in dry-run).
write_body() {
  if ((DRY_RUN)); then
    log "$2"
  else
    printf '%s\n' "$2" >"$out_dir/$1"
  fi
}

# set_invoke METHOD AREA RESOURCE ROUTE [az args...] - fills INVOKE with an ADO REST
# call; ROUTE is space-separated key=value route parameters.
INVOKE=()
set_invoke() {
  local method="$1" area="$2" resource="$3" route="$4"
  shift 4
  local route_args
  read -r -a route_args <<<"$route"
  INVOKE=(az devops invoke "${DEVOPS[@]}" --area "$area" --resource "$resource"
    --route-parameters "${route_args[@]}" --http-method "$method" --api-version "$API_VERSION" "$@")
}

# lookup_id PLACEHOLDER CMD... - an id from a read-only lookup ("" when absent).
lookup_id() {
  local placeholder="$1" value
  shift
  value="$(value_or_placeholder "$placeholder" "$@")"
  [[ "$value" == "None" || "$value" == "null" ]] && value=""
  printf '%s' "$value"
}

# require_id NAME ID - after a create, the re-lookup must find it.
require_id() {
  [[ -n "$2" ]] || die "$1 was not found after it was created"
}

# ---------------------------------------------------------------------------
step "Look up the ADO project, subscription and approver"
project_id="$(lookup_id "<projectId-of-$ADO_PROJECT>" \
  az devops project show "${DEVOPS[@]}" --project "$ADO_PROJECT" --query id -o tsv)"
[[ -n "$project_id" ]] || die "ADO project $ADO_PROJECT not found in $ORG_URL"
subscription_name="$(lookup_id "<subscriptionName>" az account show --query name -o tsv)"
approver_id="$(lookup_id "<identityId-of-$ADO_APPROVER>" \
  az devops user show "${DEVOPS[@]}" --user "$ADO_APPROVER" --query id -o tsv)"
[[ -n "$approver_id" ]] || die "ADO_APPROVER $ADO_APPROVER is not a user in $ORG_URL"
repo_id="$(lookup_id "<repositoryId-of-$ADO_REPO>" \
  az repos show "${PROJECT[@]}" --repository "$ADO_REPO" --query id -o tsv)"
[[ -n "$repo_id" ]] || die "repository $ADO_REPO not found in project $ADO_PROJECT"

# ---------------------------------------------------------------------------
# ensure_check KIND RESOURCE_TYPE RESOURCE_ID RESOURCE_NAME - create the check on an
# environment or service connection, or re-apply its settings when it exists.
#   Approval       ADO_APPROVER must approve (shared and prod environments)
#   ExclusiveLock  one run at a time (every environment)
#   BranchControl  only runs of refs/heads/main may use it (every connection and
#                  environment), so a manual run of another branch cannot sign in
#                  as azure-shared/azure-prod, not even in a plan stage
ensure_check() {
  local kind="$1" resource_type="$2" resource_id="$3" resource_name="$4"
  local type_id type_name settings filter check_id body="check-$resource_type-$resource_name-$1.json"
  case "$kind" in
    Approval)
      type_id="$CHECK_APPROVAL_ID" type_name="Approval"
      settings="{ \"approvers\": [ { \"id\": \"$approver_id\" } ], \"executionOrder\": \"anyOrder\", \"minRequiredApprovers\": 0, \"requesterCannotBeApprover\": false, \"blockedApprovers\": [], \"instructions\": \"Review the saved plan in the run's Plan stage before approving (terraform.md rule 26).\" }"
      ;;
    ExclusiveLock)
      type_id="$CHECK_EXCLUSIVE_LOCK_ID" type_name="ExclusiveLock" settings="{}"
      ;;
    BranchControl)
      type_id="$CHECK_TASK_ID" type_name="Task Check"
      settings="{ \"definitionRef\": { \"id\": \"$BRANCH_CONTROL_TASK_ID\", \"name\": \"evaluatebranchProtection\", \"version\": \"0.0.1\" }, \"displayName\": \"Branch control\", \"inputs\": { \"allowedBranches\": \"refs/heads/$INTEGRATION_BRANCH\", \"ensureProtectionOfBranch\": \"true\", \"allowUnknownStatusBranch\": \"false\" }, \"retryInterval\": 5 }"
      ;;
    *) die "unknown check $kind" ;;
  esac
  write_body "$body" "$(
    cat <<EOF
{
  "type": { "id": "$type_id", "name": "$type_name" },
  "settings": $settings,
  "resource": { "type": "$resource_type", "id": "$resource_id", "name": "$resource_name" },
  "timeout": $CHECK_TIMEOUT_MINUTES
}
EOF
  )"
  if [[ "$kind" == BranchControl ]]; then
    filter="settings.definitionRef.id=='$BRANCH_CONTROL_TASK_ID'"
  else
    filter="type.id=='$type_id' || type.id=='$(printf '%s' "$type_id" | tr '[:lower:]' '[:upper:]')'"
  fi
  set_invoke GET PipelinesChecks configurations "project=$ADO_PROJECT" \
    --query-parameters "resourceType=$resource_type" "resourceId=$resource_id" \
    --query "value[?$filter].id | [0]" -o tsv
  check_id="$(lookup_id "" "${INVOKE[@]}")"
  if [[ -n "$check_id" ]]; then
    log "exists: $kind check on $resource_type $resource_name; re-applying its settings"
    set_invoke PATCH PipelinesChecks configurations "project=$ADO_PROJECT id=$check_id" \
      --in-file "$out_dir/$body" --output none
  else
    set_invoke POST PipelinesChecks configurations "project=$ADO_PROJECT" \
      --in-file "$out_dir/$body" --output none
  fi
  run "${INVOKE[@]}"
}

# ---------------------------------------------------------------------------
# Service connections: workload identity federation only, no secret (security.md rule 10).
# The federation subject is sc://<org>/<project>/<connection>, which state-backend.sh
# set on each deploy identity's federated credential.
endpoint_ids=()
for owner in shared dev prod; do
  connection="$(service_connection_name "$owner")"
  identity="$(deploy_identity_name "$owner")"
  step "Service connection $connection ($identity)"
  client_id="$(lookup_id "<clientId-of-$identity>" \
    az identity show --name "$identity" --resource-group "$STATE_RG" --query clientId -o tsv)"
  [[ -n "$client_id" ]] || die "deploy identity $identity not found; run state-backend.sh first"
  endpoint_query="[?name=='$connection'].id | [0]"
  endpoint_id="$(lookup_id "" az devops service-endpoint list "${PROJECT[@]}" --query "$endpoint_query" -o tsv)"
  if [[ -n "$endpoint_id" ]]; then
    binding="$(az devops service-endpoint show "${PROJECT[@]}" --id "$endpoint_id" \
      --query "join('|', [authorization.scheme, authorization.parameters.serviceprincipalid])" -o tsv)"
    if [[ "$binding" != "WorkloadIdentityFederation|$client_id" ]]; then
      die "service connection $connection exists but is '$binding', not WorkloadIdentityFederation for $identity ($client_id). Delete it in ADO and re-run."
    fi
    log "exists: $connection (workload identity federation, $identity)"
  else
    write_body "endpoint-$owner.json" "$(
      cat <<EOF
{
  "name": "$connection",
  "type": "azurerm",
  "url": "https://management.azure.com/",
  "description": "Deploy identity $identity (spine AD-17); workload identity federation, no secret.",
  "authorization": {
    "scheme": "WorkloadIdentityFederation",
    "parameters": { "tenantid": "$ARM_TENANT_ID", "serviceprincipalid": "$client_id" }
  },
  "data": {
    "environment": "AzureCloud",
    "scopeLevel": "Subscription",
    "subscriptionId": "$ARM_SUBSCRIPTION_ID",
    "subscriptionName": "$subscription_name",
    "creationMode": "Manual"
  },
  "isShared": false,
  "isReady": true,
  "serviceEndpointProjectReferences": [
    { "projectReference": { "id": "$project_id", "name": "$ADO_PROJECT" }, "name": "$connection" }
  ]
}
EOF
    )"
    run az devops service-endpoint create "${DEVOPS[@]}" \
      --service-endpoint-configuration "$out_dir/endpoint-$owner.json" --output none
    if ((DRY_RUN)); then
      endpoint_id="<endpointId-of-$connection>"
    else
      endpoint_id="$(lookup_id "" az devops service-endpoint list "${PROJECT[@]}" --query "$endpoint_query" -o tsv)"
      require_id "service connection $connection" "$endpoint_id"
    fi
  fi
  # ADO sets the federation issuer and subject; read them back, because the deploy
  # identity's federated credential (state-backend.sh) only trusts sc://<org>/<project>/<name>.
  expected_subject="sc://$ADO_ORG/$ADO_PROJECT/$connection"
  federation="$(lookup_id "<issuer>|$expected_subject" az devops service-endpoint list "${PROJECT[@]}" \
    --query "[?name=='$connection'] | [0] | join('|', [authorization.parameters.workloadIdentityFederationIssuer, authorization.parameters.workloadIdentityFederationSubject])" \
    -o tsv)"
  issuer="${federation%%|*}"
  subject="${federation#*|}"
  if [[ "$subject" != "$expected_subject" ]]; then
    die "service connection $connection has federation subject '$subject' (issuer '$issuer'), but $identity trusts '$expected_subject'. Align the federated credential (state-backend.sh) or the connection, then re-run."
  fi
  log "federation: issuer $issuer, subject $subject"
  endpoint_ids+=("$endpoint_id")
  ensure_check BranchControl endpoint "$endpoint_id" "$connection"
done

# ---------------------------------------------------------------------------
# Environments with their checks. Every environment gets an exclusive lock (one
# deploy at a time); shared and prod also get the approval check (AD-17: Dev applies
# automatically, shared and Prod after a manual approval).
environment_id() {
  set_invoke GET distributedtask environments "project=$ADO_PROJECT" \
    --query-parameters "name=$1" --query "value[?name=='$1'].id | [0]" -o tsv
  lookup_id "" "${INVOKE[@]}"
}

environment_ids=()
for env in shared dev prod; do
  step "Environment $env"
  env_id="$(environment_id "$env")"
  if [[ -n "$env_id" ]]; then
    log "exists: environment $env ($env_id)"
  else
    write_body "environment-$env.json" \
      "{ \"name\": \"$env\", \"description\": \"AD-17 deploy target ($env); checks set by infra/bootstrap/ado-setup.sh\" }"
    set_invoke POST distributedtask environments "project=$ADO_PROJECT" \
      --in-file "$out_dir/environment-$env.json" --output none
    run "${INVOKE[@]}"
    if ((DRY_RUN)); then
      env_id="<environmentId-of-$env>"
    else
      env_id="$(environment_id "$env")"
      require_id "environment $env" "$env_id"
    fi
  fi
  environment_ids+=("$env_id")

  ensure_check ExclusiveLock environment "$env_id" "$env"
  ensure_check BranchControl environment "$env_id" "$env"
  if [[ "$env" != dev ]]; then
    ensure_check Approval environment "$env_id" "$env"
  fi
done

# ---------------------------------------------------------------------------
pipeline_id() {
  lookup_id "" az pipelines list "${PROJECT[@]}" --name "$1" --query "[0].id" -o tsv
}

pr_pipeline_id=""
deploy_pipeline_id=""
for entry in "${PIPELINES[@]}"; do
  name="${entry%%|*}"
  yaml="${entry#*|}"
  step "Pipeline $name ($yaml)"
  id="$(pipeline_id "$name")"
  if [[ -n "$id" ]]; then
    log "exists: pipeline $name ($id)"
  else
    run az pipelines create "${PROJECT[@]}" --name "$name" --repository "$ADO_REPO" --repository-type tfsgit \
      --branch "$INTEGRATION_BRANCH" --yml-path "$yaml" --skip-first-run true --output none
    if ((DRY_RUN)); then
      id="<pipelineId-of-$name>"
    else
      id="$(pipeline_id "$name")"
      require_id "pipeline $name" "$id"
    fi
  fi
  case "$name" in
    *-pr) pr_pipeline_id="$id" ;;
    *-deploy) deploy_pipeline_id="$id" ;;
  esac
done

# Only the deploy pipeline may use the service connections and environments.
step "Authorise the deploy pipeline on the service connections and environments"
write_body "permit-deploy.json" "{ \"pipelines\": [ { \"id\": $deploy_pipeline_id, \"authorized\": true } ] }"
for pair in \
  "endpoint:${endpoint_ids[0]}" "endpoint:${endpoint_ids[1]}" "endpoint:${endpoint_ids[2]}" \
  "environment:${environment_ids[0]}" "environment:${environment_ids[1]}" "environment:${environment_ids[2]}"; do
  set_invoke PATCH pipelinePermissions pipelinePermissions \
    "project=$ADO_PROJECT resourceType=${pair%%:*} resourceId=${pair#*:}" \
    --in-file "$out_dir/permit-deploy.json" --output none
  run "${INVOKE[@]}"
done

# ---------------------------------------------------------------------------
# Branch policy: every change to main goes through a PR whose build must pass.
step "Branch policy on $INTEGRATION_BRANCH: PR build required"
policy_id="$(lookup_id "" az repos policy list "${PROJECT[@]}" --repository-id "$repo_id" \
  --branch "$INTEGRATION_BRANCH" \
  --query "[?type.displayName=='Build' && settings.buildDefinitionId==\`$pr_pipeline_id\`].id | [0]" -o tsv)"
policy_settings=(--blocking true --enabled true --display-name "PR checks (ci/checks.sh all)"
  --manual-queue-only false --queue-on-source-update-only false --valid-duration 720)
if [[ -n "$policy_id" ]]; then
  log "exists: build policy $policy_id; re-applying its settings"
  run az repos policy build update "${PROJECT[@]}" --id "$policy_id" --build-definition-id "$pr_pipeline_id" \
    "${policy_settings[@]}" --output none
else
  run az repos policy build create "${PROJECT[@]}" --repository-id "$repo_id" --branch "$INTEGRATION_BRANCH" \
    --build-definition-id "$pr_pipeline_id" "${policy_settings[@]}" --output none
fi

step "Done"
log "Next: merge to $INTEGRATION_BRANCH to run the deploy pipeline; approve the shared and prod stages when asked (see README.md)."
