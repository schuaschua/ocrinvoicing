"""Story 1.2: structural tests on the Jenkins CI/CD (Jenkinsfile, ci/jenkins/) and repo-wide
guards on the scripts behind it. Offline: the files are read as text, nothing runs Jenkins.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
JENKINSFILE = REPO_ROOT / "Jenkinsfile"
JENKINS_DIR = REPO_ROOT / "ci" / "jenkins"
WEEKLY = JENKINS_DIR / "Jenkinsfile.weekly"
PROD = JENKINS_DIR / "Jenkinsfile.prod"

# The AD-17 order on main (spine AD-17; Prod is its own job, Dj 2026-10-02).
DEPLOY_STAGES = [
    "Plan shared/foundation",
    "Approve shared/foundation",
    "Apply shared/foundation",
    "Plan dev/foundation",
    "Apply dev/foundation",
    "Migrate dev",
    "Plan dev/app",
    "Apply dev/app",
    "Deploy code dev",
    "Record dev commit",
    "Tag sweep",
]
# The Prod job's order (Jenkinsfile.prod), without its two grouping stages.
PROD_STAGES = [
    "Verify the commit",
    "Plan prod/foundation",
    "Approve prod/foundation",
    "Apply prod/foundation",
    "Migrate prod",
    "Plan prod/app",
    "Approve prod/app",
    "Apply prod/app",
    "Deploy code prod",
    "Tag sweep prod",
]
# The Jenkins tree in casc.yaml: (Job DSL kind, full name).
JENKINS_TREE = [
    ("folder", "ocrinvoicing"),
    ("folder", "ocrinvoicing/dev"),
    ("folder", "ocrinvoicing/prod"),
    ("multibranchPipelineJob", "ocrinvoicing/dev/ocrinvoicing"),
    ("pipelineJob", "ocrinvoicing/dev/weekly-scan"),
    ("pipelineJob", "ocrinvoicing/prod/deploy"),
]


def _code(path: Path) -> str:
    """The file without comment lines (comments may name things to explain them)."""
    return "\n".join(line for line in path.read_text(encoding="utf-8").splitlines() if not line.lstrip().startswith(("//", "#")))


def _stage_body(text: str, name: str) -> str:
    """The text of one stage('name') block, up to the next stage."""
    start = text.index(f"stage('{name}')")
    following = text.find("stage('", start + 1)
    return text[start : following if following != -1 else len(text)]


def _lib_value(name: str) -> str:
    match = re.search(rf'^readonly {name}="?([^"\n]+)"?$', (REPO_ROOT / "ci" / "lib.sh").read_text(), re.M)
    assert match, f"{name} not found in ci/lib.sh"
    return match.group(1)


def _jenkinsfile_guards() -> None:
    """The Jenkinsfiles and image. Covers: every checks.sh subcommand on every branch but
    main (its PR build ran them), terraform beside the app checks, and the audit weekly; the AD-17 stage order on main; an input step (Dj only) on shared and nowhere
    else; no Prod stage or identity; each stack applies its own saved plan; sign-in only through
    the deploy identity; status posted to the PR with the token from the credential; the image
    pins the tools of ci/lib.sh and Terraform matches the plugin tool. The Jenkins tree in casc;
    the Prod job: started by hand on main, only the commit the dev chain recorded, checked in
    every stage, Dj's approval before each apply, signed in only as Prod; the tag sweeps."""
    text = _code(JENKINSFILE)
    stages = re.findall(r"stage\('([^']+)'\)", text)

    # Every check on every branch but main; terraform beside the app checks; the audit
    # weekly.
    assert re.findall(r"sh 'ci/checks\.sh (\w+)'", text) == ["lint", "test", "audit", "secrets", "terraform"]
    checks = text[text.index("stage('Checks')") : text.index("stage('Deploy (AD-17)')")]
    assert "when { not { branch 'main' } }" in checks[:600]
    assert "parallel {" in checks and checks.index("stage('terraform')") > checks.index("parallel {")
    assert "TF_PLUGIN_CACHE_DIR = '/var/jenkins_home/" in text
    # Branch workspaces and the tests' leftover volumes are removed after the checks.
    assert "cleanup {" in checks and "deleteDir()" in checks and "docker volume prune --force" in checks
    weekly = _code(WEEKLY)
    assert re.findall(r"ci/checks\.sh (\w+)", weekly) == ["audit"]
    casc = (JENKINS_DIR / "casc.yaml").read_text(encoding="utf-8")
    assert "cron(" not in weekly, "the schedule is defined once, on the job in casc.yaml"
    (cron,) = re.findall(r"spec\('([^']+)'\)", casc)
    minute, hour, dom, month, dow = cron.split()
    assert dom == "*" and month == "*" and dow != "*"  # weekly
    assert "TF_BUILD = 'true'" in text and "TF_BUILD = 'true'" in weekly

    # The AD-17 order, only on main and only after the checks passed.
    assert [name for name in stages[stages.index("Deploy (AD-17)") + 1 :] if name != "Apply shared, then Dev"] == DEPLOY_STAGES
    deploy = text[text.index("stage('Deploy (AD-17)')") :]
    assert "branch 'main'" in deploy[:300] and "currentBuild.currentResult == 'SUCCESS'" in deploy[:300]

    # One input, only Dj, only before the shared apply; waiting holds no executor (no agent
    # at the top or on the approval stage; the input is a stage directive, skipped when the
    # plan has no changes).
    assert len(re.findall(r"\binput\b", text)) == 1
    approve = _stage_body(text, "Approve shared/foundation")
    assert "input {" in approve and "submitter 'dj'" in approve and "timeout(time: 24, unit: 'HOURS')" in approve
    assert "beforeInput true" in approve and "expression { HAS_WORK.shared_foundation }" in approve
    assert "agent" not in approve
    assert re.search(r"pipeline \{\s*agent none", text)

    # No Prod anywhere: no stage, stack, identity or migration.
    assert not re.search(r"(?i)prod", text)
    assert "owner in ['shared', 'dev']" in text

    # Each stack applies only the saved plan of its own plan stage, only when it has changes.
    for stack, owner in (("shared/foundation", "shared"), ("dev/foundation", "dev"), ("dev/app", "dev")):
        step = stack.replace("/", "_")
        assert f"planStack('{step}', '{stack}', '{owner}'" in _stage_body(text, f"Plan {stack}")
        apply = _stage_body(text, f"Apply {stack}")
        assert f"applyStack('{step}', '{stack}', '{owner}')" in apply
        assert f"HAS_WORK.{step}" in apply
    assert 'sh "ci/terraform-apply.sh ${stack} .work/ci/plans/${id}/tfplan"' in text
    assert "ci/terraform-plan.sh ${stack} .work/ci/plans/${id}" in text

    # Sign-in only as the stage owner's deploy identity; Terraform from the plugin tool.
    assert "az login --identity --client-id \"$CI_MSI_CLIENT_ID\"" in text
    assert "DEPLOY_CLIENT_ID_${owner.toUpperCase()}" in text
    assert "PATH+TERRAFORM=${tool TERRAFORM_TOOL}" in text

    # PR status with the token from the Jenkins credential, never echoed.
    assert "usernamePassword(credentialsId: 'ado-pat'" in text and 'sh "ci/ado-status.sh ${state}"' in text
    status = (REPO_ROOT / "ci" / "ado-status.sh").read_text(encoding="utf-8")
    assert "--config -" in status and "set -x" not in status and "echo \"$ADO_PAT" not in status

    # Saved plans and az profiles never outlive the run; a failed status post is caught (the
    # build fails without posting a second time).
    assert "rm -rf .work/ci/plans .work/azure-* || true" in text and text.count("sh CLEANUP") == 2
    assert "catch (err)" in text and "currentBuild.result = 'FAILURE'" in text

    # The image pins the tools of ci/lib.sh; the Terraform plugin tool is the same version.
    dockerfile = (JENKINS_DIR / "Dockerfile").read_text(encoding="utf-8")
    args = dict(re.findall(r"^ARG (\w+)=(\S+)$", dockerfile, re.M))
    for arg, lib in (
        ("TERRAFORM_VERSION", "TERRAFORM_VERSION"),
        ("TERRAFORM_SHA256", "TERRAFORM_SHA256_LINUX_AMD64"),
        ("GITLEAKS_VERSION", "GITLEAKS_VERSION"),
        ("GITLEAKS_SHA256", "GITLEAKS_SHA256_LINUX_X64"),
        ("UV_VERSION", "UV_VERSION"),
        ("UV_SHA256", "UV_SHA256_LINUX_X64"),
    ):
        assert args[arg] == _lib_value(lib), arg
    assert args["NODE_VERSION"].split(".")[0] == _lib_value("NODE_VERSION")
    assert re.search(r"^FROM .*jenkins/jenkins:[\d.]+-lts-jdk\d+@sha256:[0-9a-f]{64}$", dockerfile, re.M)
    # The Terraform tool's home is the image's checksum-verified copy: nothing is downloaded.
    version = _lib_value("TERRAFORM_VERSION")
    assert f'name: "terraform-{version}"\n        home: "/usr/local/bin"' in casc and f"'terraform-{version}'" in text
    assert "terraformInstaller" not in casc and "installSource" not in casc
    assert "-d /usr/local/bin" in dockerfile and "terraform.zip terraform" in dockerfile
    plugins = [line for line in (JENKINS_DIR / "plugins.txt").read_text().splitlines() if line and not line.startswith("#")]
    assert all(re.fullmatch(r"[\w.-]+:[\w.-]+", line) for line in plugins), "every plugin is pinned"

    # The Jenkins tree: exactly the three jobs under ocrinvoicing/dev and ocrinvoicing/prod.
    casc_code = _code(JENKINS_DIR / "casc.yaml")
    assert re.findall(r"\b(folder|multibranchPipelineJob|pipelineJob)\('([^']+)'\)", casc_code) == JENKINS_TREE
    # The prod job's block only: up to its closing brace at the job indentation.
    start = casc_code.index("pipelineJob('ocrinvoicing/prod/deploy')")
    prod_job = casc_code[start : casc_code.index("\n      }", start) + 8]
    assert "scriptPath('ci/jenkins/Jenkinsfile.prod')" in prod_job and "branch('*/main')" in prod_job
    assert "triggers" not in prod_job and "cron" not in prod_job, "Dj starts the Prod job by hand"
    assert 'key: "DEPLOY_CLIENT_ID_PROD"' in casc

    # The tag sweep (shared, then dev) and the dev-commit record end the dev chain.
    sweep = _stage_body(text, "Tag sweep")
    assert sweep.index("asDeployIdentity('shared') { sh 'ci/tag-sweep.sh shared' }") < sweep.index(
        "asDeployIdentity('dev') { sh 'ci/tag-sweep.sh dev' }"
    )
    assert "sh 'ci/deploy-state.sh record'" in _stage_body(text, "Record dev commit")

    # The Prod job: the AD-17 order, one checkout, only the recorded commit.
    prod = _code(PROD)
    prod_stages = re.findall(r"stage\('([^']+)'\)", prod)
    assert [name for name in prod_stages if ", " not in name] == PROD_STAGES
    assert "skipDefaultCheckout()" in prod and "disableConcurrentBuilds()" in prod
    assert prod.count("checkout scm") == 1 and "checkout scm" in _stage_body(prod, "Verify the commit")
    verify = _stage_body(prod, "Verify the commit")
    assert "DEPLOY_COMMIT = sh(returnStdout: true, script: 'ci/deploy-state.sh verify').trim()" in verify
    assert verify.index("checkout scm") < verify.index("ci/deploy-state.sh verify")
    # Every later stage acts only on that commit (asProd checks it before signing in).
    asprod = prod[prod.index("def asProd(") : prod.index("def planStack(")]
    assert asprod.index("onDeployCommit()") < asprod.index("az login")
    for name in PROD_STAGES[1:]:
        if not name.startswith("Approve"):
            assert re.search(r"planStack\(|applyStack\(|onDeployCommit\(\)|asProd \{", _stage_body(prod, name)), name
    # Dj approves each apply: two inputs, Dj only, 24 hours, no executor held while waiting.
    assert len(re.findall(r"\binput\b", prod)) == 2 and re.search(r"pipeline \{\s*agent none", prod)
    for stack in ("prod/foundation", "prod/app"):
        step = stack.replace("/", "_")
        approve = _stage_body(prod, f"Approve {stack}")
        assert "input {" in approve and "submitter 'dj'" in approve and "timeout(time: 24, unit: 'HOURS')" in approve
        assert "beforeInput true" in approve and f"expression {{ HAS_WORK.{step} }}" in approve
        assert "agent" not in approve
        assert f"applyStack('{step}', '{stack}')" in _stage_body(prod, f"Apply {stack}")
    assert "asProd { sh 'ci/tag-sweep.sh prod' }" in _stage_body(prod, "Tag sweep prod")
    # Only Prod's identity, and only in this file.
    assert "env.DEPLOY_CLIENT_ID_PROD" in prod and "DEPLOY_CLIENT_ID_PROD" not in text
    assert not re.search(r"(?i)DEPLOY_CLIENT_ID_(SHARED|DEV)|'(shared|dev)/|ci/\S+\.sh (shared|dev)\b", prod)
    assert "rm -rf .work/ci/plans .work/azure-* || true" in prod and prod.count("sh CLEANUP") == 1


def _repo_guards() -> None:
    """Repo-wide scans of the Jenkinsfiles and ci/. Covers: no auto-approve and apply only from a
    saved plan; operator steps never run in CI; no GitHub Actions or Azure DevOps YAML; no secret
    in the Jenkins configuration; tool downloads are pinned by checksum."""
    jenkinsfiles = [JENKINSFILE, WEEKLY, PROD]
    scripts = sorted((REPO_ROOT / "ci").glob("*.sh"))

    # No auto-approve; apply only from a saved plan.
    for path in [*jenkinsfiles, *scripts, JENKINS_DIR / "casc.yaml"]:
        assert "auto-approve" not in path.read_text(encoding="utf-8"), path
    applies = [
        (path.name, line.strip())
        for path in scripts
        for line in path.read_text(encoding="utf-8").splitlines()
        if re.match(r"\s*terraform\b.*\bapply\b", line)
    ]
    assert applies == [("terraform-apply.sh", 'terraform -chdir="$dir" apply -input=false -lock-timeout=5m tfplan')]

    # Operator steps never run in CI (code lines only: comments may name one).
    operator_scripts = [p.name for p in (REPO_ROOT / "infra" / "bootstrap").glob("*.sh") if p.name != "lib.sh"]
    assert "ci-vm.sh" in operator_scripts
    texts = [_code(path) for path in [*jenkinsfiles, *scripts]]
    for name in operator_scripts:
        assert not any(name in text for text in texts), name

    # No other CI system.
    assert not (REPO_ROOT / ".github" / "workflows").exists()
    assert not (REPO_ROOT / "pipelines").exists()
    assert not any("##vso[" in text for text in texts)

    # No secret in the Jenkins configuration: secrets come only from mounted files.
    casc = (JENKINS_DIR / "casc.yaml").read_text(encoding="utf-8")
    secret_values = re.findall(r"(?im)^\s*(?:password|secret|token)\s*:\s*(\S+)", casc)
    assert secret_values and all(value.startswith('"${readFile:/run/secrets/') for value in secret_values)

    # Tool downloads are pinned by checksum.
    for name in ("TERRAFORM_SHA256_LINUX_AMD64", "GITLEAKS_SHA256_LINUX_X64", "UV_SHA256_LINUX_X64"):
        assert re.fullmatch(r"[0-9a-f]{64}", _lib_value(name)), name
    dockerfile = (JENKINS_DIR / "Dockerfile").read_text(encoding="utf-8")
    downloads = re.findall(r'fetch "(\S+)"', dockerfile)
    sums = re.findall(r"^ARG \w+_SHA256=([0-9a-f]{64})$", dockerfile, re.M)
    assert len(downloads) == len(sums) == 6


def test_story_1_2_jenkins_and_repo_guards() -> None:
    """Story 1.2 guards, merged under the test cap: the Jenkinsfiles and image, then repo-wide scans."""
    _jenkinsfile_guards()
    _repo_guards()
