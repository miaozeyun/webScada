"""全局配置（pydantic-settings）：环境变量 > .env 文件 > 默认值。
参数口径与默认值见 docs/design/00-总览.md「统一口径速查」、根目录 .env.example 与
docs/implementation/server-closed-loop-plan.md（M8 服务端闭环新增段）。
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

# 弱 JWT 密钥黑名单：出现即拒绝启动（M8 fail-fast；DEBUG=True 本地开发豁免）
_WEAK_JWT_SECRETS = {"", "CHANGE_ME", "changeme", "change_me", "secret", "test"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ---- 应用 ----
    APP_NAME: str = "webScada"
    DEBUG: bool = False
    # 生产：postgresql+asyncpg://...（compose 注入）；测试：sqlite+aiosqlite:///:memory:
    DATABASE_URL: str = "postgresql+asyncpg://webscada:webscada123@postgres:5432/webscada"

    # ---- 鉴权 ----
    JWT_SECRET: str = "CHANGE_ME"          # 部署必改：lifespan 校验弱值/过短值直接拒绝启动
    JWT_EXPIRE_HOURS: int = 2              # 无状态 JWT；7x24 大屏走分享 token 不受此限
    LOGIN_LOCKOUT_ATTEMPTS: int = 5        # 登录失败锁定阈值（内存计数）
    LOGIN_LOCKOUT_SECONDS: int = 60

    # ---- 数据源凭证加密（G6）----
    # Fernet 密钥；丢失 = 已存凭证不可解，需在各数据源面板重填
    DATASOURCE_SECRET: str = ""

    # ---- 管理员初始化（存量置 admin；其余用户经 users API 管理）----
    ADMIN_USER: str = "admin"
    ADMIN_PASSWORD: str = "CHANGE_ME"

    # ---- doc 体积阈值（G21）----
    DOC_WARN_BYTES: int = 1024 * 1024      # ≤1MB 编辑器 UI 告警（前端消费）
    DOC_MAX_BYTES: int = 2 * 1024 * 1024   # >2MB 服务端 422 doc_too_large

    # ---- 图片上传（编辑器图片/轮播组件直传）----
    # 落盘目录（compose 以命名卷持久化；非 root 运行时目录须可写）
    UPLOAD_DIR: str = "uploads"
    UPLOAD_MAX_BYTES: int = 5 * 1024 * 1024

    # ---- 报警保留（G15；清理任务由 background_jobs 消费）----
    ALARM_RETENTION_DAYS: int = 30
    ALARM_MAX_ROWS_PER_PROJECT: int = 200_000

    # ---- 公开面限流（G16）----
    SHARE_MAX_WS_PER_TOKEN: int = 20
    JWT_WS_MAX_PER_USER_PROJECT: int = 10
    RATE_LIMIT_CONNECT_PER_MIN: int = 30   # 同 IP+token 拉取分享文档（rate_limit 中间件消费）
    WS_MAX_CONNECTIONS: int = 50           # 全实例 WS 连接上限（00-总览规模基线）
    COLLECTOR_MAX_VARIABLES_PER_PROJECT: int = 5000  # 单工程变量规模基线（同上）
    # ---- License（M8 阶段 2 骨架：未配置 KEY = 开源核心全功能；配置后按授权上限收敛） ----
    LICENSE_KEY: str = ""                    # 空=开源核心模式
    LICENSE_SIGNING_SECRET: str = ""         # 签发/校验共用（与产品侧配置一致；空=license 功能关闭）
    RATE_LIMIT_ENABLED: bool = True        # False 限流中间件整体旁路（仅压测用）
    REST_LOGIN_PER_MIN: int = 10           # 同 IP 登录尝试上限（rate_limit 中间件消费）
    REST_DATASOURCE_TEST_PER_MIN: int = 12  # 同 IP 数据源连通性测试上限
    REST_HISTORY_PER_MIN: int = 60         # 同 IP 历史查询上限（终审 #2：分享 token 免登录通道兜底）

    # ---- 工程 JSON 契约版本（G8 + M8 迁移通道，见契约文档 §7）----
    # 冻结规约：提版本前必须先落地「前端 migrateDoc() + 服务端 N-1 兼容窗口」三件套
    CURRENT_SCHEMA_VERSION: int = 1
    # 服务端 N-1 兼容窗口：接受 schemaVersion ∈ {CURRENT, CURRENT-1}（F 包消费）
    SCHEMA_COMPAT_WINDOW: int = 1         # 兼容窗口深度（当前=1，即 N-1）

    # ---- M8 服务端闭环：采集 ----
    COLLECTOR_RECONNECT_MIN_MS: int = 1000
    COLLECTOR_RECONNECT_MAX_MS: int = 30000
    COLLECTOR_CONNECT_TIMEOUT_MS: int = 5000
    # 值合帧窗口（03-接口清单 §3.4：100ms 合帧 + 变化抑制）
    WS_FRAME_COALESCE_MS: int = 100
    # stale 判定缺省：3 × 变量采集周期，最小 5s（02 §1.7）
    STALE_MIN_TIMEOUT_MS: int = 5000

    # ---- M8 服务端闭环：历史（historian，工作包 B）----
    HISTORY_RETENTION_DAYS: int = 30       # 清理任务消费（background_jobs）
    HISTORY_SAMPLE_INTERVAL_MS: int = 5000  # 定窗采样：每窗口落最后一个 good 值
    HISTORY_WRITE_BATCH: int = 500          # 缓冲批量入库阈值
    HISTORY_MAX_ROWS_PER_KEY: int = 50000   # 逐 key 查询硬上限：触顶自动提升 stepMs 聚合（终审 #2）

    # ---- M8 服务端闭环：报警通知（工作包 B notify）----
    NOTIFY_WEBHOOK_URL: str = ""            # 空=禁用 webhook 外发
    NOTIFY_WEBHOOK_TIMEOUT_MS: int = 5000
    NOTIFY_SMTP_HOST: str = ""              # 空=禁用邮件外发
    NOTIFY_SMTP_PORT: int = 465
    NOTIFY_SMTP_USERNAME: str = ""
    NOTIFY_SMTP_PASSWORD: str = ""
    NOTIFY_SMTP_FROM: str = ""
    NOTIFY_SMTP_USE_TLS: bool = True
    ALARM_NOTIFY_MIN_LEVEL: str = "warn"    # info/warn/critical：低于该级别不外发
    ALARM_NOTIFY_THROTTLE_SEC: int = 300    # 同规则外发节流

    # ---- M8 可观测 ----
    METRICS_TOKEN: str = ""                 # 空=/metrics 免鉴权（仅限内网/反代屏蔽时）

    # ---- CORS（收紧默认：同源部署不放开；跨域部署显式白名单，逗号分隔）----
    CORS_ORIGINS: str = ""

    def validate_runtime(self) -> None:
        """启动期安全自检（main.lifespan 调用，fail fast）。

        - JWT_SECRET 弱值/长度 < 32：拒绝启动（DEBUG=True 本地开发豁免）
        - DATASOURCE_SECRET 由 utils.encrypt.ensure_key 校验（lifespan 先行调用）
        """
        if self.DEBUG:
            return
        if self.JWT_SECRET in _WEAK_JWT_SECRETS or len(self.JWT_SECRET) < 32:
            raise RuntimeError(
                "JWT_SECRET 为弱值或长度不足 32 字符，拒绝启动。"
                "生成方式：python -c \"import secrets;print(secrets.token_hex(32))\""
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
