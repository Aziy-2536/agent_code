"""数据访问层：统一导出 Repository 工厂。

用法（FastAPI 依赖注入示例）：
    repo = TaskRepository(session)   # session 来自 get_db() 依赖
"""

from repositories.power_repository import PowerRepository
from repositories.report_repository import ReportRepository
from repositories.task_repository import TaskRepository

__all__ = ["TaskRepository", "ReportRepository", "PowerRepository"]
