import { useState, useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useAuthStore } from '../stores';
import { authApi, fetchJson } from '../services/api';

export default function SSOBind() {
    const { t } = useTranslation();
    const navigate = useNavigate();
    const [searchParams] = useSearchParams();
    const setAuth = useAuthStore((s) => s.setAuth);
    
    const ssoToken = searchParams.get('token') || '';
    const suggestedMobile = searchParams.get('mobile') || '';
    const suggestedEmail = searchParams.get('email') || '';
    const provider = searchParams.get('provider') || 'feishu';
    
    const [bindType, setBindType] = useState<'use_suggested' | 'use_other'>('use_suggested');
    const [contactType, setContactType] = useState<'mobile' | 'email'>(
        suggestedMobile ? 'mobile' : suggestedEmail ? 'email' : 'mobile'
    );
    const [contact, setContact] = useState('');
    const [code, setCode] = useState('');
    const [countdown, setCountdown] = useState(0);
    const [loading, setLoading] = useState(false);
    const [sending, setSending] = useState(false);
    const [error, setError] = useState('');
    
    // Cross-tenant confirmation state
    const [needsConfirmation, setNeedsConfirmation] = useState(false);
    const [existingTenantName, setExistingTenantName] = useState('');
    const [newTenantName, setNewTenantName] = useState('');
    const [existingIdentityId, setExistingIdentityId] = useState('');
    
    useEffect(() => {
        if (suggestedMobile || suggestedEmail) {
            setBindType('use_suggested');
        } else {
            setBindType('use_other');
        }
    }, [suggestedMobile, suggestedEmail]);
    
    useEffect(() => {
        if (countdown > 0) {
            const timer = setTimeout(() => setCountdown(countdown - 1), 1000);
            return () => clearTimeout(timer);
        }
    }, [countdown]);
    
    const maskMobile = (mobile: string) => {
        if (mobile.length >= 11) {
            return `${mobile.slice(0, 3)}****${mobile.slice(-4)}`;
        }
        return mobile;
    };
    
    const maskEmail = (email: string) => {
        const [name, domain] = email.split('@');
        if (name && domain) {
            return `${name[0]}***@${domain}`;
        }
        return email;
    };
    
    const handleSendCode = async () => {
        setError('');
        
        const targetContact = bindType === 'use_suggested' 
            ? (contactType === 'mobile' ? suggestedMobile : suggestedEmail)
            : contact;
        
        if (!targetContact) {
            setError(t('ssoBind.contactRequired', '请输入联系方式'));
            return;
        }
        
        setSending(true);
        try {
            await authApi.sendVerificationCode({
                contact: targetContact,
                channel: contactType,
                purpose: 'bind',
            });
            setCountdown(60);
        } catch (err: any) {
            setError(err.message || t('ssoBind.sendFailed', '发送验证码失败'));
        } finally {
            setSending(false);
        }
    };
    
    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setError('');
        setLoading(true);
        
        const targetContact = bindType === 'use_suggested'
            ? (contactType === 'mobile' ? suggestedMobile : suggestedEmail)
            : contact;
        
        try {
            const res = await fetchJson<any>('/auth/sso-bind', {
                method: 'POST',
                body: JSON.stringify({
                    sso_token: ssoToken,
                    bind_type: bindType,
                    mobile: bindType === 'use_other' && contactType === 'mobile' ? contact : undefined,
                    email: bindType === 'use_other' && contactType === 'email' ? contact : undefined,
                    verification_code: code,
                    confirm: needsConfirmation,  // Send confirmation flag
                }),
            });
            
            // Check if cross-tenant confirmation is needed
            if (res.needs_confirmation) {
                setNeedsConfirmation(true);
                setExistingTenantName(res.existing_tenant_name || '其他企业');
                setNewTenantName(res.new_tenant_name || '当前企业');
                setExistingIdentityId(res.identity_id || '');
                setLoading(false);
                return;
            }
            
            if (res.access_token && res.user) {
                setAuth(res.user, res.access_token);
                navigate('/');
            } else {
                setError(t('ssoBind.bindFailed', '绑定失败'));
            }
        } catch (err: any) {
            setError(err.message || t('ssoBind.bindFailed', '绑定失败'));
        } finally {
            setLoading(false);
        }
    };
    
    const handleConfirmBind = async () => {
        setError('');
        setLoading(true);
        
        const targetContact = bindType === 'use_suggested'
            ? (contactType === 'mobile' ? suggestedMobile : suggestedEmail)
            : contact;
        
        try {
            const res = await fetchJson<any>('/auth/sso-bind', {
                method: 'POST',
                body: JSON.stringify({
                    sso_token: ssoToken,
                    bind_type: bindType,
                    mobile: bindType === 'use_other' && contactType === 'mobile' ? contact : undefined,
                    email: bindType === 'use_other' && contactType === 'email' ? contact : undefined,
                    verification_code: code,
                    confirm: true,
                }),
            });
            
            if (res.access_token && res.user) {
                setAuth(res.user, res.access_token);
                navigate('/');
            } else {
                setError(t('ssoBind.bindFailed', '绑定失败'));
            }
        } catch (err: any) {
            setError(err.message || t('ssoBind.bindFailed', '绑定失败'));
        } finally {
            setLoading(false);
        }
    };
    
    const providerNames: Record<string, string> = {
        feishu: '飞书',
        wecom: '企业微信',
        dingtalk: '钉钉',
    };
    
    return (
        <div className="login-page">
            <div className="login-form-panel" style={{ maxWidth: '100%' }}>
                <div className="login-form-wrapper" style={{ maxWidth: '420px' }}>
                    <div className="login-form-header">
                        <div className="login-form-logo">
                            <img src="/logo-black.png" className="login-logo-img" alt="" style={{ width: 28, height: 28, marginRight: 8, verticalAlign: 'middle' }} />
                            小圣AI
                        </div>
                        <h2 className="login-form-title">
                            {t('ssoBind.title', '首次登录绑定')}
                        </h2>
                        <p className="login-form-subtitle">
                            {t('ssoBind.subtitle', `首次使用${providerNames[provider] || provider}登录，请绑定联系方式以完成注册`)}
                        </p>
                    </div>
                    
                    {error && (
                        <div className="login-error">
                            <span>⚠</span> {error}
                        </div>
                    )}
                    
                    {/* Cross-tenant confirmation */}
                    {needsConfirmation ? (
                        <div style={{ padding: '16px 0' }}>
                            <div style={{
                                padding: '20px',
                                borderRadius: '12px',
                                background: 'rgba(245, 158, 11, 0.1)',
                                border: '1px solid rgba(245, 158, 11, 0.3)',
                                marginBottom: '20px',
                            }}>
                                <div style={{ fontSize: '15px', fontWeight: 600, marginBottom: '12px', color: 'var(--text-primary)' }}>
                                    {t('ssoBind.confirmTitle', '确认绑定企业')}
                                </div>
                                <div style={{ fontSize: '13px', color: 'var(--text-secondary)', lineHeight: '1.6' }}>
                                    {t('ssoBind.confirmDesc', `您已加入「{{existing}}」，确认绑定到「{{new}}」？绑定后可在企业间切换。`, {
                                        existing: existingTenantName,
                                        new: newTenantName,
                                    })}
                                </div>
                            </div>
                            
                            <div style={{ display: 'flex', gap: '12px' }}>
                                <button
                                    type="button"
                                    className="login-submit"
                                    style={{ flex: 1, background: 'var(--bg-secondary)', color: 'var(--text-primary)' }}
                                    onClick={() => {
                                        setNeedsConfirmation(false);
                                        navigate('/login');
                                    }}
                                >
                                    {t('common.cancel', '取消')}
                                </button>
                                <button
                                    type="button"
                                    className="login-submit"
                                    style={{ flex: 1 }}
                                    onClick={handleConfirmBind}
                                    disabled={loading}
                                >
                                    {loading ? <span className="login-spinner" /> : t('ssoBind.confirmBind', '确认绑定')}
                                </button>
                            </div>
                        </div>
                    ) : (
                    <form onSubmit={handleSubmit} className="login-form">
                        {/* 选择绑定方式 */}
                        {(suggestedMobile || suggestedEmail) ? (
                            <div className="login-field">
                                <label>{t('ssoBind.selectContact', '选择联系方式')}</label>
                                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', marginTop: '8px' }}>
                                    {suggestedMobile && (
                                        <label style={{
                                            display: 'flex',
                                            alignItems: 'center',
                                            padding: '12px',
                                            borderRadius: '8px',
                                            border: bindType === 'use_suggested' && contactType === 'mobile' 
                                                ? '1px solid var(--accent-primary)' 
                                                : '1px solid var(--border-subtle)',
                                            background: bindType === 'use_suggested' && contactType === 'mobile'
                                                ? 'rgba(59, 130, 246, 0.1)'
                                                : 'var(--bg-secondary)',
                                            cursor: 'pointer',
                                        }}>
                                            <input
                                                type="radio"
                                                name="bindType"
                                                checked={bindType === 'use_suggested' && contactType === 'mobile'}
                                                onChange={() => { setBindType('use_suggested'); setContactType('mobile'); }}
                                                style={{ marginRight: '12px' }}
                                            />
                                            <div>
                                                <div style={{ fontSize: '14px', fontWeight: 500 }}>
                                                    {t('ssoBind.useSuggestedMobile', '使用当前手机号')}
                                                </div>
                                                <div style={{ fontSize: '12px', color: 'var(--text-tertiary)' }}>
                                                    {maskMobile(suggestedMobile)} ({t('ssoBind.fromProvider', '来自{{provider}}', { provider: providerNames[provider] })})
                                                </div>
                                            </div>
                                        </label>
                                    )}
                                    {suggestedEmail && (
                                        <label style={{
                                            display: 'flex',
                                            alignItems: 'center',
                                            padding: '12px',
                                            borderRadius: '8px',
                                            border: bindType === 'use_suggested' && contactType === 'email'
                                                ? '1px solid var(--accent-primary)'
                                                : '1px solid var(--border-subtle)',
                                            background: bindType === 'use_suggested' && contactType === 'email'
                                                ? 'rgba(59, 130, 246, 0.1)'
                                                : 'var(--bg-secondary)',
                                            cursor: 'pointer',
                                        }}>
                                            <input
                                                type="radio"
                                                name="bindType"
                                                checked={bindType === 'use_suggested' && contactType === 'email'}
                                                onChange={() => { setBindType('use_suggested'); setContactType('email'); }}
                                                style={{ marginRight: '12px' }}
                                            />
                                            <div>
                                                <div style={{ fontSize: '14px', fontWeight: 500 }}>
                                                    {t('ssoBind.useSuggestedEmail', '使用当前邮箱')}
                                                </div>
                                                <div style={{ fontSize: '12px', color: 'var(--text-tertiary)' }}>
                                                    {maskEmail(suggestedEmail)} ({t('ssoBind.fromProvider', '来自{{provider}}', { provider: providerNames[provider] })})
                                                </div>
                                            </div>
                                        </label>
                                    )}
                                    <label style={{
                                        display: 'flex',
                                        alignItems: 'center',
                                        padding: '12px',
                                        borderRadius: '8px',
                                        border: bindType === 'use_other'
                                            ? '1px solid var(--accent-primary)'
                                            : '1px solid var(--border-subtle)',
                                        background: bindType === 'use_other'
                                            ? 'rgba(59, 130, 246, 0.1)'
                                            : 'var(--bg-secondary)',
                                        cursor: 'pointer',
                                    }}>
                                        <input
                                            type="radio"
                                            name="bindType"
                                            checked={bindType === 'use_other'}
                                            onChange={() => setBindType('use_other')}
                                            style={{ marginRight: '12px' }}
                                        />
                                        <div style={{ fontSize: '14px', fontWeight: 500 }}>
                                            {t('ssoBind.useOther', '使用其他联系方式')}
                                        </div>
                                    </label>
                                </div>
                            </div>
                        ) : (
                            <div style={{ marginBottom: '16px', padding: '12px', background: 'rgba(59, 130, 246, 0.1)', borderRadius: '8px', border: '1px solid rgba(59, 130, 246, 0.2)' }}>
                                <div style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>
                                    {t('ssoBind.noSuggestedContact', '请绑定您的手机号或邮箱以完成注册')}
                                </div>
                            </div>
                        )}
                        
                        {/* 使用其他联系方式 */}
                        {bindType === 'use_other' && (
                            <div className="login-field">
                                <label>{t('ssoBind.contactType', '联系方式类型')}</label>
                                <div style={{ display: 'flex', gap: '12px', marginTop: '8px' }}>
                                    <label style={{
                                        display: 'flex',
                                        alignItems: 'center',
                                        padding: '8px 16px',
                                        borderRadius: '8px',
                                        border: contactType === 'mobile'
                                            ? '1px solid var(--accent-primary)'
                                            : '1px solid var(--border-subtle)',
                                        background: contactType === 'mobile'
                                            ? 'rgba(59, 130, 246, 0.1)'
                                            : 'var(--bg-secondary)',
                                        cursor: 'pointer',
                                    }}>
                                        <input
                                            type="radio"
                                            name="contactType"
                                            checked={contactType === 'mobile'}
                                            onChange={() => setContactType('mobile')}
                                            style={{ marginRight: '8px' }}
                                        />
                                        {t('ssoBind.mobile', '手机号')}
                                    </label>
                                    <label style={{
                                        display: 'flex',
                                        alignItems: 'center',
                                        padding: '8px 16px',
                                        borderRadius: '8px',
                                        border: contactType === 'email'
                                            ? '1px solid var(--accent-primary)'
                                            : '1px solid var(--border-subtle)',
                                        background: contactType === 'email'
                                            ? 'rgba(59, 130, 246, 0.1)'
                                            : 'var(--bg-secondary)',
                                        cursor: 'pointer',
                                    }}>
                                        <input
                                            type="radio"
                                            name="contactType"
                                            checked={contactType === 'email'}
                                            onChange={() => setContactType('email')}
                                            style={{ marginRight: '8px' }}
                                        />
                                        {t('ssoBind.email', '邮箱')}
                                    </label>
                                </div>
                            </div>
                        )}
                        
                        {bindType === 'use_other' && (
                            <div className="login-field">
                                <label>
                                    {contactType === 'mobile' 
                                        ? t('ssoBind.mobileLabel', '手机号')
                                        : t('ssoBind.emailLabel', '邮箱')
                                    }
                                </label>
                                <input
                                    type={contactType === 'mobile' ? 'tel' : 'email'}
                                    value={contact}
                                    onChange={(e) => setContact(e.target.value)}
                                    required
                                    placeholder={contactType === 'mobile' 
                                        ? t('ssoBind.mobilePlaceholder', '请输入手机号')
                                        : t('ssoBind.emailPlaceholder', '请输入邮箱')
                                    }
                                />
                            </div>
                        )}
                        
                        {/* 验证码 */}
                        <div className="login-field">
                            <label>{t('ssoBind.codeLabel', '验证码')}</label>
                            <div style={{ display: 'flex', gap: '8px' }}>
                                <input
                                    type="text"
                                    value={code}
                                    onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                                    required
                                    maxLength={6}
                                    placeholder={t('ssoBind.codePlaceholder', '请输入6位验证码')}
                                    style={{ flex: 1 }}
                                />
                                <button
                                    type="button"
                                    onClick={handleSendCode}
                                    disabled={countdown > 0 || sending || (bindType === 'use_other' && !contact)}
                                    style={{
                                        padding: '0 16px',
                                        borderRadius: '8px',
                                        border: '1px solid var(--border-subtle)',
                                        background: countdown > 0 ? 'var(--bg-tertiary)' : 'var(--accent-primary)',
                                        color: countdown > 0 ? 'var(--text-tertiary)' : 'white',
                                        fontSize: '13px',
                                        fontWeight: 500,
                                        cursor: countdown > 0 ? 'not-allowed' : 'pointer',
                                        whiteSpace: 'nowrap',
                                    }}
                                >
                                    {countdown > 0 
                                        ? t('ssoBind.countdown', '{{seconds}}秒后重试', { seconds: countdown })
                                        : t('ssoBind.sendCode', '发送验证码')
                                    }
                                </button>
                            </div>
                        </div>
                        
                        <button className="login-submit" type="submit" disabled={loading || code.length !== 6}>
                            {loading ? (
                                <span className="login-spinner" />
                            ) : (
                                <>
                                    {t('ssoBind.confirm', '确认绑定')}
                                    <span style={{ marginLeft: '6px' }}>→</span>
                                </>
                            )}
                        </button>
                    </form>
                    )}
                </div>
            </div>
        </div>
    );
}