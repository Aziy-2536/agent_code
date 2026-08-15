"""API 接入层：应用实例从 app.api.main 导入。"""

# 把 FastAPI 应用实例提升到包级别：
#   from app.api import app 就能拿到应用（uvicorn 启动 / 测试用）
from app.api.main import app

# 包级导出白名单
__all__ = ["app"]
