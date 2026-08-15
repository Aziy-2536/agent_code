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
