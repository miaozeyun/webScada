"""ORM 模型：与 alembic 0001/0002/0003 迁移一致（G10 权威表结构）。

可移植性说明：doc/doc_snapshot/detail 用 JSON 变体（PostgreSQL 上为 JSONB，测试 SQLite 上为 JSON）；
UUID 主键由 Python 侧生成（服务端生成，G9），不依赖 PG 的 gen_random_uuid()；
BIGSERIAL 自增主键在 SQLite 测试环境回落 INTEGER。

M8 服务端闭环新增（docs/implementation/server-closed-loop-plan.md 为实施契约）：
- users.role（admin/operator/viewer，存量迁移置 admin）
- alarm_records 单行状态机列（acked_at/acked_by/acked_note/cleared_at，status 改为
  triggered/acked/cleared；recovered_at 由 cleared_at 取代并已在 0002 迁移中删除）
- audit_logs（RBAC 审计，工作包 C 消费）
- history_values（服务端 historian 入库，工作包 B 消费；按 ts 分区可后置）
"""
import uuid
from datetime import datetime

from sqlalchemy import (
    CHAR,
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

# PostgreSQL 用 JSONB（可索引/高效）；其他方言（测试用 SQLite）回落普通 JSON
JSONVariant = JSON().with_variant(JSONB(), "postgresql")


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("role IN ('admin','operator','viewer')", name="ck_user_role"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)  # bcrypt
    # M8 RBAC：admin=用户管理/审计/全部工程；operator=工程读写/反控/报警确认；viewer=只读
    role: Mapped[str] = mapped_column(Text, nullable=False, server_default="admin")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # ProjectDoc 全量（含 Fernet 加密后的数据源凭证）；schemaVersion 校验入口
    doc: Mapped[dict] = mapped_column(JSONVariant, nullable=False)
    # 乐观锁版本号（G2）：PUT 携带 baseRevision，不符 409；doc 内不冗余
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    owner: Mapped[User] = relationship(lazy="joined")

    __table_args__ = (Index("idx_projects_owner", "owner_id"),)


class ShareLink(Base):
    """分享链接（快照方案 G5）：创建/refresh 时冻结脱敏后 doc；无 page_id（G10）。"""

    __tablename__ = "share_links"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    token: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    doc_snapshot: Mapped[dict] = mapped_column(JSONVariant, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)   # NULL=永不过期
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)   # 非 NULL=已撤销
    last_access_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    # 快照最近刷新时间（创建/refresh 写入）：与 projects.updated_at 比较判断「分享画面是否落后」
    refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # token 的 UNIQUE 约束已隐式建唯一索引，不再重复建 idx_share_token（与 alembic 0001 一致）


class AlarmRecord(Base):
    """报警记录：服务端报警引擎 7x24 写入（运行数据不入 doc）。

    单行状态机（M8 修复「恢复另插新行」缺陷）：triggered → (acked) → cleared。
    - 触发：插入 status='triggered'；同规则未恢复期间重复触发不插新行
    - 确认：triggered→acked（acked_at/acked_by/acked_note）；cleared 后补确认只填 ack 字段不改 status
    - 恢复：triggered/acked → cleared（cleared_at）；已填 ack 字段保留
    variable_key/value 为触发时快照（变量删除后历史仍可读，工程值口径）。
    """

    __tablename__ = "alarm_records"
    __table_args__ = (
        CheckConstraint("level IN ('info','warn','critical')", name="ck_alarm_level"),
        CheckConstraint("status IN ('triggered','acked','cleared')", name="ck_alarm_status"),
        # 复合索引：按工程查报警时按触发时间倒序（与 alembic 0001/0002 一致）
        Index("idx_alarm_proj_triggered", "project_id", text("triggered_at DESC")),
    )

    # 自增主键：PostgreSQL 用 BIGINT（与 alembic 一致）；SQLite 测试环境
    # 的 autoincrement 仅对 INTEGER PRIMARY KEY 生效，故回落 INTEGER（JSONVariant 同款可移植做法）
    id: Mapped[int] = mapped_column(Integer().with_variant(BigInteger(), "postgresql"), primary_key=True, autoincrement=True)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    rule_id: Mapped[str] = mapped_column(Text, nullable=False)
    variable_key: Mapped[str] = mapped_column(Text, nullable=False)
    level: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # ---- M8 状态机扩展 ----
    acked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acked_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    acked_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    cleared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditLog(Base):
    """审计日志（M8 RBAC 配套）：只追加不更新；冗余 username 快照防用户删除后不可读。

    action 枚举（工作包 C audit_service 埋点）：login / write_var / alarm_ack / alarm_clear /
    project_save / share_create / share_revoke / user_mgmt / datasource_test。
    """

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("idx_audit_created", text("created_at DESC")),
        Index("idx_audit_user", "user_id"),
        Index("idx_audit_action", "action"),
    )

    id: Mapped[int] = mapped_column(Integer().with_variant(BigInteger(), "postgresql"), primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    username: Mapped[str | None] = mapped_column(Text, nullable=True)   # 触发时快照
    action: Mapped[str] = mapped_column(Text, nullable=False)
    target_type: Mapped[str | None] = mapped_column(Text, nullable=True)   # project/share/user/alarm/variable
    target_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    detail: Mapped[dict | None] = mapped_column(JSONVariant, nullable=True)
    ip: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class HistoryValue(Base):
    """历史值（M8 服务端 historian）：换算后工程值定窗采样入库；按 ts 分区可后置。

    - variable_key 为触发时快照口径（变量删除后区间查询仍可读），与 alarm_records 同 rationale
    - value 为工程值数值（服务端换算流水执行后：bitIndex → scale/offset → precision）
    - 清理任务消费 HISTORY_RETENTION_DAYS（background_jobs 启动 + 每 24h 各一次）
    """

    __tablename__ = "history_values"
    __table_args__ = (
        Index("idx_history_proj_var_ts", "project_id", "variable_key", text("ts DESC")),
    )

    id: Mapped[int] = mapped_column(Integer().with_variant(BigInteger(), "postgresql"), primary_key=True, autoincrement=True)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    variable_key: Mapped[str] = mapped_column(Text, nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)


class RefreshToken(Base):
    """refresh token（阶段二 Task 3：操作员免重登）。

    - 库内只存 sha256(token) 十六进制（CHAR(64) 唯一）；明文仅在 login/refresh 响应返回一次
    - 轮换语义：/auth/refresh 成功 = 旧记录 revoked_at 置位 + 签发新对（一次性消费，
      条件 UPDATE 防并发双花）
    - 复用检测：已吊销 token 再次出现 = 疑似泄露重放 → 吊销该 user 全部未过期 refresh
    - 状态全部落库，无进程内状态（与 jti 黑名单的内存语义刻意不同：重启不丢、可审计）
    """

    __tablename__ = "refresh_tokens"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_refresh_token_hash"),
        Index("idx_refresh_user", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)      # 7 天
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # 非 NULL=已吊销/已轮换
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class NotificationOutbox(Base):
    """通知补发队列（阶段三：断网/渠道故障期间的通知不丢）。

    - 触发/恢复外发先走即时发送；失败渠道落一行 pending，由后台 worker 指数退避重试
    - channel/payload 为发送时快照：工程后续改渠道/删规则不影响在途补发
    - status: pending → sending → sent | dead（重试超上限）；sent/dead 保留供排查
    """

    __tablename__ = "notification_outbox"
    __table_args__ = (
        CheckConstraint("status IN ('pending','sending','sent','dead')", name="ck_outbox_status"),
        Index("idx_outbox_due", "status", "next_at"),
        Index("idx_outbox_project", "project_id"),
    )

    id: Mapped[int] = mapped_column(Integer().with_variant(BigInteger(), "postgresql"), primary_key=True, autoincrement=True)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    alarm_id: Mapped[int | None] = mapped_column(
        Integer().with_variant(BigInteger(), "postgresql"), nullable=True
    )
    event: Mapped[str] = mapped_column(Text, nullable=False)          # trigger | recovery
    channel_kind: Mapped[str] = mapped_column(Text, nullable=False)
    channel_json: Mapped[dict] = mapped_column(JSONVariant, nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSONVariant, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
