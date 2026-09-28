#!/usr/bin/env bash
# shellcheck shell=bash
# shellcheck disable=SC2034  # constants are used by the scripts that source this file
#
# Shared settings for the CI scripts (Story 1.2). Sourced, never executed.
# The pipelines in pipelines/ only call these scripts, so every check also runs locally.

set -Eeuo pipefail

CI_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$CI_DIR/.." && pwd)"
# Reports (JUnit, Cobertura) and scratch files go under the gitignored .work/ folder.
CI_WORK="$REPO_ROOT/.work/ci"
export CI_DIR REPO_ROOT CI_WORK

# Pinned tool versions. Terraform matches required_version in every root.
readonly TERRAFORM_VERSION="1.16.4"
readonly TERRAFORM_SHA256_LINUX_AMD64="dc94af0eef1147718ad7c8daea792ed199e3e0492eec180d0adafa2a65a879df"
readonly GITLEAKS_VERSION="8.30.1"
readonly GITLEAKS_SHA256_LINUX_X64="551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb"
readonly UV_VERSION="0.11.8"
readonly UV_SHA256_LINUX_X64="56dd1b66701ecb62fe896abb919444e4b83c5e8645cca953e6ddd496ff8a0feb"
readonly PYTHON_VERSION="3.13"
readonly NODE_VERSION="22"
# Test runner for ci/tests and infra/scripts/tests (outside the backend project).
readonly PYTEST_VERSION="9.1.1"
readonly PYYAML_VERSION="6.0.3"
# pytest's own dependencies, pinned too so the test runner is fully reproducible.
readonly PYTEST_DEPENDENCY_PINS="iniconfig==2.3.0 packaging==26.3 pluggy==1.6.0 pygments==2.21.0"

# Coverage floors (Story 1.2, coding-style.md rule 25). Never lower them to pass;
# backend/pyproject.toml [tool.coverage.report] fail_under holds the same backend value.
readonly BACKEND_COVERAGE_MIN=80
readonly WEB_COVERAGE_MIN=60
# Supplier page JavaScript budget, gzipped (UX-DR22: weak mobile signal).
readonly SUPPLIER_JS_GZIP_MAX_KB=150

log() { printf '%s\n' "$*"; }
die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

# set_output NAME VALUE - an Azure DevOps output variable (read by later stages'
# conditions); printed plainly when run locally.
set_output() {
  if [[ -n "${TF_BUILD:-}" ]]; then
    echo "##vso[task.setvariable variable=$1;isOutput=true]$2"
  else
    log "output: $1=$2"
  fi
}

# Deploy-time settings come from the AzureCLI@2 task's signed-in service connection;
# nothing is stored in the repo or the pipeline (azure.md rule 6). `az` stays signed
# in through the task. Terraform (provider and azurerm backend) uses azurerm's Azure
# DevOps OIDC: it asks the pipeline for a fresh federated token whenever it needs one,
# so a long apply cannot outlive a static token. The task exposes the connection
# (AZURESUBSCRIPTION_*); the step maps SYSTEM_ACCESSTOKEN in from $(System.AccessToken);
# SYSTEM_OIDCREQUESTURI is a predefined agent variable.
export_arm_context() {
  if [[ -z "${ARM_SUBSCRIPTION_ID:-}" ]]; then
    ARM_SUBSCRIPTION_ID="$(az account show --query id -o tsv)"
  fi
  if [[ -z "${ARM_TENANT_ID:-}" ]]; then
    ARM_TENANT_ID="${AZURESUBSCRIPTION_TENANT_ID:-${tenantId:-$(az account show --query tenantId -o tsv)}}"
  fi
  export ARM_SUBSCRIPTION_ID ARM_TENANT_ID
  [[ -n "${TF_BUILD:-}" ]] || return 0
  local name
  for name in AZURESUBSCRIPTION_SERVICE_CONNECTION_ID SYSTEM_ACCESSTOKEN SYSTEM_OIDCREQUESTURI; do
    [[ -n "${!name:-}" ]] || die "$name is not set: run this in an AzureCLI@2 task with SYSTEM_ACCESSTOKEN mapped from \$(System.AccessToken)"
  done
  export ARM_USE_OIDC=true ARM_USE_CLI=false
  export ARM_CLIENT_ID="${AZURESUBSCRIPTION_CLIENT_ID:-${servicePrincipalId:-}}"
  [[ -n "$ARM_CLIENT_ID" ]] || die "no client id for the service connection (AZURESUBSCRIPTION_CLIENT_ID)"
  export ARM_ADO_PIPELINE_SERVICE_CONNECTION_ID="$AZURESUBSCRIPTION_SERVICE_CONNECTION_ID"
  export ARM_OIDC_REQUEST_TOKEN="$SYSTEM_ACCESSTOKEN" ARM_OIDC_REQUEST_URL="$SYSTEM_OIDCREQUESTURI"
  unset ARM_OIDC_TOKEN
}

# stack_dir STACK - infra/<env>/<stack> for a stack given as <env>/<stack>.
# CI_INFRA_DIR is a test seam only (ci/tests point it at a scratch copy).
stack_dir() {
  [[ "$1" =~ ^(shared|dev|prod)/[a-z]+$ ]] || die "stack must be <shared|dev|prod>/<name>, got '$1'"
  printf '%s/%s' "${CI_INFRA_DIR:-$REPO_ROOT/infra}" "$1"
}
