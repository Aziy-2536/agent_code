"""任务路由：创建任务、查询状态、查询执行步骤与工具调用。

设计要点：
- 只做"收请求 -> 调 Repository -> 转 Pydantic 响应"，不含业务逻辑。
- Agent 执行引擎后续接入：create 之后由 Harness 触发执行，本文件职责不变。
"""
# FastAPI 路由三件套：
#   APIRouter   = 路由实例（把一组接口组织成一个模块）
#   Depends     = 依赖注入器（把 get_db 产出的 session 传给函数）
#   HTTPException = 抛 HTTP 错误（如 404）的标准方式
#   status      = HTTP 状态码常量（如 status.HTTP_201_CREATED）
from fastapi import APIRouter, Depends, HTTPException, status

# AsyncSession：路由函数参数 db 的类型注解
from sqlalchemy.ext.asyncio import AsyncSession

# get_db：自定义依赖（产出请求级 Session）
from app.api.deps import get_db

# TaskRepository：任务数据访问（真正的数据操作在这里）
from repositories import TaskRepository

# Pydantic Schema：
#   CreateTaskRequest  = 请求体（创建任务时收什么）
#   ErrorResponse      = 404 时的响应体
#   TaskResponse       = 任务响应（创建/查询共用）
#   StepResponse       = 步骤响应
#   ToolCallResponse   = 工具调用响应
from schemas import (
    CreateTaskRequest,
    ErrorResponse,
    StepResponse,
    TaskResponse,
    ToolCallResponse,
)

# 路由实例：本模块内所有接口的路径前缀是 /tasks
#   最终完整路径 = /api/v1/tasks（main.py 挂载时再拼 api_prefix）
router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post(
    "",                                       # 路径：POST /tasks（空 = 用 prefix 本身）
    response_model=TaskResponse,              # 成功响应的 Pydantic 模型（FastAPI 据此序列化）
    status_code=status.HTTP_201_CREATED,      # 成功状态码：201 Created
    summary="创建分析任务",                     # OpenAPI 文档里显示的接口说明
)
async def create_task(
    req: CreateTaskRequest,                   # 请求体：FastAPI 自动按 CreateTaskRequest 校验
                                              #   - question 为空 → 自动 422（不用自己写 if）
    db: AsyncSession = Depends(get_db),       # 依赖注入：从 get_db 拿请求级 Session
) -> TaskResponse:
    """提交一个分析任务，返回任务信息（状态初始 CREATED）。

    创建后立即触发后台执行（asyncio.create_task），接口不等执行完成——
    返回 201，客户端轮询 GET /tasks/{task_id} 看状态。
    """
    # 创建 Repository（把注入的 session 传进去）
    repo = TaskRepository(db)
    # 调用 Repository 建任务（写入 MySQL）
    task = await repo.create_task(
        question=req.question,                # 用户问题（已过 Pydantic 校验）
        task_type=req.task_type,              # 任务类型（默认 analysis）
        tenant_id=req.tenant_id or "default", # 用户没传就用默认租户
    )

    # 后台执行 Agent（不阻塞响应）；task_id 已由 create_task 生成
    import asyncio

    from app.workers.analysis_worker import run_agent_in_background
    asyncio.create_task(run_agent_in_background(task.task_id))

    # model_validate：ORM 对象 -> Pydantic 响应
    return TaskResponse.model_validate(task)


@router.get(
    "/{task_id}",                                        # 路径参数：GET /tasks/{task_id}
    response_model=TaskResponse,                         # 成功响应模型
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}},  # 404 时的响应模型
    summary="查询任务状态",
)
async def get_task(
    task_id: str,                             # 路径参数：URL 里的 task_id
    db: AsyncSession = Depends(get_db),
) -> TaskResponse:
    """按 task_id 查任务；不存在返回 404。"""
    repo = TaskRepository(db)
    # 查任务：查不到返回 None
    task = await repo.get_by_task_id(task_id)
    if task is None:
        # 抛 HTTPException：FastAPI 自动转成 404 响应（带 ErrorResponse 结构）
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"task not found: {task_id}",
        )
    return TaskResponse.model_validate(task)


@router.get(
    "/{task_id}/steps",                      # 路径：GET /tasks/{task_id}/steps
    response_model=list[StepResponse],       # 响应是 StepResponse 列表
    summary="查询任务执行步骤",
)
async def get_task_steps(
    task_id: str,
    db: AsyncSession = Depends(get_db),
) -> list[StepResponse]:
    """查任务的 LangGraph 节点执行记录。"""
    repo = TaskRepository(db)
    # 查步骤列表（按执行顺序）
    steps = await repo.list_steps(task_id)
    # 列表推导：每个 ORM 步骤对象 -> StepResponse（批量转换）
    return [StepResponse.model_validate(s) for s in steps]


@router.get(
    "/{task_id}/tool-calls",                 # 路径：GET /tasks/{task_id}/tool-calls
    response_model=list[ToolCallResponse],
    summary="查询任务工具调用记录",
)
async def get_task_tool_calls(
    task_id: str,
    db: AsyncSession = Depends(get_db),
) -> list[ToolCallResponse]:
    """查任务执行过程中的工具调用明细（审计用）。"""
    repo = TaskRepository(db)
    # 查工具调用列表
    calls = await repo.list_tool_calls(task_id)
    return [ToolCallResponse.model_validate(c) for c in calls]
