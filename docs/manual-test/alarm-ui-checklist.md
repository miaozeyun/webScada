# M8 工作包 D · 前端报警呈现手测清单

> 范围：AlarmPanel / AlarmBanner / WidgetHost 报警态（S2） / HistoryChartWidget 服务端历史。
> 契约依据：`docs/implementation/server-closed-loop-plan.md` §4.1、§4.2、§5、§9-D；`docs/design/02` §2.11/§2.12。
> 自动化说明：本包不装任何 npm 依赖（vitest 由 F 包统一引入），故以本清单人工验收。

## 0. 环境准备

- [ ] 服务端就绪：仓库根目录 `docker compose up -d`（PostgreSQL + server），`alembic upgrade head` 已执行（0002 状态机列存在）。
- [ ] 前端就绪：`web/` 下 `npm run dev`（入口端口见仓库 README；默认 Vite 端口）。
- [ ] 账号三件套：admin（初始）；operator、viewer 经「用户管理」（E 包页面）或 `POST /api/v1/users` 预建。
- [ ] 演示工程：新建 mock 工程，配置 1 个 number 变量（key 如 `temp_01`，sine 模拟覆盖阈值两侧），报警规则 `temp_01 > 80`（level=critical）、`temp_01 < 5`（level=info），并给某组件（如 rect/var-display）绑定该变量的 `style.fill` color 映射（S1 通道）与一条 value 绑定。
- [ ] 记下工程 id（列表 URL 或 GET /api/v1/projects 返回值），后续用 `<projectId>` 指代。

## 1. 挂接说明（宿主集成前的临时手测法）

宿主挂接由 A 包（RuntimeStage / ShareView）在集成阶段完成。A 包就绪前，可临时在任意既有视图挂载验证：

```vue
<AlarmPanel :project-id="projectId" />
<AlarmBanner :project-id="projectId" />
```

- AlarmPanel 建议放入 `el-drawer` / 侧栏容器（组件自身只管内容，不含外层布局）。
- AlarmBanner 建议置于运行画面上方（深色横幅，无报警时整组件不渲染）。
- WidgetHost / HistoryChartWidget 无需挂接，运行预览即生效。

## 2. AlarmPanel 报警列表（契约 §4.1）

- [ ] **加载**：以 admin 登录打开面板，能列出报警行，触发时间倒序；总条数与分页 total 一致。
- [ ] **缺省过滤**：初始勾选「触发/已确认」，不显示「已恢复」行；清空状态下拉后回服务端缺省口径（未恢复集合）。
- [ ] **状态过滤**：单勾「已恢复」只出 cleared 行。
- [ ] **级别过滤**：level=critical 只出严重行。
- [ ] **变量前缀过滤**：输入 `temp` 出 `temp_01`；输入不匹配前缀出空表（无报错）。
- [ ] **时间区间过滤**：选最近 1 小时，出区间内行；选未来时间出空表。
- [ ] **分页**：size 切换 20/50/100 生效；翻页后过滤器保持；单页内数据不重复不遗漏。
- [ ] **输入防抖**：变量前缀连续输入不逐键发请求（Network 面板观察 ≤1 次/300ms）。

## 3. 未知 status 灰显兜底（契约 §11.8 存量兼容）

- [ ] 人工构造未知状态行（服务端库内把某行 status 改为任意串，如 `psql -c "UPDATE alarm_records SET status='weird' WHERE id=<id>"`）。
- [ ] 面板刷新后该行状态标签显示「weird（未知）」且为灰色（plain 形态），不报错、不吞行；级别列同理（可另行改 level 值验证「x（未知）」灰标签）。

## 4. ack 角色矩阵（契约 §4.1）

- [ ] **admin**：触发行显示「确认」按钮；填写说明（可留空）后成功，行内出现确认信息（操作人/时间/说明），状态变「已确认」。
- [ ] **operator**：同样可见并确认成功。
- [ ] **viewer**：操作列整列隐藏，无法触发确认。
- [ ] **未登录（分享页挂接场景）**：无确认按钮。
- [ ] **cleared 补确认**：对已恢复且未确认的行显示「补确认」，成功后状态保持「已恢复」、确认信息补齐（幂等契约）。
- [ ] **幂等**：对已确认行不显示按钮（前端口径：已有 ackedAt 不再出按钮）；如用接口重放，服务端返回当前态不报错。
- [ ] **note 上限**：输入 >256 字符时提示「说明不超过 256 字符」并阻止提交。
- [ ] **403 路径**（可选）：viewer 用浏览器控制台 `fetch` 直接调 ack 接口 → 403 信封。

## 5. alarmAck 帧联动刷新（契约 §5）

- [ ] 双浏览器（或普通+无痕窗口）同登 admin/operator 打开同工程报警面板，均能看到同一条触发报警。
- [ ] 窗口 A 确认该报警 → 窗口 B 面板**无手动刷新**即出现确认信息（联动通道：A 包 server 模式把 alarmAck 帧写入 runtime store 事件流 → 面板静默重查；另有本页 ack 的 `webscada:alarm-acked` DOM 事件兜底）。
- [ ] 同页横幅确认 → 面板同步刷新（反之亦然）。

## 6. AlarmBanner 报警横幅

- [ ] 无活动报警时横幅不渲染，不留空块。
- [ ] 制造 critical + info 两条报警：critical 排前，徽标计数=2，摘要行显示最高级别与消息。
- [ ] 超过 maxShow（默认 3）条时尾部显示「另有 N 条活动报警未展示」。
- [ ] 「收起/展开」切换正常；单条「本屏隐藏」后从横幅消失、计数同步减一。
- [ ] 未知 level 条目（可临时在 store 注入 level='urgent' 的假事件验证）：标签灰显「未知」、条左强调色为安全橙，不白屏不报错。
- [ ] operator/admin 可见快捷「确认」并成功；viewer/未登录（无 projectId）不渲染确认按钮。
- [ ] 报警恢复帧（alarmClear）到达后对应条目消失；全部恢复后横幅整体消失。

## 7. WidgetHost 报警态 S2 > S1 > S0（02 §2.12 唯一实现点）

- [ ] **S2 命中**：绑定变量的报警激活时，组件填充色被覆盖为工程 `settings.alarm.levelColors` 对应级别色，并叠加闪烁动画（周期取组件 blink.intervalMs，未配则 1s）。
- [ ] **优先级**：同时配置 S1 color 映射（enum/range）的组件，报警期显示报警色而非映射色；恢复后自动回落 S1 映射色；无绑定时回落 S0 静态填充色。
- [ ] **多报警取最高**：同组件绑定变量上两条不同级别报警并存时，显示 critical 色。
- [ ] **编辑态零影响**：编辑器画布（运行未启动）不闪烁不变色。
- [ ] **visibility 优先**：组件 visibility 绑定求值为隐藏时，报警态不得使其出现（显隐由 PreviewNode 覆盖层决定）。
- [ ] **分享页**：本地引擎事件形态下（无 doc 反查时该路径退化）不报错；A 包 server 模式帧携带 variableKey 后，分享页同样呈现 S2。

## 8. HistoryChartWidget 服务端历史（契约 §4.2）

- [ ] **服务端曲线**：运行 5 分钟后打开历史图，能拉到 `/projects/{id}/history` 返回的曲线（Network 面板确认请求参数含 `keys=<变量key>&from&to&stepMs&maxPoints=500`，from/to 为 ISO8601 UTC）。
- [ ] **stepMs 联动 range**：切 1h/6h/24h/3d，请求中 stepMs 分别约 18s/108s/432s/1296s（=range/200，下限 1000ms），即范围越大步长越大。
- [ ] **30s 自动刷新**：曲线随时间推进自动补新点。
- [ ] **回落本地缓冲**：停掉 server（`docker compose stop server`）后 30s 内图表亮左上角「本地缓存」角标，曲线降级为本地分钟桶数据，无未捕获异常；server 恢复后角标消失、回到服务端数据。
- [ ] **未配置变量**：不发起请求，显示空态文案。
- [ ] **live 迷你图**（组件属性 live=true）：行为与 M7 一致（引擎内存序列，不经服务端）。

## 9. 分享页通道（与 A 包集成联调）

- [ ] A 包宿主调用 `setHistoryProjectId(id)` + `setHistoryShareToken(token)` 后，分享页历史图请求头为 `Authorization: Bearer <shareToken>` 并成功返回曲线。
- [ ] 分享页报警面板/横幅无 ack 按钮（未登录角色=null）。
- [ ] 未注入两参数的旧分享页：历史图不发 `/history` 请求（直接本地缓冲），不出现 401 弹窗。

## 10. 回归

- [ ] `cd web && npx vue-tsc --noEmit` 零错误（D 包交付时全量即绿）。
- [ ] 报警规则触发/恢复、提示音、右上角徽标等 M5/M7 既有行为不受影响（前端引擎路径仍可用；A 包切 server 模式后以服务端判定为准）。
- [ ] `POST /projects/{id}/alarm-records` 旧上报不再被 M8 前端主动调用（`api/alarms.ts` 中该函数仅作 A 包改造期的编译兼容，标 @deprecated；集成阶段随 RuntimeStage 调用点一并删除）。
