/**
 * User Management — admin page to view and manage user quotas and roles.
 */
import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useAuthStore } from '../stores';
import LinearCopyButton from '../components/LinearCopyButton';

interface ChannelIdentity {
    provider_type: string;
    external_id: string | null;
    open_id: string | null;
    unionid: string | null;
    name: string | null;
}

interface UserInfo {
    id: string;
    username: string;
    email: string;
    display_name: string;
    role: string;
    is_active: boolean;
    quota_message_limit: number;
    quota_message_period: string;
    quota_messages_used: number;
    quota_max_agents: number;
    quota_agent_ttl_hours: number;
    agents_count: number;
    feishu_open_id?: string;
    created_at?: string;
    source?: string;
    channel_identities?: ChannelIdentity[];
}

const API_PREFIX = '/api';

async function fetchJson<T>(url: string, options?: RequestInit): Promise<T> {
    const token = localStorage.getItem('token');
    const res = await fetch(`${API_PREFIX}${url}`, {
        headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        ...options,
    });
    if (!res.ok) throw new Error(await res.text());
    return res.json();
}

const PERIOD_OPTIONS = [
    { value: 'permanent', label: 'Permanent' },
    { value: 'daily', label: 'Daily' },
    { value: 'weekly', label: 'Weekly' },
    { value: 'monthly', label: 'Monthly' },
];

const PAGE_SIZE = 15;

export default function UserManagement() {
    const { t, i18n } = useTranslation();
    const isChinese = i18n.language?.startsWith('zh');
    const { user: currentUser, setUser } = useAuthStore();

    const [users, setUsers] = useState<UserInfo[]>([]);
    const [loading, setLoading] = useState(true);
    const [editingUserId, setEditingUserId] = useState<string | null>(null);
    const [editForm, setEditForm] = useState({
        quota_message_limit: 50,
        quota_message_period: 'permanent',
        quota_max_agents: 2,
        quota_agent_ttl_hours: 48,
    });
    const [saving, setSaving] = useState(false);
    const [toast, setToast] = useState('');
    const [changingRoleUserId, setChangingRoleUserId] = useState<string | null>(null);

    // Invite modal state
    const [showInviteModal, setShowInviteModal] = useState(false);
    const [inviteEmails, setInviteEmails] = useState('');
    const [inviting, setInviting] = useState(false);
    const [inviteResult, setInviteResult] = useState<{ invited: number; message: string } | null>(null);


    // Search, sort & pagination
    const [searchQuery, setSearchQuery] = useState('');
    const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc');
    const [page, setPage] = useState(1);
    const [showUnboundOnly, setShowUnboundOnly] = useState(false);
    const [showMergeModal, setShowMergeModal] = useState(false);
    const [mergeSourceUser, setMergeSourceUser] = useState<UserInfo | null>(null);
    const [mergeTargetId, setMergeTargetId] = useState<string>('');
    const [merging, setMerging] = useState(false);

    const loadUsers = async () => {
        setLoading(true);
        try {
            const tenantId = localStorage.getItem('current_tenant_id') || '';
            const data = await fetchJson<UserInfo[]>(`/users/${tenantId ? `?tenant_id=${tenantId}` : ''}`);
            setUsers(data);
        } catch (e) {
            console.error('Failed to load users', e);
        }
        setLoading(false);
    };

    useEffect(() => { loadUsers(); }, []);

    const startEdit = (user: UserInfo) => {
        setEditingUserId(user.id);
        setEditForm({
            quota_message_limit: user.quota_message_limit,
            quota_message_period: user.quota_message_period,
            quota_max_agents: user.quota_max_agents,
            quota_agent_ttl_hours: user.quota_agent_ttl_hours,
        });
    };

    const handleSave = async () => {
        if (!editingUserId) return;
        setSaving(true);
        try {
            await fetchJson(`/users/${editingUserId}/quota`, {
                method: 'PATCH',
                body: JSON.stringify(editForm),
            });
            setToast(isChinese ? '✅ 配额已更新' : '✅ Quota updated');
            setTimeout(() => setToast(''), 2000);
            setEditingUserId(null);
            loadUsers();
        } catch (e: any) {
            setToast(`❌ ${e.message}`);
            setTimeout(() => setToast(''), 3000);
        }
        setSaving(false);
    };

    // ── Role change handler ──
    const handleRoleChange = async (userId: string, newRole: string) => {
        setChangingRoleUserId(userId);
        try {
            await fetchJson(`/users/${userId}/role`, {
                method: 'PATCH',
                body: JSON.stringify({ role: newRole }),
            });
            setToast(isChinese ? 'Role updated' : 'Role updated');
            setTimeout(() => setToast(''), 2000);
            // If changed own role, update auth store
            if (userId === currentUser?.id) {
                setUser({ ...currentUser, role: newRole as any });
            }
            loadUsers();
        } catch (e: any) {
            const detail = (() => { try { return JSON.parse(e.message)?.detail; } catch { return e.message; } })();
            setToast(`Error: ${detail || e.message}`);
            setTimeout(() => setToast(''), 4000);
        }
        setChangingRoleUserId(null);
    };

    // ── Handlers ──

    const handleSendInvites = async () => {
        const emails = inviteEmails.split(/[\n,]+/).map(e => e.trim()).filter(Boolean);
        if (emails.length === 0) return;
        setInviting(true);
        setInviteResult(null);
        try {
            const res = await fetchJson<any>('/enterprise/invite-users', {
                method: 'POST',
                body: JSON.stringify({ emails }),
            });
            setInviteResult({ invited: res.invited, message: res.message });
            setInviteEmails('');
            // Refresh user list after invite
            loadUsers();
        } catch (e: any) {
            setToast(`Error: ${e.message}`);
            setTimeout(() => setToast(''), 3000);
        }
        setInviting(false);
    };

    const handleMergeUser = async () => {
        if (!mergeSourceUser || !mergeTargetId) return;
        if (mergeSourceUser.id === mergeTargetId) {
            setToast(isChinese ? '不能合并到同一个用户' : 'Cannot merge to the same user');
            setTimeout(() => setToast(''), 3000);
            return;
        }
        setMerging(true);
        try {
            const res = await fetchJson<{ message: string }>(`/users/${mergeSourceUser.id}/merge-to/${mergeTargetId}`, { method: 'POST' });
            setToast(`✅ ${res.message}`);
            setTimeout(() => setToast(''), 3000);
            setShowMergeModal(false);
            setMergeSourceUser(null);
            setMergeTargetId('');
            loadUsers();
        } catch (e: any) {
            const detail = (() => { try { return JSON.parse(e.message)?.detail; } catch { return e.message; } })();
            setToast(`❌ ${detail || e.message}`);
            setTimeout(() => setToast(''), 4000);
        }
        setMerging(false);
    };

    const openMergeModal = (user: UserInfo) => {
        setMergeSourceUser(user);
        setMergeTargetId('');
        setShowMergeModal(true);
    };

    const periodLabel = (period: string) => {
        if (isChinese) {
            const map: Record<string, string> = { permanent: '永久', daily: '每天', weekly: '每周', monthly: '每月' };
            return map[period] || period;
        }
        return PERIOD_OPTIONS.find(p => p.value === period)?.label || period;
    };

    // Role label & styling helpers
    const roleBadge = (role: string) => {
        const styles: Record<string, { bg: string; color: string; label: string; labelZh: string }> = {
            platform_admin: { bg: 'rgba(239,68,68,0.12)', color: '#ef4444', label: 'Platform Admin', labelZh: 'Platform Admin' },
            org_admin:      { bg: 'rgba(168,85,247,0.12)', color: '#a855f7', label: 'Admin', labelZh: 'Admin' },
        };
        const s = styles[role];
        if (!s) return null;
        return (
            <span style={{ marginLeft: '6px', fontSize: '10px', background: s.bg, color: s.color, borderRadius: '4px', padding: '1px 6px', fontWeight: 500 }}>
                {isChinese ? s.labelZh : s.label}
            </span>
        );
    };

    const formatDate = (iso?: string) => {
        if (!iso) return '-';
        const d = new Date(iso);
        return d.toLocaleString(isChinese ? 'zh-CN' : 'en-US', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
    };

    // Search filter
    const filtered = (() => {
        let result = users;
        if (showUnboundOnly) {
            result = result.filter(u => !u.email && (!u.channel_identities || u.channel_identities.length === 0));
        }
        if (searchQuery.trim()) {
            const q = searchQuery.toLowerCase();
            result = result.filter(u => (u.username?.toLowerCase().includes(q)) || (u.display_name?.toLowerCase().includes(q)) || (u.email?.toLowerCase().includes(q)));
        }
        return result;
    })();

    // Sort
    const sorted = [...filtered].sort((a, b) => {
        const ta = a.created_at ? new Date(a.created_at).getTime() : 0;
        const tb = b.created_at ? new Date(b.created_at).getTime() : 0;
        return sortOrder === 'asc' ? ta - tb : tb - ta;
    });

    // Paginate
    const totalPages = Math.max(1, Math.ceil(sorted.length / PAGE_SIZE));
    const paged = sorted.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

    const toggleSort = () => {
        setSortOrder(o => o === 'asc' ? 'desc' : 'asc');
        setPage(1);
    };

    return (
        <div>
            {toast && (
                <div style={{
                    position: 'fixed', top: '20px', right: '20px', padding: '10px 20px',
                    borderRadius: '8px', background: toast.startsWith('✅') ? 'var(--success)' : 'var(--error)',
                    color: '#fff', fontSize: '13px', zIndex: 9999, transition: 'all 0.3s',
                }}>
                    {toast}
                </div>
            )}

            {loading ? (
                <div style={{ textAlign: 'center', padding: '40px', color: 'var(--text-tertiary)' }}>
                    {t('common.loading')}...
                </div>
            ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    {/* Search bar + Invite button */}
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                            <input
                                className="form-input"
                                type="text"
                                placeholder={isChinese ? '搜索用户名、显示名或邮箱…' : 'Search username, name or email…'}
                                value={searchQuery}
                                onChange={e => { setSearchQuery(e.target.value); setPage(1); }}
                                style={{
                                    width: '280px', fontSize: '13px',
                                    padding: '8px 12px 8px 12px',
                                    background: 'var(--bg-elevated)', border: '1px solid var(--border-subtle)',
                                    borderRadius: '8px',
                                }}
                            />
                            <button className={`btn ${showUnboundOnly ? 'btn-primary' : 'btn-secondary'}`} style={{ fontSize: '12px', padding: '6px 12px' }} onClick={() => { setShowUnboundOnly(!showUnboundOnly); setPage(1); }}>
                                {isChinese ? '未绑定' : 'Unbound'}
                            </button>
                            {(searchQuery || showUnboundOnly) && (
                                <span style={{ fontSize: '12px', color: 'var(--text-tertiary)' }}>
                                    {isChinese ? `${filtered.length} / ${users.length} 位用户` : `${filtered.length} / ${users.length} users`}
                                </span>
                            )}
                        </div>
                        <button
                            className="btn btn-primary"
                            style={{ fontSize: '13px', padding: '6px 16px' }}
                            onClick={() => { setShowInviteModal(true); setInviteEmails(''); setInviteResult(null); }}
                        >
                            {isChinese ? '邀请新用户' : 'Invite Users'}
                        </button>
                    </div>

                    {/* Header */}
                    <div style={{
                        display: 'grid', gridTemplateColumns: '1.4fr 1.4fr 0.8fr 0.7fr 0.7fr 0.8fr 0.8fr 0.8fr 0.8fr 100px',
                        gap: '10px', padding: '10px 16px', fontSize: '11px', fontWeight: 600,
                        color: 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: '0.05em',
                    }}>
                        <div>{t('enterprise.users.user', isChinese ? '用户' : 'User')}</div>
                        <div>{t('enterprise.users.email', 'Email')}</div>
                        {/* Created At with sort toggle */}
                        <div
                            style={{ cursor: 'pointer', userSelect: 'none', display: 'flex', alignItems: 'center', gap: '3px' }}
                            onClick={toggleSort}
                            title={isChinese ? '点击切换排序' : 'Click to toggle sort order'}
                        >
                            {isChinese ? '注册时间' : 'Joined'} {sortOrder === 'asc' ? '↑' : '↓'}
                        </div>
                        <div>{isChinese ? '角色' : 'Role'}</div>
                        <div>{isChinese ? '来源' : 'Source'}</div>
                        <div>{t('enterprise.users.msgQuota', isChinese ? '消息配额' : 'Msg Quota')}</div>
                        <div>{t('enterprise.users.period', isChinese ? '周期' : 'Period')}</div>
                        <div>{t('enterprise.users.agents', isChinese ? '数字员工' : 'Agents')}</div>
                        <div>{t('enterprise.users.ttl', 'TTL')}</div>
                        <div></div>
                    </div>

                    {paged.map(user => (
                        <div key={user.id}>
                            <div className="card" style={{
                                display: 'grid', gridTemplateColumns: '1.4fr 1.4fr 0.8fr 0.7fr 0.7fr 0.8fr 0.8fr 0.8fr 0.8fr 100px',
                                gap: '10px', alignItems: 'center', padding: '12px 16px',
                            }}>
                                <div>
                                    <div style={{ fontWeight: 500, fontSize: '14px' }}>
                                        {user.display_name || user.username}
                                        {roleBadge(user.role)}
                                    </div>
                                    <div style={{ fontSize: '11px', color: 'var(--text-tertiary)' }}>@{user.username}</div>
                                    {user.channel_identities && user.channel_identities.length > 0 && (
                                        <div style={{ display: 'flex', gap: '4px', marginTop: '4px' }}>
                                            {[...new Set(user.channel_identities.map(ch => ch.provider_type))].map(pt => (
                                                <span key={pt} style={{ fontSize: '9px', background: pt === 'feishu' ? 'rgba(58,132,255,0.12)' : pt === 'dingtalk' ? 'rgba(0,137,255,0.12)' : 'rgba(43,174,103,0.12)', color: pt === 'feishu' ? '#3a84ff' : pt === 'dingtalk' ? '#0089ff' : '#2bae67', borderRadius: '3px', padding: '1px 5px' }}>
                                                    {pt === 'feishu' ? '飞书' : pt === 'dingtalk' ? '钉钉' : pt === 'wecom' ? '企微' : pt}
                                                </span>
                                            ))}
                                        </div>
                                    )}
                                </div>
                                <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>{user.email}</div>
                                <div style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>{formatDate(user.created_at)}</div>
                                {/* Role selector — only for admin users, not for platform_admin targets */}
                                <div>
                                    {currentUser?.role && ['platform_admin', 'org_admin'].includes(currentUser.role) && user.role !== 'platform_admin' ? (
                                        <select
                                            className="form-input"
                                            value={user.role}
                                            disabled={changingRoleUserId === user.id}
                                            onChange={e => {
                                                const newRole = e.target.value;
                                                const confirmMsg = isChinese
                                                    ? `确认将 ${user.display_name || user.username} 的角色更改为 ${newRole === 'org_admin' ? 'Admin' : 'Member'}？`
                                                    : `Change ${user.display_name || user.username}'s role to ${newRole === 'org_admin' ? 'Admin' : 'Member'}?`;
                                                if (confirm(confirmMsg)) handleRoleChange(user.id, newRole);
                                            }}
                                            style={{ fontSize: '11px', padding: '2px 4px', width: '100%', minWidth: 0 }}
                                        >
                                            <option value="member">{isChinese ? 'Member' : 'Member'}</option>
                                            <option value="org_admin">{isChinese ? 'Admin' : 'Admin'}</option>
                                        </select>
                                    ) : (
                                        <span style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>
                                            {user.role === 'platform_admin' ? 'Platform Admin'
                                                : user.role === 'org_admin' ? 'Admin' : 'Member'}
                                        </span>
                                    )}
                                </div>
                                <div>
                                    {user.source === 'feishu' ? (
                                        <span style={{ fontSize: '10px', background: 'rgba(58,132,255,0.12)', color: '#3a84ff', borderRadius: '4px', padding: '2px 7px', whiteSpace: 'nowrap' }}>
                                            飞书
                                        </span>
                                    ) : (
                                        <span style={{ fontSize: '10px', background: 'rgba(0,180,120,0.12)', color: 'var(--success)', borderRadius: '4px', padding: '2px 7px', whiteSpace: 'nowrap' }}>
                                            {isChinese ? '注册' : 'Reg'}
                                        </span>
                                    )}
                                </div>
                                <div>
                                    <span style={{ fontSize: '13px', fontWeight: 500 }}>{user.quota_messages_used}</span>
                                    <span style={{ fontSize: '11px', color: 'var(--text-tertiary)' }}> / {user.quota_message_limit}</span>
                                </div>
                                <div>
                                    <span className="badge badge-info" style={{ fontSize: '10px' }}>{periodLabel(user.quota_message_period)}</span>
                                </div>
                                <div>
                                    <span style={{ fontSize: '13px', fontWeight: 500 }}>{user.agents_count}</span>
                                    <span style={{ fontSize: '11px', color: 'var(--text-tertiary)' }}> / {user.quota_max_agents}</span>
                                </div>
                                <div style={{ fontSize: '12px' }}>{user.quota_agent_ttl_hours}h</div>
                                <div style={{ display: 'flex', gap: '4px' }}>
                                    <button className="btn btn-secondary" style={{ padding: '4px 10px', fontSize: '11px' }} onClick={() => editingUserId === user.id ? setEditingUserId(null) : startEdit(user)}>
                                        {editingUserId === user.id ? t('common.cancel') : `✏️`}
                                    </button>
                                    {user.role !== 'platform_admin' && (
                                        <button className="btn btn-secondary" style={{ padding: '4px 10px', fontSize: '11px' }} onClick={() => openMergeModal(user)} title={isChinese ? '合并到其他用户' : 'Merge to another user'}>
                                            🔗
                                        </button>
                                    )}
                                </div>
                            </div>

                            {/* Inline edit form */}
                            {editingUserId === user.id && (
                                <div className="card" style={{ marginTop: '4px', padding: '16px', background: 'var(--bg-secondary)', borderLeft: '3px solid var(--accent-color)' }}>
                                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: '16px' }}>
                                        <div className="form-group">
                                            <label className="form-label" style={{ fontSize: '11px' }}>{t('enterprise.users.msgLimit', isChinese ? '消息限额' : 'Message Limit')}</label>
                                            <input className="form-input" type="number" min={0} value={editForm.quota_message_limit} onChange={e => setEditForm({ ...editForm, quota_message_limit: Number(e.target.value) })} />
                                        </div>
                                        <div className="form-group">
                                            <label className="form-label" style={{ fontSize: '11px' }}>{t('enterprise.users.period', isChinese ? '重置周期' : 'Period')}</label>
                                            <select className="form-input" value={editForm.quota_message_period} onChange={e => setEditForm({ ...editForm, quota_message_period: e.target.value })}>
                                                {PERIOD_OPTIONS.map(p => (<option key={p.value} value={p.value}>{periodLabel(p.value)}</option>))}
                                            </select>
                                        </div>
                                        <div className="form-group">
                                            <label className="form-label" style={{ fontSize: '11px' }}>{t('enterprise.users.maxAgents', isChinese ? '最多数字员工' : 'Max Agents')}</label>
                                            <input className="form-input" type="number" min={0} value={editForm.quota_max_agents} onChange={e => setEditForm({ ...editForm, quota_max_agents: Number(e.target.value) })} />
                                        </div>
                                        <div className="form-group">
                                            <label className="form-label" style={{ fontSize: '11px' }}>{t('enterprise.users.agentTTL', isChinese ? '员工存活时长(h)' : 'Agent TTL (hours)')}</label>
                                            <input className="form-input" type="number" min={1} value={editForm.quota_agent_ttl_hours} onChange={e => setEditForm({ ...editForm, quota_agent_ttl_hours: Number(e.target.value) })} />
                                        </div>
                                    </div>
                                    <div style={{ marginTop: '12px', display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
                                        <button className="btn btn-secondary" onClick={() => setEditingUserId(null)}>{t('common.cancel')}</button>
                                        <button className="btn btn-primary" onClick={handleSave} disabled={saving}>{saving ? (isChinese ? '保存中...' : 'Saving...') : t('common.save')}</button>
                                    </div>
                                </div>
                            )}
                        </div>
                    ))}

                    {paged.length === 0 && (
                        <div style={{ textAlign: 'center', padding: '24px', color: 'var(--text-tertiary)' }}>
                            {isChinese ? '暂无用户数据' : 'No users found'}
                        </div>
                    )}

                    {/* Pagination */}
                    {totalPages > 1 && (
                        <div style={{ display: 'flex', justifyContent: 'center', gap: '8px', marginTop: '16px' }}>
                            <button className="btn btn-secondary" disabled={page === 1} onClick={() => setPage(p => Math.max(1, p - 1))}>{isChinese ? '上一页' : 'Prev'}</button>
                            <span style={{ padding: '8px 16px', fontSize: '13px' }}>{page} / {totalPages}</span>
                            <button className="btn btn-secondary" disabled={page === totalPages} onClick={() => setPage(p => Math.min(totalPages, p + 1))}>{isChinese ? '下一页' : 'Next'}</button>
                        </div>
                    )}
                </div>
            )}

            {/* Invite Users Modal */}
            {showMergeModal && mergeSourceUser && (
                <div style={{ position: 'fixed', inset: 0, zIndex: 10000, background: 'rgba(0,0,0,0.5)', display: 'flex', alignItems: 'center', justifyContent: 'center' }} onClick={() => setShowMergeModal(false)}>
                    <div style={{ background: 'var(--bg-primary)', borderRadius: '12px', width: '480px', boxShadow: '0 20px 60px rgba(0,0,0,0.3)' }} onClick={e => e.stopPropagation()}>
                        <div style={{ padding: '20px', borderBottom: '1px solid var(--border-subtle)', display: 'flex', justifyContent: 'space-between' }}>
                            <h3 style={{ margin: 0, fontSize: '16px' }}>{isChinese ? '合并用户' : 'Merge User'}</h3>
                            <button onClick={() => setShowMergeModal(false)} style={{ background: 'none', border: 'none', fontSize: '18px', cursor: 'pointer' }}>x</button>
                        </div>
                        <div style={{ padding: '20px' }}>
                            <div style={{ marginBottom: '16px', padding: '12px', background: 'var(--bg-secondary)', borderRadius: '8px' }}>
                                <div style={{ fontSize: '12px', color: 'var(--text-tertiary)' }}>{isChinese ? '源用户' : 'Source User'}</div>
                                <div style={{ fontWeight: 500 }}>{mergeSourceUser.display_name || mergeSourceUser.username}</div>
                            </div>
                            <label className="form-label">{isChinese ? '合并到' : 'Merge to'}</label>
                            <select className="form-input" value={mergeTargetId} onChange={e => setMergeTargetId(e.target.value)}>
                                <option value="">{isChinese ? '选择...' : 'Select...'}</option>
                                {users.filter(u => u.id !== mergeSourceUser.id && u.role !== 'platform_admin' && (u.email || (u.channel_identities && u.channel_identities.length > 0))).map(u => (
                                    <option key={u.id} value={u.id}>{u.display_name || u.username} ({u.email || '有渠道'})</option>
                                ))}
                            </select>
                            <div style={{ marginTop: '12px', padding: '10px', background: 'rgba(255,150,0,0.1)', color: '#f90', borderRadius: '6px', fontSize: '12px' }}>
                                ⚠️ {isChinese ? '合并后源用户将被删除' : 'Source user will be deleted'}
                            </div>
                        </div>
                        <div style={{ padding: '16px 20px', borderTop: '1px solid var(--border-subtle)', display: 'flex', justifyContent: 'flex-end', gap: '12px' }}>
                            <button className="btn btn-secondary" onClick={() => setShowMergeModal(false)}>{isChinese ? '取消' : 'Cancel'}</button>
                            <button className="btn btn-primary" onClick={handleMergeUser} disabled={merging || !mergeTargetId}>{merging ? '...' : (isChinese ? '确认' : 'Confirm')}</button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
