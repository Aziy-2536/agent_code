"""电力业务数据查询（Agent 查数入口）。

设计决策：
1. 只读查询：本层不提供写方法——从机制上保证 Agent 只能查数不能改数
   （配合 harness 的 SQL 只读策略，双保险）。
2. 查询参数来自业务语义（区域、日期范围、阈值），不暴露裸 SQL——
   调用方（Agent）不需要知道表结构，只需要"给我某区域某区间的指标"。
"""
# date：日期类型（stat_date 字段的类型）
#   注意：是 from datetime import date，不是 datetime！
from datetime import date

# select：SQLAlchemy 查询构造器
from sqlalchemy import select

# AsyncSession：异步会话类型（类型注解用）
from sqlalchemy.ext.asyncio import AsyncSession

# 业务模型：区域日度指标 + 线路线损明细
from models import LineLossDetail, RegionDailyMetric


class PowerRepository:
    """电力业务数据查询仓库（只读）。"""

    def __init__(self, session: AsyncSession) -> None:
        # session 从外部注入（与另外两个 Repository 一致）
        self._session = session

    # ==================== 区域日度指标 ====================

    async def get_region_metrics(
        self, region: str, start_date: date, end_date: date
    ) -> list[RegionDailyMetric]:
        """某区域某日期区间的日度指标，升序返回（趋势分析用）。

        典型问题："分析 A 区域近 30 天线损率走势"
        """
        # SELECT * FROM region_daily_metrics
        # WHERE region = :r AND stat_date BETWEEN :start AND :end
        # ORDER BY stat_date ASC（升序：日期从旧到新，画趋势图方便）
        result = await self._session.execute(
            select(RegionDailyMetric)
            .where(
                RegionDailyMetric.region == region,          # 区域精确匹配
                RegionDailyMetric.stat_date >= start_date,   # 日期下限
                RegionDailyMetric.stat_date <= end_date,     # 日期上限
            )
            .order_by(RegionDailyMetric.stat_date)
        )
        # scalars().all()：结果集转成 RegionDailyMetric 对象列表
        return list(result.scalars().all())

    # ==================== 线损明细 ====================

    async def list_high_loss_lines(
        self,
        loss_rate_threshold: float,      # 线损率阈值（如 0.10 = 10%）
        region: str | None = None,       # 可选：限定区域
        stat_date: date | None = None,   # 可选：限定日期
        limit: int = 50,                 # 最多返回条数
    ) -> list[LineLossDetail]:
        """查询线损率超过阈值的线路（"找出高损线路"类问题）。"""
        # 基础查询：SELECT * FROM line_loss_details WHERE loss_rate >= 阈值
        # 按线损率倒序（最高损的排最前）+ 限量
        stmt = (
            select(LineLossDetail)
            .where(LineLossDetail.loss_rate >= loss_rate_threshold)
            .order_by(LineLossDetail.loss_rate.desc())   # 高损在前
            .limit(limit)
        )
        # 可选条件：region 传了才加 WHERE（SQLAlchemy 会链式拼接条件）
        if region:
            stmt = stmt.where(LineLossDetail.region == region)
        # 可选条件：stat_date 传了才加 WHERE
        if stat_date:
            stmt = stmt.where(LineLossDetail.stat_date == stat_date)
        # 执行查询，转成对象列表
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
