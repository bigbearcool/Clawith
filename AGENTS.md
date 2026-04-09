# Clawith 项目指南

## 部署方式

### Docker 部署

```bash
git clone https://github.com/dataelement/Clawith.git
cd Clawith
cp .env.example .env
docker compose up -d --build
# → 前端: http://localhost:3000
# → 后端: http://localhost:8000
```

更新部署：
```bash
git pull && docker compose up -d --build
```

### 本地开发

```bash
bash setup.sh         # 生产依赖
bash setup.sh --dev   # 开发依赖（含 pytest）

bash restart.sh       # 启动服务
# → 前端: http://localhost:3008
# → 后端: http://localhost:8008
```

`restart.sh` 自动检测 Docker 容器，若存在则用 Docker 模式。强制本地模式用 `bash restart.sh --source`。

## 核心命令

### 数据库
```bash
cd backend
.venv/bin/python seed.py                    # 初始化表结构和种子数据
.venv/bin/alembic upgrade head              # 运行迁移（可选，seed.py 已处理）
.venv/bin/alembic stamp head                # 标记当前版本（seed.py 自动执行）

# 重置数据库（清空所有数据）
dropdb clawith && createdb clawith && .venv/bin/python seed.py
```

**重要**：`seed.py` 会创建所有 41 个表并标记 alembic 版本。切勿混用 `Base.metadata.create_all` 和 alembic 迁移，否则会导致表结构不一致。

### 前端
```bash
cd frontend
npm run dev      # 开发服务器
npm run build    # 生产构建 (tsc && vite build)
```

### 后端
```bash
cd backend
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8008  # 启动
.venv/bin/python -m pytest tests/                          # 所有测试
.venv/bin/python -m pytest tests/test_xxx.py               # 单个测试
.venv/bin/ruff check app/                                  # Lint
```

## 环境变量

从 `.env.example` 复制到 `.env`：
- `SECRET_KEY` / `JWT_SECRET_KEY` — 生产环境必须修改
- `DATABASE_URL` — setup.sh 自动配置，或手动指定
- `PUBLIC_BASE_URL` — 生产环境必设（如 `https://your-domain.com`）
- `FEISHU_APP_ID` / `FEISHU_APP_SECRET` — 飞书 SSO（可选）

## 项目结构

### 后端 (`backend/app/`)
- `main.py` — FastAPI 入口
- `api/` — 37 个 API 模块
  - `websocket.py` — 核心：LLM 流式输出、工具调用循环
  - `gateway.py` — OpenClaw 边缘节点协议
  - `enterprise.py` — 企业管理、组织同步
  - `feishu.py` / `wecom.py` / `dingtalk.py` — IM 集成
- `services/` — 业务逻辑
  - `agent_tools.py` — Agent 工具中心
  - `llm_client.py` — LLM 调用封装
- `models/` — SQLAlchemy ORM
- `alembic/versions/` — 数据库迁移

### 前端 (`frontend/src/`)
- `pages/AgentDetail.tsx` — 主 Agent 聊天 UI（WebSocket 流式渲染）
- `pages/EnterpriseSettings.tsx` — 企业设置
- `services/api.ts` — Axios API 客户端
- `stores/` — Zustand 状态管理

### Skills (`backend/agent_template/skills/` + `.agents/skills/`)
Agent 可动态加载的技能模块。

## 架构要点

- 第一个注册用户自动成为平台管理员
- Agent 工作区数据：`backend/agent_data/<agent-id>/`
- Aware Engine：自主触发系统
- A2A：Agent 间通信需 `AgentAgentRelationship` 授权
- OpenClaw：边缘节点 poll/report/send 协议

详细架构见 `ARCHITECTURE_SPEC_EN.md`。

## 技术栈

- Python 3.12+，Node.js 20+，PostgreSQL 15+
- 后端：FastAPI, SQLAlchemy 2.0 async, Alembic, Redis
- 前端：React 19, Vite, TypeScript, Zustand, TanStack Query