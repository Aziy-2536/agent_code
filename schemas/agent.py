"""Agent 内部数据契约（主链路的数据层地基）。

本文件是 Agent 主链路的**契约层**——所有节点（route/act/report）之间
通过这里的类型通信。设计原则：

1. **全部用 Pydantic 模型**（不是 TypedDict）：
   - 结构化校验：字段缺失/类型错在建图入口就报错，而不是运行到一半才炸
   - 序列化零成本：直接 .model_dump() 落库（task_steps.detail JSON 列）
   - 与工具框架（Pydantic schema）天然一致
2. **契约即文档**：每个字段的语义写死在类型里，节点实现不需要猜
3. **与数据层解耦**：契约面向"业务语义"（region_code/metric/days），
   不暴露表结构——Repository 在节点内部把语义翻译成查询
4. **可序列化**：所有类型都能 JSON 化（存 task_steps / tool_calls / 报告），
   不含 ORM 对象、不含 datetime（统一 str 格式）——与 infra/cache.py 哲学一致
"""
from datetime import date, timedelta
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


# ==================== 意图与参数 ====================

class IntentType(str, Enum):
    """问数意图类型（路由的依据）。

    - REGION_METRICS   区域指标查询：某镇街某时段指标（线损率/回收率/供电量）
    - HIGH_LOSS_LINE   高损线路：线损率超阈值的线路排名
    - HIGH_LOSS_TAIQU  高损台区：线损率超阈值的台区排名
    - USER_USAGE       户级用电：某用户某时段用电量
    - TAIQU_RECONCILED 台区对账：Σ户表 vs 台区总表（线损验证）
    - UNKNOWN          无法识别 → 走 clarify 节点
    """

    REGION_METRICS = "region_metrics"
    HIGH_LOSS_LINE = "high_loss_line"
    HIGH_LOSS_TAIQU = "high_loss_taiqu"
    USER_USAGE = "user_usage"
    TAIQU_RECONCILED = "taiqu_reconciled"
    UNKNOWN = "unknown"


class IntentResult(BaseModel):
    """LLM 意图解析结果：意图 + 结构化参数（模板化查询的输入）。

    设计决策：LLM 只提取参数，不生成 SQL（模板化查询，规避 NL2SQL 风险）。
    所有字段可空——缺什么由 clarify 节点补齐，而不是直接失败。
    """

    intent: IntentType = IntentType.UNKNOWN
    # ---- 通用筛选参数 ----
    region_code: str | None = Field(
        default=None, description="镇街编码（DG001~DG032）；用户说「虎门镇」时由元数据反查"
    )
    region_name: str | None = Field(
        default=None, description="用户原始说的镇街名（反查 region_code 用）"
    )
    metric: str | None = Field(
        default=None, description="指标 code（line_loss_rate/collection_rate/...）；模板即口径"
    )
    # ---- 时间范围 ----
    start_date: str | None = Field(
        default=None, description="起始日期 YYYY-MM-DD；缺省由 clarify 补（默认近30天）"
    )
    end_date: str | None = Field(
        default=None, description="结束日期 YYYY-MM-DD；缺省由 clarify 补（默认今天）"
    )
    days: int | None = Field(
        default=None, ge=1, le=365, description="最近 N 天（用户说「近30天」时用，优先于 start/end）"
    )
    # ---- 阈值类参数 ----
    loss_threshold: float | None = Field(
        default=None, gt=0, lt=1, description="线损率阈值（比例小数，0.10=10%）；高损类意图用"
    )
    limit: int | None = Field(
        default=10, ge=1, le=100, description="返回条数上限（排名类意图默认10）"
    )
    # ---- 户级参数 ----
    user_id: str | None = Field(
        default=None, description="用户编号（用户说户号时）；USER_USAGE 意图用"
    )
    # ---- 对账参数 ----
    taiqu_code: str | None = Field(
        default=None, description="台区编号（用户说「台区」时）；TAIQU_RECONCILED 意图用"
    )
    # ---- 原始问题 ----
    raw_query: str = Field(default="", description="用户原始问题全文（透传，供报告引用）")

    @field_validator("start_date", "end_date")
    @classmethod
    def _validate_date(cls, v: str | None) -> str | None:
        """日期必须是 YYYY-MM-DD 或 None（不在这里做语义校验，只保证格式）。"""
        if v is None:
            return None
        try:
            date.fromisoformat(v)
        except ValueError as e:
            raise ValueError(f"日期格式应为 YYYY-MM-DD，收到: {v}") from e
        return v

    @property
    def resolved_dates(self) -> tuple[date, date] | None:
        """解析出实际日期区间（days 优先于 start/end），供 act 节点直接用。

        - days 给了 → (今天-days+1, 今天)
        - start/end 给了 → 直接用
        - 都没有 → None（需要 clarify 补）
        """
        if self.days:
            today = date.today()
            return today - timedelta(days=self.days - 1), today
        if self.start_date and self.end_date:
            return date.fromisoformat(self.start_date), date.fromisoformat(self.end_date)
        return None

    def missing_params(self) -> list[str]:
        """当前意图还缺哪些参数（clarify 节点用来决定追问什么）。

        返回缺失参数名列表；空列表 = 参数齐全可执行。
        """
        if self.intent == IntentType.UNKNOWN:
            return ["intent"]
        missing: list[str] = []
        if self.intent in (IntentType.REGION_METRICS, IntentType.HIGH_LOSS_LINE,
                           IntentType.HIGH_LOSS_TAIQU):
            if not self.region_code and not self.region_name:
                missing.append("region")
        if self.intent == IntentType.USER_USAGE and not self.user_id:
            missing.append("user_id")
        if self.intent == IntentType.TAIQU_RECONCILED and not self.taiqu_code:
            missing.append("taiqu_code")
        if self.resolved_dates is None:
            missing.append("date_range")
        return missing


# ==================== 查询请求 / 响应 ====================

class QueryRequest(BaseModel):
    """查询标准：act 节点翻译成 Repository 调用的输入。

    从 IntentResult 派生（模板 + 参数 → 具体查询），比 IntentResult 更"已定型"：
    - region_name 已反查成 region_code（或保持名称，由 Repository 处理）
    - days 已解析成 start/end
    - 每个请求对应一个明确的 Repository 方法
    """

    intent: IntentType
    region_code: str | None = None
    metric: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    loss_threshold: float | None = None
    limit: int = 10
    user_id: str | None = None
    taiqu_code: str | None = None


class QueryResult(BaseModel):
    """查询结果：act 节点产出，report 节点消费。

    统一结构（不按意图分多个模型）：
    - rows: 数据行（dict 列表，脱敏后）
    - columns: 列说明（表头 + 含义，report 节点据此生成表格/文案）
    - 附加信息（total/avg/max 等统计）放 meta，report 可引用
    """

    intent: IntentType
    rows: list[dict[str, Any]] = Field(default_factory=list)
    columns: list[dict[str, str]] = Field(
        default_factory=list, description="列元数据：[{name, label, unit}]"
    )
    meta: dict[str, Any] = Field(default_factory=dict, description="统计信息（total/avg/...）")
    truncated: bool = Field(default=False, description="是否因 limit 截断")
    error: str | None = Field(default=None, description="查询失败时的错误信息")

    @property
    def is_empty(self) -> bool:
        """空结果（无行）判定：report 节点据此决定"无数据"文案。"""
        return not self.rows and not self.error

    @property
    def display_rows(self) -> list[dict]:
        """给报告用的行：只保留 columns 里声明过的键（避免泄露多余字段）。"""
        if not self.columns:
            return self.rows
        keep = {c["name"] for c in self.columns}
        return [{k: v for k, v in r.items() if k in keep} for r in self.rows]


# ==================== 报告素材 ====================

class ReportSection(BaseModel):
    """报告段落：报告正文的一个语义块。"""

    title: str = ""
    kind: Literal["text", "table", "insight", "warning"] = "text"
    content: str = ""
    rows: list[dict[str, Any]] = Field(default_factory=list)  # kind=table 时的数据
    columns: list[dict[str, str]] = Field(default_factory=list)


class ReportInput(BaseModel):
    """报告素材：report 节点组装成最终报告的输入。

    从 QueryResult + 意图上下文组装，report 节点负责把它变成
    analysis_reports.content（结构化 JSON）和用户可见的文案。
    """

    query: str = Field(description="用户原始问题")
    intent: IntentType
    result: QueryResult
    sections: list[ReportSection] = Field(default_factory=list)
    generated_at: str = ""  # ISO 时间，report 节点填


# ==================== 工具调用契约（schemas/tools.py 的引用源） ====================

class ToolCallSpec(BaseModel):
    """Agent 发起的工具调用（与 models/task.py 的 ToolCall 表对应）。

    注意区分：
    - 本类是"调用意图"（节点 → 工具），存 task_steps.detail 或走 LLM function calling
    - models.ToolCall 是"调用记录"（审计），存 tool_calls 表
    - schemas/tools.py 是工具自身的输入/输出 schema（注册表用）
    """

    tool_name: str
    args: dict[str, Any] = Field(default_factory=dict)


# ==================== 状态聚合（LangGraph state 的语义层） ====================

class AgentTurn(BaseModel):
    """单轮分析任务的完整状态快照（orchestration/state.py 的语义载体）。

    图节点之间通过它传递：意图 → 查询 → 报告。
    存储：任务结束时可整体 model_dump() 存 task_steps.detail 做审计。
    """

    query: str = ""
    intent: IntentResult = Field(default_factory=IntentResult)
    request: QueryRequest | None = None
    result: QueryResult | None = None
    report: ReportInput | None = None
    clarification_needed: list[str] = Field(default_factory=list)
    error: str | None = None

    @property
    def is_ready(self) -> bool:
        """意图参数齐全、可执行（clarify 节点判据）。"""
        return not self.intent.missing_params()
