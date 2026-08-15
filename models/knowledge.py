"""指标口径与知识元数据模型。

设计决策：
- metric_definitions 是指标字典：口径、公式、单位、来源统一登记。
  RAG 检索它的描述文本，domain 层按 code 执行公式，两者通过 code 对齐。
"""
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from models.task import Base


class MetricDefinition(Base):
    """标准指标定义：口径与公式的唯一事实来源。"""

    __tablename__ = "metric_definitions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)  # 如 line_loss_rate
    name: Mapped[str] = mapped_column(String(64))  # 如 线损率
    category: Mapped[str] = mapped_column(String(32), default="general")
    formula: Mapped[str] = mapped_column(Text, default="")  # 计算口径描述
    unit: Mapped[str] = mapped_column(String(16), default="")  # % / kWh / 元
    description: Mapped[str] = mapped_column(Text, default="")  # RAG 检索文本
    source: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())