"""AgentContext 共享上下文（编排层地基）。

设计决策（参考工业实践）：
1. 所有节点、所有工具不各自创建依赖，统一从 AgentContext 取——
   保证"能力获取方式"单一，避免节点间各自持有一套依赖。
2. LangGraph 的 GraphState 必须可序列化（checkpoint 落盘），
   所以 context 实例不进 state，state 里只存 ctx_id，
   通过 ContextRegistry 间接挂载——本文件同时提供注册表。
3. 能力对象（llm/rag/tools/memory/tracer）后续以 Protocol 接口注入，
   第一版先固化"标识 + 输入 + 过程数据 + 预算 + 状态控制"。
"""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field

from config.settings import get_settings


@dataclass(frozen=True)
class Intent:
    """意图识别结果（不可变，便于跨节点传递）。"""

    label: str
    confidence: float


@dataclass
class CostBudget:
    """任务预算：Token / 步骤 / 耗时 / 成本 四维控制。"""

    max_steps: int = 20
    max_tokens: int = 50_000
    max_seconds: float = 300.0
    max_cost_usd: float = 2.0

    @classmethod
    def from_settings(cls) -> "CostBudget":
        s = get_settings()
        return cls(
            max_steps=s.agent_max_steps,
            max_tokens=s.agent_budget_tokens,
            max_seconds=float(s.agent_timeout_seconds),
            max_cost_usd=s.agent_budget_usd,
        )

    def exceeded(self, steps: int, tokens: int, elapsed: float, cost_usd: float) -> bool:
        return (
            steps >= self.max_steps
            or tokens >= self.max_tokens
            or elapsed >= self.max_seconds
            or cost_usd >= self.max_cost_usd
        )


@dataclass
class AgentContext:
    """单个分析任务的共享上下文，贯穿 LangGraph 全部节点与工具。"""

    # ---- 标识 ----
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    task_id: str = field(default="")
    session_id: str = field(default="")
    tenant_id: str = field(default="default")

    # ---- 输入 ----
    query: str = field(default="")
    intent: Intent | None = None

    # ---- 过程数据 ----
    plan: list[str] = field(default_factory=list)  # 规划出的执行步骤
    steps: list[dict] = field(default_factory=list)  # 工具调用记录 [{tool, input, output, status}]
    rag_hits: list[dict] = field(default_factory=list)  # RAG 命中文档
    intermediate: dict = field(default_factory=dict)  # 中间数据结果

    # ---- 控制 ----
    budget: CostBudget = field(default_factory=CostBudget.from_settings)
    step_counter: int = 0
    mode: str = "plan_solve"  # plan_solve / react

    # ---- 元信息 ----
    metadata: dict = field(default_factory=dict)  # 租户/区域/权限等扩展信息

    def record_step(self, tool: str, inp: dict, output: dict | None = None, status: str = "SUCCEEDED") -> None:
        """记录一次工具调用（审计数据源）。"""
        self.steps.append(
            {"tool": tool, "input": inp, "output": output, "status": status}
        )
        self.step_counter += 1

    def budget_exceeded(self, tokens: int, elapsed: float, cost_usd: float) -> bool:
        return self.budget.exceeded(self.step_counter, tokens, elapsed, cost_usd)


class ContextRegistry:
    """ctx_id -> AgentContext 的进程内注册表（含生命周期管理）。

    说明：单进程部署下用内存 dict 足够；多实例部署时应替换为 Redis 存储，
    保持接口不变（create / get / drop）。
    """

    def __init__(self) -> None:
        self._store: dict[str, AgentContext] = {}
        self._lock = threading.Lock()

    def create(self, query: str, **kwargs) -> tuple[str, AgentContext]:
        """创建 context 并注册，返回 (ctx_id, context)。"""
        ctx = AgentContext(query=query, **kwargs)
        ctx_id = ctx.trace_id  # 直接用 trace_id 作为 ctx_id，全链路一致
        with self._lock:
            self._store[ctx_id] = ctx
        return ctx_id, ctx

    def get(self, ctx_id: str) -> AgentContext | None:
        return self._store.get(ctx_id)

    def get_or_raise(self, ctx_id: str) -> AgentContext:
        ctx = self._store.get(ctx_id)
        if ctx is None:
            raise KeyError(f"AgentContext not found: {ctx_id}")
        return ctx

    def drop(self, ctx_id: str) -> None:
        with self._lock:
            self._store.pop(ctx_id, None)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()


# 全局注册表单例：LangGraph 节点通过 ctx_id 取 context
registry = ContextRegistry()


def get_context(ctx_id: str) -> AgentContext:
    """节点/工具取 context 的统一入口。"""
    return registry.get_or_raise(ctx_id)
