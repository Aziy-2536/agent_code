# Agent 知识层架构：元数据 / 检索 / 增量同步

> 本文档沉淀"知识层"设计决策：元数据知识库的定位、多路召回、向量库职责、
> 多存储增量同步。与 `agent-memory.md`（记忆架构）、`architecture.md`（总体架构）配套阅读。

---

## 1. 核心结论（先记住这三条）

1. **元数据 ≠ 业务库**：LLM 不直接查数仓，只接触"经配置筛选的元数据上下文"，
   SQL（或模板参数）最终执行在真实数仓上。
2. **向量库 = 语义检索索引层，不是 RAG 的存储**：它横跨知识域（RAG）、
   Agent 域（记忆召回、技能匹配）等多个领域，只做"语义相似召回"。
3. **MySQL 是唯一事实源，一切派生存储（Qdrant/Milvus、ES、Redis）都可重建**。

---

## 2. 方案对比：LLM 直连数仓 vs 元数据上下文 vs 模板化查询

| 维度 | A. LLM 直接调数据库 | B. 元数据上下文 + 受限 NL2SQL | C. 模板化查询（本项目主线） |
|---|---|---|---|
| LLM 输出 | 自由 SQL | 受限 SQL（上下文白名单内） | 只提取参数，不产 SQL |
| 口径正确性 | ❌ 全靠模型猜 | 🟡 指标口径预定义在元数据 | ✅ 模板即口径，零歧义 |
| 安全/注入 | ❌ 灾难级，明细可被扫 | 🟡 表字段白名单 + EXPLAIN 校验 | ✅ 参数化拼接，无注入面 |
| 上下文成本 | ❌ 全 schema 塞 prompt | ✅ 召回+过滤后只剩所需 | ✅ 固定模板，prompt 极小 |
| 灵活性 | ✅ 最高 | ✅ 高（多表 join 等） | ❌ 只覆盖预设问题类型 |
| 可审计/可解释 | ❌ 黑盒 | 🟡 元数据可解释 | ✅ 完全可解释 |

**结论：B 显著优于 A；C 是 B 的更安全特例。** 本项目保持 C 为主线（主档），
B（受限 NL2SQL）作为二期备档覆盖复杂问数（top N、环比、多指标对比）。

### 2.1 参考项目（shopkeeper-agent）的教训

参考项目 [shopkeeper-agent](https://github.com/didilili/shopkeeper-agent) 的架构：

```
conf/meta_config.yaml（配置驱动：哪些表/字段/指标/别名/取值进知识库）
  → 同步脚本（meta_knowledge_service.py）
  → 元数据知识库（MySQL meta 4 表 + Qdrant 向量 + ES 全文）
  → 问数智能体（LangGraph：关键词抽取 → 多路召回 → 合并 → 过滤
     → 生成 SQL → EXPLAIN 校验 → correct_sql 校正 → 执行）
```

要点与教训：

- **配置驱动**："不是代码决定同步什么，而是配置决定同步什么"——新表上线只改配置。
  真实数仓有大量中间表/临时表/废弃表，不该暴露给问数系统。
- **EXPLAIN 只校验语法，不校验语义**：发现不了 join 错、口径错、漏过滤条件。
- **全量重建是病根**：`_save_column_info_to_qdrant` 每次用 `uuid4()` 随机 id
  重建全部向量点，ES 取值全量 index——无 diff、无增量、无"数仓变化才触发"。
- **无记忆机制**：query_service 是无状态工作流，无会话历史、无案例复用。

---

## 3. 多路召回（multi-recall）

### 3.1 定义

多路召回 = **同一个 query 同时走多条独立召回通道，结果合并去重**。
通道划分按"召回对象"，不是按存储种类。

```
用户问题："虎门镇这个月线损率多少，和上个月比"
   ├─① ES 字段名精确/字面召回  → column_name 匹配 "line_loss"
   ├─② 向量库 字段语义召回     → 描述/别名 "线损率"（近义）
   ├─③ 向量库 指标语义召回     → 指标 "line_loss_rate" 口径
   ├─④ ES 字段取值召回         → "虎门镇" → region_code=DG012
   ├─⑤ MySQL 规则精确         → 历史语义规则 LIKE
   └─⑥ RAG 文档召回           → 指标口径文档片段
        ↓ 合并
   RRF（Reciprocal Rank Fusion）加权 → 去重 → 过滤 → 下游
```

### 3.2 存储选择原则（通道内选工具）

| 匹配特性 | 存储 |
|---|---|
| 精确 / 取值映射（虎门镇→DG012） | ES（或 MySQL 精确表） |
| 字面模糊（分词、拼音、IK 中文） | ES |
| 语义近似（"成交总额"≈order_amount） | 向量库 |
| 结构化过滤 / 统计 / 审计 | MySQL |

### 3.3 对主链路的定位

模板化查询已内置"最短路"：`build_context` 把元数据直接拼进 prompt，
LLM 只提取参数——**主链路不需要多路召回**。多路召回是二期受限 NL2SQL 备档才需要的。

---

## 4. 向量库（Milvus/Qdrant）职责边界

> **Milvus 的最终功能 = 全系统唯一的"语义召回引擎"**：
> 把"含义相近但字面不同"的请求翻译成"候选 id 列表"，交给下游回表。
> 它只做相似度计算，不做真相、统计、权限、缓存。

### 4.1 能力矩阵

| 能力 | MySQL | ES | Milvus/Qdrant |
|---|---|---|---|
| 精确匹配 | ✅ | ✅ term | ❌ 本质不支持（payload 过滤弱） |
| 字面模糊 | 🟡 LIKE | ✅ 分词 match | ❌ |
| **语义模糊**（近义） | ❌ | ❌（要配同义词表） | ✅ 向量距离 |
| 过滤+排序 | ✅ | ✅ 强 | 🟡 filter 弱 |

### 4.2 统一 collection 设计（一个库，多 collection）

```
Qdrant/Milvus（一个向量库实例）
  ├── collection: meta_columns     ← 元数据：字段名/描述/别名 向量
  │     payload: table.column      → 回 MySQL meta 表取完整行
  ├── collection: meta_metrics     ← 指标名/描述/别名 向量 → 回表取口径
  ├── collection: episodic_mem     ← 记忆：案例 query/summary 向量 → 回 agent 库
  ├── collection: semantic_rules   ← 记忆：规则 content 向量 → 回表取置信度
  └── collection: rag_knowledge    ← RAG：知识文档/指标描述切块向量 → 回表取原文
```

**铁律：向量库只存"检索入口 + 回指 id"，完整内容、权限、统计、审计永远在 MySQL。**
向量库挂了 = 检索退化（降级 LIKE/关键词），系统变弱但**不丢数据**。

### 4.3 什么时候才值得上向量库

三个条件同时满足：① 查询是模糊的（需要近义匹配）；② 候选集大（几千条以上）；
③ 回表成本可接受（top-k 后回事实层取数据）。
精确查询、小数据集、强治理场景（审计/统计/淘汰）→ 向量库不该是主角。

---

## 5. 多存储增量同步（diff 驱动，替代参考项目的全量重建）

### 5.1 架构：MySQL 事实源 + 派生索引最终一致

```
MySQL meta 表（事实源：meta_tables / meta_fields / meta_values）
   ├──→ Qdrant/Milvus sink：字段/指标向量点（稳定业务 id）
   ├──→ ES sink：字段取值全文（doc id = column_id + value）
   └──→ Redis：不参与同步，只做查询结果缓存失效（TTL 自愈）

apply 顺序：MySQL 最先成功（变更受理）→ 派生索引尽力而为（失败重试）
一致性策略：最终一致，不做跨存储分布式事务（过度设计）
```

### 5.2 增量引擎结构

```
change_set = diff(数仓快照 + 配置变化, MySQL meta 表)   # 粒度到字段
apply（幂等，逐 sink）：
  1. MySQL   : 按业务唯一键 upsert          ← 事实源
  2. 向量库  : delete-by-filter(column_id) + upsert 新向量点   # 必须删旧，防别名残留
  3. ES      : delete_by_query(column_id) + bulk index
每步幂等；MySQL 成功即"变更已受理"，派生索引失败记录待重试
```

### 5.3 前置条件（现在就要做，否则二期返工）

- `MetaField` 加业务唯一键 `(table_name, field_name)`；
  `MetaValue` 加 `(field_name, value)` 唯一索引——否则 upsert 会重复插入。
- `sync_meta.py` 的 apply 层定义 sink 接口
  （`upsert_change(change)` / `delete_change(change)`），
  今天只有 MySQLSink，二期直接加 VectorSink、ESSink——diff 引擎与调用方零改动。

### 5.4 各存储增量姿势

| 存储 | 增量姿势 | 可行性 | 关键前置 |
|---|---|---|---|
| MySQL meta 3 表 | 按业务唯一键 upsert | ✅ 现在能做 | 加唯一索引（见 5.3） |
| 向量库 | 稳定向量点 id + payload 带 column_id，按字段"删旧→插新" | ✅ | id 用稳定业务 id（如 `fact_region_daily.region_code`），**绝不随机生成** |
| ES | doc id = column_id+value 拼接，delete_by_query(column_id)+bulk | ✅ | 按字段整体重建该字段取值，防陈旧值 |
| Redis | 不参与同步，变更后 cache_del 失效 | ✅ 已有 | — |

---

## 6. 与记忆层的关系（统一知识同步引擎）

元数据与记忆的向量化走**同一条同步管道**，只差写入时机与审批策略：

| | 元数据 | 记忆 |
|---|---|---|
| 写入频率 | 低频，diff 驱动 | 高频，任务结束自动沉淀 |
| 审批 | 需审批（LLM 提议 + 人拍板，怕错） | 自动（质量门禁，怕丢） |
| 归属库 | power_insight（业务域） | agent 库（Agent 域） |
| 检索方式 | 精确命中优先（取值反查） | 语义召回优先（相似案例/规则） |

---

## 7. LLM 维护元数据（二期可选）：提议权与生效权分离

**LLM 只做"元数据补全助手"，绝不直接写配置**：

| Tool | 输入 | 适用内容 |
|---|---|---|
| `suggest_meta_update` | table/field/建议描述/别名/取值映射/理由 | 语义层：别名、描述、取值字典 |
| `report_schema_diff` | 数仓快照 vs 元数据库 | 结构层：发现新表/字段变更 |

落地走审批（复用 `harness/approval.py`）：LLM 提议 → 人工确认 → 增量同步生效。

三条红线（为什么 LLM 不能直接写）：
1. **幻觉污染比缺失更可怕**：缺失只召回失败（可重试）；写错别名会静默返回错误数据。
2. **口径是业务权威**：GMV 算哪几列是业务决策，不是生成任务。
3. **"哪些表值得暴露"是治理决策**：临时表/废弃表的筛选标准 LLM 学不会。

---

## 8. 关键设计决策清单（速记）

1. 问数 = 模板化查询（主档）→ 受限 NL2SQL（备档，二期）
2. 元数据知识库是 Agent 前提底座：先理解上下文，再动手查询
3. MySQL 唯一事实源；Qdrant/Milvus + ES 是派生索引；Redis 是热缓存
4. 向量库 = 语义召回引擎，输出候选 id，不做真相/权限/统计
5. 多路召回按"召回对象"分通道，存储按"精确/字面/语义"选
6. 增量同步 = diff 引擎 + sink 接口，幂等应用，最终一致
7. LLM 维护元数据 = 提议权与生效权分离（审批闸门）
8. 全量重建是反模式（参考项目病根）：稳定业务 id + 字段级先删后插
