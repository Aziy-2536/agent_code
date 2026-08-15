"""电力业务数据查询（Agent 查数入口）。

设计决策：
1. 只读查询：本层不提供写方法，写操作走 ingestion/seed 流程——从机制上保证
   Agent 只能查数不能改数（配合 PolicyGuard 的 SQL 只读策略）。
2. 查询参数来自业务语义（区域、日期范围、阈值），不暴露裸 SQL。
"""
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import LineLossDetail, RegionDailyMetric


class PowerRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ---------- 区域日度指标 ----------
    async def list_region_metrics(
        self,
        region: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        limit: int = 100,
    ) -> list[RegionDailyMetric]:
        """按区域/日期范围查询日度指标（支持"近30天某区域线损"类问题）。"""
        stmt = select(RegionDailyMetric).order_by(RegionDailyMetric.stat_date.desc())
        if region:
            stmt = stmt.where(RegionDailyMetric.region == region)
        if start_date:
            stmt = stmt.where(RegionDailyMetric.stat_date >= start_date)
        if end_date:
            stmt = stmt.where(RegionDailyMetric.stat_date <= end_date)
        stmt = stmt.limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_region_metrics(
        self, region: str, start_date: date, end_date: date
    ) -> list[RegionDailyMetric]:
        """便捷方法：某区域某日期区间，升序返回（趋势分析用）。"""
        result = await self._session.execute(
            select(RegionDailyMetric)
            .where(
                RegionDailyMetric.region == region,
                RegionDailyMetric.stat_date >= start_date,
                RegionDailyMetric.stat_date <= end_date,
            )
            .order_by(RegionDailyMetric.stat_date)
        )
        return list(result.scalars().all())

    # ---------- 线损明细 ----------
    async def list_high_loss_lines(
        self,
        loss_rate_threshold: float,
        region: str | None = None,
        stat_date: date | None = None,
        limit: int = 50,
    ) -> list[LineLossDetail]:
        """查询线损率超过阈值的线路（"找出高损线路"类问题）。"""
        stmt = (
            select(LineLossDetail)
            .where(LineLossDetail.loss_rate >= loss_rate_threshold)
            .order_by(LineLossDetail.loss_rate.desc())
            .limit(limit)
        )
        if region:
            stmt = stmt.where(LineLossDetail.region == region)
        if stat_date:
            stmt = stmt.where(LineLossDetail.stat_date == stat_date)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
