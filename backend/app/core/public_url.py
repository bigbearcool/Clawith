"""Utility functions for getting platform public URL."""

import os
from urllib.parse import urlparse


def get_public_base_url_sync() -> str:
    """Get the platform public base URL (sync version - only checks env var).

    For async version with database lookup, use get_public_base_url_async().
    Returns empty string if not configured.
    """
    url = os.environ.get("PUBLIC_BASE_URL", "").strip()
    return url.rstrip("/") if url else ""


async def get_public_base_url_async(db=None) -> str:
    """Get the platform public base URL (async version - checks DB first, then env).

    Priority:
    1. Database system_settings.public_base_url (if db provided)
    2. Environment variable PUBLIC_BASE_URL

    Returns empty string if not configured.
    """
    if db:
        from sqlalchemy import select
        from app.models.system_settings import SystemSetting

        result = await db.execute(select(SystemSetting).where(SystemSetting.key == "public_base_url"))
        setting = result.scalar_one_or_none()
        if setting and setting.value:
            return setting.value.strip().rstrip("/")

    return get_public_base_url_sync()


def get_sso_domain_from_slug(slug: str, base_url: str = None) -> str:
    """Generate SSO subdomain URL from tenant slug.

    Args:
        slug: Tenant slug (e.g., "acme")
        base_url: Platform base URL (e.g., "https://bigbear.cool"). If None, uses env var.

    Returns:
        SSO domain URL (e.g., "https://acme.bigbear.cool")

    Example:
        get_sso_domain_from_slug("acme", "https://bigbear.cool") → "https://acme.bigbear.cool"
    """
    if not slug:
        return ""

    if base_url is None:
        base_url = get_public_base_url_sync()

    if not base_url:
        return ""

    parsed = urlparse(base_url)
    domain = parsed.netloc

    if parsed.scheme and domain:
        return f"{parsed.scheme}://{slug}.{domain}"

    return ""
