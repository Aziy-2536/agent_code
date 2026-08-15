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

# 允许从仓库根目录直接运行脚本（python scripts/init_db.py 时能找到项目模块）
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from db import get_engine  # noqa: E402
from models import Base  # noqa: E402


async def init_db(drop_first: bool = False) -> None:
    engine = get_engine()
    if drop_first:
        # 先关外键检查再删表，避免约束报错
        async with engine.begin() as conn:
    # engine.begin() = 开启一个"事务"（begin + 自动 commit）
    # 为什么用 begin() 不用 connect()：begin() 结束时自动提交；
    # 删除操作要么全成功要么全失败（事务保证），不会删一半留下烂摊子

    # ---- 第 1 行：关掉外键检查 ----
            await conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
    # 外键：表与表之间的"引用约束"（如 task_steps.task_id 引用 analysis_tasks.task_id）
    # 正常删表时，MySQL 会检查"有没有别的表引用它"，有引用就拒绝删除
    # 但我们想"全删掉"，所以先关检查：= 0 表示"暂时不查引用，放行删除"
    # 如果不关：删 analysis_tasks 时，task_steps 还引用着它 → 报错删不掉

    # ---- 第 2 行：真正删掉所有表 ----
            await conn.run_sync(Base.metadata.drop_all)
    # drop_all = create_all 的反操作：把 models 里定义的所有表都 DROP 掉
    # run_sync()：async 连接里跑同步方法（drop_all 是同步的），
    #   包一层让它在 greenlet 上下文执行（之前踩过的 async 坑）
    # 为什么按 models 删：models 里有什么表就删什么表（8 张全删）

    # ---- 第 3 行：重新打开外键检查 ----
            await conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
    # 删完后必须恢复 = 1（默认值）
    # 如果不恢复：之后的所有操作都不检查外键 → 脏数据能混进去，
    #   而且可能影响其他连接——这是全局会话设置，必须还回去

    # 到这里 engine.begin() 的事务自动 commit：
    #   SET 0 → DROP 全部 → SET 1，三条语句作为一个事务提交
    #   如果中间任何一步失败，整体回滚（外键设置也会回滚）

            print("[init_db] dropped all tables")
# 提示：所有表已删除（控制台输出，方便看执行过程）
    async with engine.begin() as conn:
         # ① 开事务连接（之前讲过：代码块正常结束自动提交，异常自动回滚）
        await conn.run_sync(Base.metadata.create_all)
            # ② 建表：拿着 models 的"户口本"，把不存在的表建出来
    #    （已存在的跳过——所以叫 created/verified）
    # ③ 到这里事务已自动提交，连接归还池子
        
    tables = sorted(Base.metadata.tables.keys())
    # ④ 从 models 拿全部表名，排个序（好看）
#    注意：不是查数据库！是读 models 定义（Base.metadata 这本户口本）
#    → 所以无论表实际建没建，这里都能拿到 8 个名字
    print(f"[init_db] created/verified tables ({len(tables)}):")
    # ⑤ 打印提示：共 8 张表（"created/verified" = 建的建、已存在的验证过）
    
    for t in tables:
        print(f"  - {t}")
     # ⑥ 逐个打印表名，方便你肉眼确认：analysis_reports、analysis_tasks...
    await engine.dispose()
    # ⑦ 释放连接池（应用级收尾）
#    为什么脚本要 dispose：脚本是一次性程序，跑完就该把数据库连接全断开，
#    让进程干净退出；不释放的话连接会挂着直到进程结束


def main() -> None:
    parser = argparse.ArgumentParser(description="初始化本地 MySQL 数据库")
     # ① 创建一个"命令行参数解析器"（argparse 是 Python 标准库）
    #    description：脚本的帮助说明——运行时 `python scripts/init_db.py --help` 会显示它
    parser.add_argument("--drop", action="store_true", help="先删除已有表再重建（仅本地开发）")
        # ② 定义这个脚本支持的参数：--drop
    #    action="store_true"：这是个"开关"参数
    #      - 命令行写了 --drop  → args.drop = True
    #      - 命令行没写 --drop  → args.drop = False
    #    help：--help 时显示的说明文字
    args = parser.parse_args()
    # ③ 真正去"读"命令行写了什么
    #    运行 `python scripts/init_db.py`        → args.drop = False
    #    运行 `python scripts/init_db.py --drop` → args.drop = True
    asyncio.run(init_db(drop_first=args.drop))
    # ④ 调用核心函数，把"是否删表"的决定传进去
    #    asyncio.run()：启动异步事件循环，运行 async 函数 init_db
    #    （init_db 是 async def，不能直接调用，必须用 asyncio.run 包一层）
    #    drop_first=args.drop：--drop 传了 True 就删表重建，没传就只建表

if __name__ == "__main__":
    main()