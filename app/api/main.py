"""FastAPI 应用入口。

设计决策：
1. lifespan 管理资源生命周期：连接池懒初始化，关闭时统一释放。
2. 只做"组装"：挂路由、配前缀、健康检查——不承载业务逻辑。
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import reports, tasks
from config.settings import get_settings
from db import close_redis, dispose_engine

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动：连接均懒初始化（db/ 层首次调用才建），无需额外动作
    yield
    # 关闭：释放连接池
    await dispose_engine()
    await close_redis()


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
)

# 挂载路由（统一 API 前缀）
app.include_router(tasks.router, prefix=settings.api_prefix)
app.include_router(reports.router, prefix=settings.api_prefix)


@app.get("/health", tags=["health"], summary="健康检查")
async def health() -> dict:
    return {"status": "ok", "app": settings.app_name, "env": settings.app_env}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=settings.api_host, port=settings.api_port)
