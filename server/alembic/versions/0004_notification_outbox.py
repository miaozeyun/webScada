"""notification_outbox 表（阶段三：通知失败补发，断网期间通知不丢）

- 触发/恢复即时发送失败的渠道落 pending 行，后台 worker 指数退避重试
- channel_json/payload_json 为发送时快照，后续改渠道/删规则不影响在途补发
- 上限后置 dead（死信），保留供排障

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-25
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "notification_outbox",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("alarm_id", sa.BigInteger(), nullable=True),
        sa.Column("event", sa.Text(), nullable=False),
        sa.Column("channel_kind", sa.Text(), nullable=False),
        sa.Column("channel_json", postgresql.JSONB(), nullable=False),
        sa.Column("payload_json", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('pending','sending','sent','dead')", name="ck_outbox_status"),
    )
    op.create_index("idx_outbox_due", "notification_outbox", ["status", "next_at"])
    op.create_index("idx_outbox_project", "notification_outbox", ["project_id"])


def downgrade() -> None:
    op.drop_index("idx_outbox_project", table_name="notification_outbox")
    op.drop_index("idx_outbox_due", table_name="notification_outbox")
    op.drop_table("notification_outbox")
