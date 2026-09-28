# Review: verification of committed decisions

- **Target:** `ARCHITECTURE-SPINE.md` (draft, 2026-09-28)
- **Lens:** was each committed decision checked against current sources, or asserted from memory? Only claims *not* already verified in `.memlog.md` (versions, DI F0 quotas, Flex free grant, PG Entra/backup/pgcrypto existence, blob lifecycle, SWA plan features) were checked.
- **Method:** Microsoft Learn pages (most revised Aug-Sep 2026), prices.azure.com retail API (southeastasia), and upstream source code. Checked on 2026-09-28.

## Verdict

Most platform claims hold up. But **two decisions rest on facts that are wrong or out of date**:

- AD-16's notifier, ACS Email, was announced for retirement in September 2026, and the default Azure-managed domain is throttled to 10 emails an hour.
- AD-17's log cap allows about 6 times the free ingestion allowance.

Several other ADs are missing configuration prerequisites that the platform requires (the queue `newBatchThreshold`, the DI custom subdomain, the pgcrypto allow-list and the Entra "assignment required" setting). Fix the two High items before stories are cut.

## Findings

### F1 (High): AD-16. ACS Email is retiring, and its default domain can't carry the planned volume

- **What the spine says:** "Only `adapters/email.py` (Azure Communication Services Email, with managed identity) sends mail." The cost is under $0.01. The only open point is residency.
- **What the sources say:**
  - Microsoft lists **ACS Email under "Retired"**. It is in maintenance mode, with "security and critical fixes only", and retires on **30 September 2028**. Microsoft says: "We recommend using the two-year retirement period to migrate existing workloads off ACS Email rather than onboarding new solutions." Onboarding "is subject to change at any time."
  - **Azure-managed domains** allow **5 emails a minute and 10 an hour per subscription**. These limits can't be raised, and the domains are "intended for testing purposes only". Dev and Prod share one subscription (AD-17), so they share those 10 an hour.
  - **Custom domains** allow 30 a minute and 100 an hour. Raising those limits needs a support ticket and a failure rate below 1%.
  - Managed-identity (Entra) auth for `EmailClient` **is** supported (confirmed).
- **Impact:** CAP-13's Monday reminder batch to all suppliers, plus the CAP-14/15 staff alerts, can exceed 10 an hour on a managed domain. The PoC would also be built on a service Microsoft advises against for new work.
- **Fix:**
  - Re-open AD-16 as an `[ASSUMPTION]` decision.
  - If ACS stays for the PoC, require a **verified custom domain** (DNS on a domain Dj owns, $0), throttle sends in the adapter to stay under 30 a minute and 100 an hour, and add "ACS Email retires 2028-09-30" to Deferred.
  - Note that Microsoft's replacement, M365 High Volume Email, covers **internal recipients only**, so it can't reach suppliers. The alternatives are a Marketplace provider (Infobip, Telesign) or another SMTP/API provider behind the same port.
  - The port-and-adapter rule (P-4) already contains the change. Only the adapter choice and its cost line move.
- **Sources:**
  - https://learn.microsoft.com/en-us/azure/communication-services/acs-retirement-and-breaking-changes-guide
  - https://learn.microsoft.com/en-us/azure/communication-services/concepts/service-limits#email
  - https://learn.microsoft.com/en-us/azure/communication-services/concepts/email/email-quota-increase
  - https://learn.microsoft.com/en-us/python/api/overview/azure/communication-email-readme?view=azure-python

### F2 (High): AD-17. The log caps don't hold the "about $0" cost

- **What the spine says:** each environment has one Log Analytics workspace and one App Insights instance, with "a 0.5 GB/day cap and 30-day retention". The cost is "about $0, within the free ingestion allowance."
- **What the sources say:**
  - The free allowance is "the first **5 GB/month per billing account**" for Analytics Logs. It is shared by every workspace on the account, not granted per workspace.
  - Above that, ingestion costs **$2.99/GB** in southeastasia (retail API, tier minimum 5 GB).
  - Analytics Logs include 31 days of retention, so 30-day retention is free (confirmed).
- **Arithmetic:** 0.5 GB/day × 30 days × 2 environments = 30 GB/month allowed. That is 25 GB above the free allowance, or about **$75/month at worst**, which is 7 times P-2. The caps prevent a runaway, but they don't keep the cost at $0.
- **Fix:**
  - Set the daily cap to about **0.08 GB/day per environment** (about 2.4 GB/month each), or 0.15 GB/day if Dev and Prod share one workspace.
  - Enable App Insights sampling.
  - Keep the $8 budget alert as the backstop.
- **Sources:**
  - https://azure.microsoft.com/en-us/pricing/details/monitor/
  - https://learn.microsoft.com/en-us/azure/azure-monitor/logs/cost-logs
  - `https://prices.azure.com/api/retail/prices?$filter=serviceName eq 'Log Analytics' and armRegionName eq 'southeastasia'` (Analytics Logs Data Ingestion: $0 for the first 5 GB, then $2.99/GB)

### F3 (Medium): AD-8 and AD-2. "Max instances 1 and batch size 1" doesn't guarantee one call at a time, and DI needs a custom subdomain for managed identity

**Queue concurrency**

- The Queue binding runs up to **`batchSize` + `newBatchThreshold`** messages at once for each function.
- The default `newBatchThreshold` is `N*batchSize/2`. To be sure of a single execution, set `"batchSize": 1, "newBatchThreshold": 0` explicitly.
- These `host.json` settings apply to **every queue function in the `pipeline` app**, so the quality, validate and post stages also become serial. That is acceptable at PoC volume, but the spine should say so.

**Max instances**

- The lowest Flex max-instance value is now **1**, so the spine's setting is valid (confirmed).
- However, the maximum instance count "applies to each independently-scaling function group". Queue functions each scale in their own group (`function:<name>`), so max instances 1 gives **each** stage one instance. This works for `extract`, but the rule should be written that way.
- The alternative is to move `extract` into its own app.

**Polling rate**

- F0 has separate limits: **1 TPS for analyze (POST) and 1 TPS for Get (poll)**. The adapter's combined limit of 1 request a second is safe.
- Microsoft also recommends polling "not ... more than once every 2 seconds", and honouring `retry-after`. Add both to the adapter rule.

**Managed identity auth**

- "Regional endpoints don't support Microsoft Entra authentication. You need to create a **custom subdomain**."
- In Terraform, `azurerm_cognitive_account` needs `custom_subdomain_name`.
- Both the Dev and Prod `pipeline` identities need **Cognitive Services User** on the shared resource.

**Scope of the F0 limit (minor)**

- The quota table says "Maximum number of Document Intelligence resources per **region**: 1" for F0.
- The memlog says "per subscription". The practical effect is the same in single-region southeastasia.

**Sources:**

- https://learn.microsoft.com/en-us/azure/azure-functions/functions-bindings-storage-queue#hostjson-settings
- https://learn.microsoft.com/en-us/azure/azure-functions/flex-consumption-plan (Considerations: "The lowest maximum scale is currently `1`", and the maximum instance count section)
- https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/service-limits?view=doc-intel-4.0.0
- https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/authentication/managed-identities?view=doc-intel-4.0.0

### F4 (Medium): AD-14. Security Defaults MFA is "when necessary", and the token is open to the whole tenant unless assignment is required

**How Security Defaults applies MFA**

- Security Defaults requires every user to *register* for MFA. After that, "Microsoft decides when a user is prompted for multifactor authentication, based on factors such as location, device, role, and task".
- It does **not** force MFA at every sign-in for non-admins, and only Microsoft Authenticator (or OATH TOTP) is allowed.
- If P-19 means "MFA on every staff sign-in", Entra ID Free can't enforce it without Conditional Access (P1). Record it as a departure accepted by Dj, or reword P-19 to "MFA-registered, risk-prompted".

**Who can get a token**

- Easy Auth provides "only authentication, not authorization". By default "any user in your Microsoft Entra tenant can request a token for your application".
- The spine should require **"Assignment required = Yes"** on the enterprise app. This works on Entra ID Free, where individual user-to-app-role assignment is supported and group assignment needs P1 (confirmed).
- The spine's rule that every route checks its role in code is correct and necessary.

**Confirmed**

- Built-in auth and CORS are both supported on Flex Consumption (the migration guide says to "recreate" both).
- SWA Free allows 10 apps per subscription; the spine uses 4. Invitation roles are capped at 25.
- Calling a separate Functions origin directly from the browser with CORS works on any SWA plan. Only "linked backends" need Standard.

**Not confirmed (test early)**

- Does a CORS preflight (`OPTIONS`) pass when Easy Auth is set to "require authentication" on Flex? No Learn statement was found. Spike it in the first story. If the preflight is blocked, exclude `OPTIONS` or use `excludedPaths` through file-based configuration.

**Sources:**

- https://learn.microsoft.com/en-us/entra/fundamentals/security-defaults
- https://learn.microsoft.com/en-us/azure/app-service/overview-authentication-authorization
- https://learn.microsoft.com/en-us/entra/identity/enterprise-apps/assign-user-or-group-access-portal
- https://learn.microsoft.com/en-us/azure/azure-functions/migration/migrate-plan-consumption-to-flex
- https://learn.microsoft.com/en-us/azure/static-web-apps/quotas
- https://learn.microsoft.com/en-us/azure/static-web-apps/functions-bring-your-own

### F5 (Medium): AD-11. pgcrypto needs allow-listing, and the per-app database role model is underspecified

**Allow-listing**

- On Flexible Server, an extension must be allow-listed in the `azure.extensions` server parameter before `CREATE EXTENSION` works.
- In Terraform, set it with `azurerm_postgresql_flexible_server_configuration`.
- Azure Linux 3.0 hosts also disable OpenSSL "legacy" algorithms for pgcrypto. `pgp_sym_encrypt` defaults to AES-128 and is unaffected, but don't pick a legacy cipher.

**Multiple managed identities**

- These are confirmed: each identity becomes its own role through `pgaadauth_create_principal[_with_oid]` (service principal type).
- **But** a Function app connects as one identity. Two rules can't both hold without more identities:
  - "Only the `staff-api` admin role decrypts": other staff-api roles would share the same database login.
  - "The purchasing adapter's own database role" inside `pipeline`: the pipeline app would need a second login.
- Either state that these are app-level checks, or give `staff-api` and `pipeline` a second user-assigned identity for those paths. A Function app can carry several user-assigned identities.

**Key exposure**

- Passing the key into `pgp_sym_encrypt(..., key)` sends it to the server as a query parameter. It can appear in the server logs if `log_statement` or error logging captures parameters.
- Either keep logging of parameters off (a rule), or encrypt in the application with the Python `cryptography` library and store only the ciphertext. That would also remove the pgcrypto dependency.

**Sources:**

- https://learn.microsoft.com/en-us/azure/postgresql/extensions/how-to-allow-extensions
- https://learn.microsoft.com/en-us/azure/postgresql/extensions/concepts-extensions-considerations
- https://learn.microsoft.com/en-us/azure/postgresql/security/security-manage-entra-users

### F6 (Medium): AD-7 and AD-12. Two stop and retry details are wrong

- **The server restarts itself after 7 days.** "After you stop the ... flexible server, it automatically starts after seven days."
  - Nights and weekends are fine.
  - A holiday stop longer than 7 days silently restarts the server and bills compute.
  - Add a note, or a scheduled stop through an automation task.
- **The TTL resets on every re-enqueue.** AD-7 re-enqueues "an identical message", and each new message gets a fresh 7-day TTL.
  - "Until message TTL 7 days" therefore never ends, and the loop is unbounded.
  - Carry `first_enqueued_at` in the message (a change to AD-2's "exactly `{invoice_id, correlation_id}`") or in the blob metadata, and go to the admin queue after 7 days.
- **Encoding and delay (confirmed).** `QueueClient.send_message(visibility_timeout=...)` supports the 15-minute delay.
  - The Functions trigger expects **base64** by default (`messageEncoding`).
  - Set `TextBase64EncodePolicy` on the SDK client, or set `messageEncoding: none`, so re-enqueued messages don't fail to decode.

**Sources:**

- https://learn.microsoft.com/en-us/azure/postgresql/configure-maintain/how-to-stop-server
- https://learn.microsoft.com/en-us/azure/azure-functions/functions-bindings-storage-queue#hostjson-settings
- https://learn.microsoft.com/en-us/python/api/azure-storage-queue/azure.storage.queue.queueclient?view=azure-python

### F7 (Low): AD-9 and Conventions. DI field names hold, but there is no "printed supplier ID" field, and phash ignores EXIF rotation

**DI field names (prebuilt-invoice, 2024-11-30 schema)**

- These fields are confirmed: `InvoiceId`, `InvoiceDate`, `InvoiceTotal` (currency), `VendorName`, `VendorTaxId`, `PurchaseOrder`, `CustomerId`, and `PaymentDetails[]` with `IBAN`, `SWIFT`, `BankAccountNumber`, `BPayBillerCode` and `BPayReference`.
- The `invoice_id → invoice_number` rename in Conventions is sound.
- **There is no generic "supplier ID" field.** `SUPPLIER_ID_MISMATCH` (AD-5) must be defined against `VendorTaxId` (for example a UEN or GST number) or a custom-model field. CAP-8 bank details come from `PaymentDetails`.

**ImageHash**

- `phash(image, hash_size=8, ...)` gives a 64-bit hash (confirmed in the source), and `hash1 - hash2` is the Hamming distance.
- The library does **not** handle EXIF orientation. Apply `PIL.ImageOps.exif_transpose` before hashing, or the same invoice photographed in portrait and in landscape won't match.
- The threshold of 8 remains unverified, as the spine already notes. The README gives no guidance.

**Sources:**

- https://github.com/Azure-Samples/document-intelligence-code-samples/blob/main/schema/2024-11-30-ga/invoice.md
- https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/prebuilt/invoice?view=doc-intel-4.0.0
- https://github.com/JohannesBuchner/imagehash (and `imagehash/__init__.py`, `def phash(image, hash_size=8, highfreq_factor=4)`)

## Confirmed with no change needed

| Claim (AD) | Result | Source |
| --- | --- | --- |
| Flex Consumption available in southeastasia (AD-1) | Confirmed. Southeast Asia was in the GA region set. Recheck with `az functionapp list-flexconsumption-locations` | https://techcommunity.microsoft.com/blog/appsonazureblog/azure-functions-flex-consumption-is-now-generally-available/4298778 |
| Flex has one app per plan, no `WEBSITE_TIME_ZONE`, Python 3.13 (AD-1) | Confirmed. Note: the minimum billable execution is 1,000 ms, which still fits the grant | https://learn.microsoft.com/en-us/azure/azure-functions/flex-consumption-plan |
| Storage Queue `maxDequeueCount` 5 goes to `<queue>-poison` (AD-2) | Confirmed (default 5). The `q-admin` sink needs a trigger on each `-poison` queue | https://learn.microsoft.com/en-us/azure/azure-functions/functions-bindings-storage-queue |
| Table Storage with managed identity from Functions (AD-6) | Confirmed: `TableServiceClient` with a token credential, role **Storage Table Data Contributor** (Contributor or Owner is not enough) | https://learn.microsoft.com/en-us/azure/storage/tables/authorize-access-azure-active-directory |
| Table Storage cost of about $0.01 (AD-6) | Confirmed: Standard LRS $0.00036 per 10K operations, $0.045/GB | prices.azure.com (Storage, Tables, southeastasia) |
| Entra ID Free supports app roles assigned to individual users, and group assignment needs P1 (AD-14) | Confirmed | https://learn.microsoft.com/en-us/entra/identity/enterprise-apps/assign-user-or-group-access-portal |
| PostgreSQL Entra auth with many managed identities (AD-11) | Confirmed | https://learn.microsoft.com/en-us/azure/postgresql/security/security-manage-entra-users |
| DI F0 limits of 1 TPS analyze and 1 TPS get, 2 pages, 4 MB (AD-8) | Confirmed | https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/service-limits?view=doc-intel-4.0.0 |
| Azure DevOps workload identity federation service connection driving Terraform (AD-17) | Confirmed: AzureCLI task with `addSpnToEnvironment` exposes `idToken`, which feeds `ARM_USE_OIDC`/`ARM_OIDC_TOKEN`. Microsoft publishes a sample | https://learn.microsoft.com/en-us/samples/azure-samples/azure-devops-terraform-oidc-ci-cd/azure-devops-terraform-oidc-ci-cd/ ; https://devblogs.microsoft.com/devops/introduction-to-azure-devops-workload-identity-federation-oidc-with-terraform/ |
| Key Vault costs about $0.03 a month (AD-11) | Confirmed: Standard operations cost $0.03 per 10K. Cache secrets per instance so the cost stays at cents | prices.azure.com (Key Vault, southeastasia) |
| ACS Email supports managed identity (AD-16) | Confirmed, but see F1 | https://learn.microsoft.com/en-us/azure/communication-services/how-tos/managed-identity |

## Not confirmed

- A CORS preflight passing through Easy Auth with "require authentication" on Flex (F4). Spike it.
- DI API 2024-11-30 serving `prebuilt-invoice` in southeastasia. Only indirect evidence was found (the region is listed for DI, and a Q&A thread shows a southeastasia resource using 2024-11-30). Confirm when the resource is created.
- The phash Hamming threshold of 8 (AD-9). This is an empirical choice.
