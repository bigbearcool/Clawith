# Clawith 企业版 SSO 部署文档

> 分支：`enterprise-sso-v1.8.1`  
> 基于官方：`v1.8.1`  
> 更新时间：2025-04-05

---

## 📋 目录

- [Git 操作指南](#git-操作指南)
- [部署方式](#部署方式)
- [功能特性](#功能特性)
- [代码差异](#代码差异)
- [配置说明](#配置说明)
- [常见问题](#常见问题)

---

## 🔀 Git 操作指南

### 1. 克隆项目

```bash
# 克隆并切换到此分支
git clone -b enterprise-sso-v1.8.1 https://github.com/bigbearcool/Clawith.git

# 或克隆后切换
git clone https://github.com/bigbearcool/Clawith.git
cd Clawith
git checkout enterprise-sso-v1.8.1
```

### 2. 查看分支状态

```bash
# 查看本地分支
git branch

# 查看所有分支（含远程）
git branch -a

# 查看当前状态
git status

# 查看与官方版本的差异
git log --oneline v1.8.1..HEAD
git diff --stat v1.8.1..HEAD
```

### 3. 提交更改

```bash
# 添加所有更改
git add .

# 提交
git commit -m "描述你的更改"

# 推送到远程
git push origin enterprise-sso-v1.8.1
```

### 4. 拉取远程更新

```bash
git pull origin enterprise-sso-v1.8.1
```

### 5. 同步官方更新

```bash
# 添加官方仓库（如果还没添加）
git remote add upstream https://github.com/dataelement/Clawith.git

# 拉取官方更新
git fetch upstream

# 合并官方主分支
git merge upstream/main

# 或合并特定版本标签
git merge v1.8.1

# 推送到你的分支
git push origin enterprise-sso-v1.8.1
```

### 6. 合并到主分支

```bash
# 切换到主分支
git checkout main

# 合并企业版分支
git merge enterprise-sso-v1.8.1

# 推送
git push origin main
```

### 7. 创建 Pull Request

访问：https://github.com/bigbearcool/Clawith/pull/new/enterprise-sso-v1.8.1

---

## 🚀 部署方式

### 方式一：Docker Compose（推荐）

#### 1. 环境要求

- Docker 20.10+
- Docker Compose 2.0+
- 至少 4GB 内存

#### 2. 配置环境变量

创建 `.env` 文件：

```env
# 数据库配置
POSTGRES_USER=clawith
POSTGRES_PASSWORD=your_secure_password
POSTGRES_DB=clawith

# 平台公共 URL（必填，用于生成 SSO 域名）
PUBLIC_BASE_URL=https://your-domain.com

# 如果使用 IP 访问
# PUBLIC_BASE_URL=http://1.2.3.4:3008

# 其他配置
DEBUG=false
SECRET_KEY=your_secret_key_here
```

#### 3. 启动服务

```bash
# 启动所有服务
docker-compose up -d

# 查看日志
docker-compose logs -f

# 查看服务状态
docker ps
```

#### 4. 初始化数据库

```bash
# 进入后端容器
docker exec -it clawith-backend-1 bash

# 运行数据库迁移
alembic upgrade head

# 退出容器
exit
```

#### 5. 访问服务

- **前端**: http://localhost:3008
- **API**: http://localhost:8000/docs
- **企业子域名**: http://{slug}.your-domain.com:3008

#### 6. 停止服务

```bash
# 停止服务
docker-compose down

# 停止并清空数据
docker-compose down -v
```

### 方式二：手动部署

#### 后端

```bash
cd backend

# 安装依赖
pip install -r requirements.txt

# 配置数据库
export DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/clawith

# 运行迁移
alembic upgrade head

# 启动服务
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

#### 前端

```bash
cd frontend

# 安装依赖
npm install

# 构建
npm run build

# 或开发模式
npm run dev
```

### DNS 配置

如果使用子域名登录，需要配置泛域名解析：

```
*.your-domain.com  A  your-server-ip
```

---

## ✨ 功能特性

### 1. 双 Identity 架构

**概述**: 将用户身份分为两层
- `Identity`: 全局身份（email, phone 等唯一标识）
- `User`: 租户用户（关联 Identity，支持跨租户）

**优势**:
- 支持同一用户加入多个企业
- 统一身份管理
- 租户数据隔离

**相关文件**:
- `backend/app/models/user.py` - 模型定义
- `backend/alembic/versions/add_identity_architecture.py` - 迁移脚本

### 2. 企业 SSO 登录

**支持平台**: 飞书、钉钉、企业微信

**功能**:
- 自定义企业 slug
- 自动生成企业子域名登录页
- SSO 回调 URL 使用正确的租户域名

**使用流程**:
1. 管理后台创建公司，填写 slug（如 `acme`）
2. 系统自动生成 `sso_domain`: `https://acme.your-domain.com`
3. 配置飞书/钉钉/企业微信应用
4. 访问 `https://acme.your-domain.com/login` 即可 SSO 登录

**相关文件**:
- `backend/app/services/sso_service.py` - SSO 服务
- `backend/app/api/auth.py` - 登录 API
- `frontend/src/pages/Login.tsx` - 登录页

### 3. 飞书通讯录全局同步

**问题**: 飞书默认 API 需要部门权限，但很多企业未开启

**解决方案**: 使用飞书全局用户 API，绕过部门权限限制

**功能**:
- 自动同步所有用户（无需部门权限）
- 自动创建/恢复部门
- 姓名拼音转换（支持中文搜索）
- 权限不足警告

**配置权限**（飞书开放平台）:
- `contact:user.base:readonly` - 获取用户基本信息
- `contact:department.base:readonly` - 获取部门信息（可选）

**相关文件**:
- `backend/app/services/org_sync_adapter.py` - 同步适配器
- `backend/app/services/feishu_service.py` - 飞书服务

### 4. Agent 群组广播

**功能**: Agent 可以向多个群聊发送消息

**使用**:
1. Agent 详情页配置群组关系
2. 使用 `send_channel_message` 工具发送群组消息

**相关文件**:
- `backend/app/models/org.py` - AgentGroup 模型
- `backend/app/api/agent_groups.py` - 群组 API
- `backend/app/services/agent_tools.py` - 消息发送工具

### 5. 平台设置 UI

**功能**: 在管理后台配置平台公共 URL

**位置**: 管理后台 → 公司管理 → 平台设置

**相关文件**:
- `frontend/src/pages/AdminCompanies.tsx` - 管理界面
- `backend/app/core/public_url.py` - URL 工具函数

---

## 📊 代码差异

### 新增文件 (9个)

#### 后端
1. `backend/alembic/versions/add_identity_architecture.py` - Identity 架构迁移
2. `backend/alembic/versions/add_sso_login_enabled.py` - SSO 登录开关
3. `backend/app/api/agent_groups.py` - Agent 群组 API
4. `backend/app/api/gateway.py` - Gateway 轮询 API
5. `backend/app/core/public_url.py` - 公共 URL 工具

#### 前端
6. `frontend/src/pages/AgentDetail.tsx` - Agent 详情页

### 修改文件 (26个)

| 文件 | 改动 | 说明 |
|------|------|------|
| `backend/app/models/user.py` | +31 | Identity + User 双模型 |
| `backend/app/models/org.py` | +32 | AgentGroup 模型 |
| `backend/app/api/auth.py` | -897 | SSO 登录重构 |
| `backend/app/api/admin.py` | +329 | Company CRUD + slug |
| `backend/app/api/tenants.py` | +112 | 子域名解析 |
| `backend/app/services/org_sync_adapter.py` | +507 | 全局用户同步 |
| `backend/app/services/feishu_service.py` | -516 | 飞书服务重构 |
| `backend/app/services/sso_service.py` | +167 | SSO 服务 |
| `frontend/src/pages/AdminCompanies.tsx` | +248 | 管理界面 |

### 统计

```
31 files changed
2208 insertions(+)
1783 deletions(-)
```

---

## ⚙️ 配置说明

### 1. 环境变量

| 变量 | 说明 | 示例 |
|------|------|------|
| `PUBLIC_BASE_URL` | 平台公共 URL | `https://your-domain.com` |
| `DATABASE_URL` | 数据库连接 | `postgresql+asyncpg://...` |
| `SECRET_KEY` | 密钥 | 随机字符串 |
| `DEBUG` | 调试模式 | `false` |

### 2. 企业 SSO 配置

#### 飞书配置

**开放平台**: https://open.feishu.cn

1. 创建企业自建应用
2. 配置权限:
   - `contact:user.base:readonly`
   - `contact:department.base:readonly` (可选)
3. 配置重定向 URL: `https://{slug}.your-domain.com/api/auth/feishu/callback`
4. 获取 `App ID` 和 `App Secret`

**在管理后台配置**:
- 进入企业管理 → 飞书配置
- 填写 App ID 和 App Secret
- 开启 SSO 登录
- 触发通讯录同步

#### 钉钉/企业微信

类似配置，参考官方文档。

### 3. DNS 配置

**泛域名解析**:

```
类型: A
主机: *
值: your-server-ip
TTL: 600
```

**Nginx 配置**:

```nginx
server {
    listen 3000;
    server_name ~^(?<subdomain>.+)\.your-domain\.com$;
    
    location / {
        proxy_pass http://frontend:3000;
        proxy_set_header Host $host;
    }
    
    location /api/ {
        proxy_pass http://backend:8000;
        proxy_set_header Host $host;
    }
}
```

---

## ❓ 常见问题

### Q1: 登录页没有 SSO 选项？

**原因**: 访问了 `localhost` 而不是企业子域名

**解决**: 使用企业子域名访问，如 `https://acme.your-domain.com/login`

### Q2: 飞书同步只返回 1 个用户？

**原因**: 飞书应用权限不足或应用配置错误

**解决**:
1. 确认飞书开放平台已添加权限
2. 确认应用可用范围为"全员"
3. 确认使用正确的 App ID 和 App Secret

### Q3: 数据库迁移失败？

**解决**:

```bash
# 检查迁移状态
alembic current

# 重置迁移
alembic downgrade base
alembic upgrade head
```

### Q4: 子域名解析失败？

**检查**:
1. DNS 是否配置泛域名解析
2. Nginx 是否配置正确
3. 访问 `GET /api/tenants/resolve-by-domain?domain=xxx`

### Q5: SSO 回调 URL 错误？

**检查**:
1. 企业 `sso_domain` 是否正确
2. 飞书开放平台重定向 URL 是否配置
3. `PUBLIC_BASE_URL` 环境变量是否设置

---

## 🔧 维护命令

### 数据库

```bash
# 清空数据库（危险操作）
docker-compose down -v

# 备份数据库
docker exec clawith-postgres-1 pg_dump -U clawith clawith > backup.sql

# 恢复数据库
cat backup.sql | docker exec -i clawith-postgres-1 psql -U clawith clawith
```

### 日志

```bash
# 查看后端日志
docker logs clawith-backend-1 -f --tail 100

# 查看所有服务日志
docker-compose logs -f
```

### 重启服务

```bash
# 重启单个服务
docker-compose restart backend

# 重启所有服务
docker-compose restart
```

---

## 📝 Commit 历史

完整提交记录（25个）:

```
1b28d60 feat: 企业 SSO 功能完善
b1fbd04 fix: add synchronize_session=False for bulk update
63ceed8 feat: add permission warning when Feishu sync returns few users
421f50a fix: add missing validate_sso_enablement method
5c6f2ce fix: force regenerate sso_domain when slug changes
d1acb17 fix: show updated SSO domain after editing company slug
0b35118 fix: slug generation and migration dependency
28745e9 fix: correct indentation in platform_service.py
9c104f7 fix: change priority - database PUBLIC_BASE_URL > env
2db113e feat: auto-refresh companies list after platform URL saved
f94e992 feat: auto-generate SSO domain from slug and platform URL
ae5f736 fix: merge headers correctly in fetchJson
c07f747 feat: add platform public URL setting UI
ed96081 fix: correct indentation errors in tenants.py
f6fdf4b fix: correct docker-compose.yml indentation
3a6114c chore: update VERSION to 1.8.1-enterprise
2b8529a fix: use login_identifier instead of username
47f52cb feat: implement dual-identity architecture
c7e2d95 fix: correct Identity import path
b7ede9c feat: add enterprise SSO support with custom slug
0a10cb0 chore: apply local WIP fixes
a600367 fix: Feishu org sync - use global user API
b036b25 fix: use Feishu global user API
d74c9e6 chore: add pypinyin for org sync
a4fa49a fix: send_channel_message support group broadcast
72d8d11 feat: add group relationship support
```

---

## 📞 支持

- **GitHub**: https://github.com/bigbearcool/Clawith
- **分支**: https://github.com/bigbearcool/Clawith/tree/enterprise-sso-v1.8.1
- **官方仓库**: https://github.com/dataelement/Clawith

---

## 📄 License

MIT License - 与官方 Clawith 一致