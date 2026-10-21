# Changelog

webScada 的所有显著变更记录在本文件。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)（0.x 阶段不含兼容性承诺）。

## [Unreleased] — 运维与法务文档包 + 服务端闭环改造（进行中）

### Docker 部署加固改造（2026-10-21）

#### Added

- **基础镜像加速开关**：`REG_PREFIX` 环境变量统一驱动 compose `image` 与两处 Dockerfile `FROM`
  （默认官方 `docker.io/`；国内设 `m.daocloud.io/docker.io/` 或 `dockerpull.com/`），pip/npm 源保持内建。
- **nginx 容器健康检查**：wget 探活 80 入口（此前仅 server/postgres/emqx 有 healthcheck）。
- **README.Docker.md 部署手册**：镜像加速、常用命令、备份恢复（引用 scripts/backup.sh）、安全基线。

#### Changed

- **server 容器降权运行**：镜像内新建 `appuser`（uid 1000）并以 `USER appuser` 启动；
  compose 叠加 `cap_drop: ALL` + `no-new-privileges`（应用无本地写盘、绑非特权端口 8000，已核验）；
  tls-init 一次性服务覆写 `user: "0"`（需写宿主机证书 bind mount）。
- **容器加固基线**：全员 `security_opt: no-new-privileges:true`；postgres/emqx 保留官方镜像
  所需能力集不动。
- **自定义 bridge 网络** `webscada-net` 显式声明（此前隐式 default 网络），服务名 DNS 语义不变。
- **restart 策略** `always` → `unless-stopped`（宿主机重启不再拉起运维手动停下的服务）。
- server 增加 `stop_grace_period: 30s`（WS 长连接优雅排空）。
- `web/Dockerfile` 锁文件 `package-lock.json*` 可选匹配改为强制存在（npm ci 本就硬依赖锁文件）。

#### Security

- **根 .dockerignore 收紧**：排除 `deploy/certs`（私钥严禁进镜像/上下文）、参考仓库 `github/`、
  `backup*`/`backups`/`artifacts` 历史产物、`.claude`/`.agents`、`LICENSE` 等。


### M9 批次2-5：资产库 / 模板 / 表达式 / 移动端（对标 BY组态，2026-10-21）

#### Added

- **我的图元**：画布选中（可多选/成组）→ 右键「存为我的图元」或面板按钮 → `doc.assets.mySymbols`
  （展平 + 坐标归一化），「我的」Tab 缩略渲染（静态平铺，无引擎依赖），拖入/点击克隆插入（id 重映射）。
- **画面装饰**：`title-bar` 标题栏组件（text/align，颜色走 style.color）+ symbol 资产 decor 分类 7 件
  （科技边框/四角边框/容器框/状态底栏/分隔线/点阵底纹/弧光角饰）。
- **画面模板**：面板「模板」Tab 一键新建整页，4 个静态占位模板（大屏总览/单线图框架/双栏控制面板/
  移动端竖屏），复用 demos 工厂（`utils/pageTemplates/`）。
- **组件面板五 Tab 化**：组件 / 图元库 / 装饰 / 模板 / 我的（对标 BY 左侧面板形态）。
- **表达式函数库扩容**（双端同构）：sin/cos/tan/asin/acos/atan/atan2/exp/log/clamp/sign，
  Python 侧逐条对齐 JS 语义（log(0)=-inf、asin(2)=NaN、exp 溢出=inf…），同构测试 5 组新增。
- **内置秒节拍 `_tick`**：虚拟变量 expr / 条件弹框表达式引用即每秒重算（定时脚本等价物）；
  服务端 hub 注册哨兵变量 + runtime_boot 每秒推进（广播 + 级联），本地模式引擎定时器推进。
- **画面方向强制**：`ScreenCfg.orientation`（auto/landscape/portrait），运行态视口方向不符时页面
  rotate(90°)（外层占位互换，自适应按旋转后视口计算）；PropPanel 页面设置新增下拉。
- **渲染密度基准**：`docs/assessment/render-bench.md`（复用 M7 stressDoc 1100 组件工程，
  Playwright 测量方法与通过线，回应 BY「1100 组件加载测试」卖点）。

#### Changed

- 拖放协议三形态：纯 type / `symbol|<symbolId>` / `mysym|<资产id>`；`addComponent` 增第四参 extraProps。
- 契约 02 §8 扩充（8.2-8.6）；`assets`/`orientation` 均为可选字段，**schemaVersion 保持 1**
  （遵循 §7 全量可选字段先例，不为纯增量制造迁移窗口）。

### M9 批次1：行业图元库（对标 BY组态「图元图库」，2026-10-21）

#### Added

- **symbol 通用图元组件**：一个 WidgetType 承载全部行业图元 SVG，颜色走 `style.color`
  → `--dev-color`（与设备类同通道，color 绑定/报警态驱动变色）。
- **自绘 SVG 资产库** `web/src/assets/symbols/`：9 大类（阀门/泵类/罐体/暖通风/管件/
  水处理/电力/仪表/其他）首批 **68 个全自绘**简笔工业风图元（版权红线：不引入第三方素材）；
  `import.meta.glob` eager 收集，新增 SVG 文件零代码注册，中文名登记 `NAME_MAP`。
- **组件面板 Tab 化**：「组件 / 图元库」双 Tab；图元库支持关键词搜索 + 分类过滤，
  SVG 缩略预览，拖拽/点击放置（拖放协议支持复合载荷 `symbol|<symbolId>`）。
- 契约：`WidgetType` +`'symbol'`（docs/design/02 §8，双端同步，schemaVersion 不变）。

#### Changed

- README 功能矩阵修正 4 处 M8 已交付但仍标「缺失/改造中」的滞后口径
  （Modbus TCP、迁移三件套、报警 ack+通知、服务端采集/historian/RBAC）。


### 评审基线

- 依据 `docs/assessment/commercial-readiness-2026-10-20.md`：阶段裁定 `internal-pilot`，
  综合成熟度 2.2/5；本版本起按「阶段 0 止血合法化 → 阶段 1 服务端闭环」路线推进。

### Added

- **LICENSE**：采用 AGPL-3.0（防云厂商闭源白嫖、划定企业版商业边界）。
- **NOTICE.md**：版权声明 + 开源核心/企业版双授权边界说明（企业版能力目前均为规划中）。
- **CI**：`.github/workflows/ci.yml` —— server job（PostgreSQL 16 service container +
  `pip install -e ".[dev]"` + alembic upgrade head 迁移冒烟 + pytest）、
  web job（npm ci + vue-tsc --noEmit + vite build）。
- **备份恢复**：`scripts/backup.sh`（pg_dump 整库 + 工程 JSON JSONL 导出 + 保留期清理）、
  `scripts/restore.sh`（交互确认整库恢复 + 健康检查 + 行数校验）、
  `docs/operations/backup-restore.md`（操作手册与月度恢复演练要求）。
- **TLS**：nginx 443 server 块（TLS 1.2/1.3），证书挂载 `./deploy/certs`；
  `scripts/gen-selfsigned-cert.sh` 自签生成脚本；compose 新增 tls-init 一次性服务
  （证书缺失时自动补齐自签证书）；80 端口保留并附升级指引注释。
- **EMQX 收口**：`EMQX_MQTT__ALLOW_ANONYMOUS=false` 禁匿名（写死，无旁路）；
  8083/18083 端口仅绑定 `127.0.0.1`；新增 emqx-authn-init 一次性服务经 Management API
  写入默认 MQTT 账号（`EMQX_DEFAULT_USERNAME/PASSWORD`，幂等）。

- **前端 UI 优化包（2026-10-21）**：
  - 台账卡片视图：表格/卡片双模式切换（选择持久化）；编辑器保存前自动截取首页画面
    存 `doc.project.thumbnail`（320px JPEG），列表端点按需读出；导出/分享出口统一剔除该字段。
  - 编辑器多选批量编辑：属性面板多选态支持几何同值覆盖、显隐/锁定整体设定、
    文字色/填充/字号/对齐批量应用（单条 undo 覆盖全部选中项）；补齐 Ctrl+A 全选快捷键。
  - 运行态全屏按钮（RuntimeStage 标题栏，大屏值班场景）；分享页失败态重试按钮。
  - 首屏品牌 splash（index.html 内联，JS 就绪前消除白屏）；编辑器/分享页统一 `ws-spinner` 加载指示。
  - 版本号构建期注入（`__APP_VERSION__`，取 package.json），替代登录页脚硬编码。
  - 主题：未做过选择时跟随系统 `prefers-color-scheme`（深色偏好 → graphite）；
    `theme-color` meta 随主题切换同步。

- **样式令牌化与可访问性（2026-10-21）**：
  - 主题派生层（`theme.ts` applyTheme 按主题计算写入）：深底反白分档 `--ws-inv-*`、
    信号/警示透明底 `--ws-signal-a*` / `--ws-alert-a*` / `--ws-warn-a*`、深底状态灯
    `--ws-{ok,warn,alert}-bright`（逐主题手调）、`--ws-ink-edge` 等；清除界面层跨主题
    硬编码（此前切普鲁士蓝/机械绿/铜排时，hover 底、状态灯、报警徽标仍为电气青/固定色）。
  - 深底幽灵按钮收敛为全局 `.ws-ghost-btn`（配色选择器/台账/编辑器/管理页共用，
    替代 4 处重复定义）；半透明白 8 档收敛为 6 档令牌；字号归整（去 11.5/12.5px）。
  - 图表组件默认样式收敛至 `web/src/widgets/chart/shared.ts`（CHART/AXIS/TITLE_STYLE/
    PALETTE，4 处 AXIS 重复定义合一）；widget 画布默认色统一（去 #2563eb/#38bdf8/#22c55e
    等体系外杂色，画布内容仍不随 UI 主题）。

### Fixed

- 工程台账分页器旁误渲染孤立 `/>` 文本（ProjectsView 模板多余闭合符）。
- 分享页加载/错误态残留旧深色背景（与全站浅色工业主题不一致，且文字对比度不足）。
- 登录页预填 `admin` 用户名（向访客暴露默认管理员账号）。
- 运行态服务提示引用从未定义的 `--ws-signal-amber/--ws-signal-red`（恒走 Tailwind 回退色）。
- 浅色 4 套主题 `--ws-text-3` 白底对比度约 3.1:1，调深至 ≥4.5:1（WCAG AA，12px 辅助正文）。

### Changed
- **README.md** 全面重写：功能矩阵诚实区分「已实现 / 服务端闭环改造中」、架构 mermaid 图、
  含 EMQX 鉴权与 TLS 的快速开始、默认账号与安全提醒、已知限制清单、路线图（internal-pilot）。
- docker-compose.yml：nginx 配置改为卷挂载（改 conf 免重建镜像）；EMQX 8083 收口至回环地址。

### ⚠ 破坏性 / 升级注意

- **EMQX 禁匿名后，匿名 MQTT 数据源与未配置凭证的浏览器直连数据源将无法建连**——
  属预期收口；请在 EMQX 管理台（本机 18083）按需创建专用账号，或等待服务端采集闭环
  （阶段 1）后统一切服务端接入。
- 服务端对 `schemaVersion` 为硬等值校验且迁移三件套（migrateDoc / N-1 窗口 / 自动备份）
  未落地：**存量工程文件跨版本导入导出能力冻结**，`CURRENT_SCHEMA_VERSION` 维持 1。

### 进行中（服务端闭环，见 README 路线图阶段 1）

- 服务端采集引擎（MQTT → Modbus）与数据源凭证注回通道
- 服务端 7x24 报警判定、ack 状态流转、通知外发（邮件/Webhook）
- 服务端 historian 历史入库与区间查询（替代浏览器 localStorage 分钟桶）
- RBAC 用户管理、操作审计日志
- REST 限流真实落地、JWT 弱密钥 fail-fast、迁移三件套

## [0.7.0] — 2026-10-20（M7）

### Added

- 全站浅色工业仪表主题（theme.css 设计令牌体系），替代默认蓝色系。
- 19 种新组件（组件注册总数达 39 种）。
- 运行态动作与交互：开关/多档/输入框指令、事件 writeVar 反控写（变量须显式
  `writable=true`；分享页恒只读）；浏览器直连数据源反控（mqtt publish / rest POST /
  ws send / mock 回环）。
- 50 步撤销历史覆盖扩展；跨页复制粘贴。

## [0.6.0] — 2026-10-20（M1.5–M6）

### Added

- 编辑器交互重构：拖放/对齐吸附/框选/旋转感知（移植自 visual-drag-demo，MIT，见
  THIRD_PARTY_NOTICES.md）、20 种组件。
- 变量与数据接入（M3）：MQTT / REST 轮询 / WebSocket / Mock 四类数据源、
  数据源凭证 Fernet 加密存储与出口脱敏。
- 绑定与运行态引擎（M4）：数值/颜色/显隐三类绑定、换算流水（bitIndex → scale/offset →
  precision）、WS 推送（snapshot/values/alarm/alarmClear 帧、100ms 合帧、心跳判死）。
- 报警（M5）：阈值/回差/持续时间规则、报警记录入库与浏览器端展示。
- 发布分享（M6）：分享链接 + 冻结脱敏快照（share_links.doc_snapshot）、
  分享运行态独立 WS 配额。

### Security

- JWT 登录锁定（失败 5 次锁 60s）、jti 黑名单（进程内）、WS 连接配额（分享/用户两维度）。

## [0.1.0] — 2026-10-20（M0 + M1）

### Added

- 部署底座：docker-compose 四容器（nginx / server / postgres / emqx）、
  健康检查依赖链、entrypoint 等库就绪重试。
- 登录鉴权：JWT（HS256）、管理员幂等初始化（ADMIN_USER/ADMIN_PASSWORD）。
- 工程 CRUD：乐观锁（revision + baseRevision，409 REVISION_CONFLICT）、
  导入导出（数据源凭证脱敏）、ProjectDoc 契约校验（422 结构化错误）。
- Alembic 迁移：users / projects / share_links / alarm_records。
- 画布编辑器核心（M1）：画布、图元基础编辑、页面管理。

[Unreleased]: https://example.invalid/webScada/compare/v0.7.0...HEAD
[0.7.0]: https://example.invalid/webScada/compare/v0.6.0...v0.7.0
[0.6.0]: https://example.invalid/webScada/compare/v0.1.0...v0.6.0
[0.1.0]: https://example.invalid/webScada/releases/tag/v0.1.0
