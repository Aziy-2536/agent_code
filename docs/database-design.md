# PowerInsight Agent 数据库设计（东莞版）

> 面向真实规模：东莞市 32 镇街（6 大片区）、约 400 万用电户。
> 核心思路：**按数据形态分层**（维度/明细/账单/汇总），明细滚动归档、
> 账单永久保存、汇总即时查询；**查询走缓存分层**（Redis 优先、MySQL 兜底）。

---

## 0. 评审记录（2026-08，双视角独立评估后修订）

> 两个独立大模型对设计做了批判性评审，以下是修订记录。

### 0.1 评审发现的根本性问题（已修订）

| # | 问题 | 修订 |
|---|---|---|
| 1 | `dim_user` 缺 `taiqu_code` → 台区线损对账（总表−Σ户表）无法实现 | ✅ dim_user 补 taiqu_code（用户→台区归属） |
| 2 | 明细键用 `(user_id, stat_date)` → 多表户撞键 | ✅ 键实体改为"计量点"，新增 dim_meter |
| 3 | 维度基数错：96 线/288 台区 vs 真实 1.2 万~2 万台区 | ✅ 文档标注真实量级，seed 标注"样例" |
| 4 | 滚动归档无跨冷热查询路径 → 同比/历史对 Agent 丢数据 | ✅ 汇总是小表**永久保留**，仅明细归档 |
| 5 | `fact_line_loss` 主键列序错误 | ✅ 改 `(line_code, stat_date)` PK + region_code 索引 |
| 6 | 无 read_flag → 低采集率算出"假高损" | ✅ 事实表补 read_flag（ACTUAL/ESTIMATED） |
| 7 | 台区级 collection_rate 缺失 | ✅ fact_taiqu_daily 补 collection_rate |
| 8 | 无 ETL 审计字段 | ✅ 汇总事实表补 data_source |
| 9 | VARCHAR(32) 宽主键在 14.6 亿行上索引百 GB | ✅ 文档标注明细层用 BIGINT 代理键（代码暂缓） |
| 10 | 缓存为不存在的瓶颈买单（汇总层本就毫秒级） | ✅ 缓存保留为演示模式，标注"待 P99>50ms 实测决定" |

### 0.2 评审保留的设计（确认正确）

不按地区分表、四层分离、明细滚动归档+账单永久、不建外键、
DECIMAL 不用 float、复合主键=唯一约束+查询索引、Agent 走汇总层、
数据入库+发事件用 Outbox（二期）。

### 0.3 遗留待办（P0 架构级，不在建模范畴）

- **权限上下文进缓存 key**：不同权限用户问同问题会串数据（安全级），
  上线前必须加 tenant/org 维度或权限结果不入共享缓存
- **NL→SQL 查询守卫**：模板化白名单，拒绝退化到 14.6 亿行明细扫描
- **seed 量级**：当前 320 用户仅为样例，性能策略需按真实量级
  （1.2 万~2 万台区）重新验证，或用压测工具模拟

---

## 1. 设计原则

1. **按数据形态分表，不按地区分表**：地区用字段（region_code）表达，不用 32 张表——
   跨区域分析不用 UNION 32 张、改结构不用改 32 次、维护成本不爆炸。
2. **先单表，再分区，最后才分库分表**：每升一级都是被数据量逼出来的，
   不是设计时主动预拆。
3. **明细、账单、汇总三层分离**：生命周期不同、存储策略不同、服务对象不同。
4. **MySQL 是事实源**：需要事务一致性和审计的数据在此；Redis 是可丢失的
   缓存/运行时状态（丢了可从 MySQL 重建）；Milvus 只存知识向量。

---

## 2. 版本演进（DEMO → 东莞化）

| 版本 | 状态 | 说明 |
|---|---|---|
| v1 DEMO | ✅ 已实现（旧表保留） | `region_daily_metrics` / `line_loss_details`：region 用 varchar、自增 id |
| **v2 东莞版** | ✅ **已实现** | `dim_*` 维度 + `fact_*` 汇总，region_code 编码 + 复合主键 |
| v3 真实化 | 📝 文档设计 | 明细/账单三层 + 日期滚动分区 + 归档 |
| v4 规模化 | 📝 规划 | 主从读写分离 → 必要时按 region 分库 |

**迁移策略**：v2 新建 `models/dongguan.py`（7 张表），旧表保留至 Agent
主链路跑通后清理——避免正在验证的代码被破坏。

---

## 3. 数据分层与量级测算（东莞）

| 层级 | 表 | 数据量/年 | 存储策略 | 状态 |
|---|---|---|---|---|
| 维度 | `dim_region`（32 镇街） | 32 行 | 单表 | ✅ 已实现 |
| 维度 | `dim_line`（线路） | 96 行 | 单表 | ✅ 已实现 |
| 维度 | `dim_taiqu`（台区/变压器） | 288 行 | 单表 | ✅ 已实现 |
| 维度 | `dim_user`（用户，精简） | 样例 320 行 | 单表 | ✅ 已实现 |
| 汇总 | `fact_region_daily`（区域日度） | 1.9 万行 | 单表 + 复合主键 | ✅ 已实现 |
| 汇总 | `fact_line_loss`（线路日度） | 5.8 万行 | 单表 + 复合主键 | ✅ 已实现 |
| 汇总 | `fact_taiqu_daily`（台区日度） | 17.3 万行 | 单表 + 复合主键 | ✅ 已实现 |
| 明细 | `fact_user_daily`（每户日电量） | **14.6 亿行** | 单表 + 日期滚动分区 + 归档 | 📝 暂缓 |
| 账单 | `fact_user_monthly`（每户月电量） | 4,800 万行 | 单表 + 月分区（永久） | 📝 暂缓 |

**量级对比**：机动车保有量（东莞约 400 万辆）vs 用电户（约 400 万户），
但车辆系统按天产生的记录远少于"每户每日电量"——户表明细是真正的海量数据。

---

## 4. 东莞版表结构（已实现，`models/dongguan.py`）

### 4.1 维度层

```python
# dim_region：32 镇街，编码 DG001~DG032，按 6 大片区分组
#   （城区/松山湖/滨海/水乡/东南临深/东部产业园）
DimRegion:
    region_code  String(8)   PK      # DG001~DG032
    region_name  String(32)          # 南城街道 / 虎门镇...
    district     String(16)          # 片区
    data_source  String(16)          # 数据来源

# dim_line：线路档案（每镇街 3 条，10kV）
DimLine:
    line_code     String(32)  PK     # DG001-L1 / DG001-L2...
    region_code   String(8)   idx
    line_name     String(64)
    voltage_level String(8)          # 10kV

# dim_taiqu：台区/变压器档案（每线路 3 个）
DimTaiqu:
    taiqu_code     String(32)  PK    # TQ-DG001-L1-1...
    line_code      String(32)  idx   # 所属线路
    region_code    String(8)   idx
    transformer_no String(32)        # 变压器编号
    capacity       Numeric(10,2)     # 容量 kVA

# dim_user：用户档案（精简版，真实主数据在营销系统，这里只存分析最小集）
DimUser:
    user_id     String(32)  PK       # U-DG001-001...
    region_code String(8)   idx
    taiqu_code  String(32)  idx      # 所属台区（评审补：支撑台区线损对账）
    user_type   String(8)            # 居民/一般工商业/大工业
    meter_no    String(32)           # 电表号（关联 dim_meter）

# dim_meter：电表/计量点（评审补：明细数据的键实体是"计量点"而非"用户"）
DimMeter:
    meter_code   String(32)  PK      # 电表编号
    user_id      String(32)  idx     # 所属用户（一户多表场景）
    region_code  String(8)   idx
    install_date Date               # 装表日期（换表史）
    status       String(8)           # ACTIVE / REPLACED
```

### 4.2 汇总层（复合主键 = 唯一约束 + 查询索引）

```python
# fact_region_daily：区域日度（Agent 分析主数据源）
FactRegionDaily:
    region_code     String(8)     PK
    stat_date       Date          PK       # 同区域同天唯一
    supply_kwh      Numeric(18,4)         # 供电量
    sale_kwh        Numeric(18,4)         # 售电量
    line_loss_rate  Numeric(10,6)         # 线损率
    collection_rate Numeric(10,6)         # 回收率

# fact_line_loss：线路日度（评审修订：主键列序改，按线路查是主查询）
FactLineLoss:
    line_code    String(32)    PK    # 主键第 1 列：按线路查/跨区排名
    stat_date    Date          PK
    region_code  String(8)     idx   # 查询索引（非主键）
    supply_kwh / sale_kwh / loss_kwh / loss_rate

# fact_taiqu_daily：台区日度（比线路更细的粒度，"高损台区"分析）
FactTaiquDaily:
    taiqu_code      String(32)  PK
    stat_date       Date        PK
    supply_kwh / sale_kwh / loss_kwh / loss_rate
    read_flag       String(16)          # ACTUAL 实抄 / ESTIMATED 估抄（评审补：防"假高损"）
    collection_rate Numeric(10,6)       # 台区级电费回收率（评审补）
```

**关键设计**：
- 复合主键 `(region_code, stat_date)` 等：同粒度同日期唯一（防重复），
  同时天然是查询索引前缀（`WHERE region_code=? AND stat_date BETWEEN ...` 毫秒级）
- 金额/电量用 `Numeric`（DECIMAL），不用 float
- 不建外键：分析型数据用逻辑外键（应用层保证），换取写入吞吐和灵活性

---

## 5. 明细层与账单层（文档设计，代码暂缓）

### 5.1 `fact_user_daily`：每户日电量（14.6 亿行/年）

```
数据来源：智能电表（每户一个）→ 每日自动采集 → 用电信息采集系统
```

**为什么单表能扛（关键机制）**：

```
400 万行/天 ≈ 1.2 亿行/月

方案对比：
  单表不分区 + 永久保留  ❌ 5 年 70 亿行，索引和查询爆炸
  单表 + 日期滚动分区 ✅ 热分区 1~2 亿行，MySQL 能扛；老分区定期归档
  分库分表（哈希）      ⚠️ 数据量再上量级（全省）才需要
```

```sql
CREATE TABLE fact_user_daily (
    id           BIGINT AUTO_INCREMENT,
    user_id      VARCHAR(32)  NOT NULL,   -- dim_user 外键
    region_code  VARCHAR(8)   NOT NULL,
    stat_date    DATE         NOT NULL,
    kwh          DECIMAL(12,4) NOT NULL,
    UNIQUE KEY uk_user_date (user_id, stat_date),   -- 每户每天唯一
    KEY idx_region_date (region_code, stat_date)
) PARTITION BY RANGE COLUMNS(stat_date) (...);       -- 日期滚动分区
```

**滚动归档机制**：超过保留期的分区 → EXCHANGE PARTITION → 挪到历史库/冷存储。
（这也解释了为什么电费 APP 只提供近 1 年历史日电量查询。）

### 5.2 `fact_user_monthly`：每户月账单（4,800 万行/年，永久保留）

```sql
CREATE TABLE fact_user_monthly (
    user_id    VARCHAR(32),  stat_month CHAR(7),
    kwh        DECIMAL(12,4),      -- 月用电量（从日电量汇总）
    amount     DECIMAL(12,2),      -- 电费金额（钱，必须精确）
    paid       TINYINT DEFAULT 0,
    UNIQUE KEY uk_user_month (user_id, stat_month)
) PARTITION BY RANGE COLUMNS(stat_month) (...);
```

**月冻结 vs 日电量**：日电量是分析数据（滚动归档），月冻结是账单数据
（永久保留）——两套表、两个生命周期，不是二选一。

### 5.3 `dim_meter`（电表）为什么暂缓

1 户 1 表时 meter_no 放 `dim_user` 字段即可；只有 1 户多表/换表场景
才需要独立 `dim_meter` + `meter_change_log`——一期不做，文档预留。

---

## 6. 查询性能方案（Redis 缓存分层）

### 6.1 四层查询路径

```
Agent 查询 "虎门镇昨天线损率"
   │
   ├─ ① 先查 Redis：key = power:cache:region_daily:DG012:2026-08-14
   │      ├─ 命中 → 直接返回（MySQL 不碰）
   │      └─ 未命中 ↓
   ├─ ② 查 MySQL：fact_region_daily 复合主键定位（毫秒级）
   ├─ ③ 结果写回 Redis（TTL 5 分钟）
   └─ ④ 返回
```

### 6.2 缓存 key 规范（`infra/cache.py`）

```
{redis_key_prefix}:cache:{业务前缀}:{参数指纹}
例：power:cache:region_metrics:DG012:2026-08-09:2026-08-15
    power:cache:high_loss_lines:0.1:DG012
    power:cache:regions
```

### 6.3 Redis 的角色边界

| 认知 | 说明 |
|---|---|
| Redis 是**缓存层**，不是数据源 | MySQL 永远是事实源 |
| **读**：Redis 命中就读 Redis，未命中读 MySQL 并回写——**二选一，不双读** |
| **写**：只写 MySQL | Redis 靠 TTL + 主动失效（`cache_del`）同步 |
| Redis 挂了 | 降级回源 MySQL（`cache_get` 异常返回 None），只慢不错 |
| 一致性 | 最多 TTL 时长的轻微延迟（可接受），无丢失风险 |

### 6.4 已实现代码

```
infra/cache.py                  → cache_get / cache_set / cache_del（TTL + 降级）
repositories/dongguan_repository.py → 查询方法"缓存优先"
scripts/seed_dongguan.py        → 32 镇街 / 96 线路 / 288 台区 / 25,000 汇总
```

---

## 7. 数据一致性机制（缓存 vs Outbox）

### 7.1 查询缓存：不需要 Outbox

MySQL↔Redis 是**缓存关系，不是双写**：

```
写操作：只写 MySQL（唯一事实源）
读操作：先查 Redis，未命中回源 MySQL，回写缓存副本
```

- 没有"同时写两个地方" → 不需要 Outbox
- 只需 TTL + 主动失效（`cache_del`）保证一致性

### 7.2 Outbox Pattern：二期接 Kafka 时用（数据接入）

**解决"双写一致"**：数据入库 + 发事件（Kafka）必须同时成功。

```
电力 API 数据入库（Ingestion）：
  ① 写业务表 + ② 写 outbox 表（待发事件）——【同一事务】
后台 Outbox Relay（独立进程）：
  ① 扫 outbox → 读到待发事件
  ② 发 Kafka（power.data.ingested 等）
  ③ 成功 → 删除/标记 outbox 记录；失败 → 重试（事件不丢，最多延迟）
```

**什么时候上**：架构文档 §4/§5 的 Kafka 事件层落地时（`power.data.ingested`、
`power.analysis.completed`...），数据接入和事件发布必须不丢——上 Outbox。

### 7.3 机制选择表

| 场景 | 机制 |
|---|---|
| 查询热点（读加速） | ✅ 缓存（Redis 先查、MySQL 兜底、TTL）——已实现 |
| 数据变更后清缓存 | ✅ 主动失效（`cache_del`）——已实现 |
| 数据入库 + 发事件（二期） | ⚠️ Outbox Pattern——接 Kafka 时实现 |
| 明细 → 汇总 ETL | 定时任务/物化视图 |

---

## 8. 主从读写分离（三期）

```
                 ┌→ 从库 A（报表/Agent 查询）
写入 → 主库 ─────┼→ 从库 B（历史归档查询）
                 └→ 从库 C（分析查询）
```

- 实现：`mysql_writer_dsn` / `mysql_reader_dsn` 双引擎；读走 reader、写走 writer
- **关键坑**：主从延迟——"刚写入立刻读"可能读不到，一致性敏感的读走主库
- Docker 演示：1 主 2 从 + binlog 复制

---

## 9. 与 Agent 平台的配合

```
Agent 查询 "A区线损率"
   → fact_region_daily（汇总层，缓存优先，秒回）
   → 需要明细归因 → fact_user_daily 热分区 / fact_user_monthly（暂缓）
   → 口径对齐 → metric_definitions（知识域）
```

- **Agent 分析走汇总层**，不直接扫 14 亿行日明细
- 汇总表数据来源：ETL/定时任务从明细层聚合（二期）
- 指标口径（线损率/回收率）与 `metric_definitions` 对齐

---

## 10. 演进路径

```
v1 DEMO（✅ 完成）：region varchar、单表、无维度表
   ↓
v2 东莞版（✅ 完成）：region_code 编码 + 维度表 + 复合主键
                  + seed 32 镇街数据 + Redis 缓存查询
   ↓
v3 真实化（📝 设计）：明细/账单三层 + 日期滚动分区 + 归档 + Kafka Outbox
   ↓
v4 规模化（📝 规划）：主从读写分离 → 必要时按 region 分库分表
```

---

## 11. 面试叙事

> "数据库设计我按数据形态分层：维度（region/line/taiqu/user）、汇总
> （区域/线路/台区日度）、明细（每户日电量）、账单（月冻结）四类，
> 生命周期和存储策略各不相同。东莞 32 镇街不按地区分表——用 region_code
> 编码 + 复合主键实现'按地区组织'，对应用透明。每户日电量 14.6 亿行/年
> 靠日期滚动分区 + 归档扛住，账单走月冻结永久保存。
> 查询性能四层解决：汇总表预聚合 + 复合主键索引 + Redis 缓存热点
> （不双读，MySQL 兜底）+ 二期读写分离。数据一致性上，缓存用 TTL/主动失效；
> 二期接 Kafka 时数据入库与事件发布用 Outbox 保证不丢。"
```
