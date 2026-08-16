"""持久化模型包：统一导出，供建表脚本与 Repository 使用。

双库划分：
- AgentBase（→ agent 库）：任务域 + 记忆域
- BusinessBase（→ power_insight 库）：业务域 + 知识域
"""
from models.base import AgentBase, BusinessBase
from models.dongguan import (
    DimLine,
    DimMeter,
    DimRegion,
    DimTaiqu,
    DimUser,
    FactLineLoss,
    FactRegionDaily,
    FactTaiquDaily,
    FactUserDaily,
)
from models.knowledge import MetricDefinition
from models.memory import (
    Conversation,
    ConversationMessage,
    EpisodicMemory,
    SemanticMemory,
)
from models.metadata import MetaField, MetaTable, MetaValue
from models.power import LineLossDetail, RegionDailyMetric
from models.task import AnalysisReport, AnalysisTask, HumanApproval, TaskStep, ToolCall

# Agent 域（→ agent 库）
AGENT_MODELS = [AnalysisTask, TaskStep, ToolCall, HumanApproval, AnalysisReport,
                Conversation, ConversationMessage, EpisodicMemory, SemanticMemory]

# 业务域（→ power_insight 库）
BUSINESS_MODELS = [DimRegion, DimLine, DimTaiqu, DimUser, DimMeter,
                   FactRegionDaily, FactLineLoss, FactTaiquDaily, FactUserDaily,
                   MetricDefinition, RegionDailyMetric, LineLossDetail,
                   MetaTable, MetaField, MetaValue]

__all__ = [
    # 双基类
    "AgentBase",
    "BusinessBase",
    # Agent 域：任务
    "AnalysisTask",
    "TaskStep",
    "ToolCall",
    "HumanApproval",
    "AnalysisReport",
    # Agent 域：记忆/会话
    "Conversation",
    "ConversationMessage",
    "EpisodicMemory",
    "SemanticMemory",
    # 业务域：知识
    "MetricDefinition",
    # 业务域：元数据知识库
    "MetaTable",
    "MetaField",
    "MetaValue",
    # 业务域：旧版业务表（Agent 主链路跑通后清理）
    "RegionDailyMetric",
    "LineLossDetail",
    # 业务域：东莞版维度
    "DimRegion",
    "DimLine",
    "DimTaiqu",
    "DimUser",
    "DimMeter",
    # 业务域：东莞版汇总
    "FactRegionDaily",
    "FactLineLoss",
    "FactTaiquDaily",
    "FactUserDaily",
]
