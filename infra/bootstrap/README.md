# Bootstrap and operator steps (spine AD-17)

These scripts are the out-of-band steps of AD-17 (terraform.md rule 29). An operator runs them from a shell signed in with `az login`. They never run in the pipeline (Jenkins on the CI VM).

Every script:

- is idempotent: a re-run skips what exists and re-applies settings and tags;
- stops before any change when a required input is missing, naming the variable (exit 1);
- names the failed step on error (`set -Eeuo pipefail`);
- supports `--dry-run`, which prints every planned `az`/`psql`/`gpg` call without calling Azure (lookups are skipped and treated as "absent"), and `--help`;
- runs on macOS's bash 3.2 as well as bash 5.

No script or committed file holds a secret, subscription id or tenant id. Pass them as environment variables.

## Inputs

| Variable | Used by | Meaning |
| --- | --- | --- |
| `ARM_SUBSCRIPTION_ID` | all but `app-registrations.sh`, `verify-db-isolation.sh` | target subscription |
| `ARM_TENANT_ID` | `app-registrations.sh` | Entra tenant; `az` must be signed in to it |
| `TAG_OWNER`, `TAG_COST_CENTRE`, `TAG_APPLICATION`, `TAG_DATA_CLASSIFICATION` | `state-backend.sh`, `ci-vm.sh` | P-17 tag values (use the same values as the stacks' `terraform.tfvars`) |
| `ADO_ORG`, `ADO_PROJECT` | `ci-vm.sh` | Azure DevOps organisation and project (`example-org`, `ocrinvoicing`): the repository Jenkins polls |
| `ADO_REPO` | `ci-vm.sh` (optional) | Azure Repos repository; default `ADO_PROJECT` |
| `ADO_PAT_FILE` | `ci-vm.sh` (optional) | the Azure DevOps personal access token file; default `.work/ado-pat` (gitignored). It is copied to the VM on ssh's standard input and is never printed |
| `CI_SSH_SOURCE_IP` | `ci-vm.sh` | the operator's public IPv4 address, the only source the NSG lets in (SSH only) |
| `CI_SSH_PUBLIC_KEY_FILE` | `ci-vm.sh` | the operator's SSH public key for the VM's `ciadmin` user; the private key is the same path without `.pub` (or the ssh agent's) |
| `STACKS` | `test-alerts.sh` (optional) | which action groups to test; default `shared dev prod`; repeats are ignored |
| `ENVIRONMENT` | `pgp-step4b.sh`, `database-step5.sh` | `dev` or `prod` |
| `PG_ADMIN_USER` | `database-step5.sh`, `verify-db-isolation.sh` | the PostgreSQL Entra admin used to connect: the pg-admins group's name, `babaloo-sea-lng-grp-21`, signed in with a member's token. Required, and it must not be the environment's loaders group (the load-script login): the load script never runs as server admin. `database-step5.sh` stops if the two are equal |
| `CONNECT_AS_LOGIN`, `TARGET_DB` | `verify-db-isolation.sh` (mode 2) | a real connection attempt that must be refused |

## Names

| What | Name |
| --- | --- |
| Resource groups | `babaloo-sea-lng-rg-21` (shared stack), `-rg-01` (dev), `-rg-11` (prod), `-rg-22` (bootstrap-only: state and deploy identities) and `-rg-23` (bootstrap-only: the CI VM) |
| State storage | Dj's existing `stdjtfstatesea` in `rg-tfstate-sea` (Dj, 2026-09-30: not created or changed by these scripts); containers `ocrinvoicing-shared`, `ocrinvoicing-dev`, `ocrinvoicing-prod`; key `foundation.tfstate` per stack, and `app.tfstate` for dev and prod |
| Deploy identities | `babaloo-sea-lng-id-21` (shared), `-id-22` (dev), `-id-23` (prod), all in `rg-22` |
| Private-key vaults (OCR-129) | `babaloo-sea-lng-kv-22` (dev), `-kv-23` (prod), in `rg-22`; each holds only its environment's `pgp-private-key`; no diagnostic settings, by decision (Dj, 2026-09-29) |
| App registrations | `babaloo-sea-lng-staff-api-<env>`, `babaloo-sea-lng-accounts-sim-<env>` |
| Entra security groups (`grp`) | loaders `babaloo-sea-lng-grp-01` (dev), `-grp-11` (prod): the supplier load script's database login; pg-admins `babaloo-sea-lng-grp-21` (shared): the PostgreSQL Entra admin. Dj is a member of all three (Dj, 2026-09-29: his guest UPN is over PostgreSQL's 63-character role-name limit and holds `#`) |
| CI VM (`rg-23`) | `babaloo-sea-lng-vm-21` (Ubuntu 24.04 LTS, B2s), `-vnet-21`/`-snet-21`, `-nsg-21`, `-pip-21`, `-nic-21`, `-osdisk-21` |
| Action groups (all email Dj) | `babaloo-sea-lng-ag-21` (shared: the `shared` budget), `-ag-01` (dev), `-ag-11` (prod) |

`rg-22` is created and managed only by these scripts. No Terraform stack manages it, no deploy identity holds any role on it, and no identity's RBAC Administrator reaches it. The state account's group `rg-tfstate-sea` is likewise outside every stack: each deploy identity holds only its container-scoped state roles in it. So no stack's identity can change another identity or another stack's state through Azure RBAC, or read or grant access to a PGP private key. On the CI VM, though, any build can use both the shared and Dev identities (below), so this separation holds between Prod and the rest, not between shared and Dev.

The Entra groups are not Azure resources: `app-registrations.sh` creates them, `infra/bootstrap/lib.sh` names them (`loaders_group_name`, `pg_admins_group_name`) and `infra/modules/naming` does not. A member signs in to PostgreSQL with the group's name as the user name and their own Entra token.

## Before deploying Story 1.6 (environments already set up)

Migration `0004_master_audit` needs `pgcrypto` and grants to the environment's loaders group (Dj's load-script login), so on an environment whose step 5 ran before Story 1.6, in this order:

1. Re-run `./app-registrations.sh`. It creates the loaders groups (`grp-01`, `grp-11`) and the pg-admins group (`grp-21`), adds you to each, and prints the pg-admins group's object id and name.
2. If the PostgreSQL Entra admin is still a user, make it the pg-admins group: set `postgres_entra_admin_object_id`, `postgres_entra_admin_principal_name` and `postgres_entra_admin_principal_type = "Group"` in `infra/shared/foundation/terraform.tfvars` as printed, and let the Jenkins deploy chain apply `shared/foundation`.
3. Re-run step 5 for both environments, connected as the pg-admins group: `ENVIRONMENT=dev ./database-step5.sh`, then `ENVIRONMENT=prod ./database-step5.sh`. It is idempotent; the new parts create the loaders group's login and rights and `pgcrypto` in `invoicing_<env>`.
4. Merge. The Dev migration stage then applies `0004_master_audit` (Prod waits for its own deploy decision, below). It needs no variable: `ci/migrate.sh` takes the loaders group's name from `lib.sh`.

## Run order

| AD-17 step | Who | What to run |
| --- | --- | --- |
| 1 | operator with Owner | `./state-backend.sh`, then `./app-registrations.sh`, then `./budget-and-roles.sh` |
| 1b | operator | push the code to Azure Repos (below) |
| 1c | operator with Owner | `./ci-vm.sh` (after `state-backend.sh`, which creates the deploy identities it attaches), then the Jenkins first run and the branch policy (below). Every later merge to `main` starts the deploy chain |
| 2 | `shared` deploy identity (Jenkins) | `infra/shared/foundation`: fill `terraform.tfvars`; Jenkins plans it, Dj approves the `Approve shared/foundation` input, it applies the saved plan |
| 3 | operator | `./rbac-step3.sh` |
| 4 | env deploy identity (Jenkins) | `infra/dev/foundation` (applies automatically). Prod has no Jenkins stage: its deploy identity is not on the CI VM, and how Prod deploys is a later decision (Dj, 2026-09-29) |
| 4b | operator with Owner, plus Key Vault Secrets Officer on both vaults for this step only | after `<env>/foundation` exists (it creates the `staff-api` identity): `ENVIRONMENT=dev ./pgp-step4b.sh`, then, after `prod/foundation`, `ENVIRONMENT=prod ./pgp-step4b.sh` |
| 5 | operator as PostgreSQL Entra admin (a member of the pg-admins group `grp-21`) | `ENVIRONMENT=dev ./database-step5.sh`, then prod; then `./verify-db-isolation.sh` |
| 6, 7, 9 | Jenkins | Dev migrations, `dev/app`, Dev code deploy (the `Jenkinsfile` at the repository root) |
| 8 | operator | `staff-api` redirect URI, then the sign-in check (Story 2.7, below) |
| Purchasing seed | operator, signed in as the env deploy identity | after the environment's migrations: the synthetic PO and goods-received data (below) |
| Supplier load | Dj, signed in as himself, connecting as the environment's loaders group (`grp-01` dev, `grp-11` prod) | after step 4b, step 5, the environment's migrations and `<env>/app`: the synthetic suppliers and their upload links (below) |
| Alert check | operator | `./test-alerts.sh` once the stacks are applied, then check that Dj received every test email (below) |
| Pipeline check | operator | after the first Dev code deploy: the metric namespace and the stopped-database wait (below) |

Try each script with `--dry-run` first.

### Step 1: state, groups, identities, app registrations, role

- `state-backend.sh` registers the resource providers and waits for each (the `azurerm` provider has `resource_provider_registrations = "none"`), creates the four tagged resource groups, checks that the existing state account `stdjtfstatesea` has shared-key access off and versioning on (it stops otherwise, and never changes the account), creates this project's three containers there, the two private-key vaults `kv-22` (dev) and `kv-23` (prod) in `rg-22` (RBAC mode, purge protection, 7-day soft delete, public network access like the environment vaults, the five tags with `environment` set to their environment; an existing vault has these settings and its tags re-applied, and nobody gets a role on it), and the three deploy identities. They have no federated credentials: the CI VM carries the shared and Dev ones as user-assigned managed identities (step 1c; Dj, 2026-09-29). If an earlier run made `ado-<owner>` credentials, delete them: `az identity federated-credential delete --name ado-<owner> --identity-name <identity> --resource-group babaloo-sea-lng-rg-22`.
- Deploy identity rights (azure.md rule 31 and AD-17 "Deploy identity rights"):
  - every deploy identity: Contributor on its own stack's resource group (`rg-21`, `rg-01` or `rg-11`, never `rg-22`), and Storage Blob Data Contributor on its own state container (`ocrinvoicing-<owner>`, scoped to the container, never the account);
  - `dev` and `prod` also: Role Based Access Control Administrator on their resource group, conditioned to assigning or removing only the runtime roles (Storage Blob Data Contributor/Owner, Storage Queue Data Contributor/Message Sender, Storage Table Data Contributor, Key Vault Secrets User/Officer, Monitoring Metrics Publisher) and only to service principals; and Storage Blob Data Reader on the `ocrinvoicing-shared` state container.
- `app-registrations.sh` creates, per environment, `staff-api` (single tenant, app roles `admin`, `finance`, `procurement`, `management`, `goods_in`, ID tokens on, "assignment required" on its service principal, no secret) and `accounts-sim` (single tenant, identifier URI `api://<appId>`). It prints the client ids that `<env>/app` needs: put the `staff-api` one in `infra/<env>/app/terraform.tfvars` as `staff_api_client_id` (Story 2.7) and the `accounts-sim` one as `accounts_sim_client_id` (Story 3.1: its built-in auth accepts tokens for `api://<client id>` from the environment's `pipeline` identity only), before `<env>/app` is planned. Neither is a secret. The redirect URI is step 8.
- `app-registrations.sh` also creates the Entra security groups used as PostgreSQL logins (Dj, 2026-09-29: his guest UPN is over PostgreSQL's 63-character role-name limit), and adds the signed-in operator (`az ad signed-in-user show`) as a member of each: the loaders groups `babaloo-sea-lng-grp-01` (dev) and `-grp-11` (prod), the supplier load script's login, and the pg-admins group `babaloo-sea-lng-grp-21`, the PostgreSQL Entra admin. An existing group is kept, and an existing member is not re-added. It prints the pg-admins group's object id and name: before `shared/foundation` is first applied, put them in `infra/shared/foundation/terraform.tfvars` as `postgres_entra_admin_object_id` and `postgres_entra_admin_principal_name`, with `postgres_entra_admin_principal_type = "Group"`. Creating groups and adding members needs Entra rights, not just Owner on the subscription: an Entra role such as Groups Administrator (or Global Administrator), or, for an existing group, being its owner. The creator of a group is its owner. A new member's Azure sign-in picks up the group after `az login` is run again.
- `budget-and-roles.sh` creates the custom role `ACS Email Sender` (`Microsoft.Communication/CommunicationServices/Read` and `Microsoft.Communication/EmailServices/write`; the exact minimum is an open question in the spine; assigned to the pipelines by `<env>/app` once ACS exists, Story 5.2). There is no subscription budget (Dj, 2026-09-30: dropped, the subscription holds other projects; the resource-group budgets track this project). A `babaloo-sea-lng-budget-22` made by an earlier run can be deleted: `az consumption budget delete --budget-name babaloo-sea-lng-budget-22`.

### Step 1b: push the code to Azure Repos

The code and the Terraform modules live in Azure Repos (`example-org/ocrinvoicing`); Jenkins polls it. Create a personal access token in Azure DevOps (User settings > Personal access tokens) with the scopes **Code: Read & write** and **Code: Status**, and save it, alone, in `.work/ado-pat` (gitignored; `chmod 600`). Read & write is for this push; Jenkins itself needs only Code Read and Code Status. Then:

```sh
git remote add azure https://dev.azure.com/example-org/ocrinvoicing/_git/ocrinvoicing
GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=http.extraHeader \
  GIT_CONFIG_VALUE_0="Authorization: Basic $(printf ':%s' "$(cat .work/ado-pat)" | base64)" \
  git -c credential.helper= push azure main
```

The token goes to git through environment variables, never on a command line (where `ps` would show it).

The token has an expiry: when it lapses, create a new one, save it in `.work/ado-pat` and re-run `ci-vm.sh`, which replaces the one Jenkins uses.

### Step 1c: the CI VM and Jenkins

`ci-vm.sh` (operator with Owner, `az` signed in; needs `ssh` and `scp`) creates or updates, in the tagged `rg-23`:

- a VNet and subnet, and the NSG `nsg-21`, on the subnet and the NIC, whose only inbound rule allows SSH (22) from `CI_SSH_SOURCE_IP`/32. Azure's default rules deny every other inbound connection, so there is no web port: Jenkins is reached only through an SSH tunnel;
- a static public IP and the VM `vm-21`: Ubuntu 24.04 LTS, `Standard_B2s` (2 vCPU, 4 GB), SSH key only (user `ciadmin`), no auto-shutdown for now (Dj deallocates it when not in use: `az vm deallocate --name babaloo-sea-lng-vm-21 --resource-group babaloo-sea-lng-rg-23`; a schedule comes later). Cloud-init (`ci-vm-cloud-init.yaml`) installs Docker and keeps Ubuntu's unattended security upgrades on;
- the shared and Dev deploy identities (`id-21`, `id-22`) attached as user-assigned managed identities, and never Prod's (`id-23`; if it is ever attached, a re-run takes it off). An identity that does not exist yet is skipped with a warning; run `state-backend.sh` and re-run `ci-vm.sh` to attach it;
- over SSH, `ci-vm-remote.sh` on the VM: it stores the token as `/opt/jenkins/secrets/ado-pat`, generates Dj's Jenkins password once (`/opt/jenkins/secrets/admin-password`), both readable only by root and the Jenkins user; writes the non-secret settings (repository, the two identities' client ids) to `/opt/jenkins/jenkins.env`; builds the image from `ci/jenkins/` and (re)starts the `jenkins` container with `jenkins_home` on a named volume.

A re-run creates nothing that exists, starts the VM if it is deallocated, re-applies the SSH rule (for a new IP, set `CI_SSH_SOURCE_IP` and re-run), tags and identities, and rebuilds the image. It recreates the Jenkins container only when the image or its settings changed, and refuses to while a build is running (wait, or stop the build, then re-run); jobs and history survive in the volume.

What runs on the VM:

- **Jenkins** (`ci/jenkins/Dockerfile`): Jenkins LTS pinned by digest, the plugins pinned in `plugins.txt`, and the build tools pinned with checksums (Terraform, gitleaks, uv, Node 22, shellcheck, the az CLI, the Docker CLI, Python 3.13, Playwright's Chromium). `casc.yaml` configures everything at each start: the local user `dj`, the Terraform tool (the Jenkins Terraform plugin, pointed at the image's checksum-verified Terraform, same version as `ci/lib.sh`; nothing is downloaded), the `ado-pat` credential read from the mounted secret file, the client ids as global variables, and the jobs.
- **Network**: the container shares the host network and Jenkins listens on `127.0.0.1:8080` only. Nothing listens on a public port.
- **Docker socket**: the container gets `/var/run/docker.sock`, so the backend tests can start their PostgreSQL containers. That makes Jenkins root-equivalent on the VM, which is accepted for a single-purpose, SSH-only VM (Dj, 2026-09-29).
- **Identities**: no Azure secret is stored anywhere; each deploy stage signs in as its own stack owner's identity (`az login --identity --client-id`, Terraform through `ARM_USE_MSI`). But both identities are on the VM, and every branch build runs that branch's own `Jenkinsfile` and test code there. So code in any pushed branch can get a token for the shared or Dev identity and change `shared` without Dj's approval: the approval and the per-stage sign-in only guard against mistakes, not against a hostile branch. Dj accepted this for the PoC because only Dj and Claude push (the `azure.md` rule 31 exceptions, Dj 2026-09-30); it must be closed before anyone else gets push access or before Prod.
- **Capacity**: a B2s has 4 GB of memory and Jenkins runs two executors, so two builds at once (each with Node, pytest and a PostgreSQL container) can run out of memory. Deploy stages hold no executor while waiting for Dj's approval.
- **No backup**: `jenkins_home` is a Docker volume on the VM's disk with no backup. Everything in it can be rebuilt (`casc.yaml` recreates the configuration and jobs); only build history is lost.

Jenkins first run:

1. Open the tunnel: `ssh -N -L 8080:127.0.0.1:8080 ciadmin@<public IP>` (`ci-vm.sh` prints it), then browse to `http://127.0.0.1:8080`.
2. Sign in as `dj` with the password from `ssh ciadmin@<public IP> sudo cat /opt/jenkins/secrets/admin-password`. Don't change it in the UI: `casc.yaml` sets it from that file at each start. To change it, edit `/opt/jenkins/secrets/admin-password` on the VM (`sudo`), then re-run `ci-vm.sh` (or `sudo docker restart jenkins`).
3. Check the jobs: `ocrinvoicing` (multibranch; scans Azure Repos every 5 minutes and builds each branch with the root `Jenkinsfile`) and `ocrinvoicing-weekly-scan` (`ci/checks.sh audit` on `main`, Mondays 01:00 UTC). Start a scan of `ocrinvoicing` by hand the first time.
4. **Branch policy** (Azure DevOps, Project settings > Repositories > `ocrinvoicing` > Policies > branch `main`): require a pull request, and add a **Status check** policy for the status `jenkins/checks`, required, reset on source update. Jenkins posts it on the latest pull request iteration of the commit it built (`ci/ado-status.sh`), so a failing or missing build blocks the merge.
   - A branch built before its pull request existed has posted no status: after opening the pull request, click **Build Now** on that branch in the `ocrinvoicing` job.
   - A status stuck on `pending` (a build that died before posting its result): rebuild the branch (**Build Now**); the new build posts over it.
5. **Weekly scan alerts**: a failed scheduled run notifies nobody. Look at the job after each Monday, or add a mail server later.

What the jobs do:

- **Every branch other than `main`**: `ci/checks.sh lint`, `test`, `audit`, `secrets` and `terraform` (all run even when one fails), and the result posted to the branch's pull request into `main`. A failed status post fails the build. Run `ci/checks.sh all` locally for the same result.
- **`main`** (one run at a time): the checks, then the AD-17 chain. Each stack is planned (`plan -out=tfplan`, then `check_tags.py` on `terraform show -json`) and, only when the plan has changes, applied from that saved plan in the same workspace. Order: `shared/foundation` (Dj approves the `input`, 24 hours at most; the wait holds no executor), `dev/foundation`, Dev migrations, `dev/app`, Dev code deploy. Dev applies without approval (the recorded terraform.md rule 26/33 exception). A failed or rejected step stops everything after it. Saved plans and az profiles are deleted at the end of every run.
- **Migrations** (`ci/migrate.sh`): `alembic upgrade head` as the environment's deploy identity with an Entra token, straight to the server (the PoC firewall is open, so no temporary rule); skipped with "no migrations" until `backend/migrations/env.py` exists. From Story 1.6 the migrations also grant `master` and `audit` to the environment's loaders group (Dj's load-script login), whose name `ci/migrate.sh` takes from `lib.sh`, like the other logins.
- **Weekly scan**: `ci/checks.sh audit` on `main` every Monday, failing on any finding.

### Step 2: no email domain needed

Step 2 needs no email domain. ACS Email (Story 5.2, AD-16) is in `shared/foundation`, but with `email_custom_domain` empty (the default) nothing of it is created, no `ACS Email Sender` role is assigned and no alert email is sent. Turning it on is the separate "Email domain" step below.

### Email domain: staff alert emails (Story 5.2, once, when Dj is ready)

Staff alert emails (price rises and watchlist listings, AD-16) go out only from a custom domain Dj owns. In order:

1. In `infra/shared/foundation/terraform.tfvars`, set `email_custom_domain` (e.g. `alerts.example.com`, a domain or subdomain Dj controls DNS for). Leave `email_domain_link_enabled` unset (`false`).
2. Apply `shared/foundation` (plan, Dj approves, apply). It creates the Communication Services resource (`babaloo-sea-lng-acs-21`, access keys off, data in "Asia Pacific"), the Email Communication Service (`babaloo-sea-lng-ecs-21`) and the customer-managed domain. Nothing is linked, no sender exists, and `<env>/app` still assigns no ACS role.
3. Re-run `rbac-step3.sh` (step 3): now that ACS exists, it also gives each environment's deploy identity RBAC Administrator on ACS, conditioned to assigning only `ACS Email Sender`. This must happen before step 7, whose deploy chain assigns that role.
4. Read the DNS records: `terraform -chdir=infra/shared/foundation output -json email_domain_verification_records` (Domain TXT, SPF TXT, DKIM and DKIM2 CNAMEs, DMARC). Add each at the domain's registrar by hand.
5. Start verification, once per record type, and wait until each shows `Verified` (DNS can take up to a day):

   ```sh
   domain_id="/subscriptions/$ARM_SUBSCRIPTION_ID/resourceGroups/babaloo-sea-lng-rg-21/providers/Microsoft.Communication/emailServices/babaloo-sea-lng-ecs-21/domains/<email_custom_domain>"
   for type in Domain SPF DKIM DKIM2; do
     az rest --method post --url "https://management.azure.com$domain_id/initiateVerification?api-version=2023-03-31" --body "{\"verificationType\": \"$type\"}"
   done
   az rest --method get --url "https://management.azure.com$domain_id?api-version=2023-03-31" --query properties.verificationStates
   ```

6. Make `alerts@<email_custom_domain>` receivable: every alert email is addressed to it as the only To (staff are in Bcc), so without a mailbox or an MX record for the domain each send also bounces back to it.
7. Set `email_domain_link_enabled = true` in the same `terraform.tfvars`, and set the app settings: in `infra/dev/app/terraform.tfvars` (and Prod's) set `alert_recipients_finance`, `alert_recipients_procurement` and `alert_recipients_management` (lists of addresses; empty means nobody). Apply `shared/foundation` (it links the domain and creates the sender `alerts@<email_custom_domain>`), then `<env>/foundation` and `<env>/app`: the pipeline gets `ACS Email Sender` on ACS and `EMAIL_ACS_ENDPOINT`, `EMAIL_SENDER_ADDRESS`, `STAFF_APP_BASE_URL` and `ALERT_RECIPIENTS_*`. Alerts not yet emailed go out at the next analytics refresh (alerts from before the first summaries run were stored already marked emailed), throttled to 5 a minute and 20 an hour in Dev, 25 and 80 in Prod. Alerts created more than 14 days before that run are marked emailed without a send. The first run after switch-on may log `email.failed` (403) while the new role assignment propagates; the alerts stay pending and go at the next run.
8. Check that the custom role `ACS Email Sender` really allows a send before relying on it (the spine still lists its exact actions as open): watch the first analytics refresh's logs for `email.sent`; `email.failed code=HttpResponseError` on every alert means the role's actions are not enough. Fix the role in `budget-and-roles.sh` (or, as a last resort, assign Communication and Email Service Owner by hand) and wait for the next run.

To turn emails off again, empty the recipient lists (nobody is mailed; the alerts stay pending) or set `email_domain_link_enabled = false` (the sender address and the pipeline's ACS role go, so nothing is sent). Either way the change only reaches the pipeline once `shared/foundation`, then `<env>/foundation`, then `<env>/app` are re-applied, in that order, for each environment.

### Step 3: conditioned RBAC Administrator on the shared DI

`rbac-step3.sh` gives each environment deploy identity RBAC Administrator on the Document Intelligence account (may assign only Cognitive Services User), only to service principals. `<env>/app` uses it to grant each environment's `pipeline` identity its DI runtime role. Story 5.2 adds the same on the shared Communication Services resource (may assign only the custom role `ACS Email Sender`, found by name, so `budget-and-roles.sh` must have run). While ACS doesn't exist (no `email_custom_domain`), that part is skipped with a message; re-run the script once the "Email domain" step has created it (its step 3).

### Step 4b: PGP key pair (once per environment)

The private key is readable only by the environment's `staff-api` identity (OCR-129, AD-11). So it does not live in the environment's vault (`kv-01`/`kv-11`), where the env deploy identity (Secrets Officer, and Contributor on the group) could read it, but in the environment's private-key vault in `rg-22` (`kv-22` dev, `kv-23` prod), which no Terraform stack manages and on which no deploy identity, pipeline identity or loaders group (Dj's load-script login) has any role.

Preconditions: `state-backend.sh` has created the private-key vaults, and `<env>/foundation` exists (it creates the `staff-api` identity, `babaloo-sea-lng-id-02` dev, `-id-12` prod). The operator is an Owner of the subscription and gives themself Key Vault Secrets Officer on both vaults for this step only:

```sh
me="$(az ad signed-in-user show --query id -o tsv)"
sub="/subscriptions/$ARM_SUBSCRIPTION_ID"
env_vault="$sub/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.KeyVault/vaults/babaloo-sea-lng-kv-01"  # prod: rg-11, kv-11
pk_vault="$sub/resourceGroups/babaloo-sea-lng-rg-22/providers/Microsoft.KeyVault/vaults/babaloo-sea-lng-kv-22"   # prod: kv-23
for scope in "$env_vault" "$pk_vault"; do
  az role assignment create --assignee-object-id "$me" --assignee-principal-type User --role "Key Vault Secrets Officer" --scope "$scope"
done
```

`pgp-step4b.sh`:

1. stops before writing anything if the `staff-api` identity or the private-key vault does not exist, naming the step to run first;
2. stops if `pgp-private-key` is still in the environment's vault (stored there before OCR-129; see "Moving an existing private key" below). It never copies it;
3. if `pgp-public-key` (environment vault) and `pgp-private-key` (private-key vault) both exist, generates nothing; if only one exists it stops (a new pair would make existing ciphertext unreadable);
4. otherwise generates an RSA 3072 key pair with no passphrase in a throwaway `GNUPGHOME` under the gitignored `.work/` folder, stores the ASCII-armoured keys as `pgp-private-key` in the private-key vault first and `pgp-public-key` in the environment's vault last (both tagged `fingerprint=<key fingerprint>`), and deletes the local copies;
5. gives the `staff-api` identity Key Vault Secrets User on the `pgp-private-key` secret only (checked on every run, so a re-run completes a grant an earlier run missed).

Terraform never manages these two secrets or the private-key vault. `<env>/app` tells `staff-api` where the key is with the app setting `PGP_PRIVATE_KEY_VAULT_URI` (e.g. `https://babaloo-sea-lng-kv-22.vault.azure.net/`) and grants nothing on it.

Afterwards, remove your two Secrets Officer assignments (same loop with `az role assignment delete --assignee "$me" --role "Key Vault Secrets Officer" --scope "$scope"`).

**Moving an existing private key** (an environment whose step 4b ran before OCR-129, so `pgp-private-key` is in `kv-01`/`kv-11`). Do it once, as the Owner with the two Secrets Officer assignments above, before `<env>/app` is next applied (that apply removes `staff-api`'s old role on the env-vault secret):

```sh
( # a subshell, so set -eu, umask 077 and the trap stay local to it
set -eu
env_kv=babaloo-sea-lng-kv-01; pk_kv=babaloo-sea-lng-kv-22   # prod: kv-11, kv-23
umask 077; mkdir -p .work
work="$(mktemp -d .work/pgp-move.XXXXXX)"
cleanup() {
  set +e; GNUPGHOME="$work/gnupg" gpgconf --kill gpg-agent 2>/dev/null
  for f in "$work"/*.asc; do [ -e "$f" ] && { rm -P "$f" 2>/dev/null || shred -u "$f"; }; done   # macOS / Linux
  rm -rf "$work"
}
trap cleanup EXIT
# key_fpr <file>: the real fingerprint of the key in <file>, read in a throwaway GNUPGHOME.
key_fpr() {
  rm -rf "$work/gnupg"; mkdir "$work/gnupg"
  GNUPGHOME="$work/gnupg" gpg --batch --quiet --import "$1"
  GNUPGHOME="$work/gnupg" gpg --batch --with-colons --list-secret-keys | awk -F: '/^fpr:/ { print $10; exit }'
}
want="$(az keyvault secret show --vault-name "$env_kv" --name pgp-public-key --query tags.fingerprint -o tsv)"
[ -n "$want" ] || { echo "pgp-public-key has no fingerprint tag; nothing moved" >&2; exit 1; }
az keyvault secret download --vault-name "$env_kv" --name pgp-private-key --file "$work/source.asc"
[ "$(key_fpr "$work/source.asc")" = "$want" ] || { echo "the env-vault private key does not match pgp-public-key; nothing moved" >&2; exit 1; }
az keyvault secret set --vault-name "$pk_kv" --name pgp-private-key --file "$work/source.asc" \
  --content-type application/pgp-keys --tags "fingerprint=$want" --output none
# Check the copy as stored, before the env copy is deleted.
az keyvault secret download --vault-name "$pk_kv" --name pgp-private-key --file "$work/copy.asc"
[ "$(key_fpr "$work/copy.asc")" = "$want" ] || { echo "the copy in $pk_kv does not match pgp-public-key; the env copy is kept" >&2; exit 1; }
az keyvault secret delete --vault-name "$env_kv" --name pgp-private-key --output none
)
```

The env vault has purge protection (Terraform sets it and it can't be turned off), so the deleted secret can't be purged: with all its versions, it stays recoverable by an identity with Secrets Officer there (the env deploy identity has it) until the vault's 7-day soft-delete retention ends, and is then removed for good. Dj accepted this 7-day window (2026-09-29). Only after those 7 days does `az keyvault secret list-deleted --vault-name "$env_kv"` stop listing it; check it then, not straight away. Right after the move, run `pgp-step4b.sh`: it finds both keys, generates nothing and grants `staff-api` on the moved key.

### Step 5: database logins (once per environment)

`database-step5.sh` connects to the server's `postgres` database as the Entra admin, the pg-admins group, with a member's `az` token, and runs `database-step5.sql`. Run it signed in (`az login`) as a member of `babaloo-sea-lng-grp-21`:

```sh
PG_ADMIN_USER=babaloo-sea-lng-grp-21 ENVIRONMENT=dev ./database-step5.sh   # then ENVIRONMENT=prod
```

`PG_ADMIN_USER` must not be the environment's loaders group (the load-script login); the script stops if it is. First it looks up the loaders group (`babaloo-sea-lng-grp-01` dev, `-grp-11` prod) and stops if `app-registrations.sh` has not created it. Then it:

- creates the environment's logins with `pgaadauth_create_principal`: the `pipeline`, `staff-api` and `accounts-sim` identities, the deploy identity, and the loaders group (`supplier-api` has none);
- makes the deploy identity the owner of `invoicing_<env>`, in one transaction with the temporary role membership it needs;
- revokes `CONNECT` and `TEMPORARY` from `PUBLIC` on both databases;
- grants `CONNECT` on `invoicing_<env>` to that environment's logins only;
- connects to `invoicing_<env>` and creates the `pgcrypto` extension there (Story 1.6: `pgp_pub_encrypt` for bank details). Only the server admin may create an extension on Azure; Terraform allow-lists it. Migration `0004_master_audit` then finds it.

It then gives the loaders group (principal type `Group`) Key Vault Secrets User on the `pgp-public-key` and `hmac-key` secrets only (never the private key, which is in the private-key vault; OCR-129) and Storage Table Data Contributor on the storage account, for the load script. A vault-wide Secrets User assignment from an earlier run of this step is removed. Schema grants are Alembic migrations (step 6), not part of this step.

`verify-db-isolation.sh` checks, as the admin (`PG_ADMIN_USER=babaloo-sea-lng-grp-21`), that both databases exist, that `PUBLIC` cannot connect to either and that each environment login can connect to its own database and not the other (PASS/FAIL per check, exit 1 on any FAIL). To prove a real refusal, run it on the CI VM inside the Jenkins container (`docker exec -it jenkins bash`), signed in as the dev deploy identity (`az login --identity --client-id "$DEPLOY_CLIENT_ID_DEV"`), with `CONNECT_AS_LOGIN=babaloo-sea-lng-id-22 TARGET_DB=invoicing_prod`.

Each environment has its own loaders group, so the loaders groups are cross-checked like the other logins.

### Step 8: staff-api redirect URI and sign-in check (once per environment, Story 2.7)

**Before the next pipeline run:** `infra/dev/app` and `infra/prod/app` now need `staff_api_client_id` in their `terraform.tfvars` (the client id `app-registrations.sh` prints; not a secret), or their plan stops asking for it. Re-run `app-registrations.sh` too, so group claims are turned off on the `staff-api` registrations.

`<env>/app` turns on built-in auth for `staff-api` (Entra, single tenant, ID tokens only, no client secret, token store off; only `/api/health` is anonymous). Entra refuses the sign-in until the app registration knows where to send the user back, and the host name exists only after `<env>/app` is applied. So, after the first `<env>/app` apply:

1. Read the host name: `terraform output -json function_apps` in `infra/<env>/app`, key `staff_api.host_name` (Dev `babaloo-sea-lng-func-02.azurewebsites.net`, Prod `-func-12`).
2. Add the redirect URI to `babaloo-sea-lng-staff-api-<env>` (ID tokens stay on, no secret):

   ```sh
   app_id="$(az ad app list --display-name babaloo-sea-lng-staff-api-<env> --query '[0].appId' -o tsv)"
   az ad app update --id "$app_id" --web-redirect-uris "https://<staff-api host>/.auth/login/aad/callback" --enable-id-token-issuance true
   ```

   `--web-redirect-uris` replaces the list, so include any URI already there (`az ad app show --id "$app_id" --query web.redirectUris`).
3. Assign each staff user their app role(s) on the Enterprise application `babaloo-sea-lng-staff-api-<env>` (Users and groups > Add user/group). "Assignment required" is on, so an unassigned user is refused by Entra.
4. **Check sign-in** (verified offline only until now):
   - open `https://<staff-api host>/` in a private window: it redirects to the Entra login, and after sign-in the staff app shows the user's sidebar and landing page;
   - `curl -i -H 'X-Requested-With: XMLHttpRequest' https://<staff-api host>/api/me` answers `401`, not a redirect (AD-14; an open question in the spine);
   - `curl -i https://<staff-api host>/api/health` answers `200` without signing in;
   - sign in as a tenant user who has **no** role assignment on the Enterprise application: Entra must refuse with `AADSTS50105` ("assignment required" is working);
   - `/api/me` never touches the database, so while PostgreSQL is stopped the sign-in and the landing page still load; the full-page offline notice appears on the first call that reads data (from the screen stories on), not on landing;
   - in the browser's developer tools, the `AppServiceAuthSession` cookie is `Secure` and `HttpOnly`; note its `SameSite` value. AD-14 asks for `Lax`, and `authsettingsV2` has no setting for it: if the platform sets another value, record it as a departure from AD-14 for Dj to accept (the CSRF defence is the `X-Requested-With` header either way).

### Purchasing seed: synthetic PO and goods-received data (Story 2.4)

The purchasing simulation (AD-10, CAP-20) starts empty. Its data is synthetic (`backend/seed/sim_purchasing.json`, security.md rule 1). The app logins can only read it (AD-11), so the seed must run as the environment's deploy identity, which owns the schema. There is no pipeline stage for it: it is an operator step, once per environment after its migrations. Run these commands from a checkout, in a shell signed in to `az` as that environment's deploy identity (`babaloo-sea-lng-id-22` for Dev, `-id-23` for Prod). For Dev, that is a shell on the CI VM inside the Jenkins container (`docker exec -it jenkins bash`, then `az login --identity --client-id "$DEPLOY_CLIENT_ID_DEV"`):

```sh
export PGHOST=babaloo-sea-lng-psql-21.postgres.database.azure.com PGPORT=5432 PGSSLMODE=require
export PGUSER=babaloo-sea-lng-id-22 PGDATABASE=invoicing_dev   # prod: babaloo-sea-lng-id-23, invoicing_prod
export PGPASSWORD="$(az account get-access-token --resource-type oss-rdbms --query accessToken -o tsv)"
uv run --directory backend --locked --no-dev python -m invoicing.tools.seed_purchasing
# Prod only, and only on purpose:
uv run --directory backend --locked --no-dev python -m invoicing.tools.seed_purchasing --allow-prod
```

The command checks the file before it writes anything, then prints the rows upserted per table. It exits 2 with a one-line error for a missing or invalid file, or for an id the database already holds under another natural key.

- **Idempotent.** Rows are upserted by natural key: material code, PO number, PO line number and delivery number. Re-run it after editing the JSON. Rows removed from the file stay in the database, and the command prints a warning with their count per table.
- **Prod.** The command refuses `invoicing_prod` unless `--allow-prod` is given. Seeding Prod is a deliberate PoC choice: Prod has no real purchasing system yet, and the data is synthetic only. When the real adapter replaces `sim` (`PURCHASING_ADAPTER`), clear the simulation's data from Prod.
- **Supplier ids.** The ids in the file are fixed synthetic UUIDs for the supplier load script (Story 1.6) to use.

### Supplier load: suppliers, bank details and upload links (Story 1.6)

The load script creates or updates the supplier master (`master.supplier`, `master.supplier_bank`) from a CSV of **synthetic** suppliers (security.md rule 1), and issues each supplier's upload link. Dj runs it signed in as himself, a member of the environment's loaders group (`babaloo-sea-lng-grp-01` dev, `-grp-11` prod), and connects to PostgreSQL as that group: step 5 gave the group a login, Key Vault Secrets User on `pgp-public-key` and `hmac-key` only, and Storage Table Data Contributor. Audit entries name the group as the actor, not Dj. It never reads the private key and never decrypts.

The CSV has one header row with exactly these columns, in any order: `supplier_id` (required, a UUID; use the ids in `backend/seed/sim_purchasing.json`, rows match on it), `name` (required), `phone`, `tax_id`, `bank_account_number`, `iban`, `swift` (the AD-18 bank field ids). A blank bank, `phone` or `tax_id` cell leaves the stored value unchanged (a new supplier stores it empty). So a blank cell can't clear a phone or tax id, or remove a bank field. To do that, an admin (the PostgreSQL Entra admin, the pg-admins group, not the loaders group, which has no DELETE) runs the change by hand and records it in the audit log in the same transaction, naming column or field ids only, never values:

```sql
BEGIN;
UPDATE master.supplier SET phone = NULL WHERE id = '<supplier_id>';          -- or tax_id
-- DELETE FROM master.supplier_bank WHERE supplier_id = '<supplier_id>' AND field_id = 'iban';
INSERT INTO audit.event (id, action, entity, entity_id, detail)
VALUES (gen_random_uuid(), 'supplier.updated', 'supplier', '<supplier_id>',
        '{"fields": ["phone"], "by_hand": true}');                            -- or 'supplier_bank.removed', {"field_id": "iban"}
COMMIT;
```

Keep the CSV outside the repository, or under the gitignored `.work/`.

```sh
az login   # as Dj, a member of the loaders group
export PGHOST=babaloo-sea-lng-psql-21.postgres.database.azure.com PGPORT=5432 PGSSLMODE=require
export PGUSER=babaloo-sea-lng-grp-01 PGDATABASE=invoicing_dev   # prod: babaloo-sea-lng-grp-11, invoicing_prod
export PGPASSWORD="$(az account get-access-token --resource-type oss-rdbms --query accessToken -o tsv)"
uv run --directory backend --locked --no-dev python -m invoicing.tools.load_suppliers \
  --file "$PWD/.work/suppliers.csv" \
  --host babaloo-sea-lng-func-01.azurewebsites.net \
  --vault-uri https://babaloo-sea-lng-kv-01.vault.azure.net/ \
  --account babaloosealngst01
# Prod: -func-11, -kv-11, babaloosealngst11, and --allow-prod.
```

On macOS with the python.org Python, run its `Install Certificates.command` once first (or `export SSL_CERT_FILE="$PWD/backend/.venv/lib/python3.13/site-packages/certifi/cacert.pem"`): otherwise the async Table Storage client fails TLS verification and the load stops after the database step with "Table Storage (supplierlinks) can't be reached". Running the same command again then issues the links.

`--host` is the `supplier-api` host (`terraform output -json function_apps` in `infra/<env>/app`).

- **What it does.** It checks the whole CSV first (a bad file exits 2 with one line naming the row and column, and writes nothing). In one database transaction it creates or updates each supplier, stores each non-empty bank value as `pgp_pub_encrypt` ciphertext plus an HMAC-SHA256 fingerprint of the value normalised (spaces and hyphens stripped, uppercase), and writes an `audit.event` row per change (field ids only, never values). After that commits, each supplier in the CSV without an active link gets one. Every link change is audited before it is made (`supplier_link.issued`, `supplier_link.replaced`, `supplier_link.revoked`, supplier id only).
- **Links are printed once.** Each new link is printed on its own line, `link for <supplier_id> (<name>): https://<host>/u#<token>`, for Dj to send by WhatsApp or SMS. Only its SHA-256 is stored (`supplierlinks`), so it can never be shown again: a lost link is replaced, not recovered. Don't paste the output anywhere else.
- **Idempotent.** Running it again with the same CSV changes nothing and prints `links: none issued`. A value written differently (spaces, hyphens, case) is not a change.
- **Replace or revoke** (Dj, AD-6): `--replace-link <supplier_id>` revokes the supplier's active link and prints a new one; `--revoke <supplier_id>` revokes it and issues none (the page then shows "This link isn't working"). Both are audited. `--file` and `--vault-uri` are optional with these; `--revoke` needs no `--host`. A revoked supplier still in the CSV gets a fresh link from the next load, so to keep a supplier revoked, remove it from the CSV (Dj, 2026-09-29). An unknown supplier, or `--revoke` with no active link, exits 2 and changes nothing.
- **A failed link write** (Table Storage unreachable) exits 1 after the database commit, and the one-line error names the exact recovery: usually run the same command again (for `--replace-link` or `--revoke`, that command for the same supplier). If storing a new link failed, its response may have been lost after the link was stored, so nobody has seen its token: if the re-run prints no link for that supplier, run `--replace-link <supplier_id>`.
- **Prod** is refused unless `--allow-prod` is given, as for the purchasing seed.

### Alert check: prove an alert reaches Dj (Story 1.5)

Every alert goes through an action group that emails Dj: `ag-21` for the `shared` budget, `ag-01` and `ag-11` for the Dev and Prod budgets and their log alerts (AD-17). After the stacks are applied (and after any change to an action group):

1. Run `./test-alerts.sh` (try `--dry-run` first; `STACKS="shared dev"` before Prod exists). It first checks that every requested action group exists and has an email receiver, and stops before sending anything if one doesn't. Then it sends one test notification through each group with `az monitor action-group test-notifications create`, to the email receivers stored on that group (so it tests what Terraform configured, not an address typed on the command line). It changes nothing.
2. **Check that Dj received it:** one test email per action group at each address the script lists, each naming its group. Look in the spam folder too, and mark the sender as safe.
3. If one is missing, check that group's email receiver in its stack's `terraform.tfvars` (`alert_email`) and re-run. An alert that doesn't reach Dj is not an alert.

`<env>/app` holds three log search alerts on the environment's Application Insights `traces` (the custom metrics never reached Application Insights in Dev, so no alert uses them): `poison_message` on `poison.done`, one alert per `queue`, and `stuck_invoices` on `sweeper.done` with `requeued` + `orphans` above 0 (`ar-01`/`ar-02` in Dev, `ar-11`/`ar-12` in Prod, Story 2.2), and `di_pages_used_pct` on `extract.di_usage` (`ar-03` Dev, `ar-13` Prod, Story 2.3), which fires at 80 % of the environment's monthly page cap (Dev 100, Prod 400). There is no separate log-cap alert: the 0.08 GB daily cap bounds ingestion (AD-17).

### Pipeline check: first Dev deploy (Story 2.2)

Everything below was verified offline only. Once, after the first Dev code deploy of the `pipeline` app (and again for Prod):

1. **Poison alert.** The alert rules search the Dev Application Insights (`appi-01`) `traces` for `poison.done`, `sweeper.done` and `extract.di_usage` (queries in `infra/modules/env-app/main.tf`). Wait for the first sweep (every 15 minutes, `sweeper.done` is logged even when nothing is stuck) and check in **Logs** that `traces | where message startswith "sweeper.done "` returns it. Then, with a temporary queue role, send one malformed message to `q-quality`; after 5 failures it reaches `q-quality-poison` and the trigger logs `poison.done code=… queue=q-quality-poison`. Within about 20 minutes `ar-01` must fire for that queue and Dj must get its email.
2. **Stopped-database wait (AD-7).** Stop the PostgreSQL server, then upload a test invoice through the supplier link. In the Dev logs (`traces`), `pipeline.db_wait` with `code=DB_OFFLINE` and `queue=q-quality` must appear; in the storage account, the `q-quality` message is invisible for 15 minutes (its next-visible time is 15 minutes out) and keeps its `attempt`. Start the server again: within 15 minutes the message is processed and the invoice reaches `awaiting_extraction`. No message may reach `q-quality-poison` while the server is stopped.

## Tag gate (P-17)

`infra/scripts/check_tags.py` fails a plan whose taggable Azure resources lack any of the five tags:

Plan JSON contains sensitive values, so write it under the gitignored `.work/` folder, never elsewhere in the repo:

```sh
mkdir -p .work
terraform -chdir=infra/dev/foundation plan -out=tfplan
terraform -chdir=infra/dev/foundation show -json tfplan > .work/dev-foundation.plan.json
python3 infra/scripts/check_tags.py .work/dev-foundation.plan.json   # exit 1 lists each failing resource
```

It also fails a resource whose tags are only known after apply.

The deploy pipeline runs it after every plan and before any apply (`ci/terraform-plan.sh`), and deletes the plan JSON afterwards; a failing gate stops that stack and everything after it.
