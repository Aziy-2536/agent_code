"""问数工具：模板化查询的执行体（接 DongguanRepository）。

设计决策（问数 = 模板化查询，不自由 NL2SQL）：
1. 每个工具对应一类"预设问题模板"（区域指标/高损线路/高损台区/户级用电/台区对账）。
   LLM 只提取参数（region/metric/days/阈值），**绝不生成 SQL**——
   工具内部用参数化查询，从机制上规避 SQL 注入与明细扫描。
2. 工具输出统一为 QueryResult 可用的 dict 结构（rows/columns/meta）。
3. 依赖注入：每个 run 函数接收一个 Repository 工厂（注入 session），
   便于在节点里用 get_db() 的 session 创建。
4. 脱敏：户级工具返回前经 Repository 的脱敏逻辑（PII 不出库）。
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Callable

from pydantic import BaseModel, Field

from repositories.dongguan_repository import DongguanRepository
from tools.base import Tool, ToolError
from tools.registry import registry

# Repository 工厂类型：节点注入 session，工具用工厂拿到 Repository
RepoFactory = Callable[[], DongguanRepository]


# ==================== 工具输入模型（Pydantic = 契约 + LLM JSON schema） ====================

class _RegionMetricsInput(BaseModel):
    """区域指标查询入参。"""
    region_code: str = Field(description="镇街编码，如 DG012（虎门镇）")
    metric: str = Field(description="指标 code：line_loss_rate/collection_rate/supply_kwh/sale_kwh")
    days: int = Field(default=30, ge=1, le=365, description="最近 N 天")


class _HighLossInput(BaseModel):
    """高损查询入参（线路/台区共用）。"""
    region_code: str | None = Field(default=None, description="限定镇街编码，可空=全部")
    loss_threshold: float = Field(default=0.10, gt=0, lt=1, description="线损率阈值（比例小数 0.10=10%）")
    limit: int = Field(default=10, ge=1, le=100)


class _UserUsageInput(BaseModel):
    """户级用电查询入参。"""
    user_id: str = Field(description="用户编号，如 U-DG012-001")
    days: int = Field(default=7, ge=1, le=90, description="最近 N 天")


class _TaiquReconcileInput(BaseModel):
    """台区对账入参。"""
    taiqu_code: str = Field(description="台区编号，如 TQ-DG001-L1-1")
    days: int = Field(default=7, ge=1, le=30, description="最近 N 天")


# ==================== 工具执行函数（接 Repository） ====================

async def _run_region_metrics(input: _RegionMetricsInput, repo: DongguanRepository) -> dict:
    """区域指标查询：某镇街某指标近 N 天序列。"""
    end = date.today()
    start = end - timedelta(days=input.days - 1)
    rows = await repo.get_region_metrics(input.region_code, start, end)
    # 只保留目标指标列（模板化：口径 = metric 字段，不自由选列）
    metric_labels = {
        "line_loss_rate": ("线损率", "%"),
        "collection_rate": ("回收率", "%"),
        "supply_kwh": ("供电量", "kWh"),
        "sale_kwh": ("售电量", "kWh"),
    }
    label, unit = metric_labels.get(input.metric, (input.metric, ""))
    data = [
        {"stat_date": r.get("stat_date"), input.metric: r.get(input.metric)}
        for r in rows
    ]
    return {
        "rows": data,
        "columns": [
            {"name": "stat_date", "label": "日期", "unit": ""},
            {"name": input.metric, "label": label, "unit": unit},
        ],
        "meta": {"metric": input.metric, "region_code": input.region_code, "days": input.days},
    }


async def _run_high_loss_lines(input: _HighLossInput, repo: DongguanRepository) -> dict:
    """高损线路查询。"""
    rows = await repo.list_high_loss_lines(input.loss_threshold, input.region_code, input.limit)
    return {
        "rows": rows,
        "columns": [
            {"name": "line_code", "label": "线路编号", "unit": ""},
            {"name": "region_code", "label": "镇街", "unit": ""},
            {"name": "loss_rate", "label": "线损率", "unit": "%"},
            {"name": "stat_date", "label": "日期", "unit": ""},
        ],
        "meta": {"threshold": input.loss_threshold, "limit": input.limit},
    }


async def _run_high_loss_taiqu(input: _HighLossInput, repo: DongguanRepository) -> dict:
    """高损台区查询。"""
    rows = await repo.list_high_loss_taiqu(input.loss_threshold, input.region_code, input.limit)
    return {
        "rows": rows,
        "columns": [
            {"name": "taiqu_code", "label": "台区编号", "unit": ""},
            {"name": "loss_rate", "label": "线损率", "unit": "%"},
            {"name": "stat_date", "label": "日期", "unit": ""},
        ],
        "meta": {"threshold": input.loss_threshold, "limit": input.limit},
    }


async def _run_user_usage(input: _UserUsageInput, repo: DongguanRepository) -> dict:
    """户级用电查询（PII 脱敏由 Repository 保证）。"""
    end = date.today()
    start = end - timedelta(days=input.days - 1)
    rows = await repo.get_user_daily_usage(input.user_id, start, end)
    return {
        "rows": rows,
        "columns": [
            {"name": "stat_date", "label": "日期", "unit": ""},
            {"name": "kwh", "label": "用电量", "unit": "kWh"},
        ],
        "meta": {"user_id": input.user_id, "days": input.days},
    }


async def _run_taiqu_reconcile(input: _TaiquReconcileInput, repo: DongguanRepository) -> dict:
    """台区线损对账：Σ户表 vs 台区总表。"""
    end = date.today()
    start = end - timedelta(days=input.days - 1)
    rows = await repo.reconcile_taiqu_loss(input.taiqu_code, start, end)
    return {
        "rows": rows,
        "columns": [
            {"name": "stat_date", "label": "日期", "unit": ""},
            {"name": "supply_kwh", "label": "台区供电", "unit": "kWh"},
            {"name": "sum_user_kwh", "label": "Σ户表", "unit": "kWh"},
            {"name": "loss_kwh", "label": "线损电量", "unit": "kWh"},
            {"name": "loss_rate", "label": "线损率", "unit": "%"},
        ],
        "meta": {"taiqu_code": input.taiqu_code, "days": input.days},
    }


# ==================== 工具注册（白名单） ====================

def register_query_tools(repo_factory: RepoFactory) -> None:
    """注册全部问数工具（绑定 Repository 工厂）。

    在 harness 启动时调用一次；LLM 的 Function Calling 定义由 registry 统一生成。
    """
    # 用闭包把 repo_factory 绑定进每个 run 函数
    registry.register(Tool(
        name="get_region_metrics",
        description="查询某镇街某指标（线损率/回收率/供电量/售电量）近 N 天的日度序列。"
                    "当用户问「某镇街/某区域的线损率、回收率、供电量走势」时用。",
        input_model=_RegionMetricsInput,
        run=lambda i: _run_region_metrics(i, repo_factory()),
    ))
    registry.register(Tool(
        name="get_high_loss_lines",
        description="查询线损率超过阈值的线路排名（高损线路）。当用户问「哪些线路高损/线损超标」时用。",
        input_model=_HighLossInput,
        run=lambda i: _run_high_loss_lines(i, repo_factory()),
    ))
    registry.register(Tool(
        name="get_high_loss_taiqu",
        description="查询线损率超过阈值的台区排名（高损台区）。当用户问「哪些台区高损」时用。",
        input_model=_HighLossInput,
        run=lambda i: _run_high_loss_taiqu(i, repo_factory()),
    ))
    registry.register(Tool(
        name="get_user_daily_usage",
        description="查询某用户近 N 天的日用电量。当用户问「某户/某用户用了多少电」时用。",
        input_model=_UserUsageInput,
        run=lambda i: _run_user_usage(i, repo_factory()),
    ))
    registry.register(Tool(
        name="reconcile_taiqu_loss",
        description="台区线损对账：Σ户表电量 vs 台区总表电量。当用户问「某台区线损对不对/对账」时用。",
        input_model=_TaiquReconcileInput,
        run=lambda i: _run_taiqu_reconcile(i, repo_factory()),
    ))
