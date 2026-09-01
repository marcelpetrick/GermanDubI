"""Give each project its own German narrator.

The voice was a machine-wide setting, so every project on a machine shared one narrator.
It belongs to the work rather than the installation: two dubs can reasonably want
different voices. Existing projects keep NULL, which means "use the configured default"
and preserves exactly what they were already doing.

Revision ID: a1c4e7b90d21
Revises: 11505ca091a8
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a1c4e7b90d21"
down_revision = "11505ca091a8"
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
    if not _has_column("projects", "voice"):
        op.add_column("projects", sa.Column("voice", sa.String(length=64), nullable=True))


def downgrade() -> None:
    if _has_column("projects", "voice"):
        op.drop_column("projects", "voice")
