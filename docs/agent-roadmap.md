# Agent 主链路路线图（阶段交接记忆）

> 本文档是阶段成果存档，供新上下文窗口直接读取。
> 新窗口继续时：**继续 Agent 主链路，从 `schemas/agent.py` 开始**。

## 📚 架构设计文档索引（先读这三份）

| 文档 | 内容 | 状态 |
|---|---|---|
| [agent-knowledge.md](agent-knowledge.md) | 知识层架构：元数据定位、方案对比、多路召回、向量库职责边界、多存储增量同步、LLM 维护元数据 | ✅ 已落盘 |
| [agent-memory.md](agent-memory.md) | 记忆架构：三层记忆实现、semantic+feedback+Milvus 自学习闭环、用户特征、作用域与权限隔离、表结构调整 | ✅ 已落盘 |
| [architecture.md](architecture.md) | 总体架构：分层职责、存储设计、开发顺序 | ✅ 已有 |

> 三份的关系：`architecture.md` 是总图，`agent-knowledge.md` 是知识/检索/同步的深挖，
> `agent-memory.md` 是记忆的深挖。新窗口先读 roadmap 本文件，再按需读对应深挖文档。

---

## 一、已完成（全部实测通过）

### 基础设施

| 项 | 状态 |
|---|---|
| 双库架构 | ✅ agent 库（9 表）+ power_insight 库（14 表） |
| LLM 接入 | ✅ DeepSeek 调通 + Function Calling 验证 |
| 环境 | ✅ conda `langchain_demo`，Docker 三件套运行中 |

### 数据层（power_insight 库）

```
东莞维度：dim_region(32) / dim_line(96) / dim_taiqu(288) / dim_user(3200) / dim_meter(3200)
东莞汇总：fact_region_daily(1920) / fact_line_loss(5760) / fact_taiqu_daily(17280)
指标字典：metric_definitions(6)
旧表：region_daily_metrics / line_loss_details（待清理）
```

seed 参数（seed_dongguan.py）：32 镇街 × 3 线路 × 3 台区，每镇街 100 样例用户，
事实表覆盖最近 60 天（32×60=1920，96×60=5760，288×60=17280）。

### 双库架构（最新）

```
agent 库          ← Agent 域：任务 5 表 + 记忆 4 表（AgentBase）
power_insight 库  ← 业务域：东莞 8 表 + 指标 1 + 元数据 3（BusinessBase）
```

### 本轮新增：元数据知识库（Agent 前提底座）

```
models/metadata.py        3 表（MetaTable/MetaField/MetaValue）
scripts/seed_meta.py      灌入 8 表 + 13 字段 + 12 取值
repositories/meta_repository.py  检索接口（含 build_context 上下文组装）
验证：表列表/字段检索/取值反查（虎门镇→DG012）/上下文 998 字符 ✅
```

### 已就绪的 Agent 资产

```
infra/llm_gateway.py    DeepSeek 调用 + Function Calling + token 统计 ✅
tools/base.py + registry  工具框架（Pydantic schema）✅
tools/query_tools.py   5 个真实问数工具（接 DongguanRepository）✅
schemas/agent.py        内部数据契约（IntentResult/QueryRequest/QueryResult/ReportInput/AgentTurn）✅
orchestration/           context/state/graph + route/act/report/clarify 节点 ✅
harness/                 task_manager（状态机）+ runtime（执行入口）✅
app/workers/            analysis_worker（后台执行）+ POST /tasks 触发 ✅
```

---

## 二、Agent 主链路（✅ 已跑通，端到端实测）

```
POST /tasks → 后台执行 → 意图解析(route) → 反查 region_code(act)
  → 模板化查询(工具) → 报告(report) → 落库 + 任务终态
```

**实测结论**（真实 DeepSeek + 真实 MySQL）：
- ✅ "虎门镇近7天线损率" → SUCCEEDED，7 行数据 + LLM 洞察 + 报告落库
- ✅ "查一下线损"（参数不全）→ NEEDS_CLARIFICATION，生成追问
- ✅ 状态机：CREATED→RUNNING→SUCCEEDED/FAILED/NEEDS_CLARIFICATION

**过程中的关键修复（reflection 抓到的真实 bug）**：
1. `_serialize_row` 只转 date 不转 Decimal → 工具层输出 Decimal 对象，改为全量 JSON 化
2. LLM 只填 region_name 不填 region_code → act 节点补 region_name→region_code 反查（元数据取值字典）
3. clarify 后仍走 report → report 读空 result 崩溃，改为 clarify 直接 END
4. `missing_params` 对 UNKNOWN 返回空 → 补 ["intent"] 分支

---

## 三、下一步（二期，未阻塞主链路）

```
□ 记忆模块接入（memory/ 六个占位文件 → episodic/semantic 沉淀）
□ 受限 NL2SQL 备档（多路召回 + Milvus 语义检索）
□ 用户特征表 user_profiles + 作用域过滤落地
□ 报告内容前端展示（app/static/index.html 接报告 API）
□ 任务失败重试 + 幂等（harness/ 已有占位）
```

---

## 四、关键设计决策（已定的，别丢）

1. **双库物理隔离**：AgentBase→agent 库，BusinessBase→power_insight 库
2. **不按地区分表**：region_code + 复合主键
3. **问数=模板化查询**：不自由 NL2SQL，LLM 只提取参数（规避 SQL 注入/明细扫描）
4. **DataAgent 独立**（模块+节点，不独立部署），架构文档早有规划
5. **元数据先于 Agent**：先理解上下文再动手（region_name→region_code 反查靠元数据）
6. **LangGraph 已用**（orchestration/ 是落点，图已装配）
7. **LLM 缓存**（二期：Redis fingerprint）

---

## 五、待办/隐患

- `metric_definitions` 在 seed_dongguan 里灌了，元数据 seed 单独跑（seed_meta.py）
- 评审遗留 P0：权限进缓存 key、NL→SQL 守卫（模板化已缓解，见 agent-knowledge.md）
- **二期增强**：记忆模块接入、受限 NL2SQL 备档、user_profiles、前端展示、重试幂等
  （见上面"三、下一步"清单）
- ✅ ~~seed 取值字典不全~~：已改为从 REGIONS 自动生成 32 镇街映射（38 条取值），
  反查 32/32 通过
