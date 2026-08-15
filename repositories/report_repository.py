"""分析报告数据访问。

设计决策：
- 报告的 content 是结构化 JSON（结论/依据/异常明细/建议），citations 是引用列表，
  两者都用 JSON 列存储，便于检索与序列化。
"""
# select：SQLAlchemy 查询构造器（代替手写 SELECT）
from sqlalchemy import select

# AsyncSession：异步会话类型（用于类型注解）
from sqlalchemy.ext.asyncio import AsyncSession

# 报告模型：这个 Repository 操作的对象
from models import AnalysisReport


class ReportRepository:
    """分析报告数据访问仓库：保存报告、按 id/task 查询。"""

    def __init__(self, session: AsyncSession) -> None:
        # session 从外部注入（与 TaskRepository 一致），本类不管理事务生命周期
        self._session = session

    async def save(
        self,
        task_id: str,                    # 关联的任务 id
        title: str,                      # 报告标题
        summary: str,                    # 摘要/结论
        content: dict,                   # 结构化正文（JSON）
        citations: list | None = None,   # 知识引用列表
        status: str = "DRAFT",           # 状态：DRAFT / REVIEWED / PUBLISHED
    ) -> AnalysisReport:
        """保存新报告（或按 task_id 覆盖更新）。

        设计：upsert 语义（有则更新，无则新建）
        ——一个任务最多一份报告，Agent 可能多次生成，后一次覆盖前一次。
        """
        # 第 1 步：查这个任务是否已有报告
        existing = await self.get_by_task_id(task_id)
        if existing is not None:
            # 已有 → 更新字段（改属性，commit 时自动 UPDATE）
            existing.title = title
            existing.summary = summary
            existing.content = content
            existing.citations = citations or []   # None 时用空列表
            existing.status = status
            await self._session.commit()
            return existing

        # 第 2 步：没有 → 新建
        report = AnalysisReport(
            task_id=task_id, title=title, summary=summary,
            content=content, citations=citations or [], status=status,
        )
        self._session.add(report)          # 加入会话
        await self._session.commit()       # 写库（此时生成 report_id / created_at）
        await self._session.refresh(report)  # 刷新：读回数据库生成的值
        return report

    async def get_by_report_id(self, report_id: str) -> AnalysisReport | None:
        """按对外 report_id（UUID）查报告。"""
        # SELECT * FROM analysis_reports WHERE report_id = :id
        result = await self._session.execute(
            select(AnalysisReport).where(AnalysisReport.report_id == report_id)
        )
        # 0 条 → None；1 条 → 对象；多条 → 报错（report_id 唯一，正常不会发生）
        return result.scalar_one_or_none()

    async def get_by_task_id(self, task_id: str) -> AnalysisReport | None:
        """按任务查报告（一个任务最多一份）。"""
        result = await self._session.execute(
            select(AnalysisReport).where(AnalysisReport.task_id == task_id)
        )
        return result.scalar_one_or_none()

    async def list_recent(self, limit: int = 20) -> list[AnalysisReport]:
        """最近报告列表（id 倒序 = 最新在前）。"""
        result = await self._session.execute(
            select(AnalysisReport).order_by(AnalysisReport.id.desc()).limit(limit)
        )
        return list(result.scalars().all())
