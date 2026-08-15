# Industrial Agent 项目目录说明

本项目面向多模态短视频创作 Agent，采用“通用 Agent 能力、业务领域、应用入口、基础设施、评估与运维”分层设计。

## 总体架构

```text
apps/       对外应用入口
app/        核心业务与 Agent 能力
data/       数据与运行文件
evals/      评估体系
deploy/     部署与运维
docs/       设计文档与运行手册
tests/      自动化测试
```

依赖方向建议为：

```text
apps -> app/services -> app/agents / app/domain / app/repositories
app/agents -> app/domain / app/infra / app/common
app/repositories -> app/domain / app/infra/db
workers -> app/services / app/agents / app/repositories
```

## 核心源码：`app/`

### `app/api/`

FastAPI 路由、请求参数、响应模型和鉴权入口。负责 HTTP、SSE、WebSocket 等协议适配，不直接承载复杂业务逻辑。

### `app/agents/`

Agent 编排、状态机和工具调用逻辑。负责剧本解析、人物抽取、分镜规划、素材检索、提示词生成和人工审核流程。

### `app/agents/nodes/`

Agent 工作流节点。每个节点只负责一个可测试的步骤，例如 `parse_document`、`extract_characters`、`plan_storyboard` 和 `validate_output`。

### `app/agents/tools/`

Agent 可调用工具，例如文档解析、向量检索、素材搜索、图片生成、视频生成和项目查询工具。

### `app/domain/`

稳定的领域模型和业务规则，不依赖 FastAPI、数据库或具体模型供应商。

### `app/domain/entities/`

项目、剧本、人物、场景、分镜、素材和生成任务等实体。

### `app/domain/value_objects/`

不可变的值对象，例如任务状态、镜头类型、媒体尺寸、模型配置和分页参数。

### `app/services/`

应用服务层，负责组织完整用例，例如创建项目、启动分析、提交生成任务、人工审核和发布结果。

### `app/repositories/`

数据访问抽象。统一封装项目、剧本、任务、素材、向量和运行轨迹的读写，避免业务代码直接拼接 SQL。

### `app/infra/`

外部基础设施适配层。

- `llm/`：LLM、Embedding、图片和视频模型客户端
- `db/`：数据库连接、事务和 ORM 配置
- `cache/`：Redis、分布式锁和幂等控制
- `storage/`：MinIO、S3 或本地文件存储
- `observability/`：日志、指标、Trace 和模型调用记录

### `app/common/`

跨模块通用能力，例如配置、异常、日志上下文、ID 生成、重试策略和类型定义。这里不放具体业务逻辑。

### `app/config/`

应用配置加载、环境变量映射和配置校验。

## 应用入口：`apps/`

### `apps/api/`

生产环境 API 启动入口，负责创建 FastAPI 应用、注册路由和生命周期钩子。

### `apps/cli/`

命令行入口，用于本地运行 Agent、导入数据、执行评估和维护任务。

### `apps/ui/`

前端或轻量 Web UI。只负责展示项目、分镜、任务进度和审核操作，业务逻辑仍由 API 提供。

## 配置：`configs/`

- `environments/`：开发、测试、生产环境配置模板
- `prompts/`：版本化的 System Prompt、节点 Prompt 和修复 Prompt
- `schemas/`：结构化输出 JSON Schema 和版本定义

密钥、Token 和密码不得提交到仓库，应放在 `.env` 或密钥管理系统中。

## 数据与知识：`data/`、`knowledge_base/`、`memory_store/`

### `data/`

业务运行数据目录。

- `fixtures/`：可重复生成的测试数据
- `uploads/`：用户上传的原始文件

生产环境上传文件和生成媒体应使用对象存储，不应依赖本地磁盘。

### `knowledge_base/`

RAG 知识库原始资料和规则。

- `rules/`：人物一致性、镜头规范和内容安全规则
- `schemas/`：表结构、素材元数据和领域知识结构
- `examples/`：高质量剧本、分镜和提示词样例

### `memory_store/`

Agent 记忆的持久化目录。

- `summaries/`：长文档和历史对话摘要
- `checkpoints/`：工作流中断恢复所需的检查点
- `profiles/`：用户偏好、项目风格和角色档案

## 评估：`evals/`

用于证明 Agent 质量，而不只是展示 Demo。

- `datasets/`：测试集、Golden Set 和对抗样例
- `metrics/`：JSON 成功率、人物抽取准确率、RAG Recall@K、任务成功率和延迟指标
- `runners/`：批量评估运行器
- `reports/`：评估报告和回归结果

## 测试：`tests/`

- `unit/`：领域模型、工具和 Agent 节点的单元测试
- `integration/`：数据库、Redis、对象存储和模型客户端集成测试
- `e2e/`：从创建项目到生成分镜的端到端测试
- `eval/`：Agent 质量和 RAG 评估测试
- `fixtures/`：测试夹具、模拟响应和临时数据

## 文档与规范：`docs/`、`openspec/`

### `docs/`

- `architecture/`：系统架构和数据流
- `adr/`：架构决策记录
- `api/`：接口文档
- `runbooks/`：部署、故障排查和回滚手册
- `topics/`：RAG、记忆、Agent、并发和安全专题

### `openspec/`

需求变更、技术方案和功能规格。重要功能应先记录设计，再进入实现。

## 脚本、示例与部署

### `scripts/`

一次性或运维脚本。

- `data/`：数据生成、导入和清洗
- `maintenance/`：迁移、清理和修复
- `evaluation/`：评估、回归和报告生成

### `examples/`

可运行的自定义工具、Agent 工作流和调用示例，用于降低新成员上手成本。

### `deploy/`

- `docker/`：Dockerfile 和 Docker Compose 配置
- `k8s/`：Kubernetes Deployment、Service、ConfigMap 和 HPA
- `monitoring/`：Prometheus、Grafana 和日志采集配置

## 数据库：`migrations/`

数据库迁移脚本和版本历史。任何表结构变更都应通过迁移完成，不直接修改线上数据库。

## Agent 扩展：`skill_library/`

可复用的 Agent Skill 定义，包括技能说明、输入输出约束、工具依赖和示例。Skill 应保持领域独立，具体业务编排放在 `app/agents/`。

## 版本控制注意事项

以下内容通常不应提交到 Git：

```text
venv/
__pycache__/
.env
data/uploads/
data/outputs/
memory_store/checkpoints/
```

工业级项目的重点不是目录越多越好，而是每个目录有清晰边界、依赖方向稳定、测试和评估能够跟随业务代码一起演进。
