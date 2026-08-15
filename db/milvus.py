"""Milvus 客户端模板（pymilvus MilvusClient，底层 gRPC）。

设计决策：
1. MilvusClient 是官方推荐的高层客户端，封装了 collection 增删改查，
   相比直接操作 Connections 更简单。
2. 懒初始化（lru_cache）：Milvus 未启动时 import 程序不崩，首次调用才连接。
3. 注意：MilvusClient 在 gRPC 模式下创建时会立即建立连接，
   连接失败会抛异常——调用方需自行捕获并给出友好提示。
"""
from functools import lru_cache

from pymilvus import MilvusClient

from config.settings import get_settings


@lru_cache(maxsize=1)
def get_milvus_client() -> MilvusClient:
    """创建（或复用）Milvus 客户端单例。"""
    settings = get_settings()
    return MilvusClient(
        uri=settings.milvus_uri,
        db_name=settings.milvus_db,
    )


def close_milvus_client() -> None:
    """释放 Milvus 客户端连接。"""
    client = get_milvus_client()
    client.close()
    get_milvus_client.cache_clear()
