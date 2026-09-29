"""`intake.invoice.device_check` accepts `skipped`: the page couldn't run its check
(Story 1.9, AD-5 `device_check: passed|overridden|skipped`).

Revision ID: 0003_device_check_skipped
Revises: 0002_sim_purchasing
Create Date: 2026-09-29

Backward-compatible only (coding-style.md rule 29): the check is widened, nothing is
removed. The value lists are copies of domain/upload.py DeviceCheck at the time of
writing, on purpose (see 0001_intake).

Downgrade narrows the check back. Code from before this revision can't read
`skipped`, and the server treats `skipped` like `passed` (AD-6: it checks every upload
again), so downgrade rewrites `skipped` rows as `passed` first. That loses only the
record that the page skipped its check.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003_device_check_skipped"
down_revision: str | Sequence[str] | None = "0002_sim_purchasing"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "intake"
TABLE = "invoice"
CONSTRAINT = "ck_invoice_device_check"
DEVICE_CHECKS = ("passed", "overridden", "skipped")
PREVIOUS_DEVICE_CHECKS = ("passed", "overridden")


def _in(column: str, values: Sequence[str]) -> str:
    # Literals from the constants above only, never from input.
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _replace_check(values: Sequence[str]) -> None:
    op.drop_constraint(CONSTRAINT, TABLE, schema=SCHEMA, type_="check")
    op.create_check_constraint(
        CONSTRAINT, TABLE, _in("device_check", values), schema=SCHEMA
    )


def upgrade() -> None:
    _replace_check(DEVICE_CHECKS)


def downgrade() -> None:
    op.execute(
        f"UPDATE {SCHEMA}.{TABLE} SET device_check = 'passed'"  # noqa: S608  # constants only
        " WHERE device_check = 'skipped'"
    )
    _replace_check(PREVIOUS_DEVICE_CHECKS)
