"""Seed data script — creates all tables and seeds initial data.

This script should be run after `alembic upgrade head` to populate initial data.
For a fresh database, you can run this directly to create all tables.
"""

import asyncio
import sys

sys.path.insert(0, ".")

from app.config import get_settings
from app.core.security import hash_password
from app.database import Base, engine, async_session

# Import ALL models so Base.metadata.create_all can create all tables
# Order matters for foreign key resolution
from app.models.tenant import Tenant  # noqa: F401
from app.models.user import User, Identity  # noqa: F401
from app.models.identity import IdentityProvider, SSOScanSession  # noqa: F401
from app.models.agent import Agent, AgentTemplate  # noqa: F401
from app.models.llm import LLMModel  # noqa: F401
from app.models.task import Task  # noqa: F401
from app.models.skill import Skill, SkillFile  # noqa: F401
from app.models.tool import Tool  # noqa: F401
from app.models.participant import Participant  # noqa: F401
from app.models.channel_config import ChannelConfig  # noqa: F401
from app.models.schedule import AgentSchedule  # noqa: F401
from app.models.trigger import AgentTrigger  # noqa: F401
from app.models.audit import AuditLog  # noqa: F401
from app.models.plaza import PlazaPost, PlazaComment, PlazaLike  # noqa: F401
from app.models.activity_log import AgentActivityLog  # noqa: F401
from app.models.org import OrgDepartment, OrgMember, AgentRelationship, AgentAgentRelationship  # noqa: F401
from app.models.system_settings import SystemSetting  # noqa: F401
from app.models.invitation_code import InvitationCode  # noqa: F401
from app.models.agent_credential import AgentCredential  # noqa: F401
from app.models.chat_session import ChatSession  # noqa: F401
from app.models.gateway_message import GatewayMessage  # noqa: F401
from app.models.notification import Notification  # noqa: F401
from app.models.published_page import PublishedPage  # noqa: F401
from app.models.tenant_setting import TenantSetting  # noqa: F401


async def seed():
    """Create tables and seed initial data.

    This function:
    1. Creates all tables using SQLAlchemy metadata (if not exist)
    2. Seeds initial data (default tenant, agent templates)
    3. Marks alembic as up-to-date (so future migrations work correctly)
    """
    settings = get_settings()

    # Create all tables (idempotent - skips existing tables)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("✅ Database tables created")

    # Mark alembic as up-to-date so future migrations work
    import subprocess

    try:
        result = subprocess.run(
            [".venv/bin/alembic", "stamp", "head"],
            capture_output=True,
            text=True,
            cwd="/app" if settings.AGENT_DATA_DIR.startswith("/data") else ".",
        )
        if result.returncode == 0:
            print("✅ Alembic marked as up-to-date")
    except Exception:
        pass  # Alembic may not be configured

    async with async_session() as db:
        # Note: No default admin user is seeded.
        # The first user to register via the UI becomes platform_admin automatically.
        from sqlalchemy import select, func

        # 1. Default company (tenant)
        existing_tenant = await db.execute(select(Tenant).where(Tenant.slug == "default"))
        if not existing_tenant.scalar_one_or_none():
            db.add(Tenant(name="Default", slug="default", im_provider="web_only"))
            print("✅ Default company created")

        # 2. Built-in templates
        templates = [
            {
                "name": "研究助手",
                "description": "专注于信息搜集、竞品分析、行业研究的数字员工",
                "icon": "🔬",
                "category": "research",
                "soul_template": "## Identity\n你是一名专业的研究助手，擅长信息搜集和分析。\n\n## Personality\n- 严谨细致\n- 数据驱动\n- 客观中立\n\n## Boundaries\n- 引用来源须标注\n- 不做主观判断",
                "is_builtin": True,
            },
            {
                "name": "项目管理助手",
                "description": "负责项目进度跟踪、任务分配、督办提醒的数字员工",
                "icon": "📋",
                "category": "management",
                "soul_template": "## Identity\n你是一名高效的项目管理助手。\n\n## Personality\n- 条理清晰\n- 主动跟进\n- 注重截止日期\n\n## Boundaries\n- 不擅自修改项目计划\n- 重大决策需确认",
                "is_builtin": True,
            },
            {
                "name": "客户服务助手",
                "description": "处理客户咨询、FAQ 回答、工单管理的数字员工",
                "icon": "💬",
                "category": "support",
                "soul_template": "## Identity\n你是一名热情专业的客户服务助手。\n\n## Personality\n- 友好热情\n- 耐心细致\n- 解决导向\n\n## Boundaries\n- 不承诺超出权限的内容\n- 敏感问题转人工",
                "is_builtin": True,
            },
            {
                "name": "数据分析师",
                "description": "数据查询、报表生成、趋势分析的数字员工",
                "icon": "📊",
                "category": "analytics",
                "soul_template": "## Identity\n你是一名数据分析专家。\n\n## Personality\n- 精确严谨\n- 善于可视化\n- 洞察力强\n\n## Boundaries\n- 数据安全第一\n- 不泄露原始数据",
                "is_builtin": True,
            },
            {
                "name": "内容创作助手",
                "description": "文案撰写、内容审核、社交媒体管理的数字员工",
                "icon": "✍️",
                "category": "content",
                "soul_template": "## Identity\n你是一名创意内容助手。\n\n## Personality\n- 创意丰富\n- 文字功底好\n- 了解营销\n\n## Boundaries\n- 遵守品牌调性\n- 发布前需审核",
                "is_builtin": True,
            },
        ]

        for tmpl in templates:
            existing = await db.execute(select(AgentTemplate).where(AgentTemplate.name == tmpl["name"]))
            if not existing.scalar_one_or_none():
                db.add(AgentTemplate(**tmpl))
                print(f"✅ Template created: {tmpl['icon']} {tmpl['name']}")

        # 3. Demo agents for platform admin (if admin has zero agents)
        from app.models.agent import Agent

        admin_result = await db.execute(select(User).where(User.role == "platform_admin"))
        admin_user = admin_result.scalar_one_or_none()
        if admin_user:
            agent_count_result = await db.execute(
                select(func.count()).select_from(Agent).where(Agent.creator_id == admin_user.id)
            )
            agent_count = agent_count_result.scalar()
            if agent_count == 0:
                demo_agents = [
                    {
                        "name": "Morty",
                        "role_description": "Research Assistant — focused on information gathering, competitive analysis, and industry research.",
                        "status": "idle",
                        "heartbeat_enabled": True,
                    },
                    {
                        "name": "Meeseeks",
                        "role_description": "Task Executor — focuses on completing specific tasks assigned by the user efficiently.",
                        "status": "idle",
                        "heartbeat_enabled": True,
                    },
                ]
                for agent_data in demo_agents:
                    agent = Agent(
                        creator_id=admin_user.id,
                        tenant_id=admin_user.tenant_id,
                        **agent_data,
                    )
                    db.add(agent)
                    await db.flush()

                    # Initialize workspace directories
                    from pathlib import Path

                    ws_root = Path(settings.AGENT_DATA_DIR) / str(agent.id)
                    try:
                        for sub in ["workspace", "memory", "skills"]:
                            (ws_root / sub).mkdir(parents=True, exist_ok=True)
                        soul_path = ws_root / "soul.md"
                        if not soul_path.exists():
                            soul_path.write_text(f"# {agent.name}\n\n{agent.role_description}\n", encoding="utf-8")
                        mem_path = ws_root / "memory" / "memory.md"
                        if not mem_path.exists():
                            mem_path.write_text(
                                "# Memory\n\n_Record important information and knowledge here._\n", encoding="utf-8"
                            )
                    except OSError:
                        pass  # AGENT_DATA_DIR may not be writable
                    print(f"✅ Demo agent created: {agent.name}")

        await db.commit()

    print("\n🎉 Seed data complete!")


if __name__ == "__main__":
    asyncio.run(seed())
