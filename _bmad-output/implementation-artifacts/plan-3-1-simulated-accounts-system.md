---
title: 'Story 3.1: Simulated accounts system'
type: 'feature'
ticket: '3-1-simulated-accounts-system'
created: '2026-09-30'
status: 'built'
route: 'full'
route_source: 'auto'
baseline_revision: 'b71ab725997aed2e9249cd7ccac17f27dc660717'
review: 'thorough'
review_source: 'auto'
lenses_ran: ['edge-case-hunter', 'verification-gap']
review_loop_iteration: 0
context:
  - '{project-root}/docs/standards/coding-style.md'
  - '{project-root}/docs/standards/security.md'
  - '{project-root}/docs/standards/terraform.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Posting (3.2) has nothing to post to: the on-premises accounts link doesn't exist, and the `accounts-sim` app is an empty shell with no auth.

**Approach:** Turn `accounts-sim` into a simulated accounts XML API behind the AD-10 contract: `POST /api/invoices` validates an invoice XML document against `adapters/accounts_xml/invoice-v1.xsd`, stores it once per `invoice_id` in `sim_accounts` and returns its `accounts_ref`; only its own environment's `pipeline` identity may call it (built-in auth plus an in-code check); a failure mode makes it return errors for end-to-end retry tests.

## Boundaries & Constraints

**Always:** built-in auth on `accounts-sim` (own app registration, audience `api://<accounts_sim_client_id>`, `allowedPrincipals.identities` = this environment's `pipeline` principal id, unauthenticated → 401); in code, fail closed in Azure when built-in auth is off, and refuse any caller whose `X-MS-CLIENT-PRINCIPAL-ID` is not the configured pipeline principal id; XML parsed only in `adapters/accounts_xml/` with entity expansion and network access disabled (xmlschema `defuse="always"`), body size capped; `sim_accounts` read/write for the accounts-sim login only (AD-11), with the migration role argument required like the others; idempotent on `invoice_id` (unique); no bank data in the XSD or the store; no field values in logs; bound parameters.

**Never:** the pipeline's post stage or `AccountsPort` (3.2); a Prod client id value (Prod tfvars stay commented, like staff-api); a health route change to the deploy loop; more than **3** new test cases.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Post | valid invoice XML from the pipeline identity | stored in `sim_accounts.invoice`, 201 with XML `<result><accounts_ref>SIM-000123</accounts_ref></result>` | — |
| Repeat | same `invoice_id` again (any body) | 200 with the same `accounts_ref`; no second row | race: unique constraint → re-read and return the stored ref |
| Invalid XML / schema | malformed, wrong namespace, missing field, bad decimal | 400 with a code (`XML_INVALID`); nothing stored | entity/DTD payload refused, never expanded |
| Too large | body > 256 KB | 413 | — |
| Unauthenticated | no token | 401 (platform) | — |
| Wrong principal | a human user, another identity, the other environment's pipeline | 403 (platform `allowedPrincipals`, and in code) | nothing stored |
| Auth off in Azure | `WEBSITE_AUTH_ENABLED` not true on an Azure site | 401 `AUTH_DISABLED` | — |
| Failure mode | `sim_accounts.failure_mode.fail_next = N`, `status = 503` | the next N calls return that status (decrementing), then normal | — |

</frozen-after-approval>

## Code Map

- `backend/src/invoicing/apps/accounts_sim/function_app.py`, `settings.py` -- empty shell today; add settings (`postgres_host/database/user`, `pipeline_principal_id`, `platform auth trusted` like staff-api) and the route (`host.json` default `api/` prefix).
- `backend/src/invoicing/apps/common.py` -- `HostName`, `PgName`, `load_settings`, `start_telemetry`; `apps/staff_api/function_app.py` + `apps/staff_api/settings.py` (Story 2.8) for the engine and the `WEBSITE_AUTH_ENABLED` fail-closed pattern; `adapters/principal.py` (staff-shaped; read its fail-closed logic, don't reuse `StaffPrincipal`).
- `backend/src/invoicing/adapters/http.py` -- `http_endpoint`, `json_response`, `error_response` (add an XML response helper or build the XML body here).
- `backend/src/invoicing/adapters/postgres/engine.py` -- `postgres_engine`, `entra_token_provider`, `open_connection`.
- `backend/migrations/versions/0002_sim_purchasing.py` -- schema/grant pattern; latest is `0008_extraction_pages` → new `0009_sim_accounts.py`.
- `backend/migrations/env.py` (`ROLE_ARGUMENTS`), `ci/migrate.sh` (lines ~62-77, `app_identity_name "$env" accounts-sim`), `backend/tests/conftest.py` (`PostgresServer` roles, `alembic()` `-x` args, `APP_ONLY_SETTINGS`).
- `backend/pyproject.toml` / `uv.lock` -- add `xmlschema` (exact pin); import-linter contract like `purchasing-sim-is-private` so only `adapters/accounts_xml` imports it.
- `infra/modules/env-app/main.tf` -- `locals.staff_api_auth` + `azapi_update_resource.staff_api_auth` (authsettingsV2 pattern, `data.azapi_client_config`); `app_specific_settings.accounts_sim` (add POSTGRES_* with `var.identities["accounts_sim"].name`, `PIPELINE_PRINCIPAL_ID`); `variables.tf` (`staff_api_client_id` validation to copy); `outputs.tf`.
- `infra/{dev,prod}/app/variables.tf`, `main.tf`, `terraform.tfvars` -- `accounts_sim_client_id` (dev `5ab1d364-f5e2-4b82-911b-9b359855781f`, from `app-registrations.sh`; prod commented); tftests (`env_app.tftest.hcl` staff-auth asserts ~310-372 and settings key sets ~386; dev/prod `app.tftest.hcl`).
- `infra/bootstrap/README.md` -- step telling the operator to put the accounts-sim client id in tfvars.

## Tasks & Acceptance

**Execution:**
- [x] `backend/src/invoicing/adapters/accounts_xml/invoice-v1.xsd` + `adapters/accounts_xml/__init__.py` -- the contract (namespace `urn:ocrinvoicing:accounts:invoice:v1`; `invoice_id`, `supplier_id`, `invoice_number`, `invoice_date`, `currency`, `po_number`, `sub_total`, `total_tax`, `invoice_total`, lines with `line_no`, `material_id`, `description`, `quantity`, `unit_price`, `amount`); a parse/validate function returning a typed invoice (Decimals) and an XML builder the pipeline will use in 3.2.
- [x] `backend/migrations/versions/0009_sim_accounts.py` -- `sim_accounts.invoice(accounts_ref PK, invoice_id UNIQUE, supplier_id, invoice_number, invoice_total, document xml/text, created_at)`, a ref sequence, `sim_accounts.failure_mode(id=1 check, fail_next int ≥ 0, status int)`; grants to the accounts-sim role only; `accounts_sim_role` wired in `env.py`, `ci/migrate.sh`, conftest.
- [x] `backend/src/invoicing/apps/accounts_sim/*` -- settings, engine, principal check, failure mode, `POST api/invoices`.
- [x] Terraform: accounts-sim built-in auth resource, settings, variable, outputs, tftest asserts (no new `run` blocks); README step.
- [x] Tests (≤ 3 new cases): one app test against PG as the accounts-sim login (post, repeat, invalid/XXE/too large, wrong principal, auth off, failure mode, other logins refused on `sim_accounts`); XSD round-trip assertions inside it or one pure test.

**Acceptance Criteria:**
- Given `ci/checks.sh all`, then it passes with ≤ 200 test cases.

## Implementation Notes

- The contract code lives in `adapters/accounts_xml/contract.py`, not `__init__.py`: ci/tests' coverage fixture copies every `__init__.py` as a bare package marker, so code there skews its measured percent. `__init__.py` is a docstring only.
- Adapter API: `parse_invoice(bytes) -> AccountsInvoice` (Decimals, UUIDs, `date`), `build_invoice_xml(AccountsInvoice) -> bytes` (encodes through the XSD, so an invalid value raises `XmlInvalidError`; never rounds: money with more than 2 decimals, quantity with more than 3, non-finite or unscalable values, XML-illegal characters and non-normalised token fields are refused). `parse_invoice` strips namespace prefixes (a prefixed valid document parses); the XSD `Date` type allows no timezone, `result_xml(accounts_ref)`. `po_number` is required and lines are 1..500 with unique `line_no`.
- New error codes: `XML_INVALID` (400, `XmlInvalidError`) and `SIMULATED_FAILURE` (the failure mode's body code; its HTTP status is the row's `status`, constrained 400-599).
- Failure mode is checked after the caller check and before the body is read (a refused caller never uses up a failure); one `UPDATE ... WHERE fail_next > 0 RETURNING status`, so concurrent calls never over-fail.
- Idempotency: `INSERT ... ON CONFLICT (invoice_id) DO NOTHING RETURNING accounts_ref`, then re-read in the same transaction (covers the race). `accounts_ref` = `SIM-` + sequence zero-padded to at least 6 digits, widening past 999999 (server default; `lpad` would truncate, `to_char` prints `######`). Documents must be UTF-8 (400 otherwise); a BOM is dropped (`utf-8-sig`) before storing as text. Simulated 429/503 carry `Retry-After: 5`.
- `PlatformAuthSettings` (apps/common.py) now holds `WEBSITE_SITE_NAME`/`WEBSITE_AUTH_ENABLED` and `platform_auth_trusted`; staff-api and accounts-sim settings both extend it. `invoices_endpoint` takes `platform_auth_trusted` as a required keyword (no trusting default).
- Grants (0009): accounts-sim login gets USAGE on the schema, SELECT+INSERT on `invoice`, SELECT+UPDATE on `failure_mode`, USAGE on the sequence; nobody else anything. `-x accounts_sim_role` is now required by env.py (ci/migrate.sh passes `app_identity_name <env> accounts-sim`: id-04 Dev, id-14 Prod). conftest's `outsider` login is renamed `accounts_sim` (same role name).
- Terraform: `azapi_update_resource.accounts_sim_auth` (Return401, issuer `https://sts.windows.net/<tenant>/v2.0`, audience `api://<client id>`, `allowedPrincipals.identities = [pipeline principal id]`, token store off); `accounts_sim` app settings add POSTGRES_* and `PIPELINE_PRINCIPAL_ID`; outputs `accounts_sim_auth` and `accounts_sim_app_settings`; asserts added to existing runs only.
- Import-linter: `include_external_packages = true` and contract `accounts-xml-is-private`; `tests/test_story_2_4_import_rule.py` now expects 2 contracts and proves an `xmlschema` import elsewhere breaks.
- Tests: 2 new cases (`tests/adapters/test_story_3_1_accounts_xml.py`, `tests/apps/test_story_3_1_accounts_sim.py`); repo total 182 of 200.

## Plan Change Log

## Review Triage Log

Pass 1 (2026-09-30, unattended). Lenses one at a time: edge-case-hunter, verification-gap. Verdicts: high 1, medium 8, low 3, false 0.

| # | Lens | Finding | Verdict | Route | Evidence |
|---|------|---------|---------|-------|----------|
| E2/V3 | both | `build_invoice_xml` silently rounds money (109.005 → 109.00) and quantities instead of refusing | high | patch | an amount different from the extracted one could be posted with no error (coding-style rule 4) |
| E1 | edge | Infinity / 1E+30 raises an uncaught InvalidOperation in the builder | medium | patch | probe confirmed |
| E3 | edge | XML-illegal control characters make the builder emit a malformed document | medium | patch | OCR text can carry them |
| E4 | edge | XSD-valid namespace-prefixed document decodes with prefixed keys → 400 | medium | patch | a conforming sender is refused |
| E5 | edge | XSD-valid date with a timezone → 400 | medium | patch | restrict the XSD date pattern |
| E6 | edge | xs:token collapses whitespace, so sim and pipeline references can silently differ | medium | patch | refuse non-normalised tokens in the builder |
| E7/E8/E12 | edge | `lpad` truncates past 999999 → duplicate `accounts_ref` → permanent 500 | medium | patch | `to_char(…,'FM000000')` style without truncation |
| E9 | edge | Simulated 503 lacks Retry-After | low | patch | retry tests should match production |
| E10 | edge | A BOM is stored in the document text | low | patch | decode `utf-8-sig` |
| E11 | edge | (claim) conforming documents refused | medium | patch (E4/E5) | same root cause |
| V1 | gap | `auth.disabled` start-up log unasserted | low | patch | the operator's only signal |
| V2 | gap | Failure mode before the body is read unpinned | medium | patch | a malformed post during failure mode |

## Design Notes

Decisions made unattended (Dj asleep, 2026-09-30):
- **xmlschema** (pure Python, `defuse="always"`) over lxml: no binary wheel, safe defaults for XXE.
- **Two layers of caller check**: the platform's `allowedPrincipals` and an in-code comparison of `X-MS-CLIENT-PRINCIPAL-ID` with `PIPELINE_PRINCIPAL_ID`, failing closed when built-in auth is off in Azure (same rule as staff-api, without the default-to-trusted slip noted in deferred-work).
- **Failure mode lives in the database** (`sim_accounts.failure_mode`), so it can be switched on without a redeploy (operator SQL as the accounts-sim login or admin).
- **XML response** (`<result><accounts_ref/>`), 201 on first store, 200 on repeat.
- **No bank data** in the XSD: the accounts system pays from its own supplier master.
- [ASSUMPTION] Managed-identity tokens are v1 (`sts.windows.net` issuer); built-in auth accepts both for Entra — confirm on Dev.

## Verification

**Commands:**
- `ci/checks.sh all` -- expected: all checks pass, test cases ≤ 200.
