"""性能索引：history_values.ts 前导 + alarm_records (project_id,status,rule_id)

- history_values.ts 单列索引：30 天保留清理的 cutoff 范围扫描与分批删除走索引，免全表扫大 DELETE
- alarm_records 复合索引：报警中心/统计按工程 + 状态（活跃/已恢复）+ 规则的高频过滤口径

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-27
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("idx_history_ts", "history_values", ["ts"])
    op.create_index("idx_alarm_proj_status_rule", "alarm_records", ["project_id", "status", "rule_id"])


def downgrade() -> None:
    op.drop_index("idx_alarm_proj_status_rule", table_name="alarm_records")
    op.drop_index("idx_history_ts", table_name="history_values")
