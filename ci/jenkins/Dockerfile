# syntax=docker/dockerfile:1
#
# Story 1.2 (spine AD-17): the Jenkins controller that runs all CI/CD on the CI VM.
# infra/bootstrap/ci-vm.sh builds it there and starts it (docker.sock mounted, Jenkins on
# 127.0.0.1:8080 only). Jenkins LTS, the pinned plugins (plugins.txt), the configuration
# (casc.yaml) and the pinned tools that ci/checks.sh and the deploy scripts call.
#
# Tool versions and SHA-256 sums match ci/lib.sh (ci/tests/test_jenkins.py checks that
# they do; the build context is this folder, so ci/lib.sh can't be read here). The deploy
# stages take Terraform through the Jenkins Terraform plugin, whose tool home is this
# checksum-verified copy (casc.yaml). The VM is amd64, hence the platform.
FROM --platform=linux/amd64 jenkins/jenkins:2.568.3-lts-jdk21@sha256:c1e4c349365f6d16d88595b2c5f7e8ff39b8ae1d061f62420bac193b4b9616d0

ARG TERRAFORM_VERSION=1.16.4
ARG TERRAFORM_SHA256=dc94af0eef1147718ad7c8daea792ed199e3e0492eec180d0adafa2a65a879df
ARG GITLEAKS_VERSION=8.30.1
ARG GITLEAKS_SHA256=551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb
ARG UV_VERSION=0.11.8
ARG UV_SHA256=56dd1b66701ecb62fe896abb919444e4b83c5e8645cca953e6ddd496ff8a0feb
ARG NODE_VERSION=22.23.3
ARG NODE_SHA256=df450af89261115ef9f9e3830c3eeb2cc9213b63c720b1af623cb5dcbe2e02de
ARG SHELLCHECK_VERSION=0.11.0
ARG SHELLCHECK_SHA256=8c3be12b05d5c177a04c29e3c78ce89ac86f1595681cab149b65b97c4e227198
ARG DOCKER_CLI_VERSION=29.8.1
ARG DOCKER_CLI_SHA256=d8db66739d2e28d4933786d73e918d9be643a67fbd835db1bf740d650a259e70
ARG AZURE_CLI_VERSION=2.90.0
# The Playwright version web/supplier and web/staff pin: its Chromium system libraries.
ARG PLAYWRIGHT_VERSION=1.63.0

USER root
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Python 3.13 is Debian 13's python3 (backend requires-python ==3.13.*; uv uses it and
# never downloads another). git and zip tools for the scripts; openssh-client for git.
RUN apt-get update \
  && apt-get install -y --no-install-recommends \
    ca-certificates curl git openssh-client python3 python3-venv unzip xz-utils \
  && rm -rf /var/lib/apt/lists/*

# Every download is checked against its pinned SHA-256 before use.
RUN fetch() { \
      curl --fail --silent --show-error --location --retry 3 --output "$3" "$1" \
        && printf '%s  %s\n' "$2" "$3" | sha256sum --check --strict -; \
    } \
  && cd /tmp \
  && fetch "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_amd64.zip" \
    "$TERRAFORM_SHA256" terraform.zip \
  && unzip -q terraform.zip terraform -d /usr/local/bin \
  && fetch "https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION}_linux_x64.tar.gz" \
    "$GITLEAKS_SHA256" gitleaks.tar.gz \
  && tar -xzf gitleaks.tar.gz -C /usr/local/bin gitleaks \
  && fetch "https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/uv-x86_64-unknown-linux-gnu.tar.gz" \
    "$UV_SHA256" uv.tar.gz \
  && tar -xzf uv.tar.gz -C /usr/local/bin --strip-components=1 \
    uv-x86_64-unknown-linux-gnu/uv uv-x86_64-unknown-linux-gnu/uvx \
  && fetch "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-x64.tar.xz" \
    "$NODE_SHA256" node.tar.xz \
  && tar -xJf node.tar.xz -C /usr/local --strip-components=1 --no-same-owner \
    --exclude='*/CHANGELOG.md' --exclude='*/LICENSE' --exclude='*/README.md' \
  && fetch "https://github.com/koalaman/shellcheck/releases/download/v${SHELLCHECK_VERSION}/shellcheck-v${SHELLCHECK_VERSION}.linux.x86_64.tar.xz" \
    "$SHELLCHECK_SHA256" shellcheck.tar.xz \
  && tar -xJf shellcheck.tar.xz -C /usr/local/bin --strip-components=1 "shellcheck-v${SHELLCHECK_VERSION}/shellcheck" \
  && fetch "https://download.docker.com/linux/static/stable/x86_64/docker-${DOCKER_CLI_VERSION}.tgz" \
    "$DOCKER_CLI_SHA256" docker.tgz \
  && tar -xzf docker.tgz -C /usr/local/bin --strip-components=1 docker/docker \
  && rm -rf /tmp/*

# uv uses Debian's Python 3.13 and never downloads one (reproducible, no surprise version).
ENV UV_PYTHON_DOWNLOADS=never

# az CLI, pinned, in its own virtual environment (Microsoft's apt repository has no
# Debian 13 build). pip, not uv: azure-cli pins some dependencies to pre-releases.
RUN python3 -m venv /opt/azure-cli \
  && /opt/azure-cli/bin/pip install --no-cache-dir --disable-pip-version-check "azure-cli==${AZURE_CLI_VERSION}" \
  && ln -s /opt/azure-cli/bin/az /usr/local/bin/az

# Chromium's system libraries and the browser for the a11y check (ci/checks.sh test). The
# jenkins user can't install packages, so they are baked in; a later Playwright pin adds
# its own browser to the same folder at run time.
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright
RUN npx --yes "playwright@${PLAYWRIGHT_VERSION}" install --with-deps chromium \
  && chown -R jenkins:jenkins "$PLAYWRIGHT_BROWSERS_PATH" \
  && rm -rf /var/lib/apt/lists/* /root/.npm

# Plugins, every one pinned (plugins.txt lists the whole resolved set).
COPY plugins.txt /usr/share/jenkins/ref/plugins.txt
RUN jenkins-plugin-cli --plugin-file /usr/share/jenkins/ref/plugins.txt --latest false

# Configuration as code; secrets come from files mounted at /run/secrets (casc.yaml).
COPY casc.yaml /usr/share/jenkins/casc/casc.yaml
ENV CASC_JENKINS_CONFIG=/usr/share/jenkins/casc/casc.yaml \
    JAVA_OPTS="-Djenkins.install.runSetupWizard=false" \
    JENKINS_OPTS="--httpListenAddress=127.0.0.1 --httpPort=8080"

USER jenkins
