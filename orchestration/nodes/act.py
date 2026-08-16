"""执行节点（act）：把意图翻译成工具调用，产出 QueryResult。

设计决策：
1. 模板化：intent → 具体工具（5 类意图 → 5 个工具）是**确定性映射**，
   不是让 LLM 再选工具——意图解析阶段 LLM 已经选好了，act 只做执行。
   这比"LLM 自由选工具"更可控（工具调用可审计、可预测）。
2. 参数补全：IntentResult → 工具入参，缺失的日期默认近 30 天。
3. 结果统一包装成 QueryResult（rows/columns/meta），report 节点消费。
"""
from __future__ import annotations

from datetime import date, timedelta

from langgraph.runtime import Runtime

from orchestration.context import AgentContext
from orchestration.state import AgentState
from schemas.agent import IntentResult, IntentType, QueryResult
from tools.registry import get_registry


# 意图 → 工具名 + 参数构造（模板化映射）
def _to_tool_call(intent: IntentResult) -> tuple[str, dict]:
    """IntentResult → (工具名, 工具入参)。"""
    days = intent.days or 30

    if intent.intent == IntentType.REGION_METRICS:
        return "get_region_metrics", {
            "region_code": intent.region_code or "",
            "metric": intent.metric or "line_loss_rate",
            "days": days,
        }
    if intent.intent == IntentType.HIGH_LOSS_LINE:
        return "get_high_loss_lines", {
            "region_code": intent.region_code,
            "loss_threshold": intent.loss_threshold or 0.10,
            "limit": intent.limit or 10,
        }
    if intent.intent == IntentType.HIGH_LOSS_TAIQU:
        return "get_high_loss_taiqu", {
            "region_code": intent.region_code,
            "loss_threshold": intent.loss_threshold or 0.12,
            "limit": intent.limit or 10,
        }
    if intent.intent == IntentType.USER_USAGE:
        return "get_user_daily_usage", {
            "user_id": intent.user_id or "",
            "days": days,
        }
    if intent.intent == IntentType.TAIQU_RECONCILED:
        return "reconcile_taiqu_loss", {
            "taiqu_code": intent.taiqu_code or "",
            "days": min(days, 30),
        }
    raise ValueError(f"不支持的意图: {intent.intent}")


async def act_node(state: AgentState, runtime: Runtime[AgentContext]) -> dict:
    """执行查询：intent → 工具 → QueryResult。"""
    intent = IntentResult.model_validate(state["intent"])
    ctx = runtime.context
    registry = get_registry()

    # 关键：region_name → region_code 反查（LLM 只知"虎门镇"，不知 DG012 编码）。
    # 用元数据取值字典（meta_values）反查，这是"先理解上下文"的落地。
    await _resolve_region_code(intent, ctx)

    tool_name, args = _to_tool_call(intent)
    tool = registry.get(tool_name)
    if tool is None:
        result = QueryResult(intent=intent.intent, error=f"工具未注册: {tool_name}")
        return {"error": f"工具未注册: {tool_name}",
                "result": result.model_dump(mode="json")}

    try:
        raw = await tool.execute(args)
        result = QueryResult(
            intent=intent.intent,
            rows=raw.get("rows", []),
            columns=raw.get("columns", []),
            meta=raw.get("meta", {}),
        )
        return {"result": result.model_dump(mode="json"), "error": None}
    except Exception as e:
        result = QueryResult(intent=intent.intent, error=str(e))
        return {"result": result.model_dump(mode="json"), "error": str(e)}


async def _resolve_region_code(intent: IntentResult, ctx: AgentContext) -> None:
    """region_name → region_code 反查（元数据取值字典）。

    仅当 LLM 填了 region_name 但 region_code 为空时反查；
    反查失败（名字不在字典里）→ region_code 置空，交给 Repository 返回空结果，
    报告层会提示"无数据"。
    """
    if intent.region_code or not intent.region_name:
        return
    try:
        meta_repo = ctx.meta_repo_factory()
        code = await meta_repo.resolve_value("region_code", intent.region_name)
        if code:
            intent.region_code = code
    except Exception:
        pass  # 反查失败不阻塞，region_code 保持空
