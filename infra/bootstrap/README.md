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
| `ARM_TENANT_ID` | `app-registrations.sh` | Entra tenant; `az` must be signed in to it |
| `TAG_OWNER`, `TAG_COST_CENTRE`, `TAG_APPLICATION`, `TAG_DATA_CLASSIFICATION` | `state-backend.sh` | P-17 tag values (use the same values as the stacks' `terraform.tfvars`) |
| `ADO_ORG`, `ADO_ORG_ID`, `ADO_PROJECT` | `state-backend.sh` | Azure DevOps organisation name, organisation id (GUID) and project, for the federated credentials |
| `ADO_SC_SHARED`, `ADO_SC_DEV`, `ADO_SC_PROD` | `state-backend.sh` (optional) | service connection names; default `azure-shared`, `azure-dev`, `azure-prod`. Story 1.2 must create the connections with these names |
| `ALERT_EMAIL` | `budget-and-roles.sh` | where the $8 subscription budget alert goes |
| `ENVIRONMENT` | `pgp-step4b.sh`, `database-step5.sh` | `dev` or `prod` |
| `DJ_USER_UPN` | `database-step5.sh` | Dj's Entra UPN: the load-script login |
| `PG_ADMIN_USER` | `database-step5.sh`, `verify-db-isolation.sh` | the PostgreSQL Entra admin used to connect. Required, and it must be a separate principal from `DJ_USER_UPN` (e.g. an Entra group whose members are the operators): the load script never runs as server admin. `database-step5.sh` stops if the two are equal |
| `CONNECT_AS_LOGIN`, `TARGET_DB` | `verify-db-isolation.sh` (mode 2) | a real connection attempt that must be refused |

## Names

| What | Name |
| --- | --- |
| Resource groups | `babaloo-sea-lng-rg-21` (shared stack), `-rg-01` (dev), `-rg-11` (prod), and `-rg-22` (bootstrap-only: state and deploy identities) |
| State storage | `babaloosealngst21` in `rg-22`; containers `shared`, `dev`, `prod`; key `foundation.tfstate` per stack |
| Deploy identities | `babaloo-sea-lng-id-21` (shared), `-id-22` (dev), `-id-23` (prod), all in `rg-22` |

`rg-22` is created and managed only by these scripts. No Terraform stack manages it and no deploy identity holds Contributor on it; each deploy identity has only its container-scoped state roles there. So no stack's identity can change another identity's federated credentials or another stack's state.
| App registrations | `babaloo-sea-lng-staff-api-<env>`, `babaloo-sea-lng-accounts-sim-<env>` |
| Subscription budget | `babaloo-sea-lng-budget-22` ($8) |

## Run order

| AD-17 step | Who | What to run |
| --- | --- | --- |
| 1 | operator with Owner | `./state-backend.sh`, then `./app-registrations.sh`, then `./budget-and-roles.sh` |
| 2 | `shared` deploy identity (pipeline) | `infra/shared/foundation`: fill `terraform.tfvars`, plan, approve, apply. Then add the email domain's DNS records (below) |
| 3 | operator | `./rbac-step3.sh` |
| 4 | env deploy identity (pipeline) | `infra/dev/foundation`, then `infra/prod/foundation` |
| 4b | operator with Key Vault Secrets Officer on the vault | `ENVIRONMENT=dev ./pgp-step4b.sh`, then `ENVIRONMENT=prod ./pgp-step4b.sh` |
| 5 | operator as PostgreSQL Entra admin | `ENVIRONMENT=dev ./database-step5.sh`, then prod; then `./verify-db-isolation.sh` |
| 6-9 | pipeline / operator | Stories 1.2 and 1.3 (migrations, `<env>/app`, redirect URI, code deploy) |

Try each script with `--dry-run` first.

### Step 1: state, groups, identities, app registrations, role, budget

- `state-backend.sh` registers the resource providers and waits for each (the `azurerm` provider has `resource_provider_registrations = "none"`), creates the four tagged resource groups, the state account (LRS, shared-key access off, public blob access off, TLS 1.2, versioning and 7-day soft delete) and its three containers, and the three deploy identities with a federated credential for their Azure DevOps service connection (issuer `https://vstoken.dev.azure.com/<ADO_ORG_ID>`, subject `sc://<org>/<project>/<connection>`). An existing credential whose issuer or subject differs from the current inputs is updated.
- Deploy identity rights (azure.md rule 31 and AD-17 "Deploy identity rights"):
  - every deploy identity: Contributor on its own stack's resource group (`rg-21`, `rg-01` or `rg-11`, never `rg-22`), and Storage Blob Data Contributor on its own state container;
  - `dev` and `prod` also: Role Based Access Control Administrator on their resource group, conditioned to assigning or removing only the runtime roles (Storage Blob Data Contributor/Owner, Storage Queue Data Contributor/Message Sender, Storage Table Data Contributor, Key Vault Secrets User/Officer, Monitoring Metrics Publisher) and only to service principals; and Storage Blob Data Reader on the `shared` state container.
- `app-registrations.sh` creates, per environment, `staff-api` (single tenant, app roles `admin`, `finance`, `procurement`, `management`, `goods_in`, ID tokens on, "assignment required" on its service principal, no secret) and `accounts-sim` (single tenant, identifier URI `api://<appId>`). It prints the client ids that `<env>/app` needs. The redirect URI is step 8.
- `budget-and-roles.sh` creates the custom role `ACS Email Sender` (`Microsoft.Communication/CommunicationServices/Read` and `Microsoft.Communication/EmailServices/write`; the exact minimum is an open question in the spine) and the $8 subscription budget with an alert to `ALERT_EMAIL`. An existing budget is left unchanged.

### Step 2 extra: verify the email domain, then link it

`shared/foundation` creates the ACS Email service with Dj's custom domain but does not link it, because Azure refuses to link an unverified domain.

1. After the first apply, read `terraform output email_domain` and add the listed DNS records (Domain, SPF, DKIM, DKIM2) at the DNS host.
2. Start verification for each record type, e.g. `az communication email domain initiate-verification --domain-name <domain> --email-service-name babaloo-sea-lng-ecs-21 --resource-group babaloo-sea-lng-rg-21 --verification-type Domain` (repeat for `SPF`, `DKIM`, `DKIM2`).
3. When all are `Verified`, set `email_domain_link_enabled = true` in `infra/shared/foundation/terraform.tfvars` and apply again.

### Step 3: conditioned RBAC Administrator on the shared DI and ACS

`rbac-step3.sh` gives each environment deploy identity RBAC Administrator on the Document Intelligence account (may assign only Cognitive Services User) and on the ACS resource (may assign only `ACS Email Sender`), only to service principals. `<env>/app` uses these to grant each environment's `pipeline` identity its runtime roles.

### Step 4b: PGP key pair (once per environment)

Precondition: the operator holds Key Vault Secrets Officer on the vault, for example:
`az role assignment create --assignee <your object id> --role "Key Vault Secrets Officer" --scope <vault id>`
(remove it afterwards if you want).

`pgp-step4b.sh` generates an RSA 3072 key pair with no passphrase in a throwaway `GNUPGHOME` under the gitignored `.work/` folder, stores the ASCII-armoured keys as `pgp-private-key` first and `pgp-public-key` last (both tagged `fingerprint=<key fingerprint>`), and deletes the local copies. If both secrets exist it does nothing; if only one exists it stops (a new pair would make existing ciphertext unreadable). Terraform never manages these two secrets.

### Step 5: database logins (once per environment)

`database-step5.sh` connects to the server's `postgres` database as the Entra admin (`PG_ADMIN_USER`, not Dj's load-script user) with an `az` token and runs `database-step5.sql`:

- creates the environment's logins with `pgaadauth_create_principal`: the `pipeline`, `staff-api` and `accounts-sim` identities, the deploy identity, and Dj's user (`supplier-api` has none);
- makes the deploy identity the owner of `invoicing_<env>`, in one transaction with the temporary role membership it needs;
- revokes `CONNECT` and `TEMPORARY` from `PUBLIC` on both databases;
- grants `CONNECT` on `invoicing_<env>` to that environment's logins only.

It then gives Dj's user Key Vault Secrets User on the vault and Storage Table Data Contributor on the storage account, for the load script. Schema grants are Alembic migrations (step 6), not part of this step.

`verify-db-isolation.sh` checks, as the admin, that both databases exist, that `PUBLIC` cannot connect to either and that each environment login can connect to its own database and not the other (PASS/FAIL per check, exit 1 on any FAIL). To prove a real refusal, run it inside a Dev pipeline job signed in as the dev deploy identity with `CONNECT_AS_LOGIN=babaloo-sea-lng-id-22 TARGET_DB=invoicing_prod`.

Dj's user is one login on the shared server and is granted `CONNECT` by both environments, so it is left out of the cross-check.

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

The pipeline (Story 1.2) runs it after every plan and before any apply.
