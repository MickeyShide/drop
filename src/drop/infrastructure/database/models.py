import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    JSON,
    LargeBinary,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from drop.infrastructure.database.base import Base


class DropStatus(str, enum.Enum):
    UPLOADING = "UPLOADING"
    PROCESSING = "PROCESSING"
    ACTIVE = "ACTIVE"
    CONSUMED = "CONSUMED"
    EXPIRED = "EXPIRED"
    DELETING = "DELETING"
    DELETED = "DELETED"
    FAILED = "FAILED"


class OutboxStatus(str, enum.Enum):
    PENDING = "PENDING"
    PROCESSED = "PROCESSED"
    FAILED = "FAILED"


class GrantStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"


class DropModel(Base):
    __tablename__ = "drops"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    public_id: Mapped[str] = mapped_column(
        String(32),
        unique=True,
        nullable=False,
        index=True,
    )

    access_token_hash: Mapped[bytes] = mapped_column(
        LargeBinary,
        nullable=False,
    )

    original_filename: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    storage_key: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
        unique=True,
    )

    content_type: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    size_bytes: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )

    status: Mapped[DropStatus] = mapped_column(
        Enum(DropStatus, name="drop_status"),
        nullable=False,
    )

    max_downloads: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    download_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class DownloadGrantModel(Base):
    __tablename__ = "download_grants"
    __table_args__ = (
        UniqueConstraint(
            "drop_id", "client_session_hash", name="uq_drop_client_session"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    drop_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("drops.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    client_session_hash: Mapped[bytes] = mapped_column(
        LargeBinary,
        nullable=False,
    )

    status: Mapped[GrantStatus] = mapped_column(
        Enum(GrantStatus, name="grant_status"),
        nullable=False,
        default=GrantStatus.ACTIVE,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class OutboxEventModel(Base):
    __tablename__ = "outbox_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    event_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    payload: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
    )

    status: Mapped[OutboxStatus] = mapped_column(
        Enum(OutboxStatus, name="outbox_status"),
        nullable=False,
        default=OutboxStatus.PENDING,
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class DownloadEventModel(Base):
    __tablename__ = "download_events"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    drop_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )

    ip_address: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    user_agent: Mapped[str | None] = mapped_column(
        String(512),
        nullable=True,
    )

    request_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )

    download_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    duration_ms: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
