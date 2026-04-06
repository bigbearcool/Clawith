# 小圣AI 部署文档

> 分支：`xiaosheng-dev`  
> 基于官方：`Clawith v1.8.1`  
> 更新时间：2026-04-06

---

## 📋 目录

- [概述](#概述)
- [修改内容](#修改内容)
- [部署方式](#部署方式)
- [功能特性](#功能特性)
- [配置说明](#配置说明)
- [常见问题](#常见问题)
- [Git 操作指南](#git-操作指南)

---

## 概述

小圣AI 是基于 Clawith v1.8.1 的企业定制版本，主要包含以下定制内容：

1. **品牌定制化** - 将 Clawith 更名为 小圣AI
2. **飞书消息优化** - 修复截断问题，禁用工具状态和流式光标
3. **企业 SSO 功能** - 支持飞书/钉钉/企业微信 SSO 登录
4. **飞书通讯录全局同步** - 绕过部门权限限制
5. **Agent 群组广播** - 支持向多个群聊发送消息

---

## 修改内容

### 1. 品牌定制化 (小圣AI)

| 文件 | 修改内容 |
|------|----------|
| `frontend/src/pages/Login.tsx` | 登录页标题 "Clawith" → "小圣AI" |
| `frontend/src/pages/Layout.tsx` | 侧边栏 logo 文字 "Clawith" → "小圣AI"，版本号去掉 "v" 前缀 |
| `frontend/src/i18n/zh.json` | 所有中文文案中的 "Clawith" 替换为 "小圣AI"（包括邮件模板） |
| `frontend/VERSION` | `1.8.1-xiaosheng-AI`（不带 v） |
| `backend/VERSION` | `v1.8.1-xiaosheng-AI` |

**版本号显示逻辑**：
- `backend/VERSION`: API 返回的版本号（带 v）
- `frontend/VERSION`: 前端构建时嵌入的版本号（不带 v）
- `Layout.tsx`: 直接显示 `{info.version}`，不再额外加 v

### 2. 飞书消息优化

**文件**: `backend/app/api/feishu.py`

| 问题 | 解决方案 |
|------|----------|
| 消息被截断 | 将最终 PATCH 发送逻辑从 `finally` 块后移至 `try` 块内部，确保执行 |
| 工具调用记录显示 | 注释掉 `_build_card` 中的工具状态区块 |
| 流式光标 "▌" 显示 | `body = answer_text`，不再添加光标 |
| MiniMax 空内容 | 图片回复时 `reply_text` 为空则使用累积内容 |

**关键代码变更**：

```python
# _build_card 函数
def _build_card(
    answer_text: str,
    thinking_text: str = "",
    streaming: bool = False,
    tool_status_lines: list[str] | None = None,
    agent_name: str | None = None,
    show_tool_status: bool = True,  # 新增参数
) -> dict:
    # 工具状态区块 - 已禁用
    # if show_tool_status:
    #     ...
    
    # 主内容 - 不添加光标
    body = answer_text  # 原为: answer_text + ("▌" if streaming else "")
```

```python
# process_feishu_event 函数
try:
    reply_text = await _call_agent_llm(...)
    # ... 发送逻辑移到这里
except Exception as e:
    logger.error(...)
finally:
    # 确保 final PATCH 发送
    if msg_id_for_patch and reply_text:
        final_card = _build_card(final_text, "", streaming=False, show_tool_status=False)
        await feishu_service.patch_message(...)
```

### 3. 企业 SSO 功能

**架构变更**：双 Identity 架构

```
Identity (全局身份) → email, phone (平台唯一)
User (租户用户) → 关联 Identity，支持跨租户
```

**新增文件**：
- `backend/app/models/user.py` - Identity + User 双模型
- `backend/app/api/gateway.py` - Gateway 轮询 API
- `backend/app/api/agent_groups.py` - Agent 群组 API
- `backend/app/core/public_url.py` - 公共 URL 工具
- `backend/app/services/sso_service.py` - SSO 服务重构
- `backend/alembic/versions/add_identity_architecture.py` - Identity 架构迁移
- `backend/alembic/versions/add_sso_login_enabled.py` - SSO 登录开关
- `frontend/src/pages/AgentDetail.tsx` - Agent 详情页

**修改文件**：
- `backend/app/api/auth.py` - SSO 登录重构
- `backend/app/api/admin.py` - Company CRUD + slug
- `backend/app/api/tenants.py` - 子域名解析
- `backend/app/services/org_sync_adapter.py` - 全局用户同步
- `frontend/src/pages/AdminCompanies.tsx` - 管理界面

### 4. 飞书通讯录全局同步

**问题**: 飞书默认 API 需要部门权限，很多企业未开启

**解决方案**: 使用飞书全局用户 API

```python
# 原来: contact/v3/users/find_by_department (需要部门权限)
# 现在: contact/v3/users (全局用户列表，无需部门权限)
```

**功能**：
- 自动同步所有用户（无需部门权限）
- 自动创建/恢复部门
- 姓名拼音转换（支持中文搜索）
- 权限不足警告

### 5. Agent 群组广播

**新增模型**: `AgentGroup`（关联 Agent 和多个群聊）

**使用流程**：
1. Agent 详情页配置群组关系
2. 使用 `send_channel_message` 工具发送群组消息

---

## 部署方式

### 方式一：Docker Compose（推荐）

#### 1. 环境要求

- Docker 20.10+
- Docker Compose 2.0+
- 至少 4GB 内存

#### 2. 克隆项目

```bash
git clone -b xiaosheng-dev https://github.com/bigbearcool/Clawith.git
cd Clawith
```

#### 3. 配置环境变量

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

# 前端端口
FRONTEND_PORT=3008

# 安全密钥
SECRET_KEY=your_secret_key_here
JWT_SECRET_KEY=your_jwt_secret_here

# 飞书配置（可选）
FEISHU_APP_ID=your_app_id
FEISHU_APP_SECRET=your_app_secret

# 密码重置 Token 有效期（分钟）
PASSWORD_RESET_TOKEN_EXPIRE_MINUTES=30
```

#### 4. 启动服务

```bash
# 构建并启动
docker compose up -d --build

# 查看日志
docker compose logs -f

# 查看服务状态
docker ps
```

#### 5. 初始化数据库

```bash
# 进入后端容器
docker exec -it clawith-backend-1 bash

# 运行数据库迁移
alembic upgrade head

# 退出容器
exit
```

#### 6. 访问服务

- **前端**: http://localhost:3008
- **API 文档**: http://localhost:8000/docs
- **企业子域名**: http://{slug}.your-domain.com:3008

#### 7. 更新部署

```bash
# 拉取最新代码
git pull origin xiaosheng-dev

# 重新构建并启动
docker compose up -d --build
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

---

## 功能特性

### 1. 企业 SSO 登录

**支持平台**: 飞书、钉钉、企业微信

**使用流程**：
1. 管理后台创建公司，填写 slug（如 `acme`）
2. 系统自动生成 `sso_domain`: `https://acme.your-domain.com`
3. 配置飞书/钉钉/企业微信应用
4. 访问 `https://acme.your-domain.com/login` 即可 SSO 登录

### 2. 飞书配置

**开放平台**: https://open.feishu.cn

**权限要求**：
- `contact:user.base:readonly` - 获取用户基本信息
- `contact:department.base:readonly` - 获取部门信息（可选）

**配置步骤**：
1. 创建企业自建应用
2. 配置权限（如上）
3. 配置重定向 URL: `https://{slug}.your-domain.com/api/auth/feishu/callback`
4. 获取 `App ID` 和 `App Secret`
5. 在管理后台 → 企业管理 → 飞书配置中填写

---

## 配置说明

### DNS 配置（子域名登录）

如果使用子域名登录，需要配置泛域名解析：

```
*.your-domain.com  A  your-server-ip
```

### Nginx 配置示例

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

## 常见问题

### Q1: 版本号显示为 "vv1.8.1..."

**原因**: VERSION 文件带 v 前缀，前端代码也加了 v

**解决**: 
- `frontend/VERSION` 不带 v（`1.8.1-xiaosheng-AI`）
- 清除浏览器缓存

### Q2: 飞书消息被截断

**原因**: `finally` 块后的代码可能不执行

**解决**: 已修复，最终发送逻辑移至 `try` 块内部

### Q3: 飞书同步只返回 1 个用户

**原因**: 飞书应用权限不足或应用配置错误

**解决**:
1. 确认飞书开放平台已添加权限
2. 确认应用可用范围为"全员"
3. 确认使用正确的 App ID 和 App Secret

### Q4: 登录页没有 SSO 选项

**原因**: 访问了 `localhost` 而不是企业子域名

**解决**: 使用企业子域名访问，如 `https://acme.your-domain.com/login`

### Q5: 数据库迁移失败

**解决**:

```bash
# 检查迁移状态
alembic current

# 重置迁移
alembic downgrade base
alembic upgrade head
```

---

## Git 操作指南

### 1. 查看分支状态

```bash
# 查看本地分支
git branch

# 查看当前状态
git status

# 查看与官方版本的差异
git log --oneline v1.8.1..HEAD
git diff --stat v1.8.1..HEAD
```

### 2. 同步官方更新

```bash
# 添加官方仓库（如果还没添加）
git remote add upstream https://github.com/dataelement/Clawith.git

# 拉取官方更新
git fetch upstream

# 合并官方主分支
git merge upstream/main

# 推送到你的分支
git push origin xiaosheng-dev
```

### 3. 提交更改

```bash
# 添加更改
git add .

# 提交
git commit -m "描述你的更改"

# 推送
git push origin xiaosheng-dev
```

---

## 维护命令

### 数据库

```bash
# 备份数据库
docker exec clawith-postgres-1 pg_dump -U clawith clawith > backup.sql

# 恢复数据库
cat backup.sql | docker exec -i clawith-postgres-1 psql -U clawith clawith

# 清空数据库（危险操作）
docker compose down -v
```

### 日志

```bash
# 查看后端日志
docker logs clawith-backend-1 -f --tail 100

# 查看所有服务日志
docker compose logs -f
```

### 重启服务

```bash
# 重启单个服务
docker compose restart backend

# 重启所有服务
docker compose restart
```

---

## 代码差异统计

```
48 files changed
5362 insertions(+)
3124 deletions(-)
```

**新增文件 (11个)**：
- `backend/alembic/versions/add_identity_architecture.py`
- `backend/alembic/versions/add_sso_login_enabled.py`
- `backend/alembic/versions/add_failed_status_to_tasks.py`
- `backend/alembic/versions/add_task_status_to_chat_sessions.py`
- `backend/app/api/gateway.py`
- `backend/app/api/agent_groups.py`
- `backend/app/core/public_url.py`
- `frontend/src/pages/AgentDetail.tsx`
- `ENTERPRISE_SSO_DEPLOYMENT.md`
- `PR_DESCRIPTION.md`

---

## Commit 历史（关键提交）

```
9c49226 feat: 小圣AI定制化 - 品牌更名、飞书消息优化、版本号更新
c1d1f11 fix: Feishu org sync - use global user API
305e018 chore: add pypinyin for org sync
1b28d60 feat: 企业 SSO 功能完善
47f52cb feat: implement dual-identity architecture
b7ede9c feat: add enterprise SSO support with custom slug
```

---

## 支持

- **GitHub**: https://github.com/bigbearcool/Clawith
- **分支**: https://github.com/bigbearcool/Clawith/tree/xiaosheng-dev
- **官方仓库**: https://github.com/dataelement/Clawith

---

## License

MIT License - 与官方 Clawith 一致