"""LangGraph 执行运行时包装器（Agent 执行入口）。

设计决策：
1. Runtime 是"一次任务执行"的编排者：装配 AgentContext → 跑图 → 落库。
   业务代码不直接调图，统一走 Runtime.execute()。
2. 双库隔离（session 边界清晰）：
   - agent 库 session（任务/报告/状态）→ task_repo / report_repo
   - 业务库 session（东莞数据/元数据）→ business_repo / meta_repo
   两个 session 生命周期由调用方（worker/路由）管理，runtime 不负责关闭。
3. 元数据上下文在任务开始前组装（MetaStoreRepository.build_context），
   注入 route 节点的 LLM prompt——"先理解上下文再动手"。
4. 状态机：CREATED → RUNNING → SUCCEEDED/FAILED/NEEDS_CLARIFICATION。
"""
from __future__ import annotations

from typing import Callable, Any

from harness.task_manager import TaskManager
from orchestration.context import AgentContext
from orchestration.graph import graph
from orchestration.state import AgentState
from repositories.meta_repository import MetaStoreRepository
from repositories.report_repository import ReportRepository
from repositories.task_repository import TaskRepository
from schemas.agent import ReportInput
from tools.query_tools import register_query_tools


class AgentRuntime:
    """Agent 执行运行时（一次任务一次执行）。

    Args:
        agent_session_factory: () -> AsyncSession（agent 库）
        business_session_factory: () -> AsyncSession（业务库 power_insight）
    """

    def __init__(
        self,
        agent_session_factory: Callable[[], Any],
        business_session_factory: Callable[[], Any],
    ):
        self._agent_session_factory = agent_session_factory
        self._business_session_factory = business_session_factory

    async def execute(self, task_id: str) -> dict:
        """执行一个任务：装配上下文 → 跑图 → 落库 → 更新状态。

        返回最终 state（含 report）。
        """
        # 双库 session：agent（任务/报告）+ business（数据/元数据）
        async with self._agent_session_factory() as agent_session, \
                   self._business_session_factory() as business_session:

            task_repo = TaskRepository(agent_session)
            task = await task_repo.get_by_task_id(task_id)
            if task is None:
                return {"error": f"task not found: {task_id}"}

            manager = TaskManager(task_repo)

            # 1. CREATED → RUNNING
            await manager.transition(task_id, "RUNNING")

            # 2. 装配上下文（元数据 + 依赖 + 工具）
            ctx = await self._build_context(
                task_id, business_session, agent_session
            )

            # 3. 跑图
            try:
                final_state = await graph.ainvoke(
                    {"query": task.question},
                    context=ctx,
                )
            except Exception as e:
                await manager.transition(task_id, "FAILED", error=str(e))
                return {"error": str(e)}

            # 4. 落库报告 + 终态
            await self._persist_result(task_id, manager, task_repo, agent_session, final_state)
            return final_state

    async def _build_context(
        self,
        task_id: str,
        business_session: Any,
        agent_session: Any,
    ) -> AgentContext:
        """装配 AgentContext：元数据上下文 + Repository 工厂 + 工具注册。"""
        ctx = AgentContext(task_id=task_id)

        # Repository 工厂（闭包绑定 session）
        from repositories.dongguan_repository import DongguanRepository

        ctx.business_repo_factory = lambda: DongguanRepository(business_session)
        ctx.meta_repo_factory = lambda: MetaStoreRepository(business_session)

        # 元数据上下文（表/字段/取值）——注入 LLM
        try:
            ctx.meta_context = await MetaStoreRepository(business_session).build_context()
        except Exception:
            ctx.meta_context = ""  # 元数据不可用不阻塞执行

        # 注册真实工具（白名单）
        register_query_tools(ctx.business_repo_factory)

        return ctx

    async def _persist_result(
        self,
        task_id: str,
        manager: TaskManager,
        task_repo: TaskRepository,
        agent_session: Any,
        final_state: dict,
    ) -> None:
        """落库：报告 + 任务终态。"""
        clarification = final_state.get("clarification_needed", [])

        if clarification:
            await manager.transition(task_id, "NEEDS_CLARIFICATION")
        elif final_state.get("error"):
            await manager.transition(task_id, "FAILED", error=final_state["error"])
        else:
            await manager.transition(task_id, "SUCCEEDED")
            await self._save_report(task_id, agent_session, final_state.get("report"))

    async def _save_report(self, task_id: str, agent_session: Any, report_data: dict | None) -> None:
        """把 ReportInput 落 analysis_reports 表。"""
        if not report_data:
            return
        try:
            report = ReportInput.model_validate(report_data)
        except Exception:
            return  # 报告解析失败不阻塞任务状态

        report_repo = ReportRepository(agent_session)
        intent = report.intent.value if hasattr(report.intent, "value") else str(report.intent)
        title = f"[{intent}] {report.query[:40]}"
        await report_repo.save(
            task_id=task_id,
            title=title,
            summary=self._build_summary(report),
            content={"sections": [s.model_dump(mode="json") for s in report.sections]},
        )

    @staticmethod
    def _build_summary(report: ReportInput) -> str:
        """从报告段落提取摘要（insight 段优先，否则首段）。"""
        for s in report.sections:
            if s.kind == "insight" and s.content:
                return s.content[:200]
        for s in report.sections:
            if s.content:
                return s.content[:200]
        return "报告已生成"
