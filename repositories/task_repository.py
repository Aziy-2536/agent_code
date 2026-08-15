"""任务数据访问：任务/步骤/工具调用/审批的读写。

设计决策：
1. Session 由外部注入（FastAPI 依赖注入或调用方），本类不创建 session、
   不管理事务生命周期——调用方决定 commit 时机。
2. 只暴露业务语义方法（create / get / update_status），不暴露 SQL。
3. 返回 ORM 对象，序列化交给上层（schemas 层）。
"""
# datetime：记录任务完成时间（终态时间戳）用
#   datetime.now() 生成"当前时刻"，存进 finished_at 字段
from datetime import datetime

# select：SQLAlchemy 的查询构造器
#   作用：用 Python 代码构造 SELECT 语句，代替手写 SQL 字符串
#   好处：类型安全、防注入（参数自动转义）
from sqlalchemy import select

# AsyncSession：异步会话类型
#   只用于"类型注解"（__init__ 的参数标注），运行时不会真的 import 一个实例
from sqlalchemy.ext.asyncio import AsyncSession

# 任务域模型：这个 Repository 操作的对象
#   AnalysisTask = 任务主表模型，TaskStep = 步骤，ToolCall = 工具调用，HumanApproval = 审批
from models import AnalysisTask, HumanApproval, TaskStep, ToolCall


class TaskRepository:
    """任务数据访问仓库：封装任务及其子记录的所有读写操作。"""

    def __init__(self, session: AsyncSession) -> None:
        # session 从外部注入（FastAPI 的 get_db 依赖 / Worker 传入）
        # 为什么不自己创建：事务边界由调用方管理，本类只负责"用 session 干活"
        self._session = session

    # ==================== 任务（主表） ====================

    async def create_task(
        self,
        question: str,                 # 用户问题（必填）
        task_type: str = "analysis",   # 任务类型，默认分析
        tenant_id: str = "default",    # 租户，默认 default
        trace_id: str = "",            # 链路追踪 id（可空）
    ) -> AnalysisTask:
        """创建任务并落库，返回带 task_id 的任务对象。"""
        # 第 1 步：在内存中构造 ORM 对象
        #   此时还没碰数据库——只是"准备好一条记录的数据"
        task = AnalysisTask(
            question=question,
            task_type=task_type,
            tenant_id=tenant_id,
            trace_id=trace_id,
            status="CREATED",          # 初始状态（状态机的起点）
        )
        # 第 2 步：add() 加入会话
        #   会话会跟踪这个对象，等 commit 时一起写库
        self._session.add(task)
        # 第 3 步：commit() 提交事务
        #   真正执行 INSERT 语句；此时数据库才生成 task_id（UUID）和 created_at
        await self._session.commit()
        # 第 4 步：refresh() 刷新对象
        #   把数据库生成的值（task_id / created_at）读回内存对象
        #   不 refresh 的话，task.task_id 还是空的，调用方拿不到
        await self._session.refresh(task)
        return task

    async def get_by_task_id(self, task_id: str) -> AnalysisTask | None:
        """按对外 UUID 查任务，查不到返回 None。"""
        # 构造查询：SELECT * FROM analysis_tasks WHERE task_id = :id
        result = await self._session.execute(
            select(AnalysisTask).where(AnalysisTask.task_id == task_id)
        )
        # scalar_one_or_none() 的行为：
        #   0 条结果 → None（查不到）
        #   1 条结果 → 返回该对象
        #   多条结果 → 抛异常（task_id 有唯一索引，正常不会发生；多条=数据异常，宁可报错）
        return result.scalar_one_or_none()

    async def update_status(
        self,
        task_id: str,
        status: str,                       # 新状态
        error_message: str | None = None,  # 失败原因（可选）
    ) -> AnalysisTask | None:
        """更新任务状态；终态（SUCCEEDED/FAILED）时记录完成时间。"""
        # 先按 id 查出任务对象（复用上面的查询方法）
        task = await self.get_by_task_id(task_id)
        # 查不到 → 返回 None，让调用方决定怎么处理（比如报 404）
        if task is None:
            return None
        # 直接改 ORM 对象的属性——SQLAlchemy 会跟踪"脏数据"，
        # commit 时自动生成 UPDATE 语句（只更新改过的列）
        task.status = status
        if error_message is not None:
            # 有错误信息才覆盖（None 表示"没错误，别动旧值"）
            task.error_message = error_message
        # 终态（成功/失败）时记录完成时间：统计任务耗时用
        if status in ("SUCCEEDED", "FAILED"):
            task.finished_at = datetime.now()
        await self._session.commit()
        return task

    async def list_recent(self, limit: int = 20) -> list[AnalysisTask]:
        """最近任务列表（按 id 倒序 = 最新在前）。"""
        # order_by(id.desc())：id 倒序（自增 id 越大 = 越新）
        # limit(limit)：只取前 N 条
        result = await self._session.execute(
            select(AnalysisTask).order_by(AnalysisTask.id.desc()).limit(limit)
        )
        # scalars()：从结果集取"实体流"（每行一个 AnalysisTask）
        # .all()：转成 Python 列表
        return list(result.scalars().all())

    # ==================== 步骤（LangGraph 节点执行记录） ====================

    async def add_step(
        self,
        task_id: str,
        node_name: str,                # 节点名：route / plan / act / observe / review / report
        detail: dict | None = None,    # 节点中间结果（JSON）
    ) -> TaskStep:
        """记录一个执行步骤（对应 LangGraph 节点的一次执行）。"""
        step = TaskStep(task_id=task_id, node_name=node_name, detail=detail)
        self._session.add(step)          # 加入会话
        await self._session.commit()     # 写库
        return step

    async def list_steps(self, task_id: str) -> list[TaskStep]:
        """按任务查执行步骤，按 id 升序 = 执行顺序。"""
        result = await self._session.execute(
            select(TaskStep)
            .where(TaskStep.task_id == task_id)
            .order_by(TaskStep.id)       # 升序：先执行的在前面
        )
        return list(result.scalars().all())

    # ==================== 工具调用（审计数据源） ====================

    async def add_tool_call(
        self,
        task_id: str,
        tool_name: str,                  # 工具名：sql_query / metric_calculator ...
        input: dict,                     # 入参（SQL 语句、指标 code 等）
        output: dict | None = None,      # 结果摘要
        status: str = "SUCCEEDED",       # SUCCEEDED / FAILED / REJECTED
        error: str | None = None,        # 失败原因
        duration_ms: int = 0,            # 耗时（毫秒）
    ) -> ToolCall:
        """记录一次工具调用（入参/出参/耗时）——审计与评测的关键数据。"""
        call = ToolCall(
            task_id=task_id, tool_name=tool_name, input=input,
            output=output, status=status, error=error, duration_ms=duration_ms,
        )
        self._session.add(call)
        await self._session.commit()
        return call

    async def list_tool_calls(self, task_id: str) -> list[ToolCall]:
        """按任务查工具调用记录，按执行顺序。"""
        result = await self._session.execute(
            select(ToolCall)
            .where(ToolCall.task_id == task_id)
            .order_by(ToolCall.id)
        )
        return list(result.scalars().all())

    # ==================== 人工审批 ====================

    async def add_approval(self, task_id: str, tool_name: str, params: dict) -> HumanApproval:
        """创建一条审批请求（状态默认 PENDING）。"""
        # params：待审批的动作参数（比如"创建工单"的工单内容）
        approval = HumanApproval(task_id=task_id, tool_name=tool_name, params=params)
        self._session.add(approval)
        await self._session.commit()
        return approval

    async def get_approval(self, approval_id: int) -> HumanApproval | None:
        """按主键查审批记录。"""
        # session.get(模型, 主键)：SQLAlchemy 的"按主键快速查询"
        #   比 select().where() 更简洁，且命中缓存
        return await self._session.get(HumanApproval, approval_id)
