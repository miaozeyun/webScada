"""v1 路由模块清单（装配唯一入口为 app/main.py，本文件不做 import）。

既有：health / auth / projects / shares / alarms
M8 新增（六个工作包交付，契约见 docs/implementation/server-closed-loop-plan.md §4）：
- datasources（A：POST /datasources/test 连通性测试 + 凭证注回）
- ws        （A：/ws/runtime 服务端值流/报警/写通道）
- history   （B：/projects/{id}/history 历史区间查询）
- users     （C：用户 CRUD 与角色管理，admin）
- audit     （C：审计日志查询，admin）
- metrics   （共享骨架：/metrics 根路径，Prometheus 文本）

各包只新建/独占修改自己的模块文件；main.py / 本文件 / models.py / core/* 由首席架构师独占。
"""
