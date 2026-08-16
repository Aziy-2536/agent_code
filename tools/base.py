"""工具协议和通用工具元数据。

设计决策（工具框架的最小可用版）：
1. 工具 = 一个 Pydantic 输入模型（schema）+ 一个 async 执行函数（run）。
   输入模型即"契约"：LLM Function Calling 的 JSON schema 由它生成，
   调用方校验入参也靠它——一个定义两处用。
2. 工具输出统一为 dict（可 JSON 序列化），不返回 ORM 对象。
3. 工具无状态：依赖（Session/Repository）在 run 时由调用方注入，
   不在注册时绑定——便于测试和复用。
4. 安全（P0）：工具白名单注册制，LLM 只能调用注册过的工具；
   工具名 → 执行函数 的映射是唯一入口，不存在"任意工具名反射调用"。
"""
from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic import BaseModel


class ToolError(Exception):
    """工具执行失败（业务错误，非编程错误）。"""


@dataclass
class Tool:
    """一个已注册工具的完整描述。

    - name / description：LLM Function Calling 用（让 LLM 知道"什么时候用这个工具"）
    - input_model：Pydantic 输入模型（生成 JSON schema + 校验入参）
    - run：async 执行函数，签名为 (input_model) -> dict
    """

    name: str
    description: str
    input_model: type[BaseModel]
    run: Callable[..., Any]

    def to_openai_function(self) -> dict:
        """转成 OpenAI Function Calling 的 tools 定义（给 infra/llm_gateway）。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_model.model_json_schema(),
            },
        }

    async def execute(self, args: dict[str, Any]) -> dict:
        """校验入参并执行，返回 dict 结果。

        - 入参校验失败抛 ToolError（带具体字段错误）
        - 执行函数抛异常时向上抛（由 harness 记录到 tool_calls 表）
        """
        try:
            validated = self.input_model.model_validate(args)
        except Exception as e:
            raise ToolError(f"工具 {self.name} 入参校验失败: {e}") from e
        # 执行函数可能是 async 或 sync（统一 await）
        result = self.run(validated)
        if inspect.isawaitable(result):
            result = await result
        return result
