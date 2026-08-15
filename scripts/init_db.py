"""初始化数据库：按域分别在两个库建表。

用法：
    python scripts/init_db.py            # 建表（已存在的表自动跳过）
    python scripts/init_db.py --drop     # 先删表再重建（危险操作，仅本地开发）

双库设计：
    agent 库          ← AgentBase（任务域 + 记忆域）
    power_insight 库  ← BusinessBase（业务域 + 知识域）

设计决策：
1. 第一版用 MetaData.create_all（幂等，只建不存在的表），
   生产环境后续应引入 Alembic 做迁移管理——create_all 无法改已存在的表。
2. 连接参数全部来自 get_settings()，与 .env 保持一致。
"""
import argparse
import asyncio
import sys
from pathlib import Path

# 允许从仓库根目录直接运行脚本（python scripts/init_db.py 时能找到项目模块）
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from config.settings import get_settings  # noqa: E402
from models import AgentBase, BusinessBase  # noqa: E402


async def _init_one(engine, base, drop_first: bool) -> None:
    """对单个库执行建表（或删表重建）。"""
    if drop_first:
        # 先关外键检查再删表，避免约束报错
        async with engine.begin() as conn:
            await conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
            await conn.run_sync(base.metadata.drop_all)
            await conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
        print(f"[init_db] {engine.url.database}: dropped all tables")
    async with engine.begin() as conn:
        # run_sync：把同步的 create_all 包进 async 连接上下文
        await conn.run_sync(base.metadata.create_all)
    tables = sorted(base.metadata.tables.keys())
    print(f"[init_db] {engine.url.database}: created/verified tables ({len(tables)}):")
    for t in tables:
        print(f"  - {t}")


async def init_db(drop_first: bool = False) -> None:
    settings = get_settings()
    # 双库双引擎：agent 库（AgentBase）+ power_insight 库（BusinessBase）
    agent_engine = create_async_engine(settings.mysql_agent_dsn)
    business_engine = create_async_engine(settings.mysql_dsn)
    await _init_one(agent_engine, AgentBase, drop_first)
    await _init_one(business_engine, BusinessBase, drop_first)
    # 释放连接池（脚本是一次性程序，跑完断开）
    await agent_engine.dispose()
    await business_engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="初始化数据库（agent + power_insight 双库）")
    parser.add_argument("--drop", action="store_true", help="先删除已有表再重建（仅本地开发）")
    args = parser.parse_args()
    asyncio.run(init_db(drop_first=args.drop))


if __name__ == "__main__":
    main()
