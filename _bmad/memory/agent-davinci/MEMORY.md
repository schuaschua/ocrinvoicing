# Memory

_Curated long-term knowledge. Empty at birth — grows through sessions._

_Distilled insights, not raw notes: the principles the owner held firm on or dropped and why, challenges they deferred, drawing and document choices they corrected. Aim to stay under roughly 1500 tokens. Raw notes go in `sessions/YYYY-MM-DD.md`. See `references/memory-guidance.md`._

## Principles (2026-09-28, architecture.md P-1..P-15, azure.md P-16..P-20)
- Pillars: 1 cost, 2 security, 3 performance, 4 reliability, 5 opex, 6 sustainability.
- Held firm: PaaS only (stricter than my "PaaS first"); $10/month for everything despite challenge (recorded as risk on P-2); AI = Document Intelligence only; no on-prem link — accounts XML API + PO DB both simulated in Azure.
- Changed their mind: Cosmos -> PostgreSQL after my OLTP/analytics caution.
- Accepted my defaults readily (tags, naming pattern, RTO/RPO 24h, env strictness). Org new to AI.
- Org babaloo, app lng, region southeastasia. No regulator region set in config (PDPA not loaded).

## Open for early sessions
- Q9 production on-prem link; Q10b correction data-quality standard.
- Risks handed to bmad-architecture: CAP-6 visual duplicates under P-9; P-2 cost ceiling vs DI per-page cost.
- Drawing preferences / HLD template not yet discovered.

## Bank-detail protection (2026-09-28)
- Dj asked why encrypt / how HMAC catches fraud / why not plaintext; after explanation chose to KEEP PGP encryption + HMAC fingerprints (AD-11, P-7) over the plaintext simplification.
- Dj has MORE QUESTIONS on HMAC/PGP later: raise it at the next architecture session, before Story 1.6 / 2.3 are built.
