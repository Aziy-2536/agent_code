"""FastAPI 依赖注入：请求级 AsyncSession。

设计决策：
1. 每个请求一个 AsyncSession（事务边界 = 请求边界），用完自动关闭/回滚。
2. 路由函数通过 Depends(get_db) 拿 session，再传给 Repository——
   Repository 不自己创建 session（与 repositories/ 的设计约定一致）。
"""
# AsyncIterator：异步生成器类型（get_db 用 yield，属于异步生成器）
from typing import AsyncIterator

# AsyncSession：异步会话类型（类型注解用）
from sqlalchemy.ext.asyncio import AsyncSession

# get_session_maker：从 db/ 层拿"会话工厂"（连 MySQL 连接池的入口）
from db import get_session_maker


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI 依赖：产出请求级 Session。

    用法：async def xxx(db: AsyncSession = Depends(get_db)):
    """
    # async with：进入时创建 session，退出时自动 close
    #   - 请求正常结束 → session 关闭（Repository 内部已 commit）
    #   - 请求抛异常 → session 关闭并 rollback（不提交半截数据）
    # 为什么 yield 而不是 return：
    #   依赖注入的"产出"必须是生成器——yield 之后的部分
    #   会在请求处理完（响应返回后）才执行，正好用于收尾关闭
    async with get_session_maker()() as session:
        yield session
