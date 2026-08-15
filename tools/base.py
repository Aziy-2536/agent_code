"""Tool 系统基础抽象（Schema-Over-Magic 模式，参考工业实践）。

核心设计：
1. 每个工具用 Pydantic 显式声明 input_schema / output_schema，
   反对反射魔法——这是"Schema-Over-Magic"原则。
2. `_run(ctx, inp)` 子类实现真实逻辑；`run()` 统一入口负责
   输入校验、耗时统计、异常兜底（失败包装为 ToolOutput）。
3. `to_openai_function()` 把 schema 转成 Function Calling 格式，
   工具定义与 LLM 协议解耦——换协议不改工具。
4. 相比参考项目，增加两个与 Harness 衔接的元数据字段：
   - `requires_approval`：高风险工具标记，ApprovalManager 据此挂起任务
   - `permission`：read / write / admin，PolicyGuard 据此做权限检查
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any, ClassVar, Generic, Type, TypeVar

from pydantic import BaseModel, ValidationError

from orchestration.context import AgentContext

InputT = TypeVar("InputT", bound=BaseModel)
OutputT = TypeVar("OutputT", bound=BaseModel)


class ToolInput(BaseModel):
    """所有工具输入 schema 的基类（约定空）。"""


class ToolOutput(BaseModel):
    """所有工具输出 schema 的基类：统一 success / error / latency / metadata。"""

    success: bool = True
    error: str | None = None
    latency_ms: float = 0.0
    metadata: dict[str, Any] = {}


class ToolBase(ABC, Generic[InputT, OutputT]):
    """工具基类。子类需声明 name / description / input_schema / output_schema。"""

    name: ClassVar[str]
    description: ClassVar[str]
    input_schema: ClassVar[Type[ToolInput]]
    output_schema: ClassVar[Type[ToolOutput]]

    # 工具适用意图（空元组 = 通用工具，任何意图都可用）
    intents: ClassVar[tuple[str, ...]] = ()

    # 与 Harness 衔接的安全元数据
    requires_approval: ClassVar[bool] = False  # True 时触发人工审批
    permission: ClassVar[str] = "read"  # read / write / admin

    @abstractmethod
    def _run(self, ctx: AgentContext, inp: InputT) -> OutputT:
        """子类实现的真实逻辑。ctx 为当前任务的 AgentContext。"""

    def run(self, ctx: AgentContext, inp_data: dict[str, Any] | InputT) -> OutputT:
        """统一执行入口：校验输入、计时、异常兜底。"""
        t0 = time.time()

        # 1. 输入校验：dict 自动转 schema；校验失败直接抛，
        #    让上层 Agent 看到 schema 错误并重新组织参数
        try:
            inp = (
                inp_data
                if isinstance(inp_data, self.input_schema)
                else self.input_schema(**inp_data)
            )
        except ValidationError:
            raise

        # 2. 执行真实逻辑
        try:
            out = self._run(ctx, inp)
            try:
                out.latency_ms = (time.time() - t0) * 1000
            except Exception:
                pass
            return out
        except Exception as exc:  # noqa: BLE001
            # 3. 异常兜底：包装为失败 ToolOutput，不向上抛（工具失败不等于任务失败）
            return self.output_schema(  # type: ignore[call-arg]
                success=False,
                error=f"{type(exc).__name__}: {exc}",
                latency_ms=(time.time() - t0) * 1000,
            )

    # ---------- LLM Function Calling schema ----------
    @classmethod
    def to_openai_function(cls) -> dict[str, Any]:
        """转 OpenAI Function Calling 兼容描述（deepseek 等兼容协议同样适用）。"""
        return {
            "type": "function",
            "function": {
                "name": cls.name,
                "description": cls.description,
                "parameters": cls.input_schema.model_json_schema(),
            },
        }
