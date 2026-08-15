"""模型基类：按"域"划分两个 Base（双库物理隔离）。

设计决策（双库方案）：
- AgentBase    → agent 库：任务域（task.py）+ 记忆域（memory.py）
- BusinessBase → power_insight 库：业务域（dongguan.py）+ 知识域（knowledge.py）+ 旧表（power.py）

为什么两个 Base：SQLAlchemy 中一张表属于哪个库由"建表时用的引擎 DSN"决定，
而 create_all 只建"该 Base 的 metadata 上注册的表"——所以按域拆两个 Base，
各自 create_all 到各自库，实现物理隔离。
"""
from sqlalchemy.orm import DeclarativeBase


class AgentBase(DeclarativeBase):
    """Agent 域基类：任务/会话/记忆 → agent 库。"""


class BusinessBase(DeclarativeBase):
    """业务域基类：东莞数据/指标字典 → power_insight 库。"""
