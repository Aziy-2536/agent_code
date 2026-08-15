"""任务数据访问：任务/步骤/工具调用/审批的读写。

设计决策：
1. Session 由外部注入（FastAPI 依赖注入或调用方），本类不创建 session、
   不管理事务生命周期——调用方决定 commit 时机。
2. 只暴露业务语义方法（create / get / update_status），不暴露 SQL。
3. 返回 ORM 对象，序列化交给上层。
"""
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import AnalysisTask, HumanApproval, TaskStep, ToolCall


class TaskRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ---------- 任务 ----------
    async def create_task(
        self,
        question: str,
        task_type: str = "analysis",
        tenant_id: str = "default",
        trace_id: str = "",
    ) -> AnalysisTask:
        """创建任务并落库，返回带 task_id 的任务对象。"""
        task = AnalysisTask(
            question=question,
            task_type=task_type,
            tenant_id=tenant_id,
            trace_id=trace_id,
            status="CREATED",
        )
        self._session.add(task)
        await self._session.commit()
        await self._session.refresh(task)
        return task

    async def get_by_task_id(self, task_id: str) -> AnalysisTask | None:
        result = await self._session.execute(
            select(AnalysisTask).where(AnalysisTask.task_id == task_id)
        )
        return result.scalar_one_or_none()

    async def update_status(
        self,
        task_id: str,
        status: str,
        error_message: str | None = None,
    ) -> AnalysisTask | None:
        """更新任务状态；终态（SUCCEEDED/FAILED）时记录完成时间。"""
        task = await self.get_by_task_id(task_id)
        if task is None:
            return None
        task.status = status
        if error_message is not None:
            task.error_message = error_message
        if status in ("SUCCEEDED", "FAILED"):
            task.finished_at = datetime.now()
        await self._session.commit()
        return task

    async def list_recent(self, limit: int = 20) -> list[AnalysisTask]:
        result = await self._session.execute(
            select(AnalysisTask).order_by(AnalysisTask.id.desc()).limit(limit)
        )
        return list(result.scalars().all())

    # ---------- 步骤 ----------
    async def add_step(
        self,
        task_id: str,
        node_name: str,
        detail: dict | None = None,
    ) -> TaskStep:
        step = TaskStep(task_id=task_id, node_name=node_name, detail=detail)
        self._session.add(step)
        await self._session.commit()
        return step

    async def list_steps(self, task_id: str) -> list[TaskStep]:
        result = await self._session.execute(
            select(TaskStep)
            .where(TaskStep.task_id == task_id)
            .order_by(TaskStep.id)
        )
        return list(result.scalars().all())

    # ---------- 工具调用（审计数据源） ----------
    async def add_tool_call(
        self,
        task_id: str,
        tool_name: str,
        input: dict,
        output: dict | None = None,
        status: str = "SUCCEEDED",
        error: str | None = None,
        duration_ms: int = 0,
    ) -> ToolCall:
        call = ToolCall(
            task_id=task_id,
            tool_name=tool_name,
            input=input,
            output=output,
            status=status,
            error=error,
            duration_ms=duration_ms,
        )
        self._session.add(call)
        await self._session.commit()
        return call

    async def list_tool_calls(self, task_id: str) -> list[ToolCall]:
        result = await self._session.execute(
            select(ToolCall)
            .where(ToolCall.task_id == task_id)
            .order_by(ToolCall.id)
        )
        return list(result.scalars().all())

    # ---------- 人工审批 ----------
    async def add_approval(self, task_id: str, tool_name: str, params: dict) -> HumanApproval:
        approval = HumanApproval(task_id=task_id, tool_name=tool_name, params=params)
        self._session.add(approval)
        await self._session.commit()
        return approval

    async def get_approval(self, approval_id: int) -> HumanApproval | None:
        return await self._session.get(HumanApproval, approval_id)
