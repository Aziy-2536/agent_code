"""报告生成节点（report）：QueryResult → 用户可读的报告。

设计决策：
1. 分两段：先结构化（程序拼 tables/insights），再自然语言（LLM 润色）。
   结构化部分是确定性的（表格/统计），LLM 只做"用自然语言解释数据"。
2. 报告结果写 ReportInput（sections），后续由 harness 落 analysis_reports 表。
3. 空结果/错误结果也有对应文案，不静默失败。
"""
from __future__ import annotations

from langgraph.runtime import Runtime

from infra.llm_gateway import chat
from orchestration.context import AgentContext
from orchestration.state import AgentState
from schemas.agent import IntentResult, QueryResult, ReportInput, ReportSection


async def report_node(state: AgentState, runtime: Runtime[AgentContext]) -> dict:
    """生成报告：result → ReportInput（结构化 + LLM 润色）。"""
    ctx = runtime.context
    query = state.get("query", "")
    intent = IntentResult.model_validate(state.get("intent", {"intent": "unknown"}))
    result = QueryResult.model_validate(state.get("result", {}))

    sections: list[ReportSection] = []

    # 1. 错误分支
    if result.error:
        sections.append(ReportSection(
            title="查询失败", kind="warning", content=f"查询出错：{result.error}"
        ))
    # 2. 空结果分支
    elif result.is_empty:
        sections.append(ReportSection(
            title="无数据", kind="text", content="未查询到符合条件的数据，请确认筛选条件。"
        ))
    # 3. 正常分支：表格 + LLM 洞察
    else:
        sections.append(ReportSection(
            title="数据明细", kind="table",
            rows=result.display_rows, columns=result.columns,
        ))
        # LLM 用自然语言解释数据（只解释，不重新查询）
        insight = await _llm_insight(ctx, query, result)
        sections.append(ReportSection(
            title="分析洞察", kind="insight", content=insight,
        ))

    report = ReportInput(
        query=query,
        intent=intent.intent,
        result=result,
        sections=sections,
    )
    return {"report": report.model_dump(mode="json")}


async def _llm_insight(ctx: AgentContext, query: str, result: QueryResult) -> str:
    """LLM 生成洞察文案（失败时降级为确定性摘要，不阻塞报告）。"""
    summary = f"共 {len(result.rows)} 条记录"
    if result.meta:
        summary += "，" + "，".join(f"{k}={v}" for k, v in list(result.meta.items())[:3])

    try:
        data_preview = result.display_rows[:10]
        messages = [
            {"role": "system", "content": "你是电力数据分析师。基于查询结果，用 2-3 句中文概括关键发现，"
                                          "突出异常（如高损、趋势），不要编造数据之外的内容。"},
            {"role": "user", "content": f"问题：{query}\n摘要：{summary}\n数据：{data_preview}"},
        ]
        r = await chat(messages, temperature=0.3, max_tokens=300)
        ctx.consume(r)
        return r.content.strip() or summary
    except Exception:
        # LLM 不可用：降级为确定性摘要，报告仍产出
        return summary
