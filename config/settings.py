"""应用配置模型。

统一配置入口，基于 pydantic-settings：
- 配置来源优先级：环境变量 > .env 文件 > 代码默认值。
- 业务代码不直接读取 os.environ，统一通过 get_settings() 获取。
- 敏感字段（数据库密码、LLM Key、JWT 密钥）在日志输出前必须脱敏。
"""

# from __future__ import annotations：让类型注解延迟求值（字符串化），
#   这样 "Settings" 在类定义内部引用自身不报错，Python 3.10 的常见写法
from __future__ import annotations

# lru_cache：装饰器，给函数加"结果缓存"——同一参数只算一次，之后直接返回缓存
from functools import lru_cache

from pydantic_settings import BaseSettings 

# Literal：类型约束，让 app_env 只能是这三个值之一，别的值启动就报错
from typing import Literal

# Field：字段配置器，给字段加默认值、约束（ge=大于等于、gt=大于、le=小于等于）
# field_validator：字段校验器，在赋值后/前对值做处理（比如去斜杠）
from pydantic import Field, field_validator

# BaseSettings：pydantic-settings 的基类，让"类字段"自动绑定环境变量/.env
# SettingsConfigDict：配置类的配置项（读哪个文件、编码、大小写等）
from pydantic_settings import BaseSettings, SettingsConfigDict

EnvType = Literal["development", "test", "production"]

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",  # 指定 .env 文件路径，默认当前目录
        env_file_encoding="utf-8",  # 指定 .env 文件编码
        case_sensitive=False,  # 环境变量大小写不敏感
        extra="ignore",  # 忽略未声明的环境变量，避免报错
    )
    
    # ===============应用环境=======================
    app_name: str = "power-insight-agent"   # 服务名，FastAPI title 用
    app_env: EnvType = "development" # 环境：development/test/production，靠 Literal 约束
    app_debug: bool = True  # 是否调试模式，靠 app_env 自动设置
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_prefix: str = "/api/v1"  # API 前缀，FastAPI root_path 用
    log_level: str = "INFO"  # 日志级别，DEBUG/INFO/WARNING/ERROR/CRITICAL
    
     # ==================== MySQL ====================
    # 宿主机 3307 -> 容器 3306（docker-compose 避让映射，避开本机 MySQL）
    # DSN 格式：协议://用户:密码@主机:端口/库名，db/mysql.py 直接拿这个建连接池
    
    mysql_dsn: str #= "mysql+asyncmy://power:power@localhost:3307/power_insight"
    # MYSQL_POOL_SIZE: int = 5
    # MYSQL_MAX_OVERFLOW: int = 10
    mysql_echo: bool = False  # 是否打印 SQL 日志，True 会打印所有 SQL，生产环境慎用
    mysql_pool_size: int = Field(default=5, ge=1, description="连接池基础大小")#连接池必须大于等于1
    mysql_max_overflow: int = Field(default=10, ge=0, description="池满后可额外扩的临时连接数")#这个值必须大于等于0

    # ==================== Redis ====================
    # 宿主机 6380 -> 容器 6379（避让映射）
    
    redis_url: str #= "redis://localhost:6380/0"
    redis_key_prefix: str = Field(default="power", description="Redis key 前缀，避免冲突")
    
    # ==================== Milvus ====================
    milvus_uri: str #= "http://localhost:19530"   # gRPC 端点，db/milvus.py 用它连接
    milvus_db: str = "default"                   # 库名
    milvus_collection_prefix: str = "power_"     # 集合名前缀：power_metric_knowledge 之类

    # ==================== Kafka ====================
    # 二期才部署，先留配置位（Kafka topic 的设计在架构文档 §5）
    kafka_bootstrap_servers: str = "localhost:9092"
    kafka_client_id: str = "power-insight-agent"

    # ==================== LLM ====================
    # 兼容 OpenAI 协议的服务商（deepseek/openai/qwen），infra/llm_gateway.py 用
    llm_provider: str = "deepseek"               # 服务商名
    llm_model: str = "deepseek-chat"             # 模型名
    llm_api_key: str = ""                        # API Key（.env 里填，别写进代码）
    llm_base_url: str = ""                       # 自定义端点（deepseek 可不填）
    llm_temperature: float = Field(default=0.2, ge=0.0, le=2.0)  # 随机性，0~2 之间
    llm_max_tokens: int = Field(default=4096, ge=1)              # 单次最大输出 token
    llm_timeout_seconds: float = Field(default=60.0, gt=0)       # 请求超时，必须 > 0
    llm_max_retries: int = Field(default=3, ge=0)                # 失败重试次数

    # ==================== 安全 / JWT ====================
    # 认证模块用（二期）；生产必须换成随机强密钥
    jwt_secret: str = "change-me-in-production"  # JWT 签名密钥（.env 里覆盖）
    jwt_algorithm: str = "HS256"                 # 签名算法
    jwt_expire_minutes: int = Field(default=1440, gt=0)  # token 有效期：1440 分钟 = 24 小时

    # ==================== 租户与权限 ====================
    enable_multi_tenant: bool = False   # 一期单租户，二期开多租户
    default_tenant: str = "default"     # 默认租户 id

    # ==================== Agent 预算与超时 ====================
    # orchestration/context.py 的 CostBudget.from_settings() 消费这些值
    agent_max_steps: int = Field(default=20, ge=1)        # 单任务最大执行步骤
    agent_budget_tokens: int = Field(default=50_000, ge=1)  # 单任务 token 预算
    agent_budget_usd: float = Field(default=2.0, ge=0.0)  # 单任务成本上限（美元）
    agent_timeout_seconds: int = Field(default=300, gt=0) # 单任务超时（秒）
    agent_retry_max: int = Field(default=3, ge=0)         # 任务级重试次数

    # ==================== 幂等 / 限流 ====================
    idempotency_ttl_seconds: int = Field(default=86_400, gt=0)  # 幂等键保留 24h
    rate_limit_per_minute: int = Field(default=120, ge=1)       # 每分钟请求上限

    # ==================== 可观测性 ====================
    tracing_enabled: bool = False  # OpenTelemetry 链路追踪开关
    metrics_enabled: bool = True   # Prometheus 指标开关

    # ==================== 派生属性 ====================
    # 不是配置项，是"根据 app_env 算出来的结论"，方便代码里写 if settings.is_prod
    @property
    def is_dev(self) -> bool:
        return self.app_env == "development"

    @property
    def is_test(self) -> bool:
        return self.app_env == "test"

    @property
    def is_prod(self) -> bool:
        return self.app_env == "production"

    # field_validator：字段校验器
    # mode="before"：在赋值给字段之前先跑这个函数（还能顺便做清洗）
    # 作用：把 "https://api.deepseek.com/v1/" 末尾的 / 去掉，避免后面拼 URL 出现 //
    @field_validator("llm_base_url", mode="before")
    @classmethod
    def _strip_base_url(cls, v: object) -> str:
        """去掉 base_url 末尾斜杠，避免拼接 URL 时出现双斜杠。"""
        if isinstance(v, str):
            return v.rstrip("/")
        return ""

    # log_safe_summary：给启动日志用的"脱敏快照"
    # 为什么：直接 print(settings) 会把密码、API Key、JWT 密钥全打出来——日志泄露
    # 实现：model_dump() 转成 dict，遇到敏感字段就替换成 ***
    def log_safe_summary(self) -> dict:
        """返回脱敏后的配置摘要，用于启动日志；禁止直接打印整个 Settings。"""
        secrets = {"mysql_dsn", "llm_api_key", "jwt_secret"}
        return {
            key: ("***" if key in secrets else value)
            for key, value in self.model_dump().items()
        }


# lru_cache(maxsize=1)：只创建一个 Settings 实例并缓存
# 为什么：读 .env 是 IO 操作，不该每次 get_settings() 都读一遍
# 副作用：改 .env 后要重启进程才生效（lru_cache 记住了旧值）
@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """获取全局配置单例（进程内缓存，环境变量变更需重启生效）。"""
    return Settings()