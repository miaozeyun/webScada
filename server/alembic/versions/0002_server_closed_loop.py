"""M8 服务端闭环：RBAC / 审计 / 历史 / 报警单行状态机（契约 §3）

- users 增 role 列（admin/operator/viewer；存量置 admin）
- alarm_records 状态机：active/recovered → triggered/acked/cleared；
  增 acked_at/acked_by/acked_note/cleared_at；删 recovered_at（数据并入 cleared_at）
  ——修复「恢复另插新行」缺陷，改为单行状态机 triggered→(acked)→cleared
- 新表 audit_logs（C 包审计埋点）
- 新表 history_values（B 包 historian 入库；按 ts 分区可后置）

 Revision ID: 0002
 Revises: 0001
 Create Date: 2026-10-20
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---- 1. users.role（存量置 admin：与「全员管理员」现状等价，之后经 users API 收敛）----
    op.add_column("users", sa.Column("role", sa.Text(), nullable=False, server_default="admin"))
    op.create_check_constraint(
        "ck_user_role", "users", "role IN ('admin','operator','viewer')"
    )

    # ---- 2. alarm_records 单行状态机 ----
    op.add_column("alarm_records", sa.Column("acked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("alarm_records", sa.Column("acked_by", sa.Uuid(), nullable=True))
    op.add_column("alarm_records", sa.Column("acked_note", sa.Text(), nullable=True))
    op.add_column("alarm_records", sa.Column("cleared_at", sa.DateTime(timezone=True), nullable=True))
    # 旧约束先摘（active/recovered 值即将改写，保留会违反新值域）
    op.drop_constraint("ck_alarm_status", "alarm_records", type_="check")
    # 数据迁移：active→triggered；recovered→cleared（cleared_at 并入 recovered_at）
    op.execute("UPDATE alarm_records SET status = 'triggered' WHERE status = 'active'")
    op.execute(
        "UPDATE alarm_records SET status = 'cleared', cleared_at = recovered_at "
        "WHERE status = 'recovered'"
    )
    op.create_check_constraint(
        "ck_alarm_status", "alarm_records", "status IN ('triggered','acked','cleared')"
    )
    op.create_foreign_key(
        "fk_alarm_records_acked_by_users", "alarm_records", "users", ["acked_by"], ["id"],
        ondelete="SET NULL",
    )
    op.drop_column("alarm_records", "recovered_at")

    # ---- 3. audit_logs（只追加；user_id/username 快照防用户删除后不可读）----
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("username", sa.Text(), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("target_type", sa.Text(), nullable=True),
        sa.Column("target_id", sa.Text(), nullable=True),
        sa.Column("detail", postgresql.JSONB(), nullable=True),
        sa.Column("ip", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_audit_created", "audit_logs", [sa.text("created_at DESC")])
    op.create_index("idx_audit_user", "audit_logs", ["user_id"])
    op.create_index("idx_audit_action", "audit_logs", ["action"])

    # ---- 4. history_values（高频写入；按 ts 分区可后置，先以复合索引支撑区间查询）----
    op.create_table(
        "history_values",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("variable_key", sa.Text(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
    )
    op.create_index(
        "idx_history_proj_var_ts", "history_values", ["project_id", "variable_key", sa.text("ts DESC")]
    )


def downgrade() -> None:
    # ---- 4. history_values ----
    op.drop_index("idx_history_proj_var_ts", table_name="history_values")
    op.drop_table("history_values")

    # ---- 3. audit_logs ----
    op.drop_index("idx_audit_action", table_name="audit_logs")
    op.drop_index("idx_audit_user", table_name="audit_logs")
    op.drop_index("idx_audit_created", table_name="audit_logs")
    op.drop_table("audit_logs")

    # ---- 2. alarm_records 回退 active/recovered 口径 ----
    op.add_column("alarm_records", sa.Column("recovered_at", sa.DateTime(timezone=True), nullable=True))
    op.drop_constraint("fk_alarm_records_acked_by_users", "alarm_records", type_="foreignkey")
    op.drop_constraint("ck_alarm_status", "alarm_records", type_="check")
    # 状态回填：cleared→recovered（recovered_at=cleared_at）；triggered/acked→active（未恢复）
    op.execute(
        "UPDATE alarm_records SET status = 'recovered', recovered_at = cleared_at "
        "WHERE status = 'cleared'"
    )
    op.execute("UPDATE alarm_records SET status = 'active' WHERE status IN ('triggered','acked')")
    op.create_check_constraint(
        "ck_alarm_status", "alarm_records", "status IN ('active','recovered')"
    )
    op.drop_column("alarm_records", "cleared_at")
    op.drop_column("alarm_records", "acked_note")
    op.drop_column("alarm_records", "acked_by")
    op.drop_column("alarm_records", "acked_at")

    # ---- 1. users.role ----
    op.drop_constraint("ck_user_role", "users", type_="check")
    op.drop_column("users", "role")
