"""projects.readonly：三套旗舰演示工程只读（2026-10-29）

- 演示工程供客户在编辑器里体验拖拽/反控，但保存链路不落库（PUT 返回 403
  `PROJECT_READONLY`），避免演示画面被改脏；要定制请「复制工程」再编辑。
- 只读是工程级属性（同 pinned），不进 doc、不参与 revision 乐观锁。
- 存量回填：按演示案例生成时的固定工程名（`demoDoc()` 统一追加「（演示案例）」）。
  只回填三套旗舰案例；其余演示案例保持可编辑。

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-29
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 与 web/src/utils/demos/{wind,datacenter,line}.ts → demoDoc() 的命名同口径
_FLAGSHIP_DEMO_NAMES = (
    "海上风电集控（演示案例）",
    "数据中心基础设施（演示案例）",
    "智能制造产线（演示案例）",
)


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("readonly", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.execute(
        sa.text("UPDATE projects SET readonly = true WHERE name IN :names").bindparams(
            sa.bindparam("names", value=_FLAGSHIP_DEMO_NAMES, expanding=True)
        )
    )


def downgrade() -> None:
    op.drop_column("projects", "readonly")
