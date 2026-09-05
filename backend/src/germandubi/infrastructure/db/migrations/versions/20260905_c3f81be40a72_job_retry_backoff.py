"""Give a failed stage somewhere to record when it may be tried again.

Retries were immediate, so all three attempts happened inside the same millisecond and a
transient failure -- a rate-limited download, a busy GPU -- was retried while the condition
that caused it was still true. The run then failed having genuinely been attempted once.
Existing jobs keep NULL, which means "claimable now" and is what they were already doing.

Revision ID: c3f81be40a72
Revises: a1c4e7b90d21
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c3f81be40a72"
down_revision = "a1c4e7b90d21"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    """Return whether a column is already present.

    A database created before migrations owned the schema is stamped at the base revision
    and then upgraded, so a migration can meet a change that is already there. Checking
    first is what makes that safe.
    """
    inspector = sa.inspect(op.get_bind())
    return any(existing["name"] == column for existing in inspector.get_columns(table))


def upgrade() -> None:
    if not _has_column("jobs", "next_attempt_at"):
        op.add_column(
            "jobs", sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True)
        )


def downgrade() -> None:
    if _has_column("jobs", "next_attempt_at"):
        op.drop_column("jobs", "next_attempt_at")
