# PowerInsight Agent

面向电力营销与经营分析场景的多智能体数据分析平台。

当前仓库先建立工程骨架，后续按 `docs/development-order.md` 的顺序实现。

核心技术方向：FastAPI、LangGraph、MySQL、Redis、Milvus、Kafka、MCP、Agent Harness。

## 环境准备

项目使用 conda 虚拟环境 `langchain_demo`（Python 3.10）：

```bash
# 激活环境
conda activate langchain_demo

# 安装运行依赖（核心依赖已装齐后，按需补充）
pip install -r requirements.txt

# 可选分组（按需）
pip install -e ".[rag]"   # 向量化：sentence-transformers + torch（体积大）
pip install -e ".[data]"  # 文件适配：pandas + openpyxl
pip install -e ".[dev]"   # 开发测试：pytest / ruff / mypy

# 本地配置
cp .env.example .env
```
