"""澄清节点（clarify）：意图参数不全或无法识别时，生成追问。

设计决策：
1. clarify 只在"参数不全/意图未知"时进入（条件边路由），不是必经节点。
2. 追问文案确定性生成（按缺什么参数说什么），不额外调 LLM——
   省 token，且追问内容可控。
3. 产出写入 report（作为"待澄清"报告），任务状态由 harness 置为
   NEEDS_CLARIFICATION，用户补充后重新发起任务。
"""
from __future__ import annotations

from langgraph.runtime import Runtime

from orchestration.context import AgentContext
from orchestration.state import AgentState
from schemas.agent import IntentResult, QueryResult, ReportInput, ReportSection

# 缺失参数 → 中文追问
_MISSING_HINTS = {
    "region": "请告诉我你想查哪个镇街（如「虎门镇」「南城街道」）。",
    "user_id": "请提供要查询的用户编号（户号）。",
    "taiqu_code": "请提供要查询的台区编号。",
    "date_range": "请告诉我要查询的时间范围（如「近30天」）。",
    "intent": "我没能理解你的问题，请用更明确的方式描述（如「虎门镇近30天线损率」）。",
}


async def clarify_node(state: AgentState, runtime: Runtime[AgentContext]) -> dict:
    """生成追问报告（参数不全/意图未知时）。"""
    missing = state.get("clarification_needed", [])
    intent = IntentResult.model_validate(state.get("intent", {"intent": "unknown"}))

    hints = [_MISSING_HINTS.get(m, f"缺少参数：{m}") for m in missing] or [
        _MISSING_HINTS["intent"]
    ]
    question = " ".join(hints)

    section = ReportSection(
        title="需要补充信息",
        kind="warning",
        content=question,
    )
    report = ReportInput(
        query=state.get("query", ""),
        intent=intent.intent,
        result=QueryResult(intent=intent.intent),
        sections=[section],
    )
    return {"report": report.model_dump(mode="json")}
