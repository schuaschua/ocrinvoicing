"""staff-api reads this month's Document Intelligence pages (Story 2.8, AD-8).

Revision ID: 0007_staff_queue
Revises: 0006_validation
Create Date: 2026-09-30

Backward-compatible only (coding-style.md rule 29): one grant, nothing changed.

The admin queue warns at 80 % of the environment's monthly page cap, so the staff-api
login may SELECT `intake.di_usage` (0005_extraction gave it nothing there). It still
cannot change it: only the pipeline counts pages.
"""

from collections.abc import Sequence

from alembic import context, op

revision: str = "0007_staff_queue"
down_revision: str | Sequence[str] | None = "0006_validation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PRIVILEGE = "SELECT ON intake.di_usage"


def _staff_api() -> str:
    """The staff-api login, quoted as an identifier (env.py checked its shape)."""
    roles: dict[str, str] = context.config.attributes["roles"]
    quote = op.get_bind().dialect.identifier_preparer.quote_identifier
    return quote(roles["staff_api_role"])


def upgrade() -> None:
    op.execute(f"GRANT {PRIVILEGE} TO {_staff_api()}")


def downgrade() -> None:
    """Revokes the grant. Needs the same `-x` role arguments as the upgrade."""
    op.execute(f"REVOKE {PRIVILEGE} FROM {_staff_api()}")
