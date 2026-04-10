"""Unified verification code service for email and mobile.

Provides:
- Verification code generation and storage (Redis)
- SMS verification code sending (via sms_service)
- Email verification code sending (via email_verification_service)
- Rate limiting
- Code verification
"""

import hashlib
import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from enum import Enum as PyEnum

from loguru import logger

from app.config import get_settings
from app.core.events import get_redis
from app.services.identity_service import normalize_mobile


class VerificationPurpose(str, PyEnum):
    """Verification code purpose."""

    REGISTER = "register"
    BIND = "bind"
    RESET_PASSWORD = "reset_password"
    LOGIN = "login"


class VerificationChannel(str, PyEnum):
    """Verification channel."""

    EMAIL = "email"
    MOBILE = "mobile"


class VerificationCodeService:
    """Unified verification code service."""

    KEY_PREFIX = "verification_code:"

    async def generate_code(
        self,
        contact: str,
        channel: str,
        purpose: str,
        length: int = 6,
    ) -> tuple[str, int]:
        """Generate and store a verification code.

        Args:
            contact: Email or mobile number
            channel: "email" or "mobile"
            purpose: Purpose (register/bind/reset_password)
            length: Code length (default 6 digits)

        Returns:
            Tuple of (code, expire_seconds)
        """
        redis = await get_redis()
        settings = get_settings()

        if channel == VerificationChannel.MOBILE.value:
            contact = normalize_mobile(contact)
            expire_seconds = settings.VERIFICATION_CODE_MOBILE_EXPIRE
        else:
            expire_seconds = settings.VERIFICATION_CODE_EMAIL_EXPIRE

        key = self._get_key(contact, channel, purpose)

        raw_code = "".join([str(secrets.randbelow(10)) for _ in range(length)])
        code_hash = self._hash_code(raw_code)

        data = {
            "contact": contact,
            "channel": channel,
            "purpose": purpose,
            "code_hash": code_hash,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        await redis.setex(key, expire_seconds, json.dumps(data))

        return raw_code, expire_seconds

    async def verify_code(
        self,
        contact: str,
        channel: str,
        purpose: str,
        code: str,
    ) -> tuple[bool, str]:
        """Verify a verification code.

        Args:
            contact: Email or mobile number
            channel: "email" or "mobile"
            purpose: Purpose
            code: Verification code to verify

        Returns:
            Tuple of (success, message)
        """
        redis = await get_redis()

        if channel == VerificationChannel.MOBILE.value:
            contact = normalize_mobile(contact)

        key = self._get_key(contact, channel, purpose)

        stored_data = await redis.get(key)
        if not stored_data:
            return False, "Verification code expired or not found"

        try:
            data = json.loads(stored_data)
        except json.JSONDecodeError:
            return False, "Invalid verification data"

        stored_hash = data.get("code_hash")
        if not stored_hash:
            return False, "Invalid verification data"

        input_hash = self._hash_code(code)
        if input_hash != stored_hash:
            return False, "Invalid verification code"

        await redis.delete(key)

        return True, "Verified successfully"

    async def check_rate_limit(
        self,
        contact: str,
        channel: str,
    ) -> tuple[bool, str]:
        """Check if rate limit allows sending.

        Args:
            contact: Email or mobile number
            channel: "email" or "mobile"

        Returns:
            Tuple of (allowed, error_message)
        """
        redis = await get_redis()
        settings = get_settings()

        if channel == VerificationChannel.MOBILE.value:
            contact = normalize_mobile(contact)

        now = datetime.now(timezone.utc)
        daily_key = f"verification:daily:{channel}:{contact}:{now.strftime('%Y%m%d')}"
        interval_key = f"verification:interval:{channel}:{contact}"

        daily_count = await redis.get(daily_key)
        daily_limit = settings.VERIFICATION_CODE_DAILY_LIMIT
        if daily_count and int(daily_count) >= daily_limit:
            return False, f"Daily limit ({daily_limit}) exceeded"

        ttl = await redis.ttl(interval_key)
        interval_seconds = settings.VERIFICATION_CODE_SEND_INTERVAL
        if ttl > 0:
            return False, f"Please wait {ttl} seconds before requesting again"

        return True, ""

    async def record_send(
        self,
        contact: str,
        channel: str,
    ):
        """Record a send for rate limiting."""
        redis = await get_redis()
        settings = get_settings()

        if channel == VerificationChannel.MOBILE.value:
            contact = normalize_mobile(contact)

        now = datetime.now(timezone.utc)
        daily_key = f"verification:daily:{channel}:{contact}:{now.strftime('%Y%m%d')}"
        interval_key = f"verification:interval:{channel}:{contact}"
        interval_seconds = settings.VERIFICATION_CODE_SEND_INTERVAL

        pipe = redis.pipeline()
        pipe.incr(daily_key)
        pipe.expire(daily_key, 86400)
        pipe.setex(interval_key, interval_seconds, "1")
        await pipe.execute()

    async def send_mobile_code(
        self,
        mobile: str,
        purpose: str,
    ) -> tuple[bool, str]:
        """Send verification code via SMS.

        Args:
            mobile: Mobile number
            purpose: Purpose (register/bind/reset_password)

        Returns:
            Tuple of (success, message)
        """
        from app.services.sms_service import sms_service

        normalized = normalize_mobile(mobile)
        if not normalized:
            return False, "Invalid mobile number format"

        allowed, error = await self.check_rate_limit(normalized, VerificationChannel.MOBILE.value)
        if not allowed:
            return False, error

        code, expire_seconds = await self.generate_code(normalized, VerificationChannel.MOBILE.value, purpose)

        success, message = await sms_service.send_verification_code(normalized, code, purpose)

        if success:
            await self.record_send(normalized, VerificationChannel.MOBILE.value)
            logger.info(f"[Verification] Sent SMS code to {normalized[:3]}****{normalized[-4:]} for {purpose}")
            return True, f"Verification code sent, expires in {expire_seconds // 60} minutes"
        else:
            return False, f"Failed to send SMS: {message}"

    async def send_email_code(
        self,
        email: str,
        purpose: str,
        display_name: str = "User",
    ) -> tuple[bool, str]:
        """Send verification code via email.

        Args:
            email: Email address
            purpose: Purpose
            display_name: User display name

        Returns:
            Tuple of (success, message)
        """
        allowed, error = await self.check_rate_limit(email, VerificationChannel.EMAIL.value)
        if not allowed:
            return False, error

        code, expire_seconds = await self.generate_code(email, VerificationChannel.EMAIL.value, purpose)

        try:
            from app.services.system_email_service import send_system_email, render_email_template

            settings = get_settings()
            variables = {
                "display_name": display_name,
                "verification_code": code,
                "expiry_minutes": str(expire_seconds // 60),
            }

            template_map = {
                VerificationPurpose.REGISTER.value: "email_verification",
                VerificationPurpose.BIND.value: "email_verification",
                VerificationPurpose.RESET_PASSWORD.value: "password_reset",
            }

            template_name = template_map.get(purpose, "email_verification")
            subject, body = await render_email_template(template_name, variables)
            await send_system_email(email, subject, body)

            await self.record_send(email, VerificationChannel.EMAIL.value)
            logger.info(f"[Verification] Sent email code to {email} for {purpose}")
            return True, f"Verification code sent, expires in {expire_seconds // 60} minutes"

        except Exception as e:
            logger.exception(f"[Verification] Failed to send email: {e}")
            return False, f"Failed to send email: {str(e)}"

    async def send_code(
        self,
        contact: str,
        channel: str,
        purpose: str,
        display_name: str = "User",
    ) -> tuple[bool, str]:
        """Send verification code via specified channel.

        Args:
            contact: Email or mobile number
            channel: "email" or "mobile"
            purpose: Purpose
            display_name: User display name (for email)

        Returns:
            Tuple of (success, message)
        """
        if channel == VerificationChannel.MOBILE.value:
            return await self.send_mobile_code(contact, purpose)
        elif channel == VerificationChannel.EMAIL.value:
            return await self.send_email_code(contact, purpose, display_name)
        else:
            return False, f"Unknown channel: {channel}"

    def _get_key(self, contact: str, channel: str, purpose: str) -> str:
        """Generate Redis key for verification code."""
        return f"{self.KEY_PREFIX}{channel}:{purpose}:{contact}"

    def _hash_code(self, code: str) -> str:
        """Hash verification code for security."""
        return hashlib.sha256(code.encode("utf-8")).hexdigest()


verification_service = VerificationCodeService()
