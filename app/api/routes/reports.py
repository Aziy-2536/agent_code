"""报告路由：查询分析报告。"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from repositories import ReportRepository
from schemas import ErrorResponse, ReportResponse

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get(
    "/{report_id}",
    response_model=ReportResponse,
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}},
    summary="查询分析报告",
)
async def get_report(
    report_id: str,
    db: AsyncSession = Depends(get_db),
) -> ReportResponse:
    repo = ReportRepository(db)
    report = await repo.get_by_report_id(report_id)
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"report not found: {report_id}")
    return ReportResponse.model_validate(report)
