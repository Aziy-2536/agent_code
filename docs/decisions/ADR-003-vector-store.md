# ADR-003: 向量存储选型 Milvus（vs Qdrant / Chroma）

**Status**: Accepted
**Date**: 2026-08-15

## Context

系统需要为指标口径、政策文档、业务规则提供语义检索（Hybrid RAG）。
向量库选型需考虑：生产可演进性、数据规模、检索质量、部署复杂度。

## Decision

采用 **Milvus 2.4**（standalone 部署，docker-compose 一键起：
milvus + etcd + minio），理由：

1. **生产级**：支持十亿级向量、丰富的索引类型（IVF/HNSW）、标量过滤 + 向量混合检索，
   是国内工业界（尤其数据类场景）的主流选择。
2. **官方 GUI（Attu）**：可视化管理集合/索引/数据，开发体验好。
3. **生态**：pymilvus SDK 成熟，与 Hybrid RAG（BM25 + Dense + RRF）配套资料多。
4. **与项目叙事匹配**：电力数据平台用 Milvus 比 Chroma 更有说服力。

配套决策：
- 只存知识向量（指标口径、政策、规则、案例），**不存业务交易数据**（业务事实在 MySQL）。
- 访问通过 `db/milvus.py` 懒初始化单例；`rag/milvus_store.py` 之上保留
  `VectorStore` 抽象接口，Milvus 是其中一个实现，便于未来替换。

## Consequences

**正向**：
- 检索质量与扩展性满足第一版，且可平滑演进到集群模式。
- Attu + docker-compose 让本地开发与演示零门槛。

**负向**：
- 部署组件多（etcd + minio + milvus 三容器），资源占用高于单文件方案。
- 写入是近实时，查询前需要 flush/等待可见性（已通过 `flush()` 处理）。

## Alternatives Considered

1. **Qdrant**：Rust 实现、单容器简单、性能好；但国内电力/数据场景生态弱于 Milvus。
2. **Chroma**：嵌入式、零运维，适合原型；生产级能力和社区弱，放弃。
3. **Elasticsearch**：已有本地镜像，但向量检索能力与 Milvus 相比非专长，且重。
