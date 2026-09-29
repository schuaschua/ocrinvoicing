# Azure: OCR Invoice Automation

Azure-specific answers and principles. Read with [architecture.md](architecture.md), which holds the shared answers
and principles P-1 to P-15. Principles here continue that sequence.

## Context

| # | Question | Answer | Source |
| --- | --- | --- | --- |
| 3 | Service model | PaaS only; no Azure VMs, VM scale sets or other IaaS | owner: Dj, 2026-09-28 |
| 6 | Naming convention | `<orgname>-<region>-<appname>-<resourceType>-<number>` with Azure resource-type abbreviations: `babaloo-sea-lng-<resourceType>-<nn>`, e.g. `babaloo-sea-lng-func-01` | owner: Dj, 2026-09-28 |
| 7 | Tags | `owner`, `costCentre`, `environment`, `application`, `dataClassification` | owner: Dj, 2026-09-28 |
| 8 | Region | Southeast Asia (Singapore), `southeastasia`; no availability zones | owner: Dj, 2026-09-28 |
| 9 | On-premises connection | None for the PoC. The accounts XML API and the PO / goods-received DB are simulated inside Azure. | owner: Dj, 2026-09-28 |
| 15 | Managed services | Database: Azure Database for PostgreSQL Flexible Server. CI/CD: Jenkins in Docker on one VM, running Terraform (code in Azure Repos) (Dj, 2026-09-29). AI platform: Azure AI Document Intelligence. | owner: Dj, 2026-09-28 |

## Principles

### P-16 Naming
- **Rule:** Every Azure resource is named `babaloo-sea-lng-<resourceType>-<nn>`, using Azure's resource-type abbreviations and a two-digit number. The environment is carried in the `environment` tag and the resource group.
- **Why:** Resources are identifiable at a glance. Operational excellence (5).
- **Source:** Context row 6.
- **Applies to:** All Azure resources. Where a service's naming rules forbid hyphens or limit length (for example storage accounts), the AD states the shortened form.

### P-17 Mandatory tags
- **Rule:** Every Azure resource and resource group carries all five tags: `owner`, `costCentre`, `environment`, `application`, `dataClassification`. The deployment pipeline applies them, and a resource missing any of them is not deployed.
- **Why:** Cost can be traced per environment against P-2, and data sensitivity is visible. Cost optimization (1), operational excellence (5).
- **Source:** Context row 7.
- **Applies to:** All Azure resources.

### P-18 Managed identities and Key Vault
- **Rule:** Azure services authenticate to each other with managed identities. Any secret that cannot be replaced by a managed identity lives in Azure Key Vault, never in code, config files or pipeline variables.
- **Why:** No credentials to leak. Security (2).
- **Source:** Context row 14 (Strict), via architecture.md P-6.
- **Applies to:** All service-to-service calls, including calls to the simulated accounts API and PO DB.

### P-19 Entra ID for people
- **Rule:** Admin, finance, procurement and management users sign in with Microsoft Entra ID with MFA, and see only what their role allows. Suppliers are identified by their upload link (P-8), not by an Entra account.
- **Why:** Security (2).
- **Source:** Context row 14 (Strict); CAP-9, CAP-14 to CAP-18.
- **Applies to:** All staff-facing views.

### P-20 Approved Azure services
- **Rule:** Use Azure Database for PostgreSQL Flexible Server for the database, Azure AI Document Intelligence for extraction, and Jenkins (in Docker on one Azure VM, code in Azure Repos) for CI/CD (Dj, 2026-09-29). Other services are chosen in an AD within P-1, P-2 and P-15, and all of them must be available in `southeastasia`.
- **Why:** These are the stack the team knows. Cost optimization (1), operational excellence (5).
- **Source:** Context row 15.
- **Applies to:** The whole solution.

## Open questions
- Q9: the production connection to on-premises (site-to-site VPN or ExpressRoute, and its bandwidth), once the simulation is replaced.

## Changes
| Date | Item | Change | Why |
| --- | --- | --- | --- |
| 2026-09-28 | All | First version, P-16 to P-20 | Agreed with Dj before `bmad-architecture` |
| 2026-09-29 | P-20, row 15 | CI/CD moves to Jenkins on a VM | Dj, sprint change proposal 2026-09-29 |
