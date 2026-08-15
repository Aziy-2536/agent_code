"""生成模拟电力数据，方便测试与演示。

用法：
    python scripts/seed_mock_data.py            # 灌入模拟数据（先清空业务表再灌，幂等）

设计决策：
1. 幂等：先清空 3 张业务表（region_daily_metrics / line_loss_details / metric_definitions）
   再插入——重复运行不会产生重复数据。
2. random.seed(42) 固定随机种子：每次生成的数据一样（可复现，便于调试）。
3. 数据设计贴合测试场景：
   - 3 个区域 × 60 天日度指标（线损率 5%~20% 波动，含超阈值）
   - 每条线路近 7 天明细（含高损线路 >10%，方便测"找高损线路"）
   - 指标字典 5 条（RAG 检索和 domain 公式用）
"""
import asyncio
import random
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

# 允许从仓库根目录直接运行脚本
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from db import dispose_engine, get_session_maker  # noqa: E402
from models import LineLossDetail, MetricDefinition, RegionDailyMetric  # noqa: E402

# 固定随机种子：保证每次生成的数据一致（可复现）
random.seed(42)

# 模拟参数
REGIONS = ["A区", "B区", "C区"]      # 3 个区域
DAYS = 60                             # 每个区域 60 天数据
LINES_PER_REGION = 3                  # 每个区域 3 条线路
LOSS_DAYS = 7                         # 线路明细覆盖最近 7 天


def make_metrics() -> list[MetricDefinition]:
    """指标字典：口径/公式/单位/来源（RAG 与 domain 层的对齐依据）。"""
    return [
        MetricDefinition(
            code="line_loss_rate", name="线损率", category="general",
            formula="(1 - 售电量/供电量) * 100", unit="%",
            description="线损率反映线路损耗水平，超过10%视为高损",
            source="营销部",
        ),
        MetricDefinition(
            code="supply_kwh", name="供电量", category="general",
            formula="区域供电总电量", unit="kWh",
            description="一定时间内电网向区域输送的总电量",
            source="营销部",
        ),
        MetricDefinition(
            code="sale_kwh", name="售电量", category="general",
            formula="实际售出的电量", unit="kWh",
            description="用户实际消耗并计费的电量",
            source="营销部",
        ),
        MetricDefinition(
            code="collection_rate", name="电费回收率", category="finance",
            formula="实收电费/应收电费 * 100", unit="%",
            description="电费回收情况指标",
            source="财务部",
        ),
        MetricDefinition(
            code="arrears_rate", name="欠费率", category="finance",
            formula="欠费金额/应收电费 * 100", unit="%",
            description="用户欠费水平指标",
            source="财务部",
        ),
    ]


def make_region_metrics() -> list[RegionDailyMetric]:
    """区域日度指标：供电量随机 8000~12000，线损率 5%~20% 波动。"""
    rows: list[RegionDailyMetric] = []
    today = date.today()
    for region in REGIONS:
        # 每个区域生成连续 DAYS 天
        for i in range(DAYS):
            d = today - timedelta(days=DAYS - 1 - i)   # 从旧到新
            supply = random.randint(8000, 12000)        # 供电量（度）
            loss = random.uniform(0.05, 0.20)           # 线损率 5%~20%
            sale = supply * (1 - loss)                  # 售电量 = 供电量 * (1-线损)
            rows.append(RegionDailyMetric(
                region=region,
                stat_date=d,
                supply_kwh=Decimal(str(supply)),                    # 注意：用 str 转 Decimal，避免浮点误差
                sale_kwh=Decimal(str(round(sale, 2))),
                line_loss_rate=Decimal(str(round(loss, 4))),
            ))
    return rows


def make_line_loss() -> list[LineLossDetail]:
    """线路日线损明细：每个区域 3 条线路近 7 天，含高损线路（>10%）。"""
    rows: list[LineLossDetail] = []
    today = date.today()
    for region in REGIONS:
        for li in range(LINES_PER_REGION):
            line_code = f"{region[0]}N-{100 + li}"          # A区 -> AN-100, AN-101...
            # 第 0 条线路固定高损（>10%），方便测"找高损线路"
            high_loss = li == 0
            for i in range(LOSS_DAYS):
                d = today - timedelta(days=LOSS_DAYS - 1 - i)
                supply = random.randint(4000, 7000)
                # 高损线路线损率 12%~18%，普通线路 3%~8%
                loss = random.uniform(0.12, 0.18) if high_loss else random.uniform(0.03, 0.08)
                sale = supply * (1 - loss)
                rows.append(LineLossDetail(
                    region=region,
                    line_code=line_code,
                    line_name=f"{region}{li + 1}号线",
                    stat_date=d,
                    supply_kwh=Decimal(str(supply)),
                    sale_kwh=Decimal(str(round(sale, 2))),
                    loss_kwh=Decimal(str(round(supply * loss, 2))),   # 损失电量
                    loss_rate=Decimal(str(round(loss, 4))),
                ))
    return rows


async def seed() -> None:
    """主流程：清空业务表 -> 插入模拟数据。"""
    factory = get_session_maker()
    async with factory() as session:
        # ---- 第 1 步：清空 3 张业务表（保证幂等，重复跑不产生重复数据） ----
        await session.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
        for model in (RegionDailyMetric, LineLossDetail, MetricDefinition):
            await session.execute(text(f"DELETE FROM {model.__tablename__}"))
        await session.execute(text("SET FOREIGN_KEY_CHECKS = 1"))

        # ---- 第 2 步：插入指标字典 ----
        session.add_all(make_metrics())

        # ---- 第 3 步：插入区域日度指标 ----
        region_rows = make_region_metrics()
        session.add_all(region_rows)

        # ---- 第 4 步：插入线路明细 ----
        line_rows = make_line_loss()
        session.add_all(line_rows)

        # ---- 第 5 步：一次性提交 ----
        await session.commit()

        # ---- 第 6 步：统计并打印 ----
        from sqlalchemy import func, select

        for model, label in (
            (MetricDefinition, "指标字典"),
            (RegionDailyMetric, "区域日度指标"),
            (LineLossDetail, "线路明细"),
        ):
            cnt = (await session.execute(select(func.count()).select_from(model))).scalar()
            print(f"  {label}: {cnt} 条")

    await dispose_engine()
    print("[seed] 模拟数据灌入完成")


if __name__ == "__main__":
    asyncio.run(seed())
