"""FastAPI 请求/响应数据契约（Pydantic v2）。

设计要点：
1. 请求与响应分开定义，各管各的。
2. 响应只暴露对外 UUID（task_id/report_id），不暴露自增主键等内部字段。
3. from_attributes=True 支持从 ORM 对象直接构造响应（字段名对齐 models/）。
"""
# datetime：时间字段的类型（序列化时自动转 ISO 格式）
from datetime import datetime

# Any：宽松类型（JSON 列的内容结构不定，用 Any 兜住）
from typing import Any

# BaseModel：Pydantic 数据类基类
# ConfigDict：模型的元配置（from_attributes 开关在这）
# Field：字段配置器（默认值、约束、描述）
from pydantic import BaseModel, ConfigDict, Field


# ==================== 请求 ====================

class CreateTaskRequest(BaseModel):
    """创建分析任务请求体。"""

    # min_length=1：空字符串直接 422（FastAPI 自动校验）
    # max_length=2000：防超大输入
    question: str = Field(min_length=1, max_length=2000, description="用户问题")
    # 默认 analysis：用户不传就用分析类型
    task_type: str = Field(default="analysis", description="analysis / report / sync")
    # None 表示"不传就由服务端决定"（接口层填默认租户）
    tenant_id: str | None = Field(default=None, description="租户，缺省用默认租户")


# ==================== 响应 ====================

class TaskResponse(BaseModel):
    """任务响应：创建/查询共用。"""

    # from_attributes=True：允许从 ORM 对象构造（TaskResponse.model_validate(task)）
    model_config = ConfigDict(from_attributes=True)

    task_id: str                       # 对外 UUID（不自增 id！）
    task_type: str
    question: str
    status: str
    trace_id: str
    error_message: str | None = None   # 可能没有
    created_at: datetime
    finished_at: datetime | None = None  # 未完成时为 None


class TaskListResponse(BaseModel):
    """最近任务列表响应（ORM 没有的聚合字段 total 在这）。"""

    items: list[TaskResponse]
    total: int


class StepResponse(BaseModel):
    """任务执行步骤响应（对应 LangGraph 节点）。"""

    model_config = ConfigDict(from_attributes=True)

    node_name: str
    status: str
    detail: dict[str, Any] | None = None   # JSON 内容，结构不定
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
    """统一错误响应（404 等场景的返回体）。"""

    error: str
    detail: str | None = None