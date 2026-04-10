import { useState, useEffect, useRef } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useAuthStore } from '../stores';
import { authApi, tenantApi, fetchJson } from '../services/api';
import type { TokenResponse } from '../types';

export default function Login() {
    const { t, i18n } = useTranslation();
    const navigate = useNavigate();
    const [searchParams] = useSearchParams();
    const invitationCode = searchParams.get('code');
    const invitedEmail = searchParams.get('email') || '';
    const setAuth = useAuthStore((s) => s.setAuth);
    // Default to register if there's an invitation code — will be overridden after email check
    const [isRegister, setIsRegister] = useState(!!invitationCode);
    const [error, setError] = useState('');
    const [successMessage, setSuccessMessage] = useState('');
    const [loading, setLoading] = useState(false);
    const [checkingEmail, setCheckingEmail] = useState(!!invitationCode && !!invitedEmail);
    const [tenant, setTenant] = useState<any>(null);
    const [resolving, setResolving] = useState(true);
    const [ssoProviders, setSsoProviders] = useState<any[]>([]);
    const [ssoLoading, setSsoLoading] = useState(false);
    const [ssoError, setSsoError] = useState('');
    const [tenantSelection, setTenantSelection] = useState<any[] | null>(null);

    // Registration method: 'verification_code' or 'password'
    const [registerMethod, setRegisterMethod] = useState<'verification_code' | 'password'>('verification_code');
    // Contact type for verification code registration
    const [registerContactType, setRegisterContactType] = useState<'email' | 'mobile'>('email');
    // Verification code countdown timer
    const [codeCountdown, setCodeCountdown] = useState(0);
    const countdownTimerRef = useRef<number | null>(null);

    const [form, setForm] = useState({
        login_identifier: invitedEmail,  // Pre-fill invited email if present
        password: '',
        tenant_id: '',
        // Verification code fields
        register_contact: invitedEmail,
        verification_code: '',
        // Invitation code for registration
        invitation_code_input: invitationCode || '',
    });

    useEffect(() => {
        document.documentElement.setAttribute('data-theme', 'dark');

        // If arriving via invitation link with email, check whether the email is already registered
        // to decide whether to show login or register form.
        if (invitationCode && invitedEmail) {
            setCheckingEmail(true);
            fetch('/api/enterprise/check-email-exists', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email: invitedEmail }),
            })
                .then(r => r.json())
                .then((res: { exists: boolean }) => {
                    // If email already registered → show login form; otherwise show register form
                    setIsRegister(!res.exists);
                })
                .catch(() => {
                    // On error, fall back to register form (safe default)
                    setIsRegister(true);
                })
                .finally(() => setCheckingEmail(false));
        }

        // Resolve tenant by domain (for SSO detection only, not for login form)
        const domain = window.location.host;
        if (domain.startsWith('localhost') || domain.startsWith('127.0.0.1')) {
            setResolving(false);
            return;
        }

        tenantApi.resolveByDomain(domain)
            .then(res => {
                if (res) {
                    setTenant(res);
                }
            })
            .catch(() => { })
            .finally(() => setResolving(false));
    }, []);

    // Countdown timer cleanup
    useEffect(() => {
        return () => {
            if (countdownTimerRef.current) {
                clearInterval(countdownTimerRef.current);
            }
        };
    }, []);

    useEffect(() => {
        let cancelled = false;
        if (!tenant?.sso_enabled || isRegister) {
            setSsoProviders([]);
            setSsoError('');
            return;
        }
        if (!tenant?.id) return;

        setSsoLoading(true);
        setSsoError('');

        fetchJson<{ session_id: string }>(`/sso/session?tenant_id=${tenant.id}`, { method: 'POST' })
            .then(res => fetchJson<any[]>(`/sso/config?sid=${res.session_id}`))
            .then(providers => {
                if (cancelled) return;
                setSsoProviders(providers || []);
            })
            .catch(() => {
                if (cancelled) return;
                setSsoError(t('auth.ssoLoadFailed', 'Failed to load SSO providers.'));
                setSsoProviders([]);
            })
            .finally(() => {
                if (cancelled) return;
                setSsoLoading(false);
            });

        return () => { cancelled = true; };
    }, [tenant?.id, tenant?.sso_enabled, isRegister, t]);

    const toggleLang = () => {
        i18n.changeLanguage(i18n.language === 'zh' ? 'en' : 'zh');
    };

    const handleSendVerificationCode = async () => {
        const contact = form.register_contact.trim();
        if (!contact) {
            setError(registerContactType === 'email' 
                ? t('auth.emailRequired', '请输入邮箱地址')
                : t('auth.mobileRequired', '请输入手机号码'));
            return;
        }
        
        if (registerContactType === 'email' && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(contact)) {
            setError(t('auth.invalidEmail', '邮箱格式不正确'));
            return;
        }
        
        if (registerContactType === 'mobile' && !/^1[3-9]\d{9}$/.test(contact)) {
            setError(t('auth.invalidMobile', '手机号码格式不正确'));
            return;
        }

        setError('');
        setLoading(true);
        try {
            const res = await authApi.sendVerificationCode({
                contact: registerContactType === 'mobile' ? contact : contact.toLowerCase(),
                channel: registerContactType,
                purpose: 'register',
            });
            setSuccessMessage(res.message || t('auth.codeSent', '验证码已发送'));
            
            // Start countdown timer (60 seconds)
            setCodeCountdown(60);
            countdownTimerRef.current = window.setInterval(() => {
                setCodeCountdown(prev => {
                    if (prev <= 1) {
                        if (countdownTimerRef.current) {
                            clearInterval(countdownTimerRef.current);
                        }
                        return 0;
                    }
                    return prev - 1;
                });
            }, 1000);
        } catch (err: any) {
            setError(err.message || t('auth.codeSendFailed', '验证码发送失败'));
        } finally {
            setLoading(false);
        }
    };

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setError('');
        setSuccessMessage('');
        setLoading(true);

        try {
            if (isRegister) {
                // Handle verification code registration
                if (registerMethod === 'verification_code') {
                    const contact = form.register_contact.trim();
                    const code = form.verification_code.trim();
                    const inviteCode = form.invitation_code_input.trim();
                    
                    if (!contact) {
                        setError(registerContactType === 'email' 
                            ? t('auth.emailRequired', '请输入邮箱地址')
                            : t('auth.mobileRequired', '请输入手机号码'));
                        setLoading(false);
                        return;
                    }
                    
                    if (!code) {
                        setError(t('auth.codeRequired', '请输入验证码'));
                        setLoading(false);
                        return;
                    }

                    if (!inviteCode) {
                        setError(t('auth.invitationCodeRequired', '请输入企业邀请码'));
                        setLoading(false);
                        return;
                    }

                    // First verify the code
                    await authApi.verifyCode({
                        contact: registerContactType === 'mobile' ? contact : contact.toLowerCase(),
                        channel: registerContactType,
                        purpose: 'register',
                        code: code,
                    });

                    // Then register with the verified contact
                    const regRes = await authApi.register({
                        username: registerContactType === 'email' 
                            ? contact.split('@')[0] 
                            : `user_${contact.slice(-4)}`,
                        email: registerContactType === 'email' ? contact.toLowerCase() : '',
                        password: '',  // Will be set later in profile setup
                        display_name: registerContactType === 'email' 
                            ? contact.split('@')[0] 
                            : contact.slice(-4),
                        ...(registerContactType === 'mobile' ? { mobile: contact } : {}),
                        invitation_code: inviteCode,
                        verification_code: code,
                        contact_type: registerContactType,
                    });
                    
                    if (regRes.access_token && regRes.user) {
                        setAuth(regRes.user, regRes.access_token);
                    }
                    // After joining via invitation code, go to home (no company setup needed)
                    navigate('/');
                    return;
                }
                
                // Handle password registration (legacy flow - still requires invitation code)
                const inviteCode = form.invitation_code_input.trim();
                if (!inviteCode) {
                    setError(t('auth.invitationCodeRequired', '请输入企业邀请码'));
                    setLoading(false);
                    return;
                }
                
                const regRes = await authApi.register({
                    username: form.login_identifier.split('@')[0],
                    email: form.login_identifier,
                    password: form.password,
                    display_name: form.login_identifier.split('@')[0],
                    invitation_code: inviteCode,
                });
                // Save authentication state for company selection (user not active yet)
                if (regRes.access_token && regRes.user) {
                    setAuth(regRes.user, regRes.access_token);
                }
                // After joining via invitation code, go to home (no company setup needed)
                navigate('/');
                return;
            } else {
                const res = await authApi.login({
                    login_identifier: form.login_identifier,
                    password: form.password,
                    // Only pass tenant_id for dedicated SSO subdomain login (not IP-mode SSO).
                    // IP-mode SSO resolves a tenant for SSO buttons only and must NOT constrain
                    // password-based login to that tenant (it would reject users from other tenants).
                    ...(tenant?.id && tenant.sso_domain && !tenant.sso_domain.match(/^https?:\/\/\d{1,3}(\.\d{1,3}){3}(:\d+)?$/)
                        ? { tenant_id: tenant.id }
                        : {}
                    ),
                });

                // Check if multi-tenant selection is needed
                if ('requires_tenant_selection' in res && res.requires_tenant_selection) {
                    setTenantSelection(res.tenants);
                    setLoading(false);
                    return;
                }

                const tokenRes = res as TokenResponse;
                setAuth(tokenRes.user, tokenRes.access_token);

                // If the user arrived via an invitation link, join the invited company
                // before redirecting. The /tenants/join endpoint handles:
                // - Existing user with no tenant → assigns the tenant directly
                // - Existing user with a tenant → creates a new User record for the new tenant
                //   and returns a new access_token scoped to that tenant.
                if (invitationCode) {
                    try {
                        const joinRes = await tenantApi.join(invitationCode);
                        if (joinRes?.access_token) {
                            // Store the new tenant-scoped token first so that
                            // the subsequent /auth/me call uses the correct context.
                            localStorage.setItem('token', joinRes.access_token);
                            const meRes = await authApi.me();
                            setAuth(meRes, joinRes.access_token);
                        }
                        navigate('/');
                        return;
                    } catch (joinErr: any) {
                        // If joining fails (code already used, code invalid, already a member),
                        // just continue into the user's existing company — don't block login.
                        console.warn('[invitation] join failed, entering original company:', joinErr.message);
                    }
                }

                if (tokenRes.user && !tokenRes.user.tenant_id) {
                    navigate('/setup-company');
                } else {
                    navigate('/');
                }
            }
        } catch (err: any) {
            // Handle structured verification error
            if (err.detail?.needs_verification) {
                navigate('/verify-email', { 
                    state: { 
                        fromRegister: false, 
                        email: err.detail.email || form.login_identifier 
                    } 
                });
                return;
            }

            const msg = err.message || '';
            if (msg && msg !== 'Failed to fetch' && !msg.includes('NetworkError') && !msg.includes('ERR_CONNECTION')) {
                if (msg.includes('company has been disabled')) {
                    setError(t('auth.companyDisabled'));
                } else if (msg.includes('Invalid credentials')) {
                    setError(t('auth.invalidCredentials'));
                } else if (msg.includes('Account is disabled')) {
                    setError(t('auth.accountDisabled'));
                } else if (msg.includes('does not belong to this organization')) {
                    setError(t('auth.notInOrganization', 'This account does not belong to this organization.'));
                } else if (msg.includes('500') || msg.includes('Internal Server Error')) {
                    setError(t('auth.serverStarting'));
                } else if (msg.includes('Email already registered') || msg.includes('该邮箱已注册')) {
                    setError(t('auth.emailAlreadyRegistered', '该邮箱已注册，请直接登录'));
                } else {
                    setError(msg);
                }
            } else {
                setError(t('auth.serverUnreachable'));
            }
        } finally {
            setLoading(false);
        }
    };

    const handleTenantSelect = async (tenantId: string) => {
        setForm(f => ({ ...f, tenant_id: tenantId }));
        setTenantSelection(null);
        setError('');
        setLoading(true);

        try {
            const res = await authApi.login({
                login_identifier: form.login_identifier,
                password: form.password,
                tenant_id: tenantId,
            });

            // Should not get multi-tenant response when tenant_id is provided
            if ('requires_tenant_selection' in res && res.requires_tenant_selection) {
                setTenantSelection(res.tenants);
                setLoading(false);
                return;
            }

            const tokenRes = res as TokenResponse;
            setAuth(tokenRes.user, tokenRes.access_token);
            if (tokenRes.user && !tokenRes.user.tenant_id) {
                navigate('/setup-company');
            } else {
                navigate('/');
            }
        } catch (err: any) {
            const msg = err.message || '';
            setError(msg || t('auth.loginFailed', 'Login failed'));
        } finally {
            setLoading(false);
        }
    };

    const ssoMeta: Record<string, { label: string; icon: string }> = {
        feishu: { label: 'Feishu', icon: '/feishu.png' },
        dingtalk: { label: 'DingTalk', icon: '/dingtalk.png' },
        wecom: { label: 'WeCom', icon: '/wecom.png' },
    };

    return (
        <div className="login-page">
            {/* ── Left: Branding Panel ── */}
            <div className="login-hero">
                <div className="login-hero-bg" />
                <div className="login-hero-content">
                    <div className="login-hero-badge">
                        <span className="login-hero-badge-dot" />
                        {t('login.hero.badge')}
                    </div>
                    <h1 className="login-hero-title">
                        {t('login.hero.title')}<br />
                        <span style={{ fontSize: '0.65em', fontWeight: 600, opacity: 0.85 }}>{t('login.hero.subtitle')}</span>
                    </h1>
                    <p className="login-hero-desc" dangerouslySetInnerHTML={{ __html: t('login.hero.description') }} />
                    <div className="login-hero-features">
                        <div className="login-hero-feature">
                            <span className="login-hero-feature-icon">🤖</span>
                            <div>
                                <div className="login-hero-feature-title">{t('login.hero.features.multiAgent.title')}</div>
                                <div className="login-hero-feature-desc">{t('login.hero.features.multiAgent.description')}</div>
                            </div>
                        </div>
                        <div className="login-hero-feature">
                            <span className="login-hero-feature-icon">🧠</span>
                            <div>
                                <div className="login-hero-feature-title">{t('login.hero.features.persistentMemory.title')}</div>
                                <div className="login-hero-feature-desc">{t('login.hero.features.persistentMemory.description')}</div>
                            </div>
                        </div>
                        <div className="login-hero-feature">
                            <span className="login-hero-feature-icon">🏛️</span>
                            <div>
                                <div className="login-hero-feature-title">{t('login.hero.features.agentPlaza.title')}</div>
                                <div className="login-hero-feature-desc">{t('login.hero.features.agentPlaza.description')}</div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            {/* ── Right: Form Panel ── */}
            <div className="login-form-panel">
                {/* Language Switcher */}
                <div style={{
                    position: 'absolute', top: '16px', right: '16px',
                    cursor: 'pointer', fontSize: '13px', color: 'var(--text-secondary)',
                    display: 'flex', alignItems: 'center', gap: '4px',
                    padding: '6px 12px', borderRadius: '8px',
                    background: 'var(--bg-secondary)', border: '1px solid var(--border-subtle)',
                    zIndex: 101,
                }} onClick={toggleLang}>
                    🌐
                </div>

                <div className="login-form-wrapper">
                    {checkingEmail ? (
                        // While resolving invitation email, show a minimal loading indicator
                        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', minHeight: '200px', gap: '16px' }}>
                            <span className="login-spinner" style={{ width: 24, height: 24 }} />
                            <span style={{ fontSize: '13px', color: 'var(--text-tertiary)' }}>
                                {t('auth.checkingInvitation', 'Checking invitation...')}
                            </span>
                        </div>
                    ) : (
                    <>
                    <div className="login-form-header">
                        <div className="login-form-logo"><img src="/logo-black.png" className="login-logo-img" alt="" style={{ width: 28, height: 28, marginRight: 8, verticalAlign: 'middle' }} />小圣AI</div>
                        <h2 className="login-form-title">
                            {isRegister ? t('auth.register') : t('auth.login')}
                        </h2>
                        <p className="login-form-subtitle">
                            {isRegister ? t('auth.subtitleRegister') : t('auth.subtitleLogin')}
                        </p>
                    </div>

                    {error && (
                        <div className="login-error">
                            <span>⚠</span> {error}
                        </div>
                    )}

                    {successMessage && (
                        <div className="login-success" style={{
                            background: 'rgba(34, 197, 94, 0.1)',
                            color: '#16a34a',
                            padding: '12px 16px',
                            borderRadius: '8px',
                            marginBottom: '16px',
                            fontSize: '14px',
                            display: 'flex',
                            alignItems: 'center',
                            gap: '8px',
                            border: '1px solid rgba(34, 197, 94, 0.2)',
                        }}>
                            <span>✓</span> {successMessage}
                        </div>
                    )}

                    {tenant && tenant.sso_enabled && !isRegister && (
                        <div style={{ marginBottom: '24px' }}>
                            <div style={{
                                padding: '16px', borderRadius: '12px', background: 'rgba(59,130,246,0.08)',
                                border: '1px solid rgba(59,130,246,0.15)', marginBottom: '16px',
                                textAlign: 'center'
                            }}>
                                <div style={{ fontSize: '13px', fontWeight: 600, color: 'var(--accent-primary)', marginBottom: '4px' }}>
                                    {tenant.name}
                                </div>
                                <div style={{ fontSize: '11px', color: 'var(--text-tertiary)' }}>
                                    {t('auth.ssoNotice', 'Enterprise SSO is enabled for this domain.')}
                                </div>
                            </div>

                            {ssoLoading && (
                                <div style={{ textAlign: 'center', color: 'var(--text-tertiary)', fontSize: '12px' }}>
                                    {t('auth.ssoLoading', 'Loading SSO providers...')}
                                </div>
                            )}

                            {!ssoLoading && ssoProviders.length > 0 && (
                                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: '12px' }}>
                                    {ssoProviders.map(p => {
                                        const meta = ssoMeta[p.provider_type] || { label: p.name || p.provider_type, icon: '' };
                                        return (
                                            <button
                                                key={p.provider_type}
                                                className="login-submit"
                                                style={{
                                                    background: 'var(--bg-secondary)',
                                                    color: 'var(--text-primary)',
                                                    display: 'flex',
                                                    alignItems: 'center',
                                                    justifyContent: 'center',
                                                    gap: '10px',
                                                    border: '1px solid var(--border-subtle)',
                                                }}
                                                onClick={() => window.location.href = p.url}
                                            >
                                                {meta.icon ? (
                                                    <img src={meta.icon} alt={meta.label} width={18} height={18} style={{ borderRadius: '4px' }} />
                                                ) : (
                                                    <span style={{ width: 18, height: 18, borderRadius: 4, background: 'var(--bg-tertiary)', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', fontSize: 10 }}>
                                                        {(meta.label || '').slice(0, 1).toUpperCase()}
                                                    </span>
                                                )}
                                                {meta.label || p.name || p.provider_type}
                                            </button>
                                        );
                                    })}
                                </div>
                            )}

                            {!ssoLoading && ssoProviders.length === 0 && (
                                <div style={{ textAlign: 'center', color: 'var(--text-tertiary)', fontSize: '12px' }}>
                                    {ssoError || t('auth.ssoNoProviders', 'No SSO providers configured.')}
                                </div>
                            )}

                            <div style={{
                                display: 'flex', alignItems: 'center', gap: '12px',
                                margin: '20px 0', color: 'var(--text-tertiary)', fontSize: '11px'
                            }}>
                                <div style={{ flex: 1, height: '1px', background: 'var(--border-subtle)' }} />
                                {t('auth.or', 'or')}
                                <div style={{ flex: 1, height: '1px', background: 'var(--border-subtle)' }} />
                            </div>
                        </div>
                    )}

                    <form onSubmit={handleSubmit} className="login-form">
                        {isRegister && registerMethod === 'verification_code' && (
                            <>
                                {/* Contact type toggle */}
                                <div style={{ marginBottom: '12px', display: 'flex', gap: '8px' }}>
                                    <button
                                        type="button"
                                        className={`btn ${registerContactType === 'email' ? 'btn-primary' : 'btn-secondary'}`}
                                        style={{ fontSize: '13px', padding: '8px 16px', flex: 1 }}
                                        onClick={() => {
                                            setRegisterContactType('email');
                                            setForm(f => ({ ...f, register_contact: '' }));
                                        }}
                                    >
                                        {t('auth.useEmail', '邮箱注册')}
                                    </button>
                                    <button
                                        type="button"
                                        className={`btn ${registerContactType === 'mobile' ? 'btn-primary' : 'btn-secondary'}`}
                                        style={{ fontSize: '13px', padding: '8px 16px', flex: 1 }}
                                        onClick={() => {
                                            setRegisterContactType('mobile');
                                            setForm(f => ({ ...f, register_contact: '' }));
                                        }}
                                    >
                                        {t('auth.useMobile', '手机注册')}
                                    </button>
                                </div>

                                {/* Contact input */}
                                <div className="login-field">
                                    <label>{registerContactType === 'email' ? t('auth.email') : t('auth.mobile', '手机号码')}</label>
                                    <input
                                        type={registerContactType === 'email' ? 'email' : 'tel'}
                                        value={form.register_contact}
                                        onChange={(e) => setForm({ ...form, register_contact: e.target.value })}
                                        required
                                        autoFocus
                                        placeholder={registerContactType === 'email' 
                                            ? t('auth.emailPlaceholder', '请输入邮箱地址')
                                            : t('auth.mobilePlaceholder', '请输入手机号码')
                                        }
                                    />
                                </div>

                                {/* Verification code */}
                                <div className="login-field">
                                    <label>{t('auth.verificationCode', '验证码')}</label>
                                    <div style={{ display: 'flex', gap: '8px' }}>
                                        <input
                                            type="text"
                                            value={form.verification_code}
                                            onChange={(e) => setForm({ ...form, verification_code: e.target.value })}
                                            required
                                            placeholder={t('auth.codePlaceholder', '请输入验证码')}
                                            style={{ flex: 1 }}
                                            maxLength={6}
                                        />
                                        <button
                                            type="button"
                                            className="btn btn-secondary"
                                            style={{ fontSize: '13px', padding: '0 12px', minWidth: '100px' }}
                                            onClick={handleSendVerificationCode}
                                            disabled={codeCountdown > 0 || loading}
                                        >
                                            {codeCountdown > 0 
                                                ? `${codeCountdown}s` 
                                                : t('auth.sendCode', '发送验证码')
                                            }
                                        </button>
                                    </div>
                                </div>

                                {/* Invitation code - required for new identity system */}
                                <div className="login-field">
                                    <label>{t('auth.invitationCode', '邀请码')} <span style={{ color: 'var(--error)' }}>*</span></label>
                                    <input
                                        type="text"
                                        value={form.invitation_code_input}
                                        onChange={(e) => setForm({ ...form, invitation_code_input: e.target.value.toUpperCase() })}
                                        required
                                        placeholder={t('auth.invitationCodePlaceholder', '请输入企业邀请码')}
                                        style={{ textTransform: 'uppercase', letterSpacing: '2px', fontFamily: 'monospace' }}
                                    />
                                    {!tenant && (
                                        <div style={{ fontSize: '11px', color: 'var(--text-tertiary)', marginTop: '4px' }}>
                                            {t('auth.invitationCodeHint', '注册需要企业邀请码，请联系企业管理员获取')}
                                        </div>
                                    )}
                                </div>
                            </>
                        )}

                        {isRegister && registerMethod === 'password' && (
                            <>
                                <div className="login-field">
                                    <label>{t('auth.email')}</label>
                                    <input
                                        type="email"
                                        value={form.login_identifier}
                                        onChange={(e) => setForm({ ...form, login_identifier: e.target.value })}
                                        required
                                        autoFocus
                                        placeholder={t('auth.emailPlaceholder')}
                                    />
                                </div>

                                <div className="login-field">
                                    <label>{t('auth.password')}</label>
                                    <input
                                        type="password"
                                        value={form.password}
                                        onChange={(e) => setForm({ ...form, password: e.target.value })}
                                        required
                                        placeholder={t('auth.passwordPlaceholder')}
                                    />
                                </div>

                                {/* Invitation code for password registration */}
                                <div className="login-field">
                                    <label>{t('auth.invitationCode', '邀请码')} <span style={{ color: 'var(--error)' }}>*</span></label>
                                    <input
                                        type="text"
                                        value={form.invitation_code_input}
                                        onChange={(e) => setForm({ ...form, invitation_code_input: e.target.value.toUpperCase() })}
                                        required
                                        placeholder={t('auth.invitationCodePlaceholder', '请输入企业邀请码')}
                                        style={{ textTransform: 'uppercase', letterSpacing: '2px', fontFamily: 'monospace' }}
                                    />
                                </div>
                            </>
                        )}

                        {!isRegister && (
                            <>
                                <div className="login-field">
                                    <label>{t('auth.email')}</label>
                                    <input
                                        type="email"
                                        value={form.login_identifier}
                                        onChange={(e) => setForm({ ...form, login_identifier: e.target.value })}
                                        required
                                        autoFocus
                                        placeholder={t('auth.emailPlaceholder')}
                                    />
                                </div>

                                <div className="login-field">
                                    <label>{t('auth.password')}</label>
                                    <input
                                        type="password"
                                        value={form.password}
                                        onChange={(e) => setForm({ ...form, password: e.target.value })}
                                        required
                                        placeholder={t('auth.passwordPlaceholder')}
                                    />
                                </div>

                                <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '-4px', marginBottom: '8px' }}>
                                    <Link
                                        to="/forgot-password"
                                        style={{ fontSize: '13px', color: 'var(--accent-primary)', textDecoration: 'none' }}
                                    >
                                        {t('auth.forgotPassword', 'Forgot password?')}
                                    </Link>
                                </div>
                            </>
                        )}

                        {/* Registration method toggle */}
                        {isRegister && (
                            <div style={{ marginTop: '8px', textAlign: 'center' }}>
                                <button
                                    type="button"
                                    style={{ 
                                        fontSize: '12px', 
                                        color: 'var(--text-tertiary)', 
                                        background: 'transparent', 
                                        border: 'none', 
                                        cursor: 'pointer',
                                        textDecoration: 'underline',
                                    }}
                                    onClick={() => {
                                        setRegisterMethod(registerMethod === 'verification_code' ? 'password' : 'verification_code');
                                        setError('');
                                        setSuccessMessage('');
                                    }}
                                >
                                    {registerMethod === 'verification_code' 
                                        ? t('auth.usePasswordRegister', '使用密码注册')
                                        : t('auth.useCodeRegister', '使用验证码注册')
                                    }
                                </button>
                            </div>
                        )}

                        <button className="login-submit" type="submit" disabled={loading}>
                            {loading ? (
                                <span className="login-spinner" />
                            ) : (
                                <>
                                    {isRegister ? t('auth.register') : t('auth.login')}
                                    <span style={{ marginLeft: '6px' }}>→</span>
                                </>
                            )}
                        </button>
                    </form>

                    {/* Multi-tenant selection modal */}
                    {tenantSelection && (
                        <div style={{
                            position: 'fixed',
                            top: 0, left: 0, right: 0, bottom: 0,
                            background: 'rgba(5, 5, 8, 0.82)',
                            backdropFilter: 'blur(8px)',
                            WebkitBackdropFilter: 'blur(8px)',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            zIndex: 2000,
                        }}>
                            {/* Dark glass card — stands out via border + shadow, not color inversion */}
                            <div style={{
                                background: '#161620',
                                borderRadius: '16px',
                                padding: '32px',
                                maxWidth: '400px',
                                width: '90%',
                                border: '1px solid rgba(255, 255, 255, 0.12)',
                                boxShadow: '0 0 0 1px rgba(255,255,255,0.04), 0 32px 80px rgba(0,0,0,0.7)',
                            }}>
                                <h3 style={{ fontSize: '18px', fontWeight: 700, marginBottom: '8px', color: 'rgba(255,255,255,0.95)' }}>
                                    {t('auth.selectOrganization', '选择公司')}
                                </h3>
                                <p style={{ fontSize: '13px', color: 'rgba(255,255,255,0.42)', marginBottom: '20px', lineHeight: '1.5' }}>
                                    {t('auth.multiTenantPrompt', '该邮箱对应多个公司，请选择要登录的公司：')}
                                </p>
                                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                                    {tenantSelection.map((tenant: any) => (
                                        <button
                                            key={tenant.tenant_id}
                                            onClick={() => handleTenantSelect(tenant.tenant_id)}
                                            style={{
                                                padding: '12px 16px',
                                                borderRadius: '10px',
                                                border: '1px solid rgba(255,255,255,0.09)',
                                                background: 'rgba(255,255,255,0.05)',
                                                color: 'rgba(255,255,255,0.88)',
                                                fontSize: '14px',
                                                fontWeight: 500,
                                                cursor: 'pointer',
                                                textAlign: 'left',
                                                transition: 'background 0.15s, border-color 0.15s',
                                            }}
                                            onMouseEnter={e => {
                                                (e.currentTarget as HTMLButtonElement).style.background = 'rgba(255,255,255,0.10)';
                                                (e.currentTarget as HTMLButtonElement).style.borderColor = 'rgba(255,255,255,0.20)';
                                            }}
                                            onMouseLeave={e => {
                                                (e.currentTarget as HTMLButtonElement).style.background = 'rgba(255,255,255,0.05)';
                                                (e.currentTarget as HTMLButtonElement).style.borderColor = 'rgba(255,255,255,0.09)';
                                            }}
                                        >
                                            {tenant.tenant_name} {tenant.tenant_slug && `(${tenant.tenant_slug})`}
                                        </button>
                                    ))}
                                    {/* Create or Join Organization */}
                                    <button
                                        onClick={async () => {
                                            // Log in with the first tenant to get a valid token, then redirect to company setup
                                            try {
                                                setLoading(true);
                                                const firstTenant = tenantSelection[0];
                                                const res = await authApi.login({
                                                    login_identifier: form.login_identifier,
                                                    password: form.password,
                                                    tenant_id: firstTenant.tenant_id,
                                                });
                                                const tokenRes = res as TokenResponse;
                                                setAuth(tokenRes.user, tokenRes.access_token);
                                                setTenantSelection(null);
                                                navigate('/setup-company?from=tenant-selection');
                                            } catch (err: any) {
                                                setError(err.message || 'Failed');
                                                setTenantSelection(null);
                                            } finally {
                                                setLoading(false);
                                            }
                                        }}
                                        style={{
                                            padding: '12px 16px',
                                            borderRadius: '10px',
                                            border: '1px dashed rgba(255,255,255,0.15)',
                                            background: 'transparent',
                                            color: 'rgba(255,255,255,0.38)',
                                            fontSize: '14px',
                                            cursor: 'pointer',
                                            textAlign: 'left',
                                            transition: 'border-color 0.15s, color 0.15s',
                                        }}
                                        onMouseEnter={e => {
                                            (e.currentTarget as HTMLButtonElement).style.borderColor = 'rgba(255,255,255,0.28)';
                                            (e.currentTarget as HTMLButtonElement).style.color = 'rgba(255,255,255,0.6)';
                                        }}
                                        onMouseLeave={e => {
                                            (e.currentTarget as HTMLButtonElement).style.borderColor = 'rgba(255,255,255,0.15)';
                                            (e.currentTarget as HTMLButtonElement).style.color = 'rgba(255,255,255,0.38)';
                                        }}
                                    >
                                        {t('auth.createOrJoinOrganization', 'Create or Join Organization')}
                                    </button>
                                </div>
                                <button
                                    onClick={() => setTenantSelection(null)}
                                    style={{
                                        marginTop: '16px',
                                        padding: '10px 16px',
                                        borderRadius: '10px',
                                        border: '1px solid rgba(255,255,255,0.07)',
                                        background: 'rgba(255,255,255,0.04)',
                                        color: 'rgba(255,255,255,0.5)',
                                        fontSize: '14px',
                                        fontWeight: 500,
                                        cursor: 'pointer',
                                        width: '100%',
                                        transition: 'background 0.15s, color 0.15s',
                                    }}
                                    onMouseEnter={e => {
                                        (e.currentTarget as HTMLButtonElement).style.background = 'rgba(255,255,255,0.08)';
                                        (e.currentTarget as HTMLButtonElement).style.color = 'rgba(255,255,255,0.7)';
                                    }}
                                    onMouseLeave={e => {
                                        (e.currentTarget as HTMLButtonElement).style.background = 'rgba(255,255,255,0.04)';
                                        (e.currentTarget as HTMLButtonElement).style.color = 'rgba(255,255,255,0.5)';
                                    }}
                                >
                                    {t('common.cancel', 'Cancel')}
                                </button>
                            </div>
                        </div>
                    )}

                    <div className="login-switch">
                        {isRegister ? t('auth.hasAccount') : t('auth.noAccount')}{' '}
                        <a href="#" onClick={(e) => { e.preventDefault(); setIsRegister(!isRegister); setError(''); }}>
                            {isRegister ? t('auth.goLogin') : t('auth.goRegister')}
                        </a>
                    </div>
                    </>
                    )}
                </div>
            </div>
        </div>
    );
}
