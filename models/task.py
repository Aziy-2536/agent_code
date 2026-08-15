"""任务域持久化模型。

设计决策：
1. 内部主键自增 BIGINT，对外 task_id 用 UUID + 唯一索引（防枚举）。
2. 多变结构（工具入参、节点详情）用 JSON 列。
3. 时间字段统一 created_at / updated_at / finished_at 命名。
"""
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, Text, JSON, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """所有模型的公共基类（建表时按它的 metadata 建）。"""


class AnalysisTask(Base):
    """分析任务主表：一次用户请求的根实体。"""

    __tablename__ = "analysis_tasks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(
        String(36), unique=True, index=True,
        default=lambda: str(uuid.uuid4()),   # 创建时自动生成 UUID
    )
    task_type: Mapped[str] = mapped_column(String(32), default="analysis")
    question: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="CREATED", index=True)
    tenant_id: Mapped[str] = mapped_column(String(64), default="default", index=True)
    trace_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    budget_tokens: Mapped[int] = mapped_column(BigInteger, default=50_000)
    cost_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    
class TaskStep(Base):
    """任务内部执行步骤（对应 LangGraph 节点的一次执行）。"""

    __tablename__ = "task_steps"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(36), index=True)
    node_name: Mapped[str] = mapped_column(String(32))  # route / plan / act / observe / review / report
    status: Mapped[str] = mapped_column(String(32), default="RUNNING")
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # 节点中间结果
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ToolCall(Base):
    """工具调用记录：审计与评测的关键数据源。"""

    __tablename__ = "tool_calls"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(36), index=True)
    tool_name: Mapped[str] = mapped_column(String(64))
    input: Mapped[dict] = mapped_column(JSON)
    output: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="SUCCEEDED")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class HumanApproval(Base):
    """人工审批记录：高风险动作必须留痕。"""

    __tablename__ = "human_approvals"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(36), index=True)
    tool_name: Mapped[str] = mapped_column(String(64))
    params: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(32), default="PENDING")  # PENDING / APPROVED / REJECTED
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AnalysisReport(Base):
    """分析报告：任务最终产物，结论与数据依据/引用强关联。"""

    __tablename__ = "analysis_reports"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    report_id: Mapped[str] = mapped_column(
        String(36), unique=True, index=True,
        default=lambda: str(uuid.uuid4()),
    )
    task_id: Mapped[str] = mapped_column(String(36), index=True)
    title: Mapped[str] = mapped_column(String(256), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    content: Mapped[dict] = mapped_column(JSON)          # 结构化正文
    citations: Mapped[list] = mapped_column(JSON, default=list)  # 知识引用列表
    status: Mapped[str] = mapped_column(String(32), default="DRAFT")  # DRAFT / REVIEWED / PUBLISHED
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    
