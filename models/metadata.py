"""元数据知识库模型（业务域 → power_insight 库）。

设计决策（问数 Agent 的前提底座）：
1. 四类元数据：表信息 / 字段信息 / 字段取值 / 指标信息（指标复用 metric_definitions）。
2. 结构化保存 + 后续向量化（二期 Milvus）实现"先理解上下文，再动手查询"。
3. meta_values 存"枚举值语义"：LLM 识别"虎门镇"→ region_code=DG012 靠它。
4. 元数据是业务语义描述，人工录入（seed），不靠 AI 生成。
"""
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from models.base import BusinessBase


class MetaTable(BusinessBase):
    """表元数据：业务表信息（找该查哪些表）。"""

    __tablename__ = "meta_tables"

    table_name: Mapped[str] = mapped_column(String(64), primary_key=True)   # 表名
    table_desc: Mapped[str] = mapped_column(Text, default="")               # 业务用途说明
    table_layer: Mapped[str] = mapped_column(String(16), default="")        # 维度/汇总/明细/知识
    primary_key: Mapped[str] = mapped_column(String(128), default="")       # 主键
    related_tables: Mapped[str] = mapped_column(Text, default="")           # 关联表（逗号分隔）
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class MetaField(BusinessBase):
    """字段元数据：字段信息（理解字段业务含义与建模角色）。"""

    __tablename__ = "meta_fields"
    # P0 前置（增量 upsert 防重复）：同一张表的同一字段只允许一条元数据。
    # 增量同步（sync_meta.py）按 (table_name, field_name) upsert，无唯一键会重复插入。
    __table_args__ = (
        UniqueConstraint("table_name", "field_name", name="uq_meta_fields_table_field"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    table_name: Mapped[str] = mapped_column(String(64), index=True)
    field_name: Mapped[str] = mapped_column(String(64))
    field_desc: Mapped[str] = mapped_column(Text, default="")               # 业务含义
    field_type: Mapped[str] = mapped_column(String(32), default="")         # varchar/decimal/date
    role: Mapped[str] = mapped_column(String(16), default="")               # 维度/度量/时间/主键
    is_filter: Mapped[int] = mapped_column(Integer, default=0)              # 1=可用于过滤
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class MetaValue(BusinessBase):
    """字段取值字典：枚举值语义（识别用户提到的字段取值）。"""

    __tablename__ = "meta_values"
    # P0 前置：同一字段的同一显示值只允许映射一个编码（"虎门镇"→DG012 必须唯一）。
    # 增量同步按 (field_name, value) upsert，无唯一键会重复插入。
    __table_args__ = (
        UniqueConstraint("field_name", "value", name="uq_meta_values_field_value"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    table_name: Mapped[str] = mapped_column(String(64), default="")
    field_name: Mapped[str] = mapped_column(String(64), index=True)         # region_code
    code: Mapped[str] = mapped_column(String(32))                           # DG012
    value: Mapped[str] = mapped_column(String(64))                          # 虎门镇
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
