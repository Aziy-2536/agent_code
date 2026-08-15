"""Redis 缓存封装：查询缓存 + 序列化。

设计决策：
1. 缓存 key 规范：{redis_key_prefix}:cache:{业务前缀}:{参数指纹}
   （如 power:cache:region_loss:DG012:2026-08-15）
2. 只缓存"可序列化"的结果（JSON），不缓存 ORM 对象——避免 session 关联问题。
3. 统一 TTL（过期自动刷新），防止脏数据长期驻留。
4. 缓存不可用时降级：Redis 挂了直接回源 MySQL，不让缓存成为单点。
"""
import json

from db import get_redis
from config.settings import get_settings

_settings = get_settings()


def _key(*parts: str) -> str:
    """拼缓存 key：prefix + 分段。"""
    return ":".join([_settings.redis_key_prefix, "cache", *parts])


async def cache_get(*parts: str) -> object | None:
    """读缓存：命中返回解析后的对象，未命中/异常返回 None。"""
    try:
        r = get_redis()
        raw = await r.get(_key(*parts))
        if raw is None:
            return None
        return json.loads(raw)
    except Exception:
        # 缓存不可用（Redis 挂了/序列化失败）：降级为未命中，回源 MySQL
        return None


async def cache_set(*parts: str, value: object, ttl: int = 300) -> None:
    """写缓存：JSON 序列化 + TTL。失败静默（缓存写失败不影响业务）。"""
    try:
        r = get_redis()
        await r.set(_key(*parts), json.dumps(value, ensure_ascii=False, default=str), ex=ttl)
    except Exception:
        pass  # 写缓存失败不影响主流程


async def cache_del(*parts: str) -> None:
    """删缓存（数据变更后调用，防止读到旧值）。"""
    try:
        r = get_redis()
        await r.delete(_key(*parts))
    except Exception:
        pass
