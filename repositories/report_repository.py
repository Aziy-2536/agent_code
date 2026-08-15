"""分析报告数据访问。

设计决策：
- 报告的 content 是结构化 JSON（结论/依据/异常明细/建议），citations 是引用列表，
  两者都用 JSON 列存储，便于检索与序列化，避免几十个固定列。
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import AnalysisReport


class ReportRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(
        self,
        task_id: str,
        title: str,
        summary: str,
        content: dict,
        citations: list | None = None,
        status: str = "DRAFT",
    ) -> AnalysisReport:
        """保存新报告（或按 task_id 覆盖更新）。"""
        existing = await self.get_by_task_id(task_id)
        if existing is not None:
            existing.title = title
            existing.summary = summary
            existing.content = content
            existing.citations = citations or []
            existing.status = status
            await self._session.commit()
            return existing

        report = AnalysisReport(
            task_id=task_id,
            title=title,
            summary=summary,
            content=content,
            citations=citations or [],
            status=status,
        )
        self._session.add(report)
        await self._session.commit()
        await self._session.refresh(report)
        return report

    async def get_by_report_id(self, report_id: str) -> AnalysisReport | None:
        result = await self._session.execute(
            select(AnalysisReport).where(AnalysisReport.report_id == report_id)
        )
        return result.scalar_one_or_none()

    async def get_by_task_id(self, task_id: str) -> AnalysisReport | None:
        result = await self._session.execute(
            select(AnalysisReport).where(AnalysisReport.task_id == task_id)
        )
        return result.scalar_one_or_none()

    async def list_recent(self, limit: int = 20) -> list[AnalysisReport]:
        result = await self._session.execute(
            select(AnalysisReport).order_by(AnalysisReport.id.desc()).limit(limit)
        )
        return list(result.scalars().all())
