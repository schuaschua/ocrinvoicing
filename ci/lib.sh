#!/usr/bin/env bash
# shellcheck shell=bash
# shellcheck disable=SC2034  # constants are used by the scripts that source this file
#
# Shared settings for the CI scripts (Story 1.2). Sourced, never executed.
# The Jenkins pipelines (Jenkinsfile, ci/jenkins/Jenkinsfile.weekly) only call these
# scripts, so every check also runs locally.

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
# pytest-xdist runs ci/tests in parallel (-n auto); execnet is its only other dependency.
readonly PYTEST_XDIST_PINS="pytest-xdist==3.8.0 execnet==2.1.2"

# Coverage floors (Story 1.2, coding-style.md rule 25). Never lower them to pass;
# backend/pyproject.toml [tool.coverage.report] fail_under holds the same backend value.
readonly BACKEND_COVERAGE_MIN=80
readonly WEB_COVERAGE_MIN=60
# At most this many test cases across the repo, each parameterised case counting
# (Dj, 2026-09-29; coding-style.md rule 20 exception). Never raise it to pass.
readonly MAX_TEST_CASES=200
# Supplier page JavaScript budget, gzipped (UX-DR22: weak mobile signal).
readonly SUPPLIER_JS_GZIP_MAX_KB=150

log() { printf '%s\n' "$*"; }
die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

# set_output NAME VALUE - a step result the Jenkinsfile reads (e.g. hasWork, which
# skips a stage with nothing to do). Always printed; also appended as NAME=VALUE to
# $CI_OUTPUT_FILE when the Jenkinsfile sets it.
set_output() {
  log "output: $1=$2"
  if [[ -n "${CI_OUTPUT_FILE:-}" ]]; then
    mkdir -p "$(dirname "$CI_OUTPUT_FILE")"
    printf '%s=%s\n' "$1" "$2" >>"$CI_OUTPUT_FILE"
  fi
}

# Deploy-time sign-in (spine AD-17). On the CI VM every deploy stage runs as its stack
# owner's user-assigned deploy identity, attached to the VM: the Jenkinsfile sets
# CI_MSI_CLIENT_ID to that identity's client id and signs `az` in with
# `az login --identity --client-id`. Terraform (provider and azurerm backend) uses the
# same identity through the VM's managed-identity endpoint (ARM_USE_MSI). No Azure
# secret exists anywhere (azure.md rule 6). Locally, without CI_MSI_CLIENT_ID,
# Terraform uses the operator's own `az login`.
export_arm_context() {
  if [[ -z "${ARM_SUBSCRIPTION_ID:-}" ]]; then
    ARM_SUBSCRIPTION_ID="$(az account show --query id -o tsv)"
  fi
  if [[ -z "${ARM_TENANT_ID:-}" ]]; then
    ARM_TENANT_ID="$(az account show --query tenantId -o tsv)"
  fi
  export ARM_SUBSCRIPTION_ID ARM_TENANT_ID
  if [[ -z "${CI_MSI_CLIENT_ID:-}" ]]; then
    [[ -z "${TF_BUILD:-}" ]] || die "CI_MSI_CLIENT_ID is not set: in CI a deploy stage signs in only as its stack owner's deploy identity"
    return 0
  fi
  # Only the managed identity: no OIDC, CLI, secret or certificate variable is left for
  # azurerm to pick up instead.
  unset ARM_USE_OIDC ARM_USE_CLI ARM_OIDC_TOKEN ARM_OIDC_TOKEN_FILE_PATH ARM_OIDC_REQUEST_TOKEN \
    ARM_OIDC_REQUEST_URL ARM_ADO_PIPELINE_SERVICE_CONNECTION_ID ARM_CLIENT_SECRET \
    ARM_CLIENT_CERTIFICATE_PATH ARM_CLIENT_CERTIFICATE_PASSWORD
  export ARM_USE_MSI=true ARM_CLIENT_ID="$CI_MSI_CLIENT_ID"
}

# stack_dir STACK - infra/<env>/<stack> for a stack given as <env>/<stack>.
# CI_INFRA_DIR is a test seam only (ci/tests point it at a scratch copy).
stack_dir() {
  [[ "$1" =~ ^(shared|dev|prod)/[a-z]+$ ]] || die "stack must be <shared|dev|prod>/<name>, got '$1'"
  printf '%s/%s' "${CI_INFRA_DIR:-$REPO_ROOT/infra}" "$1"
}
