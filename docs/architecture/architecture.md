# Architecture: OCR Invoice Automation

Agreed with Dj on 2026-09-28. `bmad-architecture` loads this file and the provider files beside it as
standing facts. Every AD fits the answers below and honours the principles, or names the principle it departs
from and why.

## Context

| # | Question | Answer | Source |
| --- | --- | --- | --- |
| 1 | Environment | Hybrid. The accounts system (XML API) and the PO / goods-received DB are on-premises in the target state. For the PoC, both are simulated inside Azure. | owner: Dj, 2026-09-28 |
| 2 | Cloud platforms | Azure only ([azure.md](azure.md)) | owner: Dj, 2026-09-28 |
| 3 | Service model | PaaS only | owner: Dj, 2026-09-28 |
| 4 | Well-Architected priorities | 1 cost optimization, 2 security, 3 performance efficiency, 4 reliability, 5 operational excellence, 6 sustainability | owner: Dj, 2026-09-28 |
| 5 | Policies and guidelines | None | owner: Dj, 2026-09-28 |
| 8 | Regions and availability | Single region, no zone redundancy (single datacentre) | owner: Dj, 2026-09-28 |
| 9 | On-premises integration | High traffic expected in the target state. The PoC has no link to on-premises: every on-premises system is simulated in Azure. The production link is not yet decided. | owner: Dj, 2026-09-28 |
| 10 | AI | Only Azure AI Document Intelligence; no models of our own. The organisation is not familiar with AI. | owner: Dj, 2026-09-28 |
| 11 | Environments | Two: Dev and Prod. One subscription, a resource group per environment, a manual approval gate before Prod, no real supplier data in Dev. | owner: Dj, 2026-09-28 |
| 12 | Architecture style | Event-driven | owner: Dj, 2026-09-28 |
| 13 | Migration | No. A new build that replaces manual keying. | `SPEC.md §Why` |
| 14 | Security level | Strict | owner: Dj, 2026-09-28 |
| 15 | Approved stack | Front end React; back end Python; database PostgreSQL; CI/CD and AI platform in [azure.md](azure.md) | owner: Dj, 2026-09-28 |
| 16 | Application type | Pure web, responsive for phones (the supplier upload page is a mobile web page reached by link) | `SPEC.md §Assumptions` |
| 17 | Analytics | Light: CAP-14 to CAP-18 over a few thousand invoices a month; no warehouse or big batch/streaming jobs | owner: Dj, 2026-09-28 |

## Policies and guidelines
- None. The organisation has placed no policies in this folder.
- No regional regulator is set in `_bmad/config.toml`, so no regulator documents shaped these principles.

## Principles

### P-1 PaaS only
- **Rule:** Every component runs on a managed PaaS or serverless service. No virtual machines or other IaaS.
- **Why:** Keeps running and operating costs low for a PoC. Cost optimization (pillar 1).
- **Source:** Context row 3.
- **Applies to:** The whole solution, including the simulated on-premises systems.

### P-2 Monthly cost ceiling
- **Rule:** Total Azure spend, all environments and Document Intelligence pages included, must stay at or under US $10 per month. A budget alert fires before the ceiling is reached. Every AD states its expected monthly cost against this ceiling.
- **Why:** Cost optimization (pillar 1).
- **Source:** Owner: Dj, 2026-09-28.
- **Applies to:** The whole solution.
- **Known risk:** At "thousands of invoices a month" (`SPEC.md §Constraints`), Document Intelligence's per-page charge alone is likely to exceed US $10, and so is an always-on PostgreSQL server. Dj kept the ceiling after this was raised. An AD that cannot fit names P-2 and states the cost.

### P-3 Event-driven stages
- **Rule:** Intake stages (upload, quality check, extraction, validation, posting, admin queue) hand work to each other through queues or events. No stage calls the next stage synchronously. A failed step retries from its queue, and after its retries it goes to the admin queue.
- **Why:** Scales to zero when idle and isolates failures. Cost optimization (1), performance efficiency (3), reliability (4).
- **Source:** Context row 12; CAP-9, CAP-11.
- **Applies to:** The invoice intake pipeline.

### P-4 One adapter per external system
- **Rule:** The accounts XML API and the PO / goods-received DB are each reached only through their own adapter with a fixed contract. Switching an adapter from the Azure simulation to the real on-premises system changes no capability's behaviour and no code outside the adapter.
- **Why:** The PoC simulates every on-premises system, so the swap later must be cheap and safe. Reliability (4).
- **Source:** Context rows 1 and 9; CAP-20; `SPEC.md §Constraints`.
- **Applies to:** Accounts posting (CAP-11), PO matching (CAP-5), overdue list (CAP-12), delivery dates (CAP-19).

### P-5 Supplier identity from the link or the delivery
- **Rule:** The supplier on an invoice is taken only from the upload link or the warehouse delivery, never from a supplier ID printed on the invoice. A printed ID that disagrees sends the invoice to the admin queue.
- **Why:** Stops impersonated senders. Security (2).
- **Source:** `SPEC.md §Constraints`; CAP-1, CAP-9.
- **Applies to:** Intake (CAP-1, CAP-2).

### P-6 Encrypted and authenticated calls
- **Rule:** Every call between components, and to or from any external or simulated system, uses TLS and an authenticated caller. Nothing trusts a caller by being anonymous or by its IP address alone.
- **Why:** Invoices carry supplier bank details. Security (2).
- **Source:** Context row 14 (Strict).
- **Applies to:** The whole solution, and later the production on-premises link.

### P-7 Bank details protected
- **Rule:** Supplier bank details are encrypted at rest and readable only by the admin role. An invoice whose bank details differ from the supplier master never auto-posts.
- **Why:** Payment-redirect fraud. Security (2).
- **Source:** Context row 14; CAP-8.
- **Applies to:** The supplier master, extracted invoice data and the admin queue.

### P-8 Supplier upload links
- **Rule:** Each supplier's upload link is unguessable, unique to that supplier, and issued and revoked automatically. A revoked link accepts no uploads.
- **Why:** The link is the supplier's identity (P-5). Security (2).
- **Source:** Context row 14; CAP-1.
- **Applies to:** The supplier upload page.

### P-9 Document Intelligence as the only AI
- **Rule:** The only AI service is Azure AI Document Intelligence. Use its prebuilt invoice model first, and add custom models only where CAP-10 needs them. No other AI service, and no models trained or hosted by us. Any extracted field below 98% confidence goes to the admin queue.
- **Why:** The organisation is new to AI, and one managed service keeps cost and risk bounded. A human reviews every uncertain result. Cost optimization (1), security (2).
- **Source:** Context row 10; CAP-4, CAP-10; `SPEC.md §Constraints` (98% threshold).
- **Applies to:** Extraction and learning from corrections.
- **Known risk:** CAP-6 requires detecting "visually the same document" (a re-photographed invoice). Document Intelligence does not compare images, so this must be met without AI (for example a perceptual image hash) or the AD must name P-9 and say why.

### P-10 Analytics from pre-computed views
- **Rule:** Analytics (CAP-14 to CAP-18) read from summary tables or materialized views that are refreshed on events or by a scheduled job, never from ad-hoc queries over the transactional invoice tables.
- **Why:** Keeps the OLTP database small and cheap while the dashboards stay fast. Cost optimization (1), performance efficiency (3).
- **Source:** Context rows 15 and 17.
- **Applies to:** Price comparison, watchlist, scorecards and the finance view.

### P-11 One-month retention enforced by the platform
- **Rule:** Invoice images and raw admin corrections are deleted automatically after 1 month by platform lifecycle rules, with no manual clean-up. Extracted invoice fields, and Document Intelligence models trained from corrections, are kept.
- **Why:** Keeps storage cost down and meets the PoC retention rule, while keeping CAP-10 learning and CAP-15's year of price history. Cost optimization (1).
- **Source:** `SPEC.md §Constraints`; owner: Dj, 2026-09-28.
- **Applies to:** Image storage and correction records.

### P-12 Recovery targets
- **Rule:** RTO 24 hours and RPO 24 hours, met with the platform's built-in backups only. No standby or replica environment.
- **Why:** Enough for a PoC at the lowest cost. Reliability (4), cost optimization (1).
- **Source:** Owner: Dj, 2026-09-28.
- **Applies to:** The database and blob storage.

### P-13 Two environments, gated
- **Rule:** There are exactly two environments, Dev and Prod. Changes reach Prod only through the pipeline after a manual approval. Real supplier invoices and bank details never enter Dev.
- **Why:** Security (2), operational excellence (5).
- **Source:** Context row 11.
- **Applies to:** The whole solution and its pipeline.

### P-14 Single region
- **Rule:** The solution runs in a single region with no zone redundancy.
- **Why:** Cost optimization (1).
- **Source:** Context row 8.
- **Applies to:** The whole solution. The region is named in [azure.md](azure.md).

### P-15 Data residency
- **Rule:** All data, including supplier bank details, invoice images and backups, is stored and processed only in the chosen region.
- **Why:** Security (2).
- **Source:** Owner: Dj, 2026-09-28.
- **Applies to:** Every data store and every processing service, Document Intelligence included.

## Open questions
- Q9: the production link to the on-premises accounts system and PO DB (VPN or dedicated circuit, and its bandwidth). Decided by Dj before the switch from simulation.
- Q10b: the data-quality standard for admin corrections that train Document Intelligence custom models (CAP-10). Decided by Dj.

## Accepted departures
Accepted by Dj on 2026-09-28. Each is recorded in the architecture spine (`_bmad-output/planning-artifacts/architecture/architecture-ocrinvoicing-2026-09-28/ARCHITECTURE-SPINE.md`).

| Principle | Departure | Spine |
| --- | --- | --- |
| P-2 | The solution costs about US $11–12 a month, mostly PostgreSQL B1ms, even though Dj stops it by hand at night and at weekends. Document Intelligence stays at $0 on F0, with the PoC capped at 500 pages a month. A budget alert fires at $8. | AD-8, AD-12 |
| P-8 | Upload links are issued and revoked by an operator-run supplier load script, and Dj sends each new link by WhatsApp or SMS. There is no automatic issuing. | AD-6 |
| P-9 | Only a defined set of key fields is checked against the 98% threshold. Other extracted fields are stored but never send an invoice to the admin queue. | AD-18 |
| P-13 | Dev and Prod share one PostgreSQL server (separate databases and identities), one Document Intelligence F0 resource (per-environment page caps) and one ACS Email resource (per-environment send limits). | AD-8, AD-12, AD-16 |
| P-19 | MFA comes from Entra Security Defaults (Entra ID Free), which prompts on risk rather than at every sign-in. | AD-14 |

## Changes
| Date | Item | Change | Why |
| --- | --- | --- | --- |
| 2026-09-28 | All | First version, P-1 to P-15 | Agreed with Dj before `bmad-architecture` |
| 2026-09-28 | Row 15 | Database changed from Cosmos DB to PostgreSQL | Dj: the workload is OLTP, with light analytics beside it |
| 2026-09-28 | Open questions | CAP-6 risk settled by AD-9 (fingerprint plus perceptual hash, no AI); P-2 risk costed in AD-12 | Architecture spine finalized |
| 2026-09-28 | Accepted departures | Added P-2, P-13 and P-19 departures | Accepted by Dj during `bmad-architecture`. P-20 is kept: the web apps are served from the Function apps in `southeastasia` (AD-14), not from Static Web Apps |
| 2026-09-28 | Accepted departures | Added P-8 and P-9 departures; P-13 extended to ACS Email | Accepted by Dj during the `bmad-architecture` update that followed the implementation readiness check |
