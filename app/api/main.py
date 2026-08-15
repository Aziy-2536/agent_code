"""FastAPI 应用入口。

设计决策：
1. lifespan 管理资源生命周期：连接池懒初始化，关闭时统一释放。
2. 只做"组装"：挂路由、配前缀、静态页面、健康检查——不承载业务逻辑。
3. 静态目录 app/static 提供前端测试页面（/ 直接访问）。
"""
# asynccontextmanager：把普通函数变成"异步上下文管理器"（lifespan 需要）
from contextlib import asynccontextmanager

# Path：处理文件路径（定位 static 目录）
from pathlib import Path

# FastAPI：应用类
# StaticFiles：静态文件挂载（把目录里的 HTML/CSS/JS 直接提供给浏览器）
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

# 两个路由模块：任务 + 报告
from app.api.routes import reports, tasks

# get_settings：读取配置（服务名、API 前缀等）
from config.settings import get_settings

# 关闭时的资源释放：MySQL 连接池 / Redis 连接
from db import close_redis, dispose_engine

# 启动时读一次配置，全局使用
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动阶段（yield 之前）：连接均懒初始化（db/ 层首次调用才建），无需动作
    yield
    # 关闭阶段（yield 之后）：进程退出前释放资源
    #   优雅关闭：先告诉数据库"我要走了"，断开所有连接
    #   不释放的话：进程退出时连接会挂着，数据库侧积累僵尸连接
    await dispose_engine()   # 释放 MySQL 连接池
    await close_redis()      # 关闭 Redis 连接


# 创建 FastAPI 实例：
#   title    = 服务名（OpenAPI 文档标题）
#   version  = 版本号
#   lifespan = 生命周期管理（启动/关闭钩子）
app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
)

# 挂载 API 路由：统一前缀 /api/v1
#   /api/v1/tasks、/api/v1/reports
app.include_router(tasks.router, prefix=settings.api_prefix)
app.include_router(reports.router, prefix=settings.api_prefix)


@app.get("/health", tags=["health"], summary="健康检查")
async def health() -> dict:
    """健康检查：返回服务状态（部署探活用）。"""
    return {"status": "ok", "app": settings.app_name, "env": settings.app_env}


# 静态页面必须最后挂载（关键坑！）：
#   mount("/") 会匹配"所有路径"——如果放在前面，
#   会拦截 /api/v1/* 和 /health，让它们全部 404
#   放在最后：先匹配具体路由，剩下的才走静态文件
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
if STATIC_DIR.exists():
    # html=True：访问 / 时自动返回 index.html
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")


if __name__ == "__main__":
    # 直接运行时的启动方式：python app/api/main.py
    import uvicorn

    # host/port 从配置读（.env 里 API_HOST / API_PORT）
    uvicorn.run(app, host=settings.api_host, port=settings.api_port)
