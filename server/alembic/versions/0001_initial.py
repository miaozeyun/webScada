"""M0 初始表：users / projects / share_links / alarm_records（G10 权威表结构）

 Revision ID: 0001
 Revises:
 Create Date: 2026-10-20
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 用户（单团队：无注册接口，管理员由 scripts/create_admin.py 初始化）
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("username", sa.Text(), nullable=False, unique=True),
        sa.Column("password_hash", sa.Text(), nullable=False),  # bcrypt
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # 工程：doc 为唯一事实来源（整存 JSONB），revision 为乐观锁（G2）
    op.create_table(
        "projects",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("doc", postgresql.JSONB(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_projects_owner", "projects", ["owner_id"])

    # 分享链接：快照方案（G5）——创建/refresh 时冻结脱敏后 doc；无 page_id（G10）
    op.create_table(
        "share_links",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token", sa.Text(), nullable=False, unique=True),
        sa.Column("doc_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_access_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    # token 列的 UNIQUE 约束已隐式建唯一索引，无需再建 idx_share_token（复查 minor 修复：防双倍索引维护）

    # 报警记录：运行数据（高频写入，不入 doc）；variable_key/value 为触发时快照
    op.create_table(
        "alarm_records",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rule_id", sa.Text(), nullable=False),          # 触发时快照，有意不做外键
        sa.Column("variable_key", sa.Text(), nullable=False),     # 触发时快照（变量删除后历史仍可读）
        sa.Column("level", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),             # 工程值字符串快照
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("triggered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recovered_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("level IN ('info','warn','critical')", name="ck_alarm_level"),
        sa.CheckConstraint("status IN ('active','recovered')", name="ck_alarm_status"),
    )
    op.create_index("idx_alarm_proj_triggered", "alarm_records", ["project_id", sa.text("triggered_at DESC")])


def downgrade() -> None:
    op.drop_table("alarm_records")
    op.drop_table("share_links")
    op.drop_table("projects")
    op.drop_table("users")
