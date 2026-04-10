"""SMS service for sending verification codes.

Supports multiple providers:
- Alibaba Cloud SMS (primary)
- Tencent Cloud SMS (reserved for future)
"""

import json
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

from loguru import logger

from app.core.events import get_redis
from app.config import get_settings


class SMSProvider(ABC):
    """Abstract SMS provider interface."""

    @abstractmethod
    async def send_verification_code(
        self,
        mobile: str,
        code: str,
        purpose: str = "register",
    ) -> tuple[bool, str]:
        """Send verification code via SMS.

        Args:
            mobile: Target mobile number (normalized)
            code: Verification code
            purpose: Purpose (register/bind/reset_password)

        Returns:
            Tuple of (success, message)
        """
        pass


class AlibabaSMSProvider(SMSProvider):
    """Alibaba Cloud SMS provider."""

    def __init__(
        self,
        access_key_id: str,
        access_key_secret: str,
        sign_name: str,
        template_codes: dict[str, str],
    ):
        self.access_key_id = access_key_id
        self.access_key_secret = access_key_secret
        self.sign_name = sign_name
        self.template_codes = template_codes

    async def send_verification_code(
        self,
        mobile: str,
        code: str,
        purpose: str = "register",
    ) -> tuple[bool, str]:
        """Send verification code via Alibaba Cloud SMS."""
        try:
            from alibabacloud_dysmsapi20170525.client import Client
            from alibabacloud_dysmsapi20170525 import models as sms_models
            from alibabacloud_tea_openapi import models as open_api_models

            config = open_api_models.Config(
                access_key_id=self.access_key_id,
                access_key_secret=self.access_key_secret,
            )
            config.endpoint = "dysmsapi.aliyuncs.com"

            client = Client(config)

            template_code = self.template_codes.get(purpose) or self.template_codes.get("register", "")
            if not template_code:
                return False, f"Template code not found for purpose: {purpose}"

            send_request = sms_models.SendSmsRequest(
                phone_numbers=mobile,
                sign_name=self.sign_name,
                template_code=template_code,
                template_param=json.dumps({"code": code}),
            )

            response = client.send_sms(send_request)

            if response.body and response.body.code == "OK":
                logger.info(f"[SMS] Sent verification code to {mobile[:3]}****{mobile[-4:]}")
                return True, "Sent successfully"
            else:
                error_msg = response.body.message if response.body else "Unknown error"
                logger.error(f"[SMS] Failed to send: {error_msg}")
                return False, error_msg

        except Exception as e:
            logger.exception(f"[SMS] Alibaba SMS error: {e}")
            return False, str(e)


class TencentSMSProvider(SMSProvider):
    """Tencent Cloud SMS provider (reserved for future)."""

    def __init__(
        self,
        secret_id: str,
        secret_key: str,
        app_id: str,
        sign_name: str,
        template_codes: dict[str, str],
    ):
        self.secret_id = secret_id
        self.secret_key = secret_key
        self.app_id = app_id
        self.sign_name = sign_name
        self.template_codes = template_codes

    async def send_verification_code(
        self,
        mobile: str,
        code: str,
        purpose: str = "register",
    ) -> tuple[bool, str]:
        """Send verification code via Tencent Cloud SMS."""
        try:
            from tencentcloud.common import credential
            from tencentcloud.common.profile.client_profile import ClientProfile
            from tencentcloud.common.profile.http_profile import HttpProfile
            from tencentcloud.sms.v20210111 import sms_client, models

            cred = credential.Credential(self.secret_id, self.secret_key)
            http_profile = HttpProfile()
            http_profile.endpoint = "sms.tencentcloudapi.com"
            client_profile = ClientProfile()
            client_profile.httpProfile = http_profile

            client = sms_client.SmsClient(cred, "ap-guangzhou", client_profile)

            template_id = self.template_codes.get(purpose) or self.template_codes.get("register", "")
            if not template_id:
                return False, f"Template ID not found for purpose: {purpose}"

            req = models.SendSmsRequest()
            req.SmsSdkAppId = self.app_id
            req.SignName = self.sign_name
            req.TemplateId = template_id
            req.PhoneNumberSet = [f"+86{mobile}"]
            req.TemplateParamSet = [code]

            response = client.SendSms(req)

            if response.SendStatusSet and response.SendStatusSet[0].Code == "Ok":
                logger.info(f"[SMS] Sent verification code to {mobile[:3]}****{mobile[-4:]}")
                return True, "Sent successfully"
            else:
                error_msg = response.SendStatusSet[0].Message if response.SendStatusSet else "Unknown error"
                logger.error(f"[SMS] Failed to send: {error_msg}")
                return False, error_msg

        except Exception as e:
            logger.exception(f"[SMS] Tencent SMS error: {e}")
            return False, str(e)


class SMSService:
    """SMS service with provider abstraction."""

    def __init__(self):
        self._providers: dict[str, SMSProvider] = {}
        self._default_provider: str = "alibaba"

    def register_provider(self, name: str, provider: SMSProvider, default: bool = False):
        """Register an SMS provider."""
        self._providers[name] = provider
        if default:
            self._default_provider = name

    async def send_verification_code(
        self,
        mobile: str,
        code: str,
        purpose: str = "register",
        provider_name: str | None = None,
    ) -> tuple[bool, str]:
        """Send verification code.

        Args:
            mobile: Target mobile number (normalized)
            code: Verification code
            purpose: Purpose (register/bind/reset_password)
            provider_name: Provider to use (default: configured default)

        Returns:
            Tuple of (success, message)
        """
        provider = self._providers.get(provider_name or self._default_provider)
        if not provider:
            return False, f"SMS provider not configured: {provider_name or self._default_provider}"

        return await provider.send_verification_code(mobile, code, purpose)

    async def check_rate_limit(
        self,
        mobile: str,
        daily_limit: int = 10,
        interval_seconds: int = 60,
    ) -> tuple[bool, str]:
        """Check if rate limit allows sending.

        Args:
            mobile: Target mobile number
            daily_limit: Max sends per day
            interval_seconds: Min seconds between sends

        Returns:
            Tuple of (allowed, error_message)
        """
        redis = await get_redis()
        now = datetime.now(timezone.utc)
        today_key = f"sms:daily:{mobile}:{now.strftime('%Y%m%d')}"
        interval_key = f"sms:interval:{mobile}"

        daily_count = await redis.get(today_key)
        if daily_count and int(daily_count) >= daily_limit:
            return False, f"Daily limit ({daily_limit}) exceeded"

        ttl = await redis.ttl(interval_key)
        if ttl > 0:
            return False, f"Please wait {ttl} seconds before requesting again"

        return True, ""

    async def record_send(
        self,
        mobile: str,
        interval_seconds: int = 60,
    ):
        """Record a send for rate limiting."""
        redis = await get_redis()
        now = datetime.now(timezone.utc)
        today_key = f"sms:daily:{mobile}:{now.strftime('%Y%m%d')}"
        interval_key = f"sms:interval:{mobile}"

        pipe = redis.pipeline()
        pipe.incr(today_key)
        pipe.expire(today_key, 86400)
        pipe.setex(interval_key, interval_seconds, "1")
        await pipe.execute()


def init_sms_service() -> SMSService:
    """Initialize SMS service from settings."""
    settings = get_settings()
    service = SMSService()

    alibaba_enabled = bool(settings.ALIBABA_SMS_ACCESS_KEY)
    if alibaba_enabled:
        provider = AlibabaSMSProvider(
            access_key_id=settings.ALIBABA_SMS_ACCESS_KEY,
            access_key_secret=settings.ALIBABA_SMS_SECRET,
            sign_name=settings.ALIBABA_SMS_SIGN_NAME,
            template_codes={
                "register": settings.ALIBABA_SMS_TEMPLATE_REGISTER,
                "bind": settings.ALIBABA_SMS_TEMPLATE_BIND,
                "reset_password": settings.ALIBABA_SMS_TEMPLATE_RESET,
            },
        )
        service.register_provider("alibaba", provider, default=True)
        logger.info("[SMS] Alibaba SMS provider initialized")

    tencent_enabled = bool(getattr(settings, "TENCENT_SMS_SECRET_ID", None))
    if tencent_enabled:
        provider = TencentSMSProvider(
            secret_id=settings.TENCENT_SMS_SECRET_ID,
            secret_key=settings.TENCENT_SMS_SECRET_KEY,
            app_id=settings.TENCENT_SMS_APP_ID,
            sign_name=settings.TENCENT_SMS_SIGN_NAME,
            template_codes={
                "register": settings.TENCENT_SMS_TEMPLATE_REGISTER,
                "bind": settings.TENCENT_SMS_TEMPLATE_BIND,
                "reset_password": settings.TENCENT_SMS_TEMPLATE_RESET,
            },
        )
        service.register_provider("tencent", provider, default=not alibaba_enabled)
        logger.info("[SMS] Tencent SMS provider initialized")

    return service


sms_service = init_sms_service()
