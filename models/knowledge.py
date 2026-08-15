"""指标口径与知识元数据模型。

设计决策：
- metric_definitions 是"指标字典"：口径、公式、单位、来源统一登记。
  RAG 检索它的文本描述，domain 层按 code 执行公式，两者通过 code 对齐，
  保证"知识里说的口径"和"代码算的口径"一致。
"""
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from models.task import Base


class MetricDefinition(Base):
    """标准指标定义：口径与公式的唯一事实来源。"""

    __tablename__ = "metric_definitions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)  # 指标编码，如 line_loss_rate
    name: Mapped[str] = mapped_column(String(64))  # 指标名称，如 线损率
    category: Mapped[str] = mapped_column(String(32), default="general")  # general / anomaly / finance
    formula: Mapped[str] = mapped_column(Text, default="")  # 计算口径描述
    unit: Mapped[str] = mapped_column(String(16), default="")  # 单位：%、kWh、元 等
    description: Mapped[str] = mapped_column(Text, default="")  # 业务说明（RAG 检索文本）
    source: Mapped[str] = mapped_column(String(64), default="")  # 数据来源/部门
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
