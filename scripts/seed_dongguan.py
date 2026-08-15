"""生成东莞版模拟数据：32 镇街 + 线路 + 台区 + 用户 + 汇总事实。

用法：
    python scripts/seed_dongguan.py

设计决策：
1. 幂等：先清空东莞版表再灌（重复运行不产生重复数据）。
2. 结构贴合真实：32 镇街按 6 大片区分组；每镇街若干线路；
   每线路若干台区；用户样例挂到镇街。
3. 数据贴合测试场景：
   - 每个镇街固定 1 条高损线路（>10%），方便测"高损线路"
   - 每个线路固定 1 个高损台区（>12%），方便测"高损台区"
4. 复合主键 (region/line/taiqu, date)：重复运行先 DELETE 保证幂等。
"""
import asyncio
import random
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from db import dispose_engine, get_session_maker  # noqa: E402
from models import (  # noqa: E402
    DimLine,
    DimMeter,
    DimRegion,
    DimTaiqu,
    DimUser,
    FactLineLoss,
    FactRegionDaily,
    FactTaiquDaily,
)

random.seed(2026)  # 固定种子，可复现

DAYS = 60          # 每个事实表覆盖最近 60 天
LINES_PER_REGION = 3   # 每镇街 3 条线路
TAIQU_PER_LINE = 3     # 每线路 3 个台区
USERS_PER_REGION = 10  # 每镇街 10 个样例用户（共 320 户，够演示）

# 东莞 32 镇街（4 街道 + 28 镇，按 6 大片区分组）
REGIONS: list[tuple[str, str]] = [
    # (镇街名, 片区)
    ("莞城街道", "城区片区"), ("南城街道", "城区片区"), ("东城街道", "城区片区"),
    ("万江街道", "城区片区"), ("高埗镇", "城区片区"), ("石碣镇", "城区片区"),
    ("松山湖", "松山湖片区"), ("大朗镇", "松山湖片区"), ("寮步镇", "松山湖片区"),
    ("大岭山镇", "松山湖片区"), ("茶山镇", "松山湖片区"), ("石排镇", "松山湖片区"),
    ("横沥镇", "松山湖片区"), ("东坑镇", "松山湖片区"),
    ("长安镇", "滨海片区"), ("虎门镇", "滨海片区"), ("厚街镇", "滨海片区"),
    ("沙田镇", "滨海片区"), ("道滘镇", "滨海片区"), ("洪梅镇", "滨海片区"),
    ("麻涌镇", "水乡片区"), ("望牛墩镇", "水乡片区"), ("中堂镇", "水乡片区"),
    ("石龙镇", "水乡片区"),
    ("塘厦镇", "东南临深片区"), ("凤岗镇", "东南临深片区"), ("清溪镇", "东南临深片区"),
    ("樟木头镇", "东南临深片区"), ("黄江镇", "东南临深片区"),
    ("常平镇", "东部产业园片区"), ("谢岗镇", "东部产业园片区"), ("桥头镇", "东部产业园片区"),
]
assert len(REGIONS) == 32, f"镇街数量应为 32，实际 {len(REGIONS)}"


def gen_regions() -> list[DimRegion]:
    """32 个镇街，编码 DG001~DG032。"""
    return [
        DimRegion(region_code=f"DG{i + 1:03d}", region_name=name, district=district)
        for i, (name, district) in enumerate(REGIONS)
    ]


def gen_lines(regions: list[DimRegion]) -> list[DimLine]:
    """每镇街 3 条线路，编码 DGxxx-L1/L2/L3。"""
    lines: list[DimLine] = []
    for r in regions:
        for li in range(LINES_PER_REGION):
            lines.append(DimLine(
                line_code=f"{r.region_code}-L{li + 1}",
                region_code=r.region_code,
                line_name=f"{r.region_name}{li + 1}号线路",
                voltage_level="10kV",
            ))
    return lines


def gen_taiqu(lines: list[DimLine]) -> list[DimTaiqu]:
    """每线路 3 个台区，编码 TQ-xxx。"""
    tais: list[DimTaiqu] = []
    for ln in lines:
        for ti in range(TAIQU_PER_LINE):
            tais.append(DimTaiqu(
                taiqu_code=f"TQ-{ln.line_code}-{ti + 1}",
                line_code=ln.line_code,
                region_code=ln.region_code,
                transformer_no=f"TR-{ln.line_code}-{ti + 1}",
                capacity=Decimal(str(random.randint(315, 1000))),
            ))
    return tais


def gen_users(regions: list[DimRegion], tais: list[DimTaiqu]) -> list[DimUser]:
    """每镇街 10 个样例用户（真实 400 万户不模拟，样例够演示关联）。

    评审修订：用户必须归属台区（taiqu_code）——支撑台区线损对账。
    实现：用户轮询分配到本镇街的台区。
    """
    users: list[DimUser] = []
    for r in regions:
        # 本镇街的台区列表（用户轮询挂靠）
        region_tais = [t for t in tais if t.region_code == r.region_code]
        for ui in range(USERS_PER_REGION):
            tq = region_tais[ui % len(region_tais)] if region_tais else None
            users.append(DimUser(
                user_id=f"U-{r.region_code}-{ui + 1:03d}",
                region_code=r.region_code,
                taiqu_code=tq.taiqu_code if tq else "",
                user_type=random.choice(["居民", "居民", "一般工商业"]),
                meter_no=f"M-{r.region_code}-{ui + 1:03d}",
            ))
    return users


def gen_meters(users: list[DimUser]) -> list[DimMeter]:
    """每个用户一台电表（计量点）。评审修订：明细键实体是 meter 不是 user。"""
    meters: list[DimMeter] = []
    for u in users:
        meters.append(DimMeter(
            meter_code=u.meter_no,
            user_id=u.user_id,
            region_code=u.region_code,
            install_date=date.today() - timedelta(days=random.randint(365, 2000)),
            status="ACTIVE",
        ))
    return meters


def gen_region_facts(regions: list[DimRegion]) -> list[FactRegionDaily]:
    """区域日度：线损率 5%~18% 波动（含高损日，方便测异常）。"""
    rows: list[FactRegionDaily] = []
    today = date.today()
    for r in regions:
        for i in range(DAYS):
            d = today - timedelta(days=DAYS - 1 - i)
            supply = random.randint(80_000, 150_000)          # 镇街级供电量
            loss = random.uniform(0.05, 0.18)
            sale = supply * (1 - loss)
            rows.append(FactRegionDaily(
                region_code=r.region_code,
                stat_date=d,
                supply_kwh=Decimal(str(supply)),
                sale_kwh=Decimal(str(round(sale, 2))),
                line_loss_rate=Decimal(str(round(loss, 4))),
                collection_rate=Decimal(str(round(random.uniform(0.90, 0.99), 4))),
            ))
    return rows


def gen_line_facts(lines: list[DimLine]) -> list[FactLineLoss]:
    """线路日度：每镇街第 1 条线路固定高损（12%~18%）。"""
    rows: list[FactLineLoss] = []
    today = date.today()
    for ln in lines:
        high = ln.line_code.endswith("-L1")   # 每个镇街 L1 线是高损
        for i in range(DAYS):
            d = today - timedelta(days=DAYS - 1 - i)
            supply = random.randint(40_000, 80_000)
            loss = random.uniform(0.12, 0.18) if high else random.uniform(0.03, 0.08)
            sale = supply * (1 - loss)
            rows.append(FactLineLoss(
                region_code=ln.region_code,
                line_code=ln.line_code,
                stat_date=d,
                supply_kwh=Decimal(str(supply)),
                sale_kwh=Decimal(str(round(sale, 2))),
                loss_kwh=Decimal(str(round(supply * loss, 2))),
                loss_rate=Decimal(str(round(loss, 4))),
            ))
    return rows


def gen_taiqu_facts(tais: list[DimTaiqu]) -> list[FactTaiquDaily]:
    """台区日度：每线路第 1 个台区固定高损（>12%）。

    评审修订：补 read_flag（少数估抄日）+ collection_rate（台区回收率）。
    """
    rows: list[FactTaiquDaily] = []
    today = date.today()
    for tq in tais:
        high = tq.taiqu_code.endswith("-1")   # 每线路第 1 个台区高损
        for i in range(DAYS):
            d = today - timedelta(days=DAYS - 1 - i)
            supply = random.randint(3_000, 8_000)
            loss = random.uniform(0.12, 0.22) if high else random.uniform(0.03, 0.08)
            sale = supply * (1 - loss)
            # 约 5% 的天是估抄日（read_flag=ESTIMATED），模拟采集异常
            read_flag = "ESTIMATED" if random.random() < 0.05 else "ACTUAL"
            rows.append(FactTaiquDaily(
                taiqu_code=tq.taiqu_code,
                stat_date=d,
                supply_kwh=Decimal(str(supply)),
                sale_kwh=Decimal(str(round(sale, 2))),
                loss_kwh=Decimal(str(round(supply * loss, 2))),
                loss_rate=Decimal(str(round(loss, 4))),
                read_flag=read_flag,
                collection_rate=Decimal(str(round(random.uniform(0.88, 0.99), 4))),
            ))
    return rows


async def seed() -> None:
    """主流程：清空东莞版表 -> 按依赖序插入（维度先、事实后）。"""
    factory = get_session_maker()
    async with factory() as session:
        # ---- 第 1 步：清空（幂等）----
        await session.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
        for model in (FactTaiquDaily, FactLineLoss, FactRegionDaily,
                      DimMeter, DimUser, DimTaiqu, DimLine, DimRegion):
            await session.execute(text(f"DELETE FROM {model.__tablename__}"))
        await session.execute(text("SET FOREIGN_KEY_CHECKS = 1"))

        # ---- 第 2 步：维度（先插，事实表依赖它们的编码）----
        regions = gen_regions()
        lines = gen_lines(regions)
        tais = gen_taiqu(lines)
        users = gen_users(regions, tais)      # 用户挂台区（评审修订）
        meters = gen_meters(users)            # 每用户一个计量点（评审修订）
        session.add_all(regions + lines + tais + users + meters)

        # ---- 第 3 步：汇总事实 ----
        session.add_all(gen_region_facts(regions))
        session.add_all(gen_line_facts(lines))
        session.add_all(gen_taiqu_facts(tais))

        # ---- 第 4 步：一次性提交 ----
        await session.commit()

        # ---- 第 5 步：统计打印 ----
        from sqlalchemy import func, select

        for model, label in (
            (DimRegion, "镇街"), (DimLine, "线路"), (DimTaiqu, "台区"),
            (DimUser, "用户样例"), (DimMeter, "电表"),
            (FactRegionDaily, "区域日度"), (FactLineLoss, "线路日度"),
            (FactTaiquDaily, "台区日度"),
        ):
            cnt = (await session.execute(select(func.count()).select_from(model))).scalar()
            print(f"  {label}: {cnt}")

    await dispose_engine()
    print("[seed_dongguan] 东莞版模拟数据灌入完成")


if __name__ == "__main__":
    asyncio.run(seed())
