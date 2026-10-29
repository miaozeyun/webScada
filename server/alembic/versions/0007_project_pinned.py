"""projects.pinned：工程台账置顶（列表按 pinned DESC, updated_at DESC 排序）

- 置顶是工程级属性（跨账号/设备一致），不放进 doc —— 不参与 revision 乐观锁，
  避免「置顶一下」把别人的画面改动顶成 409 冲突。
- 存量工程默认 false。

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-29
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("pinned", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    # 列表默认排序（pinned DESC, updated_at DESC）的覆盖索引
    op.create_index(
        "idx_projects_pinned_updated",
        "projects",
        ["pinned", sa.text("updated_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("idx_projects_pinned_updated", table_name="projects")
    op.drop_column("projects", "pinned")
