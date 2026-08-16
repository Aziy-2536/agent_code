"""异步分析任务消费者（后台执行 Agent）。

设计决策：
1. 轻量后台执行：POST /tasks 创建任务后，用 asyncio.create_task 触发
   run_agent_in_background，不阻塞接口返回（响应立即给 201，执行在后台）。
   —— 一期不引入 Celery/Kafka，够用且简单；二期任务量大再上消息队列。
2. 每个任务独立双库 session：agent 库（任务/报告）+ business 库（数据/元数据）。
3. 异常兜底：执行函数内捕获所有异常，保证任务不会卡在 RUNNING。
"""
from __future__ import annotations

import asyncio
import logging

from db import get_agent_session_maker, get_session_maker
from harness.runtime import AgentRuntime

logger = logging.getLogger(__name__)


async def run_agent_in_background(task_id: str) -> None:
    """后台执行一个分析任务（供 asyncio.create_task 调用）。"""
    try:
        runtime = AgentRuntime(
            agent_session_factory=get_agent_session_maker(),
            business_session_factory=get_session_maker(),
        )
        result = await runtime.execute(task_id)
        logger.info("[worker] task %s finished: %s", task_id, _brief(result))
    except Exception as e:
        # 兜底：runtime 内部应已处理，这里是最后防线
        logger.exception("[worker] task %s crashed: %s", task_id, e)


def _brief(result: dict) -> str:
    """结果摘要（日志用，不打全量）。"""
    if "error" in result and result["error"]:
        return f"error={result['error']}"
    report = result.get("report", {})
    if report:
        return f"report_sections={len(report.get('sections', []))}"
    return "ok"
