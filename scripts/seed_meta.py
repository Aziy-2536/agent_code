"""灌入元数据知识库（业务表信息 + 字段信息 + 字段取值）。

设计决策：
1. 元数据是业务语义描述，必须人工录入（不靠 AI 生成，AI 生成不准）。
2. 覆盖 8 张东莞版业务表：表信息（用途/主键/关联）+ 关键字段（含义/角色）+ 取值（镇街编码映射）。
3. 幂等：先清空 3 张元数据表再灌。
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from db import dispose_engine, get_session_maker  # noqa: E402
from models import MetaField, MetaTable, MetaValue  # noqa: E402


def gen_tables() -> list[MetaTable]:
    """表信息：8 张东莞版业务表。"""
    return [
        MetaTable(table_name="dim_region", table_desc="东莞32镇街档案（含6大片区分组）",
                  table_layer="维度", primary_key="region_code",
                  related_tables="dim_line,dim_user,fact_region_daily"),
        MetaTable(table_name="dim_line", table_desc="10kV线路档案（每镇街多条线路）",
                  table_layer="维度", primary_key="line_code",
                  related_tables="dim_region,dim_taiqu,fact_line_loss"),
        MetaTable(table_name="dim_taiqu", table_desc="台区/变压器档案（线路下多个台区）",
                  table_layer="维度", primary_key="taiqu_code",
                  related_tables="dim_line,dim_user,fact_taiqu_daily"),
        MetaTable(table_name="dim_user", table_desc="用电用户档案（居民/工商业，挂台区）",
                  table_layer="维度", primary_key="user_id",
                  related_tables="dim_region,dim_taiqu,dim_meter"),
        MetaTable(table_name="dim_meter", table_desc="电表/计量点档案（每用户一表）",
                  table_layer="维度", primary_key="meter_code",
                  related_tables="dim_user"),
        MetaTable(table_name="fact_region_daily", table_desc="区域日度汇总（供电量/售电量/线损率/回收率）",
                  table_layer="汇总", primary_key="region_code+stat_date",
                  related_tables="dim_region"),
        MetaTable(table_name="fact_line_loss", table_desc="线路日度线损（高损线路分析）",
                  table_layer="汇总", primary_key="line_code+stat_date",
                  related_tables="dim_line"),
        MetaTable(table_name="fact_taiqu_daily", table_desc="台区日度线损（高损台区分析，含实抄/估抄标志）",
                  table_layer="汇总", primary_key="taiqu_code+stat_date",
                  related_tables="dim_taiqu"),
    ]


def gen_fields() -> list[MetaField]:
    """字段信息：关键字段的业务含义与角色。"""
    return [
        # dim_region
        MetaField(table_name="dim_region", field_name="region_code", field_desc="镇街编码（DG001~DG032）",
                  field_type="varchar", role="主键", is_filter=1),
        MetaField(table_name="dim_region", field_name="region_name", field_desc="镇街名称（如虎门镇/南城街道）",
                  field_type="varchar", role="维度", is_filter=1),
        MetaField(table_name="dim_region", field_name="district", field_desc="六大片区（城区/滨海/水乡等）",
                  field_type="varchar", role="维度", is_filter=1),
        # fact_region_daily
        MetaField(table_name="fact_region_daily", field_name="stat_date", field_desc="统计日期",
                  field_type="date", role="时间", is_filter=1),
        MetaField(table_name="fact_region_daily", field_name="supply_kwh", field_desc="供电量（度）",
                  field_type="decimal", role="度量"),
        MetaField(table_name="fact_region_daily", field_name="sale_kwh", field_desc="售电量（度）",
                  field_type="decimal", role="度量"),
        MetaField(table_name="fact_region_daily", field_name="line_loss_rate", field_desc="线损率（比例小数，0.10=10%）",
                  field_type="decimal", role="度量"),
        MetaField(table_name="fact_region_daily", field_name="collection_rate", field_desc="电费回收率（口径=实收/应收）",
                  field_type="decimal", role="度量"),
        # fact_line_loss
        MetaField(table_name="fact_line_loss", field_name="line_code", field_desc="线路编号（DG001-L1）",
                  field_type="varchar", role="维度", is_filter=1),
        MetaField(table_name="fact_line_loss", field_name="loss_rate", field_desc="线路线损率（>10% 视为高损）",
                  field_type="decimal", role="度量"),
        # fact_taiqu_daily
        MetaField(table_name="fact_taiqu_daily", field_name="taiqu_code", field_desc="台区编号",
                  field_type="varchar", role="维度", is_filter=1),
        MetaField(table_name="fact_taiqu_daily", field_name="loss_rate", field_desc="台区线损率（>12% 视为高损）",
                  field_type="decimal", role="度量"),
        MetaField(table_name="fact_taiqu_daily", field_name="read_flag", field_desc="实抄/估抄标志（ACTUAL/ESTIMATED，估抄可能假高损）",
                  field_type="varchar", role="维度", is_filter=1),
    ]


def gen_values() -> list[MetaValue]:
    """字段取值：镇街编码 → 名称映射（LLM 识别"虎门镇"→DG012 靠它）。

    数据源：从 scripts.seed_dongguan.REGIONS 自动生成全部 32 镇街
    （单一数据源，避免两处手工维护不一致）——编码 DG001~DG032 按 REGIONS 顺序。
    """
    # 从 seed_dongguan 导入 32 镇街（(镇街名, 片区) 列表）
    from scripts.seed_dongguan import REGIONS

    values = [
        MetaValue(table_name="dim_region", field_name="region_code",
                  code=f"DG{i + 1:03d}", value=name)
        for i, (name, _district) in enumerate(REGIONS)
    ]
    # 指标取值（metric code 语义）
    values += [
        MetaValue(table_name="metric_definitions", field_name="code", code="line_loss_rate", value="线损率"),
        MetaValue(table_name="metric_definitions", field_name="code", code="collection_rate", value="电费回收率"),
        MetaValue(table_name="metric_definitions", field_name="code", code="supply_kwh", value="供电量"),
        MetaValue(table_name="metric_definitions", field_name="code", code="sale_kwh", value="售电量"),
        # read_flag 取值
        MetaValue(table_name="fact_taiqu_daily", field_name="read_flag", code="ACTUAL", value="实抄"),
        MetaValue(table_name="fact_taiqu_daily", field_name="read_flag", code="ESTIMATED", value="估抄"),
    ]
    return values


async def seed_meta() -> None:
    factory = get_session_maker()
    async with factory() as session:
        # 清空（幂等）
        await session.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
        for model in (MetaValue, MetaField, MetaTable):
            await session.execute(text(f"DELETE FROM {model.__tablename__}"))
        await session.execute(text("SET FOREIGN_KEY_CHECKS = 1"))

        # 灌入
        session.add_all(gen_tables())
        session.add_all(gen_fields())
        session.add_all(gen_values())
        await session.commit()

        # 统计
        from sqlalchemy import func, select

        for model, label in ((MetaTable, "表元数据"), (MetaField, "字段元数据"), (MetaValue, "取值字典")):
            cnt = (await session.execute(select(func.count()).select_from(model))).scalar()
            print(f"  {label}: {cnt}")

    await dispose_engine()
    print("[seed_meta] 元数据知识库灌入完成")


if __name__ == "__main__":
    asyncio.run(seed_meta())
