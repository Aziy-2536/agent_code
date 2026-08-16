"""东莞版数据模型：维度表 + 汇总事实表（业务分析主数据源）。

设计决策（见 docs/database-design.md）：
1. 按数据形态分层：维度（少变）/ 汇总（预聚合）/ 明细（海量，暂缓）。
2. 不按地区分表：region_code 编码 + 复合主键实现"按地区组织"，对应用透明。
3. 复合主键 = 天然唯一约束 + 查询索引：
   - fact_region_daily: (region_code, stat_date)  同区域同天唯一
   - fact_line_loss:    (line_code, stat_date)    按线路查是主查询，region_code 降为索引
   - fact_taiqu_daily:  (taiqu_code, stat_date)
4. 金额/电量用 DECIMAL（Numeric），不用 float。

评审修订（2026-08，双视角评审后）：
- dim_user 补 taiqu_code：用户→台区归属，支撑"台区线损 = 总表电量 - Σ户表电量"对账
- 新增 dim_meter：明细数据的键实体是"计量点/电表"而非用户（一户多表不撞键）
- fact_line_loss 主键列序修正：主查询是按线路，region_code 降为查询索引
- 汇总事实表补数据质量字段（read_flag 估抄标志、collection_rate 台区回收率）
- 汇总事实表补审计字段（data_source）
"""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Date, DateTime, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from models.base import BusinessBase


# ==================== 维度层（少变，不分区） ====================

class DimRegion(BusinessBase):
    """区域维度：东莞 32 镇街。"""

    __tablename__ = "dim_region"

    region_code: Mapped[str] = mapped_column(String(8), primary_key=True)  # DG001~DG032
    region_name: Mapped[str] = mapped_column(String(32))                    # 南城街道 / 虎门镇...
    district: Mapped[str] = mapped_column(String(16))                       # 片区：城区/滨海/水乡...
    data_source: Mapped[str] = mapped_column(String(16), default="模拟")    # 数据来源


class DimLine(BusinessBase):
    """线路维度：10kV 线路档案。"""

    __tablename__ = "dim_line"

    line_code: Mapped[str] = mapped_column(String(32), primary_key=True)
    region_code: Mapped[str] = mapped_column(String(8), index=True)         # 归属镇街
    line_name: Mapped[str] = mapped_column(String(64))
    voltage_level: Mapped[str] = mapped_column(String(8), default="10kV")


class DimTaiqu(BusinessBase):
    """台区维度：变压器供电范围（"高损台区"分析粒度）。"""

    __tablename__ = "dim_taiqu"

    taiqu_code: Mapped[str] = mapped_column(String(32), primary_key=True)   # TQ-xxx
    line_code: Mapped[str] = mapped_column(String(32), index=True)          # 所属线路
    region_code: Mapped[str] = mapped_column(String(8), index=True)         # 所属镇街
    transformer_no: Mapped[str] = mapped_column(String(32))                 # 变压器编号
    capacity: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)    # 容量 kVA


class DimUser(BusinessBase):
    """用户维度（精简版）。

    评审修订：补 taiqu_code——用户必须归属到台区，
    否则"台区线损 = 总表电量 - Σ户表电量"对账无法在模型上实现。
    """

    __tablename__ = "dim_user"

    user_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    region_code: Mapped[str] = mapped_column(String(8), index=True)
    taiqu_code: Mapped[str] = mapped_column(String(32), index=True, default="")  # 所属台区（评审补）
    user_type: Mapped[str] = mapped_column(String(8), default="居民")       # 居民/一般工商业/大工业
    meter_no: Mapped[str] = mapped_column(String(32), default="")           # 电表号（关联 dim_meter）

    # ==================== PII 字段（设计见 infra/security.py） ====================
    # 姓名/电话：中敏，明文存储 + 出库前脱敏（mask_name / mask_phone）
    customer_name: Mapped[str] = mapped_column(String(32), default="")      # 客户姓名（出库脱敏）
    phone: Mapped[str] = mapped_column(String(16), default="")              # 联系电话（出库脱敏）
    # 用电地址：中高敏，明文存储 + 出库分级脱敏（mask_address：保留到路/小区级）。
    # 注意：address 是"物理位置"（人在哪），≠ 电气归属（电从哪来）；
    # 户-台区-线路 归属链由 taiqu_code→dim_taiqu→line_code→dim_line 表达，与地址无关。
    address: Mapped[str] = mapped_column(String(256), default="")           # 用电地址（出库脱敏）
    # 身份证：高敏，三层存储——
    #   id_card_hash   SHA-256 摘要（等值匹配/去重，不可逆）
    #   id_card_enc    AES-GCM 密文（低频明文核验，可逆）
    #   id_card_masked 脱敏副本 440106********1234（展示零解密成本）
    id_card_hash: Mapped[str] = mapped_column(String(64), default="")       # SHA-256(id_card)
    id_card_enc: Mapped[str] = mapped_column(String(256), default="")      # AES-GCM 密文
    id_card_masked: Mapped[str] = mapped_column(String(32), default="")    # 脱敏副本


class DimMeter(BusinessBase):
    """电表（计量点）维度。

    评审修订：明细数据的键实体是"计量点"而非"用户"——
    一户多表（专变/大工业）场景下 user_id 会撞键，必须用 meter_code。
    """

    __tablename__ = "dim_meter"

    meter_code: Mapped[str] = mapped_column(String(32), primary_key=True)   # 电表编号
    user_id: Mapped[str] = mapped_column(String(32), index=True)            # 所属用户
    region_code: Mapped[str] = mapped_column(String(8), index=True)
    install_date: Mapped[date | None] = mapped_column(Date, nullable=True)  # 装表日期（换表史）
    status: Mapped[str] = mapped_column(String(8), default="ACTIVE")        # ACTIVE / REPLACED


# ==================== 汇总层（预聚合，Agent 分析主数据源） ====================

class FactRegionDaily(BusinessBase):
    """区域日度汇总：供电/售电/线损/回收率。"""

    __tablename__ = "fact_region_daily"

    # 复合主键：同区域同一天唯一（防重复），同时是查询索引前缀
    region_code: Mapped[str] = mapped_column(String(8), primary_key=True)
    stat_date: Mapped[date] = mapped_column(Date, primary_key=True)
    supply_kwh: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)      # 供电量
    sale_kwh: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)        # 售电量
    line_loss_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)   # 线损率（比例小数，如 0.10=10%）
    collection_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)  # 电费回收率（口径=实收/应收，非采集成功率）
    data_source: Mapped[str] = mapped_column(String(16), default="模拟")        # 审计：数据来源
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class FactLineLoss(BusinessBase):
    """线路日度线损：支撑"高损线路"分析。

    评审修订：主键列序改为 (line_code, stat_date)——
    主查询场景是"按线路查历史/跨区线路排名"，line_code 应作主键前缀；
    region_code 降为普通索引（按镇街筛选用）。
    """

    __tablename__ = "fact_line_loss"

    line_code: Mapped[str] = mapped_column(String(32), primary_key=True)
    stat_date: Mapped[date] = mapped_column(Date, primary_key=True)
    region_code: Mapped[str] = mapped_column(String(8), index=True)            # 查询索引（非主键）
    supply_kwh: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)
    sale_kwh: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)
    loss_kwh: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)
    loss_rate: Mapped[Decimal] = mapped_column(Numeric(10, 6), default=0)      # 线损率（比例小数）
    data_source: Mapped[str] = mapped_column(String(16), default="模拟")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class FactTaiquDaily(BusinessBase):
    """台区日度线损：支撑"高损台区"分析（比线路更细的粒度）。

    评审修订：补数据质量字段——
    - read_flag：实抄/估抄标志，低采集率时"假高损"可被识别
    - collection_rate：台区级电费回收率
    """

    __tablename__ = "fact_taiqu_daily"

    taiqu_code: Mapped[str] = mapped_column(String(32), primary_key=True)
    stat_date: Mapped[date] = mapped_column(Date, primary_key=True)
    supply_kwh: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)
    sale_kwh: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)
    loss_kwh: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)
    loss_rate: Mapped[Decimal] = mapped_column(Numeric(10, 6), default=0)
    read_flag: Mapped[str] = mapped_column(String(16), default="ACTUAL")       # ACTUAL 实抄 / ESTIMATED 估抄
    collection_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)  # 台区级回收率
    data_source: Mapped[str] = mapped_column(String(16), default="模拟")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class FactUserDaily(BusinessBase):
    """户日电量明细（样例级，支撑户级查询与台区对账演示）。

    设计决策：
    1. 样例版：30 天 × 3200 户 ≈ 9.6 万行（真实版 14.6 亿行/年是 v3 的事，
       见 docs/database.md §5.1——日期滚动分区 + 归档）。
    2. 复合主键 (user_id, stat_date)：每户每天唯一。
    3. 与台区汇总自洽：台区 supply_kwh ≈ Σ(户表 kwh) × (1 + 台区线损率)，
       支撑"台区线损 = 总表电量 − Σ户表电量"对账演示。
    """

    __tablename__ = "fact_user_daily"

    user_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    stat_date: Mapped[date] = mapped_column(Date, primary_key=True)
    region_code: Mapped[str] = mapped_column(String(8), index=True)            # 镇街（冗余，加速按区域查）
    taiqu_code: Mapped[str] = mapped_column(String(32), index=True)            # 台区（冗余，加速对账）
    kwh: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=0)            # 当日用电量（度）
    data_source: Mapped[str] = mapped_column(String(16), default="模拟")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

