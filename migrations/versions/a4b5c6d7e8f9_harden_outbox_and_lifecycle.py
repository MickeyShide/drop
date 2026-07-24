"""harden Outbox delivery and retire unused processing state

Revision ID: a4b5c6d7e8f9
Revises: f3a4b5c6d7e8
Create Date: 2026-07-25 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a4b5c6d7e8f9"
down_revision: Union[str, Sequence[str], None] = "f3a4b5c6d7e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # PROCESSING was never part of an executable Drop workflow. Existing rows
    # are made visible for operator recovery instead of silently pretending to
    # be active.
    op.execute("ALTER TYPE drop_status RENAME TO drop_status_old")
    new_drop_status = sa.Enum(
        "UPLOADING",
        "ACTIVE",
        "CONSUMED",
        "EXPIRED",
        "DELETING",
        "DELETED",
        "FAILED",
        name="drop_status",
    )
    new_drop_status.create(op.get_bind())
    op.execute(
        """
        ALTER TABLE drops
        ALTER COLUMN status TYPE drop_status
        USING (
            CASE status::text
                WHEN 'PROCESSING' THEN 'FAILED'
                ELSE status::text
            END
        )::drop_status
        """
    )
    op.execute("DROP TYPE drop_status_old")

    op.execute("ALTER TYPE outbox_status ADD VALUE IF NOT EXISTS 'PROCESSING'")
    op.add_column(
        "outbox_events",
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "outbox_events",
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "outbox_events",
        sa.Column("last_error", sa.String(length=512), nullable=True),
    )
    op.alter_column("outbox_events", "attempts", server_default=None)
    op.create_index(
        "ix_outbox_events_status_locked_at",
        "outbox_events",
        ["status", "locked_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_outbox_events_status_locked_at", table_name="outbox_events")
    op.drop_column("outbox_events", "last_error")
    op.drop_column("outbox_events", "locked_at")
    op.drop_column("outbox_events", "attempts")

    op.execute("ALTER TYPE drop_status RENAME TO drop_status_old")
    old_drop_status = sa.Enum(
        "UPLOADING",
        "PROCESSING",
        "ACTIVE",
        "CONSUMED",
        "EXPIRED",
        "DELETING",
        "DELETED",
        "FAILED",
        name="drop_status",
    )
    old_drop_status.create(op.get_bind())
    op.execute(
        "ALTER TABLE drops ALTER COLUMN status TYPE drop_status USING status::text::drop_status"
    )
    op.execute("DROP TYPE drop_status_old")

    # PostgreSQL cannot remove enum values in-place, so recreate the type.
    op.execute("ALTER TYPE outbox_status RENAME TO outbox_status_old")
    old_outbox_status = sa.Enum(
        "PENDING",
        "PROCESSED",
        "FAILED",
        name="outbox_status",
    )
    old_outbox_status.create(op.get_bind())
    op.execute(
        """
        ALTER TABLE outbox_events
        ALTER COLUMN status TYPE outbox_status
        USING (
            CASE status::text
                WHEN 'PROCESSING' THEN 'PENDING'
                ELSE status::text
            END
        )::outbox_status
        """
    )
    op.execute("DROP TYPE outbox_status_old")
