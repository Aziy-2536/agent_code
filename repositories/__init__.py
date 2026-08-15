"""数据访问层：统一导出 Repository。

用法（FastAPI 依赖注入示例）：
    repo = TaskRepository(session)   # session 来自 get_db() 依赖
"""
# 把各 Repository 提到包级别：
#   外部只需要 from repositories import XxxRepository，不用关心具体文件
from repositories.dongguan_repository import DongguanRepository  # 东莞版业务查询（缓存优先）
from repositories.power_repository import PowerRepository  # 旧版电力业务查询（只读）
from repositories.report_repository import ReportRepository  # 报告存取
from repositories.task_repository import TaskRepository  # 任务/步骤/工具/审批

# __all__：from repositories import * 时导出哪些名字（白名单）
__all__ = [
    "TaskRepository",
    "ReportRepository",
    "PowerRepository",
    "DongguanRepository",
]
