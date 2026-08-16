"""工具注册表：工具白名单的唯一入口。

设计决策：
1. 注册制：工具显式注册后才能被 Agent 调用（P0 安全）。
2. 单例：进程内一个注册表，避免多处注册导致不一致。
3. 提供三种视图：
   - get(name) → 单个工具（执行用）
   - openai_functions() → 全部工具的 Function Calling 定义（给 LLM）
   - names() → 工具名列表（调试/日志用）
"""
from __future__ import annotations

from tools.base import Tool


class ToolRegistry:
    """进程级工具注册表（单例）。"""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """注册一个工具；同名覆盖（幂等，便于测试重注册）。"""
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        """按名取工具；未注册返回 None。"""
        return self._tools.get(name)

    def names(self) -> list[str]:
        """全部工具名。"""
        return list(self._tools.keys())

    def openai_functions(self) -> list[dict]:
        """全部工具的 Function Calling 定义（给 infra/llm_gateway.chat 的 tools 参数）。"""
        return [t.to_openai_function() for t in self._tools.values()]

    def __len__(self) -> int:
        return len(self._tools)


# 进程级单例
registry = ToolRegistry()


def get_registry() -> ToolRegistry:
    """获取全局注册表单例。"""
    return registry
