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
from infra.security import encrypt_pii, hash_pii, mask_id_card  # noqa: E402
from models import (  # noqa: E402
    DimLine,
    DimMeter,
    DimRegion,
    DimTaiqu,
    DimUser,
    FactLineLoss,
    FactRegionDaily,
    FactTaiquDaily,
    FactUserDaily,
    MetricDefinition,
)

random.seed(2026)  # 固定种子，可复现

DAYS = 60          # 每个事实表覆盖最近 60 天
LINES_PER_REGION = 3   # 每镇街 3 条线路
TAIQU_PER_LINE = 3     # 每线路 3 个台区
USERS_PER_REGION = 100  # 每镇街 100 个样例用户（共 3200 户，关联演示更丰富）
USER_DAYS = 30         # 户日明细只灌最近 30 天（样例级，见 docs/database.md §5.1）

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


# 模拟姓名素材（东莞常见姓 + 名，拼接出 2~3 字名）
_SURNAMES = ["陈", "李", "黄", "张", "梁", "何", "林", "刘", "吴", "罗",
             "王", "周", "邓", "叶", "曾", "谢", "钟", "袁", "苏", "蔡"]
_GIVEN_1 = ["伟", "芳", "娜", "敏", "静", "磊", "军", "洋", "勇", "艳",
            "杰", "娟", "涛", "明", "超", "秀英", "建华", "文静", "志强", "美玲"]

# 模拟地址素材：路名 + 小区名（拼到镇街下）
_ROADS = ["太沙路", "人民路", "振兴路", "富民路", "建设大道", "文明路",
          "长安路", "东兴路", "南湖路", "光明大道"]
_COMMUNITIES = ["幸福小区", "阳光花园", "翠湖湾", "金域华府", "碧桂园",
                "万科城", "时代广场", "御景湾", "恒大名都", "绿地新都会"]


def gen_users(regions: list[DimRegion], tais: list[DimTaiqu]) -> list[DimUser]:
    """每个镇街 USERS_PER_REGION 个样例用户；含模拟 PII（姓名/电话/身份证/地址）。

    评审修订：用户必须归属台区（taiqu_code）——支撑台区线损对账。
    实现：用户轮询分配到本镇街的台区。
    """
    users: list[DimUser] = []
    for r in regions:
        # 本镇街的台区列表（用户轮询挂靠）
        region_tais = [t for t in tais if t.region_code == r.region_code]
        for ui in range(USERS_PER_REGION):
            tq = region_tais[ui % len(region_tais)] if region_tais else None
            user_id = f"U-{r.region_code}-{ui + 1:03d}"
            # ---- 模拟 PII（见 infra/security.py 设计） ----
            name = random.choice(_SURNAMES) + random.choice(_GIVEN_1)
            phone = f"13{random.randint(0, 9)}{random.randint(10000000, 99999999)}"
            birth = date(random.randint(1965, 2005),
                         random.randint(1, 12), random.randint(1, 28))
            id_card = (f"440106{birth:%Y%m%d}"
                       f"{random.randint(0, 9)}{random.randint(0, 9)}"
                       f"{random.randint(0, 9)}{random.choice('0123456789X')}")
            # 用电地址：镇街 + 路 + 门牌号 + 小区 + 栋 + 房号（物理位置，≠电气归属）
            address = (f"广东省东莞市{r.region_name}{random.choice(_ROADS)}"
                       f"{random.randint(1, 200)}号{random.choice(_COMMUNITIES)}"
                       f"{random.randint(1, 8)}栋{random.randint(101, 2601):04d}室")
            users.append(DimUser(
                user_id=user_id,
                region_code=r.region_code,
                taiqu_code=tq.taiqu_code if tq else "",
                user_type=random.choice(["居民", "居民", "一般工商业"]),
                meter_no=f"M-{r.region_code}-{ui + 1:03d}",
                # PII：姓名/电话明文（中敏，出库脱敏）+ 身份证三层（高敏）+ 地址明文（出库脱敏）
                customer_name=name,
                phone=phone,
                address=address,
                id_card_hash=hash_pii(id_card),
                id_card_enc=encrypt_pii(id_card),
                id_card_masked=mask_id_card(id_card),
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


def gen_taiqu_facts(tais: list[DimTaiqu], user_facts: list[FactUserDaily]) -> list[FactTaiquDaily]:
    """台区日度：每线路第 1 个台区固定高损（>12%）。

    严谨性设计（与户表严格自洽，方向正确）：
    - 先有每户自然电量（gen_user_facts），再反推台区总量：
        Σ户表 = 台区售电量（售电量 = 户表抄见电量）
        台区供电量 = Σ户表 / (1 - 台区线损率)      ← 线损率 = (供电-售电)/供电，标准口径
        线损电量 = 供电 - 售电 = Σ户表 × 线损率/(1-线损率)
    - 这样"台区线损 = 总表 − Σ户表"严格成立（偏差≈0），
      且户表曲线是自然的（不被台区随机值拽着走）。

    评审修订：补 read_flag（少数估抄日）+ collection_rate（台区回收率）。
    """
    rows: list[FactTaiquDaily] = []
    today = date.today()
    # Σ户表 per (taiqu_code, stat_date)
    from collections import defaultdict

    sum_home: dict[tuple[str, date], float] = defaultdict(float)
    for uf in user_facts:
        sum_home[(uf.taiqu_code, uf.stat_date)] += float(uf.kwh)

    for tq in tais:
        high = tq.taiqu_code.endswith("-1")   # 每线路第 1 个台区高损
        for i in range(DAYS):
            d = today - timedelta(days=DAYS - 1 - i)
            loss_rate = random.uniform(0.12, 0.22) if high else random.uniform(0.03, 0.08)
            home = sum_home.get((tq.taiqu_code, d), 0.0)
            if home > 0:
                # 户表明细窗口内：由户表反推（严格自洽）
                supply = home / (1 - loss_rate)
                sale = home
            else:
                # 30 天窗口外的历史（户表未覆盖）：随机生成，仅作趋势
                supply = random.randint(3_000, 8_000)
                sale = supply * (1 - loss_rate)
            read_flag = "ESTIMATED" if random.random() < 0.05 else "ACTUAL"
            rows.append(FactTaiquDaily(
                taiqu_code=tq.taiqu_code,
                stat_date=d,
                supply_kwh=Decimal(str(round(supply, 2))),
                sale_kwh=Decimal(str(round(sale, 2))),
                loss_kwh=Decimal(str(round(supply - sale, 2))),
                loss_rate=Decimal(str(round(loss_rate, 4))),
                read_flag=read_flag,
                collection_rate=Decimal(str(round(random.uniform(0.88, 0.99), 4))),
            ))
    return rows


def gen_user_facts(users: list[DimUser]) -> list[FactUserDaily]:
    """户日电量明细：30 天 × 全部用户（样例级，~9.6 万行）。

    严谨性设计（同户逐日用电必须符合真实规律，不能骤变）：
    1. 每户一个"基准日电量"（居民 5~30 度，工商业 30~200 度），
       由用户类型决定——同类型用户量级一致。
    2. 每日电量 = 基准 × 温和波动(0.85~1.15)——同户相邻两天变化 ≤15%，
       不会出现 323→205→155 这种骤降。
    3. 周末效应：居民周末略高(×1.1)，工商业工作日略高(×1.1)——符合用电模式。
    4. 台区总量不在此处决定：先有每户自然电量，再由 gen_taiqu_facts 反推
       台区 supply（对账自洽，且户表曲线不被台区随机值"拽着走"）。
    """
    rows: list[FactUserDaily] = []
    today = date.today()
    for u in users:
        # 每户基准电量（按用户类型，量级固定）
        base = random.uniform(5, 30) if u.user_type == "居民" else random.uniform(30, 200)
        # 每户一个"长期漂移"（模拟季节性缓慢变化），日波动叠加其上
        drift = random.uniform(0.95, 1.05)
        for i in range(USER_DAYS):
            d = today - timedelta(days=USER_DAYS - 1 - i)
            # 温和波动：±8%，相邻两天最大变化 ≈ 16%（叠加），同户逐日稳定
            kwh = base * drift * random.uniform(0.92, 1.08)
            # 周末/工作日效应（温和：±5%，不叠加为骤变）
            is_weekend = d.weekday() >= 5
            if (u.user_type == "居民" and is_weekend) or (u.user_type != "居民" and not is_weekend):
                kwh *= 1.05
            rows.append(FactUserDaily(
                user_id=u.user_id,
                stat_date=d,
                region_code=u.region_code,
                taiqu_code=u.taiqu_code,
                kwh=Decimal(str(round(kwh, 2))),
            ))
    return rows


def gen_metrics() -> list[MetricDefinition]:
    """指标字典（业务库知识域）：口径/公式/单位/来源，RAG 与 domain 对齐用。"""
    return [
        MetricDefinition(
            code="line_loss_rate", name="线损率", category="general",
            formula="(1 - 售电量/供电量) * 100", unit="%",
            description="线损率反映线路损耗水平，超过10%视为高损（口径：比例小数 0.10=10%）",
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
            description="电费回收情况指标（口径：电费回收率，区别于采集成功率）",
            source="财务部",
        ),
        MetricDefinition(
            code="arrears_rate", name="欠费率", category="finance",
            formula="欠费金额/应收电费 * 100", unit="%",
            description="用户欠费水平指标",
            source="财务部",
        ),
        MetricDefinition(
            code="taiqu_loss_rate", name="台区线损率", category="general",
            formula="(台区供电量 - 台区售电量)/台区供电量 * 100", unit="%",
            description="台区级线损，超过12%视为高损台区（注意区分实抄/估抄数据）",
            source="计量部",
        ),
    ]


async def seed() -> None:
    """主流程：清空东莞版表 -> 按依赖序插入（维度先、事实后）。"""
    factory = get_session_maker()
    async with factory() as session:
        # ---- 第 1 步：清空（幂等）----
        await session.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
        for model in (FactUserDaily, FactTaiquDaily, FactLineLoss, FactRegionDaily,
                      DimMeter, DimUser, DimTaiqu, DimLine, DimRegion,
                      MetricDefinition):
            await session.execute(text(f"DELETE FROM {model.__tablename__}"))
        await session.execute(text("SET FOREIGN_KEY_CHECKS = 1"))

        # ---- 第 2 步：维度（先插，事实表依赖它们的编码）----
        regions = gen_regions()
        lines = gen_lines(regions)
        tais = gen_taiqu(lines)
        users = gen_users(regions, tais)      # 用户挂台区（评审修订）
        meters = gen_meters(users)            # 每用户一个计量点（评审修订）
        session.add_all(regions + lines + tais + users + meters)

        # ---- 第 3 步：指标字典（知识域）----
        session.add_all(gen_metrics())

        # ---- 第 4 步：汇总事实 ----
        session.add_all(gen_region_facts(regions))
        session.add_all(gen_line_facts(lines))
        # 先有每户自然电量，再反推台区（对账自洽 + 户表曲线真实）
        user_facts = gen_user_facts(users)
        session.add_all(user_facts)
        session.add_all(gen_taiqu_facts(tais, user_facts))

        # ---- 第 5 步：一次性提交 ----
        await session.commit()

        # ---- 第 5 步：统计打印 ----
        from sqlalchemy import func, select

        for model, label in (
            (DimRegion, "镇街"), (DimLine, "线路"), (DimTaiqu, "台区"),
            (DimUser, "用户样例"), (DimMeter, "电表"),
            (MetricDefinition, "指标字典"),
            (FactRegionDaily, "区域日度"), (FactLineLoss, "线路日度"),
            (FactTaiquDaily, "台区日度"), (FactUserDaily, "户日明细"),
        ):
            cnt = (await session.execute(select(func.count()).select_from(model))).scalar()
            print(f"  {label}: {cnt}")

    await dispose_engine()
    print("[seed_dongguan] 东莞版模拟数据灌入完成")


if __name__ == "__main__":
    asyncio.run(seed())
