"""任务相关路由：创建、查询状态、查询执行步骤与工具调用。

设计要点：
- 只做"收请求 -> 调 Repository -> 转 Pydantic 响应"，不含业务逻辑。
- Agent 执行引擎后续接入：create 之后由 Harness 触发执行，
  本文件职责不变（骨架先行，引擎后装）。
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from repositories import TaskRepository
from schemas import (
    CreateTaskRequest,
    ErrorResponse,
    StepResponse,
    TaskResponse,
    ToolCallResponse,
)

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post(
    "",
    response_model=TaskResponse,
    status_code=status.HTTP_201_CREATED,
    summary="创建分析任务",
)
async def create_task(
    req: CreateTaskRequest,
    db: AsyncSession = Depends(get_db),
) -> TaskResponse:
    repo = TaskRepository(db)
    task = await repo.create_task(
        question=req.question,
        task_type=req.task_type,
        tenant_id=req.tenant_id or "default",
    )
    return TaskResponse.model_validate(task)


@router.get(
    "/{task_id}",
    response_model=TaskResponse,
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}},
    summary="查询任务状态",
)
async def get_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
) -> TaskResponse:
    repo = TaskRepository(db)
    task = await repo.get_by_task_id(task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"task not found: {task_id}")
    return TaskResponse.model_validate(task)


@router.get(
    "/{task_id}/steps",
    response_model=list[StepResponse],
    summary="查询任务执行步骤",
)
async def get_task_steps(
    task_id: str,
    db: AsyncSession = Depends(get_db),
) -> list[StepResponse]:
    repo = TaskRepository(db)
    steps = await repo.list_steps(task_id)
    return [StepResponse.model_validate(s) for s in steps]


@router.get(
    "/{task_id}/tool-calls",
    response_model=list[ToolCallResponse],
    summary="查询任务工具调用记录",
)
async def get_task_tool_calls(
    task_id: str,
    db: AsyncSession = Depends(get_db),
) -> list[ToolCallResponse]:
    repo = TaskRepository(db)
    calls = await repo.list_tool_calls(task_id)
    return [ToolCallResponse.model_validate(c) for c in calls]
