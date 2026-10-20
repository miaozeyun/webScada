"""ORM 模型：与 alembic 0001 迁移一致（G10 权威表结构）。

可移植性说明：doc/doc_snapshot 用 JSON 变体（PostgreSQL 上为 JSONB，测试 SQLite 上为 JSON）；
UUID 主键由 Python 侧生成（服务端生成，G9），不依赖 PG 的 gen_random_uuid()。
"""
import uuid
from datetime import datetime

from sqlalchemy import JSON, BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Integer, Text, Uuid, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

# PostgreSQL 用 JSONB（可索引/高效）；其他方言（测试用 SQLite）回落普通 JSON
JSONVariant = JSON().with_variant(JSONB(), "postgresql")


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)  # bcrypt
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

    # token 的 UNIQUE 约束已隐式建唯一索引，不再重复建 idx_share_token（与 alembic 0001 一致）


class AlarmRecord(Base):
    """报警记录：运行数据（高频写入，不入 doc）。variable_key/value 为触发时快照。"""

    __tablename__ = "alarm_records"
    __table_args__ = (
        CheckConstraint("level IN ('info','warn','critical')", name="ck_alarm_level"),
        CheckConstraint("status IN ('active','recovered')", name="ck_alarm_status"),
        # 复合索引：按工程查报警时按触发时间倒序（与 alembic 0001 一致）
        Index("idx_alarm_proj_triggered", "project_id", text("triggered_at DESC")),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
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
    recovered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
