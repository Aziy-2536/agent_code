"""可序列化的 LangGraph 图状态。

设计决策：
1. GraphState 只存"可序列化"的字段（checkpoint 需要落盘），
   因此只放 ctx_id 与少量冗余摘要字段，完整上下文在 ContextRegistry。
2. 节点从 state["ctx_id"] 取 AgentContext，修改 context 即"共享状态"。
"""
from typing import TypedDict


class GraphState(TypedDict, total=False):
    # 上下文挂载点（唯一必须字段）
    ctx_id: str

    # 冗余摘要字段：便于 checkpoint 可读、日志可观测
    question: str
    intent_label: str | None
    intent_confidence: float | None

    # 最终产物
    final_report: dict | None
    error: str | None
