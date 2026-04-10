"""User and organization models.

Dual-identity architecture:
- Identity: Global identity (natural person) across all tenants
- User: Tenant member (role and profile within a specific company)
- IdentityContact: Multiple contact methods per identity
- IdentityBinding: Channel identity bindings for cross-platform user resolution
"""

import uuid
from datetime import datetime
from enum import Enum as PyEnum

import sqlalchemy as sa
from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
    CheckConstraint,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.ext.associationproxy import association_proxy

from app.database import Base


class ContactType(str, PyEnum):
    """Contact method type."""

    MOBILE = "mobile"
    EMAIL = "email"


class ContactPurpose(str, PyEnum):
    """Contact method purpose."""

    PRIMARY = "primary"  # Primary contact for login/notifications
    VERIFIED = "verified"  # Verified backup contact
    LEGACY = "legacy"  # Historical contact (no longer active)


class Identity(Base):
    """
    Physical Identity (Lark ID).
    Represents a natural person globally across all tenants.
    """

    __tablename__ = "identities"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Global unique identifiers for login
    email: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(50), unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(100), unique=True, index=True)

    # Cached primary contacts (for quick lookup without JOIN)
    primary_email: Mapped[str | None] = mapped_column(String(255), index=True)
    primary_phone: Mapped[str | None] = mapped_column(String(50), index=True)

    # Global authentication
    password_hash: Mapped[str | None] = mapped_column(String(255))

    # Global status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_platform_admin: Mapped[bool] = mapped_column(Boolean, default=False)

    # Verification status
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    phone_verified: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    tenant_users: Mapped[list["User"]] = relationship(back_populates="identity")
    contacts: Mapped[list["IdentityContact"]] = relationship(back_populates="identity", cascade="all, delete-orphan")
    bindings: Mapped[list["IdentityBinding"]] = relationship(back_populates="identity", cascade="all, delete-orphan")


class User(Base):
    """
    Tenant Identity (Member ID).
    Represents a person's role and profile within a specific company.
    """

    __tablename__ = "users"
    # Note: Unique constraints for (tenant_id, username), (tenant_id, email) and (tenant_id, primary_mobile)
    # are handled via partial unique indexes in migration to allow NULL values

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Link to global identity
    identity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("identities.id"), index=True)

    # Tenant context
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))

    # Tenant-specific profile
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(String(500))
    title: Mapped[str | None] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(
        Enum("platform_admin", "org_admin", "agent_admin", "member", name="user_role_enum"),
        default="member",
        nullable=False,
    )

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    registration_source: Mapped[str | None] = mapped_column(String(50), default="web")

    # Generic platform-stable identity IDs
    external_id: Mapped[str | None] = mapped_column(String(255), index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Usage quotas (set by admin, defaults from tenant)
    quota_message_limit: Mapped[int] = mapped_column(Integer, default=50)
    quota_message_period: Mapped[str] = mapped_column(String(20), default="permanent")  # permanent|daily|weekly|monthly
    quota_messages_used: Mapped[int] = mapped_column(Integer, default=0)
    quota_period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    quota_max_agents: Mapped[int] = mapped_column(Integer, default=2)
    quota_agent_ttl_hours: Mapped[int] = mapped_column(Integer, default=48)

    # Relationships
    # lazy="selectin" is required because association_proxy fields (email, username,
    # password_hash, email_verified, primary_mobile) delegate to this relationship.
    # Without eager loading, any proxy access in an async context triggers a synchronous
    # IO call inside a greenlet, raising sqlalchemy.exc.MissingGreenlet.
    identity: Mapped["Identity"] = relationship(back_populates="tenant_users", lazy="selectin")

    # Association proxies for backward compatibility
    email = association_proxy("identity", "email")
    username = association_proxy("identity", "username")
    password_hash = association_proxy("identity", "password_hash")
    email_verified = association_proxy("identity", "email_verified")
    primary_mobile = association_proxy("identity", "phone")

    @property
    def has_password(self) -> bool:
        """Check if user has a password set."""
        return bool(self.password_hash)

    created_agents: Mapped[list["Agent"]] = relationship(back_populates="creator", foreign_keys="Agent.creator_id")


# Forward reference for Agent used in User relationship
from app.models.agent import Agent  # noqa: E402, F401
from app.models.org import OrgMember  # noqa: E402, F401


class IdentityContact(Base):
    """
    Contact methods for an Identity.
    Supports multiple mobile numbers and email addresses per user.
    """

    __tablename__ = "identity_contacts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    identity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("identities.id", ondelete="CASCADE"), nullable=False
    )

    # Contact type and value
    contact_type: Mapped[str] = mapped_column(String(20), nullable=False)  # mobile / email
    contact_value: Mapped[str] = mapped_column(String(255), nullable=False, index=True)  # normalized value

    # Purpose: primary (for login), verified (backup), legacy (historical)
    purpose: Mapped[str] = mapped_column(String(20), default="verified")

    # Verification status
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Source: feishu / wecom / dingtalk / web / manual
    source: Mapped[str | None] = mapped_column(String(50))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationship
    identity: Mapped["Identity"] = relationship(back_populates="contacts")

    __table_args__ = (
        UniqueConstraint("contact_type", "contact_value", name="uq_identity_contact_value"),
        sa.Index("ix_identity_contacts_identity_type", "identity_id", "contact_type"),
    )


class IdentityBinding(Base):
    """
    Channel identity bindings for cross-platform user resolution.
    Maps external provider user IDs to internal Identity.
    """

    __tablename__ = "identity_bindings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    identity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("identities.id", ondelete="CASCADE"), nullable=False
    )

    # Provider info: feishu / wecom / dingtalk / web
    provider_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    provider_user_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)  # Stable ID from provider

    # Contact snapshot from provider
    email: Mapped[str | None] = mapped_column(String(255), index=True)
    mobile: Mapped[str | None] = mapped_column(String(50), index=True)  # Normalized mobile

    # Raw data from provider (for debugging/audit)
    raw_data: Mapped[dict | None] = mapped_column(JSON)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationship
    identity: Mapped["Identity"] = relationship(back_populates="bindings")

    __table_args__ = (
        UniqueConstraint("provider_type", "provider_user_id", name="uq_identity_binding_provider_user"),
        sa.Index("ix_identity_bindings_provider_lookup", "provider_type", "provider_user_id"),
    )
