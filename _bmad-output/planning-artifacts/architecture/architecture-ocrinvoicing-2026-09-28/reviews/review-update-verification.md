# Review: verification of the updated spine's committed decisions

- **Target:** `ARCHITECTURE-SPINE.md` (status final, updated 2026-09-28). Line references are `S:<line>`.
- **Lens:** was each committed decision web-researched or reality-checked, or was it asserted from memory? The focus is on what the latest update added or depends on.
- **Method:** Microsoft Learn pages (most revised Aug–Sep 2026), the Azure retail prices API (southeastasia), PyPI and npm registry JSON, and upstream schema files. Everything was checked on 2026-09-28. The spine itself was not edited.

## Verdict

Most platform facts and every pinned version check out. However, one update-era decision is wrong on the platform's own terms, and one stack pin breaks a mandatory toolchain rule:

- **AD-2 / AD-1 (High).** `batchSize 1` + `newBatchThreshold 0` does **not** make a stage handle one message at a time on Flex Consumption. Flex uses `batchSize` as the *target executions per instance*, so a queue of N messages asks for about N instances, and the spine sets no maximum instance count. That breaks AD-8's rate limit ("1 request every 2 seconds in each environment") and puts the B1ms connection limit at risk.
- **Stack (High).** TypeScript **7.0.2** has no programmatic API, and `typescript-eslint` (required by `coding-style.md` rule 19) declares a peer range of `typescript <6.1.0`.

There are also four Medium items (queue message encoding for the re-enqueue path, the ACS role, DI currency and locale support, and the unconfirmed `X-Requested-With` → 401 behaviour) and several Low items.

## Findings

### F1 (High): AD-2 / AD-1 / AD-8. `batchSize 1` causes scale-out on Flex and doesn't serialise stages. No maximum instance count is set.

- **What the spine says:**
  - S:95: "`host.json` settings for the `pipeline` app are `batchSize` 1 and `newBatchThreshold` 0, so every stage handles one message at a time."
  - S:66: "All four use on-demand instances only." No maximum instance count is set anywhere.
  - S:211: "The adapter sends at most 1 request every 2 seconds in each environment, polling calls included."
- **What the sources say:**
  - Queue `host.json`: `batchSize` 1 "eliminates concurrency as long as your function app runs only on a single virtual machine (VM). If the function app scales out to multiple VMs, each VM could run one instance of each queue-triggered function." (functions-bindings-storage-queue, updated 2026-09-18). The `batchSize` + `newBatchThreshold` formula itself is confirmed.
  - Target-based scaling is **on by default for Flex**, and for Storage Queues "modify the host.json setting `batchSize` to set *target executions per instance*". So `batchSize` 1 means one instance per queued message.
  - Also: "messages with visibilityTimeout are still counted in event source length … This can cause overscaling". AD-7's 15-minute delayed re-enqueues (S:195) therefore also drive scale-out while the database is stopped.
  - Flex scales each queue function in its own group (`function:<name>`). The maximum instance count "applies to each independently-scaling function group", and the lowest allowed value is `1`.
- **Impact:**
  - A burst of uploads makes `extract` run on several instances at once. A per-process rate limiter then can't hold "1 request every 2 seconds", so DI F0 returns 429s (1 TPS for Analyze, 1 TPS for Get).
  - The `validate` advisory lock still protects correctness, but concurrency is not what the spine claims.
  - Many instances each open PostgreSQL connections against a B1ms server.
- **Fix:**
  - Set `maximumInstanceCount = 1` on the `pipeline` Flex app. It applies per function group, so each stage gets at most one instance.
  - Keep `batchSize` 1 and `newBatchThreshold` 0.
  - Reword S:95 to say "one message at a time per stage, *given* max instances 1".
  - Optionally cap `supplier-api` and `staff-api` too, to bound connections.
- **Sources:**
  - https://learn.microsoft.com/en-us/azure/azure-functions/functions-bindings-storage-queue#host-json
  - https://learn.microsoft.com/en-us/azure/azure-functions/functions-target-based-scaling
  - https://learn.microsoft.com/en-us/azure/azure-functions/flex-consumption-plan (per-function scaling, maximum instance count, "lowest maximum scale is currently 1")

### F2 (High): Stack. TypeScript 7.0.2 is incompatible with the mandated `typescript-eslint`

- **What the spine says:** S:505 pins `TypeScript | 7.0.2`. `docs/standards/coding-style.md` rule 19 requires "ESLint … + `typescript-eslint` recommended".
- **What the sources say:**
  - TypeScript 7.0 (the native Go compiler) went GA on 2026-07-08, and 7.0.2 is the npm `latest` (verified).
  - TypeScript 7.0 ships **without a stable programmatic API**, which is expected in 7.1.
  - `typescript-eslint@8.70.1` (npm latest) has `peerDependencies.typescript: ">=4.8.4 <6.1.0"` (verified from the registry). Its TS 7 support request was closed as "not planned" for now.
- **Impact:** a clean install either fails its peer dependency check or runs ESLint type-aware rules against an unsupported compiler. Rule 2 of `coding-style.md` makes a failing lint check block every PR.
- **Fix:** either
  - pin **TypeScript 6.0.3** (latest 6.0.x), or
  - keep 7.0.2 for `tsc` and alias TS 6 for ESLint (`@typescript/typescript6` / an npm alias), and record the dual pin in the Stack table.
- **Sources:**
  - https://devblogs.microsoft.com/typescript/announcing-typescript-7-0/
  - https://www.infoq.com/news/2026/08/typescript-7-released/
  - https://registry.npmjs.org/typescript-eslint/latest (peerDependencies)
  - https://mergify.com/blog/native-typescript-compiler-faster-typecheck

### F3 (Medium): AD-7 / AD-2. Re-enqueueing with a visibility delay needs the SDK, and the SDK's default encoding doesn't match the trigger's

- **What the spine says:** S:195: "re-enqueues the same message with a 15-minute visibility delay". The DI 429 path (S:199) and the posting backoff (S:111) also re-enqueue with a delay.
- **What the sources say:**
  - The Python `queue_output` binding can't set a visibility delay, so this path must use `azure-storage-queue` `QueueClient.send_message(..., visibility_timeout=…)`. That client sends **plain text by default**.
  - The Functions queue trigger docs say: "Functions expect a *base64* encoded string." The default `messageEncoding` is `base64`, and it is configurable only with extension bundle 4.x.
  - Poison handling and the `<queue>-poison` naming are confirmed ("adds a message to a queue named *<originalqueuename>-poison*"). `maxDequeueCount` 5 is the default (confirmed).
- **Impact:** without an encoding decision, messages that `supplier-api` or a re-enqueue writes through the SDK fail to decode at the trigger and go to poison, which routes them to `PROCESSING_FAILED`.
- **Fix:** add one line to AD-2: either "all producers use `TextBase64EncodePolicy`", or "`host.json` `messageEncoding: none` in every app", and use only one of the two.
- **Sources:**
  - https://learn.microsoft.com/en-us/azure/azure-functions/functions-bindings-storage-queue-trigger#usage
  - https://learn.microsoft.com/en-us/azure/azure-functions/functions-bindings-storage-queue#host-json

### F4 (Medium): AD-16 / AD-17 step 3. The ACS sending role is a broad built-in role or a custom role, and neither fits step 3 as written

- **What the spine says:**
  - S:365: ACS "with managed identity".
  - S:388: operators give deploy identities RBAC Administrator "conditioned to assigning only the runtime roles those resources need".
  - S:612 leaves "which built-in role lets a managed identity send" as open.
- **What the sources say:**
  - Managed-identity sending is supported.
  - Microsoft's documented options are the built-in **Communication and Email Service Owner** role, which gives "access to all Communication and Email service operations", or a **custom role** with `Microsoft.Communication/CommunicationServices/Read`, `…/Write` and `Microsoft.Communication/EmailServices/write`.
  - No narrower built-in "email sender" role appears in the Azure built-in roles list, which was searched on 2026-09-28.
  - RBAC Administrator can create and delete role assignments, but **not role definitions**. A custom role must therefore exist before the condition can name its GUID.
  - Constrained delegation itself is confirmed: conditions can restrict roles, principal types and principals, and the feature is free.
- **Fix:**
  - Close S:612: create a custom "ACS Email Sender" role in **step 1 (bootstrap)** at subscription scope.
  - Put its GUID and Cognitive Services User (`a97b65f3-24c7-4388-baec-2e87135dc908`) in the step-3 condition. Constrain the principal type to `ServicePrincipal` as well.
- **Sources:**
  - https://learn.microsoft.com/en-us/azure/communication-services/quickstarts/email/send-email-smtp/smtp-authentication
  - https://learn.microsoft.com/en-us/answers/questions/4370670/what-are-the-minimal-rbac-permissions-required-to
  - https://learn.microsoft.com/en-us/azure/role-based-access-control/delegate-role-assignments-overview
  - https://learn.microsoft.com/en-us/azure/role-based-access-control/built-in-roles

### F5 (Medium): AD-18 / AD-20. `prebuilt-invoice` doesn't list SGD or an English (Singapore) locale

- **What the spine says:** S:426 stores `currency` per field from DI. S:465 and S:598 say "in the invoice currency (SGD)" and "SGD only".
- **What the sources say:**
  - The 2024-11-30 invoice model's supported currency codes include USD, AUD, INR, IDR, THB, VND and others, but **not SGD**.
  - The English locales listed are us/au/ca/uk/in, with no `en-SG`.
  - Field names used by the spine are all confirmed in the 2024-11-30 schema: `PurchaseOrder`, `InvoiceId`, `VendorTaxId`, `SubTotal`, `TotalTax`, `InvoiceTotal`, `Items.*.ProductCode/Quantity/Unit/UnitPrice/Amount/Tax`, and `PaymentDetails.*.IBAN/SWIFT/BankAccountNumber`.
  - `PaymentDetails` is an **array**.
  - `Items.*.Tax` "possible values include tax amount, tax %, and tax Y/N".
- **Impact:**
  - A "$" on a Singapore invoice may come back as `USD` or with no code.
  - Several payment entries have no mapping to the single `bank_account_number`/`iban`/`swift` ids.
  - The line `tax` may not be an amount.
- **Fix:**
  - Set currency from configuration (SGD), not from DI. Treat a non-SGD symbol or code as a validation reason, or as `LOW_CONFIDENCE`.
  - Say that bank field ids use `PaymentDetails[<n>]` (or the first entry, and flag it when there are more).
  - Store line `tax` as text or ignore it.
  - Add "DI accuracy on SG invoices" to the test-early list (S:608).
- **Sources:**
  - https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/language-support/prebuilt?view=doc-intel-4.0.0#invoice
  - https://github.com/Azure-Samples/document-intelligence-code-samples/blob/main/schema/2024-11-30-ga/invoice.md

### F6 (Medium, unconfirmed): AD-14. "With `X-Requested-With`, built-in auth returns 401 instead of redirecting"

- **What the spine says:** S:339.
- **What the sources say:**
  - The App Service authentication docs (overview, file-based configuration, customize sign-in) document `unauthenticatedClientAction` values `RedirectToLoginPage`, `RejectWith401`, `RejectWith404` and `AllowAnonymous`, and CSRF checks based on `Origin`/`Referer`.
  - None of these pages mention `X-Requested-With`. I found no Microsoft source for the claimed 401 behaviour.
  - Community reports say the redirect-or-401 decision depends on User-Agent detection.
- **Confirmed around it:**
  - Built-in auth is supported on Flex. The migration guide says to recreate it on the new app.
  - `azurerm_function_app_flex_consumption` has `auth_settings_v2`.
  - A community Q&A reports that on Flex, `excludedPaths: ['/admin/*']` was needed after enabling auth with redirect. That is unconfirmed by Microsoft docs.
  - The session cookie's `SameSite` setting is not exposed in `authsettingsV2`, so S:338's `SameSite=Lax` is also unverified.
- **Fix:**
  - Move this to "To test early".
  - Give a fallback: the SPA calls `fetch(..., {redirect: 'manual'})` and treats an `opaqueredirect` as "signed out". Server-side CSRF enforcement (rejecting a non-GET without the header) stays in app code either way.
  - Record whatever cookie `SameSite` value the platform actually sets.
- **Sources:**
  - https://learn.microsoft.com/en-us/azure/app-service/overview-authentication-authorization
  - https://github.com/MicrosoftDocs/azure-docs/blob/main/articles/app-service/configure-authentication-file-based.md
  - https://learn.microsoft.com/en-us/azure/azure-functions/migration/migrate-plan-consumption-to-flex
  - https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/function_app_flex_consumption

### F7 (Low): AD-12 / AD-11. PostgreSQL logins are server-wide, not per database

- **What the spine says:** S:306: "Each environment's logins exist only in its own database". S:292: `pgaadauth_create_principal`.
- **What the sources say:**
  - PostgreSQL roles are cluster-wide.
  - `pgaadauth_create_principal(roleName, isAdmin, isMfa)` exists, and so does `pgaadauth_create_principal_with_oid(roleName, objectId, objectType, isAdmin, isMfa)`. The second is safer for user-assigned identities whose display names might collide.
  - Entra-only authentication mode is supported (confirmed).
  - The isolation actually comes from S:291 (`REVOKE CONNECT … FROM PUBLIC`) plus a per-environment `GRANT CONNECT`.
- **Fix:**
  - Reword S:306 to "each login has `CONNECT` only on its own environment's database".
  - Name `pgaadauth_create_principal_with_oid` for the managed identities.
- **Sources:**
  - https://learn.microsoft.com/en-us/azure/postgresql/security/security-manage-entra-users
  - https://learn.microsoft.com/en-us/azure/postgresql/security/security-entra-configure

### F8 (Low): AD-17 monitoring. The "log cap at 90%" alert and its cost

- **What the spine says:** S:411 has an alert on "log cap at 90%". S:415 costs the alerts at "about $0.30 a month for the metric alerts".
- **What the sources say:**
  - For a workspace, Microsoft documents a **log search alert** on `_LogOperation | where Detail contains "OverQuota"`, which fires when the cap is *reached*. The percentage warning threshold is a classic-App-Insights feature.
  - A 90% alert therefore needs a custom log search alert on the `Usage` table.
  - Log search alerts cost $0.50/month (15-minute frequency) to $1.50/month (5-minute) per rule in southeastasia (retail API). Metric alerts are $0.10 per time series after the first 10 free.
  - For workspace-based App Insights, "the effective daily cap is the minimum of the two settings", so set both. The cap "can't stop data collection at precisely the specified cap level", and excess is billed.
- **Fix:**
  - Use the documented OverQuota alert, or a `Usage`-based 90% query at 15-minute frequency.
  - Restate the cost as about $1–2/month for both environments.
  - Set the App Insights cap as well.
- **Sources:**
  - https://learn.microsoft.com/en-us/azure/azure-monitor/logs/daily-cap
  - https://prices.azure.com/api/retail/prices (Azure Monitor, southeastasia: "Alerts System Log Monitored at 15 Minute Frequency" $0.50; "Alerts Metric Monitored" $0.10 after 10)

### F9 (Low): AD-17. The custom metric `poison_message{queue}` dimension is dropped by default

- **What the sources say:**
  - OpenTelemetry custom metrics go to both `customMetrics` (logs) and the metric store. However, "the preaggregated version of the metric is stored by default with no dimensions".
  - Keeping dimensions is a **preview** opt-in with separate custom-metric billing.
  - The claim that Storage has no per-queue metric is **confirmed**: `QueueMessageCount` has dimension `<none>` and a 1-hour grain.
- **Fix:** alert on the undimensioned total (more than 0 in an hour is enough), and read the queue name from logs. Alternatively, accept the preview setting and its cost.
- **Sources:**
  - https://learn.microsoft.com/en-us/azure/azure-monitor/app/metrics-overview#custom-metrics-dimensions-and-preaggregation
  - https://learn.microsoft.com/en-us/azure/storage/queues/monitor-queue-storage-reference

### F10 (Low): AD-17. `terraform_remote_state` needs a data-plane grant on the shared state

- **What the spine says:** S:394: environment stacks read `shared/foundation` outputs.
- **What the sources say:**
  - The azurerm backend supports `use_oidc = true` and `use_azuread_auth = true` with Azure DevOps WIF, including service-connection ID token refresh in Terraform task v5. That part is confirmed.
  - Reading another stack's state with Entra auth needs **Storage Blob Data Reader** on that state container, and nothing in step 1 grants it.
  - The remote state also exposes *all* of `shared`'s state to the environment identities.
- **Fix:**
  - In step 1, grant each environment's deploy identity Blob Data Reader on the `shared` state container only.
  - Keep secrets out of `shared` outputs.
- **Sources:**
  - https://devblogs.microsoft.com/devops/introducing-azure-devops-id-token-refresh-and-terraform-task-version-5/
  - https://learn.microsoft.com/en-us/samples/azure-samples/azure-devops-terraform-oidc-ci-cd/azure-devops-terraform-oidc-ci-cd/

### F11 (Low / reality-check): AD-14. Serving the SPA from a Python function app

- **Status:** feasible, but no Microsoft-documented pattern. It uses an HTTP trigger on the catch-all route `{*path}` with `extensions.http.routePrefix: ""`. This is a community pattern.
- **Constraints to write down:**
  - The route prefix `admin` is reserved by the host.
  - Every static response must also set the security headers (S:335).
  - Build output adds to the package that each cold start downloads.
- **Fix:** add a spike ("serve `web/staff` from `staff-api` behind built-in auth") to the test-early list.
- **Sources:**
  - https://learn.microsoft.com/en-us/azure/azure-functions/functions-bindings-http-webhook-trigger
  - https://svrooij.io/2020/11/05/azure-functions-serve-static-files/

### F12 (Low): AD-16 wording

- S:364 says the domain's limits are "30 a minute and 100 an hour". The limit is actually scoped **per subscription** ("Send Email | Per Subscription | 1 | 30"; "60 | 100"). The arithmetic is unchanged because there is one subscription, but anything else in the subscription that sends mail shares these limits.
- Source: https://learn.microsoft.com/en-us/azure/communication-services/concepts/service-limits#email

### F13 (Info): pgcrypto on Azure Linux 3.0 / OpenSSL 3

- `pgcrypto` is supported on PG 18 (v1.4), and it must be allow-listed (confirmed).
- Algorithms that OpenSSL 3 classes as legacy (for example `bf` and `cast5`) aren't available.
- Pin `cipher-algo=aes256` in `pgp_sym_encrypt` options.
- Source: https://learn.microsoft.com/en-us/azure/postgresql/extensions/concepts-extensions-considerations

## Confirmed as stated

| Claim (spine line) | Result | Source |
| --- | --- | --- |
| Python 3.13 on Flex (S:60, S:492) | Confirmed. Flex supports 3.10–3.14. On 3.13+, worker dependency isolation is on by default and `azure-functions-runtime` can be pinned. | https://learn.microsoft.com/en-us/azure/azure-functions/flex-consumption-plan#supported-language-stack-versions ; https://learn.microsoft.com/en-us/azure/azure-functions/functions-reference-python |
| Flex in southeastasia; one app per plan (S:61) | Confirmed | https://techcommunity.microsoft.com/blog/appsonazureblog/azure-functions-flex-consumption-is-now-generally-available/4298778 ; flex-consumption-plan "Apps per plan" |
| Free grant of 250K executions and 100K GB-s (S:68) | Confirmed. The grant is **per subscription across all function apps**, so all 8 apps share it. The minimum billable execution is 1,000 ms. The 512 MB instance size gives four times the headroom. | https://azure.microsoft.com/en-us/pricing/details/functions/ ; retail API |
| Timers in UTC (S:67, S:317) | Confirmed. `WEBSITE_TIME_ZONE`/`TZ` are "not currently supported" on Flex. | flex-consumption-plan, Considerations |
| Poison queue `<queue>-poison`, `maxDequeueCount` 5 (S:94) | Confirmed | functions-bindings-storage-queue-trigger |
| No per-queue Storage metric (S:409) | Confirmed | monitor-queue-storage-reference |
| PG 18 on Flexible Server (S:302, S:496) | Confirmed GA (18.6). Some extensions are excluded, but pgcrypto isn't one of them. | https://learn.microsoft.com/en-us/azure/postgresql/configure-maintain/concepts-supported-versions |
| Stopped server restarts after 7 days (S:197) | Confirmed. The server may also be started briefly for monthly maintenance. | https://learn.microsoft.com/en-us/azure/postgresql/configure-maintain/how-to-stop-server |
| B1ms (S:302) | Confirmed. B1MS compute costs $0.026/hour in southeastasia (retail API). | prices.azure.com |
| Entra-only auth, `pgaadauth_create_principal` (S:280, S:292) | Confirmed (see F7 for the wording) | security-manage-entra-users |
| DI F0: 500 pages/month, first 2 pages, 4 MB, 1 TPS (S:204) | Confirmed. Analyze and Get each have **separate** 1 TPS limits. There is 1 F0 resource per region. | https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/service-limits?view=doc-intel-4.0.0 |
| DI managed identity needs a custom subdomain (S:208) | Confirmed: "Regional endpoints do not support Microsoft Entra authentication." | https://learn.microsoft.com/en-us/azure/ai-services/authentication |
| DI v4.0 `2024-11-30` in southeastasia (S:207, S:610) | Microsoft says "V4 is now GA across all the regions". Keep the test-early item, but the risk is low. | https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/whats-new?view=doc-intel-4.0.0 |
| ACS Email retires 2028-09-30 (S:368) | Confirmed. Onboarding new resources is still allowed, but Microsoft recommends against new solutions. | https://learn.microsoft.com/en-us/azure/communication-services/acs-retirement-and-breaking-changes-guide |
| ACS custom domain limits of 30/min and 100/h (S:364) | Confirmed. They are per subscription (F12). | service-limits#email |
| RBAC Administrator with conditions restricting roles (S:388) | Confirmed and free. Custom roles work (see F4). | delegate-role-assignments-overview |
| Terraform on Azure DevOps with WIF (S:395) | Confirmed | devblogs ID-token-refresh / Terraform task v5 |
| URL fragment is never sent to the server (S:172) | Confirmed. The fragment is "dereferenced solely by the user agent", and user agents also strip it from `Referer`. It stays visible to all page scripts and in browser history, so the page should `history.replaceState` after reading it. | https://www.rfc-editor.org/rfc/rfc3986#section-3.5 ; https://www.rfc-editor.org/rfc/rfc9110#section-10.1.3 |

## Package versions (PyPI and npm, 2026-09-28)

| Package | Spine | Latest | Released | Status |
| --- | --- | --- | --- | --- |
| azure-ai-documentintelligence | 1.0.2 | 1.0.2 | 2025-03-27 | Current. It targets API `2024-11-30`. |
| psycopg | 3.3.6 | 3.3.6 | 2026-09-18 | Current |
| SQLAlchemy | 2.1.1 | 2.1.1 | 2026-09-25 | Current. It was released 3 days ago, so the 2.1 line is young. Pin exactly. |
| alembic | 1.20.0 | 1.20.0 | 2026-09-11 | Current |
| pydantic | 2.13.5 | 2.13.5 | 2026-08-28 | Current |
| ImageHash | 4.3.2 | 4.3.2 | 2025-02-01 | Current |
| rapidfuzz | 3.14.6 | 3.14.6 | 2026-08-30 | Current |
| react | 19.3.0 | 19.3.0 | 2026-09-09 | Current |
| vite | 8.3.1 | 8.3.1 | 2026-09-24 | Current. `@vitejs/plugin-react` 6.1.1 and vitest 5.0.2 support Vite 8. |
| typescript | 7.0.2 | 7.0.2 | 2026-07-08 | Current, but **incompatible with typescript-eslint** (F2). The latest 6.0.x is 6.0.3. |

**Missing from the Stack table**, although the spine depends on them. Pin them too, because each is a cross-unit contract:

- `azure-functions` 2.3.0 (requires Python ≥3.13);
- `azure-monitor-opentelemetry` 1.8.10;
- `azure-communication-email` 1.1.0;
- `azure-storage-queue` 12.17.0 (F3);
- `pydantic-settings` 2.15.0;
- `Pillow` 12.3.0;
- `typescript-eslint` 8.70.1.
