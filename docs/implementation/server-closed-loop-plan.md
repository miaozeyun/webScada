# 服务端监控闭环 · 实施契约（M8）

> 版本：1.0（2026-10-20，首席架构师签发）
> 读者：6 个并行实施 agent（A~F）。本文是唯一实施权威；与 `docs/design/02/03` 冲突处，以本文为准并已回写 02/03（见 §10 修订记录）。
> 共享骨架已由架构师落地（§8），实施 agent **禁碰**；六个包只新建/独占修改 §7 分工表内的文件。

---

## 1. 目标数据流（改造后）

```
上游设备/ broker
   │
   ▼
services/collector.py（服务端常驻，工作包 A）
   ├─ mqtt：aiomqtt 订阅（Fernet 解密 config.password 后鉴权连接；QoS/cleanSession 按 doc）
   ├─ rest：httpx 定时轮询
   ├─ websocket：上游 WS 长连接客户端
   └─ mock：服务端仿真（sine/ramp/random/square/hold，与前端 MockSpec 同语义）
   │  raw（含 q/t 判定：缺帧/解析失败=bad；超 staleTimeoutMs=stale）
   ▼
services/hub.py（A）：per-project 变量池 {key: {v,q,t}}
   换算流水（与 02 §2.9 同口径，服务端执行）：
   ① address 定位帧 + jsonPath 取值 → ② bitIndex 位提取 → ③ 按 type 规范化
   （number: ×scale+offset；boolean 归一 true/false；string 原样）→ ④ precision
   用 decimal.Decimal ROUND_HALF_UP 量化（禁用内置 round，防银行家舍入分叉）
   → 虚拟变量 expr 拓扑求值（Python 白名单求值器，文法=web/src/utils/expr.ts）
   │  值变化 → 监听器回调（B 注册：rules_engine.evaluate / historian.push）
   │         → ws_manager.mark_dirty(project_id, key)
   ▼
services/ws_manager.py（A）：/api/v1/ws/runtime
   100ms 合帧 + 变化抑制 → values 帧；snapshot（内嵌 activeAlarms ≤200）；
   alarm/alarmClear/alarmAck/writeAck/reload/error 即时帧；ping/pong 心跳 20s/40s 判死
   │  双鉴权：编辑器 JWT（live doc，可写按角色）｜分享 shareToken（快照 doc，只读）
   ▼
浏览器（编辑器预览 / 运行大屏 / 分享页 / iframe）
   - web/src/runtime/sources.ts 新增 server 模式：引擎值池改由 WS 帧驱动
   - 浏览器直连适配器（mqtt.js/fetch/WebSocket）仅保留为编辑器「数据源连接测试」专用；
     有存储凭证的源走服务端 POST /api/v1/datasources/test（凭证注回），不再浏览器直连带鉴权上游
```

配套闭环（B/C）：
- 报警：rules_engine（服务端 7x24 判定，迟滞+durationMs）→ alarm_service 单行状态机入库 → notify（webhook/邮件，`ALARM_NOTIFY_MIN_LEVEL` 以下不发）→ REST ack。
- 历史：historian 定窗采样（`HISTORY_SAMPLE_INTERVAL_MS`，窗口内取最后一个 good 值）→ `history_values` 入库 → 区间查询 API；清理任务消费 `HISTORY_RETENTION_DAYS`。
- RBAC/审计：`users.role`（admin/operator/viewer）+ `audit_logs` 埋点（login/write_var/alarm_ack/project_save/share_create/share_revoke/user_mgmt）。
- 迁移通道：前端 `migrateDoc()`（F）+ 服务端 N-1 兼容窗口（F）+ `CURRENT_SCHEMA_VERSION` 冻结规约（§6）。

## 2. 现状基线（通读结论，2026-10-20）

| 事实 | 影响 |
|---|---|
| `server/app` 现有：auth/projects/shares/alarms/health 五路由；alarms 仅「前端上报入库」（status active/recovered 双行） | B 包重写为服务端状态机 |
| `pyproject` 已声明 aiomqtt/websockets/httpx，server 零引用 | A 包直接使用，无需改 pyproject |
| 出口脱敏 + PUT 空值保留合并已实现（utils/sanitize.ts↔sanitize.py 对） | A 包 collector/连接测试按需 `utils.encrypt.decrypt` 注回 |
| schemaVersion 硬等值校验在 `doc_service.check_schema_version`（PUT/import 双路径），前端 migrateDoc 不存在 | F 包实现三件套；`CURRENT_SCHEMA_VERSION=1` 冻结 |
| 限流参数（RATE_LIMIT_CONNECT_PER_MIN 等）零消费；JWT_SECRET 弱值不拦截；无 CORS 中间件；无 /metrics | 已由共享骨架落地（§8） |
| 前端引擎：`sources.ts` 浏览器直连四源；`engine.ts` 换算/报警/虚拟变量/历史全前端 | A 包 sources/engine 改造；D 包消费帧 |
| `alarm_records.recovered_at` 存量列、`users` 无 role 列 | alembic 0002 已迁移（§8.5） |

## 3. 数据库变更（alembic 0002，已随共享骨架落地）

权威迁移：`server/alembic/versions/0002_server_closed_loop.py`（可 downgrade，包含数据回填）。

1. `users` + `role TEXT NOT NULL DEFAULT 'admin' CHECK (role IN ('admin','operator','viewer'))`；存量全部 admin。
2. `alarm_records` 单行状态机：+`acked_at/acked_by(FK users SET NULL)/acked_note/cleared_at`；`status ∈ triggered|acked|cleared`；存量 active→triggered、recovered→cleared（cleared_at=recovered_at）；`recovered_at` 删除。
3. 新表 `audit_logs(id, user_id FK SET NULL, username 快照, action, target_type, target_id, detail JSONB, ip, created_at)` + 索引 created_at/user_id/action。
4. 新表 `history_values(id, project_id FK CASCADE, variable_key, ts, value DOUBLE PRECISION)` + 索引 (project_id, variable_key, ts DESC)；按 ts 分区可后置（本版不做，契约声明：分区改造时不得改表名/列语义，仅 pg_partman/原生分区迁移）。

模型权威：`server/app/db/models.py`（User.role / AuditLog / HistoryValue / AlarmRecord 扩展）。ORM 与迁移一致性由集成门禁 pytest 抽查（create_all 与 alembic upgrade 各跑一遍 schema 对比冒烟）。

## 4. API 路由清单（前端并行开发依据）

通用：信封/422/409 契约不变（03 §1.3）；时间 REST=ISO8601 UTC；权限列中「角色」仅约束 JWT 用户，分享 token 通道见 WS 一节。

### 4.1 报警（B 包）

| 方法/路径 | 权限 | 请求 → 响应 |
|---|---|---|
| `GET /api/v1/projects/{id}/alarms` | JWT 任意角色 | `?status=triggered,acked&level=&variableKey=&from=&to=&page=&size=`（status 缺省=`triggered,acked`；from/to ISO8601 按 triggered_at）→ `{total,page,size,items:[AlarmOut]}`；AlarmOut=`{id,ruleId,variableKey,level,message,value,status,triggeredAt,ackedAt?,ackedBy?,ackedNote?,clearedAt?}` |
| `POST /api/v1/projects/{id}/alarms/{alarmId}/ack` | operator/admin | `{"note"?: "≤256"}` → 200 `{id,status,ackedAt,ackedBy,ackedNote}`；幂等（acked/cleared 重复 ack 返回当前态）；成功后向工程在线 WS 广播 `alarmAck` 帧；落审计 alarm_ack |
| `GET /api/v1/projects/{id}/alarm-records` | 废弃别名 | 委托同实现；前端一律改用 `/alarms` |
| `POST /api/v1/projects/{id}/alarm-records` | 废弃兼容 | 旧前端上报 active/recovered → 映射状态机 trigger/clear；M8 前端（D 包）停用该端点 |

### 4.2 历史（B 包）

| 方法/路径 | 权限 | 请求 → 响应 |
|---|---|---|
| `GET /api/v1/projects/{id}/history` | JWT 任意角色；分享页 `Authorization: Bearer <shareToken>`（服务端识别 token 类型） | `?keys=a,b`(≤20)&from=&to=&stepMs=0&maxPoints=2000 → `{"series":{key:[[epochMs,number],...]}}`；stepMs>0 服务端窗口均值聚合；跨度 ≤ HISTORY_RETENTION_DAYS；单序列点数 ≤10000 |

### 4.3 用户管理（C 包，admin）

| 方法/路径 | 权限 | 请求 → 响应 |
|---|---|---|
| `GET /api/v1/users` | admin | `?keyword=&page=&size=` → `{total,page,size,items:[{id,username,role,createdAt}]}` |
| `POST /api/v1/users` | admin | `{"username":"≤64","password":"≥8","role":"admin|operator|viewer"}` → 201 UserOut；409 用户名重复 |
| `PUT /api/v1/users/{id}` | admin | `{"role":...}` → 200 UserOut；禁止降级最后一个 admin（409） |
| `PUT /api/v1/users/{id}/password` | admin | `{"newPassword":"≥8"}` → 204（无需旧密码；落审计 user_mgmt） |
| `DELETE /api/v1/users/{id}` | admin | → 204；不能删自己（422 self_delete）；最后一个 admin 409 |
| `GET /api/v1/auth/me`（改） | JWT | UserOut 增加 `role` 字段（C 包改 auth.py） |

### 4.4 审计查询（C 包，admin）

| 方法/路径 | 权限 | 请求 → 响应 |
|---|---|---|
| `GET /api/v1/audit-logs` | admin | `?userId=&action=&targetType=&targetId=&from=&to=&page=&size=` → `{total,page,size,items:[{id,userId,username,action,targetType,targetId,detail,ip,createdAt}]}` 按 createdAt 倒序 |

### 4.5 数据源连通性测试（A 包）

| 方法/路径 | 权限 | 请求 → 响应 |
|---|---|---|
| `POST /api/v1/datasources/test` | operator/admin | `{"type":"mqtt|websocket|rest|mock","config":{...同 doc},"projectId"?,"datasourceId"?}` → 200 `{ok,type,latencyMs,message}`；**凭证注回**：携带 projectId+datasourceId 且敏感字段空/缺省时，用库内 Fernet 密文解密后测试（空值保留语义）；非空明文按本次值；日志脱敏；结果不落库 |

### 4.6 运行态 WS 与可观测

| 端点 | 权限 | 说明 |
|---|---|---|
| `GET /api/v1/ws/runtime?project=&token=<JWT\|shareToken>&page=` | token 双通道 | 帧协议见 §5；并发上限 SHARE_MAX_WS_PER_TOKEN / JWT_WS_MAX_PER_USER_PROJECT / WS_MAX_CONNECTIONS |
| `GET /metrics`（根路径） | METRICS_TOKEN 可选 | Prometheus 文本；`webscada_uptime_seconds / ws_connections / collector_tasks / alarms_active / ws_frames_*_total / notify_*_total / rate_limited_total` |

### 4.7 既有接口的角色收敛（C 包改 projects.py/shares.py）

- `DELETE /projects/{id}`：admin 或 owner（operator 非 owner 403；viewer 403）。
- `PUT /projects/{id}`、`POST /projects/import`、`POST/DELETE /shares`：operator/admin（owner 校验仅 delete 收紧，其余团队协作口径=operator 全工程可编辑）。
- 全部写路径（project_save/share_create/share_revoke/login/write_var/alarm_ack/user_mgmt）落审计（audit_service，见 §6.3）。

## 5. WS 帧协议（/api/v1/ws/runtime，权威=03 §3 + 本节 M8 增补）

- 连接序列：token 校验（JWT 签名/有效期 或 shareToken 存在/未撤销/未过期）→ 并发上限检查（超限 `error(RATE_LIMITED)` 后 close 4000）→ 立即推 `snapshot`（内嵌 `activeAlarms`，≤200 条按 critical>warn>info 截断置 `truncated=true`）→ 持续 `values`（100ms 合帧+变化抑制）/ `alarm` / `alarmClear` / `alarmAck` / `reload` / `ping`。
- 帧目录（03 §3.4 + M8 增补，全部 JSON 文本帧）：
  - S→C `snapshot` / `values` / `alarm` / `alarmClear` / `ping` / `error` / `reload`：不变，值均为工程值（服务端换算后），`q ∈ good|stale|bad`，`bad` 时 `v=null`。
  - S→C `alarmAck`（M8 新）：`{"type":"alarmAck","alarmId":1024,"ackedAt":epochMs,"ackedBy":"username"}`，REST ack 成功后广播。
  - C→S `write`（M8 新）：`{"type":"write","reqId":"...","variableKey":"...","value":true}`。
  - S→C `writeAck`（M8 新）：`{"type":"writeAck","reqId":"...","ok":true}` 或 `{ok:false,code,message}`；`code ∈ NOT_WRITABLE|READ_ONLY|FORBIDDEN|VARIABLE_NOT_FOUND|WRITE_FAILED`。
- error 帧 code 集沿用 03 §3.3（TOKEN_EXPIRED/PROJECT_REMOVED/SHARE_REVOKED/SHARE_EXPIRED/RATE_LIMITED/PROJECT_MISMATCH 预留/INTERNAL_ERROR），close code 4000。
- 语义细则：
  - 分享连接值流按 live doc 变量集推送（快照 doc 仅决定渲染），客户端忽略未知 key（03 §3.4 既定）。
  - 服务端 20s ping，40s 无 pong 判死 close；客户端 30s 无入站帧自行重连（指数退避 1s→30s±20%）。
  - 服务重启：客户端退避重连后重发 snapshot；lifespan 重建采集与规则引擎，遗留 triggered/acked 记录启动收口为 cleared（sweep_on_startup）。
  - 分享 refresh → 该 token 全部连接 `reload`；工程 DELETE → 全部连接 `error(PROJECT_REMOVED)`；撤销 token → 该 token 连接 `error(SHARE_REVOKED)`。

## 6. 服务端模块设计（关键签名，实施 agent 按此实现，禁止改名）

### 6.1 工作包 A

```
services/expr_eval.py      # Python 白名单表达式求值器：文法与 web/src/utils/expr.ts 逐一对应
                           #   eval_expr(src: str, scope: dict[str, Value]) -> Value；expr_idents(src) -> list[str]
services/convert.py        # 换算流水唯一实现点：
                           #   to_engineering(var: VariableDef, raw: unknown) -> EngineeringValue
                           #   precision 用 Decimal ROUND_HALF_UP；bitIndex 优先；非法→值保持上一有效+q=bad
services/hub.py            # class Hub:
                           #   pool(project_id) -> dict[key, {v,q,t}]；set_doc(project_id, doc)；remove(project_id)
                           #   ingest(project_id, variable, raw, ts)   # collector 唯一入口
                           #   add_value_listener(fn) / remove_value_listener(fn)
                           #     # fn(project_id, variable: VariableDef, value, q, ts)；B 在 background_jobs 注册
                           #   mark_dirty 由 ingest 内部调 ws_manager；虚拟变量拓扑求值后同样走 ingest 通道
services/collector.py      # class Collector:
                           #   sync(project_id, doc)   # 差量热重建（datasource id+config hash）
                           #   remove(project_id)；write(project_id, variable, value)
                           #   MqttSource/RestSource/UpstreamWsSource/MockSource；Fernet decrypt 注回；
                           #   重连退避 COLLECTOR_RECONNECT_*；client id = webscada-{projectId}-{nanoid8}
services/ws_manager.py     # class WSManager:
                           #   connect/ws_close/广播原语；100ms 合帧循环；20s ping；
                           #   snapshot 组装（惰性 import alarm_service 取 activeAlarms）；
                           #   broadcast_alarm/alarm_clear/alarm_ack(project_id, ...)（B 调用）
                           #   broadcast_reload(token)（C 的 shares refresh 调用）
                           #   broadcast_project_removed(project_id)（A 的 project_service 删除钩子调用）
services/runtime_boot.py   # startup(app)/shutdown(app)：Collector+Hub+WSManager 装配、挂 app.state、
                           #   启动时对全部工程 sync；PUT/删除钩子见 project_service 独占说明
api/v1/ws.py               # GET /ws/runtime（token 双鉴权、并发计数、snapshot 首帧、write 帧→collector）
api/v1/datasources.py      # POST /datasources/test（凭证注回）
```

A 包独占旧文件：`services/project_service.py`（在 update_doc 成功后调 `collector.sync + hub.set_doc`；delete_project 内调 `hub.remove + collector.remove + ws_manager.broadcast_project_removed`；import_project 同 update_doc）。其余旧文件禁改。

### 6.2 工作包 B

```
services/alarm_service.py  # 状态机唯一实现点（REST 与引擎共用）：
                           #   trigger(db, project_id, rule快照, value_str, at) -> int|None
                           #   #   同 (project_id, rule_id) 存在未恢复行 → 不插新行返回既有 id（修复恢复另插新行）
                           #   clear(db, project_id, rule_id, at) -> int|None   # triggered/acked→cleared
                           #   ack(db, project_id, alarm_id, user, note) -> AlarmRecord
                           #   active_for_snapshot(db, project_id, limit=200) -> list[dict]  # WS snapshot 用
                           #   sweep_on_startup(db) -> int    # 遗留 triggered/acked→cleared
                           #   cleanup_expired(db) -> int     # ALARM_RETENTION_DAYS + 单工程行数上限
                           #   事件外发经惰性 import notify；WS 广播经惰性 import ws_manager
services/rules_engine.py   # 服务端判定：hysteresis 回差带 + durationMs 持续窗（02 §2.11 表格逐条实现）
                           #   attach(hub)：注册值监听；对 q!='good' 不判定；boolean 用 1/0
services/notify.py         # webhook(httpx) + 邮件(aiosmtplib? 禁——标准库 smtplib 异步包装)
                           #   # 依赖约束：不新增第三方依赖；SMTP 用 asyncio.to_thread(smtplib.SMTP_SSL/STARTTLS)
                           #   send_alarm(record, rule) -> None；节流 ALARM_NOTIFY_THROTTLE_SEC；
                           #   级别 < ALARM_NOTIFY_MIN_LEVEL 不发；失败计数 stats.notify_failed_total
services/historian.py      # class Historian: push(project_id,key,ts,value)/flush/start(app)/stop(app)
                           #   缓冲 HISTORY_WRITE_BATCH 条或 HISTORY_SAMPLE_INTERVAL_MS 定窗落库；
                           #   cleanup_history(db) -> int  # HISTORY_RETENTION_DAYS
services/background_jobs.py# startup(app)/shutdown(app)：
                           #   启动先跑 sweep_on_startup + 两类清理；每 24h 循环；
                           #   hub.add_value_listener(rules_engine) + hub.add_value_listener(historian.push)
api/v1/alarms.py           # §4.1 全部（改造既有文件）
api/v1/history.py          # §4.2（新建）
schemas/alarm.py           # AlarmOut 扩展 + AckBody（独占修改）
schemas/history.py         # 新建
```

### 6.3 工作包 C

```
services/audit_service.py  # async def audit(request|None, user|None, action, target_type=None,
                           #   target_id=None, detail: dict|None = None) -> None
                           #   # 自建短会话提交（不搭主请求事务，防回滚吞审计）；失败 log 不抛
                           #   # ip 取 X-Forwarded-For 首段（uvicorn --proxy-headers 已信任 nginx）
api/deps.py                # 既有 get_current_user 不变；新增工厂依赖（签名冻结）：
                           #   require_role(*roles: str) -> Dependency    # 不足 403 FORBIDDEN
                           #   require_admin / require_operator           # 便捷别名
                           #   require_project_edit(user, project_id) / require_project_view(...)
api/v1/users.py            # §4.3 全部（新建）
api/v1/audit.py            # §4.4（新建）
api/v1/auth.py             # me 返回 role；login 成功/失败落审计 login（detail 含 success/ip）
api/v1/projects.py         # DELETE owner/admin 收紧 + project_save 审计；import 同
api/v1/shares.py           # share_create/share_revoke 审计；refresh 成功后惰性 import
                           #   ws_manager.broadcast_reload(token)
schemas/user.py            # 新建（UserCreate/UserUpdate/UserOut/UserPasswordReset）
core/security.py           # 禁改（JWT/黑名单机制不变）
```

### 6.4 跨包依赖规约

- **禁止模块顶部跨包 import**：跨包调用（B→A 的 ws_manager/hub、C→A 的 ws_manager、A→B 的 alarm_service 快照查询）一律在**函数体内惰性 import**；防 import 环、防单包测试被其他包缺席卡死。
- 事件流向单向：collector→hub→(listeners: rules_engine, historian)→ws_manager 广播。REST ack（B）→ ws_manager.broadcast_alarm_ack。
- D/E 仅依赖 §4 API 契约，不依赖 B/C 代码完成（可并行开发，联调在集成门禁后）。

## 7. schemaVersion 迁移通道（F 包 + 冻结规约）

### 7.1 前端 migrateDoc（新建 web/src/utils/migrateDoc.ts + web/src/types/migrations.ts）

- `const MIGRATIONS: Record<number, (doc) => doc>`（键 = 起始版本，注册表集中于 migrations.ts）。
- `migrateDoc(raw: unknown): { ok: true; doc: ProjectDoc } | { ok: false; reason: 'too_new'|'invalid'; message: string }`
- 算法：非对象/无版本 → invalid；`v > CURRENT` → too_new（提示升级前端，禁止静默降级）；`v < CURRENT` → while 逐版应用 `MIGRATIONS[v]`，任一步抛错 → invalid；结果深拷贝（不用 structuredClone，Vite es2020 基线）。
- 挂接点：编辑器导入入口（文件选择/拖入）与 `web/src/api/projects.ts importProject` 提交前（F 独占该文件）。

### 7.2 服务端 N-1 兼容窗口（F 独占 services/doc_service.py）

- `check_schema_version` 放宽为接受 `v ∈ [CURRENT - settings.SCHEMA_COMPAT_WINDOW, CURRENT]`；
- `v < 下限` → 422 `version_unsupported`（文案指引前端 migrateDoc 导入入口）；`v > CURRENT` → 422（文案提示升级服务端）；
- 窗口语义：仅灰度缓冲，入库前仍按 CURRENT 结构校验——N-1 与 CURRENT 结构兼容（只增不改）是提版前置条件，不实现 Python 侧迁移逻辑。

### 7.3 CURRENT_SCHEMA_VERSION 冻结规约（本期保持 =1，仅交付机制与测试位）

提版（N→N+1）必须同时满足：① `MIGRATIONS[N]` 已实现且有 round-trip 测试；② N+1 对 N 严格向后兼容（只增字段/枚举值）；③ 服务端窗口参数默认 1 生效；④ 前后端 CURRENT_SCHEMA_VERSION 同 PR 同步；⑤ 测试矩阵覆盖「v=N 文件 → migrateDoc → 服务端保存 → 导出=v N+1」全链路。本期验收用假想 v=2 验证服务端拒绝路径、窗口参数模拟 N-1 接受路径。

## 8. 共享骨架（架构师已落地，实施 agent 禁改）

| 文件 | 状态 | 内容 |
|---|---|---|
| `server/app/db/models.py` | 已改 | User.role；AlarmRecord 状态机列 + 新值域约束；AuditLog；HistoryValue |
| `server/app/core/config.py` | 已改 | M8 全部新参数（采集/历史/通知/限流/CORS/METRICS_TOKEN/SCHEMA_COMPAT_WINDOW）+ `validate_runtime()`（JWT 弱值/短值 fail-fast，DEBUG 豁免） |
| `server/app/core/stats.py` | 新建 | 进程内指标注册表：`inc()/set_gauge()/render()`；各包埋点唯一入口 |
| `server/app/core/rate_limit.py` | 新建 | 自研滑动窗口限流中间件（登录/分享文档/连通性测试三条规则，429 信封+Retry-After，`reset_for_tests()`） |
| `server/app/api/v1/metrics.py` | 新建 | GET /metrics（根路径，METRICS_TOKEN 可选） |
| `server/app/main.py` | 已改 | 挂全部新路由 import、RateLimitMiddleware、CORS 收紧（CORS_ORIGINS 白名单非空才启用）、lifespan 顺序 `ensure_key → validate_runtime → runtime_boot.startup → background_jobs.startup`（关闭逆序） |
| `server/app/api/v1/__init__.py` | 已改 | 模块清单与分工声明（纯文档，不做 import） |
| `server/alembic/versions/0002_server_closed_loop.py` | 新建 | §3 全部（可 downgrade，含数据回填） |
| `.env.example`（根目录） | 已改 | M8 新配置段 |
| `docker-compose.yml` | 已改 | 新配置环境变量透传（该文件不属任何包，防「死配置」重演） |
| `docs/design/02`、`docs/design/03` | 已改 | §10 修订记录 |

**集成说明（重要）**：main.py 顶部 import 的 `api/v1/{ws,datasources,history,users,audit}` 与 `services/{runtime_boot,background_jobs}` 由工作包交付，**全部包合入前服务不可启动、main.py import 失败——这是预期中间态**。为此：① 各包 pytest 不得依赖 `app.main` 全量装配（见各包测试策略：自建 mini FastAPI app + `include_router(own_router)` + `dependency_overrides[get_db]`）；② 集成门禁（§9）统一跑全量。

## 9. 工作包分工表与集成顺序

| 包 | 新建文件 | 独占旧文件 | API/接口 | pytest 验收（目标全绿） |
|---|---|---|---|---|
| **A 采集与 WS 推送** | services/{expr_eval,convert,hub,collector,ws_manager,runtime_boot}.py；api/v1/{ws,datasources}.py；tests/test_convert.py、test_expr_eval.py、test_ws_runtime.py | services/project_service.py（PUT/删除/导入钩子）；web/src/runtime/{sources,engine,store}.ts；web/src/editor/RuntimeStage.vue；web/src/views/ShareView.vue | §4.5、§4.6 WS、§6.1 签名 | convert：bitIndex/scale/offset/precision（ROUND_HALF_UP 边界 x.5）、boolean 归一、bad/stale；expr_eval 与前端 expr.ts 用例同构；hub 虚拟变量拓扑+环不死循环；ws：JWT/分享/非法 token、snapshot 首帧（activeAlarms 截断）、values 合帧抑制、write→writeAck 各 code、并发上限 429 语义、reload/PROJECT_REMOVED/SHARE_REVOKED |
| **B 报警引擎与通知** | services/{alarm_service,rules_engine,notify,historian,background_jobs}.py；api/v1/history.py；schemas/history.py；tests/test_alarm_state_machine.py、test_rules_engine.py、test_historian.py、test_history_api.py、test_notify.py | api/v1/alarms.py；schemas/alarm.py | §4.1、§4.2 | 状态机：trigger 幂等不插新行、ack 幂等/迟ack、clear 保留 ack 字段、sweep_on_startup；rules_engine 迟滞表逐 op + durationMs；historian 批量入库+保留清理；history API 区间/stepMs 聚合/maxPoints；notify webhook(httpx MockTransport)+SMTP 线程池、节流、级别过滤；ack 落审计（惰性 import 打桩） |
| **C RBAC 与审计** | services/audit_service.py；api/v1/{users,audit}.py；schemas/user.py；tests/test_rbac.py、test_users_api.py、test_audit.py | api/deps.py；api/v1/auth.py；api/v1/projects.py；api/v1/shares.py | §4.3、§4.4、§4.7 | 角色依赖 401/403 矩阵（viewer/operator/admin × 写端点）；users CRUD+最后一个 admin 保护+self_delete；audit 埋点七类 action 各一例、SET NULL 后 username 快照可读；login 成功/失败审计；shares refresh 触发 broadcast_reload（打桩） |
| **D 前端报警呈现** | web/src/components/alarm/{AlarmPanel.vue,AlarmBanner.vue}；web/src/api/history.ts；tests（vitest 若无则手测清单） | web/src/widgets/WidgetHost.vue；web/src/widgets/HistoryChart*.vue（现有历史图组件）；web/src/api/alarms.ts | §4.1/§4.2 消费端 | WidgetHost 报警态优先级 S2>S1>S0+闪烁（02 §2.12）；ack 按钮（角色隐藏/禁用）→API→alarmAck 帧联动；报警列表过滤+分页；HistoryChart 接 /history（stepMs 联动 range 选择），服务端不可达回落本地缓冲 |
| **E 前端管理页** | web/src/views/admin/{UsersView.vue,AuditView.vue}；web/src/api/{users,audit}.ts | web/src/router/index.ts；web/src/views/ProjectsView.vue（菜单入口） | §4.3/§4.4 消费端 | 用户 CRUD 表单校验（密码≥8、角色枚举）、最后一个 admin 删除 409 提示；审计表过滤+分页+detail JSON 展开；非 admin 路由守卫跳转 |
| **F 迁移通道** | web/src/utils/migrateDoc.ts；web/src/types/migrations.ts；tests/test_migrate_doc.ts（或 vitest）；server/tests/test_schema_window.py | services/doc_service.py；web/src/api/projects.ts | §7 | migrateDoc：v=CURRENT 直通/v>CURRENT too_new/逐步升级/非法输入 invalid；服务端：v=CURRENT 接受、v=CURRENT-1 接受（窗口=1）、v=CURRENT-2 与 v=CURRENT+1 均 422 version_unsupported；round-trip 回归不破 |

**依赖与集成顺序**：
1. 骨架（已备）→ 2. A、B、C 并行编码（B/C 按契约签名惰性引用 A，D/E/F 按 §4/§5/§7 契约并行，不等后端）→ 3. 集成门禁：合入顺序 A→B→C→F（F 的 doc_service 与 A 的 project_service 不冲突但校验链路相关）→ D/E 联调 → 门禁清单：
   - `pytest`（server）全绿；`alembic upgrade head` + `downgrade` + 再 `upgrade` 往返成功；
   - `docker compose up` 冒烟：mock 工程预览 WS 出值 → 制造报警 → webhook 收帧 → ack → 历史查询有点 → 用户管理建 operator → operator ack 成功/viewer ack 403；
   - 前端 `npm run build` 通过；E2E 手测清单（D/E 包内）执行。

## 10. 设计文档回写记录（已由架构师完成）

| 文档 | 小节 | 修订 |
|---|---|---|
| 02 §4.1.1（新增） | M8 DDL 增量权威（role/状态机/audit_logs/history_values） |
| 02 §4.2 | 「变量实时值、趋势缓冲不落库」改为 hub 内存 + history_values 入库 |
| 02 §7.1 | 反控由「浏览器直连」改为服务端 WS write 通道；浏览器直连仅数据源连接测试 |
| 02 §7.7 | 历史权威迁移服务端；本地分钟桶降级为演示用途 |
| 03 §1.2 | 角色（admin/operator/viewer）与 403 语义 |
| 03 §2.7 | 报警列表过滤增强 + 单行状态机字段 + ack 落地（P1→M8）+ 废弃别名 |
| 03 §2.9 | datasources/test 凭证注回语义 |
| 03 §2.10~2.13（新增） | history / users / audit-logs / metrics |
| 03 §3.4 | C→S write、S→C writeAck/alarmAck 增补帧 |
| 03 §4.4 / §5 | history 挂点落地；M8 交付映射行 |

## 11. 风险与边界声明

1. **中间态不可启动**：见 §8 集成说明；任何包不得为「让服务跑起来」而注释掉 main.py 的 import（禁改骨架）。
2. **Python 表达式求值器（A）** 是最易漂移点：文法必须以 `web/src/utils/expr.ts` 为准做同构用例；虚拟变量求值失败回落上一值并 warn（不阻断值流）。
3. **限流为单实例口径**（进程内 dict）：多 worker/横向扩容时退化为单实例粒度，Redis 后端为 P1 预留；WS 心跳与并发上限同样单实例。
4. **JWT 黑名单仍为进程内**（重启失效，≤2h 窗口已声明）；Redis 化与 auth/refresh 留 P1，本契约不含。
5. **EMQX 匿名监听（8083 宿主机直暴）、nginx TLS、LICENSE** 属商用化「阶段 0」止血项，不在本契约范围；本契约上线前应先行完成或至少收口 EMQX 端口发布。
6. **history_values 高频写入**：单机 2C4G 基线按 5s 定窗 × 5000 变量/工程 ≈ 1000 行/s 峰值，PG 可承受；分区改造为后置项（§3 约束不改语义）。
7. **notify SMTP 走线程池**（asyncio.to_thread）：外发阻塞不回传值流；webhook 失败仅计数重试节流，不做死信队列（P1）。
8. **存量数据**：0002 迁移把 recovered 报警映射为 cleared，旧前端（未升级）读到 `status='cleared'` 未知值需容错显示——D 包前端按未知状态灰显兜底。
9. **compose 新配置透传**由共享骨架完成（§8）；后续新增配置必须同步 .env.example + compose + config.py 三处，纳入代码评审 checklist。

## 12. 交付物验收总清单（集成门禁）

- [ ] server pytest 全绿（含六包新增测试）
- [ ] alembic upgrade/downgrade 往返 + 0002 数据回填抽查
- [ ] WS 帧联调：snapshot/values/alarm/alarmClear/alarmAck/write/writeAck/reload/error 全帧至少一例
- [ ] 双鉴权：JWT 四角色 × 写操作矩阵、shareToken 只读
- [ ] /metrics 指标出现且随负载变化
- [ ] 前端 build + D/E 手测清单
- [ ] migrateDoc 机制测试位就绪（CURRENT 仍 =1）
- [ ] .env.example / compose / config.py 三处配置一致（评审 checklist）
