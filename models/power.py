"""电力业务持久化模型（第一版模拟数据表）。

设计决策：
- 按"区域 + 日期"为粒度：支撑按区域/日期聚合的典型分析问题。
- 金额与电量用 Decimal（Numeric），避免浮点误差。
"""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Date, DateTime, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from models.base import BusinessBase   # ← 关键：从 task.py 导入公共 Base


class RegionDailyMetric(BusinessBase):
    """区域日度营销指标：供电量、售电量、线损等。"""

    __tablename__ = "region_daily_metrics"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    region: Mapped[str] = mapped_column(String(64), index=True)
    stat_date: Mapped[date] = mapped_column(Date, index=True)
    supply_kwh: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)   # 供电量(度)
    sale_kwh: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)     # 售电量(度)
    line_loss_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)  # 线损率
    collection_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)  # 回收率
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class LineLossDetail(BusinessBase):
    """线路日线损明细：支撑"找出高损线路/台区"类问题。"""

    __tablename__ = "line_loss_details"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    region: Mapped[str] = mapped_column(String(64), index=True)
    line_code: Mapped[str] = mapped_column(String(64), index=True)   # 线路编号
    line_name: Mapped[str] = mapped_column(String(128))
    stat_date: Mapped[date] = mapped_column(Date, index=True)
    supply_kwh: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)
    sale_kwh: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)
    loss_kwh: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)   # 损失电量
    loss_rate: Mapped[Decimal] = mapped_column(Numeric(10, 6), default=0)  # 线损率
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
