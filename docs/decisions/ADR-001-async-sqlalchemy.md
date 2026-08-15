# ADR-001: 数据访问采用 SQLAlchemy 2.0 异步模式 + asyncmy 驱动

**Status**: Accepted
**Date**: 2026-08-15

## Context

系统入口是 FastAPI（异步框架），Agent Worker 也是异步任务。若使用同步驱动
（PyMySQL），数据库调用会阻塞事件循环，高并发下请求排队、吞吐下降。
需要选择：异步驱动选哪个、ORM 层如何组织。

## Decision

1. **ORM 用 SQLAlchemy 2.0 的 async 模式**（`create_async_engine` +
   `async_sessionmaker` + `AsyncSession`），同步/异步代码同构，模型定义可复用。
2. **驱动用 asyncmy**（`mysql+asyncmy://`），Cython 实现、性能优于纯 Python 的
   aiomysql，且本环境已具备。
3. **连接管理**：Engine 管连接池（进程级单例、懒初始化），Session 管工作单元
   （由 FastAPI 依赖注入提供，调用方决定事务边界）；`expire_on_commit=False`
   避免异步下 commit 后隐式 IO 抛错。
4. Kafka Worker 的批量处理如需要同步 session，可另建同步 engine，两套共用
   `models/` 定义。

## Consequences

**正向**：
- 请求处理全程非阻塞，事件循环不被数据库 IO 卡住。
- 模型层（`models/`）与连接层（`db/`）分离，测试可 mock Repository。

**负向**：
- asyncmy 依赖编译产物，部署环境需匹配 Python 版本。
- 异步调试比同步略复杂（需要 `asyncio.run` / `AsyncSession` 上下文）。

## Alternatives Considered

1. **PyMySQL 同步 + 线程池**：实现简单，但每个请求占一个线程，FastAPI 异步优势尽失。
2. **aiomysql**：纯 Python、兼容好，但性能低于 asyncmy，且生态成熟度相当。
3. **asyncmy + 裸 asyncio**：无 ORM 层，SQL 散落业务代码，放弃。
