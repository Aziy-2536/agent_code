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
