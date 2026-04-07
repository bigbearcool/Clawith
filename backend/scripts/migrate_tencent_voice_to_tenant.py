#!/usr/bin/env python3
"""Migrate tencent_voice_key from system_settings to tenant_settings for 熊团出击 tenant."""

import asyncio
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from app.database import async_session

# 熊团出击 tenant ID
TENANT_ID_XIONG_TUAN = "108d2abd-d33e-4a0a-8129-34a7f6e2fa09"


async def migrate_tencent_voice_key():
    """Migrate tencent_voice_key from system_settings to tenant_settings."""
    async with async_session() as db:
        try:
            # 1. 读取现有的系统级配置
            result = await db.execute(text("SELECT value FROM system_settings WHERE key = 'tencent_voice_key'"))
            row = result.fetchone()

            if not row:
                print("❌ No tencent_voice_key found in system_settings")
                return

            value = row[0]
            print(f"✅ Found tencent_voice_key in system_settings")
            print(f"   Secret ID: {value.get('secret_id', '')[:10]}...")
            print(f"   Secret Key: {value.get('secret_key', '')[:10]}...")

            # 2. 写入到熊团出击租户
            import json

            await db.execute(
                text(
                    """
                INSERT INTO tenant_settings (tenant_id, key, value)
                VALUES (:tenant_id, 'tencent_voice_key', :value)
                ON CONFLICT (tenant_id, key) DO UPDATE SET value = :value
                """
                ),
                {"tenant_id": TENANT_ID_XIONG_TUAN, "value": json.dumps(value)},
            )

            print(f"✅ Migrated to tenant_settings for tenant {TENANT_ID_XIONG_TUAN}")

            # 3. 删除系统级配置
            await db.execute(text("DELETE FROM system_settings WHERE key = 'tencent_voice_key'"))
            await db.commit()

            print("✅ Deleted tencent_voice_key from system_settings")
            print("\n🎉 Migration completed successfully!")

        except Exception as e:
            await db.rollback()
            print(f"❌ Migration failed: {e}")
            raise


if __name__ == "__main__":
    print("=" * 60)
    print("Migrating tencent_voice_key from system_settings to tenant_settings")
    print("=" * 60)
    asyncio.run(migrate_tencent_voice_key())
