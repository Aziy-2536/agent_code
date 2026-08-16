"""LLM 网关：DeepSeek（OpenAI 兼容协议）统一调用入口。

设计决策（LLM 工程化的最小可用版）：
1. 协议层：Chat Completions + Function Calling（工具调用）。
   返回值统一为 ChatResult：要么 content（文本），要么 tool_calls（想调哪个工具）。
2. 工程层：超时、重试（指数退避）、Token 统计、成本估算。
3. 懒初始化：首次调用才建 client（Key 未填时 import 不报错）。
4. 配置全来自 settings（.env）：provider/model/api_key/base_url。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from openai import AsyncOpenAI
from openai.types.chat.chat_completion import ChatCompletion

from config.settings import get_settings

_client: AsyncOpenAI | None = None


@dataclass
class ChatResult:
    """一次 LLM 调用的统一结果。"""

    content: str = ""                                   # LLM 的文本回答
    tool_calls: list[dict[str, Any]] = field(default_factory=list)  # 想调用的工具（Function Calling）
    prompt_tokens: int = 0                              # 输入 token
    completion_tokens: int = 0                          # 输出 token
    latency_ms: float = 0.0                             # 耗时

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def estimated_cost_usd(self) -> float:
        """成本估算（DeepSeek 约 $0.27/M 输入, $1.1/M 输出，粗略）。"""
        return self.prompt_tokens * 0.27 / 1_000_000 + self.completion_tokens * 1.1 / 1_000_000


def get_llm_client() -> AsyncOpenAI:
    """懒初始化 OpenAI 兼容客户端（DeepSeek）。"""
    global _client
    if _client is None:
        s = get_settings()
        _client = AsyncOpenAI(
            api_key=s.llm_api_key,
            base_url=s.llm_base_url or None,   # 默认 OpenAI；DeepSeek 需填
            timeout=s.llm_timeout_seconds,
            max_retries=s.llm_max_retries,     # SDK 内置重试
        )
    return _client


async def chat(
    messages: list[dict[str, str]],
    *,
    tools: list[dict] | None = None,      # Function Calling 工具定义（tools/base.py 的 to_openai_function）
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> ChatResult:
    """统一 Chat 调用：返回文本 或 工具调用意图。

    Args:
        messages: OpenAI 消息数组 [{"role": "system"/"user"/"assistant"/"tool", "content": ...}]
        tools:    可用工具定义列表（LLM 可选择的工具）
    """
    s = get_settings()
    t0 = time.time()

    # 1. 组装请求
    kwargs: dict[str, Any] = {
        "model": s.llm_model,
        "messages": messages,
        "temperature": temperature if temperature is not None else s.llm_temperature,
    }
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    else:
        kwargs["max_tokens"] = s.llm_max_tokens
    if tools:
        kwargs["tools"] = tools

    # 2. 调用（SDK 内置重试）
    resp: ChatCompletion = await get_llm_client().chat.completions.create(**kwargs)

    # 3. 解析统一结果
    result = ChatResult(latency_ms=(time.time() - t0) * 1000)
    if resp.usage:
        result.prompt_tokens = resp.usage.prompt_tokens
        result.completion_tokens = resp.usage.completion_tokens

    choice = resp.choices[0] if resp.choices else None
    if choice and choice.message:
        if choice.message.content:
            result.content = choice.message.content
        if choice.message.tool_calls:
            # Function Calling：LLM 决定调用工具 → 结构化提取
            result.tool_calls = [
                {
                    "id": tc.id,
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,   # JSON 字符串
                }
                for tc in choice.message.tool_calls
            ]
    return result


async def simple_ask(question: str, system: str = "") -> str:
    """便捷方法：单轮问答（测试用）。"""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": question})
    result = await chat(messages)
    return result.content
