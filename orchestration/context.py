"""单个分析任务的共享 AgentContext。

设计决策（一次任务 = 一个 AgentContext）：
1. 承载"跨节点共享的运行时资源"：成本预算、LLM 客户端、元数据上下文、
   Repository 工厂、工具注册表。节点通过它访问依赖，不直接碰全局。
2. 成本预算：记录 LLM token 消耗，超预算抛异常中断任务（防失控烧钱）。
3. 元数据上下文：任务开始前用 MetaStoreRepository.build_context() 组装
   业务元数据（表/字段/取值），注入 LLM prompt——"先理解上下文再动手"。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from config.settings import get_settings
from infra.llm_gateway import ChatResult


@dataclass
class CostBudget:
    """单任务成本预算（token 计数，超限抛异常）。

    消费 infra/llm_gateway.ChatResult 的 token 统计。
    """

    max_tokens: int
    used_tokens: int = 0

    @classmethod
    def from_settings(cls) -> "CostBudget":
        """从配置创建（agent_budget_tokens）。"""
        return cls(max_tokens=get_settings().agent_budget_tokens)

    def consume(self, result: ChatResult) -> None:
        """记录一次 LLM 调用的 token 消耗；超预算抛异常。"""
        self.used_tokens += result.total_tokens
        if self.used_tokens > self.max_tokens:
            raise RuntimeError(
                f"任务 token 预算超限：已用 {self.used_tokens} / {self.max_tokens}"
            )

    @property
    def remaining(self) -> int:
        return max(0, self.max_tokens - self.used_tokens)


@dataclass
class AgentContext:
    """一次分析任务的共享上下文（节点间传递的运行时资源）。"""

    task_id: str = ""
    budget: CostBudget = field(default_factory=CostBudget.from_settings)

    # 元数据上下文（任务开始前组装，注入 LLM prompt）
    meta_context: str = ""

    # 依赖注入：节点用这些工厂拿 Repository / 工具，不直接 import 全局
    # - business_repo_factory: () -> DongguanRepository（业务查询）
    # - meta_repo_factory: () -> MetaStoreRepository（元数据检索）
    business_repo_factory: Callable[[], Any] | None = None
    meta_repo_factory: Callable[[], Any] | None = None

    # 工具注册表（已在 harness 启动时注册好真实工具）
    tools: list[dict] = field(default_factory=list)  # openai function 定义列表

    def consume(self, result: ChatResult) -> None:
        """记录 LLM 消耗（委托给预算对象）。"""
        self.budget.consume(result)
