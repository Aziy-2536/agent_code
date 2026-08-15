"""Redis 异步客户端（redis-py 5.x 的 redis.asyncio）。

设计决策：
1. redis.asyncio 客户端自带连接池，from_url 创建后全局复用。
2. decode_responses=True：默认返回 bytes，开了直接拿 str，省一步 decode。
3. 懒初始化 + 显式 close：模块级单例，应用关闭时释放。
"""
import redis.asyncio as aioredis

from config.settings import get_settings

_client: aioredis.Redis | None = None   # 模块级变量存单例（redis 不用 lru_cache 的写法）


def get_redis() -> aioredis.Redis:
    """获取全局复用的异步 Redis 客户端（懒初始化单例）。"""
    global _client
    if _client is None:
        _client = aioredis.from_url(
            get_settings().redis_url,    # 地址从配置拿
            encoding="utf-8",
            decode_responses=True,       # 自动 str 解码
        )
    return _client


async def close_redis() -> None:
    """应用关闭时释放 Redis 连接。"""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None