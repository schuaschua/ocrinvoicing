#!/usr/bin/env bash
#
# Story 1.2 quality gate. The PR build (pipelines/pr.yml) and the weekly scan
# (pipelines/weekly-scan.yml) run these subcommands; run them locally the same way.
# Each check prints "==> <tool>" and, on failure, "FAILED: <tool>"; the script exits 1
# when any check failed.

# shellcheck source-path=SCRIPTDIR source=lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

# Test seam only: ci/tests point CHECKS_ROOT at a throwaway fixture tree under .work/.
if [[ -n "${CHECKS_ROOT:-}" ]]; then
  REPO_ROOT="$(cd "$CHECKS_ROOT" && pwd)"
  CI_WORK="$REPO_ROOT/.work/ci"
fi

usage() {
  cat <<'EOF'
Usage: ci/checks.sh <lint|test|audit|secrets|terraform|all>

  lint       ruff format/check, mypy and import-linter on backend/; ESLint, Prettier and tsc per
             scaffolded web app, and ESLint and Prettier on shared/quality/ (with
             web/supplier's); shellcheck on ci/ and infra/bootstrap/
  test       pytest with coverage (backend, floor 80%), Vitest with coverage per web
             app (floor 60%), then per web app the build, the supplier JS limit (150 KB
             gzipped) and the a11y check (Playwright + axe: WCAG 2.2 AA, 320px reflow,
             48px targets); pytest ci/tests. A part with no test files yet is skipped.
             Locally the a11y check skips when Playwright's Chromium is missing; under
             TF_BUILD it installs Chromium and never skips.
  audit      pip-audit on backend/uv.lock, npm audit --omit=dev per web app
  secrets    gitleaks on the git history and uncommitted changes
  terraform  terraform fmt -check, validate and test per root and module;
             pytest infra/scripts/tests
  all        every check above

Reports go to .work/ci/ (JUnit in test-results/, Cobertura in coverage/).
Tools needed: uv, terraform, gitleaks, shellcheck, node/npm (for scaffolded web apps) and
Playwright's Chromium for the a11y check (skipped locally when missing).
EOF
}

FAILED=""

# check NAME CMD... - run one tool; record a failure instead of stopping.
check() {
  local name="$1"
  shift
  printf '\n==> %s\n' "$name"
  local status=0
  "$@" || status=$?
  if ((status != 0)); then
    printf 'FAILED: %s (exit %s)\n' "$name" "$status" >&2
    FAILED="$FAILED
  $name"
  fi
}

skip() { printf '\n==> %s\nskipped: %s\n' "$1" "$2"; }

# fail MESSAGE - a check that always fails (used for a broken contract).
fail() {
  printf 'ERROR: %s\n' "$*" >&2
  return 1
}

# has_files DIR FIND-TESTS... - true when DIR holds a matching file (installed and generated folders ignored).
has_files() {
  local dir="$1"
  shift
  [[ -d "$dir" ]] || return 1
  [[ -n "$(find "$dir" \( -name node_modules -o -name .venv -o -name dist -o -name coverage \) -prune \
    -o -type f \( "$@" \) -print -quit)" ]]
}

backend_has_python() { has_files "$REPO_ROOT/backend/src" -name '*.py'; }
# Code under test: any module beyond the package markers (__init__.py) the skeleton ships.
backend_has_code() { has_files "$REPO_ROOT/backend/src" -name '*.py' ! -name '__init__.py'; }
backend_has_tests() { has_files "$REPO_ROOT/backend/tests" -name 'test_*.py' -o -name '*_test.py'; }
web_has_tests() {
  has_files "$1" -name '*.test.ts' -o -name '*.test.tsx' -o -name '*.spec.ts' -o -name '*.spec.tsx'
}

web_apps() {
  local dir
  for dir in "$REPO_ROOT"/web/*/; do
    [[ -f "$dir/package.json" ]] && printf '%s\n' "${dir%/}"
  done
  return 0
}

# A web app is scaffolded (Story 1.4) once its package.json defines scripts.
web_scaffolded() {
  python3 -c 'import json, sys; sys.exit(0 if json.load(open(sys.argv[1])).get("scripts") else 1)' "$1/package.json"
}

web_has_script() {
  python3 -c 'import json, sys; sys.exit(0 if sys.argv[2] in json.load(open(sys.argv[1])).get("scripts", {}) else 1)' \
    "$1/package.json" "$2"
}

# Roots hold a backend block; modules do not.
terraform_roots() {
  local file
  for file in "$REPO_ROOT"/infra/*/*/versions.tf; do
    case "$file" in */infra/modules/*) continue ;; esac
    grep -q 'backend "' "$file" && dirname "$file"
  done
  return 0
}

terraform_modules() {
  local file
  for file in "$REPO_ROOT"/infra/modules/*/versions.tf; do
    [[ -f "$file" ]] && dirname "$file"
  done
  return 0
}

rel() { printf '%s' "${1#"$REPO_ROOT"/}"; }

# vitest_in APP ARGS... - Vitest from the app's own devDependencies (never downloaded).
vitest_in() {
  local app="$1"
  shift
  (cd "$app" && npm exec --no -- vitest run "$@")
}

# bundle_size NAME DIST MAX_KB - the gzipped size of all built JavaScript, against MAX_KB.
bundle_size() {
  uv run --no-project --python "$PYTHON_VERSION" python - "$@" <<'PY'
import gzip
import pathlib
import sys

name, dist, limit = sys.argv[1], pathlib.Path(sys.argv[2]), float(sys.argv[3])
files = sorted(p for p in dist.rglob("*") if p.is_file() and p.suffix in (".js", ".mjs"))
if not files:
    sys.exit(f"ERROR: {name}: no JavaScript in {dist}")
kb = sum(len(gzip.compress(p.read_bytes(), compresslevel=9)) for p in files) / 1024
print(f"{name}: {len(files)} JS file(s), {kb:.1f} KB gzipped (limit {limit:g} KB)")
if kb > limit:
    sys.exit(f"ERROR: {name} JavaScript is {kb:.1f} KB gzipped, over the {limit:g} KB limit (UX-DR22)")
PY
}

# chromium_ready APP - the Chromium build the app's pinned Playwright needs is installed.
chromium_ready() {
  (cd "$1" && node -e '
const { existsSync } = require("node:fs");
const { chromium } = require("@playwright/test");
process.exit(existsSync(chromium.executablePath()) ? 0 : 1);') >/dev/null 2>&1
}

playwright_install() { (cd "$1" && npm exec --no -- playwright install --with-deps chromium); }

# web_build_checks APP NAME - build, the supplier bundle-size limit and the a11y check
# (Story 1.4: axe WCAG 2.2 AA, 320px reflow, 48px targets against `vite preview`).
web_build_checks() {
  local app="$1" name="$2" failed_before="$FAILED"
  check "npm run build ($name)" npm run --prefix "$app" build
  if [[ "$FAILED" != "$failed_before" ]]; then
    log "bundle size and a11y ($name) not run: the build failed"
    return 0
  fi
  if [[ "$name" == web/supplier ]]; then
    check "JS <= ${SUPPLIER_JS_GZIP_MAX_KB} KB gzipped ($name)" \
      bundle_size "$name" "$app/dist" "$SUPPLIER_JS_GZIP_MAX_KB"
  fi
  if ! web_has_script "$app" a11y; then
    check "a11y ($name)" fail "$name/package.json has no \"a11y\" script (axe and layout check, UX-DR21)"
    return 0
  fi
  if [[ -n "${TF_BUILD:-}" ]]; then
    # The PR build installs Chromium and never skips the check.
    failed_before="$FAILED"
    check "playwright install chromium ($name)" playwright_install "$app"
    if [[ "$FAILED" != "$failed_before" ]]; then
      log "a11y ($name) not run: the Chromium install failed"
      return 0
    fi
  elif ! chromium_ready "$app"; then
    skip "a11y ($name)" "Playwright's Chromium is not installed; run (cd $name && npx playwright install chromium). The PR build installs it and never skips."
    return 0
  fi
  check "a11y: axe WCAG 2.2 AA, 320px reflow, 48px targets ($name)" \
    env PLAYWRIGHT_JUNIT_OUTPUT_FILE="$CI_WORK/test-results/${name//\//-}-a11y.xml" \
    npm run --prefix "$app" a11y
}

# supplier_tool TOOL ARGS... - a tool from web/supplier's devDependencies, run there.
supplier_tool() { (cd "$REPO_ROOT/web/supplier" && npm exec --no -- "$@"); }

uv_backend() { uv run --directory "$REPO_ROOT/backend" --locked "$@"; }

# pytest outside the backend project (ci/tests, infra/scripts/tests), pinned.
pytest_tools() {
  local pins=(--with "pytest==$PYTEST_VERSION" --with "pyyaml==$PYYAML_VERSION") pin
  for pin in $PYTEST_DEPENDENCY_PINS $PYTEST_XDIST_PINS; do pins+=(--with "$pin"); done
  uv run --no-project --python "$PYTHON_VERSION" "${pins[@]}" pytest -p no:cacheprovider "$@"
}

# ---------------------------------------------------------------------------

run_lint() {
  if backend_has_python; then
    check "ruff format (backend)" uv_backend ruff format --check
    check "ruff check (backend)" uv_backend ruff check
    check "mypy (backend)" uv_backend mypy
    # AD-10 (Story 2.4): the import contracts in backend/pyproject.toml.
    check "import-linter (backend)" uv_backend lint-imports
  else
    skip "backend lint" "no Python code in backend/src yet"
  fi

  local app name script
  for app in $(web_apps); do
    name="$(rel "$app")"
    if ! web_scaffolded "$app"; then
      skip "$name lint" "not scaffolded yet (no scripts in package.json)"
      continue
    fi
    check "npm ci ($name)" npm ci --prefix "$app" --no-audit --no-fund
    for script in lint format:check typecheck; do
      if web_has_script "$app" "$script"; then
        check "npm run $script ($name)" npm run --prefix "$app" "$script"
      else
        check "npm run $script ($name)" fail "$name/package.json has no \"$script\" script (ESLint, Prettier and tsc are required, coding-style.md section 1)"
      fi
    done
  done

  # shared/quality/ (Story 1.9) belongs to no app: it is linted and format-checked with
  # the supplier page's ESLint and Prettier (shared/eslint.config.mjs points ESLint at
  # the supplier rules). The supplier app was installed above.
  if has_files "$REPO_ROOT/shared/quality" -name '*.ts'; then
    if [[ -d "$REPO_ROOT/web/supplier/node_modules" ]]; then
      check "eslint (shared/quality)" supplier_tool eslint --max-warnings 0 ../../shared/quality
      check "prettier --check (shared/quality)" supplier_tool prettier --check \
        ../../shared/quality ../../shared/eslint.config.mjs ../../shared/quality-thresholds.json
    else
      check "lint (shared/quality)" fail "web/supplier is not installed, so shared/quality can't be linted"
    fi
  fi

  local scripts=() file
  for file in "$REPO_ROOT"/ci/*.sh "$REPO_ROOT"/infra/bootstrap/*.sh; do
    [[ -f "$file" ]] && scripts+=("$file")
  done
  if ((${#scripts[@]})); then
    check "shellcheck" shellcheck --external-sources "${scripts[@]}"
  else
    skip "shellcheck" "no shell scripts"
  fi
}

run_test() {
  mkdir -p "$CI_WORK/test-results" "$CI_WORK/coverage"
  # Reports from an earlier run must not count towards the test-case limit.
  rm -f "$CI_WORK"/test-results/*.xml
  # A floor can't be dodged by deleting tests: once there is code, tests are required.
  if ! backend_has_code; then
    skip "pytest (backend)" "no tests yet (no backend code yet)"
  elif ! backend_has_tests; then
    check "pytest (backend)" fail "backend/src has code but backend/tests has no test files; the ${BACKEND_COVERAGE_MIN}% coverage floor applies"
  else
    check "pytest with coverage >= ${BACKEND_COVERAGE_MIN}% (backend)" uv_backend pytest \
      --cov --cov-branch --cov-report=term --cov-report="xml:$CI_WORK/coverage/backend.xml" \
      --cov-fail-under="$BACKEND_COVERAGE_MIN" --junitxml="$CI_WORK/test-results/backend.xml"
  fi

  local app name failed_before
  for app in $(web_apps); do
    name="$(rel "$app")"
    if ! web_scaffolded "$app"; then
      skip "vitest ($name)" "no tests yet (not scaffolded yet)"
      continue
    fi
    if ! web_has_tests "$app"; then
      check "vitest ($name)" fail "$name is scaffolded but has no test files; the ${WEB_COVERAGE_MIN}% coverage floor applies"
    fi
    failed_before="$FAILED"
    check "npm ci ($name)" npm ci --prefix "$app" --no-audit --no-fund
    if [[ "$FAILED" != "$failed_before" ]]; then
      log "vitest, build, bundle size and a11y ($name) not run: npm ci failed"
      continue
    fi
    if web_has_tests "$app"; then
      # The floor is passed here so a web app's own config cannot lower it.
      check "vitest with coverage >= ${WEB_COVERAGE_MIN}% ($name)" \
        vitest_in "$app" \
        --coverage.enabled=true --coverage.provider=v8 \
        --coverage.reporter=text-summary --coverage.reporter=cobertura \
        --coverage.reportsDirectory="$CI_WORK/coverage/${name//\//-}" \
        --coverage.thresholds.lines="$WEB_COVERAGE_MIN" --coverage.thresholds.statements="$WEB_COVERAGE_MIN" \
        --coverage.thresholds.functions="$WEB_COVERAGE_MIN" --coverage.thresholds.branches="$WEB_COVERAGE_MIN" \
        --reporter=default --reporter=junit --outputFile.junit="$CI_WORK/test-results/${name//\//-}.xml"
    fi
    web_build_checks "$app" "$name"
  done

  if [[ -d "$REPO_ROOT/ci/tests" ]]; then
    check "pytest (ci/tests)" pytest_tools "$REPO_ROOT/ci/tests" -q -n auto --junitxml="$CI_WORK/test-results/ci.xml"
  else
    skip "pytest (ci/tests)" "no ci/tests"
  fi
  check "at most $MAX_TEST_CASES test cases" test_case_limit
}

# test_case_limit - the whole repo's test cases, each parameterised case counting
# (coding-style.md rule 20 exception): this run's JUnit reports (backend, Vitest,
# ci/tests), plus the Playwright a11y tests, infra/scripts/tests and terraform test
# runs, which are listed rather than run here (a11y may be skipped locally; the other
# two run in the terraform job).
test_case_limit() {
  local reports=() file junit=0 playwright=0 infra=0 terraform=0 app line total
  for file in "$CI_WORK"/test-results/*.xml; do
    [[ -e "$file" && "$file" != *-a11y.xml && "$file" != */infra-scripts.xml ]] && reports+=("$file")
  done
  if ((${#reports[@]})); then
    junit="$(cat "${reports[@]}" | grep -o '<testcase ' | wc -l | tr -d ' ')"
  fi
  for app in $(web_apps); do
    web_has_script "$app" a11y || continue
    line="$(cd "$app" && npm exec --no -- playwright test --list | grep -E '^Total: [0-9]+ test')" || {
      log "ERROR: could not list the Playwright tests in $(rel "$app")"
      return 1
    }
    playwright=$((playwright + $(awk '{print $2}' <<<"$line")))
  done
  if [[ -d "$REPO_ROOT/infra/scripts/tests" ]]; then
    line="$(pytest_tools "$REPO_ROOT/infra/scripts/tests" --collect-only -q | tail -1)"
    infra="$(awk '{print $1}' <<<"$line")"
  fi
  if [[ -d "$REPO_ROOT/infra" ]]; then
    terraform="$(find "$REPO_ROOT/infra" -name '*.tftest.hcl' -not -path '*/.terraform/*' -exec cat {} + |
      { grep -c '^run "' || true; })"
  fi
  total=$((junit + playwright + infra + terraform))
  log "test cases: $total (JUnit $junit, Playwright $playwright, infra/scripts $infra, terraform runs $terraform); limit $MAX_TEST_CASES"
  ((total <= MAX_TEST_CASES)) || {
    log "ERROR: $total test cases, over the limit of $MAX_TEST_CASES (coding-style.md rule 20 exception)"
    return 1
  }
}

run_audit() {
  mkdir -p "$CI_WORK"
  local requirements="$CI_WORK/requirements-audit.txt" failed_before="$FAILED"
  rm -f "$requirements" # never audit a stale file from an earlier run
  check "uv export (backend)" uv export --directory "$REPO_ROOT/backend" --locked --all-groups \
    --no-emit-project --format requirements-txt --quiet -o "$requirements"
  if [[ "$FAILED" != "$failed_before" ]]; then
    log "pip-audit (backend) not run: uv export failed"
  elif grep -q '==' "$requirements"; then
    check "pip-audit (backend)" uv_backend pip-audit --disable-pip --require-hashes \
      --progress-spinner off -r "$requirements"
  else
    skip "pip-audit (backend)" "uv export produced no pinned dependencies"
  fi

  local app
  for app in $(web_apps); do
    if [[ -f "$app/package-lock.json" ]]; then
      check "npm audit --omit=dev ($(rel "$app"))" npm audit --prefix "$app" --omit=dev
    else
      check "npm audit --omit=dev ($(rel "$app"))" fail "$(rel "$app")/package-lock.json is missing"
    fi
  done
}

run_secrets() {
  local config="$REPO_ROOT/.gitleaks.toml"
  check "gitleaks (git history)" gitleaks git --no-banner --redact --config "$config" "$REPO_ROOT"
  check "gitleaks (uncommitted changes)" gitleaks git --no-banner --redact --config "$config" --pre-commit "$REPO_ROOT"
  check "gitleaks (staged changes)" gitleaks git --no-banner --redact --config "$config" --pre-commit --staged "$REPO_ROOT"
}

run_terraform() {
  check "terraform fmt -check" terraform fmt -check -recursive "$REPO_ROOT/infra"
  local dir name
  for dir in $(terraform_roots); do
    name="$(rel "$dir")"
    check "terraform init ($name)" terraform -chdir="$dir" init -backend=false -input=false -lockfile=readonly
    check "terraform validate ($name)" terraform -chdir="$dir" validate
    check "terraform test ($name)" terraform -chdir="$dir" test
  done
  for dir in $(terraform_modules); do
    name="$(rel "$dir")"
    check "terraform init ($name)" terraform -chdir="$dir" init -backend=false -input=false
    check "terraform validate ($name)" terraform -chdir="$dir" validate
    check "terraform test ($name)" terraform -chdir="$dir" test
  done
  mkdir -p "$CI_WORK/test-results"
  if [[ -d "$REPO_ROOT/infra/scripts/tests" ]]; then
    check "pytest (infra/scripts/tests)" pytest_tools "$REPO_ROOT/infra/scripts/tests" -q \
      --junitxml="$CI_WORK/test-results/infra-scripts.xml"
  else
    skip "pytest (infra/scripts/tests)" "no infra/scripts/tests"
  fi
}

# ---------------------------------------------------------------------------

(($# == 1)) || {
  usage >&2
  exit 2
}
case "$1" in
  -h | --help)
    usage
    exit 0
    ;;
  lint) run_lint ;;
  test) run_test ;;
  audit) run_audit ;;
  secrets) run_secrets ;;
  terraform) run_terraform ;;
  all)
    run_lint
    run_test
    run_audit
    run_secrets
    run_terraform
    ;;
  *)
    usage >&2
    die "unknown subcommand: $1"
    ;;
esac

if [[ -n "$FAILED" ]]; then
  printf '\nFailed checks:%s\n' "$FAILED" >&2
  exit 1
fi
printf '\nAll checks passed (%s).\n' "$1"
