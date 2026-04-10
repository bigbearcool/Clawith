"""Identity resolution and management service.

This service handles:
- Cross-platform user identity resolution
- Multiple contact methods per identity
- Channel identity bindings (Feishu, WeCom, DingTalk, etc.)
"""

import re
import uuid
from datetime import datetime, timezone
from typing import Any

from loguru import logger
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import Identity, IdentityContact, IdentityBinding, ContactType, ContactPurpose


class NeedsBindingError(Exception):
    """Raised when SSO login needs contact binding to complete registration."""

    def __init__(self, provider_type: str, provider_user_id: str, raw_data: dict | None = None):
        self.provider_type = provider_type
        self.provider_user_id = provider_user_id
        self.raw_data = raw_data or {}
        super().__init__(f"SSO login needs binding for {provider_type}:{provider_user_id}")


def normalize_mobile(mobile: str, country_code: str = "86") -> str:
    """Normalize mobile number to standard format.

    For China (default):
    - Remove all non-digit characters
    - Strip country code (86) if present
    - Return 11-digit number or empty string if invalid

    Args:
        mobile: Raw mobile number string
        country_code: Country code (default: 86 for China)

    Returns:
        Normalized mobile number or empty string if invalid
    """
    if not mobile:
        return ""

    digits = re.sub(r"\D", "", mobile)

    if country_code == "86":
        if digits.startswith("86") and len(digits) == 13:
            digits = digits[2:]
        if len(digits) != 11 or not digits.startswith("1"):
            return ""

    return digits


class IdentityService:
    """Service for identity resolution and management."""

    async def resolve_identity(
        self,
        db: AsyncSession,
        provider_type: str,
        provider_user_id: str,
        email: str | None = None,
        mobile: str | None = None,
        raw_data: dict | None = None,
        tenant_id: uuid.UUID | None = None,
    ) -> tuple[Identity, bool]:
        """Resolve or create an Identity from external channel.

        Priority order:
        1. Find by provider_type + provider_user_id (most reliable)
        2. Find by email (cross-channel merge)
        3. Find by mobile (cross-channel merge)
        4. Create new Identity

        Args:
            db: Database session
            provider_type: Channel type (feishu/wecom/dingtalk/web)
            provider_user_id: Stable user ID from provider
            email: Email from provider (optional)
            mobile: Mobile from provider (optional)
            raw_data: Raw data from provider for audit
            tenant_id: Tenant ID context (optional)

        Returns:
            Tuple of (Identity, is_new) where is_new indicates if created

        Raises:
            NeedsBindingError: When no contact info available for new user
        """
        normalized_mobile = normalize_mobile(mobile) if mobile else None

        # 1. Find by provider binding (most reliable)
        binding = await self._find_binding_by_provider(db, provider_type, provider_user_id)
        if binding:
            identity = await db.get(Identity, binding.identity_id)
            if identity:
                logger.debug(f"[Identity] Found by provider binding: {identity.id}")
                return identity, False

        # 2. Find by email (cross-channel merge)
        if email:
            contact = await self._find_contact_by_value(db, ContactType.EMAIL.value, email)
            if contact:
                identity = await db.get(Identity, contact.identity_id)
                if identity:
                    logger.info(f"[Identity] Merged by email: {identity.id}")
                    await self._create_binding(
                        db, identity.id, provider_type, provider_user_id, email, normalized_mobile, raw_data
                    )
                    return identity, False

        # 3. Find by mobile (cross-channel merge)
        if normalized_mobile:
            contact = await self._find_contact_by_value(db, ContactType.MOBILE.value, normalized_mobile)
            if contact:
                identity = await db.get(Identity, contact.identity_id)
                if identity:
                    logger.info(f"[Identity] Merged by mobile: {identity.id}")
                    await self._create_binding(
                        db, identity.id, provider_type, provider_user_id, email, normalized_mobile, raw_data
                    )
                    return identity, False

        # 4. Check if we have enough info to create new identity
        if not email and not normalized_mobile and provider_type != "web":
            raise NeedsBindingError(provider_type, provider_user_id, raw_data)

        # 5. Create new Identity
        identity = Identity(
            email=email,
            phone=normalized_mobile,
            primary_email=email,
            primary_phone=normalized_mobile,
            email_verified=(provider_type != "web" and email is not None),
            phone_verified=(provider_type != "web" and normalized_mobile is not None),
        )
        db.add(identity)
        await db.flush()

        # 6. Create binding
        await self._create_binding(db, identity.id, provider_type, provider_user_id, email, normalized_mobile, raw_data)

        # 7. Create initial contact records
        if email:
            await self._create_contact(
                db,
                identity.id,
                ContactType.EMAIL.value,
                email,
                ContactPurpose.PRIMARY.value,
                verified=(provider_type != "web"),
                source=provider_type,
            )

        if normalized_mobile:
            await self._create_contact(
                db,
                identity.id,
                ContactType.MOBILE.value,
                normalized_mobile,
                ContactPurpose.PRIMARY.value,
                verified=(provider_type != "web"),
                source=provider_type,
            )

        logger.info(f"[Identity] Created new identity: {identity.id}")
        return identity, True

    async def find_identity_by_contact(
        self,
        db: AsyncSession,
        contact_type: str,
        contact_value: str,
    ) -> Identity | None:
        """Find Identity by contact method (email or mobile).

        Args:
            db: Database session
            contact_type: "mobile" or "email"
            contact_value: Contact value (will be normalized for mobile)

        Returns:
            Identity if found, None otherwise
        """
        if contact_type == ContactType.MOBILE.value:
            contact_value = normalize_mobile(contact_value)

        contact = await self._find_contact_by_value(db, contact_type, contact_value)
        if contact:
            return await db.get(Identity, contact.identity_id)
        return None

    async def add_contact(
        self,
        db: AsyncSession,
        identity_id: uuid.UUID,
        contact_type: str,
        contact_value: str,
        purpose: str = ContactPurpose.VERIFIED.value,
        verified: bool = False,
        source: str | None = None,
    ) -> IdentityContact:
        """Add a contact method to an Identity.

        Args:
            db: Database session
            identity_id: Identity ID
            contact_type: "mobile" or "email"
            contact_value: Contact value
            purpose: "primary", "verified", or "legacy"
            verified: Whether contact is verified
            source: Source of contact (feishu/wecom/web/manual)

        Returns:
            Created IdentityContact

        Raises:
            ValueError: If contact already exists for another identity
        """
        if contact_type == ContactType.MOBILE.value:
            contact_value = normalize_mobile(contact_value)
            if not contact_value:
                raise ValueError("Invalid mobile number format")

        existing = await self._find_contact_by_value(db, contact_type, contact_value)
        if existing:
            if existing.identity_id != identity_id:
                raise ValueError(f"Contact {contact_value} already bound to another identity")
            return existing

        if purpose == ContactPurpose.PRIMARY.value:
            await self._demote_primary_contact(db, identity_id, contact_type)

        contact = await self._create_contact(db, identity_id, contact_type, contact_value, purpose, verified, source)

        if purpose == ContactPurpose.PRIMARY.value:
            identity = await db.get(Identity, identity_id)
            if identity:
                if contact_type == ContactType.EMAIL.value:
                    identity.primary_email = contact_value
                elif contact_type == ContactType.MOBILE.value:
                    identity.primary_phone = contact_value

        return contact

    async def set_primary_contact(
        self,
        db: AsyncSession,
        identity_id: uuid.UUID,
        contact_id: uuid.UUID,
    ) -> None:
        """Set a contact as primary.

        Args:
            db: Database session
            identity_id: Identity ID
            contact_id: Contact ID to set as primary
        """
        contact = await db.get(IdentityContact, contact_id)
        if not contact or contact.identity_id != identity_id:
            raise ValueError("Contact not found or does not belong to identity")

        await self._demote_primary_contact(db, identity_id, contact.contact_type)

        contact.purpose = ContactPurpose.PRIMARY.value
        contact.verified = True
        contact.verified_at = datetime.now(timezone.utc)

        identity = await db.get(Identity, identity_id)
        if identity:
            if contact.contact_type == ContactType.EMAIL.value:
                identity.primary_email = contact.contact_value
                identity.email_verified = True
            elif contact.contact_type == ContactType.MOBILE.value:
                identity.primary_phone = contact.contact_value
                identity.phone_verified = True

    async def delete_contact(
        self,
        db: AsyncSession,
        identity_id: uuid.UUID,
        contact_id: uuid.UUID,
    ) -> None:
        """Delete a contact method.

        Args:
            db: Database session
            identity_id: Identity ID
            contact_id: Contact ID to delete

        Raises:
            ValueError: If trying to delete the only verified contact
        """
        contact = await db.get(IdentityContact, contact_id)
        if not contact or contact.identity_id != identity_id:
            raise ValueError("Contact not found or does not belong to identity")

        if contact.purpose == ContactPurpose.PRIMARY.value:
            other_contacts = await db.execute(
                select(IdentityContact).where(
                    IdentityContact.identity_id == identity_id,
                    IdentityContact.contact_type == contact.contact_type,
                    IdentityContact.id != contact_id,
                    IdentityContact.verified == True,
                )
            )
            if not other_contacts.scalars().first():
                raise ValueError("Cannot delete the only verified contact of this type")

        await db.delete(contact)

    async def get_contacts(
        self,
        db: AsyncSession,
        identity_id: uuid.UUID,
    ) -> list[IdentityContact]:
        """Get all contacts for an Identity.

        Args:
            db: Database session
            identity_id: Identity ID

        Returns:
            List of IdentityContact
        """
        result = await db.execute(
            select(IdentityContact)
            .where(IdentityContact.identity_id == identity_id)
            .order_by(IdentityContact.contact_type, IdentityContact.purpose)
        )
        return list(result.scalars().all())

    async def _find_binding_by_provider(
        self,
        db: AsyncSession,
        provider_type: str,
        provider_user_id: str,
    ) -> IdentityBinding | None:
        """Find binding by provider type and user ID."""
        result = await db.execute(
            select(IdentityBinding).where(
                IdentityBinding.provider_type == provider_type,
                IdentityBinding.provider_user_id == provider_user_id,
            )
        )
        return result.scalar_one_or_none()

    async def _find_contact_by_value(
        self,
        db: AsyncSession,
        contact_type: str,
        contact_value: str,
    ) -> IdentityContact | None:
        """Find contact by type and value."""
        result = await db.execute(
            select(IdentityContact).where(
                IdentityContact.contact_type == contact_type,
                IdentityContact.contact_value == contact_value,
            )
        )
        return result.scalar_one_or_none()

    async def _create_binding(
        self,
        db: AsyncSession,
        identity_id: uuid.UUID,
        provider_type: str,
        provider_user_id: str,
        email: str | None,
        mobile: str | None,
        raw_data: dict | None,
    ) -> IdentityBinding:
        """Create a channel binding."""
        binding = IdentityBinding(
            identity_id=identity_id,
            provider_type=provider_type,
            provider_user_id=provider_user_id,
            email=email,
            mobile=mobile,
            raw_data=raw_data,
        )
        db.add(binding)
        await db.flush()
        return binding

    async def _create_contact(
        self,
        db: AsyncSession,
        identity_id: uuid.UUID,
        contact_type: str,
        contact_value: str,
        purpose: str,
        verified: bool,
        source: str | None,
    ) -> IdentityContact:
        """Create a contact record."""
        contact = IdentityContact(
            identity_id=identity_id,
            contact_type=contact_type,
            contact_value=contact_value,
            purpose=purpose,
            verified=verified,
            verified_at=datetime.now(timezone.utc) if verified else None,
            source=source,
        )
        db.add(contact)
        await db.flush()
        return contact

    async def _demote_primary_contact(
        self,
        db: AsyncSession,
        identity_id: uuid.UUID,
        contact_type: str,
    ) -> None:
        """Demote current primary contact to verified."""
        result = await db.execute(
            select(IdentityContact).where(
                IdentityContact.identity_id == identity_id,
                IdentityContact.contact_type == contact_type,
                IdentityContact.purpose == ContactPurpose.PRIMARY.value,
            )
        )
        current_primary = result.scalar_one_or_none()
        if current_primary:
            current_primary.purpose = ContactPurpose.VERIFIED.value


identity_service = IdentityService()
