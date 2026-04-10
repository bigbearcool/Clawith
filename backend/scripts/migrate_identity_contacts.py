"""Migrate existing data to identity_contacts and identity_bindings tables.

This script:
1. Migrates Identity data to IdentityContact
2. Migrates OrgMember data to IdentityBinding
3. Updates Identity.primary_email and primary_phone

Run with: python scripts/migrate_identity_contacts.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.models.user import Identity, IdentityContact, IdentityBinding, User
from app.models.org import OrgMember
from app.models.identity import IdentityProvider
from app.services.identity_service import normalize_mobile, ContactType, ContactPurpose


async def migrate_identities(db: AsyncSession) -> int:
    """Migrate Identity data to IdentityContact."""
    logger.info("[Migration] Starting Identity → IdentityContact migration...")

    result = await db.execute(select(Identity))
    identities = result.scalars().all()

    migrated = 0
    for identity in identities:
        # Migrate email
        if identity.email:
            existing = await db.execute(
                select(IdentityContact).where(
                    IdentityContact.identity_id == identity.id,
                    IdentityContact.contact_type == ContactType.EMAIL.value,
                    IdentityContact.contact_value == identity.email,
                )
            )
            if not existing.scalar_one_or_none():
                contact = IdentityContact(
                    identity_id=identity.id,
                    contact_type=ContactType.EMAIL.value,
                    contact_value=identity.email,
                    purpose=ContactPurpose.PRIMARY.value,
                    verified=identity.email_verified,
                    source="migration",
                )
                db.add(contact)
                migrated += 1

        # Migrate phone
        if identity.phone:
            normalized = normalize_mobile(identity.phone)
            if normalized:
                existing = await db.execute(
                    select(IdentityContact).where(
                        IdentityContact.identity_id == identity.id,
                        IdentityContact.contact_type == ContactType.MOBILE.value,
                        IdentityContact.contact_value == normalized,
                    )
                )
                if not existing.scalar_one_or_none():
                    contact = IdentityContact(
                        identity_id=identity.id,
                        contact_type=ContactType.MOBILE.value,
                        contact_value=normalized,
                        purpose=ContactPurpose.PRIMARY.value,
                        verified=identity.phone_verified if hasattr(identity, "phone_verified") else False,
                        source="migration",
                    )
                    db.add(contact)
                    migrated += 1

        # Update primary_email and primary_phone
        if not identity.primary_email and identity.email:
            identity.primary_email = identity.email
        if not identity.primary_phone and identity.phone:
            normalized = normalize_mobile(identity.phone)
            if normalized:
                identity.primary_phone = normalized

    await db.flush()
    logger.info(f"[Migration] Migrated {migrated} IdentityContact records")
    return migrated


async def migrate_org_members(db: AsyncSession) -> int:
    """Migrate OrgMember data to IdentityBinding."""
    logger.info("[Migration] Starting OrgMember → IdentityBinding migration...")

    result = await db.execute(select(OrgMember).where(OrgMember.user_id.isnot(None)))
    org_members = result.scalars().all()

    migrated = 0
    for member in org_members:
        # Get user's identity_id
        user_result = await db.execute(select(User).where(User.id == member.user_id))
        user = user_result.scalar_one_or_none()
        if not user or not user.identity_id:
            continue

        # Get provider type
        if not member.provider_id:
            continue

        provider_result = await db.execute(select(IdentityProvider).where(IdentityProvider.id == member.provider_id))
        provider = provider_result.scalar_one_or_none()
        if not provider:
            continue

        provider_type = provider.provider_type

        # Determine provider_user_id
        provider_user_id = member.unionid or member.open_id or member.external_id
        if not provider_user_id:
            continue

        # Check if binding already exists
        existing = await db.execute(
            select(IdentityBinding).where(
                IdentityBinding.provider_type == provider_type,
                IdentityBinding.provider_user_id == provider_user_id,
            )
        )
        if existing.scalar_one_or_none():
            continue

        # Normalize mobile
        mobile = None
        if member.phone:
            mobile = normalize_mobile(member.phone)

        # Create binding
        binding = IdentityBinding(
            identity_id=user.identity_id,
            provider_type=provider_type,
            provider_user_id=provider_user_id,
            email=member.email,
            mobile=mobile,
            raw_data={
                "org_member_id": str(member.id),
                "name": member.name,
                "title": member.title,
            },
        )
        db.add(binding)
        migrated += 1

    await db.flush()
    logger.info(f"[Migration] Migrated {migrated} IdentityBinding records")
    return migrated


async def create_web_bindings(db: AsyncSession) -> int:
    """Create bindings for web-registered users."""
    logger.info("[Migration] Creating web bindings for username-based users...")

    result = await db.execute(select(Identity).where(Identity.username.isnot(None)))
    identities = result.scalars().all()

    migrated = 0
    for identity in identities:
        if not identity.username:
            continue

        existing = await db.execute(
            select(IdentityBinding).where(
                IdentityBinding.provider_type == "web",
                IdentityBinding.provider_user_id == identity.username,
            )
        )
        if existing.scalar_one_or_none():
            continue

        binding = IdentityBinding(
            identity_id=identity.id,
            provider_type="web",
            provider_user_id=identity.username,
            email=identity.email,
            mobile=normalize_mobile(identity.phone) if identity.phone else None,
        )
        db.add(binding)
        migrated += 1

    await db.flush()
    logger.info(f"[Migration] Created {migrated} web IdentityBinding records")
    return migrated


async def run_migration():
    """Run all migrations."""
    logger.info("[Migration] Starting migration...")

    async with async_session() as db:
        try:
            identity_count = await migrate_identities(db)
            org_count = await migrate_org_members(db)
            web_count = await create_web_bindings(db)

            await db.commit()

            logger.info(f"[Migration] ✅ Migration completed successfully!")
            logger.info(f"  - IdentityContact: {identity_count} records")
            logger.info(f"  - IdentityBinding (OrgMember): {org_count} records")
            logger.info(f"  - IdentityBinding (Web): {web_count} records")

        except Exception as e:
            await db.rollback()
            logger.error(f"[Migration] ❌ Migration failed: {e}")
            raise


if __name__ == "__main__":
    asyncio.run(run_migration())
