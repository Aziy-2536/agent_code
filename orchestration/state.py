"""可序列化的图状态（LangGraph StateGraph 的状态容器）。

设计决策：
1. LangGraph state 用 TypedDict（框架要求），字段值全部可 JSON 序列化——
   这样 state 可以整体存 task_steps.detail 做审计。
2. 语义层用 schemas/agent.py 的 Pydantic 模型（IntentResult/QueryResult 等），
   存入 state 时 .model_dump() 成 dict，取出时 .model_validate() 还原。
   原因：LangGraph 的 state 在节点间是"浅合并 dict"，用裸 dict 字段
   比塞 Pydantic 对象更符合框架语义，且天然可序列化。
3. 字段设计对齐"模板化问数"的最短链路：query → intent → result → report，
   外加 clarify 追问和 error 兜底。
"""
from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages


class AgentState(TypedDict, total=False):
    """问数 Agent 的图状态（所有字段可选 = total=False）。

    字段语义：
    - query: 用户原始问题（入口传入）
    - messages: 对话消息（LangGraph 标准字段，add_messages 累积）
    - intent: IntentResult.model_dump() 后的 dict（意图 + 解析参数）
    - clarification_needed: 缺的参数列表（clarify 节点填，为空 = 可执行）
    - result: QueryResult.model_dump() 后的 dict（查询结果）
    - report: ReportInput.model_dump() 后的 dict（报告素材）
    - error: 兜底错误信息
    """

    query: str
    messages: Annotated[list, add_messages]
    intent: dict
    clarification_needed: list[str]
    result: dict
    report: dict
    error: str | None
