"""share_links.refreshed_at（发布状态：快照最近刷新时间）

- 创建/refresh 时写入；与 projects.updated_at 比较即可判断「分享画面是否落后于工程」
- 回填历史行 = created_at（此前无刷新记录，按首次发布口径）

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-26
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("share_links", sa.Column("refreshed_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE share_links SET refreshed_at = created_at WHERE refreshed_at IS NULL")


def downgrade() -> None:
    op.drop_column("share_links", "refreshed_at")
