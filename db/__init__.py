"""数据库连接层：统一从这里导入连接入口。"""

# 把各子模块的"公共接口"提到包级别
# 这样外部只需要 from db import xxx，不用关心函数住在哪个文件
from db.milvus import close_milvus_client, get_milvus_client
from db.mysql import (
    dispose_agent_engine,
    dispose_engine,
    get_agent_engine,
    get_agent_session_maker,
    get_engine,
    get_session_maker,
)
from db.redis import close_redis, get_redis

# __all__：声明"from db import *"时导出哪些名字（白名单）
__all__ = [
    # MySQL：业务库（power_insight）
    "get_engine",                # 引擎（连接池）
    "get_session_maker",         # 会话工厂
    "dispose_engine",            # 关闭时释放
    # MySQL：Agent 库（agent）
    "get_agent_engine",
    "get_agent_session_maker",
    "dispose_agent_engine",
    # Redis
    "get_redis",
    "close_redis",
    # Milvus
    "get_milvus_client",
    "close_milvus_client",
]
