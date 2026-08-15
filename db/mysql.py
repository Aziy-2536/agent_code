"""MySQL 异步连接模板（SQLAlchemy 2.0 async + asyncmy）。

设计决策：
1. Engine 管"连接池"，Session 管"工作单元"——两者职责不同，分开创建。
2. 懒初始化（lru_cache）：首次调用才建 engine，避免 import 时因 MySQL 未启动而崩溃；
   同时天然保证进程内单例（重复调用返回同一个 engine）。
3. expire_on_commit=False：async 场景下 commit 后再访问对象属性会触发隐式 IO，
   在异步里会抛异常，必须关掉。
4. 所有参数来自 get_settings()，不硬编码主机/端口/密码。
"""
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from config.settings import get_settings


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    """创建（或复用）异步引擎连接池。"""
    settings = get_settings()
    return create_async_engine(
        settings.mysql_dsn,
        pool_size=settings.mysql_pool_size,
        max_overflow=settings.mysql_max_overflow,
        pool_recycle=3600,  # 连接超过 1 小时强制回收，防止 MySQL 侧断连后复用坏连接
        echo=settings.mysql_echo,
    )


@lru_cache(maxsize=1)
def get_session_maker() -> async_sessionmaker[AsyncSession]:
    """创建（或复用）异步 Session 工厂。"""
    return async_sessionmaker(
        get_engine(),
        class_=AsyncSession,
        expire_on_commit=False,
    )


async def dispose_engine() -> None:
    """应用关闭时释放连接池（FastAPI shutdown 事件里调用）。"""
    engine = get_engine()
    await engine.dispose()
    get_engine.cache_clear()
    get_session_maker.cache_clear()
