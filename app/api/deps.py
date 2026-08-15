"""FastAPI 依赖注入：请求级 AsyncSession。

设计决策：
1. 每个请求一个 AsyncSession（事务边界 = 请求边界），用完自动关闭/回滚。
2. 路由函数通过 Depends(get_db) 拿 session，再传给 Repository——
   Repository 不自己创建 session（与 repositories/ 的设计约定一致）。
"""
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from db import get_session_maker


async def get_db() -> AsyncIterator[AsyncSession]:
    async with get_session_maker()() as session:
        yield session
