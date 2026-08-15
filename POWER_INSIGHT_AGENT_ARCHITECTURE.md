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
