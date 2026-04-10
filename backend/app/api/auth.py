"""Authentication API routes."""

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from loguru import logger
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, get_current_user, hash_password, verify_password
from app.database import get_db
from app.models.user import User, Identity
from app.models.identity import IdentityProvider
from app.schemas.schemas import (
    AddContactRequest,
    ContactOut,
    IdentityBindRequest,
    IdentityUnbindRequest,
    OAuthAuthorizeResponse,
    OAuthCallbackRequest,
    SelectTenantRequest,
    SendVerificationCodeRequest,
    TokenResponse,
    UserLogin,
    UserOut,
    UserRegister,
    UserUpdate,
    VerifyCodeRequest,
)
from sqlalchemy.orm import selectinload
from jose import jwt
from app.config import get_settings


router = APIRouter(prefix="/auth", tags=["auth"])


def create_temp_token(identity_id: uuid.UUID, expire_minutes: int = 10) -> str:
    """Create a temporary token for tenant selection flow."""
    settings = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(minutes=expire_minutes)
    payload = {
        "sub": str(identity_id),
        "type": "temp_tenant_select",
        "exp": expire,
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_temp_token(token: str) -> uuid.UUID:
    """Decode and validate a temporary token."""
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        if payload.get("type") != "temp_tenant_select":
            raise ValueError("Invalid token type")
        return uuid.UUID(payload["sub"])
    except Exception as e:
        raise ValueError(f"Invalid or expired token: {e}")


async def get_current_user_optional(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """Get current user or None if not authenticated."""
    from app.core.security import decode_access_token
    from sqlalchemy.orm import selectinload

    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return None

    token = auth_header.split(" ", 1)[1]
    try:
        payload = decode_access_token(token)
        user_id = payload.get("sub")
        if not user_id:
            return None

        result = await db.execute(
            select(User).where(User.id == uuid.UUID(user_id)).options(selectinload(User.identity))
        )
        user = result.scalar_one_or_none()
        return user
    except Exception:
        return None


@router.get("/registration-config")
async def get_registration_config(db: AsyncSession = Depends(get_db)):
    """Public endpoint — returns registration requirements (no auth needed)."""
    from app.models.system_settings import SystemSetting

    result = await db.execute(select(SystemSetting).where(SystemSetting.key == "invitation_code_enabled"))
    setting = result.scalar_one_or_none()
    enabled = setting.value.get("enabled", False) if setting else False
    return {"invitation_code_required": enabled}


@router.get("/check-duplicate")
async def check_duplicate(
    email: str | None = Query(None, description="Email to check"),
    username: str | None = Query(None, description="Username to check"),
    db: AsyncSession = Depends(get_db),
):
    """Check if email or username already exists."""
    from app.models.user import Identity

    result = {"email_exists": False, "username_exists": False, "conflicts": []}

    if email:
        # Check Identity email
        existing = await db.execute(select(Identity).where(Identity.email == email))
        if existing.scalar_one_or_none():
            result["email_exists"] = True
            result["conflicts"].append({"type": "email", "scope": "global", "message": "Email already registered"})

    if username:
        existing = await db.execute(select(Identity).where(Identity.username == username))
        if existing.scalar_one_or_none():
            result["username_exists"] = True
            result["conflicts"].append({"type": "username", "scope": "global", "message": "Username already taken"})

    result["has_conflict"] = result["email_exists"] or result["username_exists"]
    return result


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(data: UserRegister, db: AsyncSession = Depends(get_db)):
    """Register a new user account.

    The first user to register becomes the platform admin automatically and is
    assigned to the default company as org_admin. Subsequent users register
    without a company — they must create or join one via /tenants/self-create
    or /tenants/join.

    Supports optional SSO registration by providing provider + provider_code.
    """
    # Handle SSO registration if provider info provided
    if data.provider and data.provider_code:
        from app.services.auth_registry import auth_provider_registry
        from app.services.registration_service import registration_service

        # Get provider
        auth_provider = await auth_provider_registry.get_provider(db, data.provider)
        if not auth_provider:
            raise HTTPException(status_code=400, detail=f"Provider '{data.provider}' not supported")

        # Perform SSO registration
        user, is_new, error = await registration_service.register_with_sso(
            db, data.provider, data.provider_code, auth_provider
        )

        if error:
            raise HTTPException(status_code=400, detail=error)

        # If no tenant, check for email domain match
        if not user.tenant_id and data.email:
            tenant, _ = await registration_service.get_tenant_for_registration(db, email=data.email)
            if tenant:
                user.tenant_id = tenant.id

        # Generate token
        token = create_access_token(str(user.id), user.role)

        return TokenResponse(
            access_token=token,
            user=UserOut.model_validate(user),
            needs_company_setup=user.tenant_id is None,
        )

    # Regular username/password registration
    settings = get_settings()

    # Check if this is the first user (→ platform admin + default company org_admin)
    from sqlalchemy import func

    user_count = await db.execute(select(func.count()).select_from(User))
    is_first_user = user_count.scalar() == 0

    # Check if new identity system is enabled and require invitation code
    if settings.FEATURE_NEW_IDENTITY_SYSTEM and not is_first_user:
        if not data.invitation_code:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="邀请码必填，请联系企业管理员获取邀请码"
            )

    # Check existing Identity
    existing = await db.execute(
        select(Identity).where((Identity.username == data.username) | (Identity.email == data.email))
    )
    if existing.scalars().first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username or email already exists")

    # Note: invitation code validation has been moved to the company-join flow
    # (POST /tenants/join). Registration itself is now open.

    # Resolve tenant and role for first user only
    tenant_uuid = None
    role = "member"
    quota_defaults: dict = {}

    from app.services.registration_service import registration_service

    if is_first_user:
        from app.models.tenant import Tenant

        default = await db.execute(select(Tenant).where(Tenant.slug == "default"))
        tenant = default.scalar_one_or_none()
        if not tenant:
            tenant = Tenant(name="Default", slug="default", im_provider="web_only")
            db.add(tenant)
            await db.flush()
        tenant_uuid = tenant.id
        role = "platform_admin"
        quota_defaults = {
            "quota_message_limit": tenant.default_message_limit,
            "quota_message_period": tenant.default_message_period,
            "quota_max_agents": tenant.default_max_agents,
            "quota_agent_ttl_hours": tenant.default_agent_ttl_hours,
        }
    else:
        # Try to resolve tenant via invitation code or email domain
        tenant, _ = await registration_service.get_tenant_for_registration(
            db, email=data.email, invitation_code=data.invitation_code
        )
        if tenant:
            tenant_uuid = tenant.id
            quota_defaults = {
                "quota_message_limit": tenant.default_message_limit,
                "quota_message_period": tenant.default_message_period,
                "quota_max_agents": tenant.default_max_agents,
                "quota_agent_ttl_hours": tenant.default_agent_ttl_hours,
            }

    # Create Identity first
    identity = Identity(
        email=data.email,
        username=data.username,
        password_hash=hash_password(data.password),
        email_verified=False,
        is_active=True,
        is_platform_admin=(role == "platform_admin"),
    )
    db.add(identity)
    await db.flush()

    # Create User linked to Identity
    user = User(
        identity_id=identity.id,
        display_name=data.display_name or data.username,
        role=role,
        tenant_id=tenant_uuid,
        **quota_defaults,
    )
    db.add(user)
    await db.flush()

    # Bind to OrgMember if exists (linking platform user to organization structure)
    await registration_service.bind_org_member(db, user)

    # Auto-create Participant identity for the new user
    from app.models.participant import Participant

    db.add(
        Participant(
            type="user",
            ref_id=user.id,
            display_name=user.display_name,
            avatar_url=user.avatar_url,
        )
    )
    await db.flush()

    # Seed default agents after first user (platform admin) registration
    if is_first_user:
        await db.commit()  # commit user first so seeder can find the admin
        try:
            from app.services.agent_seeder import seed_default_agents

            await seed_default_agents()
        except Exception as e:
            logger.warning(f"Failed to seed default agents: {e}")

    needs_setup = tenant_uuid is None
    token = create_access_token(str(user.id), user.role)
    return TokenResponse(
        access_token=token,
        user=UserOut.model_validate(user),
        needs_company_setup=needs_setup,
    )


@router.post("/login", response_model=TokenResponse)
async def login(data: UserLogin, db: AsyncSession = Depends(get_db)):
    """Login with username/email and password."""
    # Find Identity by username or email
    identity_result = await db.execute(
        select(Identity).where((Identity.username == data.login_identifier) | (Identity.email == data.login_identifier))
    )
    identity = identity_result.scalar_one_or_none()

    if not identity or not identity.password_hash or not verify_password(data.password, identity.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    if not identity.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is disabled")

    # Find User linked to this Identity
    user_result = await db.execute(select(User).where(User.identity_id == identity.id))
    user = user_result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is disabled")

    # Check if user's company is disabled
    if user.tenant_id:
        from app.models.tenant import Tenant

        t_result = await db.execute(select(Tenant).where(Tenant.id == user.tenant_id))
        tenant = t_result.scalar_one_or_none()
        if tenant and not tenant.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your company has been disabled. Please contact the platform administrator.",
            )

    needs_setup = user.tenant_id is None
    token = create_access_token(str(user.id), user.role)
    return TokenResponse(
        access_token=token,
        user=UserOut.model_validate(user),
        needs_company_setup=needs_setup,
    )


@router.get("/me", response_model=UserOut)
async def get_me(current_user: User = Depends(get_current_user)):
    """Get current user profile."""
    return UserOut.model_validate(current_user)


@router.get("/my-tenants")
async def get_my_tenants(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get all tenants the current user belongs to."""
    from app.models.tenant import Tenant

    # Get user's current tenant
    if current_user.tenant_id:
        result = await db.execute(select(Tenant).where(Tenant.id == current_user.tenant_id))
        tenant = result.scalar_one_or_none()
        if tenant:
            return [
                {
                    "id": str(tenant.id),
                    "name": tenant.name,
                    "slug": tenant.slug,
                }
            ]
    return []


@router.patch("/me", response_model=UserOut)
async def update_me(
    data: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update current user profile."""
    update_data = data.model_dump(exclude_unset=True)

    # Get identity for this user
    identity_result = await db.execute(select(Identity).where(Identity.id == current_user.identity_id))
    identity = identity_result.scalar_one_or_none()
    if not identity:
        raise HTTPException(status_code=500, detail="Identity not found")

    # Validate username uniqueness if changing
    if "username" in update_data and update_data["username"] != identity.username:
        existing = await db.execute(select(Identity).where(Identity.username == update_data["username"]))
        if existing.scalars().first():
            raise HTTPException(status_code=409, detail="Username already taken")

    # Validate email uniqueness if changing
    if "email" in update_data and update_data["email"] != identity.email:
        existing = await db.execute(select(Identity).where(Identity.email == update_data["email"]))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Email already registered")

    # Validate mobile uniqueness if changing
    if "primary_mobile" in update_data and update_data["primary_mobile"] != identity.phone:
        existing = await db.execute(select(Identity).where(Identity.phone == update_data["primary_mobile"]))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Mobile already registered")

    # Update Identity fields
    if "username" in update_data:
        identity.username = update_data["username"]
    if "primary_mobile" in update_data:
        identity.phone = update_data["primary_mobile"]

    # Update User fields (excluding identity-related fields)
    user_fields = {"display_name", "avatar_url", "title"}
    for field in user_fields:
        if field in update_data:
            setattr(current_user, field, update_data[field])

    # Handle email change: send verification first, don't update until verified
    verification_sent = False
    if "email" in update_data:
        new_email = update_data["email"].lower().strip()
        if new_email != identity.email:
            # Check if new email is already used by another identity
            existing = await db.execute(select(Identity).where(Identity.email == new_email))
            if existing.scalar_one_or_none():
                raise HTTPException(status_code=409, detail="Email already registered")

            # Send verification email to new address
            from app.services.email_verification_service import email_verification_service
            from app.config import get_settings

            settings = get_settings()
            raw_code, _ = await email_verification_service.create_email_verification_token(identity.id, new_email)
            await email_verification_service.send_verification_email(
                to=new_email,
                display_name=current_user.display_name or new_email,
                verification_code=raw_code,
                expiry_minutes=settings.EMAIL_VERIFICATION_TOKEN_EXPIRE_MINUTES,
            )
            verification_sent = True

    await db.flush()

    # Sync phone to OrgMember if changed (email sync happens after verification)
    if "primary_mobile" in update_data:
        from app.services.registration_service import registration_service

        await registration_service.sync_org_member_contact_from_user(
            db,
            current_user,
            sync_email=False,
            sync_phone=True,
        )

    result = UserOut.model_validate(current_user)
    if verification_sent:
        result = result.model_dump()
        result["verification_sent"] = True
        result["message"] = "Verification email sent to new address. Please verify to complete the change."
    return result


@router.put("/me/password")
async def change_password(
    data: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Change current user's password. Requires old_password verification for existing passwords."""
    old_password = data.get("old_password", "")
    new_password = data.get("new_password", "")

    if not new_password:
        raise HTTPException(status_code=400, detail="new_password is required")

    if len(new_password) < 6:
        raise HTTPException(status_code=400, detail="New password must be at least 6 characters")

    # Get identity to check password_hash
    identity_result = await db.execute(select(Identity).where(Identity.id == current_user.identity_id))
    identity = identity_result.scalar_one_or_none()
    if not identity:
        raise HTTPException(status_code=404, detail="Identity not found")

    # If user has existing password, require old_password verification
    if identity.password_hash:
        if not old_password:
            raise HTTPException(status_code=400, detail="old_password is required")
        if not verify_password(old_password, identity.password_hash):
            raise HTTPException(status_code=400, detail="Current password is incorrect")

    identity.password_hash = hash_password(new_password)
    await db.commit()
    return {"ok": True}


# ─── Password Reset ─────────────────────────────────────────────


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


@router.post("/forgot-password")
async def forgot_password(
    data: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    """Send password reset email."""
    from app.services.email_verification_service import email_verification_service
    from app.services.system_email_service import send_password_reset_email
    from app.config import get_settings

    result = await db.execute(select(Identity).where(Identity.email == data.email.lower().strip()))
    identity = result.scalar_one_or_none()

    # Always return success to prevent email enumeration
    if not identity or not identity.email:
        return {"ok": True, "message": "If the email exists, a reset link has been sent"}

    user_result = await db.execute(select(User).where(User.identity_id == identity.id))
    user = user_result.scalar_one_or_none()

    settings = get_settings()
    raw_token, expires_at = await email_verification_service.create_email_verification_token(
        identity.id, identity.email
    )

    # Get public_base_url from database (platform settings) or fallback to env/config
    from app.models.system_settings import SystemSetting

    platform_setting = await db.execute(select(SystemSetting).where(SystemSetting.key == "platform"))
    platform_setting = platform_setting.scalar_one_or_none()
    base_url = (
        (platform_setting.value.get("public_base_url") if platform_setting and platform_setting.value else None)
        or settings.PUBLIC_BASE_URL
        or "http://localhost:3008"
    )
    reset_url = f"{base_url}/reset-password?token={raw_token}"

    await send_password_reset_email(
        to=identity.email,
        display_name=user.display_name if user and user.display_name else identity.email,
        reset_url=reset_url,
        expiry_minutes=settings.EMAIL_VERIFICATION_TOKEN_EXPIRE_MINUTES,
        db=db,
    )

    return {"ok": True, "message": "If the email exists, a reset link has been sent"}


@router.post("/reset-password")
async def reset_password(
    data: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    """Reset password using token from email."""
    from app.services.email_verification_service import email_verification_service

    if len(data.new_password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

    token_data = await email_verification_service.consume_email_verification_token(data.token)
    if not token_data:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    result = await db.execute(select(Identity).where(Identity.id == token_data["identity_id"]))
    identity = result.scalar_one_or_none()
    if not identity:
        raise HTTPException(status_code=404, detail="User not found")

    identity.password_hash = hash_password(data.new_password)
    await db.commit()

    return {"ok": True, "message": "Password reset successfully"}


@router.get("/email-hint")
async def get_email_hint(
    username: str,
    db: AsyncSession = Depends(get_db),
):
    """Get email hint for a username (shows first 2 and last 2 chars)."""
    result = await db.execute(select(Identity).where(Identity.username == username.lower().strip()))
    identity = result.scalar_one_or_none()

    if not identity or not identity.email:
        raise HTTPException(status_code=404, detail="User not found")

    email = identity.email
    if "@" in email:
        local, domain = email.split("@", 1)
        if len(local) > 4:
            hint = f"{local[:2]}***{local[-2:]}@{domain}"
        else:
            hint = f"{local[0]}***@{domain}"
    else:
        hint = f"{email[:2]}***"

    return {"hint": hint}


# ─── Email Verification ─────────────────────────────────────────────


class VerifyEmailRequest(BaseModel):
    token: str


class ResendVerificationRequest(BaseModel):
    email: str


@router.post("/verify-email")
async def verify_email(
    data: VerifyEmailRequest,
    db: AsyncSession = Depends(get_db),
):
    """Verify email address with 6-digit code."""
    from app.services.email_verification_service import email_verification_service

    token_data = await email_verification_service.consume_email_verification_token(data.token)
    if not token_data:
        raise HTTPException(status_code=400, detail="Invalid or expired verification code")

    result = await db.execute(select(Identity).where(Identity.id == token_data["identity_id"]))
    identity = result.scalar_one_or_none()
    if not identity:
        raise HTTPException(status_code=404, detail="User not found")

    # Update email if the verified email is different from current
    new_email = token_data.get("email")
    if new_email and new_email != identity.email:
        # Check if the new email is already used by another identity
        existing = await db.execute(select(Identity).where(Identity.email == new_email))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Email already registered by another user")
        identity.email = new_email

    identity.email_verified = True
    identity.is_active = True
    await db.commit()

    user_result = await db.execute(select(User).where(User.identity_id == identity.id))
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    token = create_access_token(str(user.id), user.role)

    return {
        "ok": True,
        "message": "Email verified successfully",
        "access_token": token,
        "user": UserOut.model_validate(user),
        "needs_company_setup": not user.tenant_id,
    }


@router.post("/resend-verification")
async def resend_verification(
    data: ResendVerificationRequest,
    db: AsyncSession = Depends(get_db),
):
    """Resend email verification code."""
    from app.services.email_verification_service import email_verification_service
    from app.config import get_settings

    result = await db.execute(select(Identity).where(Identity.email == data.email.lower().strip()))
    identity = result.scalar_one_or_none()

    if not identity:
        raise HTTPException(status_code=404, detail="Email not found")

    if identity.email_verified:
        return {"ok": True, "message": "Email already verified"}

    if not identity.email:
        raise HTTPException(status_code=400, detail="No email address on file")

    user_result = await db.execute(select(User).where(User.identity_id == identity.id))
    user = user_result.scalar_one_or_none()

    settings = get_settings()
    raw_code, expires_at = await email_verification_service.create_email_verification_token(identity.id, identity.email)

    await email_verification_service.send_verification_email(
        to=identity.email,
        display_name=user.display_name if user and user.display_name else identity.email,
        verification_code=raw_code,
        expiry_minutes=settings.EMAIL_VERIFICATION_TOKEN_EXPIRE_MINUTES,
    )

    return {"ok": True, "message": "Verification code sent"}


# ─── SSO/OAuth Endpoints ─────────────────────────────────────────────


@router.get("/providers")
async def list_providers(
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID | None = Query(None, description="Optional tenant ID"),
):
    """List all available identity providers."""
    from app.services.auth_registry import auth_provider_registry

    providers = await auth_provider_registry.list_providers(db, str(tenant_id) if tenant_id else None)
    return [
        {"id": str(p.id), "provider_type": p.provider_type, "name": p.name, "is_active": p.is_active} for p in providers
    ]


@router.get("/{provider}/authorize", response_model=OAuthAuthorizeResponse)
async def authorize(
    provider: str,
    redirect_uri: str = Query(..., description="OAuth callback URI"),
    state: str = Query("", description="CSRF state parameter"),
    db: AsyncSession = Depends(get_db),
):
    """Start OAuth authorization flow for a provider."""
    from app.services.auth_registry import auth_provider_registry
    from app.services.sso_service import sso_service

    # Get provider
    auth_provider = await auth_provider_registry.get_provider(db, provider)
    if not auth_provider:
        raise HTTPException(status_code=404, detail=f"Provider '{provider}' not supported")

    # Generate authorization URL
    try:
        auth_url = await auth_provider.get_authorization_url(redirect_uri, state)
    except NotImplementedError as e:
        raise HTTPException(status_code=501, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to generate authorization URL for {provider}: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate authorization URL")

    return OAuthAuthorizeResponse(authorization_url=auth_url)


@router.post("/{provider}/callback", response_model=TokenResponse)
async def oauth_callback(
    provider: str,
    data: OAuthCallbackRequest,
    db: AsyncSession = Depends(get_db),
):
    """Handle OAuth callback and login/register user."""
    from app.services.auth_registry import auth_provider_registry

    # Get provider
    auth_provider = await auth_provider_registry.get_provider(db, provider)
    if not auth_provider:
        raise HTTPException(status_code=404, detail=f"Provider '{provider}' not supported")

    try:
        # Exchange code for token
        token_data = await auth_provider.exchange_code_for_token(data.code)
        access_token = token_data.get("access_token")
        if not access_token:
            raise HTTPException(status_code=400, detail="Failed to get access token from provider")

        # Get user info
        user_info = await auth_provider.get_user_info(access_token)

        # Find or create user
        user, is_new = await auth_provider.find_or_create_user(db, user_info)

        if not user:
            raise HTTPException(status_code=500, detail="Failed to create user")

        if not user.is_active:
            raise HTTPException(status_code=403, detail="Account is disabled")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"OAuth callback failed for {provider}: {e}")
        raise HTTPException(status_code=500, detail="OAuth authentication failed")

    # Generate JWT token
    jwt_token = create_access_token(str(user.id), user.role)

    return TokenResponse(
        access_token=jwt_token,
        user=UserOut.model_validate(user),
        needs_company_setup=user.tenant_id is None,
    )


@router.post("/{provider}/bind", response_model=UserOut)
async def bind_identity(
    provider: str,
    data: IdentityBindRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Bind an external identity to the current user."""
    from app.services.auth_registry import auth_provider_registry
    from app.services.sso_service import sso_service

    # Get provider
    auth_provider = await auth_provider_registry.get_provider(db, provider)
    if not auth_provider:
        raise HTTPException(status_code=404, detail=f"Provider '{provider}' not supported")

    try:
        # Exchange code for token
        token_data = await auth_provider.exchange_code_for_token(data.code)
        access_token = token_data.get("access_token")
        if not access_token:
            raise HTTPException(status_code=400, detail="Failed to get access token from provider")

        # Get user info
        user_info = await auth_provider.get_user_info(access_token)

        # Check if identity is already linked to another user
        existing_user = await sso_service.check_duplicate_identity(db, provider, user_info.provider_user_id)
        if existing_user and existing_user.id != current_user.id:
            raise HTTPException(
                status_code=409,
                detail="This identity is already linked to another account",
            )

        # Link identity to current user
        await sso_service.link_identity(
            db,
            str(current_user.id),
            provider,
            user_info.provider_user_id,
            user_info.raw_data,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Identity bind failed for {provider}: {e}")
        raise HTTPException(status_code=500, detail="Failed to bind identity")

    return UserOut.model_validate(current_user)


@router.post("/{provider}/unbind", response_model=UserOut)
async def unbind_identity(
    provider: str,
    data: IdentityUnbindRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Unlink an external identity from the current user."""
    from app.services.sso_service import sso_service

    # Unlink identity
    success = await sso_service.unlink_identity(db, str(current_user.id), provider)
    if not success:
        raise HTTPException(status_code=404, detail=f"No linked identity found for provider '{provider}'")

    return UserOut.model_validate(current_user)


# ─── Verification Codes ────────────────────────────────


@router.post("/send-code")
async def send_verification_code(
    request: SendVerificationCodeRequest,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Send verification code via email or SMS."""
    from app.services.verification_service import verification_service, VerificationChannel

    display_name = current_user.display_name if current_user else "User"

    success, message = await verification_service.send_code(
        contact=request.contact,
        channel=request.channel,
        purpose=request.purpose,
        display_name=display_name,
    )

    if not success:
        raise HTTPException(status_code=400, detail=message)

    return {"success": True, "message": message}


@router.post("/verify-code")
async def verify_code(
    data: VerifyCodeRequest,
    db: AsyncSession = Depends(get_db),
):
    """Verify a verification code."""
    from app.services.verification_service import verification_service

    success, message = await verification_service.verify_code(
        contact=data.contact,
        channel=data.channel,
        purpose=data.purpose,
        code=data.code,
    )

    if not success:
        raise HTTPException(status_code=400, detail=message)

    return {"success": True, "message": message}


# ─── Contacts Management ────────────────────────────────


@router.get("/contacts", response_model=list[ContactOut])
async def get_contacts(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get all contact methods for current user."""
    from app.services.identity_service import identity_service

    if not current_user.identity_id:
        return []

    contacts = await identity_service.get_contacts(db, current_user.identity_id)
    return [ContactOut.model_validate(c) for c in contacts]


@router.post("/contacts", response_model=ContactOut)
async def add_contact(
    data: AddContactRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Add a contact method to current user."""
    from app.services.identity_service import identity_service
    from app.services.verification_service import verification_service

    if not current_user.identity_id:
        raise HTTPException(status_code=400, detail="User has no identity")

    # Verify the code first
    success, message = await verification_service.verify_code(
        contact=data.contact_value,
        channel=data.contact_type,
        purpose="bind",
        code=data.verification_code,
    )

    if not success:
        raise HTTPException(status_code=400, detail=message)

    try:
        contact = await identity_service.add_contact(
            db,
            identity_id=current_user.identity_id,
            contact_type=data.contact_type,
            contact_value=data.contact_value,
            purpose=data.purpose,
            verified=True,
            source="manual",
        )
        await db.commit()
        return ContactOut.model_validate(contact)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/contacts/{contact_id}/primary")
async def set_primary_contact(
    contact_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Set a contact as primary."""
    from app.services.identity_service import identity_service

    if not current_user.identity_id:
        raise HTTPException(status_code=400, detail="User has no identity")

    try:
        await identity_service.set_primary_contact(db, current_user.identity_id, contact_id)
        await db.commit()
        return {"success": True}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/contacts/{contact_id}")
async def delete_contact(
    contact_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a contact method."""
    from app.services.identity_service import identity_service

    if not current_user.identity_id:
        raise HTTPException(status_code=400, detail="User has no identity")

    try:
        await identity_service.delete_contact(db, current_user.identity_id, contact_id)
        await db.commit()
        return {"success": True}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ─── Login Configuration ────────────────────────────────


@router.get("/login-config")
async def get_login_config(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Get login page configuration for current domain."""
    from app.services.platform_service import platform_service
    from app.models.tenant import Tenant

    host = request.headers.get("host", "")
    tenant = None

    if host:
        import re

        domain_lower = host.lower().split(":")[0]

        for proto in ("https://", "http://"):
            result = await db.execute(select(Tenant).where(Tenant.sso_domain == f"{proto}{host}"))
            tenant = result.scalar_one_or_none()
            if tenant:
                break

        if not tenant:
            parts = domain_lower.split(".")
            if len(parts) >= 2:
                potential_slug = parts[0]
                if re.match(r"^([a-z0-9][a-z0-9\-]*[a-z0-9])$", potential_slug):
                    result = await db.execute(select(Tenant).where(Tenant.slug == potential_slug))
                    tenant = result.scalar_one_or_none()

    if not tenant or not tenant.is_active:
        return {
            "tenant_name": None,
            "tenant_logo": None,
            "is_public_url": True,
            "login_methods": ["mobile", "email"],
            "sso_providers": [],
        }

    result = await db.execute(
        select(IdentityProvider).where(
            IdentityProvider.tenant_id == tenant.id,
            IdentityProvider.is_active == True,
            IdentityProvider.provider_type.in_(["feishu", "wecom", "dingtalk"]),
        )
    )
    providers = result.scalars().all()

    provider_names = {
        "feishu": "飞书",
        "wecom": "企业微信",
        "dingtalk": "钉钉",
    }
    provider_icons = {
        "feishu": "https://lf3-cdn-tos.bytegoofy.com/static/object/feishu/web/static/logo/feishu-logo_144x144.png",
        "wecom": "https://rescdn.qqmail.com/node/wework/wwopen/wwopenmng/style/style/images/independent-43825c34ea.png",
        "dingtalk": "https://img.alicdn.com/imgextra/i1/O1CN01MoMNui1YrMjFLbMZp_!!6000000003114-2-tps-240-240.png",
    }

    sso_providers = []
    public_base = await platform_service.get_public_base_url(db, request)

    for p in providers:
        redirect_uri = f"{public_base}/api/auth/{p.provider_type}/callback"
        state = str(tenant.id)

        if p.provider_type == "feishu" and p.config:
            login_url = f"https://open.feishu.cn/open-apis/authen/v1/authorize?app_id={p.config.get('app_id', '')}&redirect_uri={redirect_uri}&state={state}"
        elif p.provider_type == "wecom" and p.config:
            login_url = f"https://open.work.weixin.qq.com/wwopen/sso/confirmConnect?appid={p.config.get('corp_id', '')}&agentid={p.config.get('agent_id', '')}&redirect_uri={redirect_uri}&state={state}"
        elif p.provider_type == "dingtalk" and p.config:
            login_url = f"https://login.dingtalk.com/oauth2/auth?redirect_uri={redirect_uri}&client_id={p.config.get('app_key', '')}&scope=openid&state={state}&response_type=code"
        else:
            continue

        sso_providers.append(
            {
                "type": p.provider_type,
                "name": provider_names.get(p.provider_type, p.provider_type),
                "icon": provider_icons.get(p.provider_type, ""),
                "login_url": login_url,
            }
        )

    return {
        "tenant_name": tenant.name,
        "tenant_logo": getattr(tenant, "logo_url", None),
        "is_public_url": False,
        "login_methods": ["mobile", "email"],
        "sso_providers": sso_providers,
    }


# ─── Multi-tenant Login ────────────────────────────────


@router.post("/select-tenant", response_model=TokenResponse)
async def select_tenant(
    data: SelectTenantRequest,
    db: AsyncSession = Depends(get_db),
):
    """Select tenant after multi-tenant login."""
    try:
        identity_id = decode_temp_token(data.temp_token)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid or expired token")

    # Find user for this tenant
    result = await db.execute(
        select(User).where(
            User.identity_id == identity_id,
            User.tenant_id == data.tenant_id,
        )
    )
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=403, detail="You don't belong to this tenant")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is disabled")

    token = create_access_token(str(user.id), user.role)

    return TokenResponse(
        access_token=token,
        user=UserOut.model_validate(user),
    )


# ─── SSO Bind (for new identity system) ────────────────────────────────


class SSOBindRequest(BaseModel):
    """Request for SSO bind with contact verification."""

    sso_token: str
    bind_type: str
    mobile: str | None = None
    email: str | None = None
    verification_code: str
    confirm: bool = False


@router.post("/sso-bind")
async def sso_bind(
    data: SSOBindRequest,
    db: AsyncSession = Depends(get_db),
):
    """Bind SSO identity with contact method.

    This handles:
    1. First-time SSO login - bind contact
    2. Cross-tenant binding - confirm before binding
    """
    from app.services.verification_service import verification_service
    from app.services.identity_service import identity_service, normalize_mobile
    from app.models.user import IdentityBinding
    from app.models.tenant import Tenant
    from app.models.identity import SSOScanSession

    # Decode SSO token to get session info
    try:
        sso_session_id = uuid.UUID(data.sso_token)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid SSO token")

    # Get SSO session
    result = await db.execute(select(SSOScanSession).where(SSOScanSession.id == sso_session_id))
    sso_session = result.scalar_one_or_none()
    if not sso_session or not sso_session.user_id:
        raise HTTPException(status_code=400, detail="Invalid or expired SSO session")

    # Determine contact to bind
    contact = None
    contact_type = None
    if data.bind_type == "use_suggested":
        # Use contact from SSO provider (should be pre-filled)
        if data.mobile:
            contact = normalize_mobile(data.mobile)
            contact_type = "mobile"
        elif data.email:
            contact = data.email.lower()
            contact_type = "email"
    else:
        # Use contact provided by user
        if data.mobile:
            contact = normalize_mobile(data.mobile)
            contact_type = "mobile"
        elif data.email:
            contact = data.email.lower()
            contact_type = "email"

    if not contact or not contact_type:
        raise HTTPException(status_code=400, detail="No contact provided")

    # Verify the code
    success, message = await verification_service.verify_code(
        contact=contact,
        channel=contact_type,
        purpose="bind",
        code=data.verification_code,
    )
    if not success:
        raise HTTPException(status_code=400, detail=message)

    # Get the user from SSO session
    user_result = await db.execute(select(User).where(User.id == sso_session.user_id))
    sso_user = user_result.scalar_one_or_none()
    if not sso_user:
        raise HTTPException(status_code=400, detail="User not found")

    # Check if contact already has an identity
    existing_identity = await identity_service.find_identity_by_contact(db, contact_type, contact)

    if existing_identity:
        # Check if existing identity belongs to another tenant
        existing_user_result = await db.execute(select(User).where(User.identity_id == existing_identity.id))
        existing_user = existing_user_result.scalar_one_or_none()

        if existing_user and existing_user.tenant_id != sso_user.tenant_id:
            # Cross-tenant binding - need confirmation
            if not data.confirm:
                # Get tenant names
                new_tenant_result = await db.execute(select(Tenant).where(Tenant.id == sso_user.tenant_id))
                new_tenant = new_tenant_result.scalar_one_or_none()
                existing_tenant_result = await db.execute(select(Tenant).where(Tenant.id == existing_user.tenant_id))
                existing_tenant = existing_tenant_result.scalar_one_or_none()

                return {
                    "needs_confirmation": True,
                    "existing_tenant_name": existing_tenant.name if existing_tenant else "其他企业",
                    "new_tenant_name": new_tenant.name if new_tenant else "当前企业",
                    "identity_id": str(existing_identity.id),
                }

            # Confirmed - bind SSO to existing identity
            # Create identity binding for SSO (if not already exists)
            if sso_session.provider_type:
                existing_binding_result = await db.execute(
                    select(IdentityBinding).where(
                        IdentityBinding.identity_id == existing_identity.id,
                        IdentityBinding.provider_type == sso_session.provider_type,
                        IdentityBinding.provider_user_id == str(sso_session.user_id),
                    )
                )
                existing_binding = existing_binding_result.scalar_one_or_none()
                if not existing_binding:
                    binding = IdentityBinding(
                        identity_id=existing_identity.id,
                        provider_type=sso_session.provider_type,
                        provider_user_id=str(sso_session.user_id),
                        email=contact if contact_type == "email" else None,
                        mobile=contact if contact_type == "mobile" else None,
                    )
                    db.add(binding)

            # Create org_member for the new tenant (if not already exists)
            from app.models.org import OrgMember

            existing_member_result = await db.execute(
                select(OrgMember).where(
                    OrgMember.tenant_id == sso_user.tenant_id,
                    OrgMember.user_id == existing_user.id,
                )
            )
            existing_member = existing_member_result.scalar_one_or_none()
            if not existing_member:
                member = OrgMember(
                    tenant_id=sso_user.tenant_id,
                    user_id=existing_user.id,
                    role="member",
                )
                db.add(member)
            await db.commit()

            # Return token for existing user
            token = create_access_token(str(existing_user.id), existing_user.role)
            return TokenResponse(
                access_token=token,
                user=UserOut.model_validate(existing_user),
            )

    # No existing identity or same tenant - proceed with binding
    if not sso_user.identity_id:
        # Create new identity for the user
        identity = Identity(
            email=contact if contact_type == "email" else None,
            phone=contact if contact_type == "mobile" else None,
            email_verified=contact_type == "email",
            phone_verified=contact_type == "mobile",
            is_active=True,
        )
        db.add(identity)
        await db.flush()
        sso_user.identity_id = identity.id

        # Add contact to identity
        await identity_service.add_contact(
            db,
            identity_id=identity.id,
            contact_type=contact_type,
            contact_value=contact,
            purpose="primary",
            verified=True,
            source="sso_bind",
        )
    else:
        # Update existing identity with verified contact
        identity_result = await db.execute(select(Identity).where(Identity.id == sso_user.identity_id))
        identity = identity_result.scalar_one_or_none()
        if identity:
            if contact_type == "email":
                identity.email = contact
                identity.email_verified = True
            elif contact_type == "mobile":
                identity.phone = contact
                identity.phone_verified = True

        # Add contact to existing identity
        await identity_service.add_contact(
            db,
            identity_id=sso_user.identity_id,
            contact_type=contact_type,
            contact_value=contact,
            purpose="verified",
            verified=True,
            source="sso_bind",
        )

    # Create identity binding for SSO (if not already exists)
    if sso_session.provider_type and sso_user.identity_id:
        existing_binding_result = await db.execute(
            select(IdentityBinding).where(
                IdentityBinding.identity_id == sso_user.identity_id,
                IdentityBinding.provider_type == sso_session.provider_type,
                IdentityBinding.provider_user_id == str(sso_session.user_id),
            )
        )
        existing_binding = existing_binding_result.scalar_one_or_none()
        if not existing_binding:
            binding = IdentityBinding(
                identity_id=sso_user.identity_id,
                provider_type=sso_session.provider_type,
                provider_user_id=str(sso_session.user_id),
                email=contact if contact_type == "email" else None,
                mobile=contact if contact_type == "mobile" else None,
            )
            db.add(binding)

    await db.commit()

    # Return token
    token = create_access_token(str(sso_user.id), sso_user.role)
    return TokenResponse(
        access_token=token,
        user=UserOut.model_validate(sso_user),
    )
