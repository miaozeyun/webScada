"""全局配置（pydantic-settings）：环境变量 > .env 文件 > 默认值。
参数口径与默认值见 docs/design/00-总览.md「统一口径速查」与 .env.example。
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ---- 应用 ----
    APP_NAME: str = "webScada"
    DEBUG: bool = False
    # 生产：postgresql+asyncpg://...（compose 注入）；测试：sqlite+aiosqlite:///:memory:
    DATABASE_URL: str = "postgresql+asyncpg://webscada:webscada123@postgres:5432/webscada"

    # ---- 鉴权 ----
    JWT_SECRET: str = "CHANGE_ME"          # 部署必改（compose 层强制要求非空）
    JWT_EXPIRE_HOURS: int = 2              # 无状态 JWT；7x24 大屏走分享 token 不受此限
    LOGIN_LOCKOUT_ATTEMPTS: int = 5        # 登录失败锁定阈值（内存计数）
    LOGIN_LOCKOUT_SECONDS: int = 60

    # ---- 数据源凭证加密（G6）----
    # Fernet 密钥；丢失 = 已存凭证不可解，需在各数据源面板重填
    DATASOURCE_SECRET: str = ""

    # ---- 管理员初始化（单团队，无注册接口）----
    ADMIN_USER: str = "admin"
    ADMIN_PASSWORD: str = "CHANGE_ME"

    # ---- doc 体积阈值（G21）----
    DOC_WARN_BYTES: int = 1024 * 1024      # ≤1MB 编辑器 UI 告警（前端消费）
    DOC_MAX_BYTES: int = 2 * 1024 * 1024   # >2MB 服务端 422 doc_too_large

    # ---- 报警保留（G15；清理任务 M5 生效，参数先入基线）----
    ALARM_RETENTION_DAYS: int = 30
    ALARM_MAX_ROWS_PER_PROJECT: int = 200_000

    # ---- 公开面限流（G16；WS 限流 M4/M6 生效）----
    SHARE_MAX_WS_PER_TOKEN: int = 20
    JWT_WS_MAX_PER_USER_PROJECT: int = 10
    RATE_LIMIT_CONNECT_PER_MIN: int = 30
    WS_MAX_CONNECTIONS: int = 50           # 全实例 WS 连接上限（00-总览规模基线）

    # ---- 工程 JSON 契约版本（G8：迁移唯一实现点在前端 migrateDoc()）----
    CURRENT_SCHEMA_VERSION: int = 1


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
