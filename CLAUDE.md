# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目定位

webScada：Web 原生低代码拖拽组态的实时监控大屏（AGPL-3.0 开源核心 + 企业版双授权，当前 internal-pilot 阶段）。前端 Vue3 + TypeScript + Vite + Pinia + Element Plus + ECharts；后端 FastAPI + PostgreSQL（异步 SQLAlchemy 2.0 + Alembic + Pydantic v2，**数据库是 PostgreSQL，不用 MySQL**）；MQTT 经 EMQX；部署为 docker compose 四容器（nginx / server / postgres / emqx）。

**权威设计契约在 [docs/design/](docs/design/00-总览.md)**（00 总览、02-工程JSON数据结构 为契约中心）。改契约须前后端双侧同步：`web/src/types/doc.ts` ↔ `server/app/schemas/doc.py` 同构。设计文档中的目录树是规划稿，实际落位以本仓库代码为准（如 collector / ws_manager 在 `server/app/services/` 下而非独立包）。

## 常用命令

```bash
# 后端测试（默认 SQLite 内存库，无需 PG；Windows venv 路径）
cd server
.venv/Scripts/pytest                       # 全量
.venv/Scripts/pytest tests/test_projects.py -k name   # 单文件/单用例
alembic upgrade head                       # 迁移（CI 中对真实 PG 冒烟）

# 前端
cd web
npm run dev                                # vite dev server，端口 5199（strictPort）
npm run build                              # vue-tsc --noEmit + vite build（类型检查是门禁）
npm test                                   # vitest run
npx vue-tsc --noEmit                       # 仅类型检查

# 部署（本地 .env 设 HTTP_PORT=8088，vite 代理 /api → localhost:8088 即 compose nginx 入口）
docker compose up -d --build

# E2E（Playwright sync API，需 compose 在跑 + vite dev 在跑）
python scripts/e2e_m1.py                   # BASE=http://localhost:5199
python scripts/acceptance_m0.py
```

CI（.github/workflows/ci.yml）两 job：server（PG16 service + alembic 冒烟 + `pytest -q`）、web（`npm ci` + vue-tsc + vite build）。

后端测试注意：环境变量必须在导入 app 模块之前设置（settings 导入时读取）；登录锁定/jti 黑名单/限流计数是进程内存，跨测试须重置（conftest.py 已处理）。vite 代理必须 `ws: true`，否则运行态 WebSocket `/api/v1/ws/runtime` 永挂连接中。

## 架构大图

### 编辑态/运行态双模式，共享唯一组件渲染器

`web/src/widgets/`（registry.ts 注册表 + WidgetHost.vue 统一挂载点）同时服务编辑画布与运行大屏，编辑态只是外面包了选中/操作层。新增组件 = 向 registry.ts 注册新 type + 新 .vue，不改其他模块。行业图元（75 个自绘 SVG）在 `web/src/assets/symbols/`。

### 工程 = 单 JSONB 文档 + 乐观锁

工程全量存 `projects.doc`（JSONB）+ `revision INT`。编辑器 3s 防抖全量 PUT（带 `baseRevision`），冲突 409 `REVISION_CONFLICT`。`schemaVersion` 冻结为 1；**服务端只做等值校验（422 version_unsupported）不做迁移，迁移唯一实现点在前端 `web/src/utils/migrateDoc.ts`**。

### 数据管线（server 单进程全异步，无 Redis / 无 MQ）

```
collector.py（MQTT/REST/WS/Mock/Modbus TCP 五源任务，保存后差量软重载）
  → 变量级换算（bitIndex → scale/offset → precision）→ hub.py 变量池（工程值 + 质量位 + 时间戳，进程内 Pub/Sub）
  → rules_engine.py（阈值/回差/持续判定，报警落库）＋ ws_manager.py（100ms 合帧 + 变化抑制）
  → WS /api/v1/ws/runtime 推 snapshot（内嵌 activeAlarms）/ values / alarm / alarmClear / reload / error 帧
```

**换算口径唯一（K9）**：服务端入池前一次换算，hub 只流转工程值；报警阈值、界面显示、测试注入统一按工程值口径。前端唯一换算点 `web/src/runtime/engine.ts` 的 `toEngineering()`（与后端同构，仅服务编辑器注入预览路径）；运行态值已由服务端换算，不再重复调用。

historian.py 落 `history_values`（5s 采样 / 30 天保留 / 区间聚合）；alarm_service 状态机 + ack + Webhook/邮件外发（notify.py）；RBAC 三角色（admin/operator/viewer）+ 八类审计（audit_service）。

### 「发布」= 分享快照，非状态机

签发/刷新分享链接时把库内 doc **脱敏后冻结**进 `share_links.doc_snapshot`；分享页 `/s/{token}` 只读快照，恒只读（反控写仅编辑器预览可用，且变量须显式 `writable=true`）。变量改名/删除后已分享大屏会显示停滞，刷新快照即恢复，属预期。

### 凭证治理（K11）

数据源凭证库内 Fernet 加密（密钥 `.env:DATASOURCE_SECRET`，**丢失后已存凭证不可解**）。所有出口（GET 详情/导出/分享快照）脱敏。PUT 合并规则：缺省/空串 = 保留库内值、显式 null = 清除；导入文件凭证一律视为空。

### 报警/绑定样式优先级（K12）

静态 props < 绑定映射 < 报警态；`visible` 绑定优先于报警。**唯一实现点 `web/src/widgets/WidgetHost.vue`**，不要在单个组件里另写一套。

### 单实例架构边界

限流计数、JWT 黑名单（jti）、WS 并发计数全在进程内存——多 worker/多副本即失效；重启使全部登录会话失效（JWT ≤2h，分享大屏走 token 不受限）。

## 硬性约定

- 接口前缀 `/api/v1`；运行态 WS 端点 `/api/v1/ws/runtime`（token 走查询串）。
- 校验失败统一 422 `{"code","message","errors":[{path,message}]}`。
- doc 内对象 id 由 nanoid 生成，前缀约定：`page_ / cmp_ / var_ / ds_ / bnd_ / alm_`。
- 浏览器基线 Chrome/Edge ≥ 90：build target es2020，**不用 `structuredClone`**（自写深拷贝 util）。
- 规模基线：doc > 2MB 服务端 422 `doc_too_large`；单页 ≤ 200 组件；≤ 5000 变量；WS 全实例 ≤ 50。
- 图片资产：二进制不进 doc——编辑器直传 `POST /api/v1/uploads` 落盘（compose `uploads_data` 卷），doc 只存相对 URL；`GET` 匿名可读（分享页无登录态）。
- 全站 UI 色彩走 `web/src/styles/theme.css` 的 CSS 令牌（浅色工业仪表主题），勿在组件里硬编码色值。
- 授权合规：AGPL-3.0 核心与企业版边界见 NOTICE.md；对外文案中竞品一律称「业界主流组态」不点名。
- **经验教训机制**：排查任何问题前先查阅 [docs/经验教训.md](docs/经验教训.md)；每解决完一个问题（bug / 踩坑 / 返工），把「现象 / 根因 / 解决 / 预防」追加到该文件对应分类下，无需用户提醒。

## 本地开发环境（Windows）

- 后端 venv 在 `server/.venv`；server 容器 8000 端口不暴露宿主机，一律经 nginx（本地 8088）。
- vite dev 固定端口 5199（本机 5173 被占，strictPort 防静默换端口误导 E2E）。
- E2E 陷阱：Playwright URL 匹配需用精确前缀而非 `**` 通配；Element Plus 受控输入要用键盘事件注入而非 `fill`。
