# Bootstrap and operator steps (spine AD-17)

These scripts are the out-of-band steps of AD-17 (terraform.md rule 29). An operator runs them from a shell signed in with `az login`. They never run in the pipeline.

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
| `ARM_TENANT_ID` | `app-registrations.sh`, `ado-setup.sh` | Entra tenant; `az` must be signed in to it |
| `TAG_OWNER`, `TAG_COST_CENTRE`, `TAG_APPLICATION`, `TAG_DATA_CLASSIFICATION` | `state-backend.sh` | P-17 tag values (use the same values as the stacks' `terraform.tfvars`) |
| `ADO_ORG`, `ADO_ORG_ID`, `ADO_PROJECT` | `state-backend.sh` (all three), `ado-setup.sh` (`ADO_ORG`, `ADO_PROJECT`) | Azure DevOps organisation name, organisation id (GUID) and project, for the federated credentials and the ADO setup |
| `ADO_SC_SHARED`, `ADO_SC_DEV`, `ADO_SC_PROD` | `state-backend.sh`, `ado-setup.sh` (optional) | service connection names; default `azure-shared`, `azure-dev`, `azure-prod`, which `pipelines/deploy.yml` uses. Change them only in all three places |
| `ADO_APPROVER` | `ado-setup.sh` | Dj's Azure DevOps sign-in: the approver on the `shared` and `prod` environments |
| `ADO_REPO` | `ado-setup.sh` (optional) | Azure Repos repository; default `ADO_PROJECT` |
| `ALERT_EMAIL` | `budget-and-roles.sh` | where the $8 subscription budget alert goes (same as the stacks' `alert_email`) |
| `SHARED_ACTION_GROUP_ID` | `budget-and-roles.sh` (optional) | resource id of the shared action group `ag-21` (`terraform output action_group_id` in `infra/shared/foundation`). Unset: the subscription budget alerts by email only, with a warning |
| `STACKS` | `test-alerts.sh` (optional) | which action groups to test; default `shared dev prod`; repeats are ignored |
| `ENVIRONMENT` | `pgp-step4b.sh`, `database-step5.sh` | `dev` or `prod` |
| `DJ_USER_UPN` | `database-step5.sh`; also a required variable of the deploy pipeline (`ci/migrate.sh`, below) | Dj's Entra UPN: the load-script login |
| `PG_ADMIN_USER` | `database-step5.sh`, `verify-db-isolation.sh` | the PostgreSQL Entra admin used to connect. Required, and it must be a separate principal from `DJ_USER_UPN` (e.g. an Entra group whose members are the operators): the load script never runs as server admin. `database-step5.sh` stops if the two are equal |
| `CONNECT_AS_LOGIN`, `TARGET_DB` | `verify-db-isolation.sh` (mode 2) | a real connection attempt that must be refused |

## Names

| What | Name |
| --- | --- |
| Resource groups | `babaloo-sea-lng-rg-21` (shared stack), `-rg-01` (dev), `-rg-11` (prod), and `-rg-22` (bootstrap-only: state and deploy identities) |
| State storage | `babaloosealngst21` in `rg-22`; containers `shared`, `dev`, `prod`; key `foundation.tfstate` per stack |
| Deploy identities | `babaloo-sea-lng-id-21` (shared), `-id-22` (dev), `-id-23` (prod), all in `rg-22` |
| Private-key vaults (OCR-129) | `babaloo-sea-lng-kv-22` (dev), `-kv-23` (prod), in `rg-22`; each holds only its environment's `pgp-private-key`; no diagnostic settings, by decision (Dj, 2026-09-29) |

`rg-22` is created and managed only by these scripts. No Terraform stack manages it and no deploy identity holds Contributor on it; each deploy identity has only its container-scoped state roles there, and no identity's RBAC Administrator reaches it. So no stack's identity can change another identity's federated credentials or another stack's state, or read or grant access to a PGP private key.
| App registrations | `babaloo-sea-lng-staff-api-<env>`, `babaloo-sea-lng-accounts-sim-<env>` |
| Subscription budget | `babaloo-sea-lng-budget-22` ($8) |
| Action groups (all email Dj) | `babaloo-sea-lng-ag-21` (shared: the `shared` and subscription budgets), `-ag-01` (dev), `-ag-11` (prod) |

## Before deploying Story 1.6 (environments already set up)

Migration `0004_master_audit` needs `pgcrypto` and grants to Dj's login, so on an environment whose step 5 ran before Story 1.6, in this order:

1. Re-run step 5 for both environments, as the PostgreSQL Entra admin: `ENVIRONMENT=dev ./database-step5.sh`, then `ENVIRONMENT=prod ./database-step5.sh`. It is idempotent; the new part creates `pgcrypto` in `invoicing_<env>`.
2. Set the deploy pipeline variable `DJ_USER_UPN` (see **Migrations** below).
3. Merge. The Dev and Prod migration stages then apply `0004_master_audit`.

## Run order

| AD-17 step | Who | What to run |
| --- | --- | --- |
| 1 | operator with Owner | `./state-backend.sh`, then `./app-registrations.sh`, then `./budget-and-roles.sh` |
| 1 (ADO) | operator, Project Administrator in the ADO project | `./ado-setup.sh` (after `state-backend.sh`, which creates the deploy identities it binds). Then merge to `main` to start the deploy pipeline |
| 2 | `shared` deploy identity (pipeline) | `infra/shared/foundation`: fill `terraform.tfvars`; the deploy pipeline plans it, Dj approves the `shared` stage, it applies the saved plan. Then add the email domain's DNS records (below), and re-run `SHARED_ACTION_GROUP_ID=<ag-21 id> ./budget-and-roles.sh` so the subscription budget notifies through `ag-21` |
| 3 | operator | `./rbac-step3.sh` |
| 4 | env deploy identity (pipeline) | `infra/dev/foundation` (applies automatically), then `infra/prod/foundation` (after Dj approves the `prod` stage) |
| 4b | operator with Owner, plus Key Vault Secrets Officer on both vaults for this step only | after `<env>/foundation` exists (it creates the `staff-api` identity): `ENVIRONMENT=dev ./pgp-step4b.sh`, then, after `prod/foundation`, `ENVIRONMENT=prod ./pgp-step4b.sh` |
| 5 | operator as PostgreSQL Entra admin | `ENVIRONMENT=dev ./database-step5.sh`, then prod; then `./verify-db-isolation.sh` |
| 6, 7, 9 | pipeline | Dev migrations, `dev/app`, Dev code deploy, then the same for Prod after `prod/foundation` (`pipelines/deploy.yml`; `<env>/app` and the code deploy arrive with Story 1.3) |
| 8 | operator | `staff-api` redirect URI, then the sign-in check (Story 2.7, below) |
| Purchasing seed | operator, signed in as the env deploy identity | after the environment's migrations: the synthetic PO and goods-received data (below) |
| Supplier load | Dj, signed in as himself | after step 4b, step 5, the environment's migrations and `<env>/app`: the synthetic suppliers and their upload links (below) |
| Alert check | operator | `./test-alerts.sh` once the stacks are applied, then check that Dj received every test email (below) |
| Pipeline check | operator | after the first Dev code deploy: the metric namespace and the stopped-database wait (below) |

Try each script with `--dry-run` first.

### Step 1: state, groups, identities, app registrations, role, budget

- `state-backend.sh` registers the resource providers and waits for each (the `azurerm` provider has `resource_provider_registrations = "none"`), creates the four tagged resource groups, the state account (LRS, shared-key access off, public blob access off, TLS 1.2, versioning and 7-day soft delete) and its three containers, the two private-key vaults `kv-22` (dev) and `kv-23` (prod) in `rg-22` (RBAC mode, purge protection, 7-day soft delete, public network access like the environment vaults, the five tags with `environment` set to their environment; an existing vault has these settings and its tags re-applied, and nobody gets a role on it), and the three deploy identities with a federated credential for their Azure DevOps service connection (issuer `https://vstoken.dev.azure.com/<ADO_ORG_ID>`, subject `sc://<org>/<project>/<connection>`). An existing credential whose issuer or subject differs from the current inputs is updated.
- Deploy identity rights (azure.md rule 31 and AD-17 "Deploy identity rights"):
  - every deploy identity: Contributor on its own stack's resource group (`rg-21`, `rg-01` or `rg-11`, never `rg-22`), and Storage Blob Data Contributor on its own state container;
  - `dev` and `prod` also: Role Based Access Control Administrator on their resource group, conditioned to assigning or removing only the runtime roles (Storage Blob Data Contributor/Owner, Storage Queue Data Contributor/Message Sender, Storage Table Data Contributor, Key Vault Secrets User/Officer, Monitoring Metrics Publisher) and only to service principals; and Storage Blob Data Reader on the `shared` state container.
- `app-registrations.sh` creates, per environment, `staff-api` (single tenant, app roles `admin`, `finance`, `procurement`, `management`, `goods_in`, ID tokens on, "assignment required" on its service principal, no secret) and `accounts-sim` (single tenant, identifier URI `api://<appId>`). It prints the client ids that `<env>/app` needs: put the `staff-api` one in `infra/<env>/app/terraform.tfvars` as `staff_api_client_id` (Story 2.7; not a secret) before `<env>/app` is planned. The redirect URI is step 8.
- `budget-and-roles.sh` creates the custom role `ACS Email Sender` (`Microsoft.Communication/CommunicationServices/Read` and `Microsoft.Communication/EmailServices/write`; the exact minimum is an open question in the spine) and the $8 subscription budget with an alert to `ALERT_EMAIL`. With `SHARED_ACTION_GROUP_ID` set, the alert also goes through the shared action group `ag-21`. An existing budget keeps its amount, start date and thresholds; the only change the script makes to it is adding `ag-21` to its notifications (once). The first run comes before `ag-21` exists, so run it again after step 2.

### Step 1 (ADO): service connections, environments, pipelines and branch policy

`ado-setup.sh` sets up the Azure DevOps side of AD-17. It needs the `azure-devops` extension (`az extension add --name azure-devops`) and an `az login` that is Project Administrator in the ADO project. It creates, or checks and re-applies:

- service connections `azure-shared`, `azure-dev` and `azure-prod`: Azure Resource Manager, workload identity federation (manual), subscription scope, bound to the deploy identities `id-21`, `id-22` and `id-23` by client id. No secret exists. ADO's federation subject is `sc://<org>/<project>/<connection>`, the one `state-backend.sh` put on each identity's federated credential. An existing connection bound to anything else stops the script; delete it in ADO and re-run;
- environments `shared`, `dev` and `prod`, each with an exclusive lock (one deploy at a time), and an approval check on `shared` and `prod` with `ADO_APPROVER` as approver. Approvals live on the environments, not in YAML, so this script is what gates `shared` and Prod. Dj may approve his own runs;
- a branch control check on all three connections and all three environments that allows only `refs/heads/main`. Without it, a manual run of the deploy pipeline on another branch could sign in as `azure-shared` or `azure-prod` in a plan stage, which has no approval;
- the pipelines `ocrinvoicing-pr` (`pipelines/pr.yml`), `ocrinvoicing-deploy` (`pipelines/deploy.yml`) and `ocrinvoicing-weekly-scan` (`pipelines/weekly-scan.yml`), and it authorises only the deploy pipeline on the three connections and environments;
- a blocking build policy on `main`: every change goes through a pull request whose `ocrinvoicing-pr` build (lint, tests with coverage, `pip-audit`, `npm audit`, `gitleaks`, Terraform checks) must pass.

What the pipelines do:

- **PR build**: `ci/checks.sh lint`, `test`, `audit`, `secrets` and `terraform` as parallel jobs. Run `ci/checks.sh all` locally for the same result.
- **Deploy** (every merge to `main`, one run at a time): for each stack, a plan stage (`plan -out=tfplan`, then `check_tags.py` on `terraform show -json`) and, only when the plan has changes, an apply stage in the stack's environment that applies that saved plan. So a stack with no changes asks for no approval. Order: `shared/foundation`, `dev/foundation`, Dev migrations, `dev/app`, Dev code deploy, `prod/foundation`, Prod migrations, `prod/app`, Prod code deploy. Dev applies without approval (the recorded terraform.md rule 26/33 exception); `shared` and Prod wait for the approval. A failed or rejected stage stops everything after it.
- **Migrations** (`ci/migrate.sh`): `alembic upgrade head` as the environment's deploy identity with an Entra token, straight to the server (the PoC firewall is open, so no temporary rule); skipped with "no migrations" until `backend/migrations/env.py` exists. From Story 1.6 the migrations also grant `master` and `audit` to Dj's user, so the deploy pipeline needs the variable `DJ_USER_UPN` (Dj's Entra UPN, the same value as for `database-step5.sh`). Set it once; it is not a secret: `az pipelines variable create --pipeline-name ocrinvoicing-deploy --name DJ_USER_UPN --value <upn> --org https://dev.azure.com/<ADO_ORG> --project <ADO_PROJECT>`. Without it the migration stage stops with "DJ_USER_UPN must be Dj's Entra UPN" before connecting.
- **Weekly scan**: `ci/checks.sh audit` on `main` every Monday, failing on any finding.

Prod can ask for up to four approvals in one run: `prod/foundation`, Prod migrations, `prod/app` and the Prod code deploy. ADO evaluates approvals per stage, and each of these is its own stage so it can be skipped (with no approval asked) when it has nothing to do. The pipeline can't tell whether migrations are pending without connecting to the database, so once migrations exist the Prod migration stage asks every run.

Manual operator steps after `ado-setup.sh` (no CLI for them):

1. **Weekly scan alerts.** A failed scheduled run notifies nobody by default. In Project settings > Notifications, add a subscription "A build fails" filtered to the pipeline `ocrinvoicing-weekly-scan`, delivered to Dj.
2. **Artifact retention.** The deploy run publishes each saved plan (`tfplan-<stack>`) as a pipeline artifact, because the apply stage runs on another agent. A saved plan holds sensitive values (e.g. generated secrets and connection details), and anyone who can view the pipeline's runs can download it (project Readers by default). Branch control limits who can produce one: only runs of `main`, which only a merged PR reaches. To keep them for as short as possible, set Project settings > Pipelines > Settings > Retention "Days to keep artifacts, symbols and attachments" and "Days to keep runs" to the minimum, and do not grant pipeline view rights beyond the project team. YAML cannot set a shorter per-artifact retention.

### Step 2 extra: verify the email domain, then link it

`shared/foundation` creates the ACS Email service with Dj's custom domain but does not link it, because Azure refuses to link an unverified domain.

1. After the first apply, read `terraform output email_domain` and add the listed DNS records (Domain, SPF, DKIM, DKIM2) at the DNS host.
2. Start verification for each record type, e.g. `az communication email domain initiate-verification --domain-name <domain> --email-service-name babaloo-sea-lng-ecs-21 --resource-group babaloo-sea-lng-rg-21 --verification-type Domain` (repeat for `SPF`, `DKIM`, `DKIM2`).
3. When all are `Verified`, set `email_domain_link_enabled = true` in `infra/shared/foundation/terraform.tfvars` and apply again.

### Step 3: conditioned RBAC Administrator on the shared DI and ACS

`rbac-step3.sh` gives each environment deploy identity RBAC Administrator on the Document Intelligence account (may assign only Cognitive Services User) and on the ACS resource (may assign only `ACS Email Sender`), only to service principals. `<env>/app` uses these to grant each environment's `pipeline` identity its runtime roles.

### Step 4b: PGP key pair (once per environment)

The private key is readable only by the environment's `staff-api` identity (OCR-129, AD-11). So it does not live in the environment's vault (`kv-01`/`kv-11`), where the env deploy identity (Secrets Officer, and Contributor on the group) could read it, but in the environment's private-key vault in `rg-22` (`kv-22` dev, `kv-23` prod), which no Terraform stack manages and on which no deploy identity, pipeline identity or Dj's load-script user has any role.

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

`database-step5.sh` connects to the server's `postgres` database as the Entra admin (`PG_ADMIN_USER`, not Dj's load-script user) with an `az` token and runs `database-step5.sql`:

- creates the environment's logins with `pgaadauth_create_principal`: the `pipeline`, `staff-api` and `accounts-sim` identities, the deploy identity, and Dj's user (`supplier-api` has none);
- makes the deploy identity the owner of `invoicing_<env>`, in one transaction with the temporary role membership it needs;
- revokes `CONNECT` and `TEMPORARY` from `PUBLIC` on both databases;
- grants `CONNECT` on `invoicing_<env>` to that environment's logins only;
- connects to `invoicing_<env>` and creates the `pgcrypto` extension there (Story 1.6: `pgp_pub_encrypt` for bank details). Only the server admin may create an extension on Azure; Terraform allow-lists it. Migration `0004_master_audit` then finds it.

It then gives Dj's user Key Vault Secrets User on the `pgp-public-key` and `hmac-key` secrets only (never the private key, which is in the private-key vault; OCR-129) and Storage Table Data Contributor on the storage account, for the load script. A vault-wide Secrets User assignment from an earlier run of this step is removed. Schema grants are Alembic migrations (step 6), not part of this step.

`verify-db-isolation.sh` checks, as the admin, that both databases exist, that `PUBLIC` cannot connect to either and that each environment login can connect to its own database and not the other (PASS/FAIL per check, exit 1 on any FAIL). To prove a real refusal, run it inside a Dev pipeline job signed in as the dev deploy identity with `CONNECT_AS_LOGIN=babaloo-sea-lng-id-22 TARGET_DB=invoicing_prod`.

Dj's user is one login on the shared server and is granted `CONNECT` by both environments, so it is left out of the cross-check.

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

The purchasing simulation (AD-10, CAP-20) starts empty. Its data is synthetic (`backend/seed/sim_purchasing.json`, security.md rule 1). The app logins can only read it (AD-11), so the seed must run as the environment's deploy identity, which owns the schema. There is no pipeline stage for it: it is an operator step, once per environment after its migrations. Run these commands from a checkout, in a shell signed in to `az` as that environment's deploy identity (`babaloo-sea-lng-id-22` for Dev, `-id-23` for Prod), for example an `AzureCLI@2` step on that environment's service connection:

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

The load script creates or updates the supplier master (`master.supplier`, `master.supplier_bank`) from a CSV of **synthetic** suppliers (security.md rule 1), and issues each supplier's upload link. Dj runs it as himself: step 5 gave his user a login, Key Vault Secrets User on `pgp-public-key` and `hmac-key` only, and Storage Table Data Contributor. It never reads the private key and never decrypts.

The CSV has one header row with exactly these columns, in any order: `supplier_id` (required, a UUID; use the ids in `backend/seed/sim_purchasing.json`, rows match on it), `name` (required), `phone`, `tax_id`, `bank_account_number`, `iban`, `swift` (the AD-18 bank field ids). A blank bank, `phone` or `tax_id` cell leaves the stored value unchanged (a new supplier stores it empty). So a blank cell can't clear a phone or tax id, or remove a bank field. To do that, an admin (the PostgreSQL Entra admin, not Dj's load-script login, which has no DELETE) runs the change by hand and records it in the audit log in the same transaction, naming column or field ids only, never values:

```sql
BEGIN;
UPDATE master.supplier SET phone = NULL WHERE id = '<supplier_id>';          -- or tax_id
-- DELETE FROM master.supplier_bank WHERE supplier_id = '<supplier_id>' AND field_id = 'iban';
INSERT INTO audit.event (id, action, entity, entity_id, detail)
VALUES (gen_random_uuid(), 'supplier.updated', 'supplier', '<supplier_id>',
        '{"fields": ["phone"], "by_hand": true}');                            -- or 'supplier_bank.removed', {"field_id": "iban"}
COMMIT;
``` Keep the file outside the repository, or under the gitignored `.work/`.

```sh
az login   # as Dj
export PGHOST=babaloo-sea-lng-psql-21.postgres.database.azure.com PGPORT=5432 PGSSLMODE=require
export PGUSER="<Dj's UPN>" PGDATABASE=invoicing_dev   # prod: invoicing_prod
export PGPASSWORD="$(az account get-access-token --resource-type oss-rdbms --query accessToken -o tsv)"
uv run --directory backend --locked --no-dev python -m invoicing.tools.load_suppliers \
  --file .work/suppliers.csv \
  --host babaloo-sea-lng-func-01.azurewebsites.net \
  --vault-uri https://babaloo-sea-lng-kv-01.vault.azure.net/ \
  --account babaloosealngst01
# Prod: -func-11, -kv-11, babaloosealngst11, and --allow-prod.
```

`--host` is the `supplier-api` host (`terraform output -json function_apps` in `infra/<env>/app`).

- **What it does.** It checks the whole CSV first (a bad file exits 2 with one line naming the row and column, and writes nothing). In one database transaction it creates or updates each supplier, stores each non-empty bank value as `pgp_pub_encrypt` ciphertext plus an HMAC-SHA256 fingerprint of the value normalised (spaces and hyphens stripped, uppercase), and writes an `audit.event` row per change (field ids only, never values). After that commits, each supplier in the CSV without an active link gets one. Every link change is audited before it is made (`supplier_link.issued`, `supplier_link.replaced`, `supplier_link.revoked`, supplier id only).
- **Links are printed once.** Each new link is printed on its own line, `link for <supplier_id> (<name>): https://<host>/u#<token>`, for Dj to send by WhatsApp or SMS. Only its SHA-256 is stored (`supplierlinks`), so it can never be shown again: a lost link is replaced, not recovered. Don't paste the output anywhere else.
- **Idempotent.** Running it again with the same CSV changes nothing and prints `links: none issued`. A value written differently (spaces, hyphens, case) is not a change.
- **Replace or revoke** (Dj, AD-6): `--replace-link <supplier_id>` revokes the supplier's active link and prints a new one; `--revoke <supplier_id>` revokes it and issues none (the page then shows "This link isn't working"). Both are audited. `--file` and `--vault-uri` are optional with these; `--revoke` needs no `--host`. A revoked supplier still in the CSV gets a fresh link from the next load, so to keep a supplier revoked, remove it from the CSV (Dj, 2026-09-29). An unknown supplier, or `--revoke` with no active link, exits 2 and changes nothing.
- **A failed link write** (Table Storage unreachable) exits 1 after the database commit, and the one-line error names the exact recovery: usually run the same command again (for `--replace-link` or `--revoke`, that command for the same supplier). If storing a new link failed, its response may have been lost after the link was stored, so nobody has seen its token: if the re-run prints no link for that supplier, run `--replace-link <supplier_id>`.
- **Prod** is refused unless `--allow-prod` is given, as for the purchasing seed.

### Alert check: prove an alert reaches Dj (Story 1.5)

Every alert goes through an action group that emails Dj: `ag-21` for the `shared` and subscription budgets, `ag-01` and `ag-11` for the Dev and Prod budgets and their metric alerts (AD-17). After the stacks are applied (and after any change to an action group):

1. Run `./test-alerts.sh` (try `--dry-run` first; `STACKS="shared dev"` before Prod exists). It first checks that every requested action group exists and has an email receiver, and stops before sending anything if one doesn't. Then it sends one test notification through each group with `az monitor action-group test-notifications create`, to the email receivers stored on that group (so it tests what Terraform configured, not an address typed on the command line). It changes nothing.
2. **Check that Dj received it:** one test email per action group at each address the script lists, each naming its group. Look in the spam folder too, and mark the sender as safe.
3. If one is missing, check that group's email receiver in its stack's `terraform.tfvars` (`alert_email`) and re-run. An alert that doesn't reach Dj is not an alert.

Application Insights in each environment has alerting on custom metric dimensions on, so `poison_message{queue}` keeps its queue. `<env>/app` holds the `poison_message` and `stuck_invoices` alert rules (`ar-01`/`ar-02` in Dev, `ar-11`/`ar-12` in Prod, Story 2.2); Story 2.3 adds `di_pages_used_pct`. There is no separate log-cap alert: the 0.08 GB daily cap bounds ingestion (AD-17).

### Pipeline check: first Dev deploy (Story 2.2)

Everything below was verified offline only. Once, after the first Dev code deploy of the `pipeline` app (and again for Prod):

1. **Metric namespace.** The alert rules watch the custom metric namespace `azure.applicationinsights` (an `[ASSUMPTION]` in `infra/modules/env-app/main.tf`) and skip metric validation, so a wrong namespace fails silently. Wait for the first sweep (every 15 minutes, `stuck_invoices` is sent even when it is 0), then in the portal open the Dev Application Insights (`appi-01`), **Metrics**, and check that `stuck_invoices` is listed under the namespace `azure.applicationinsights`. For `poison_message`, send a message to `q-quality` for an invoice id with no blob; after 5 failures it reaches `q-quality-poison`, and the metric appears with the dimension `queue = q-quality-poison`. Then check that `ar-01` fired and Dj got its email. If the namespace differs, change `custom_metrics_namespace` in `infra/modules/env-app/main.tf`.
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
