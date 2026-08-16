# PowerInsight Agent 面试讲解指南

> 目标：不是背代码，而是让面试官相信"这个系统是你想清楚之后设计出来的"。
> 心法：**讲"决策"不讲"功能"** —— 每个模块都能回答两个问题：
> 1. 为什么这样做？
> 2. 不这样做会有什么问题？

---

## 1. 电梯陈述（30 秒，第一句话定调）

> "我做的是一个面向**电力营销与经营分析**场景的**多智能体数据分析平台**。
> 用户用自然语言提问（比如'分析某区域近 30 天线损率异常的原因'），系统经过**任务编排、数据查询、指标计算、异常归因、知识检索**，
> 最终输出**带数据依据、知识引用和执行轨迹**的分析报告。
> 它不是一个通用聊天机器人，而是一套**可观测、可评测、可审计**的 Agent 工程底座。"

**要点**：一句话里包含 4 个信息——行业（电力）、形态（多 Agent）、能力（分析闭环）、差异化（可观测/可评测/可审计，不是 chatbot）。

---

## 2. 完整讲解脚本（3-5 分钟）

### 2.1 业务背景（30 秒）——先讲"为什么做"

电力行业的真实痛点，讲 3 个就够：

1. **指标口径混乱**：线损率、回收率这些指标，业务部门各算各的，口径不统一。
2. **分析依赖人工**：经营分析靠人去营销/计量/财务系统里查数、拼表、写报告，慢且容易错。
3. **数据分散**：营销、计量、告警、财务是不同系统，天然需要统一接入和标准化。

**你的解法**：把"指标口径"固化成代码（`domain/` 层），把"查数、分析、写报告"变成 Agent 可编排的流程，把"依据和引用"做成强制要求。

### 2.2 整体架构（2 分钟）——按层讲，每层一句话 + 一个为什么

对着架构图画（面试时主动要求画图，会加分）：

```
Client (Web/CLI/BI/定时任务)
   ↓ HTTP/SSE
FastAPI 接入层        → 认证、参数校验、任务提交、SSE 流式
   ↓
Agent Harness         → 任务生命周期、工具注册、策略守卫、预算、审批、审计、评测
   ↓
LangGraph 编排        → Route→Clarify→Plan→Retrieve→Act→Observe→Review→Report
   ↓
业务 Agent / 工具 / 知识
   ↓
Kafka 事件层          → 数据接入、异步解耦
   ↓
MySQL / Redis / Milvus
```

每层的话术：

| 层 | 一句话话术 | 为什么（追问回答） |
|---|---|---|
| FastAPI | "统一接入层，只做接入不承载业务决策" | 异步高性能、Pydantic 强校验、SSE 推流、天然出 OpenAPI 文档 |
| Harness | "保证 Agent 不是一次性的模型调用，而是可管理的工程运行时" | 没有它，Agent 就是裸调 LLM：无预算失控、无权限检查、无审计、挂了不能恢复 |
| LangGraph | "单任务内部的状态图和节点编排" | 相比 LangChain 的 AgentExecutor，它有显式状态、可 checkpoint 恢复、可人工介入 |
| 业务 Agent | "按职责拆 5 个：Metric/Data/Anomaly/Reviewer/Report" | 单一职责，每个 Agent 只做一件事，Reviewer 独立于生成者才可能纠错 |
| domain 层 | "确定性业务公式用代码写死，不交给 LLM" | 线损率=1-售电量/供电量这种公式，LLM 可能算错，代码永远算对 |
| 存储 | "MySQL 存事实和审计，Redis 存运行时状态，Milvus 存知识向量" | 各取所长：事务一致性 / 高频低延迟 / 语义检索 |

### 2.3 三个核心闭环（30 秒）——证明"有业务主线"

第一版只做三件事，讲的时候要有"边界意识"（面试官很看重这个）：

1. **指标查询**：自然语言问"本月某区域售电量"→ SQL 工具查数 → 指标计算 → 返回
2. **异常分析**："找出高损线路" → 同比/环比/阈值检测 → 归因 → 输出异常明细
3. **带引用的经营报告**：结论必须有数据依据和知识引用，Reviewer 审核后才发

**加分句**："第一版我刻意砍掉了 Kafka、真实电力 API、自动工单，因为这些基础设施会冲淡业务主线。它们作为第二阶段演进，架构上已预留位置。"

### 2.4 五个关键设计亮点（挑 2-3 个展开讲）

**亮点 A：确定性逻辑与 LLM 分离（最推荐讲）**
> "我把能确定的计算全部下沉到 `domain/` 层——线损率、同比环比、峰谷比、异常等级判定，都是纯函数，不依赖 LLM 和框架。LLM 只负责理解意图、编排计划、生成措辞。这样指标结果 100% 可复现，评测也简单。"
> 面试官如果问"为什么"，答："大模型做算术和公式容易出错，且不可复现；业务公式是领域知识，用代码固化才是可靠的。"

**亮点 B：Reviewer 独立审查（防幻觉）**
> "生成报告的 Agent 和审查报告的 Reviewer 是分开的。Reviewer 检查三件事：结论是否有数据支持、指标口径是否正确、引用是否真实存在。相当于生成者和质检员分离。"
> 追问"怎么检查引用是否真实"：答"引用指向 RAG 命中的文档 ID 和数据行，Reviewer 会回查这些 ID 是否在检索结果集里，找不到就标记待人工确认。"

**亮点 C：Harness 的预算与审批**
> "每个任务有 Token 预算、步骤上限、超时和成本上限，超了就强制收敛；高风险动作（创建工单、修改业务状态）必须经过 PolicyGuard 检查 + 人工审批，任务挂起等审批，批准后从 checkpoint 恢复。"
> 追问"checkpoint 恢复怎么做"：答"LangGraph 的状态是可序列化的，每一步执行完存快照，审批通过后用保存的状态继续跑，不用重头来。"

**亮点 D：RAG 的混合检索与引用**
> "知识检索走 Query Rewrite → BM25 + 向量双路 → RRF 融合 → Reranker 重排，保证召回率和精度。检索的是指标口径、政策文件、业务规则，让 Agent 的回答有据可依。"

**亮点 E：全链路可观测**
> "每个请求一个 trace_id 贯穿 API→任务→节点→工具→LLM→存储。重点监控：Agent 成功率、各节点耗时、Token 成本、RAG 召回率、人工审批比例。"

### 2.5 演进规划（30 秒）——展示"你想过未来"

> "架构上分四期：一期做核心闭环（已设计）；二期加 Harness 工程化（MCP、审批、checkpoint、评测）；三期接 Kafka 异步和真实电力 API 数据接入；四期做生产化（多租户、高可用、安全审计）。"
> 加分句："Kafka 的 topic 设计、事件 schema（event_id/task_id/trace_id/tenant_id）、死信队列，我在架构文档里已经定义好了，二期直接落地。"

---

## 3. 高频面试题 Q&A

**Q1: 这个项目是你一个人做的？你负责什么？**
> "独立设计架构、定开发顺序、实现代码。从架构文档、目录设计到核心模块都是我自己写的。选这个方向是因为我有电力行业背景/兴趣（如实说），且它能把 RAG、Agent、工程化三个点都串起来。"

**Q2: 为什么用 LangGraph，不用 LangChain 自带的 Agent？**
> "LangChain 的 AgentExecutor 是黑盒循环，状态不可见、不可恢复、不好介入。LangGraph 是显式状态图：节点、边、状态都是可编程的，支持 checkpoint 持久化，能实现'观察→重试→人工审批→恢复'这种复杂控制流。我们的流程是 8 个节点 5 条边，图是可控的。"

**Q3: 为什么拆 5 个 Agent？多 Agent 比单 Agent 好在哪？**
> "单一职责 + 独立优化。Reviewer 必须独立于生成者才能起到质检作用；Metric Agent 的 prompt 和工具集可以单独迭代，不影响其他部分。坏处是编排复杂、延迟增加——所以每个 Agent 只是轻量封装，重逻辑在工具和 domain 层，避免 Agent 间来回传话。"

**Q4: 怎么防止 LLM 编造数据？**
> "三层防线：① 数据全部来自工具执行结果，Agent 只允许引用真实返回值；② Reviewer 独立核查结论与引用的对应关系；③ 报告强制带数据依据和引用 ID，没有依据的结论不允许输出。另外 SQL 工具是只读的，从机制上杜绝写操作。"

**Q5: 指标口径怎么保证？**
> "口径不是写在 prompt 里让 LLM 理解，而是写在 `domain/metrics.py` 的代码里，用 MetricDefinition 注册。LLM 只是把用户问题映射到具体指标 ID，计算走代码。口径变更改代码 + 回归测试，不靠调 prompt。"

**Q6: 人工审批的流程？**
> "工具按风险分级。高风险工具调用时，Harness 的 ApprovalManager 把任务状态置为 WAITING_APPROVAL，生成审批请求（动作、参数、上下文、风险说明），通过 API 暴露给人工端。人工批准后从 checkpoint 恢复继续执行；拒绝则终止并记录原因。审批记录进审计。"

**Q7: 预算控制怎么做的？**
> "BudgetManager 在每一步执行前后检查四个维度：步骤数、Token 数、耗时、估算成本。超限有两种策略：软限（收敛到报告节点，给部分结果）和硬限（直接终止标记 FAILED）。每个任务创建时从配置读取预算，可在租户级别覆盖。"

**Q8: 怎么评测一个 Agent 系统？**
> "Golden Set：每个问题配标准答案/关键中间步骤/允许的工具序列。运行时打分：意图识别对不对、计划质量、工具选择、SQL 可执行性、结果正确性、RAG 召回、引用准确、延迟成本。每次改 prompt/模型/RAG 都跑回归对比，用评分差决定是否上线。"

**Q9: 数据从哪来？**
> "一期用模拟数据（seed 脚本生成营销/计量/线损模拟表），保证闭环可跑。二期接真实电力 API：Adapter 负责鉴权、分页、限流、字段标准化，Ingestion 负责去重、质量检查、游标管理，经 Kafka 进 MySQL。"

**Q10: 项目最大的难点/挑战？**
> （选一个真实的讲）"最难的其实是想清楚'哪些交给 LLM、哪些不交给 LLM'。一开始容易什么都让 Agent 干，后来发现确定性计算必须下沉到代码层，LLM 只做理解和编排。这个认知直接决定了 domain 层的设计。第二个难点是编排的健壮性——工具报错、空结果、超时这些分支都要在 Observe 节点处理，而不是让流程直接挂掉。"

**Q11: 和通用 RAG 问答系统比，你这个强在哪？**
> "通用 RAG 是'检索-拼 prompt-生成'，没有任务概念、没有工具、没有校验。这个项目是完整的 Agent 工程：任务有生命周期和状态机，能调工具拿真实数据，有预算有审批有审计，输出可评测。RAG 只是其中一个 Retrieve 节点。"

---

## 4. 诚实边界与补课清单（重要！）

**面试前必须认清的现状**：代码目前只完成了配置层和依赖体系，其余是结构占位（有完整设计文档）。所以：

**✅ 现在就能讲的**（设计层，讲"我设计时……"）：架构分层、开发顺序、目录职责、技术选型理由、上面所有 Q&A——这些都基于你写透的架构文档，讲起来是扎实的。

**⚠️ 讲的时候注意措辞**：
- 用"我设计为……" "架构上是……" "计划中……"，不要用"我们已经实现了……"去描述没写的代码
- 如果面试官追问"代码在哪"，诚实说："目前完成了工程骨架和配置层，核心链路我正在按开发顺序实现，第一个可运行闭环是 XX（按你实际进度说）"——**诚实 + 展示进度规划**，比吹牛好得多

**🔧 面试前建议补的最小闭环**（按这个顺序，每项都是可演示的增量）：
1. `db/mysql.py` 异步连接 + `scripts/init_db.py` 建 2-3 张核心表（analysis_tasks、analysis_reports）
2. `repositories/` 一个 Repository + FastAPI 两个接口（提交任务、查状态）
3. `harness/task_manager.py` 状态机（CREATE→RUNNING→SUCCEEDED/FAILED）
4. `orchestration/` 最小链路：Route→Plan→Act→Report（先不接 LLM，用规则路由）
5. `domain/metrics.py` 线损率等 2-3 个公式 + 单测

完成到第 4 步，你就有"可运行的最小 Agent 闭环"可演示了。

**面试官如果现场让你画**：
- 架构分层图（§2.2 那张）
- 任务状态机：CREATED→PLANNING→RUNNING→REVIEWING→SUCCEEDED / RETRYING / WAITING_APPROVAL / FAILED
- LangGraph 节点图：Route→Clarify→Plan→Retrieve→Act→Observe→Review→Report（Observe 有回 Act 的环）
- 一次任务时序：用户→API→Harness→Graph→工具→MySQL→报告→审计

---

## 5. 面试表述模板（熟读，但要用自己的话讲）

> "我设计的是一个面向电力营销场景的 Agent 平台。FastAPI 负责统一接入，Agent Harness 负责任务生命周期、权限、预算、重试、审批和评测，LangGraph 负责单任务状态编排，MySQL 保存业务事实和审计数据，Redis 管理运行时状态与缓存，Milvus 支持指标和政策知识检索，Kafka 解耦电力数据接入和批量分析，MCP 统一外部电力工具协议。系统最终形成从数据接入、知识检索、Agent 推理到报告和审计的完整闭环。"

---

# 参考项目架构学习笔记：SQL-Reconciliation-Agent 的解耦设计

> 参考项目：`E:\worke_1\SQL-Reconciliation-Agent`（企业级多 Agent SQL 对账平台）
> 学习重点：它的"解耦"架构思想，以及如何借鉴到 PowerInsight Agent。

---

## 0. 参考项目一句话

输入"对比昨天直播 GMV 和订单金额的差异"，输出差异报告 + 根因分析。
技术栈：LangGraph 状态机 + ReAct + RAG Schema 检索 + 三层记忆 + 自进化。

**它最值得学的不是功能，而是 v2 重构时沉淀的 7 个解耦模式。**

---

## 1. 七大解耦模式

### ① Context 解耦：AgentContext 单一共享（最核心）

**解耦什么**：节点/工具与"依赖获取方式"解耦。

**怎么解耦**：所有 Node、所有 Tool 不自己创建依赖（LLM/记忆/RAG/工具/预算/追踪），
统一通过一个 `AgentContext` 取。v1 的痛点是"两个 Agent 各自持有一套依赖"，
v2 改成"一个 context 贯穿全程"。

```python
@dataclass
class AgentContext:
    trace_id: str; session_id: str
    query: str; intent: Intent
    memory: MemoryStore; rag: HybridRetriever
    tools: ToolRegistry; llm: LLMGateway; tracer: Tracer
    budget: CostBudget; step_counter: int; mode: str
```

**细节**：LangGraph 的 GraphState 必须可序列化，所以 context 不直接进 state，
而是通过 `ctx_id` 间接挂载（`ctx_registry` / `ctx_store`）。

**对我们的启示**：我们的 `orchestration/context.py` 就是干这个的——将来节点
和工具都从 context 取能力，不各自 new。

---

### ② 分层解耦：L1-L5 五层架构

**解耦什么**：关注点按"变更频率 + 抽象层级"分层，依赖只允许向下。

```
L5 Interface     CLI / FastAPI / Notebook
L4 Orchestration LangGraph 状态机（route→plan→act→observe→reflect）
L3 Capability    Tools / Memory / RAG / Evolution（可插拔能力）
L2 Infrastructure LLM Gateway / SQL Safety / OTel / Eval（通用底座）
L1 Storage       SQLite / Qdrant / Redis
```

**对我们的启示**：我们已有类似分层（app / orchestration / tools / infra / db），
但缺一个明确原则：**Capability 层只依赖 Infrastructure，不反向依赖 Orchestration**。

---

### ③ 规则解耦：Rules 模块（新增意图只改一个文件）

**解耦什么**：业务规则（意图分类、守卫条件）与节点执行逻辑解耦。

**怎么解耦**：`orchestration/rules/` 下 `intent_rules.py`（8 类意图）和
`recon_guard.py`（守卫规则）。新增一种意图 = 在 rules 文件加一条，
节点逻辑一行不动。

**对我们的启示**：我们已建了 `orchestration/rules/`（intent_rules.py、
transition_rules.py）——设计完全一致，这是我们的架构文档早就规划好的。

---

### ④ 工具解耦：Pydantic Schema，拒绝反射魔法

**解耦什么**：工具的"定义"与"LLM 协议"解耦；输入输出与实现解耦。

**怎么解耦**：每个工具声明 `input_schema` / `output_schema`（Pydantic），
`to_openai_function()` 把 schema 转成 Function Calling 格式——
**换 LLM 协议不用改工具实现**。

```python
class ToolBase(ABC):
    name: str
    description: str
    input_schema: Type[ToolInput]
    output_schema: Type[ToolOutput]
    def run(self, ctx, inp) -> ToolOutput: ...
    def to_openai_function(self) -> dict: ...
```

**原则名**："Schema-Over-Magic"——用显式 schema，反对 `@tool_action` 反射。

**对我们的启示**：我们的 `tools/base.py` 占位，应直接对齐这个设计。

---

### ⑤ 基础设施解耦：LLM Gateway / SQL Safety / 方言适配

**解耦什么**：通用底座各自独立，业务不直接碰厂商 API 和裸 SQL。

| 模块 | 解耦点 |
|---|---|
| LLM Gateway（litellm） | 多厂商统一接口 + 缓存 + 重试 + 成本记账，调用方不感知厂商 |
| SQL Safety（sqlglot AST） | 安全校验独立于执行器；AST 级拦截（v1 黑名单 `"DELETE" in sql` 会被 `/* DELETE */` 绕过） |
| Dialect Adapter | SQLite/MySQL/ClickHouse/Hive 方言自动适配 |

**对我们的启示**：`infra/llm_gateway.py` 按 Gateway 模式写；
`harness/policy_guard.py` 的 SQL 检查**必须用 AST（sqlglot），不是关键字黑名单**——这是安全的正确姿势。

---

### ⑥ 存储解耦：向量后端可插拔

**解耦什么**：检索逻辑与具体向量库解耦（Qdrant / Milvus / JSON 可切换）。

**我们的启示**：我们已选型 Milvus，`rag/milvus_store.py` 之外应有
一个 `VectorStore` 抽象接口，Milvus 是其中一个实现。

---

### ⑦ 决策解耦：ADR（Architecture Decision Records）

**解耦什么**：每个关键决策的"当时为什么这么选"与代码分离沉淀。

**怎么解耦**：`docs/v2/adr/ADR-001-langgraph.md` 等，固定结构：
Context（问题）→ Decision（决定）→ Consequences（代价）→ Alternatives（备选）。

**面试价值**：能讲出"我对比过 AutoGen/CrewAI/LCEL，最后选 LangGraph 因为
状态机显式 + checkpoint"，比"我用了 LangGraph"高一个档次。

**对我们的启示**：我们 docs/ 下应建 `decisions/` 目录，写 2-3 个 ADR
（如：为什么 SQLAlchemy 2.0 async、为什么 Milvus、为什么 domain 层代码化）。

---

## 2. 对照表：参考项目 vs PowerInsight

| 解耦模式 | 参考项目 | 我们的现状 | 差距 |
|---|---|---|---|
| Context 共享 | AgentContext 贯穿 | `orchestration/context.py` 占位 | 未实现 |
| 五层分层 | L1-L5 明确 | 目录类似但无依赖规则文档 | 部分 |
| Rules 解耦 | intent_rules + recon_guard | 目录已建 | 未实现 |
| Tool Pydantic | ToolBase + Schema | `tools/base.py` 占位 | 未实现 |
| LLM Gateway | litellm + cache + cost | `infra/llm_gateway.py` 占位 | 未实现 |
| SQL AST 安全 | sqlglot | `harness/policy_guard.py` 占位 | 未实现 |
| 存储可插拔 | VectorStore 抽象 | 已选 Milvus | 可加接口 |
| ADR 记录 | 5 个 ADR | 无 | 未开始 |
| Eval-Driven | Golden Set 先行 | `evaluation/` 占位 | 未实现 |

---

## 3. 落地建议（结合我们的开发顺序）

我们的下一步刚好是 orchestration / tools / infra 三块，直接吸收：

1. **高优先**（写代码时直接采用）：
   - `orchestration/context.py` → AgentContext 共享模式（ctx_id 间接挂载）
   - `tools/base.py` → ToolBase + Pydantic input/output schema
   - `harness/policy_guard.py` → sqlglot AST 只读校验（非黑名单）
2. **中优先**：
   - `infra/llm_gateway.py` → 统一网关（openai SDK 兼容 deepseek）+ 缓存 + 成本
   - `docs/decisions/ADR-001-*.md` → 写 2 个 ADR 沉淀已做的决策
3. **后置**：Eval-Driven（Golden Set）、VectorStore 抽象、自进化

---

## 4. 参考项目的面试叙事（可借鉴的讲故事方式）

v2 文档里有"故事化叙事"，结构是：**发现 v1 三个问题 → 重构 → 量化收益**。
例子：
> "v1 我自研了一套 mini Agent 框架，跑通后自己做 code review，发现三个问题：
> 双层 Agent 没共享 context、记忆没有真正的 promotion、自进化没有质量门槛。
> 所以 v2 切到 LangGraph，引入 AgentContext 共享、Sandbox 质量门槛、Eval-Driven 改造。
> 最大收获：Agent 工程的难点不在框架，而在评测、可观测和经验沉淀的 governance。"

我们的项目也可以这么讲：从"哪些交给 LLM、哪些不交给 LLM"的认知迭代切入。
