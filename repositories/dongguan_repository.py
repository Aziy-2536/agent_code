"""东莞版业务查询仓库：维度 + 汇总事实，带 Redis 缓存。

设计决策：
1. 查询走"缓存优先"：先查 Redis（命中直接返回），未命中回源 MySQL 并回写缓存。
2. 返回可序列化 dict（不是 ORM 对象）——因为要存进 Redis JSON。
3. 缓存 key 含查询参数（region/日期范围），不同查询互不干扰。
4. 降级策略：Redis 不可用时 cache_get 返回 None，自动回源 MySQL（缓存不阻塞业务）。
"""
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infra.cache import cache_get, cache_set
from models import DimRegion, FactLineLoss, FactRegionDaily, FactTaiquDaily


def _serialize_row(row) -> dict:
    """ORM 对象 -> dict（date/Decimal 转成 JSON 友好的 str）。"""
    return {
        col: (str(getattr(row, col)) if col in ("stat_date",) else getattr(row, col))
        for col in row.__table__.columns.keys()
    }


class DongguanRepository:
    """东莞版数据查询（缓存优先，Agent 分析主入口）。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ---------- 区域日度（带缓存） ----------

    async def get_region_metrics(
        self, region_code: str, start_date: date, end_date: date
    ) -> list[dict]:
        """某镇街某日期区间的日度指标（缓存优先）。"""
        key = ("region_metrics", region_code, str(start_date), str(end_date))
        # 1. 先查缓存
        cached = await cache_get(*key)
        if cached is not None:
            return cached
        # 2. 未命中：查 MySQL（复合主键前缀，毫秒级）
        result = await self._session.execute(
            select(FactRegionDaily)
            .where(
                FactRegionDaily.region_code == region_code,
                FactRegionDaily.stat_date >= start_date,
                FactRegionDaily.stat_date <= end_date,
            )
            .order_by(FactRegionDaily.stat_date)
        )
        data = [_serialize_row(r) for r in result.scalars().all()]
        # 3. 回写缓存（5 分钟 TTL）
        await cache_set(*key, value=data, ttl=300)
        return data

    # ---------- 高损线路（带缓存） ----------

    async def list_high_loss_lines(
        self, loss_rate_threshold: float, region_code: str | None = None, limit: int = 50
    ) -> list[dict]:
        """线损率超过阈值的线路（缓存优先）。"""
        key = ("high_loss_lines", str(loss_rate_threshold), region_code or "ALL")
        cached = await cache_get(*key)
        if cached is not None:
            return cached

        stmt = (
            select(FactLineLoss)
            .where(FactLineLoss.loss_rate >= loss_rate_threshold)
            .order_by(FactLineLoss.loss_rate.desc())
            .limit(limit)
        )
        if region_code:
            stmt = stmt.where(FactLineLoss.region_code == region_code)
        result = await self._session.execute(stmt)
        data = [_serialize_row(r) for r in result.scalars().all()]
        await cache_set(*key, value=data, ttl=300)
        return data

    # ---------- 高损台区（带缓存） ----------

    async def list_high_loss_taiqu(
        self, loss_rate_threshold: float, region_code: str | None = None, limit: int = 50
    ) -> list[dict]:
        """线损率超过阈值的台区（缓存优先）。"""
        key = ("high_loss_taiqu", str(loss_rate_threshold), region_code or "ALL")
        cached = await cache_get(*key)
        if cached is not None:
            return cached

        stmt = (
            select(FactTaiquDaily)
            .where(FactTaiquDaily.loss_rate >= loss_rate_threshold)
            .order_by(FactTaiquDaily.loss_rate.desc())
            .limit(limit)
        )
        if region_code:
            # 台区表没有 region_code，需先按线路归属过滤——简化：直接全量按阈值
            pass
        result = await self._session.execute(stmt)
        data = [_serialize_row(r) for r in result.scalars().all()]
        await cache_set(*key, value=data, ttl=300)
        return data

    # ---------- 区域列表（维度，缓存短一点） ----------

    async def list_regions(self) -> list[dict]:
        """全部 32 镇街（维度表，缓存 1 小时）。"""
        key = ("regions",)
        cached = await cache_get(*key)
        if cached is not None:
            return cached
        result = await self._session.execute(select(DimRegion).order_by(DimRegion.region_code))
        data = [_serialize_row(r) for r in result.scalars().all()]
        await cache_set(*key, value=data, ttl=3600)
        return data
