"""任务生命周期、取消和重试协调（状态机）。

设计决策（任务状态机的最小可用版）：
1. 状态由 models.AnalysisTask.status 承载，状态流转在此集中定义——
   业务代码不散落改 status 字符串，统一走 TaskManager。
2. 状态机（终态不可再流转）：
   CREATED → RUNNING → SUCCEEDED / FAILED / NEEDS_CLARIFICATION
   CREATED → CANCELED（未开始可直接取消）
3. 本类不持有 session——依赖外部注入的 TaskRepository（或 session 工厂），
   与 Repository 层"session 外部注入"的纪律一致。
"""
from __future__ import annotations

from typing import Callable

from repositories.task_repository import TaskRepository


class TaskStateError(Exception):
    """非法状态流转（如从终态再改）。"""


# 允许的状态流转表：当前状态 → 允许的下一状态集合
_TRANSITIONS: dict[str, set[str]] = {
    "CREATED": {"RUNNING", "CANCELED"},
    "RUNNING": {"SUCCEEDED", "FAILED", "NEEDS_CLARIFICATION", "CANCELED"},
    "SUCCEEDED": set(),           # 终态
    "FAILED": set(),              # 终态
    "NEEDS_CLARIFICATION": {"RUNNING"},  # 用户补充后可重新运行
    "CANCELED": set(),            # 终态
}

# 终态集合
_TERMINAL = {"SUCCEEDED", "FAILED", "CANCELED"}


class TaskManager:
    """任务状态机：集中管理 status 流转。"""

    def __init__(self, repo: TaskRepository):
        self._repo = repo

    @staticmethod
    def can_transition(current: str, target: str) -> bool:
        """判断状态流转是否合法（纯函数，可独立测试）。"""
        return target in _TRANSITIONS.get(current, set())

    @staticmethod
    def is_terminal(status: str) -> bool:
        return status in _TERMINAL

    async def transition(self, task_id: str, target: str, error: str | None = None) -> None:
        """执行一次状态流转；非法流转抛 TaskStateError。"""
        task = await self._repo.get_by_task_id(task_id)
        if task is None:
            return  # 任务不存在，静默（调用方负责 404）
        if not self.can_transition(task.status, target):
            raise TaskStateError(
                f"非法状态流转: {task.status} → {target} (task={task_id})"
            )
        await self._repo.update_status(task_id, target, error_message=error)
