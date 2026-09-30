// Story 1.2 (spine AD-17): the pipeline of the multibranch job "ocrinvoicing"
// (ci/jenkins/casc.yaml). It only calls the ci/*.sh scripts, so every step also runs
// locally.
//
// Any branch other than main: the ci/checks.sh checks, with the result posted as a
// status on the branch's pull request into main (ci/ado-status.sh); the branch policy
// on main requires that status to merge.
//
// main: no checks (the pull request's branch build ran them on the same code, and the
// branch policy merges only a passed one), then the AD-17 order, each stack applied
// only from its own saved,
// tag-gated plan of this run:
//   shared/foundation (after Dj approves) -> dev/foundation -> Dev migrations
//   -> dev/app -> Dev code
// Dev applies automatically (terraform.md rules 26/33 exception). A step with nothing to
// do (hasWork=false) is skipped; a failed step stops the chain. There are no Prod
// stages: only the shared and Dev deploy identities are attached to the CI VM
// (Dj, 2026-09-29).

// The Terraform installation from the Jenkins Terraform plugin (casc.yaml).
TERRAFORM_TOOL = 'terraform-1.16.4'
// hasWork of each plan, read from the file the plan script writes (CI_OUTPUT_FILE).
HAS_WORK = [:]

// runStep ID SCRIPT - runs SCRIPT and returns its hasWork output (ci/lib.sh set_output).
def runStep(String id, String script) {
  def out = "${env.WORKSPACE}/.work/ci/outputs/${id}.env"
  sh "rm -f '${out}'"
  withEnv(["CI_OUTPUT_FILE=${out}"]) {
    sh script
  }
  return readFile(out).contains('hasWork=true')
}

// asDeployIdentity OWNER { ... } - runs the body signed in only as OWNER's deploy
// identity: `az login --identity` with its client id, and CI_MSI_CLIENT_ID for Terraform
// (ci/lib.sh export_arm_context). Each owner gets its own az profile in the workspace.
def asDeployIdentity(String owner, Closure body) {
  if (!(owner in ['shared', 'dev'])) {
    error("no deploy identity for '${owner}' on the CI VM (only shared and dev are attached)")
  }
  def name = "DEPLOY_CLIENT_ID_${owner.toUpperCase()}"
  // Named properties only: the script sandbox rejects env[name] (getAt with a computed key).
  def clientId = owner == 'shared' ? env.DEPLOY_CLIENT_ID_SHARED : env.DEPLOY_CLIENT_ID_DEV
  if (!clientId?.trim()) {
    error("${name} is not configured: attach ${owner}'s deploy identity to the CI VM and re-run its bootstrap (infra/bootstrap/README.md)")
  }
  withEnv([
    "CI_MSI_CLIENT_ID=${clientId}",
    "AZURE_CONFIG_DIR=${env.WORKSPACE}/.work/azure-${owner}",
    "PATH+TERRAFORM=${tool TERRAFORM_TOOL}",
  ]) {
    sh 'az login --identity --client-id "$CI_MSI_CLIENT_ID" --output none'
    body()
  }
}

// planStack ID STACK OWNER [OPTIONAL] - plan -out=tfplan and the P-17 tag gate; the saved
// plan goes to .work/ci/plans/ID for the apply stage of the same run.
def planStack(String id, String stack, String owner, boolean optional = false) {
  asDeployIdentity(owner) {
    HAS_WORK[id] = runStep(id, "ci/terraform-plan.sh ${stack} .work/ci/plans/${id}" + (optional ? ' --optional' : ''))
  }
}

// applyStack ID STACK OWNER - applies only the saved plan of planStack ID.
def applyStack(String id, String stack, String owner) {
  asDeployIdentity(owner) {
    sh "ci/terraform-apply.sh ${stack} .work/ci/plans/${id}/tfplan"
  }
}

// postStatus STATE - the result as a status on the branch's pull request.
def postStatus(String state) {
  withCredentials([usernamePassword(credentialsId: 'ado-pat', usernameVariable: 'ADO_PAT_USER', passwordVariable: 'ADO_PAT')]) {
    sh "ci/ado-status.sh ${state}"
  }
}

// postFinalStatus - the build's result on the pull request, once. A failed post fails the
// build without posting again.
def postFinalStatus() {
  def state = currentBuild.currentResult == 'SUCCESS' ? 'succeeded' : 'failed'
  try {
    postStatus(state)
  } catch (err) {
    echo "could not post '${state}' to the pull request: ${err}"
    currentBuild.result = 'FAILURE'
  }
}

// Saved plans and az profiles hold sensitive values: nothing outlives the run. Tolerates
// a missing workspace, .work or infra folder.
CLEANUP = 'rm -rf .work/ci/plans .work/azure-* || true; if [ -d infra ]; then find infra -name tfplan -type f -delete || true; fi'

pipeline {
  // No executor is held while the shared apply waits for Dj: each stage that runs
  // something takes its own agent, and the approval stage takes none.
  agent none
  options {
    // One run at a time per branch: deploys on main never overlap.
    disableConcurrentBuilds()
    buildDiscarder(logRotator(numToKeepStr: '30'))
  }
  environment {
    // "Running in CI": ci/checks.sh, the backend tests and the Playwright configs read it.
    TF_BUILD = 'true'
    // Providers are downloaded once into jenkins_home and reused by every init (checks
    // and plans), instead of each build downloading them again. Terraform still checks
    // each one against the committed lock files.
    TF_PLUGIN_CACHE_DIR = '/var/jenkins_home/.terraform.d/plugin-cache'
    // The modules' own inits have no committed lock file to take checksums from.
    TF_PLUGIN_CACHE_MAY_BREAK_DEPENDENCY_LOCK_FILE = 'true'
  }
  stages {
    stage('Checks') {
      agent any
      // main: the pull request's branch build already ran every check on this code, and
      // the branch policy on main only merges a passed one, so main goes straight to the
      // deploy chain (Dj, 2026-09-30: checks took over 12 minutes on every build).
      when { not { branch 'main' } }
      stages {
        stage('PR status: pending') {
          steps { postStatus('pending') }
        }
        // Every check runs, even after one fails, so a build reports them all. terraform
        // shares nothing with the app checks, so it runs beside them; lint installs the
        // web dependencies that test uses, so those stay in order.
        stage('Checks in parallel') {
          parallel {
            stage('app') {
              stages {
                stage('lint') {
                  steps { catchError(buildResult: 'FAILURE', stageResult: 'FAILURE') { sh 'ci/checks.sh lint' } }
                }
                stage('test') {
                  steps { catchError(buildResult: 'FAILURE', stageResult: 'FAILURE') { sh 'ci/checks.sh test' } }
                }
                stage('audit') {
                  steps { catchError(buildResult: 'FAILURE', stageResult: 'FAILURE') { sh 'ci/checks.sh audit' } }
                }
                stage('secrets') {
                  steps { catchError(buildResult: 'FAILURE', stageResult: 'FAILURE') { sh 'ci/checks.sh secrets' } }
                }
              }
            }
            stage('terraform') {
              steps { catchError(buildResult: 'FAILURE', stageResult: 'FAILURE') { sh 'ci/checks.sh terraform' } }
            }
          }
        }
      }
      post {
        always {
          archiveArtifacts(artifacts: '.work/ci/test-results/*.xml, .work/ci/coverage/**/*.xml', allowEmptyArchive: true)
          sh CLEANUP
          // Branch builds end here, so this is their result.
          script { if (env.BRANCH_NAME != 'main') { postFinalStatus() } }
        }
        // A branch workspace holds about 5 GB (dependencies, virtualenvs, providers), and
        // the backend tests' PostgreSQL containers leave anonymous volumes behind; kept,
        // they filled the VM's 61 GB disk (2026-09-30). Only volumes no container uses
        // are pruned, never jenkins_home. The shared caches stay in jenkins_home.
        cleanup {
          deleteDir()
          sh 'docker volume prune --force || true'
        }
      }
    }

    stage('Deploy (AD-17)') {
      when {
        allOf {
          branch 'main'
          expression { currentBuild.currentResult == 'SUCCESS' }
        }
      }
      stages {
        stage('Plan shared/foundation') {
          agent any
          steps { script { planStack('shared_foundation', 'shared/foundation', 'shared') } }
        }
        stage('Approve shared/foundation') {
          when {
            beforeInput true
            expression { HAS_WORK.shared_foundation }
          }
          options { timeout(time: 24, unit: 'HOURS') }
          input {
            message 'Apply the saved plan of shared/foundation? Review it in the "Plan shared/foundation" log first (terraform.md rule 26).'
            ok 'Apply'
            submitter 'dj'
          }
          steps { echo 'Dj approved the shared/foundation plan.' }
        }
        stage('Apply shared, then Dev') {
          agent any
          stages {
            stage('Apply shared/foundation') {
              when { expression { HAS_WORK.shared_foundation } }
              steps { script { applyStack('shared_foundation', 'shared/foundation', 'shared') } }
            }
            stage('Plan dev/foundation') {
              steps { script { planStack('dev_foundation', 'dev/foundation', 'dev') } }
            }
            stage('Apply dev/foundation') {
              when { expression { HAS_WORK.dev_foundation } }
              steps { script { applyStack('dev_foundation', 'dev/foundation', 'dev') } }
            }
            stage('Migrate dev') {
              steps {
                script {
                  if (runStep('dev_migrate', 'ci/migrate.sh --check dev')) {
                    asDeployIdentity('dev') { sh 'ci/migrate.sh dev' }
                  }
                }
              }
            }
            stage('Plan dev/app') {
              steps { script { planStack('dev_app', 'dev/app', 'dev', true) } }
            }
            stage('Apply dev/app') {
              when { expression { HAS_WORK.dev_app } }
              steps { script { applyStack('dev_app', 'dev/app', 'dev') } }
            }
            stage('Deploy code dev') {
              steps {
                script {
                  if (runStep('dev_code', 'ci/code-deploy.sh --check dev')) {
                    asDeployIdentity('dev') { sh 'ci/code-deploy.sh dev' }
                  }
                }
              }
            }
          }
        }
      }
    }
  }
  post {
    // A rejected or timed-out approval, or a failed step, can leave a saved plan behind.
    always {
      script {
        if (env.BRANCH_NAME == 'main') {
          node('built-in') { sh CLEANUP }
        }
      }
    }
  }
}
