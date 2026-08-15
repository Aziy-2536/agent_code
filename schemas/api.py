"""FastAPI 请求/响应数据契约（Pydantic v2）。

设计要点：
1. 请求与响应分开定义，各管各的。
2. 响应只暴露对外 UUID（task_id/report_id），不暴露自增主键等内部字段。
3. from_attributes=True 支持从 ORM 对象直接构造响应（字段名对齐 models/）。
"""
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# ==================== 请求 ====================

class CreateTaskRequest(BaseModel):
    """创建分析任务请求体。"""

    question: str = Field(min_length=1, max_length=2000, description="用户问题")
    task_type: str = Field(default="analysis", description="analysis / report / sync")
    tenant_id: str | None = Field(default=None, description="租户，缺省用默认租户")


# ==================== 响应 ====================

class TaskResponse(BaseModel):
    """任务响应：创建/查询共用。"""

    model_config = ConfigDict(from_attributes=True)

    task_id: str
    task_type: str
    question: str
    status: str
    trace_id: str
    error_message: str | None = None
    created_at: datetime
    finished_at: datetime | None = None


class TaskListResponse(BaseModel):
    """最近任务列表响应。"""

    items: list[TaskResponse]
    total: int


class StepResponse(BaseModel):
    """任务执行步骤响应（对应 LangGraph 节点）。"""

    model_config = ConfigDict(from_attributes=True)

    node_name: str
    status: str
    detail: dict[str, Any] | None = None
    started_at: datetime
    finished_at: datetime | None = None


class ToolCallResponse(BaseModel):
    """工具调用记录响应（审计用）。"""

    model_config = ConfigDict(from_attributes=True)

    tool_name: str
    input: dict[str, Any]
    output: dict[str, Any] | None = None
    status: str
    error: str | None = None
    duration_ms: int


class ReportResponse(BaseModel):
    """分析报告响应。"""

    model_config = ConfigDict(from_attributes=True)

    report_id: str
    task_id: str
    title: str
    summary: str
    content: dict[str, Any]
    citations: list[dict[str, Any]]
    status: str
    created_at: datetime


class ErrorResponse(BaseModel):
    """统一错误响应。"""

    error: str
    detail: str | None = None
