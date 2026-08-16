"""意图解析节点（route）：把用户问题解析成结构化 IntentResult。

设计决策（模板化问数的核心）：
1. LLM 只提取参数（意图 + region/metric/days/阈值），**不生成 SQL**。
2. 用 Function Calling 让 LLM 输出结构化 JSON（而不是自由文本再正则解析）：
   把 IntentResult 的 JSON schema 作为工具定义，LLM 返回的就是合法 JSON。
3. 元数据上下文（meta_context）注入 prompt：LLM 靠它识别"虎门镇"→region_name、
   "线损率"→metric，而不是凭空猜。
4. 解析失败（LLM 不返回 tool_calls）→ 意图置 UNKNOWN，交给 clarify 节点追问。
"""
from __future__ import annotations

import json

from langgraph.runtime import Runtime

from infra.llm_gateway import chat
from orchestration.context import AgentContext
from orchestration.state import AgentState
from schemas.agent import IntentResult, IntentType


# IntentResult 的 JSON schema（作为 Function Calling 的工具定义）
_INTENT_FUNCTION = {
    "type": "function",
    "function": {
        "name": "parse_intent",
        "description": "把用户问数问题解析成结构化意图和参数（只提取参数，不生成SQL）",
        "parameters": IntentResult.model_json_schema(),
    },
}

_SYSTEM_PROMPT = """你是电力数据分析助手的意图解析器。从用户问题中提取：
- intent：问题类型（region_metrics 区域指标 / high_loss_line 高损线路 / high_loss_taiqu 高损台区 / user_usage 户级用电 / taiqu_reconciled 台区对账 / unknown 无法识别）
- region_name/region_code：镇街（用户说地名时填 region_name，编码可留空）
- metric：指标 code（线损率=line_loss_rate，回收率=collection_rate，供电量=supply_kwh，售电量=sale_kwh）
- days 或 start_date/end_date：时间范围（"近30天"→days=30）
- loss_threshold：线损阈值（"超过10%"→0.10）
- user_id / taiqu_code：户级/台区对账时填

只输出 parse_intent 工具调用，不要自由发挥。"""


async def route_node(state: AgentState, runtime: Runtime[AgentContext]) -> dict:
    """意图解析：query → IntentResult（存 state["intent"]）。"""
    ctx = runtime.context
    query = state.get("query", "")

    # 元数据上下文（表/字段/取值，让 LLM 理解业务）
    meta = ctx.meta_context
    user_msg = query
    if meta:
        user_msg = f"【可查询的业务上下文】\n{meta}\n\n【用户问题】\n{query}"

    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]

    result = await chat(messages, tools=[_INTENT_FUNCTION], temperature=0.1)
    ctx.consume(result)

    intent = IntentResult(intent=IntentType.UNKNOWN, raw_query=query)

    # 解析 Function Calling 返回的 JSON 参数
    if result.tool_calls:
        try:
            args = json.loads(result.tool_calls[0]["arguments"])
            intent = IntentResult(**args)
            if not intent.raw_query:
                intent.raw_query = query
        except (json.JSONDecodeError, ValueError):
            # LLM 返回非法 JSON → 置 UNKNOWN 走 clarify
            intent = IntentResult(intent=IntentType.UNKNOWN, raw_query=query)
    # 无 tool_calls（LLM 直接回文本）→ 也走 clarify

    clarification = intent.missing_params() if intent.intent != IntentType.UNKNOWN else ["intent"]

    return {
        "intent": intent.model_dump(mode="json"),
        "clarification_needed": clarification,
    }
