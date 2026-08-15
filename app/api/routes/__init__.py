"""API 路由包：把各路由模块汇总导出，main.py 从这里挂载。"""

# 导入两个路由模块（tasks / reports），并重新导出
# 这样 main.py 写 `from app.api.routes import reports, tasks` 即可
from app.api.routes import reports, tasks

# __all__：包级导出白名单
__all__ = ["tasks", "reports"]
