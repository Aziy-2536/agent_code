# PowerInsight Agent 开发顺序与目录职责

## 1. 推荐开发顺序总览

项目建议按照“先业务闭环，再工程增强，最后接入真实数据”的顺序开发。

```text
阶段 0：业务模型和模拟数据
        ↓
阶段 1：基础设施和数据访问
        ↓
阶段 2：FastAPI 与任务管理
        ↓
阶段 3：LangGraph Agent 主流程
        ↓
阶段 4：工具体系和电力业务能力
        ↓
阶段 5：RAG 与记忆
        ↓
阶段 6：Harness 安全、预算、审批和恢复
        ↓
阶段 7：Kafka 异步任务和数据同步
        ↓
阶段 8：评测、可观测性和部署
```

## 2. 开发阶段顺序表

| 顺序 | 阶段 | 主要内容 | 产出 | 依赖 |
|---:|---|---|---|---|
| 0 | 业务建模 | 明确电力指标、数据表、分析场景和报告格式 | 指标字典、领域模型、模拟数据 | 无 |
| 1 | 基础设施 | 配置 MySQL、Redis、Milvus、统一配置和日志 | 可运行基础服务 | 阶段 0 |
| 2 | 数据访问 | SQLAlchemy Repository、数据模型、指标查询接口 | 可稳定访问业务数据 | 阶段 1 |
| 3 | FastAPI | API、认证、任务创建、状态查询、报告查询 | HTTP 服务入口 | 阶段 2 |
| 4 | 任务 Harness | Task Manager、状态机、幂等、预算、超时 | 可管理的 Agent 任务 | 阶段 3 |
| 5 | LangGraph 主流程 | Route、Clarify、Plan、Act、Observe、Review、Report | 单任务 Agent 闭环 | 阶段 4 |
| 6 | 基础工具 | Schema、SQL、指标计算、异常检测、报告工具 | Agent 可调用能力 | 阶段 5 |
| 7 | 电力业务 Agent | Metric、Data、Anomaly、Reviewer、Report Agent | 面向电力场景的业务能力 | 阶段 6 |
| 8 | RAG | 文档切分、向量化、Milvus 检索、重排、引用 | 指标和政策知识检索 | 阶段 1、7 |
| 9 | 记忆 | Working、Episodic、Semantic Memory | 多轮上下文和经验沉淀 | 阶段 2、8 |
| 10 | MCP | 电力数据、告警、政策和工单 MCP Server | 标准化外部工具 | 阶段 6、7 |
| 11 | 人工审批 | 高风险动作确认、Checkpoint 恢复 | Human-in-the-loop | 阶段 4、5 |
| 12 | Kafka | 异步分析、数据同步、异常事件和报告任务 | 削峰填谷、服务解耦 | 阶段 3、7 |
| 13 | API Connector | 接入营销、计量、告警和财务 API | 真实数据接入 | 阶段 1、12 |
| 14 | 评测 | Golden Set、执行准确率、RAG 和安全评测 | 回归评测报告 | 阶段 5、8 |
| 15 | 可观测性 | Trace、Metrics、成本、Kafka 延迟、错误告警 | 运维监控能力 | 阶段 3、5、12 |
| 16 | 部署 | Docker Compose、环境配置、启动脚本和文档 | 可复现部署 | 阶段 1-15 |

## 3. 第一版最小可行范围

第一版不需要一次开发全部目录，只实现以下链路即可：

```text
用户问题
  ↓
FastAPI
  ↓
Task Harness
  ↓
LangGraph
  ↓
SQL / 指标 / 异常工具
  ↓
MySQL
  ↓
RAG 检索指标口径
  ↓
分析报告
```

第一版建议包含：

```text
app/api/
config/
db/
models/
repositories/
schemas/
harness/
orchestration/
tools/
domain/
rag/
tests/
deploy/
```

Kafka、真实电力 API 和自动工单可以在第二阶段加入。

## 4. 推荐目录结构

```text
power_insight_agent/
├── app/
│   ├── api/
│   ├── cli/
│   └── workers/
├── config/
├── db/
├── models/
├── repositories/
├── schemas/
├── harness/
├── orchestration/
├── agents/
├── domain/
├── tools/
├── mcp/
├── adapters/
├── ingestion/
├── rag/
├── memory/
├── infra/
├── evaluation/
├── tests/
├── data/
├── scripts/
├── docs/
└── deploy/
```

## 5. 各文件夹职责

### 5.1 `app/`

应用启动和外部服务入口。

```text
app/
├── api/       FastAPI 路由、中间件、依赖注入
├── cli/       命令行启动、调试和演示入口
└── workers/   Kafka Consumer、异步任务 Worker
```

`app/` 只负责启动和接入，不放核心 Agent 业务逻辑。

### 5.2 `config/`

统一管理配置：

- MySQL、Redis、Milvus、Kafka 地址
- LLM Provider 和模型配置
- JWT、租户和权限配置
- 超时、重试和成本预算
- 开发、测试、生产环境差异

建议使用 Pydantic Settings，避免业务代码直接读取环境变量。

### 5.3 `db/`

数据库连接和基础设施：

- MySQL Engine 和 Session
- Redis Client
- Milvus Client
- Kafka Producer/Consumer 基础封装
- 数据库初始化和迁移

只负责连接和生命周期，不定义业务查询。

### 5.4 `models/`

持久化模型，对应 MySQL 表：

```text
User
Tenant
AnalysisTask
TaskStep
ToolCall
AnalysisReport
MetricDefinition
DataSyncJob
DataSyncCursor
AnomalyRecord
HumanApproval
AuditLog
EvaluationRun
```

### 5.5 `repositories/`

数据访问层，封装具体数据库操作：

- `task_repository.py`
- `report_repository.py`
- `metric_repository.py`
- `sync_repository.py`
- `audit_repository.py`

Agent 和 API 不直接拼接 SQL 查询业务表，而是通过 Repository 访问。

### 5.6 `schemas/`

所有输入输出的数据契约：

- API Request/Response
- Agent 状态 Schema
- Tool Input/Output
- Kafka Event Schema
- MCP Tool Schema
- Report Schema

建议统一使用 Pydantic，保证模型、工具和接口之间的数据结构明确。

### 5.7 `harness/`

Agent 工程化运行时控制层，是整个项目的核心基础设施之一。

```text
harness/
├── task_manager.py       任务创建、取消、重试和状态转换
├── runtime.py            Agent 运行时包装器
├── tool_registry.py      工具注册和工具过滤
├── policy_guard.py       权限、安全和风险动作检查
├── budget_manager.py     Token、步骤、时间和成本预算
├── retry.py              LLM 和工具重试策略
├── checkpoint.py         LangGraph 状态保存和恢复
├── approval.py           人工审批流程
├── idempotency.py        任务和消息幂等
└── audit.py              全链路审计记录
```

Harness 不负责某个具体电力业务，而是保证所有 Agent 安全、稳定、可恢复地运行。

### 5.8 `orchestration/`

LangGraph 工作流编排：

```text
orchestration/
├── graph.py              StateGraph 装配
├── state.py              GraphState 定义
├── context.py            AgentContext
├── nodes/
│   ├── route.py          意图识别
│   ├── clarify.py        澄清问题
│   ├── plan.py           任务规划
│   ├── retrieve.py       RAG 和记忆检索
│   ├── act.py            工具执行
│   ├── observe.py        结果观察
│   ├── review.py         结果审查
│   └── report.py         报告生成
└── routing.py            条件边和状态跳转规则
```

这里负责“先做什么、后做什么”，不应该塞入大量数据库细节。

### 5.9 `agents/`

面向不同职责的业务 Agent：

```text
agents/
├── metric_agent.py       指标口径理解和计算
├── data_agent.py         数据查询和数据核查
├── anomaly_agent.py      异常检测和原因分析
├── reviewer_agent.py     事实、权限和引用审查
└── report_agent.py       结构化报告生成
```

Agent 负责业务推理策略，具体数据库和 API 调用交给 `tools/` 或 `mcp/`。

### 5.10 `domain/`

电力领域核心业务逻辑，不依赖 LLM：

- 线损率计算
- 同比和环比计算
- 峰谷比计算
- 欠费率计算
- 指标阈值判断
- 异常等级定义
- 区域、线路、台区等领域对象

这一层非常重要，因为可确定的业务公式应由代码完成，而不是交给大模型自由推理。

### 5.11 `tools/`

供 Agent 调用的内部工具：

```text
tools/
├── sql_query_tool.py
├── schema_tool.py
├── metric_tool.py
├── anomaly_tool.py
├── comparison_tool.py
├── report_tool.py
└── tool_base.py
```

每个工具都应定义：

- 输入 Schema
- 输出 Schema
- 权限要求
- 是否允许自动调用
- 超时和重试策略
- 审计级别

### 5.12 `mcp/`

MCP 客户端和服务端实现：

```text
mcp/
├── client.py              Agent 侧 MCP Client
├── server.py              Power MCP Server 启动入口
├── tools/
│   ├── metering.py        计量数据工具
│   ├── policy.py          政策查询工具
│   ├── alarm.py           设备告警工具
│   └── ticket.py          工单工具
└── schemas.py             MCP 输入输出协议
```

内部数据库查询可以先使用普通 Tool；需要跨服务或外部系统的能力，再封装为 MCP Tool。

### 5.13 `adapters/`

外部电力系统适配器：

```text
adapters/
├── marketing_api.py       营销系统
├── metering_api.py        计量系统
├── finance_api.py         财务或收费系统
├── device_alarm_api.py    设备告警系统
├── file_adapter.py        Excel、CSV、PDF 等文件
└── base.py                统一 Adapter 接口
```

Adapter 负责把外部系统格式转换为内部标准模型，避免 Agent 绑定第三方 API 的字段结构。

### 5.14 `ingestion/`

数据接入、清洗和同步：

```text
ingestion/
├── sync_service.py        全量和增量同步
├── normalizer.py          字段标准化
├── quality_checker.py     数据质量检查
├── deduplicator.py        去重和幂等
├── cursor_manager.py      同步游标
└── event_publisher.py     发布 Kafka 事件
```

`adapters/` 负责“怎么访问外部系统”，`ingestion/` 负责“如何把数据可靠地接入平台”。

### 5.15 `rag/`

知识库和检索能力：

```text
rag/
├── chunker.py             文档切分
├── embedder.py            向量化
├── milvus_store.py        Milvus 存取
├── keyword_retriever.py   BM25 或关键词检索
├── dense_retriever.py     向量检索
├── fusion.py              RRF 融合
├── reranker.py            重排
├── query_rewriter.py      查询改写
└── citation.py            引用和来源管理
```

知识来源包括指标字典、政策文件、数据说明、业务规则和历史分析案例。

### 5.16 `memory/`

Agent 记忆系统：

```text
memory/
├── working.py             当前任务上下文
├── episodic.py            历史任务和执行案例
├── semantic.py            长期业务规则和经验
├── retriever.py           记忆检索
├── consolidator.py        经验总结和升级
└── feedback.py            用户反馈和使用统计
```

长期记忆必须经过去重、审核和质量门禁，不能把所有对话直接写入知识库。

### 5.17 `infra/`

通用基础设施能力：

```text
infra/
├── llm_gateway.py         多模型统一调用
├── cache.py               LLM 和查询缓存
├── tracing.py             Trace 和 Span
├── logging.py             结构化日志
├── metrics.py             Prometheus 指标
├── security.py            加密、脱敏和密钥管理
└── circuit_breaker.py     熔断和降级
```

### 5.18 `evaluation/`

Agent 评测 Harness：

```text
evaluation/
├── golden_set.py          标准问题集
├── runner.py              批量运行 Agent
├── graders.py             多维评分器
├── metrics.py             Accuracy、MRR、Recall、成本等
├── regression.py          版本回归比较
└── reports.py             评测报告
```

重点评测：意图、工具选择、SQL 执行、结果正确性、RAG 引用、安全和成本。

### 5.19 `tests/`

自动化测试：

```text
tests/
├── unit/                  单元测试
├── integration/           MySQL、Redis、Milvus 集成测试
├── contract/               API、MCP、Kafka 契约测试
├── workflow/               LangGraph 流程测试
├── security/               SQL、权限和数据脱敏测试
└── evaluation/             Agent 质量回归测试
```

### 5.20 `data/`

仅保存开发、测试和示例数据：

- 模拟电力业务数据库
- 测试指标字典
- 示例政策文档
- Golden Set
- 小规模历史分析案例

生产数据不应直接提交到代码仓库。

### 5.21 `scripts/`

一次性和运维脚本：

- 初始化数据库
- 生成模拟数据
- 导入知识库
- 执行增量同步
- 重建 Milvus 索引
- 运行评测
- 清理测试任务

### 5.22 `docs/`

项目文档：

```text
docs/
├── architecture.md        总体架构
├── api.md                  API 文档
├── domain-model.md         电力领域模型
├── rag.md                  RAG 设计
├── mcp.md                  MCP 设计
├── operations.md           运维手册
├── evaluation.md           评测说明
└── decisions/              架构决策记录
```

### 5.23 `deploy/`

部署和环境编排：

```text
deploy/
├── Dockerfile
├── docker-compose.yml      本地完整依赖
├── docker-compose.dev.yml  开发环境
├── env.example
├── migrations/             MySQL 迁移
└── monitoring/             监控配置
```

## 6. 推荐的第一次提交顺序

```text
1. README.md、docs/domain-model.md
2. config/、db/、models/、schemas/
3. MySQL Repository 和模拟电力数据
4. FastAPI /health、任务创建和任务查询
5. harness/task_manager.py
6. orchestration/graph.py 和基础 State
7. route → plan → act → report 主链路
8. SQL、指标、异常三个基础工具
9. Redis 任务状态、缓存和幂等
10. Milvus 指标口径和政策 RAG
11. Reviewer 和人工审批
12. MCP 电力数据工具
13. Kafka 数据同步和异步分析
14. API Connector
15. evaluation/ 和 tests/
16. tracing、metrics、Docker 部署
```

## 7. 文件夹之间的依赖关系

```text
app
 ├─ schemas
 ├─ harness
 └─ repositories

harness
 ├─ orchestration
 ├─ infra
 └─ schemas

orchestration
 ├─ agents
 ├─ tools
 ├─ rag
 └─ memory

tools
 ├─ domain
 ├─ repositories
 ├─ adapters
 └─ mcp

ingestion
 ├─ adapters
 ├─ db
 └─ Kafka

evaluation
 ├─ orchestration
 ├─ rag
 ├─ tools
 └─ tests
```

依赖原则：

- `domain/` 不依赖 LLM 和 FastAPI。
- `tools/` 不直接处理 HTTP 请求。
- `orchestration/` 负责流程，不负责具体存储实现。
- `agents/` 负责业务策略，不直接操作数据库连接。
- `adapters/` 不包含 Agent 推理逻辑。
- `app/` 只负责接入和启动。
- 所有高风险操作都必须经过 `harness/`。

## 8. 面试项目建议完成线

如果时间有限，完成以下内容即可形成完整项目：

```text
FastAPI
MySQL
Redis
Milvus
LangGraph
Agent Harness
Metric Agent
Anomaly Agent
RAG 指标口径检索
Human Approval
Golden Set 评测
Docker Compose
```

Kafka 和真实电力 API 作为扩展能力展示，代码实现可以放到第二阶段，不必阻塞第一版 Agent 主链路。
