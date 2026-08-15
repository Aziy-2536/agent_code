"""报告路由：查询分析报告。"""
# FastAPI 路由三件套：路由实例 / 依赖注入 / HTTP 错误 / 状态码
from fastapi import APIRouter, Depends, HTTPException, status

# AsyncSession：路由函数参数 db 的类型注解
from sqlalchemy.ext.asyncio import AsyncSession

# get_db：请求级 Session 依赖
from app.api.deps import get_db

# ReportRepository：报告数据访问
from repositories import ReportRepository

# 响应模型：ReportResponse（成功）/ ErrorResponse（404）
from schemas import ErrorResponse, ReportResponse

# 路由实例：prefix=/reports，最终路径 = /api/v1/reports
router = APIRouter(prefix="/reports", tags=["reports"])


@router.get(
    "/{report_id}",                                        # 路径参数：GET /reports/{report_id}
    response_model=ReportResponse,                         # 成功响应模型
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}},  # 404 响应模型
    summary="查询分析报告",
)
async def get_report(
    report_id: str,                           # 路径参数：URL 里的 report_id（UUID）
    db: AsyncSession = Depends(get_db),
) -> ReportResponse:
    """按 report_id（UUID）查报告；不存在返回 404。"""
    repo = ReportRepository(db)
    # 查报告：查不到返回 None
    report = await repo.get_by_report_id(report_id)
    if report is None:
        # 抛 HTTPException -> FastAPI 转成 404 响应
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"report not found: {report_id}",
        )
    # ORM -> Pydantic（from_attributes 按字段名取值）
    return ReportResponse.model_validate(report)
