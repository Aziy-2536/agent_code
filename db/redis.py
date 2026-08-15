"""Redis 异步客户端模板（redis-py 5.x 的 redis.asyncio）。

设计决策：
1. redis-py 的 asyncio 客户端自带连接池，from_url 创建的客户端可全局复用，
   不需要自己管理连接池。
2. decode_responses=True：默认返回 bytes，开了之后直接返回 str，业务代码少一步 decode。
3. 懒初始化 + 显式 close：模块级单例，应用关闭时释放。
"""
import redis.asyncio as aioredis

from config.settings import get_settings

_client: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    """获取全局复用的异步 Redis 客户端（懒初始化单例）。"""
    global _client
    if _client is None:
        _client = aioredis.from_url(
            get_settings().redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
    return _client


async def close_redis() -> None:
    """应用关闭时释放 Redis 连接（FastAPI shutdown 事件里调用）。"""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
