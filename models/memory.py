"""Agent 记忆/会话域模型（Agent 域 → agent 库）。

设计决策（双库方案 + 记忆分层）：
1. 会话（conversation）＝多轮对话的根，消息挂会话下；任务可挂会话下。
2. 情景记忆（episodic）＝历史任务案例（成败可复用），长期存储。
3. 语义记忆（semantic）＝沉淀的业务规则，质量门禁后写入（置信度 < 0.7 不生效）。
4. 分层关系：conversation（多轮）→ task（单次，已有）→ episodic（跨任务提炼）→ semantic（跨会话沉淀）。
5. 作用域隔离（P0 前置，评审遗留"权限不能串"）：记忆按内容通用性分
   user（仅本人）/ org（组织共享）/ global（系统通用）三级；
   检索注入 prompt 前必须按当前用户作用域过滤。
"""
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from models.base import AgentBase


class Conversation(AgentBase):
    """会话：多轮对话的根实体（一个会话可包含多个分析任务）。"""

    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(
        String(36), unique=True, index=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(String(32), index=True, default="")  # 用户标识
    org_code: Mapped[str] = mapped_column(String(32), index=True, default="")  # 组织/租户（P0：权限维度）
    title: Mapped[str] = mapped_column(String(128), default="")
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")  # ACTIVE / CLOSED
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class ConversationMessage(AgentBase):
    """会话消息：一轮问答（user / assistant / tool）。"""

    __tablename__ = "conversation_messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(String(36), index=True)
    role: Mapped[str] = mapped_column(String(16))  # user / assistant / tool
    content: Mapped[str] = mapped_column(Text, default="")
    task_id: Mapped[str | None] = mapped_column(String(36), nullable=True)  # 关联的分析任务（可选）
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class EpisodicMemory(AgentBase):
    """情景记忆：历史任务执行案例（成败记录，供复用/借鉴）。

    作用域（P0）：默认 user 级（仅归属用户可见）；
    经审批可升格 org / global 供团队/系统复用。
    """

    __tablename__ = "episodic_memories"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    trace_id: Mapped[str] = mapped_column(String(64), index=True, default="")
    task_id: Mapped[str] = mapped_column(String(36), index=True, default="")
    user_id: Mapped[str] = mapped_column(String(32), index=True, default="")   # 归属用户（P0 隔离维度）
    org_code: Mapped[str] = mapped_column(String(32), index=True, default="")  # 归属组织
    scope: Mapped[str] = mapped_column(String(16), default="user")             # user / org / global
    query: Mapped[str] = mapped_column(Text, default="")          # 用户问题
    intent: Mapped[str] = mapped_column(String(32), default="")   # 意图
    success: Mapped[int] = mapped_column(Integer, default=1)      # 1 成功 / 0 失败
    summary: Mapped[str] = mapped_column(Text, default="")        # 执行摘要（供检索/借鉴）
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class SemanticMemory(AgentBase):
    """语义记忆：沉淀的业务规则（质量门禁后写入，随使用动态调整置信度）。

    作用域（P0）：客观规则（口径/模板/映射）→ org / global 共享；
    主观偏好 → 走 user_profiles（本表不承载 user 级内容）。
    user_id 为 None 表示组织/系统级规则。
    """

    __tablename__ = "semantic_memories"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    rule_type: Mapped[str] = mapped_column(String(16), default="sql_pattern")  # sql_pattern / term_mapping / diff_rule
    content: Mapped[str] = mapped_column(Text, default="")        # 规则内容（结构化模板引用，非自由文本）
    user_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True, default=None)  # None=组织/系统级
    org_code: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True, default=None)
    scope: Mapped[str] = mapped_column(String(16), default="org")  # org / global（user 级走 user_profiles）
    confidence: Mapped[float] = mapped_column(Numeric(4, 3), default=0.6)
    usage_count: Mapped[int] = mapped_column(Integer, default=0)  # 被使用次数
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

