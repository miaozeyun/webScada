"""refresh_tokens 表（阶段二 Task 3：操作员免重登）

- 库内只存 sha256(token)（CHAR(64) 唯一），明文不落库
- 轮换 = revoked_at 置位 + 新签；复用已吊销 token → 吊销该 user 全部未过期 refresh
- 全部状态落库（无进程内状态），与 models.RefreshToken 一致

 Revision ID: 0003
 Revises: 0002
 Create Date: 2026-10-23
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # id 由 Python 侧 uuid4 生成（G9 服务端生成，不依赖 PG gen_random_uuid）
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.CHAR(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("token_hash", name="uq_refresh_token_hash"),
    )
    op.create_index("idx_refresh_user", "refresh_tokens", ["user_id"])


def downgrade() -> None:
    op.drop_index("idx_refresh_user", table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
