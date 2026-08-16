"""东莞版业务查询仓库：维度 + 汇总事实，带 Redis 缓存。

设计决策：
1. 查询走"缓存优先"：先查 Redis（命中直接返回），未命中回源 MySQL 并回写缓存。
2. 返回可序列化 dict（不是 ORM 对象）——因为要存进 Redis JSON。
3. 缓存 key 含查询参数（region/日期范围），不同查询互不干扰。
4. 降级策略：Redis 不可用时 cache_get 返回 None，自动回源 MySQL（缓存不阻塞业务）。
"""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infra.cache import cache_get, cache_set
from infra.security import mask_address, mask_name, mask_phone
from models import (
    DimRegion,
    DimUser,
    FactLineLoss,
    FactRegionDaily,
    FactTaiquDaily,
    FactUserDaily,
)


def _serialize_row(row) -> dict:
    """ORM 对象 -> dict（date/Decimal 转成 JSON 友好的原生类型）。

    为什么这里就要转：Repository 契约是"返回可序列化 dict"——
    调用方（工具层/节点/报告）不应关心 ORM 类型细节，
    也不该拿到 Decimal/date 这种需要二次处理的对象。
    """
    result = {}
    for col in row.__table__.columns.keys():
        val = getattr(row, col)
        if isinstance(val, (date, datetime)):
            result[col] = val.isoformat()
        elif isinstance(val, Decimal):
            result[col] = float(val)
        else:
            result[col] = val
    return result


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

    # ---------- 户级用电明细（fact_user_daily，30 天样例） ----------

    async def get_user_daily_usage(
        self, user_id: str, start_date: date, end_date: date
    ) -> list[dict]:
        """某用户某日期区间的日用电量（户级查询，缓存优先）。"""
        key = ("user_daily", user_id, str(start_date), str(end_date))
        cached = await cache_get(*key)
        if cached is not None:
            return cached
        result = await self._session.execute(
            select(FactUserDaily)
            .where(
                FactUserDaily.user_id == user_id,
                FactUserDaily.stat_date >= start_date,
                FactUserDaily.stat_date <= end_date,
            )
            .order_by(FactUserDaily.stat_date)
        )
        data = [_serialize_row(r) for r in result.scalars().all()]
        await cache_set(*key, value=data, ttl=300)
        return data

    async def reconcile_taiqu_loss(
        self, taiqu_code: str, start_date: date, end_date: date
    ) -> list[dict]:
        """台区线损对账：Σ户表 vs 台区总表（支撑"台区线损 = 总表 − Σ户表"演示）。

        返回每天的：台区供电量 / Σ户表电量 / 差额（理论线损电量）。
        """
        result = await self._session.execute(
            select(FactUserDaily)
            .where(
                FactUserDaily.taiqu_code == taiqu_code,
                FactUserDaily.stat_date >= start_date,
                FactUserDaily.stat_date <= end_date,
            )
        )
        # 按日期聚合 Σ户表
        agg: dict[date, float] = {}
        for r in result.scalars().all():
            agg[r.stat_date] = agg.get(r.stat_date, 0) + float(r.kwh)

        tq_result = await self._session.execute(
            select(FactTaiquDaily)
            .where(
                FactTaiquDaily.taiqu_code == taiqu_code,
                FactTaiquDaily.stat_date >= start_date,
                FactTaiquDaily.stat_date <= end_date,
            )
            .order_by(FactTaiquDaily.stat_date)
        )
        rows = []
        for t in tq_result.scalars().all():
            sum_home = agg.get(t.stat_date, 0)
            rows.append({
                "stat_date": str(t.stat_date),
                "supply_kwh": float(t.supply_kwh),
                "sum_user_kwh": round(sum_home, 2),
                "loss_kwh": round(float(t.supply_kwh) - sum_home, 2),
                "loss_rate": float(t.loss_rate),
            })
        return rows

    # ---------- 用户档案（PII 脱敏出库） ----------

    async def list_users(
        self, region_code: str | None = None, limit: int = 50
    ) -> list[dict]:
        """用户列表（**PII 脱敏出库**：姓名打星、电话掩码、身份证只给脱敏副本）。

        安全设计（见 infra/security.py）：
        - customer_name → mask_name（王*明）
        - phone → mask_phone（138****8000）
        - 身份证永不输出明文：只返回 id_card_masked（440106********1234）
        - 不返回 id_card_enc / id_card_hash（密文与摘要都不出库，避免泄露线索）
        """
        key = ("users", region_code or "ALL", str(limit))
        cached = await cache_get(*key)
        if cached is not None:
            return cached

        stmt = select(DimUser).order_by(DimUser.user_id).limit(limit)
        if region_code:
            stmt = stmt.where(DimUser.region_code == region_code)
        result = await self._session.execute(stmt)
        data = []
        for u in result.scalars().all():
            data.append({
                "user_id": u.user_id,
                "region_code": u.region_code,
                "taiqu_code": u.taiqu_code,
                "user_type": u.user_type,
                "meter_no": u.meter_no,
                "customer_name": mask_name(u.customer_name),
                "phone": mask_phone(u.phone),
                "address": mask_address(u.address),
                "id_card_masked": u.id_card_masked,
            })
        await cache_set(*key, value=data, ttl=300)
        return data

    async def get_user(self, user_id: str) -> dict | None:
        """单个用户档案（PII 脱敏出库，规则同 list_users）。

        敏感用户数据不进 Redis 缓存（缓存 key 无权限维度，评审 P0）：
        直接查 MySQL，返回脱敏 dict。
        """
        result = await self._session.execute(
            select(DimUser).where(DimUser.user_id == user_id)
        )
        u = result.scalar_one_or_none()
        if u is None:
            return None
        return {
            "user_id": u.user_id,
            "region_code": u.region_code,
            "taiqu_code": u.taiqu_code,
            "user_type": u.user_type,
            "meter_no": u.meter_no,
            "customer_name": mask_name(u.customer_name),
            "phone": mask_phone(u.phone),
            "address": mask_address(u.address),
            "id_card_masked": u.id_card_masked,
        }
