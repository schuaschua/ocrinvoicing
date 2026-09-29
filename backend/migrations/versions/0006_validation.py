"""The validate stage's one write to extraction lines (Story 2.5, AD-18, AD-19).

Revision ID: 0006_validation
Revises: 0005_extraction
Create Date: 2026-09-30

Backward-compatible only (coding-style.md rule 29): one grant, nothing changed.

`intake.invoice_line` stays append-only for its extracted columns (security.md rule
32): the pipeline login may UPDATE only `po_line_id` and `material_id`, which the
validate stage fills when it matches a line to a PO line (a column-level grant).
"""

from collections.abc import Sequence

from alembic import context, op

revision: str = "0006_validation"
down_revision: str | Sequence[str] | None = "0005_extraction"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "intake"
# AD-18: the columns the validate stage fills (AD-19).
MATCH_COLUMNS = ("po_line_id", "material_id")


def _pipeline() -> str:
    """The pipeline login, quoted as an identifier (env.py checked its shape)."""
    roles: dict[str, str] = context.config.attributes["roles"]
    quote = op.get_bind().dialect.identifier_preparer.quote_identifier
    return quote(roles["pipeline_role"])


def _privilege() -> str:
    return f"UPDATE ({', '.join(MATCH_COLUMNS)}) ON {SCHEMA}.invoice_line"


def upgrade() -> None:
    op.execute(f"GRANT {_privilege()} TO {_pipeline()}")


def downgrade() -> None:
    """Revokes the grant. Needs the same `-x` role arguments as the upgrade."""
    op.execute(f"REVOKE {_privilege()} FROM {_pipeline()}")
