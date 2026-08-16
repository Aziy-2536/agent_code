"""元数据知识库检索 Repository（问数 Agent 的前提底座）。

设计决策：
1. 检索场景：找表（该查哪些表）→ 找字段（字段含义）→ 找取值（识别用户提到的值）。
2. 返回结构化 dict，供 LLM 理解上下文（注入 prompt）或代码直接使用。
3. 结构化检索（精确匹配）+ 后续二期语义检索（向量化到 Milvus）。
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import MetaField, MetaTable, MetaValue


class MetaStoreRepository:
    """元数据知识库：表/字段/取值检索。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ---------- 表信息 ----------
    async def list_tables(self, layer: str | None = None) -> list[dict]:
        """列出全部表（可选按层级过滤：维度/汇总）。"""
        stmt = select(MetaTable).order_by(MetaTable.table_name)
        if layer:
            stmt = stmt.where(MetaTable.table_layer == layer)
        result = await self._session.execute(stmt)
        return [
            {
                "table_name": t.table_name,
                "table_desc": t.table_desc,
                "table_layer": t.table_layer,
                "primary_key": t.primary_key,
                "related_tables": t.related_tables,
            }
            for t in result.scalars().all()
        ]

    async def get_table(self, table_name: str) -> dict | None:
        """按表名查表信息。"""
        result = await self._session.execute(
            select(MetaTable).where(MetaTable.table_name == table_name)
        )
        t = result.scalar_one_or_none()
        if t is None:
            return None
        return {
            "table_name": t.table_name,
            "table_desc": t.table_desc,
            "table_layer": t.table_layer,
            "primary_key": t.primary_key,
            "related_tables": t.related_tables,
        }

    # ---------- 字段信息 ----------
    async def list_fields(self, table_name: str | None = None) -> list[dict]:
        """查字段（可按表过滤）——LLM 理解字段含义用。"""
        stmt = select(MetaField).order_by(MetaField.table_name, MetaField.id)
        if table_name:
            stmt = stmt.where(MetaField.table_name == table_name)
        result = await self._session.execute(stmt)
        return [
            {
                "table_name": f.table_name,
                "field_name": f.field_name,
                "field_desc": f.field_desc,
                "role": f.role,
                "is_filter": f.is_filter,
            }
            for f in result.scalars().all()
        ]

    # ---------- 取值字典 ----------
    async def resolve_value(self, field_name: str, value: str) -> str | None:
        """按显示值反查编码（"虎门镇"→"DG012"）；找不到返回 None。"""
        result = await self._session.execute(
            select(MetaValue)
            .where(MetaValue.field_name == field_name, MetaValue.value == value)
        )
        row = result.scalar_one_or_none()
        return row.code if row else None

    async def list_values(self, field_name: str) -> list[dict]:
        """查某字段的取值映射（注入 prompt 让 LLM 认识枚举值）。"""
        result = await self._session.execute(
            select(MetaValue).where(MetaValue.field_name == field_name)
        )
        return [{"code": v.code, "value": v.value} for v in result.scalars().all()]

    # ---------- 上下文组装（问数节点用） ----------
    async def build_context(self) -> str:
        """把元数据组装成一段文本，注入 LLM system prompt（先理解再动手）。"""
        tables = await self.list_tables()
        fields = await self.list_fields()
        lines = ["【可查询的数据表】"]
        for t in tables:
            lines.append(f"- {t['table_name']}（{t['table_desc']}，主键 {t['primary_key']}）")
        lines.append("\n【关键字段】")
        for f in fields:
            lines.append(f"- {f['table_name']}.{f['field_name']}：{f['field_desc']}")
        return "\n".join(lines)
