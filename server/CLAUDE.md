# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in the `server/` directory.

webScada 后端：FastAPI 单进程全异步（Uvicorn 单 worker），SQLAlchemy 2.0 async + Alembic + Pydantic v2，数据库 PostgreSQL（生产 asyncpg）。权威契约见 [docs/design/02-工程JSON数据结构.md](../docs/design/02-工程JSON数据结构.md) 与 [docs/design/03-接口清单.md](../docs/design/03-接口清单.md)；M8 服务端闭环实施契约在 [docs/implementation/server-closed-loop-plan.md](../docs/implementation/server-closed-loop-plan.md)。

## 命令

```bash
# 测试（默认 SQLite 内存库，无需 PG；Windows venv 在 .venv/Scripts）
.venv/Scripts/pytest                                 # 全量
.venv/Scripts/pytest tests/test_projects.py          # 单文件
.venv/Scripts/pytest tests/test_projects.py -k name  # 单用例
pip install -e ".[dev]"                              # 安装（Python 3.12）

alembic upgrade head        # 迁移（compose entrypoint 启动时自动执行）
alembic revision --autogenerate -m "..."   # 生成迁移（审阅后再用）
```

- pytest-asyncio `asyncio_mode = "auto"`：测试直接写 `async def test_...`，无需装饰器。
- **环境变量必须在导入 app 模块之前设置**（`Settings` 在导入时读取）——conftest.py 顶部已处理，新测试遵守此序。
- conftest 基座：SQLite 内存 + StaticPool，每测试重建引擎（单连接绑定首个事件循环，跨测试复用会串库）；进程内安全态（登录锁定 `_login_state`、jti 黑名单 `_revoked`、限流计数）每测试重置。`make_doc()` / `put_doc()` / `auth_headers` 是现成的 doc 构造与鉴权辅助。
- 启动服务（本地裸跑）：`uvicorn app.main:app --port 8000`；lifespan 有 fail-fast 自检（JWT_SECRET 弱值、DATASOURCE_SECRET 非法直接拒绝启动）。

## 架构

### 启动顺序（app/main.py lifespan，顺序冻结）

`ensure_key()` + `settings.validate_runtime()` → `runtime_boot.startup`（装配 Hub/Collector/WSManager 单例挂 app.state，启动合帧/心跳/stale 扫描循环）→ `background_jobs.startup`（hub 挂 rules_engine + historian 监听，启动收口与保留清理 + 24h 循环）。关闭逆序。

### 数据管线（services/）

```
collector.py 五源任务（mqtt/rest/ws/mock/modbus，保存后差量软重载，单源崩溃不拖垮其他源）
  → hub.ingest（唯一入口）→ convert.py 换算 → 变化判定 → 监听器（rules_engine、historian）→ mark_dirty
  → ws_manager.py 100ms 合帧 + 变化抑制 → /api/v1/ws/runtime（snapshot/values/alarm/alarmClear/ack/reload/error 帧）
```

- **convert.py 是换算流水唯一实现点**（bitIndex 位提取与 scale/offset/precision 互斥）；hub 只流转工程值，报警阈值按工程值口径。
- hub.py 另负责虚拟变量（expr）拓扑求值：Kahn 序 + 前向传播，visited 防环；失败回落上一值 warn 一次。
- rules_engine.py：迟滞/持续窗判定（q != 'good' 不判定；恢复仅越过回差带反向区间）。
- historian.py：定窗采样（窗口内 last-write-wins 仅留最后一个 good 值）+ 批量落库；flush 失败丢弃本批不阻塞值流（尽力而为语义）。
- **expr_eval.py 与前端 `web/src/utils/expr.ts` 文法逐一对应（契约最易漂移点）——改任一侧必须双侧同步且用例同构。**

### doc 校验与保存（doc_service / project_service）

- 校验流水线顺序固定：schemaVersion（接受兼容窗口 `[CURRENT-SCHEMA_COMPAT_WINDOW, CURRENT]`，入库前仍按 CURRENT 结构校验）→ 体积（>2MB 422 doc_too_large）→ Pydantic 结构 → 引用完整性（失败 422 + 字段路径）。统一错误体 `{code, message, errors:[{path,message}]}`。
- **schemaVersion 迁移唯一实现点在前端 migrateDoc()，服务端不做迁移**。
- PUT 流水线：凭证空值合并（缺省/空串=保留库内值、显式 null=清除）**先于**结构校验 → 409 乐观锁（baseRevision）→ 凭证 Fernet 加密 → revision+1。
- 导入流水线：凭证一律置空 → 重写 project.id → 新建 revision=1，不覆盖已有工程。
- 凭证所有出口（GET 详情/导出/分享快照）脱敏；share_links.doc_snapshot 为脱敏冻结快照，「发布」= 创建/刷新分享链接。

### 模型与配置

- `db/models.py` 六表单文件：users（RBAC 三角色）、projects（doc JSONB + revision 乐观锁）、share_links（token + doc_snapshot）、alarm_records（active/recovered 状态机）、audit_logs（八类操作）、history_values（5s 采样/30 天保留）。
- `core/config.py`：pydantic-settings，全部 env 有注释；`core/security.py`（bcrypt/PyJWT/jti 黑名单/登录锁定）、`core/rate_limit.py`（自研纯 ASGI 中间件，登录/分享/连通性测试/历史各有限额；`RATE_LIMIT_ENABLED=false` 仅压测旁路）。
- `api/v1/uploads.py`：图片直传落盘（`UPLOAD_DIR`，compose 命名卷 `uploads_data`；镜像内预建目录并 chown appuser）。上传 operator/admin，读取匿名（分享页）；按魔数只收 png/jpg/gif/webp，SVG 拒绝。
- `core/license.py`：License key 骨架（`LICENSE_KEY` 空 = 开源核心模式）。

## 约定与陷阱

- **单实例边界**：jti 黑名单、登录锁定、限流、WS 并发计数全在进程内存——多 worker/多副本即失效；重启使全部会话失效（JWT ≤2h，分享 token 不受限）。
- 单测跑在 SQLite：不要在迁移或运行时代码里用 PG 方言特性（如 `ON CONFLICT`）；CI 另有 PG16 上的 alembic 冒烟。
- WS 错误语义：统一 accept 后推 `error` 帧再 close(4000)（唯一例外 PROJECT_MISMATCH 保持连接）；token 走查询串，访问日志一律不打（uvicorn `--no-access-log`，访问日志由 nginx 脱敏输出）。
- entrypoint.sh 顺序：等 DB → alembic upgrade → create_admin（幂等）→ uvicorn（`--proxy-headers` 采信 nginx 的 X-Forwarded-For，限流依赖真实 client IP）。
- 日志用 Loguru（main.py 已接管标准 logging）；新增依赖进 pyproject.toml 的 `dependencies`（Dockerfile 按 tomllib 解析安装，不会读 requirements.txt）。
- 异步纪律：全链路 async，禁止在事件循环内做阻塞 IO；采集任务必须有异常兜底循环。
