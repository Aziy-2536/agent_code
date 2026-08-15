"""任务域持久化模型。

设计决策：
1. 内部主键用自增 BIGINT（索引小、MySQL 擅长），对外 task_id 用 UUID 字符串 + 唯一索引：
   外部无法通过自增 id 枚举他人任务，同时内部关联性能好。
2. 结构多变的字段（工具入参、节点详情）用 JSON 列，避免拆几十个列。
3. 统一 created_at / updated_at / finished_at 命名与语义。
"""
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text, JSON, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """所有模型的公共基类。"""


class AnalysisTask(Base):
    """分析任务主表：一次用户请求的根实体。"""

    __tablename__ = "analysis_tasks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(36), unique=True, index=True, default=lambda: str(uuid.uuid4()))
    task_type: Mapped[str] = mapped_column(String(32), default="analysis")  # analysis / report / sync
    question: Mapped[str] = mapped_column(Text, nullable=False)  # 用户原始问题
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
    task_id: Mapped[str] = mapped_column(String(36), index=True)  # 冗余业务 ID，便于按任务查询
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
    input: Mapped[dict] = mapped_column(JSON)  # 入参（SQL 语句、指标 code 等）
    output: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # 结果摘要
    status: Mapped[str] = mapped_column(String(32), default="SUCCEEDED")  # SUCCEEDED / FAILED / REJECTED
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class HumanApproval(Base):
    """人工审批记录：高风险动作必须留痕。"""

    __tablename__ = "human_approvals"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(36), index=True)
    tool_name: Mapped[str] = mapped_column(String(64))
    params: Mapped[dict] = mapped_column(JSON)  # 待审批的动作参数
    status: Mapped[str] = mapped_column(String(32), default="PENDING")  # PENDING / APPROVED / REJECTED
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)  # 审批人意见
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AnalysisReport(Base):
    """分析报告：任务最终产物，结论与数据依据/引用强关联。"""

    __tablename__ = "analysis_reports"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    report_id: Mapped[str] = mapped_column(String(36), unique=True, index=True, default=lambda: str(uuid.uuid4()))
    task_id: Mapped[str] = mapped_column(String(36), index=True)  # 关联的任务
    title: Mapped[str] = mapped_column(String(256), default="")
    summary: Mapped[str] = mapped_column(Text, default="")  # 报告摘要/结论
    content: Mapped[dict] = mapped_column(JSON)  # 结构化正文（结论/依据/异常明细/建议）
    citations: Mapped[list] = mapped_column(JSON, default=list)  # 知识引用列表（RAG 文档 ID 等）
    status: Mapped[str] = mapped_column(String(32), default="DRAFT")  # DRAFT / REVIEWED / PUBLISHED
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
