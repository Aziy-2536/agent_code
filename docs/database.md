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
| 维度 | `dim_user`（用户，精简） | 样例 3200 行 | 单表 | ✅ 已实现 |
| 汇总 | `fact_region_daily`（区域日度） | 1.9 万行 | 单表 + 复合主键 | ✅ 已实现 |
| 汇总 | `fact_line_loss`（线路日度） | 5.8 万行 | 单表 + 复合主键 | ✅ 已实现 |
| 汇总 | `fact_taiqu_daily`（台区日度） | 17.3 万行 | 单表 + 复合主键 | ✅ 已实现 |
| 明细 | `fact_user_daily`（户日电量，样例） | 9.6 万行（3200 户 × 30 天） | 单表 + 复合主键 | ✅ 已实现（样例级） |
| 明细 | `fact_user_daily`（真实版） | **14.6 亿行** | 单表 + 日期滚动分区 + 归档 | 📝 暂缓（v3） |
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

### 8.1 与 Agent 域的交互规则（记忆域必须走主库）

> **记忆域是"高频写 + 写后立即读"模式，与主从延迟天然冲突**，必须提前定死路由规则：

| 域 | 读写模式 | 主从策略 |
|---|---|---|
| 业务域（汇总表） | 批量灌入 + 聚合查询，写读间隔长 | 读走从库 🟢 延迟可容忍 |
| **记忆域（会话/记忆）** | **append_message 后同一请求内 load_recent_context** | **写后同任务内读取 → 强制走主库** 🔴 |

**规则**：
1. 会话消息/记忆**写入后同一任务内**的读取 → 强制主库（否则上下文"丢最近一轮"，难排查）
2. 跨任务/跨会话的历史检索（延迟不敏感）→ 可走从库
3. 增量同步（sync_meta.py）的 diff 校验读取 → 走主库（meta 表极小，读主库成本可忽略；
   读从库 + 延迟会误判"元数据缺失"触发错误变更）
4. 未来 ALTER（加字段/索引）→ 先从库验证再主库执行（DDL 复制到从库会阻塞该从库复制线程；
   meta/记忆表都小，无感，仅提醒大表需 pt-osc）

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

---

# 数据库双库结构说明（agent / power_insight）

> 同一 MySQL 实例（docker `power-mysql`，宿主机 3307），**两个物理独立的库**。
> 划分原则：按"域"隔离——Agent 交互数据与业务事实数据互不混存。

---

## 1. 总览

```
MySQL 实例（3307）
├── agent 库           ← Agent 域：任务执行 + 会话 + 记忆（9 表）
└── power_insight 库   ← 业务域：东莞电力数据 + 指标口径 + 元数据知识库（15 表）
```

| 维度 | agent 库 | power_insight 库 |
|---|---|---|
| 职责 | Agent 交互产物（任务/对话/经验） | 业务事实（电力数据/指标）+ 元数据知识库（表/字段/取值字典） |
| 数据性质 | 执行轨迹、上下文、沉淀经验 | 经营分析数据 |
| 增长模式 | 与使用次数挂钩 | 与业务数据量挂钩 |
| 清库策略 | 可清理（会话可删、记忆可衰减） | 保留（审计/业务） |
| 未来扩展 | 可独立成服务/独立实例 | 随业务量演进 |

---

## 2. agent 库（Agent 域）—— 9 张表

### 2.1 任务域（5 张）：一次分析的完整执行轨迹

| 表 | 作用 | 关键字段 |
|---|---|---|
| `analysis_tasks` | 任务主表（聚合根）：一次用户请求 | task_id(UUID), status, trace_id, question, 预算 |
| `task_steps` | 执行步骤（LangGraph 节点记录） | task_id, node_name, detail(JSON) |
| `tool_calls` | 工具调用明细（审计/评测数据源） | task_id, tool_name, input/output(JSON), 耗时 |
| `human_approvals` | 人工审批记录 | task_id, params(JSON), status(PENDING/APPROVED/REJECTED) |
| `analysis_reports` | 最终分析报告 | report_id(UUID), task_id, content(JSON), citations |

**关系**：主从结构——所有子表通过 `task_id` 挂到主表，一次分析 = 完整可审计轨迹。

### 2.2 记忆域（4 张）：跨任务/跨会话的上下文与经验

| 表 | 作用 | 关键字段 |
|---|---|---|
| `conversations` | 会话根：多轮对话 | conversation_id(UUID), user_id, org_code, title, status |
| `conversation_messages` | 会话消息：每轮问答 | conversation_id, role(user/assistant/tool), content, task_id(可选) |
| `episodic_memories` | 情景记忆：历史案例（成败可复用） | trace_id, task_id, user_id, org_code, scope(user/org/global), query, intent, success, summary |
| `semantic_memories` | 语义记忆：沉淀规则（质量门禁后写入） | rule_type, content, user_id(可空), org_code(可空), scope(org/global), confidence, usage_count, success_count |

> **P0 作用域隔离（评审遗留"权限不能串"）**：记忆按内容通用性分三级
> `user`（仅本人）/ `org`（组织共享）/ `global`（系统通用）。
> 检索注入 prompt 前必须按当前用户作用域过滤；user 级主观偏好走 `user_profiles`
> （二期），semantic 表不承载 user 级内容。详见 [agent-memory.md](agent-memory.md) §8。

**记忆分层**：
```
conversation（多轮对话）
   → task（单次分析，已有）
   → episodic（跨任务提炼案例）
   → semantic（跨会话沉淀规则，置信度<0.7 不生效）
```

---

## 3. power_insight 库（业务域）—— 15 张表

### 3.1 东莞版维度层（5 张）：分析对象档案

| 表 | 作用 | 关键字段 |
|---|---|---|
| `dim_region` | 32 镇街档案 | region_code(DG001~DG032), region_name, district(6 片区) |
| `dim_line` | 线路档案 | line_code, region_code, voltage_level |
| `dim_taiqu` | 台区/变压器档案 | taiqu_code, line_code, region_code, capacity |
| `dim_user` | 用户档案（精简） | user_id, region_code, taiqu_code, user_type, meter_no, customer_name, phone, address, id_card_hash, id_card_enc, id_card_masked |

> **PII 三层存储（从建模层定死，非后期补丁）**——`dim_user` 的敏感字段设计：
>
> | 字段 | 存储形态 | 用途 |
> |---|---|---|
> | `customer_name` / `phone` | 明文（中敏） | 出库前脱敏（`mask_name` / `mask_phone`），展示常态 |
> | `address` | 明文（中高敏） | 出库前分级脱敏（`mask_address`：保留到路/小区级，隐去门牌号+栋+房号） |
> | `id_card_hash` | SHA-256（不可逆） | 等值匹配/去重，类比密码存储 |
> | `id_card_enc` | AES-GCM 密文（可逆） | 低频明文核验，密钥在应用层（`PII_SECRET_KEY`） |
> | `id_card_masked` | 脱敏副本 440106********1234 | 展示零解密成本 |
>
> **地址 vs 电气归属（重要区分）**：`address` 是"物理位置"（人在哪），
> **不是**电气归属（电从哪来）。户-台区-线路归属链由
> `dim_user.taiqu_code → dim_taiqu → line_code → dim_line` 表达（评审补的，
> 支撑"台区线损 = 总表电量 − Σ户表电量"对账）。地址不参与电气归属判断。
>
> 铁律：**脱敏在数据出库前完成（Repository 层），接口/前端永远拿不到明文**；
> 密文与哈希不出库；敏感数据不进共享 Redis 缓存（权限 P0）。
> 实现见 `infra/security.py`，字段模型见 `models/dongguan.py` DimUser。
| `dim_meter` | 电表/计量点档案 | meter_code, user_id, install_date, status |

### 3.2 东莞版汇总层（3 张）：Agent 分析主数据源

| 表 | 作用 | 复合主键 |
|---|---|---|
| `fact_region_daily` | 区域日度（供电/售电/线损/回收率） | (region_code, stat_date) |
| `fact_line_loss` | 线路日度线损 | (line_code, stat_date) |
| `fact_taiqu_daily` | 台区日度线损（含 read_flag 实抄/估抄） | (taiqu_code, stat_date) |

### 3.3 户日明细层（1 张，样例级）：户级分析与台区对账

| 表 | 作用 | 复合主键 |
|---|---|---|
| `fact_user_daily` | 户日电量（30 天 × 3200 户 ≈ 9.6 万行） | (user_id, stat_date) |

> **与台区汇总严格自洽（口径正确）**：
> - 先有每户自然电量（基准 ±8% 温和波动 + 周末效应），再反推台区
> - `台区售电量 = Σ户表`（售电量 = 户表抄见电量）
> - `台区供电量 = Σ户表 / (1 − 台区线损率)`（线损率 = (供电−售电)/供电，标准口径）
> - 实测：Σ户表 = 台区售电零偏差；抽查 20 台区天 19/20 完全吻合
> （1 个为四舍五入边界）
> 样例级先行（复用同一模型），真实版 14.6 亿行/年是 v3 的
> 日期滚动分区 + 归档（见 §5.1），代码无需改动，仅扩数据量。

### 3.4 知识域（4 张）

| 表 | 作用 | 关键字段 |
|---|---|---|
| `metric_definitions` | 指标口径字典（RAG 与 domain 对齐） | code, formula, unit, description |
| `meta_tables` | 表元数据（该查哪些表） | table_name(PK), table_desc, table_layer, primary_key, related_tables |
| `meta_fields` | 字段元数据（字段业务含义/角色） | **UNIQUE(table_name, field_name)**, field_desc, field_type, role, is_filter |
| `meta_values` | 字段取值字典（"虎门镇"→DG012） | **UNIQUE(field_name, value)**, code, value |

> **元数据知识库（Agent 前提底座）**：MetaTable/MetaField/MetaValue 三表
> 服务"先理解上下文再动手"——LLM 识别表/字段/取值靠它们。
> 两处唯一键是增量同步（sync_meta.py 按业务键 upsert）的 P0 前置，防重复插入。
> 详见 [agent-knowledge.md](agent-knowledge.md) §5。

### 3.5 旧版业务表（2 张，待清理）

| 表 | 说明 |
|---|---|
| `region_daily_metrics` | DEMO 版区域指标（region varchar） |
| `line_loss_details` | DEMO 版线路线损 |

---

## 4. 为什么这样划分（设计依据）

1. **生命周期不同**：任务/会话可清理、可衰减；业务数据需保留（审计/分析）。
2. **访问模式不同**：Agent 域是"写入频繁 + 按任务检索"；业务域是"批量灌入 + 聚合查询"。
3. **未来独立扩展**：agent 库可独立成服务（记忆服务/会话服务），代码层已隔离（AgentBase），物理分实例只是加 DSN 的事。
4. **避免互相污染**：清库、迁移、权限控制互不影响。

---

## 5. 技术实现（双 Base + 双引擎）

```
代码层：
  models/base.py
    ├── AgentBase    → agent 库（task.py + memory.py 挂它）
    └── BusinessBase → power_insight 库（dongguan.py + knowledge.py + power.py 挂它）

连接层（db/mysql.py）：
  get_engine()              → power_insight 库引擎（业务）
  get_agent_engine()        → agent 库引擎（Agent）
  get_session_maker()       → 业务库会话工厂
  get_agent_session_maker() → Agent 库会话工厂

依赖注入（app/api/deps.py）：
  get_db()         → Agent 库 Session（任务/会话/记忆路由用）
  get_business_db()→ 业务库 Session（东莞数据查询用）

建表（scripts/init_db.py）：
  AgentBase.create_all    → agent 库（9 表）
  BusinessBase.create_all → power_insight 库（11 表）
```

---

## 6. 常用操作

```bash
# 建表（双库）
python scripts/init_db.py

# 灌东莞业务数据（→ power_insight 库）
python scripts/seed_dongguan.py

# 灌元数据知识库（→ power_insight 库，meta_tables/fields/values）
python scripts/seed_meta.py

# 查看两库表
docker exec power-mysql mysql -uroot -proot -e "SHOW TABLES FROM agent;"
docker exec power-mysql mysql -uroot -proot -e "SHOW TABLES FROM power_insight;"
```

---

## 7. 演进预留

- **agent 库独立成实例**：加 `agent_mysql_dsn`（独立主机），代码不变（AgentBase 已隔离）
- **记忆检索上 Milvus**：episodic/semantic 的向量索引放 Milvus，MySQL 只存结构化部分
- **元数据增量同步**：`sync_meta.py`（diff 驱动 + sink 接口）替代 seed 全量重灌；
  meta 表唯一键已就位，二期加 Qdrant/ES sink 时 diff 引擎与调用方零改动
  （详见 [agent-knowledge.md](agent-knowledge.md) §5）
- **用户特征表（user_profiles）**：user 级主观偏好（常用指标/输出格式）落 agent 库，
  MySQL 真相 + Redis 热层（详见 [agent-memory.md](agent-memory.md) §7）
- **明细层（fact_user_daily 等）**：未来进 power_insight 库（业务数据），日期分区 + 归档

---

# ADR-001: 数据访问采用 SQLAlchemy 2.0 异步模式 + asyncmy 驱动

**Status**: Accepted
**Date**: 2026-08-15

## Context

系统入口是 FastAPI（异步框架），Agent Worker 也是异步任务。若使用同步驱动
（PyMySQL），数据库调用会阻塞事件循环，高并发下请求排队、吞吐下降。
需要选择：异步驱动选哪个、ORM 层如何组织。

## Decision

1. **ORM 用 SQLAlchemy 2.0 的 async 模式**（`create_async_engine` +
   `async_sessionmaker` + `AsyncSession`），同步/异步代码同构，模型定义可复用。
2. **驱动用 asyncmy**（`mysql+asyncmy://`），Cython 实现、性能优于纯 Python 的
   aiomysql，且本环境已具备。
3. **连接管理**：Engine 管连接池（进程级单例、懒初始化），Session 管工作单元
   （由 FastAPI 依赖注入提供，调用方决定事务边界）；`expire_on_commit=False`
   避免异步下 commit 后隐式 IO 抛错。
4. Kafka Worker 的批量处理如需要同步 session，可另建同步 engine，两套共用
   `models/` 定义。

## Consequences

**正向**：
- 请求处理全程非阻塞，事件循环不被数据库 IO 卡住。
- 模型层（`models/`）与连接层（`db/`）分离，测试可 mock Repository。

**负向**：
- asyncmy 依赖编译产物，部署环境需匹配 Python 版本。
- 异步调试比同步略复杂（需要 `asyncio.run` / `AsyncSession` 上下文）。

## Alternatives Considered

1. **PyMySQL 同步 + 线程池**：实现简单，但每个请求占一个线程，FastAPI 异步优势尽失。
2. **aiomysql**：纯 Python、兼容好，但性能低于 asyncmy，且生态成熟度相当。
3. **asyncmy + 裸 asyncio**：无 ORM 层，SQL 散落业务代码，放弃。

---

# ADR-002: 确定性业务逻辑下沉 domain 层，LLM 只做理解与编排

**Status**: Accepted
**Date**: 2026-08-15

## Context

电力指标（线损率、回收率、峰谷比等）有明确公式。若把这些计算交给 LLM，
存在两个问题：大模型算术会出错且不可复现；指标口径分散在 prompt 中，
改口径 = 调 prompt，无法回归验证。

## Decision

1. `domain/` 层用纯函数固化所有确定性公式（线损率、同比环比、峰谷比、
   欠费率、异常等级判定），**不依赖 LLM、FastAPI 和任何框架**。
2. 指标口径以 `metric_definitions` 表（code/name/formula/unit/source）为
   唯一事实来源：RAG 检索它的描述文本，domain 层按 code 执行公式，
   两者通过 code 对齐。
3. LLM 只负责：意图理解（Route）、任务规划（Plan）、工具编排（Act）和
   报告措辞（Report）——即"理解与编排"，不负责"计算"。

## Consequences

**正向**：
- 计算结果 100% 可复现，可单测，评测简单（不用 LLM-as-Judge 验算）。
- 改口径 = 改代码 + 回归测试，不依赖 prompt 调优。
- 面试叙事清晰："哪些交给 LLM、哪些不交给 LLM"是 Agent 工程的核心决策。

**负向**：
- 新增指标需要写代码（成本高于改 prompt），需要配套指标字典维护流程。

## Alternatives Considered

1. **全部交给 LLM 计算**：快但不可复现、会算错，放弃。
2. **口径写在 prompt 里让 LLM 理解**：口径随 prompt 漂移，无法验证，放弃。
3. **domain 层 + 规则引擎**：引入 DSL 增加复杂度，第一版纯函数足够。

---

# ADR-003: 向量存储选型 Milvus（vs Qdrant / Chroma）

**Status**: Accepted
**Date**: 2026-08-15

## Context

系统需要为指标口径、政策文档、业务规则提供语义检索（Hybrid RAG）。
向量库选型需考虑：生产可演进性、数据规模、检索质量、部署复杂度。

## Decision

采用 **Milvus 2.4**（standalone 部署，docker-compose 一键起：
milvus + etcd + minio），理由：

1. **生产级**：支持十亿级向量、丰富的索引类型（IVF/HNSW）、标量过滤 + 向量混合检索，
   是国内工业界（尤其数据类场景）的主流选择。
2. **官方 GUI（Attu）**：可视化管理集合/索引/数据，开发体验好。
3. **生态**：pymilvus SDK 成熟，与 Hybrid RAG（BM25 + Dense + RRF）配套资料多。
4. **与项目叙事匹配**：电力数据平台用 Milvus 比 Chroma 更有说服力。

配套决策：
- 只存知识向量（指标口径、政策、规则、案例），**不存业务交易数据**（业务事实在 MySQL）。
- 访问通过 `db/milvus.py` 懒初始化单例；`rag/milvus_store.py` 之上保留
  `VectorStore` 抽象接口，Milvus 是其中一个实现，便于未来替换。

## Consequences

**正向**：
- 检索质量与扩展性满足第一版，且可平滑演进到集群模式。
- Attu + docker-compose 让本地开发与演示零门槛。

**负向**：
- 部署组件多（etcd + minio + milvus 三容器），资源占用高于单文件方案。
- 写入是近实时，查询前需要 flush/等待可见性（已通过 `flush()` 处理）。

## Alternatives Considered

1. **Qdrant**：Rust 实现、单容器简单、性能好；但国内电力/数据场景生态弱于 Milvus。
2. **Chroma**：嵌入式、零运维，适合原型；生产级能力和社区弱，放弃。
3. **Elasticsearch**：已有本地镜像，但向量检索能力与 Milvus 相比非专长，且重。
