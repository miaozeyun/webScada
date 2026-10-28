# Changelog

webScada 的所有显著变更记录在本文件。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)（0.x 阶段不含兼容性承诺）。

## [Unreleased] — 运维与法务文档包 + 服务端闭环改造（进行中）

### 生产可用性评审修复（2026-10-26）

> 来源：六位专家 + 事实核查 + 红队复核的产品评审（结论：报警链路与分享页可观测性是交付级断点）。

#### Added

- **报警呈现接入运行态**：`AlarmBanner` / `AlarmPanel` 此前已实现但全仓无宿主，运行大屏只有
  4.5s 弹窗。现于 `RuntimeStage` 挂载横幅（编辑预览可 ack，分享页只读），顶栏 `⚠` 改为
  **未确认**计数并可点开面板；顺带接线 `setAlarmLevelColors`（此前无调用者，级别色配置不生效）。
- **报警中心页 `/projects/:id/alarms`**：复用 AlarmPanel，支持状态/级别/变量/时间过滤与 ack；
  台账行菜单「报警记录」进入，交接班可查遗留报警。
- **人工清除报警** `POST /projects/{id}/alarms/{alarmId}/clear`（operator/admin，审计
  `alarm_clear`）：清理规则已变更/设备已拆除等永不自动恢复的残留报警。
- **通知投递记录** `GET /projects/{id}/notifications/deliveries`（operator/admin）：
  sent/pending/sending/dead 全量可查，渠道只回显 host；成功发送也落一条 sent 记录（此前
  outbox 只存失败行，无法回答「到底发出去没有」）。编辑器「通知」页新增最近投递表。
- **数据源运行健康** `GET /projects/{id}/datasources/status`：数据源表新增 在线/断线、
  最后收数、错误 列（collector 进程内状态，5s 轮询）。
- **变量实时值**：变量表新增「当前值 / 质量」列，复用已有 `GET /projects/{id}/variables/values`
  （此前前端零调用者）。
- **分享发布管理对话框**：列出已有链接（创建/刷新/最近访问/有效期），支持复制、打开、刷新快照、
  撤销；新建默认 **30 天**有效期（可选 7/90/天或永久）；`refreshedAt` 落后于工程 `updatedAt`
  时提示「有未发布变更」。
- **分享快照最小投影**：匿名快照剔除数据源连接配置（PLC host/port、broker、endpoint）、
  `settings.notify`（URL 内含 access_token）、变量寄存器/写地址、演示说明节点（`demoNote`）。
- **`PUBLIC_BASE_URL` 配置**：服务端生成分享 URL 优先使用；nginx `Host` 改 `$http_host`
  （`$host` 丢端口，非 80/443 部署会生成打不开的链接）。
- **台账批量删除**：表格多选 + 二次确认；「生成压测工程」收进 `?dev=1` 开发者开关。
- **低分辨率检查 / 窄屏拦截 / 预览只读**：画布属性新增「按 1366×768 检查」；编辑器 <1024px
  显示明确拦截页而非挤坏的界面；预览默认只读并提供「允许控制」显式解锁（反控写真实设备前确认）。
- **报警规则「试判定」**：用当前变量值做一次阈值判断（不落库、不外发），并展示质量状态。

#### Fixed

- **规则删除/停用后残留活动报警不清理**：保存 doc 时按启用规则集合差集收口（`sys_comm:` 系统
  报警除外，避免误清通讯中断）；启动 sweep 之外的这条主要路径补齐。
- **坏质量不清工艺报警**：`rules_engine` 在 `q != good` 时对该变量的活动报警自动收口（去重，
  值恢复 good 后可再次触发），修复「拔网线后报警永远挂着」。
- **报警音永远不响**：`soundEnabled` / 规则级 `sound` 此前无消费点；新增首次手势解锁
  AudioContext、未确认报警持续提醒（按 `soundThrottleSec` 节流），ack 后提醒自然停止。
- **分享页断线静默冻结**：chromeless 无顶栏导致断线提示不可见；现叠加断线/停更提示
  （15s 无值帧或浏览器离线），显示最后更新时间。
- **分享页多页面无法翻页 / 手机竖屏缩成一条**：新增底部悬浮页签条与「请横屏查看」提示
  （可关闭，尊重页面 `orientation` 配置）。
- **演示说明污染交付画面**：`demoNote` 节点在分享快照中剔除（需重新生成/保存演示工程后生效）。
- **版本漂移**：`package.json` / `pyproject.toml` 统一为 `0.2.0`（与 `APP_VERSION` 一致）。
- **viewer 可进编辑器**：`/editor`、`/simulator` 增加角色守卫，避免编辑到保存才 403。
- **部署脚本 `Permission denied`**：`scripts/*.sh`、`deploy/*.sh` 在 Git 索引中误存为 `100644`，
  clone/pull 后 `deploy.sh` 调用 `./scripts/backup.sh` 直接失败中止升级。全部脚本改标 `100755`，
  脚本间互调统一经 `bash` 显式执行，`deploy.sh` 启动时自愈 `chmod +x scripts/*.sh`。
- **`--admin-password` 对已有部署无效**：仅写 `.env`，而 `create_admin.py` 幂等不覆盖存量管理员，
  登录仍用旧密码。改为升级路径下同时调用新增的 `server/scripts/reset_admin_password.py` 重置库内哈希；
  口令下限放宽到 6 位（演示环境 `123456`，正式部署仍建议 ≥16 位随机值）。

#### Changed

- 报警持续时长表单改为**按秒**输入（存储仍为 `durationMs`）；规则表补 启用/持续/回差 列。
- 属性面板绑定目标改用业务名（「读数」「颜色」「显示/隐藏」…），绑定区上移至样式之前。
- 分享 API 出参新增 `refreshedAt`（Alembic 0005，历史行回填为 `created_at`）。

### 实时数据仿真台（2026-10-26）

#### Added

- **实时数据仿真台（`/simulator`）**：选工程后在前端构造仿真副本 doc（只保留一个 mock 数据源，
  基础变量改挂并置空 scale/offset/bitIndex，虚拟变量保留表达式），右侧以 `RuntimeStage` 嵌入模式
  本地渲染该工程画面；仿真值经新增 `RuntimeEngine.injectValue()` 按工程值口径入池，绑定求值、
  报警判定、虚拟变量级联、反控回环全部走真实运行态链路。左侧信号面板支持逐变量波形（正弦/
  斜坡/随机/方波/手动固定）、量程与周期调整、暂停/倍速/重置及手动注入，底部为实时趋势（最多
  8 条）。全程不写工程 doc（台账 revision 不变）也不连接真实设备；入口为工程台账「实时仿真」
  与编辑器工具条「仿真」（有未保存修改时先保存，保证仿真的是当前画面）。

### 体验 / 性能 / 样式优化（2026-10-26）

#### Changed

- **统一控制台顶栏**：抽出 `AppBar.vue`，工程台账 / 报警中心 / 仿真台 / 用户管理 / 审计日志
  共用 48px 顶栏与同一套主题令牌；报警中心此前 52px 的漂移一并修正，窄屏折叠规则收敛。
- **报警中心自动刷新**：独立报警页没有运行态引擎，补 15s 轮询（页面隐藏暂停）与「自动刷新 ·
  上次更新时间」提示；轮询失败不再每轮弹 toast，改为页内「自动刷新失败」提示；WS 触发的
  静默刷新改为 600ms 合帧，并加请求序号防旧响应覆盖新结果。
- **仿真台体验**：空格暂停/继续、R 重置；顶栏「在编辑器中打开」；工程下拉支持远程搜索
  （台账超过 100 条也能找到）；单屏 200 行上限与「另有 N 条」提示；载入工程时显示遮罩；
  仿真报警改静默（横幅/徽标保留，不再被弹窗遮住画面）；文本量禁用无意义的波形选择。
- **分享管理**：有未发布变更时提供「全部刷新」；对话框按 94vw 自适应，列宽重排修复操作按钮
  被裁；新建链接复制与列表同口径（`location.origin`），不再受反代 Host 配置影响。
- **编辑器报警入口**：数据抽屉「报警」页签新增「报警中心」按钮（有脏改动先落库）。

#### Fixed

- **仿真台组件报警态不渲染**：本地引擎报警事件补 `variableKey`/`ruleId`，与服务端帧同构，
  `WidgetHost` S2 报警色/闪烁在仿真台与分享页一致生效。
- **报警角色缓存跨账号泄漏**：`api/alarms.fetchMyRole` 缓存绑定 token、并发单飞、失败可重试；
  换账号（不刷新页面）不再沿用上一账号角色。
- **报警横幅「本屏隐藏」集合无界增长**：报警恢复后自动清理。

#### Performance

- **ECharts 增量更新**：结构不变时合并 option（保留过渡动画，仪表盘指针不再逐帧跳动），
  仅 series 数量/组件集合/轴类型变化时全量重建。
- **大依赖按需加载**：`html2canvas`（首次截图）与 `mqtt`（首次直连 MQTT / 连接测试）改为动态
  `import()`，编辑器/分享页首屏不再背约 546KB。
- **仿真台趋势有界**：主趋势只记实际绘制的 ≤8 条，sparkline 改 1Hz 预计算、渲染期查表；
  后台标签页暂停仿真时钟。
- **服务端值帧广播**：同一帧只序列化一次，各连接并发发送（连接级锁保序），慢客户端不再
  串行拖住同工程其他大屏。

### 工厂可用阶段二「用得顺手」：OPC UA + 历史聚合/导出 + 数据表格 + 工程级通知 + 免重登（2026-10-22）

#### Added

- **历史聚合扩展**：`GET /projects/{id}/history` 增 `agg` 参数（mean/min/max/last/sum，缺省 mean），
  服务端窗口聚合按所选口径取值（last=桶内末点、sum=桶内求和）；历史图表属性面板新增聚合下拉
  （props `agg` 纯增量，旧工程不受影响）。
- **历史 CSV 导出**：`GET /projects/{id}/history/export?key&from&to` 单变量原始行流式导出——
  keyset 分页（5000 行/页循环迭代，不整载、无行数上限），列 `ts,value`（ISO8601 + 原始工程值），
  跨度 ≤30 天，JWT/分享 token 双通道鉴权，限流与查询端点同额；属性面板历史图表/趋势图工具条
  增导出按钮。30 天 ×5s ≈ 51.8 万行实测流式导出完整可解析。
- **操作员免重登（refresh token）**：登录页「记住我 7 天」，rememberMe 登录签发 refresh
  （sha256 落库，Alembic 0003）；`POST /auth/refresh` 一次性轮换（旧 token 吊销 + 新对），
  复用已轮换 token 判定泄露重放并吊销该用户全部 refresh；登出/改密一并切断 refresh；前端
  http.ts 401 拦截器单飞刷新（并发请求排队共享同一次刷新，失败才登出）后重放原请求。
- **通知渠道落工程 doc**：`doc.settings.notify.channels` 四渠道（webhook/钉钉/企微/邮件，按
  kind 判别 + 渠道级 minLevel 过滤），沿 G14 存 doc 无独立端点；钉钉 secret Fernet 加密、
  出口统一脱敏、PUT 空值合并（空串=保留/null=清除）；工程配置优先、无配置回落 env 单渠道，
  按工程缓存（保存/导入/删除即时失效 + 5s TTL 兜底）；网络类异常重试 3 次（1s/2s/4s 指数
  退避，HTTP 4xx 不重试）；数据抽屉新增「通知」渠道 CRUD 表单。
- **钉钉/企微发送实现**：钉钉毫秒时间戳 + `\n` 拼接 secret 以 HMAC-SHA256 base64 加签
  （固定向量单测钉死时序与 percent-encode），text 消息；企微 markdown 消息无签名；真实群
  推送冒烟列入人工清单（需现场机器人 URL）。
- **实时/历史表格组件**：`realtime-table`（columns=变量列 JSON，列内显式 precision/unit
  ——分享页无变量定义回落时仍可格式化；质量位非 good 灰显、报警行警示色，theme.css 令牌）
  与 `history-table`（variableKey 存变量 id 经 doc/runtime 反查，rangeMs 1h/6h/24h ×
  bucketCount 区间桶末值快照，60s 定时刷新、卸载清定时器）；行构造纯函数 tableRows.ts 与
  组件解耦。
- **OPC UA 第六数据源**：asyncua 订阅推送型采集源（address=nodeId 字符串，DataChange 订阅，
  断线指数退避、重连后重建全部订阅；write=set_value 走 writable 管线；凭证加密脱敏沿 MQTT
  口径）；`POST /datasources/opcua/browse` 子节点浏览（operator+，落审计）；compose sim
  profile 新增 `sim-opcua`（ns=2 demo.temp/press/state，temp 周期变化）。实装 asyncua 2.1.0
  与旧文档五处偏差已留档（docs/经验教训.md）。
- **阶段验收（门禁）**：报警触发后 0.07s 到达 webhook 接收器（阈值 30s，TLS 接收器 + 容器
  CA 注入实测）；30 天 518,400 行合成数据 CSV 经 nginx 流式导出完整解析（首尾时间戳/步长
  断言）；refresh 链路 API 级验证（过期 access 401 → 刷新换新对 → 业务 200，复用旧 refresh
  401 且同族全吊销）；`scripts/seed_demo.py` 演示工程增实时/历史表格组件与 `--notify-webhook`
  渠道参数（幂等判定扩展到组件与渠道一致性）。

### 工厂可用阶段一「接得进来」：Modbus 深化 + MQTT 通配修复 + 点位 CSV 导入 + 仿真验证台（2026-10-22）

#### Added

- **Modbus 16/32 位编解码与批量读**：变量级契约字段 `modbusDataType`（int16/uint16/int32/uint32/float32）、
  `modbusByteOrder`（ABCD/CDAB/BADC/DCBA）、`unitId`（doc.ts ↔ doc.py 双侧同步，均缺省安全）；采集端按
  (unitId, 区) 分组合并读（相邻间隙 ≤2 合并、单组 ≤120 字/1000 位），500 连续点位仅需 5 组请求；
  反控写支持 32 位多寄存器编码（float32/int32 写入）。
- **点位 CSV 批量导入**：数据抽屉变量表新增「导入 CSV」——17 列表头解析（容忍 BOM/CRLF/引号包裹字段）、
  前 20 行预览与错误行全量提示、与既有变量重复 key 自动跳过并计数。
- **仿真验证台（compose sim profile）**：`sim-modbus`（Modbus TCP 从站：秒计数正弦区 + 23.5/ABCD、
  88.0/CDAB 双字节序 float32、int32=-123456、线圈，及 512 字零值区）与 `sim-mqtt-gateway`
  （line1~line3 温度正弦 + run/press 主题；line1 每 60s 扫过 80，供报警演示）；
  `scripts/seed_demo.py` 幂等建立「仿真演示工程」——双数据源 + 通配变量 + 报警规则 + 演示页，
  `--points N` 批量追加连续点位。阶段端到端验收（WS 帧级）全绿：m_temp=23.5 / m_temp_swap=88.0
  （双字节序）、m_int32=-123456、通配地址 any_run 有值、line1_temp>75 warn 报警 90s 内触发、
  500 点 60s 零「modbus 轮询失败」且值流不堆积。

#### Fixed

- **MQTT 变量地址支持 +/# 通配**：变量 address 改按订阅规则匹配送达主题（`+` 恰匹配一层、`#` 仅末段
  且匹配零或多层，非法 `#` 位置恒不匹配），原先非全等地址的变量永远收不到值。

### 大屏长时运行优化 + 分享页无边框 + 台账缩略图修复（2026-10-21）

#### Changed

- **分享页去掉顶部工具条**：`/s/{token}` 默认无标题栏/页签，画面铺满视口（舞台底色跟随页面底色），
  不出现任何滚动条；右上角保留悬浮「全屏」按钮（`?embed=1` 连按钮也不显示）。多页画面仍可由
  组件事件（switchPage）切换。
- **长时运行开销**：水箱液面波动从 SMIL/SVG transform 改为 HTML 合成层动画（Layout 60/s → 7~14/s）；
  管道流动从 `background-position` 改为 `transform`；`AudioContext` 卸载即关闭；
  已确认报警 id 集合封顶 2000；历史落盘间隔 10s → 60s。

#### Fixed

- **台账缩略图一直为空**：`TitleBarWidget` 的 `color-mix` 让 html2canvas 整页截图抛错（catch 静默），
  且手动保存与 3s 自动保存存在「先落库无缩略图、后 save 因 dirty 已清直接返回」的竞态。
  标题栏改兼容色值、截图失败留痕、保存前清理待触发定时器、`setThumbnail` 标脏。
  修复后卡片视图缩略图正常（320×180 JPEG），旧工程下次保存时自动补齐。

### 图片直传 + 编辑器流畅度 + 画面模板重做（2026-10-21）

#### Added

- **图片/轮播组件直传**：属性面板新增 `ImagePicker`（单图 + 多图轮播），支持本地上传
  （png/jpg/gif/webp，≤5MB，可多选）与 URL 双入口；新增 `POST /api/v1/uploads`（operator/admin，
  按魔数校验，落盘 `UPLOAD_DIR`）与匿名读取 `GET /api/v1/uploads/{name}`（分享页可直接加载）。
  compose 增加 `uploads_data` 命名卷，server 镜像预建 `/app/uploads` 并 chown appuser。
- **画面模板重做**：四套模板（大屏总览/单线图框架/双栏控制面板/移动端竖屏）统一深色 HMI 视觉：
  卡片分组、信号色标题、显式文字色、真实占位读数；单线图补齐母线-回路线缆、CT/PT/变压器/负荷、
  图例与全站遥测；移动端改为 375 宽度可读的卡片式布局。

#### Fixed

- **Delete 偶发删不掉组件**：画布 pointerdown 的 `preventDefault()` 阻止焦点离开属性面板输入框，
  键盘层把 Delete 当作「输入中」吞掉。画布按下/右键现在先收走输入焦点；组内删除后清空选中，
  避免残留幽灵 id；预览/抽屉/帮助/导入等覆盖层打开时画布快捷键整体旁路。
- **拖动/编辑卡顿**：pointermove 改为 rAF 合帧（抬起前 flush 末帧）；手势期间缓存视口矩形避免
  逐事件强制重排；自动保存的缩略图截图节流 30s（手动保存/导出/分享/离开仍即时刷新）；移除缩放坞
  `backdrop-filter`；`setNodeRect` 值未变不写；画布舞台 `will-change: transform`。
- **模板多行文案被压成一行**：text 组件 `ellipsis` 默认 nowrap，模板图例/说明改用显式
  `ellipsis=false` 的多行文本。

### 编辑器交互打磨批次（对标业界最好用编辑器，2026-10-21）

#### Added

- **组内编辑（双击入组）**：双击组进入组编辑上下文（子组件可单独选中/拖拽/缩放/删除/属性编辑/
  行内编辑/组内成组嵌套），Esc 或空白单击逐级退出并保持组选中；图层面板切换为组内成员列表
  （面包屑返回）；锁定组不可进入。Ctrl+A 在组内上下文全选成员。
- **拖动实时读数**：移动显示包围盒 X/Y 坐标、旋转显示角度（字号 1/zoom 屏幕恒定），
  松手即隐；缩放的 W×H 徽标沿用手势路径。
- **Alt+拖动复制**：确认移动瞬间克隆选中集再拖副本（原件留在原地），纯点击零副作用，
  一次拖动仅一条 undo 记录。
- **视口边缘自动平移**：拖动/框选时指针贴边（30px 缓冲）按深入程度持续平移画布（rAF 驱动，
  指针静止也持续），移动/框选实时跟随。
- **拖入放置 ghost**：组件库拖拽经过画布时按默认尺寸（我的图元=成员包围盒）渲染虚线预览框。
- **滚轮平移画布**：无 Ctrl 滚轮/触控板双指平移（Shift=水平；Firefox 行模式归一）。
- **缩放快捷键**：Ctrl+0 = 100%（视口中心锚定）、Ctrl+1 = 适应画布。
- **快捷键帮助**：`?` 键或状态栏提示入口打开三组快捷键表（基础/画布视图/编辑组件）。
- **空画布引导**：空白页面画布中央三步上手提示（不挡交互）。
- **粘贴到此处**：右键空白处以菜单位置为落点粘贴（剪贴板包围盒对齐）；跨上下文粘贴
  自动换算组内相对 ↔ 画布绝对坐标（剪贴板记录来源组原点）。

#### Fixed

- **右键菜单项点击全部失效**（存量缺陷）：window 捕获阶段 pointerdown 提前关闭菜单导致
  click 失去 target 不派发；现排除菜单内点击（`closest('.ws-contextmenu')`）。
- **右键未选中组件弹空白菜单**：现命中未选中组件即单选（已在多选集则保持），空白右键清空
  选中后弹画布菜单（编辑组上下文则退出并选回该组）。
- **模板/历史工程组件缺省字段导致克隆崩溃**：画面模板预置组件缺 `bindings`/`locked`/`z` 等，
  组内克隆（Ctrl+D/粘贴/Alt 拖动）在 `n.bindings.map` 抛 TypeError。新增 `utils/docNormalize.ts`
  在 load/replaceDoc/模板建页/我的图元插入四个入口递归补全缺省字段，消费点 `?? []` 兜底。

#### Changed

- 画布右下角 zoom 徽标移除（与状态栏读数重复）；状态栏快捷键提示改为可点击入口。
- `_cloneWithNewIds`/`pasteClipboard`/`orderSelection`/`groupSelection`/`ungroupSelection`/
  `deleteSelection`/`saveMySymbol` 支持组编辑上下文（children 坐标系、z 归一化泛化
  `normalizeZOf`）；组删空自动消组并退出编辑；undo 快照恢复后校验编辑组仍存在。
- `setNodeRect`/`updateNode`/`updateNodeProps`/`updateNodeStyle`/`commitTextEdit` 查找路径
  改为递归 `findNodeDeep`（组内节点可寻址）。



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


### M9 批次2-5：资产库 / 模板 / 表达式 / 移动端（对标业界主流组态，2026-10-21）

#### Added

- **我的图元**：画布选中（可多选/成组）→ 右键「存为我的图元」或面板按钮 → `doc.assets.mySymbols`
  （展平 + 坐标归一化），「我的」Tab 缩略渲染（静态平铺，无引擎依赖），拖入/点击克隆插入（id 重映射）。
- **画面装饰**：`title-bar` 标题栏组件（text/align，颜色走 style.color）+ symbol 资产 decor 分类 7 件
  （科技边框/四角边框/容器框/状态底栏/分隔线/点阵底纹/弧光角饰）。
- **画面模板**：面板「模板」Tab 一键新建整页，4 个静态占位模板（大屏总览/单线图框架/双栏控制面板/
  移动端竖屏），复用 demos 工厂（`utils/pageTemplates/`）。
- **组件面板五 Tab 化**：组件 / 图元库 / 装饰 / 模板 / 我的（对标业界主流组态左侧面板形态）。
- **表达式函数库扩容**（双端同构）：sin/cos/tan/asin/acos/atan/atan2/exp/log/clamp/sign，
  Python 侧逐条对齐 JS 语义（log(0)=-inf、asin(2)=NaN、exp 溢出=inf…），同构测试 5 组新增。
- **内置秒节拍 `_tick`**：虚拟变量 expr / 条件弹框表达式引用即每秒重算（定时脚本等价物）；
  服务端 hub 注册哨兵变量 + runtime_boot 每秒推进（广播 + 级联），本地模式引擎定时器推进。
- **画面方向强制**：`ScreenCfg.orientation`（auto/landscape/portrait），运行态视口方向不符时页面
  rotate(90°)（外层占位互换，自适应按旋转后视口计算）；PropPanel 页面设置新增下拉。
- **渲染密度基准**：内部《渲染基准测试报告》（复用 M7 stressDoc 1100 组件工程，
  Playwright 测量方法与通过线）。

#### Changed

- 拖放协议三形态：纯 type / `symbol|<symbolId>` / `mysym|<资产id>`；`addComponent` 增第四参 extraProps。
- 契约 02 §8 扩充（8.2-8.6）；`assets`/`orientation` 均为可选字段，**schemaVersion 保持 1**
  （遵循 §7 全量可选字段先例，不为纯增量制造迁移窗口）。

### M9 批次1：行业图元库（对标业界主流组态「图元图库」，2026-10-21）

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

- 依据内部《商用就绪度评审（2026-10-20）》：阶段裁定 `internal-pilot`，
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
