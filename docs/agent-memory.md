# Agent 记忆架构：三层记忆 / 自学习规则 / 作用域隔离

> 本文档沉淀记忆层设计决策：短期/中期/长期记忆的实现、semantic+feedback+Milvus
> 自学习闭环、记忆作用域与权限隔离。与 `agent-knowledge.md`（知识层）、
> `architecture.md`（总体架构）配套阅读。

---

## 1. 核心结论（先记住这三条）

1. **分层管生命周期，MySQL 管真相，Redis/向量库管加速**——存储介质不等于真相源。
2. **三层记忆**：短期 = 上下文（不落库）；中期 = MySQL 真相 + Redis 热层；
   长期 = MySQL 真相 + 向量索引（召回加速）。
3. **记忆不是"跟用户"或"系统通用"的二选一**，而是按内容通用性分四层作用域：
   会话 / 用户 / 组织 / 系统。检索注入前必须过作用域过滤（权限 P0 底线）。

---

## 2. 三层记忆总览

```
┌─ 上下文层（短期，可丢）────────────────────────┐
│   LLM 上下文窗口 / Agent state                 │
│   —— 只放"本次任务需要的"，超窗摘要降级          │
├─ 缓存层（热，可丢）───────────────────────────┤
│   Redis：渲染结果、热记忆、最近会话、用户特征副本 │
│   —— 挂了只变慢，真相在下面                    │
├─ 索引层（派生，可重建）────────────────────────┤
│   Milvus（语义召回）+ ES（全文/精确取值）        │
│   —— 只存"检索入口 + 回指 id"，可整体重建       │
├─ 事实层（真相，不可丢）────────────────────────┘
│   MySQL：业务数据 / 元数据 / 记忆事实 / 用户特征
│   —— 唯一权威，权限/统计/审计/一致性都在这里
```

| 记忆层 | 实现位置 | 存储 | 真相源 |
|---|---|---|---|
| 短期（working） | orchestration/state.py + memory/working.py | 进程内 + LangGraph state | 不落库 |
| 中期（session） | memory/retriever.py + infra/cache.py | Redis 热层 + MySQL 表 | MySQL |
| 长期（long-term） | memory/episodic.py + semantic.py + consolidator.py | MySQL 表 + Milvus 索引 | MySQL |

---

## 3. 短期记忆（working）：不落库，随任务生灭

```python
# orchestration/state.py（LangGraph State 字段）
class AgentState(TypedDict):
    query: str                    # 本次用户问题
    intent: IntentResult          # 解析出的意图 + 参数
    working: WorkingMemory        # 中间产物：候选表/字段/上下文片段
    messages: list[Message]       # 本次任务内 LLM 往返（含 tool 结果）
    result: QueryResult           # 最终查询结果
```

- `memory/working.py` 只做一件事：管理"本次任务内"的上下文窗口，
  超 token 预算时把最早的消息摘要压缩（滚动窗口降级），任务结束即销毁。
- **不落库**：落库的是归档后的 episodic。

---

## 4. 中期记忆（session）：MySQL 真相 + Redis 热层

```python
# memory/retriever.py —— 读侧
async def load_recent_context(conversation_id: str, limit: int = 10) -> list[Message]:
    """最近 N 轮消息：Redis 命中直接返回，未命中回 MySQL 再回填 Redis。"""
    cached = await cache_get("session", conversation_id)      # Redis 热层
    if cached:
        return cached
    messages = await _load_from_mysql(conversation_id, limit) # 真相源
    await cache_set("session", conversation_id, value=messages, ttl=600)
    return messages

# memory/retriever.py —— 写侧
async def append_message(conversation_id: str, msg: Message) -> None:
    """写 MySQL（真相）→ 失效 Redis 热 key（下次重建）。"""
    await _save_to_mysql(conversation_id, msg)
    await cache_del("session", conversation_id)
```

要点：
- Redis 只缓存"渲染好的最近 N 轮"，**每次新消息写入后删除缓存 key**（复用 cache_del）。
- Redis 挂了 → 直读 MySQL，功能不丢只慢。与 `infra/cache.py` 降级哲学一致。

---

## 5. 长期记忆（long-term）：MySQL 真相 + Milvus 索引

### 5.1 两类的存储差异

| | EpisodicMemory（案例） | SemanticMemory（规则） |
|---|---|---|
| 本质 | 历史任务成败，可丢的检索素材 | 业务口径/模板，可治理的资产 |
| 存储 | MySQL 真相（可备份导出） | **必须 MySQL 真相**（置信度/统计/审计） |
| 向量库 | 索引（query/summary 向量） | 索引（content 向量） |
| 丢失后果 | 少些参考，不致命 | 规则无法治理 → 黑盒搜索箱 |

**教程存向量库，是因为它们的长期记忆 = 可丢的检索素材（RAG 语境）。**
而 SemanticMemory 带 `confidence/usage_count/success_count/last_used_at`，
这些字段只有关系型存储用得动：淘汰（DELETE where confidence<0.7）、
审计、人工修订、按用户隔离——向量库都做不到。

### 5.2 长期记忆各模块职责

```python
# memory/episodic.py —— 案例记忆
async def archive_task(episodic: EpisodicMemory) -> None:
    """任务结束归档：写 MySQL（真相）+ 触发向量化进 Milvus（二期）。"""

# memory/semantic.py —— 规则记忆
async def upsert_rule(rule: SemanticMemory) -> None:
    """写/更规则到 MySQL；向量化进 Milvus（二期）。"""

# memory/consolidator.py —— 沉淀门禁（写侧核心）
async def consolidate(task_result, messages) -> None:
    """任务结束后调用：
    1. 成败 → archive_task 写 episodic（无条件）
    2. 同模式出现 N 次 → upsert_rule 写 semantic（质量门禁）
    3. 置信度 < 0.7 的规则 → 标记降级/淘汰
    """

# memory/feedback.py —— 使用统计（长期记忆的"治理"）
async def on_rule_used(rule_id: str, success: bool) -> None:
    """usage_count+1；success 则 success_count+1，否则置信度下调。"""

# memory/retriever.py —— 长期检索（任务开始时调用）
async def recall_long_term(query: str, top_k: int = 3) -> RecalledMemory:
    """一期：MySQL LIKE；二期：Milvus 向量召回 top-k
    → 回 MySQL 取完整行 + 作用域/权限过滤 + usage_count+1"""
```

### 5.3 铁律

Milvus 只存"query/summary/content 的向量点 + 回指 id"；
完整内容、置信度、统计、权限全在 MySQL。

---

## 6. semantic + feedback + Milvus 自学习闭环（核心机制）

把长期记忆从"存起来"变成"活起来"：规则不是写死的，是"长"出来的。

```
第一次（冷启动）：走全流程 → 沉淀成规则
第二次（命中）：Milvus 召回规则 → 直接跳到执行
第 N 次（反馈）：规则被反复验证 → 置信度上升
规则错（反馈）：置信度下调 → 低于阈值淘汰 → 自我修正
```

### 6.1 规则诞生（consolidator 沉淀）

```
同模式出现 N 次（如 3 次"线损率按月对比"）
  → 提炼规则：
     rule_type = "query_pattern"
     content   = {"template": "line_loss_trend",
                  "params": {"metric": "line_loss_rate"},
                  "filters": ["region_code", "month"]}
     confidence = 0.6（初始宁低勿高）
  → 写 MySQL（真相）→ 向量化进 Milvus（索引）
```

**关键：content 是结构化模板引用（模板 ID），不是自由文本**
——规则召回后直接可执行，不用 LLM 再翻译。

### 6.2 规则召回（retriever，任务开始）

```
query = "虎门镇线损率环比"
  → Milvus 向量召回 top-k（content 向量相似）
  → 回 MySQL 取完整行
  → 作用域/权限过滤（见第 8 节）
  → usage_count + 1
  → 按置信度分档注入 prompt：
      confidence ≥ 0.8  → 直接建议"按此模板执行"
      0.7 ≤ c < 0.8     → 建议但标注"可参考"
      c < 0.7            → 只做提示，不主动推荐
```

### 6.3 规则进化（feedback 闭环）

```
规则被使用后：
  成功 → success_count+1 → 置信度上调
  失败 → 置信度下调
  c < 0.7 → 降级为"仅提示"
  c < 0.3 或连续失败 N 次 → 废弃/删除
```

置信度更新算法（指数平滑，容忍偶发失败）：

```
新置信度 = 旧置信度 × α + 本次信号 × (1 - α)
α = 0.8（历史权重）；信号 = 1.0（成功）/ 0.0（失败）

示例：c=0.75 连续 3 次失败：
  第 1 次：0.75×0.8 + 0×0.2 = 0.60 → 降级"仅提示"
  第 2 次：0.60×0.8 = 0.48 → 标记待复核
  第 3 次：0.48×0.8 = 0.38 → 废弃
```

### 6.4 反馈信号三源加权

| 信号源 | 怎么拿到 | 强度 |
|---|---|---|
| 执行结果 | 查询成功、返回行数合理 | 弱（语法成功≠语义正确） |
| **用户行为** | 追问/纠错/采纳 | **强**（真实意图） |
| LLM 自评 | 结果与问题一致性打分 | 中（有偏差但成本低） |

```
signal = 0.3×执行成功 + 0.4×用户反馈 + 0.3×LLM 自评
```

### 6.5 三个坑（实现前要知道）

1. **语义召回假阳性**：召回"看起来像"但不该用的规则 → 置信度过滤 + 权限过滤
   必须在召回后、注入前。
2. **规则爆炸**：每次任务都沉淀会指数增长 → consolidator 合并去重
   （同 template + 同 params 只留一条）+ 定期压缩归档低频旧规则。
3. **置信度被"用得多"绑架**：usage_count 高 ≠ 置信度高 → 置信度只看
   成功比例 + 平滑历史，不看绝对次数。

---

## 7. 用户特征（user profiles）：与记忆并列的独立存储

用户特征分三类：

| 类型 | 例子 | 存储 |
|---|---|---|
| 静态身份 | 用户 ID、组织、权限等级 | MySQL（强隔离，user_id 维度） |
| 动态偏好 | 常用指标、关心的镇街、输出格式 | MySQL 真相 + Redis 热缓存 |
| 行为统计 | 意图分布、活跃度、失败率 | MySQL 派生，可延迟刷新 |

**向量库角色为零**——用户特征是"精确查询"问题（`WHERE user_id = ?`），
不是"相似召回"问题。教程存向量库是因为单用户 demo 无隔离需求；
多用户平台必须 MySQL 强隔离（评审 P0：权限不能串）。

```python
# MySQL（真相，agent 库）
user_profiles
  user_id (PK) / org_code / permission_level
  preferred_metrics JSON / preferred_regions JSON / style JSON
  updated_at

# Redis（热层，TTL 可丢）
user:profile:{user_id}   # 渲染后的偏好 JSON，任务开始一次读入
user:recent:{user_id}    # 最近 N 轮消息热窗口

# 读写时机
任务开始：读 profile（Redis 命中→用；未命中→MySQL→回填 Redis）→ 偏好注入 prompt
任务结束：若暴露新偏好 → 更新 user_profiles（MySQL）→ 删 Redis key（cache_del）
```

**偏好更新同样走"LLM 提议 + 程序落地"**：LLM 从对话识别偏好，
输出结构化建议（`set_preference(user_id, key, value)`），程序校验白名单后写库。

---

## 8. 记忆作用域与权限隔离（P0 底线）

### 8.1 可见性四层

```
会话级（per-conversation）── 一次对话内的短期上下文
用户级（per-user）───────── 特征、偏好、私有案例
组织级（per-org）────────── 业务口径、模板、团队经验
系统级（global）────────── 通用业务规则、取值字典
```

**判定标准一句话：这条记忆删掉 user 维度后还对吗？**
口径/取值映射删掉用户还对 → 组织/系统级共享；
偏好/习惯删掉用户没意义 → 用户级隔离。

### 8.2 四类记忆的作用域

| 记忆 | 作用域 |
|---|---|
| 短期（上下文） | 会话级（一次性） |
| 中期（会话消息） | 用户级（挂 conversation.user_id） |
| 用户特征 | **用户级**（绝不共享） |
| episodic 案例 | 默认用户级，可经审批升格组织级 |
| semantic 规则 | 客观规则（口径/模板/映射）→ 组织/系统级共享；主观偏好 → 用户级（走 user_profiles） |

### 8.3 检索时强制过滤

```
召回规则（Milvus 或 LIKE）：
  → 先按作用域过滤：rule.visible_to IN (global, org:{用户组织}, user:{用户id})
  → 再按置信度过滤
  → 最后才注入 prompt

用户特征 / 私有案例：WHERE user_id = 当前用户  # 硬隔离
```

**铁律：召回结果在注入 prompt 之前必须完成作用域过滤**
——否则用户 A 问问题注入了用户 B 的私有偏好/案例 = 数据串扰（P0）。

### 8.4 置信度的作用域语义

```
组织级规则：置信度跨用户聚合（群体智慧：越多人验证越可信）
用户级规则：置信度只看本用户（不受他人使用影响）
```

---

## 9. 现有模型需要补的字段（实现前必改）

看 `models/memory.py` 现状：

- ✅ `Conversation` 有 `user_id`
- ⚠️ `EpisodicMemory`：只有 `task_id`，**无 user_id / scope**
- ⚠️ `SemanticMemory`：**无 user_id / org_code / visible_to / scope**

必须补（趁早，迁移成本随数据量上升）：

```python
class EpisodicMemory:   # 需新增
    user_id: str          # 归属用户
    scope: str            # "user" / "org" / "global"（默认 user，审批升格）

class SemanticMemory:    # 需新增
    user_id: str | None   # None = 组织/系统级
    org_code: str | None
    scope: str            # org / global（主观偏好走 user_profiles，不放这）
```

---

## 10. 任务生命周期中的记忆读写（串起来）

```
任务开始：
  ① load_recent_context()      → 中期（Redis→MySQL）→ 拼进上下文（短期）
  ② recall_long_term()         → 长期（LIKE/Milvus top-k）→ 相似案例/规则进上下文
  ③ 读 user profile（Redis→MySQL）→ 偏好注入
  ④ 组装 WorkingMemory → LangGraph 图执行
任务执行中：
  ⑤ state["messages"] 积累 LLM 往返（短期，进程内）
  ⑥ append_message()           → 中期落库（MySQL + Redis 失效）
任务结束：
  ⑦ consolidate()              → 长期沉淀（episodic 必写 / semantic 门禁）
  ⑧ feedback 统计反馈闭环
  ⑨ 可选：更新 user profile（LLM 提议 + 程序落地）
```

---

## 11. 实现顺序建议

1. **第一步（现在）**：working.py + retriever.py 会话部分——MySQL 真相 + Redis 热层
   跑通中短期，不碰向量库。
2. **第二步**：episodic.py + consolidator.py——任务结束归档 + 质量门禁（先 LIKE）。
3. **第三步（二期）**：semantic.py + feedback.py 全量 + Milvus 向量召回替换 LIKE。

记忆不阻塞主链路（schemas → 工具 → harness → orchestration 时接入记忆，
作为 context 的提供方）。但**作用域字段（第 9 节）应尽早补**，属 P0 前置。

---

## 12. 与知识层的关系（两种知识的治理差异）

| | 元数据（数仓知识） | 规则记忆（Agent 经验） |
|---|---|---|
| 治理路线 | 保守：LLM 提议 + 人审批 | 进化：自动沉淀 + 反馈修正 |
| 原因 | 错不起（写错别名 → 静默错数据） | 错了能改（置信度可下调淘汰） |
| 写入 | 低频、diff 驱动、需审批 | 高频、任务结束自动、质量门禁 |
| 共享 | 系统级（取值字典、口径） | 分作用域（见第 8 节） |

两条路线的差异，本质是"错不起的知识" vs "错了能改的经验"。
