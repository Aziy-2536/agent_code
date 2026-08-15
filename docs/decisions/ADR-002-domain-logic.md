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
