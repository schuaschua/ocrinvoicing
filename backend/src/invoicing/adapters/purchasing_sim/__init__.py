"""The purchasing simulation (AD-10, CAP-20): `PurchasingPort` over its own
PostgreSQL schema, plus the operator seed. The only module that may touch that
schema; everything else reaches it through `adapters/purchasing_factory.py`, and an
import-linter contract (backend/pyproject.toml) enforces both."""
