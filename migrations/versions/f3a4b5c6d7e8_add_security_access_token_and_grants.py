"""add security access token hash and download grants table

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7
Create Date: 2026-07-24 20:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f3a4b5c6d7e8"
down_revision: Union[str, Sequence[str], None] = "e2f3a4b5c6d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "drops", sa.Column("access_token_hash", sa.LargeBinary(), nullable=True)
    )
    # Fill existing rows if any with dummy hash
    op.execute(
        "UPDATE drops SET access_token_hash = '\\x0000000000000000000000000000000000000000000000000000000000000000' WHERE access_token_hash IS NULL"
    )
    op.alter_column("drops", "access_token_hash", nullable=False)

    grant_status = sa.Enum("ACTIVE", "COMPLETED", "EXPIRED", name="grant_status")
    op.create_table(
        "download_grants",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("drop_id", sa.UUID(), nullable=False),
        sa.Column("client_session_hash", sa.LargeBinary(), nullable=False),
        sa.Column("status", grant_status, nullable=False, server_default="ACTIVE"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["drop_id"], ["drops.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "drop_id", "client_session_hash", name="uq_drop_client_session"
        ),
    )
    op.create_index(
        op.f("ix_download_grants_drop_id"),
        "download_grants",
        ["drop_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_download_grants_drop_id"), table_name="download_grants")
    op.drop_table("download_grants")
    op.execute("DROP TYPE IF EXISTS grant_status")
    op.drop_column("drops", "access_token_hash")
