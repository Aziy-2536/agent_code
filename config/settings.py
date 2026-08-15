"""应用配置模型。

统一配置入口，基于 pydantic-settings：
- 配置来源优先级：环境变量 > .env 文件 > 代码默认值。
- 业务代码不直接读取 os.environ，统一通过 get_settings() 获取。
- 敏感字段（数据库密码、LLM Key、JWT 密钥）在日志输出前必须脱敏。
"""

from __future__ import annotations
from functools import lru_cache
from typing import Literal
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

EnvType = Literal["development", "test", "production"]


class Settings(BaseSettings):
    """PowerInsight Agent 全局配置。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---------- 应用基础 ----------
    app_name: str = "power-insight-agent"
    app_env: EnvType = "development"
    app_debug: bool = False
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_prefix: str = "/api/v1"
    log_level: str = "INFO"

    # ---------- MySQL ----------
    # 宿主机 3307 -> 容器 3306（docker-compose 避让映射）
    # 异步驱动 asyncmy，供 SQLAlchemy 2.0 async 模式使用
    mysql_dsn: str = "mysql+asyncmy://power:power@localhost:3307/power_insight"
    mysql_pool_size: int = Field(default=5, ge=1)
    mysql_max_overflow: int = Field(default=10, ge=0)
    mysql_echo: bool = False

    # ---------- Redis ----------
    # 宿主机 6380 -> 容器 6379（docker-compose 避让映射）
    redis_url: str = "redis://localhost:6380/0"
    redis_key_prefix: str = "power"

    # ---------- Milvus ----------
    milvus_uri: str = "http://localhost:19530"
    milvus_db: str = "default"
    milvus_collection_prefix: str = "power_"

    # ---------- Kafka ----------
    kafka_bootstrap_servers: str = "localhost:9092"
    kafka_client_id: str = "power-insight-agent"

    # ---------- LLM ----------
    llm_provider: str = "deepseek"
    llm_model: str = "deepseek-chat"
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    llm_max_tokens: int = Field(default=4096, ge=1)
    llm_timeout_seconds: float = Field(default=60.0, gt=0)
    llm_max_retries: int = Field(default=3, ge=0)

    # ---------- 安全 / JWT ----------
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = Field(default=1440, gt=0)

    # ---------- 租户与权限 ----------
    enable_multi_tenant: bool = False
    default_tenant: str = "default"

    # ---------- Agent 预算与超时 ----------
    agent_max_steps: int = Field(default=20, ge=1)
    agent_budget_tokens: int = Field(default=50_000, ge=1)
    agent_budget_usd: float = Field(default=2.0, ge=0.0)
    agent_timeout_seconds: int = Field(default=300, gt=0)
    agent_retry_max: int = Field(default=3, ge=0)

    # ---------- 幂等 / 限流 ----------
    idempotency_ttl_seconds: int = Field(default=86_400, gt=0)
    rate_limit_per_minute: int = Field(default=120, ge=1)

    # ---------- 可观测性 ----------
    tracing_enabled: bool = False
    metrics_enabled: bool = True

    # ---------- 派生属性 ----------
    @property
    def is_dev(self) -> bool:
        return self.app_env == "development"

    @property
    def is_test(self) -> bool:
        return self.app_env == "test"

    @property
    def is_prod(self) -> bool:
        return self.app_env == "production"

    @field_validator("llm_base_url", mode="before")
    @classmethod
    def _strip_base_url(cls, v: object) -> str:
        """去掉 base_url 末尾斜杠，避免拼接 URL 时出现双斜杠。"""
        if isinstance(v, str):
            return v.rstrip("/")
        return ""

    def log_safe_summary(self) -> dict:
        """返回脱敏后的配置摘要，用于启动日志；禁止直接打印整个 Settings。"""
        secrets = {"mysql_dsn", "llm_api_key", "jwt_secret"}
        return {
            key: ("***" if key in secrets else value)
            for key, value in self.model_dump().items()
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """获取全局配置单例（进程内缓存，环境变量变更需重启生效）。"""
    return Settings()
