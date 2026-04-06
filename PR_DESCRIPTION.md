# feat: Enterprise SSO Enhancement with Custom Subdomain and Feishu Global Sync

## 📝 Summary

This PR introduces comprehensive enterprise SSO enhancements based on v1.8.1, including:

- **Dual Identity Architecture**: Separate global Identity and tenant-scoped User models
- **Custom Subdomain Login**: Auto-generated SSO domains from company slugs
- **Feishu Global User Sync**: Bypass department permission limitations
- **Agent Group Broadcasting**: Support for multi-group message broadcasting
- **Platform Settings UI**: Admin interface for platform configuration

## 🎯 Motivation

### Problem Statement

1. **User Identity Management**: Current single-layer User model doesn't support cross-tenant scenarios (same user joining multiple companies)

2. **SSO Domain Configuration**: No way to customize SSO login domains, limiting enterprise deployment flexibility

3. **Feishu Org Sync Limitations**: Default API requires department permissions that many enterprises don't enable, resulting in incomplete user sync

4. **Agent Broadcasting**: No support for sending messages to multiple groups simultaneously

### Solution

This PR addresses these issues with a complete enterprise SSO solution while maintaining backward compatibility.

## ✨ Key Features

### 1. Dual Identity Architecture

**Before**: Single User model
```
User → tenant_id, email, phone (all in one table)
```

**After**: Separated models
```
Identity → global (email, phone - unique across platform)
User → tenant-scoped (links to Identity)
```

**Benefits**:
- Same email can join multiple companies
- Unified identity management
- Better multi-tenant isolation

**Files Changed**:
- `backend/app/models/user.py` - Identity + User models
- `backend/alembic/versions/add_identity_architecture.py` - Migration script

### 2. Custom Subdomain SSO Login

**Workflow**:
1. Admin creates company with custom `slug` (e.g., "acme")
2. System auto-generates `sso_domain`: `https://acme.your-domain.com`
3. Users access `https://acme.your-domain.com/login` for tenant-specific SSO login
4. SSO callback URLs use correct tenant subdomain

**Implementation**:
- `backend/app/api/admin.py` - Company CRUD with slug support
- `backend/app/services/platform_service.py` - SSO domain generation
- `backend/app/api/tenants.py` - Subdomain resolution (supports any domain pattern)
- `frontend/src/pages/AdminCompanies.tsx` - Platform settings UI

**Example**:
```python
# Company creation
POST /api/admin/companies
{
  "name": "Acme Corp",
  "slug": "acme"  # Custom slug
}

# Auto-generated
sso_domain = "https://acme.platform.com"

# Login URL
https://acme.platform.com/login → SSO for Acme Corp
```

### 3. Feishu Global User Sync

**Problem**: Default API `contact/v3/users/find_by_department` requires:
- `contact:user.base:readonly`
- `contact:department.base:readonly` ← Often not enabled

**Solution**: Use global user list API `contact/v3/users` that works without department permissions

**Features**:
- Syncs all users regardless of department access
- Auto-creates departments from user data
- Pinyin conversion for Chinese name search
- Permission warning when few users synced

**Files Changed**:
- `backend/app/services/org_sync_adapter.py` - Global user API integration
- `backend/app/services/feishu_service.py` - Refactored Feishu service
- `backend/requirements.txt` - Added `pypinyin`

### 4. Agent Group Broadcasting

**Use Case**: Send messages to multiple WeChat/Feishu groups from one agent

**Implementation**:
- New `AgentGroup` model: links agent to chat groups
- Enhanced `send_channel_message` tool supports group broadcasting
- UI in `AgentDetail.tsx` for group configuration

**Example**:
```python
# Agent can broadcast to configured groups
send_channel_message(message="Update", groups=["sales", "support"])
```

### 5. Platform Settings UI

**Admin Interface**: Configure platform-wide settings
- Public Base URL (for SSO domain generation)
- View all companies and their SSO domains
- Edit company slugs

**Location**: Admin → Companies → Platform Settings

## 📊 Changes Summary

### New Files (9)

**Backend**:
1. `backend/alembic/versions/add_identity_architecture.py` - Identity migration
2. `backend/alembic/versions/add_sso_login_enabled.py` - SSO flag migration
3. `backend/app/api/agent_groups.py` - Group management API
4. `backend/app/api/gateway.py` - Gateway polling (extracted from main.py)
5. `backend/app/core/public_url.py` - URL utility functions

**Frontend**:
6. `frontend/src/pages/AgentDetail.tsx` - Agent group configuration

### Modified Files (26)

| File | Changes | Description |
|------|---------|-------------|
| `backend/app/models/user.py` | +31 lines | Identity + User dual model |
| `backend/app/models/org.py` | +32 lines | AgentGroup model |
| `backend/app/api/auth.py` | -897 lines | SSO login refactoring |
| `backend/app/api/admin.py` | +329 lines | Company CRUD + slug |
| `backend/app/api/tenants.py` | +112 lines | Subdomain resolution |
| `backend/app/services/org_sync_adapter.py` | +507 lines | Global user sync |
| `backend/app/services/sso_service.py` | +167 lines | SSO service |
| `frontend/src/pages/AdminCompanies.tsx` | +248 lines | Admin UI |

### Statistics

```
31 files changed
2208 insertions(+)
1783 deletions(-)
```

## 🧪 Testing

### Test Environment
- Docker Compose deployment
- PostgreSQL 15
- Python 3.12
- Node.js 18

### Test Cases

#### 1. Dual Identity Architecture
- [x] User can register with same email
- [x] User can join multiple companies
- [x] Identity data is shared across tenants
- [x] User data is isolated per tenant

#### 2. SSO Subdomain Login
- [x] Create company with custom slug
- [x] SSO domain auto-generated
- [x] Access login via subdomain
- [x] SSO providers show correctly
- [x] Callback URL uses correct domain

#### 3. Feishu Global Sync
- [x] Sync users without department permissions
- [x] Auto-create departments
- [x] Pinyin conversion works
- [x] Permission warning displays
- [x] All users synced correctly

#### 4. Agent Group Broadcasting
- [x] Configure agent groups
- [x] Send message to multiple groups
- [x] Group management API works

### Manual Testing Steps

```bash
# 1. Start services
docker-compose up -d

# 2. Run migrations
docker exec -it clawith-backend-1 alembic upgrade head

# 3. Create company with slug
POST /api/admin/companies
{
  "name": "Test Corp",
  "slug": "test"
}

# 4. Configure Feishu SSO
POST /api/enterprise/identity-providers
{
  "provider_type": "feishu",
  "config": {
    "app_id": "xxx",
    "app_secret": "xxx"
  }
}

# 5. Trigger org sync
POST /api/enterprise/org/sync?provider_id=xxx

# 6. Access login page
http://test.your-domain.com/login
```

## 📸 Screenshots

### Platform Settings UI
![Platform Settings](screenshots/platform-settings.png)
*Configure PUBLIC_BASE_URL and view all companies*

### Company Edit with Slug
![Company Edit](screenshots/company-edit.png)
*Custom slug input with auto-generated SSO domain*

### SSO Login Page
![SSO Login](screenshots/sso-login.png)
*Enterprise subdomain login with SSO options*

## ⚠️ Breaking Changes

### Database Migration Required

```bash
alembic upgrade head
```

This will:
1. Create `identities` table
2. Migrate existing user data to identities
3. Add `identity_id` foreign key to users
4. Add `sso_login_enabled` to identity_providers

### Configuration Changes

**Required**:
```env
# .env
PUBLIC_BASE_URL=https://your-domain.com
```

**DNS Configuration** (for subdomain SSO):
```
*.your-domain.com A your-server-ip
```

### API Changes

**New Endpoint**:
```
GET /api/tenants/resolve-by-domain?domain=xxx
```

**Modified Endpoints**:
```
POST /api/admin/companies - accepts "slug" field
PATCH /api/admin/companies/{id} - can update slug
GET /api/enterprise/org/sync - enhanced Feishu sync
```

## 🔄 Migration Guide

### For Existing Deployments

1. **Backup Database**
   ```bash
   pg_dump clawith > backup.sql
   ```

2. **Pull Changes**
   ```bash
   git pull origin enterprise-sso-v1.8.1
   ```

3. **Update Environment**
   ```bash
   # Add to .env
   PUBLIC_BASE_URL=https://your-domain.com
   ```

4. **Run Migration**
   ```bash
   alembic upgrade head
   ```

5. **Restart Services**
   ```bash
   docker-compose restart
   ```

6. **Update DNS** (if using subdomain SSO)
   - Configure wildcard DNS record
   - Update Nginx configuration

### For New Deployments

Follow the [deployment guide](ENTERPRISE_SSO_DEPLOYMENT.md).

## 📚 Documentation

Complete deployment documentation added:
- [ENTERPRISE_SSO_DEPLOYMENT.md](ENTERPRISE_SSO_DEPLOYMENT.md)

Includes:
- Git operations
- Deployment methods (Docker Compose, manual)
- Configuration guide
- Troubleshooting
- Maintenance commands

## 🔗 Related Issues

Addresses community requests for:
- Multi-tenant identity management
- Custom SSO domains
- Better Feishu integration
- Group broadcasting capabilities

## 🎓 Lessons Learned

### Technical Challenges

1. **SQLAlchemy Model Registration**
   - Issue: Cross-model relationships causing registration failures
   - Solution: Use `TYPE_CHECKING` for forward references

2. **Tenant Resolution**
   - Issue: Hard-coded `*.clawith.ai` domain pattern
   - Solution: Generic subdomain extraction supporting any domain

3. **Feishu API Limitations**
   - Issue: Department permission requirements
   - Solution: Use global user API endpoint

4. **Database Migration Strategy**
   - Issue: Moving existing users to Identity model
   - Solution: Migration script with data preservation

## 🤝 Credits

- Based on official Clawith v1.8.1
- Enterprise features developed by @bigbearcool
- Inspired by community feedback and enterprise deployment needs

## 📋 Checklist

- [x] Code follows project style guidelines
- [x] Self-review completed
- [x] Comments added for complex logic
- [x] Documentation updated
- [x] No new warnings generated
- [x] Tests added/updated (manual testing)
- [x] Local testing passed
- [x] Database migration tested
- [x] Backward compatibility maintained
- [x] Breaking changes documented

## 🔮 Future Enhancements

Potential improvements for future PRs:
- [ ] Automated tests for SSO flow
- [ ] More identity providers (Google, Microsoft, etc.)
- [ ] Advanced org sync conflict resolution
- [ ] Group broadcasting scheduling
- [ ] Multi-language support for enterprise features

---

## 💬 Discussion Points

We welcome feedback on:
1. **Identity architecture** - Is the dual model approach appropriate?
2. **Domain resolution** - Should we support more patterns?
3. **Migration strategy** - Any edge cases we missed?
4. **API design** - Are the new endpoints intuitive?

Thank you for reviewing this PR! 🙏