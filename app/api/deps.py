"""FastAPI 依赖注入：请求级 AsyncSession（双库）。

设计决策：
1. 每个请求一个 AsyncSession（事务边界 = 请求边界），用完自动关闭/回滚。
2. 双库隔离：get_db（agent 库，任务/会话/记忆）+ get_business_db（业务库，东莞数据）。
3. 路由函数通过 Depends(...) 拿 session，再传给 Repository——
   Repository 不自己创建 session（与 repositories/ 的设计约定一致）。
"""
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from db import get_agent_session_maker, get_session_maker


async def get_db() -> AsyncIterator[AsyncSession]:
    """Agent 库依赖：任务/会话/记忆操作（Depends(get_db)）。"""
    # async with 保证：请求结束自动 close 会话；异常自动 rollback
    async with get_agent_session_maker()() as session:
        yield session


async def get_business_db() -> AsyncIterator[AsyncSession]:
    """业务库依赖：东莞数据/指标查询（Depends(get_business_db)）。"""
    async with get_session_maker()() as session:
        yield session
