"""初始化数据库：基于 models 定义建表。

用法：
    python scripts/init_db.py            # 建表（已存在的表自动跳过）
    python scripts/init_db.py --drop     # 先删表再重建（危险操作，仅本地开发）

设计决策：
1. 第一版用 MetaData.create_all（幂等，只建不存在的表），
   生产环境后续应引入 Alembic 做迁移管理——create_all 无法改已存在的表。
2. 连接参数全部来自 get_settings()，与 .env 保持一致。
"""
import argparse
import asyncio
import sys
from pathlib import Path

# 允许从仓库根目录直接运行脚本
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from db import get_engine  # noqa: E402
from models import Base  # noqa: E402


async def init_db(drop_first: bool = False) -> None:
    engine = get_engine()
    if drop_first:
        # 按依赖倒序删表（先删子表再删主表），避免外键约束报错
        async with engine.begin() as conn:
            await conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
            await conn.run_sync(Base.metadata.drop_all)
            await conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
        print("[init_db] dropped all tables")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    tables = sorted(Base.metadata.tables.keys())
    print(f"[init_db] created/verified tables ({len(tables)}):")
    for t in tables:
        print(f"  - {t}")
    await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="初始化本地 MySQL 数据库")
    parser.add_argument("--drop", action="store_true", help="先删除已有表再重建（仅本地开发）")
    args = parser.parse_args()
    asyncio.run(init_db(drop_first=args.drop))


if __name__ == "__main__":
    main()
