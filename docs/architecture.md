# PowerInsight Agent 总体架构设计

## 1. 项目定位

PowerInsight Agent 是一个面向电力营销与经营分析场景的企业级智能 Agent 平台。

系统接收自然语言问题、定时分析任务或电力业务 API 数据，经过任务编排、数据查询、指标计算、异常诊断和知识检索，输出带有数据依据、知识引用和执行轨迹的分析结果。

典型问题：

- 分析某区域近 30 天线损率异常的原因。
- 对比营销系统和计量系统的日电量差异。
- 找出本月高损线路和异常台区。
- 分析某区域欠费增长的主要原因。
- 根据电价政策解释本月收入变化。

项目目标不是构建一个通用聊天机器人，而是构建一套可观测、可评测、可审计、可扩展的 Agent 工程底座。

## 2. 总体架构

```text
┌──────────────────────────────────────────────────────────────────────┐
│                          Client / External Systems                    │
│        Web UI  ·  CLI  ·  BI  ·  电力业务系统  ·  定时任务             │
└───────────────────────────────┬──────────────────────────────────────┘
                                │ HTTP / SSE / WebSocket
┌───────────────────────────────▼──────────────────────────────────────┐
│                         FastAPI API Gateway                           │
│  认证鉴权 · 租户隔离 · 参数校验 · 任务提交 · 流式输出 · 审计入口       │
└───────────────────────────────┬──────────────────────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────────────────┐
│                         Agent Harness                                │
│  Task Manager · Tool Registry · Policy Guard · Budget · Retry         │
│  Checkpoint · Human Approval · Audit · Trace · Evaluation              │
└───────────────────────────────┬──────────────────────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────────────────┐
│                    LangGraph Agent Orchestration                      │
│  Route → Clarify → Plan → Retrieve → Act → Observe → Review → Report  │
└───────────────┬───────────────────────┬───────────────────────┬──────┘
                │                       │                       │
                ▼                       ▼                       ▼
┌───────────────────────┐  ┌───────────────────────┐  ┌───────────────────────┐
│ Domain Agents          │  │ Tools / MCP           │  │ Knowledge & Memory    │
│ Metric Agent           │  │ SQL Query             │  │ Hybrid RAG             │
│ Data Agent             │  │ Metering API          │  │ Working Memory         │
│ Anomaly Agent          │  │ Device Alarm          │  │ Episodic Memory        │
│ Reviewer Agent         │  │ Policy Search         │  │ Semantic Memory        │
│ Report Agent           │  │ Ticket Creation       │  │ Feedback / Evolution    │
└───────────────┬───────┘  └───────────────┬───────┘  └───────────────┬───────┘
                │                          │                          │
                └──────────────────────────┼──────────────────────────┘
                                           │
┌──────────────────────────────────────────▼────────────────────────────┐
│                         Async Event Layer                              │
│ Kafka: data.ingested · analysis.requested · analysis.completed          │
│        anomaly.detected · report.requested · rag.index.requested        │
└───────────────┬───────────────────────┬───────────────────────┬────────┘
                ▼                       ▼                       ▼
┌───────────────────────┐  ┌───────────────────────┐  ┌───────────────────────┐
│ MySQL                  │  │ Redis                 │  │ Milvus                │
│ 业务事实 · 任务 · 报告  │  │ 会话 · 缓存 · 锁 · 状态 │  │ 指标 · 政策 · 案例向量 │
│ 审计 · 评测 · 同步游标  │  │ 限流 · 幂等 · Checkpoint│  │ 混合检索辅助索引       │
└───────────────────────┘  └───────────────────────┘  └───────────────────────┘
```

## 3. 分层职责

### 3.1 接入层：FastAPI

FastAPI 是系统统一服务入口，不直接承载 Agent 业务决策。

主要职责：

- 用户认证和租户识别。
- 请求参数和响应 Schema 校验。
- 提交同步或异步分析任务。
- 通过 SSE 推送 Agent 执行过程。
- 暴露人工审批、报告查询和数据同步接口。
- 提供健康检查、指标和运维接口。

建议接口：

```text
POST /api/v1/tasks                    提交分析任务
GET  /api/v1/tasks/{task_id}           查询任务状态
GET  /api/v1/tasks/{task_id}/stream    SSE 流式返回执行过程
POST /api/v1/tasks/{task_id}/approve   人工审批并恢复任务
GET  /api/v1/reports/{report_id}       获取分析报告
POST /api/v1/data/sync                 触发数据同步
GET  /api/v1/metrics                   查询标准指标
GET  /health                           健康检查
```

### 3.2 Agent Harness 层

Harness 是包裹在 Agent 外部的运行时控制层，保证 Agent 不是一次性的模型调用。

核心模块：

- `TaskManager`：管理任务创建、取消、重试和状态转换。
- `ToolRegistry`：注册工具、过滤工具、生成工具 Schema。
- `PolicyGuard`：执行权限、SQL 安全、敏感数据和高风险动作检查。
- `BudgetManager`：限制最大步骤、Token、耗时和调用成本。
- `CheckpointManager`：保存和恢复 LangGraph 执行状态。
- `ApprovalManager`：处理 Human-in-the-loop。
- `AuditLogger`：记录用户、工具、数据和结论审计信息。
- `EvaluationRunner`：运行 Golden Set、回归测试和质量评分。

任务状态建议为：

```text
CREATED → PLANNING → RUNNING → REVIEWING → SUCCEEDED
                       │             │
                       ├→ RETRYING   └→ WAITING_APPROVAL
                       └→ FAILED
```

### 3.3 LangGraph 编排层

LangGraph 负责单个 Agent 任务内部的状态图和节点跳转。

```text
用户问题
   ↓
Route：识别意图和置信度
   ├─ 低置信度 → Clarify：澄清问题
   └─ 可执行 → Plan：拆解任务
                  ↓
             Retrieve：检索指标和业务规则
                  ↓
             Act：调用 SQL/API/MCP 工具
                  ↓
             Observe：检查结果和错误
                  ├─ 可修复 → Retry / Act
                  ├─ 需人工 → Human Approval
                  └─ 已完成 → Review
                                  ↓
                              Report
```

建议使用统一的 `AgentContext` 保存：

- `trace_id`、`task_id`、`session_id`
- 用户问题和当前意图
- 当前计划和执行步骤
- 工具调用记录
- RAG 命中文档
- 中间数据结果
- Token、成本和超时预算
- 租户、区域和权限信息

### 3.4 Domain Agent 层

#### Metric Agent

负责指标口径和计算规则：

- 供电量
- 售电量
- 线损率
- 回收率
- 欠费率
- 峰谷比
- 负荷率

#### Data Agent

负责查询数据源、生成安全查询、执行多表关联和处理查询错误。

#### Anomaly Agent

负责同比、环比、阈值、趋势和异常归因分析。

#### Reviewer Agent

负责检查结论是否被数据支持、指标口径是否正确、引用是否真实以及是否需要人工确认。

#### Report Agent

负责生成结构化分析报告，包括结论、数据依据、异常明细、可能原因、引用和建议动作。

### 3.5 分层依赖规则（防止架构腐化的护栏）

系统按"抽象层级 + 变更频率"分为五层，**依赖只允许向下，禁止反向依赖**：

```text
L5 Interface       app/（api、cli、workers）       只做接入和启动
L4 Orchestration   orchestration/ + agents/        只管流程编排，不碰存储实现
L3 Capability      tools/ · rag/ · memory/         可插拔能力，只依赖底座
L2 Infrastructure  infra/ · harness/ · db/         通用底座（LLM/安全/预算/连接）
L1 Storage         MySQL / Redis / Milvus / Kafka  存储与事件
```

强制执行规则：

- `domain/` 不依赖 LLM、FastAPI 和任何框架——确定性业务公式与 AI 推理解耦。
- `tools/` 不直接处理 HTTP 请求；工具只通过输入/输出 Schema 与 Agent 交互。
- `orchestration/` 负责流程，不直接操作数据库连接（数据访问走 `repositories/`）。
- `agents/` 负责业务策略，具体执行交给 `tools/` 或 `mcp/`，不直接操作连接。
- `adapters/` 只做外部系统格式适配，不包含 Agent 推理逻辑。
- 所有高风险动作（写库、建工单、改业务状态）必须经过 `harness/`（PolicyGuard + Approval）。
- 意图规则（`orchestration/rules/`）与节点逻辑解耦：新增意图只改规则文件，不动节点。
- 节点与工具的能力获取统一走 `AgentContext`（ctx_id 间接挂载），不各自创建依赖。
- 变更时的判断标准：若修改 A 层需要连带修改 B 层，且 B 是 A 的下层，则说明依赖方向反了。

## 4. 数据接入架构

电力 API 不直接暴露给 Agent，而是通过 Connector 统一适配。

```text
电力营销 API / 计量 API / 告警 API / 文件
                    ↓
             Connector Adapter
                    ↓
         鉴权 · 分页 · 限流 · 重试
                    ↓
       字段标准化 · 数据质量校验 · 去重
                    ↓
             Kafka: data.ingested
                    ↓
              Ingestion Worker
                    ↓
                  MySQL
```

Connector 需要负责：

- API 鉴权和密钥轮换。
- 全量、增量和按时间窗口同步。
- 分页、超时、限流和重试。
- 外部字段到内部标准字段的映射。
- 数据版本和同步游标管理。
- 幂等写入和重复数据处理。
- 无效数据进入死信或修复队列。

建议的接入模块：

```text
adapters/
├── marketing_api.py
├── metering_api.py
├── device_alarm_api.py
├── finance_api.py
├── schema_mapper.py
├── sync_cursor.py
└── quality_checker.py
```

## 5. Kafka 事件设计

Kafka 用于跨服务异步解耦、批量任务和实时事件，不替代 LangGraph 的任务状态。

建议 Topic：

```text
power.data.ingested        数据接入完成
power.data.invalid         数据质量校验失败
power.analysis.requested   提交分析任务
power.analysis.completed   分析任务完成
power.anomaly.detected     发现异常
power.report.requested     请求生成报告
power.report.completed     报告生成完成
power.rag.index.requested  请求知识库索引
power.dead-letter          多次失败的消息
```

消息必须包含：

```text
event_id
event_type
task_id
tenant_id
trace_id
source
occurred_at
schema_version
payload
```

必须实现：

- 消费幂等。
- 重试 Topic。
- Dead Letter Queue。
- 消费延迟监控。
- 消息 Schema 版本管理。
- 失败任务补偿和重新投递。

## 6. 存储设计

### 6.1 MySQL

MySQL 保存需要事务、一致性和审计的数据：

```text
users / tenants / roles
analysis_tasks
task_steps
tool_calls
analysis_reports
metric_definitions
data_sync_jobs
data_sync_cursors
anomaly_records
human_approvals
audit_logs
evaluation_cases
evaluation_runs
```

原则：业务事实、任务状态最终结果、权限和审计以 MySQL 为准。

### 6.2 Redis

Redis 保存高频、临时和运行时数据：

```text
session:{session_id}
task:runtime:{task_id}
lock:task:{task_id}
cache:llm:{fingerprint}
cache:query:{fingerprint}
rate_limit:{tenant_id}
idempotency:{event_id}
```

原则：Redis 可以丢失，不能作为唯一业务事实来源。

### 6.3 Milvus

Milvus 存储向量化知识，不存储最终业务交易数据：

```text
power_metric_knowledge
power_policy_documents
power_business_rules
power_analysis_cases
power_data_dictionary
```

检索流程：

```text
用户问题
   ↓
Query Rewrite
   ↓
BM25 + Dense Retrieval
   ↓
RRF 融合
   ↓
Reranker
   ↓
引用文档和规则
```

## 7. MCP 设计

MCP 用于标准化 Agent 与外部能力之间的连接。

建议封装：

```text
get_power_metric()
query_metering_data()
get_line_loss_analysis()
get_device_alarm()
search_power_policy()
create_analysis_ticket()
```

工具调用链：

```text
LangGraph Agent
      ↓
MCP Client
      ↓
Power MCP Server
      ↓
API Adapter / MySQL / 外部业务系统
```

高风险工具，例如创建工单、发送报告和修改业务状态，必须经过 Harness 的权限检查和人工确认。

## 8. 一次分析任务的完整链路

```text
1. 用户通过 FastAPI 提交问题
2. 创建 task_id、trace_id，任务写入 MySQL
3. Redis 写入运行时状态和幂等键
4. Harness 做认证、权限、预算和工具预检查
5. LangGraph Route 判断意图
6. Planner 拆解任务
7. RAG 检索指标口径和业务规则
8. Agent 调用 SQL Tool 或 MCP Tool
9. 数据结果写入中间状态，必要时缓存到 Redis
10. Observe 检查错误、空结果和异常数据
11. 自动修复、重试或进入人工审批
12. Reviewer 检查结论和引用
13. Report Agent 生成结构化报告
14. 报告和审计记录写入 MySQL
15. FastAPI 通过 SSE 返回执行过程和最终结果
16. 成功/失败样本进入评测和长期记忆流程
```

## 9. Harness 与评测体系

评测 Harness 不只评价最终文本，还评价完整 Agent 行为：

```text
Golden Query
   ↓
Agent Runner
   ↓
Trace Collector
   ↓
多维 Grader
   ├─ 意图识别
   ├─ 计划质量
   ├─ 工具选择
   ├─ SQL 可执行性
   ├─ 结果正确性
   ├─ RAG Recall / MRR
   ├─ 引用准确性
   ├─ 权限和安全
   ├─ 延迟和成本
   └─ 人工采纳率
```

每次修改 Prompt、模型、RAG 或工作流后，都需要运行回归测试。

## 10. 可观测性与运维

每次请求使用一个 `trace_id` 串联：

```text
API Request
  └─ Agent Task
      ├─ route span
      ├─ plan span
      ├─ rag span
      ├─ tool span
      ├─ llm span
      ├─ kafka span
      └─ report span
```

重点指标：

- Agent 成功率。
- 各节点耗时。
- LLM Token 和成本。
- RAG 召回率。
- Kafka 消费延迟。
- API 错误率。
- 工具失败率。
- 重试率。
- 人工审批比例。
- 异常诊断准确率。

## 11. 部署架构

```text
                    ┌──────────────┐
                    │   Nginx      │
                    └──────┬───────┘
                           ↓
                    ┌──────────────┐
                    │ FastAPI      │
                    │ API Service   │
                    └──────┬───────┘
             ┌─────────────┼─────────────┐
             ↓             ↓             ↓
       Agent Worker   Ingest Worker   Report Worker
             └─────────────┼─────────────┘
                           ↓
              ┌────────────┼────────────┐
              ↓            ↓            ↓
           MySQL        Redis        Milvus
                           ↑
                         Kafka
```

开发环境可以使用 Docker Compose 启动全部依赖；生产环境再拆分服务并进行水平扩展。

## 12. 开发阶段建议

### Phase 1：核心闭环

- FastAPI
- LangGraph
- MySQL
- Redis
- Milvus
- 电力模拟数据
- 指标查询、线损分析和报告生成

### Phase 2：工程化增强

- Agent Harness
- MCP Server
- Human-in-the-loop
- Checkpoint 恢复
- Trace、成本和评测
- Hybrid RAG

### Phase 3：异步和数据接入

- Kafka
- 电力 API Connector
- 增量同步
- 数据质量检查
- 批量分析和异常事件流

### Phase 4：生产化增强

- 多租户
- 高可用
- 灰度发布
- 完整权限体系
- 数据脱敏和安全审计
- 监控告警和故障演练

## 13. 项目边界

第一版只实现三个核心业务闭环：

1. 电力指标自然语言查询。
2. 线损、电量和欠费异常分析。
3. 带规则引用和数据依据的经营分析报告。

Kafka、电力 API、实时告警和自动工单作为第二阶段扩展，避免第一版因为基础设施过多而失去业务主线。

## 14. 面试表述

> 我设计的是一个面向电力营销场景的 Agent 平台。FastAPI 负责统一接入，Agent Harness 负责任务生命周期、权限、预算、重试、审批和评测，LangGraph 负责单任务状态编排，MySQL 保存业务事实和审计数据，Redis 管理运行时状态与缓存，Milvus 支持指标和政策知识检索，Kafka 解耦电力数据接入、批量分析和异常事件处理，MCP 则负责统一外部电力工具协议。系统最终形成从数据接入、知识检索、Agent 推理到报告和审计的完整闭环。

---

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

---

# PowerInsight Agent 项目文件树

以下是当前仓库已经创建的文件树。带有 `__init__.py` 的目录是 Python 包；当前业务文件先保留职责占位，后续按开发顺序逐步实现。

```text
power-insight-agent/
├── app/                         应用启动和服务入口
│   ├── api/                     FastAPI 接口层
│   │   ├── __init__.py
│   │   └── main.py              FastAPI 应用入口
│   ├── cli/                     命令行入口
│   │   ├── __init__.py
│   │   └── main.py              本地调试和演示
│   ├── workers/                 异步 Worker
│   │   ├── __init__.py
│   │   ├── analysis_worker.py   Agent 分析任务消费者
│   │   └── ingestion_worker.py  数据接入任务消费者
│   └── __init__.py
│
├── config/                      统一配置
│   ├── __init__.py
│   └── settings.py              环境变量和配置模型
│
├── db/                          基础设施客户端
│   ├── __init__.py
│   ├── mysql.py                 MySQL 连接和 Session
│   ├── redis.py                 Redis 客户端
│   ├── milvus.py                Milvus 客户端
│   └── kafka.py                 Kafka Producer/Consumer
│
├── models/                      MySQL 持久化模型
│   ├── __init__.py
│   ├── task.py                  任务和步骤模型
│   ├── power.py                 电力业务数据模型
│   └── knowledge.py             指标和知识元数据模型
│
├── repositories/                数据访问层
│   ├── __init__.py
│   ├── task_repository.py       任务读写
│   ├── power_repository.py     电力数据查询
│   └── report_repository.py    报告读写
│
├── schemas/                     Pydantic 数据契约
│   ├── __init__.py
│   ├── api.py                   HTTP 请求和响应
│   ├── events.py                Kafka 事件和版本
│   ├── tools.py                 工具输入输出
│   └── agent.py                 Agent 状态和上下文
│
├── harness/                     Agent 工程化运行时控制层
│   ├── __init__.py
│   ├── task_manager.py          任务生命周期
│   ├── runtime.py               Agent 执行包装器
│   ├── tool_registry.py         工具注册和发现
│   ├── policy_guard.py          权限、安全和风险控制
│   ├── budget_manager.py        Token、步骤、时间和成本预算
│   ├── checkpoint.py            状态保存和恢复
│   ├── approval.py              人工审批
│   ├── idempotency.py           任务和消息幂等
│   └── audit.py                 执行审计
│
├── orchestration/               LangGraph 工作流编排
│   ├── __init__.py
│   ├── graph.py                 StateGraph 装配
│   ├── state.py                 可序列化图状态
│   ├── context.py               单任务共享上下文
│   ├── routing.py               条件边和跳转规则
│   ├── nodes/                   工作流节点
│   │   ├── __init__.py
│   │   ├── route.py              意图路由
│   │   ├── clarify.py            澄清问题
│   │   ├── plan.py               任务规划
│   │   ├── retrieve.py           RAG 和记忆检索
│   │   ├── act.py                工具和 MCP 调用
│   │   ├── observe.py            结果观察和错误处理
│   │   ├── review.py             结果与引用审核
│   │   └── report.py             报告生成
│   └── rules/                   路由规则
│       ├── __init__.py
│       ├── intent_rules.py       电力分析意图
│       └── transition_rules.py  状态转换规则
│
├── agents/                      业务 Agent 策略
│   ├── __init__.py
│   ├── metric_agent.py           指标口径理解
│   ├── data_agent.py             数据查询和核查
│   ├── anomaly_agent.py          异常检测和归因
│   ├── reviewer_agent.py         结论和证据审核
│   └── report_agent.py           经营分析报告
│
├── domain/                      确定性电力业务逻辑
│   ├── __init__.py
│   ├── metrics.py                线损率、售电量等公式
│   ├── anomaly.py                同比、环比和阈值计算
│   ├── entities.py               区域、线路、台区等实体
│   └── constants.py              业务常量和异常等级
│
├── tools/                       Agent 内部工具
│   ├── __init__.py
│   ├── base.py                   工具协议和元数据
│   ├── sql_query.py              只读 SQL 查询
│   ├── schema_inspector.py       Schema 探查
│   ├── metric_calculator.py      指标计算
│   ├── anomaly_detector.py       异常检测
│   └── report_generator.py       报告生成和导出
│
├── mcp/                         MCP 客户端和服务端
│   ├── __init__.py
│   ├── client.py                 Agent 侧 MCP Client
│   ├── server.py                 Power MCP Server 入口
│   ├── schemas.py                MCP 数据协议
│   └── tools/                   MCP 对外工具
│       ├── __init__.py
│       ├── metering.py           计量数据
│       ├── policy.py             政策查询
│       ├── alarm.py              设备告警
│       └── ticket.py             工单创建
│
├── adapters/                    外部系统适配器
│   ├── __init__.py
│   ├── base.py                   Adapter 统一接口
│   ├── marketing_api.py          营销系统
│   ├── metering_api.py           计量系统
│   ├── device_alarm_api.py       设备告警系统
│   ├── finance_api.py            财务和收费系统
│   └── file_adapter.py           CSV、Excel 和文档
│
├── ingestion/                   数据同步、清洗和入库
│   ├── __init__.py
│   ├── sync_service.py           全量和增量同步
│   ├── normalizer.py             字段标准化
│   ├── quality_checker.py        数据质量校验
│   ├── deduplicator.py           去重和幂等写入
│   ├── cursor_manager.py         增量同步游标
│   └── event_publisher.py        发布 Kafka 事件
│
├── rag/                         Hybrid RAG 和知识索引
│   ├── __init__.py
│   ├── chunker.py                文档切分
│   ├── embedder.py               向量化
│   ├── milvus_store.py           Milvus 存取
│   ├── keyword_retriever.py      BM25/关键词检索
│   ├── dense_retriever.py        向量检索
│   ├── fusion.py                 混合检索融合
│   ├── reranker.py               重排
│   ├── query_rewriter.py         查询改写
│   └── citation.py               引用和来源
│
├── memory/                      Agent 记忆
│   ├── __init__.py
│   ├── working.py                当前任务上下文
│   ├── episodic.py               历史任务和案例
│   ├── semantic.py               长期规则和技能
│   ├── retriever.py              记忆检索
│   ├── consolidator.py           经验沉淀
│   └── feedback.py               用户反馈统计
│
├── infra/                       通用基础设施
│   ├── __init__.py
│   ├── llm_gateway.py            模型、重试、缓存和成本
│   ├── cache.py                  缓存抽象
│   ├── tracing.py                Trace 和 Span
│   ├── logging.py                结构化日志
│   ├── metrics.py                运行指标
│   ├── security.py               脱敏和密钥
│   └── circuit_breaker.py        熔断和降级
│
├── evaluation/                  Agent Evaluation Harness
│   ├── __init__.py
│   ├── golden_set.py             标准问题集
│   ├── runner.py                 批量运行
│   ├── graders.py                多维评分
│   ├── metrics.py                质量、延迟和成本指标
│   ├── regression.py             版本回归
│   └── reports.py                评测报告
│
├── tests/                       自动化测试
│   ├── __init__.py
│   ├── conftest.py               共享 Fixture
│   ├── unit/                     单元测试
│   ├── integration/              MySQL、Redis、Milvus 集成测试
│   ├── contract/                 API、MCP、Kafka 契约测试
│   ├── workflow/                 LangGraph 流程测试
│   ├── security/                 权限和安全测试
│   └── evaluation/               Agent 质量回归测试
│
├── data/                        开发和测试数据
│   ├── README.md
│   ├── mock_power/               模拟营销、计量和告警数据
│   │   └── README.md
│   └── knowledge/                指标、政策和规则文档
│       └── README.md
│
├── scripts/                     初始化和运维脚本
│   ├── init_db.py                初始化数据库
│   ├── seed_mock_data.py          生成模拟数据
│   ├── index_knowledge.py         构建 Milvus 索引
│   └── run_evaluation.py          执行评测
│
├── examples/                    可运行示例
│   ├── basic_analysis.py          同步分析
│   └── async_analysis.py          Kafka 异步分析
│
├── docs/                        项目文档
│   ├── project-tree.md            当前文件树说明
│   ├── development-order.md       开发顺序入口
│   └── decisions/                 架构决策记录
│
├── deploy/                      部署文件
│   ├── Dockerfile
│   ├── docker-compose.yml         MySQL、Redis、Milvus、Kafka
│   └── monitoring/                监控配置
│       └── README.md
│
├── skill_library/                评审通过的 Agent 技能
├── openspec/                     功能提案和架构变更
├── .env.example                  环境变量模板
├── pyproject.toml                Python 项目配置
├── README.md                     项目入口说明
├── POWER_INSIGHT_AGENT_ARCHITECTURE.md
└── POWER_INSIGHT_AGENT_DEVELOPMENT_ORDER.md
```

## 6. 当前阶段说明

当前文件是“结构占位”，不是完整业务实现。建议先实现：

```text
config → db → models/schemas → repositories → app/api
       → harness → orchestration → tools/domain
       → rag/memory → evaluation → adapters/ingestion/kafka
```

依赖原则：

- `domain/` 不依赖 FastAPI 和 LLM。
- `orchestration/` 负责流程，不直接操作数据库连接。
- `agents/` 负责业务策略，具体执行交给 `tools/` 或 `mcp/`。
- `adapters/` 只负责外部系统格式适配。
- `ingestion/` 负责可靠同步、校验和入库。
- 所有高风险动作必须经过 `harness/`。
