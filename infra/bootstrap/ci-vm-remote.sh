#!/usr/bin/env bash
#
# AD-17 step 1c, the part that runs on the CI VM as root (ci-vm.sh copies it there with
# the ci/jenkins build context and runs it over SSH; never run it anywhere else).
#   ci-vm-remote.sh ADO_ORG ADO_PROJECT ADO_REPO CLIENT_ID_SHARED CLIENT_ID_DEV CLIENT_ID_PROD
# with the Azure DevOps token on standard input. A client id of "none" means that
# deploy identity is not attached yet.
#
# Writes /opt/jenkins/secrets/ado-pat (the only stored secret) and, once,
# /opt/jenkins/secrets/admin-password (Dj's Jenkins password), both readable only by
# root and the jenkins user (uid 1000) and mounted read-only at /run/secrets; writes
# the non-secret settings to /opt/jenkins/jenkins.env; builds the image and recreates
# the container only when the image or those settings changed, never while a build runs.
# Before the first start with the job folders (Dj, 2026-10-02) it removes the old flat
# jobs "ocrinvoicing" (multibranch) and "ocrinvoicing-weekly-scan" and their workspaces
# (about 5 GB each) from jenkins_home, so
# the folder "ocrinvoicing" can take the name; their build history is lost. Jenkins shares the host network so it can reach the test databases
# the backend tests start through the Docker socket, and listens on 127.0.0.1:8080
# only (JENKINS_OPTS in the image). The socket makes Jenkins root-equivalent on this
# single-purpose, SSH-only VM (infra/bootstrap/README.md).

set -Eeuo pipefail

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

(($# == 6)) || die "usage: ci-vm-remote.sh ADO_ORG ADO_PROJECT ADO_REPO CLIENT_ID_SHARED CLIENT_ID_DEV CLIENT_ID_PROD < token"
((EUID == 0)) || die "run as root (sudo)"
ado_org="$1" ado_project="$2" ado_repo="$3" client_id_shared="$4" client_id_dev="$5" client_id_prod="$6"
[[ "$client_id_shared" == none ]] && client_id_shared=""
[[ "$client_id_dev" == none ]] && client_id_dev=""
[[ "$client_id_prod" == none ]] && client_id_prod=""
build_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly JENKINS_UID=1000 IMAGE=ocr-jenkins:local CONTAINER=jenkins
readonly BASE=/opt/jenkins SECRETS=/opt/jenkins/secrets

command -v docker >/dev/null || die "docker is not installed (cloud-init has not finished?)"
umask 077
install -d -m 0750 -o root -g "$JENKINS_UID" "$BASE" "$SECRETS"

# The token: from stdin, surrounding whitespace dropped, never echoed.
token="$(tr -d '[:space:]')"
[[ -n "$token" ]] || die "no Azure DevOps token on standard input"
printf '%s' "$token" >"$SECRETS/ado-pat.new"
unset token
install -m 0440 -o root -g "$JENKINS_UID" "$SECRETS/ado-pat.new" "$SECRETS/ado-pat"
rm -f "$SECRETS/ado-pat.new"

if [[ ! -s "$SECRETS/admin-password" ]]; then
  openssl rand -base64 24 | tr -d '\n' >"$SECRETS/admin-password"
  echo "generated the Jenkins password for user dj in $SECRETS/admin-password"
fi
chown root:"$JENKINS_UID" "$SECRETS/admin-password"
chmod 0440 "$SECRETS/admin-password"

cat >"$BASE/jenkins.env" <<EOF
ADO_ORG=$ado_org
ADO_PROJECT=$ado_project
ADO_REPO=$ado_repo
ADO_REPO_URL=https://dev.azure.com/$ado_org/$ado_project/_git/$ado_repo
DEPLOY_CLIENT_ID_SHARED=$client_id_shared
DEPLOY_CLIENT_ID_DEV=$client_id_dev
DEPLOY_CLIENT_ID_PROD=$client_id_prod
EOF
chmod 0644 "$BASE/jenkins.env"

docker build --pull -t "$IMAGE" "$build_dir"

# Recreate the container only when the image or its settings changed: a re-run must not
# kill a running deploy. The fingerprint covers the settings and both secret files.
image_id="$(docker image inspect -f '{{.Id}}' "$IMAGE")"
config="$(cat "$BASE/jenkins.env" "$SECRETS/ado-pat" "$SECRETS/admin-password" | sha256sum | cut -d' ' -f1)"
current="$(docker inspect -f '{{.Image}} {{index .Config.Labels "ocr.config"}} {{.State.Running}}' "$CONTAINER" 2>/dev/null || true)"
if [[ "$current" == "$image_id $config true" ]]; then
  echo "Jenkins is up to date and running (container $CONTAINER); nothing restarted."
  exit 0
fi
if [[ "$current" == "$image_id $config false" ]]; then
  docker start "$CONTAINER" >/dev/null
  echo "Jenkins started (container $CONTAINER, unchanged)."
  exit 0
fi
if [[ "$current" == *" true" ]]; then
  # A running shell step keeps a durable-task control folder next to its workspace.
  # Jobs in folders keep their workspaces one or more levels deeper.
  if docker exec "$CONTAINER" sh -c 'find /var/jenkins_home/workspace -maxdepth 5 -path "*@tmp/durable-*" | grep -q .'; then
    die "a Jenkins build is running; Jenkins was not restarted. Wait for it to finish (or stop it), then re-run ci-vm.sh."
  fi
fi
docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
# The old flat jobs, only while Jenkins is stopped and only if "ocrinvoicing" is still the
# multibranch project (once it is the folder, nothing is removed).
# shellcheck disable=SC2016  # expanded by the inner sh
docker run --rm --user root --entrypoint sh -v jenkins_home:/h "$IMAGE" -c '
  if grep -qs "<org.jenkinsci.plugins.workflow.multibranch.WorkflowMultiBranchProject" /h/jobs/ocrinvoicing/config.xml; then
    rm -rf /h/jobs/ocrinvoicing /h/jobs/ocrinvoicing-weekly-scan \
      /h/workspace/ocrinvoicing_* /h/workspace/ocrinvoicing-weekly-scan*
    echo "removed the old flat jobs ocrinvoicing and ocrinvoicing-weekly-scan and their workspaces (replaced by the ocrinvoicing folder)"
  fi'
docker run -d --name "$CONTAINER" --restart unless-stopped --network host \
  --label "ocr.config=$config" \
  --group-add "$(getent group docker | cut -d: -f3)" \
  -v jenkins_home:/var/jenkins_home \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$SECRETS":/run/secrets:ro \
  --env-file "$BASE/jenkins.env" \
  "$IMAGE" >/dev/null
echo "Jenkins is starting on 127.0.0.1:8080 (container $CONTAINER, image $IMAGE)."
