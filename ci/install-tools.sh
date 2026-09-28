#!/usr/bin/env bash
#
# Installs the pinned CI tools on a hosted Linux x64 agent (pipelines/ only):
# each download is checked against the SHA-256 pinned in ci/lib.sh before use.
# Python and Node come from the UsePythonVersion and NodeTool tasks.

# shellcheck source-path=SCRIPTDIR source=lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

usage() {
  cat <<'EOF'
Usage: ci/install-tools.sh <terraform|gitleaks|uv>...

Installs into $CI_TOOLS_DIR (default .work/ci/bin) and, on an Azure DevOps agent,
prepends it to PATH for later steps.
EOF
}

(($#)) || {
  usage >&2
  exit 2
}
[[ "$1" == "-h" || "$1" == "--help" ]] && {
  usage
  exit 0
}
[[ "$(uname -s)-$(uname -m)" == "Linux-x86_64" ]] || die "install-tools.sh supports Linux x86_64 agents only"

BIN_DIR="${CI_TOOLS_DIR:-$CI_WORK/bin}"
mkdir -p "$BIN_DIR"
TEMP_PARENT="${AGENT_TEMPDIRECTORY:-$CI_WORK}"
mkdir -p "$TEMP_PARENT"
DOWNLOADS="$(mktemp -d "$TEMP_PARENT/tools.XXXXXX")"
trap 'rm -rf "$DOWNLOADS"' EXIT

# fetch URL SHA256 FILE - download and verify, or stop.
fetch() {
  local url="$1" sha="$2" file="$DOWNLOADS/$3"
  curl --fail --silent --show-error --location --retry 3 --output "$file" "$url"
  printf '%s  %s\n' "$sha" "$file" | sha256sum --check --status || die "checksum mismatch for $url"
  printf '%s' "$file"
}

for tool in "$@"; do
  case "$tool" in
    terraform)
      zip="$(fetch "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_amd64.zip" \
        "$TERRAFORM_SHA256_LINUX_AMD64" terraform.zip)"
      unzip -o -q "$zip" terraform -d "$BIN_DIR"
      ;;
    gitleaks)
      tgz="$(fetch "https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION}_linux_x64.tar.gz" \
        "$GITLEAKS_SHA256_LINUX_X64" gitleaks.tar.gz)"
      tar -xzf "$tgz" -C "$BIN_DIR" gitleaks
      ;;
    uv)
      tgz="$(fetch "https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/uv-x86_64-unknown-linux-gnu.tar.gz" \
        "$UV_SHA256_LINUX_X64" uv.tar.gz)"
      tar -xzf "$tgz" -C "$BIN_DIR" --strip-components=1 uv-x86_64-unknown-linux-gnu/uv uv-x86_64-unknown-linux-gnu/uvx
      ;;
    *) die "unknown tool: $tool" ;;
  esac
  log "installed $tool into $BIN_DIR"
done

if [[ -n "${TF_BUILD:-}" ]]; then
  echo "##vso[task.prependpath]$BIN_DIR"
fi
