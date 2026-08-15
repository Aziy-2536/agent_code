"""MySQL 异步连接管理（SQLAlchemy 2.0 async + asyncmy）。

设计决策：
1. Engine 管连接池，Session 管工作单元——职责分离。
2. 懒初始化（lru_cache）：首次调用才建 engine，import 不连接。
3. expire_on_commit=False：async 下 commit 后再访问属性会触发隐式 IO 抛错。
4. 参数全部来自 get_settings()，不硬编码。
"""
# annotations：类型注解延迟求值（async_sessionmaker[AsyncSession] 这种写法需要）
from __future__ import annotations
from functools import lru_cache
#SQLAlchemy 2.0 异步三件套：
#   AsyncEngine     = 异步引擎（连接池）
#   AsyncSession    = 异步会话（工作单元）
#   async_sessionmaker = 会话工厂（生产 AsyncSession 的"模板"）
#   create_async_engine = 创建异步引擎的函数

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
        settings.mysql_dsn,                      # 连接串：从配置拿
        pool_size=settings.mysql_pool_size,      # 池大小：从配置拿
        max_overflow=settings.mysql_max_overflow, # 池满后临时扩展数
        pool_recycle=3600,                       # 连接超 1 小时强制回收，防止 MySQL 侧断连后用坏连接
        echo=settings.mysql_echo,                # 调试时打印 SQL
    )


@lru_cache(maxsize=1)
def get_session_maker() -> async_sessionmaker[AsyncSession]:
    """创建（或复用）异步 Session 工厂。"""
    return async_sessionmaker(
        get_engine(),                            # 用上面的连接池
        class_=AsyncSession,                     # 指定会话类型（异步）
        expire_on_commit=False,                  # 关键！提交后不自动过期，避免异步隐式 IO
    )


async def dispose_engine() -> None:
    """应用关闭时释放连接池（FastAPI shutdown 事件里调用）。"""
    engine = get_engine()
    await engine.dispose()
    get_engine.cache_clear()                     # 清缓存，允许下次重建
    get_session_maker.cache_clear()