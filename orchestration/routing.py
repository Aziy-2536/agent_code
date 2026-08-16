"""条件边和工作流路由规则。

设计决策：
1. 路由逻辑与节点分离：节点只产状态，路由函数只读状态决定下一步。
   这样图装配（graph.py）清晰，且路由规则可独立测试。
2. 主链路最短路径：route → (clarify | act) → report → END。
"""
from __future__ import annotations

from orchestration.state import AgentState


def after_route(state: AgentState) -> str:
    """route 之后：参数齐全走 act，否则走 clarify。"""
    missing = state.get("clarification_needed", [])
    return "act" if not missing else "clarify"


def after_act(state: AgentState) -> str:
    """act 之后：有结果走 report；act 失败（error 存在）也走 report（report 处理错误分支）。"""
    return "report"
