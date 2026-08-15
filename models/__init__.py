"""持久化模型包：统一导出，供建表脚本与 Repository 使用。"""

from models.dongguan import (
    DimLine,
    DimMeter,
    DimRegion,
    DimTaiqu,
    DimUser,
    FactLineLoss,
    FactRegionDaily,
    FactTaiquDaily,
)
from models.knowledge import MetricDefinition
from models.power import LineLossDetail, RegionDailyMetric
from models.task import AnalysisReport, AnalysisTask, Base, HumanApproval, TaskStep, ToolCall

__all__ = [
    "Base",
    # 任务域
    "AnalysisTask",
    "TaskStep",
    "ToolCall",
    "HumanApproval",
    "AnalysisReport",
    # 知识域
    "MetricDefinition",
    # 旧版业务表（Agent 主链路跑通后清理）
    "RegionDailyMetric",
    "LineLossDetail",
    # 东莞版：维度层
    "DimRegion",
    "DimLine",
    "DimTaiqu",
    "DimUser",
    "DimMeter",
    # 东莞版：汇总层
    "FactRegionDaily",
    "FactLineLoss",
    "FactTaiquDaily",
]
