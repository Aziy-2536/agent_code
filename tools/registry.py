"""ToolRegistry：工具注册 / 查询 / 按意图过滤 / 转 LLM schema。

设计决策：
- 工具与意图解耦：filter_by_intent 按工具声明的 intents 过滤，
  意图为空的工具视为通用工具总是返回——新增意图不动工具注册表。
"""
from __future__ import annotations

import logging
from typing import Type

from tools.base import ToolBase

logger = logging.getLogger(__name__)


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolBase] = {}

    def register(self, tool: ToolBase) -> None:
        if tool.name in self._tools:
            logger.warning("tool %s already registered, overriding", tool.name)
        self._tools[tool.name] = tool

    def register_cls(self, tool_cls: Type[ToolBase], **init_kwargs) -> None:
        self.register(tool_cls(**init_kwargs))

    def get(self, name: str) -> ToolBase | None:
        return self._tools.get(name)

    def all(self) -> list[ToolBase]:
        return list(self._tools.values())

    def filter_by_intent(self, intent: str | None = None) -> list[ToolBase]:
        """按意图过滤；intents 为空的工具视为通用工具，总是返回。"""
        if not intent:
            return self.all()
        return [t for t in self._tools.values() if not t.intents or intent in t.intents]

    def to_openai_functions(self, intent: str | None = None) -> list[dict]:
        return [type(t).to_openai_function() for t in self.filter_by_intent(intent)]


# 全局工具注册表单例：应用启动时注册全部工具
registry = ToolRegistry()
