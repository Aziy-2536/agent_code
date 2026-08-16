"""StateGraph 装配：问数 Agent 的图。

图结构（最短主链路）：
    START → route → (clarify | act) → END
                    ↑                    │
                    └──── 参数齐全 ──────┘
                          act → report → END

- route：意图解析（LLM 提取参数）
- clarify：参数不全时生成追问（自己产出报告，直接 END）
- act：执行查询（模板化工具）
- report：生成报告

条件边：
    route 之后 → clarification_needed 空 ? act : clarify
"""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from orchestration.nodes.act import act_node
from orchestration.nodes.clarify import clarify_node
from orchestration.nodes.report import report_node
from orchestration.nodes.route import route_node
from orchestration.routing import after_route
from orchestration.state import AgentState


def build_graph() -> StateGraph:
    """构建并装配问数 Agent 的 StateGraph（返回已编译图）。"""
    g = StateGraph(AgentState)

    g.add_node("route", route_node)
    g.add_node("clarify", clarify_node)
    g.add_node("act", act_node)
    g.add_node("report", report_node)

    g.add_edge(START, "route")
    g.add_conditional_edges(
        "route",
        after_route,
        {"act": "act", "clarify": "clarify"},
    )
    g.add_edge("act", "report")
    # clarify 节点自己产出"待澄清"报告，直接 END（不再走 report 节点——
    # 否则 report 会因 state["result"] 缺失而报错）
    g.add_edge("clarify", END)
    g.add_edge("report", END)

    return g.compile()


# 模块级单例图（harness 复用）
graph = build_graph()
