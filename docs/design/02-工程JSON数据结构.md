# 工程 JSON 数据结构与存储映射 —— 专项定稿

> 本文为工程 JSON 契约的最终定稿：前端 `web/src/types/doc.ts` 与服务端 `app/schemas/` 以本文为同构依据；接口清单、实时协议、目录结构由其他专项文档负责，本文仅在交界面处引用。

## 1. 边界与统一口径声明（阅读后文的前提）

以下口径是全文档的前提，与架构、接口清单、实时协议专项共同遵守；组件协议与告警协议文档，实现不得偏离：

1. **换算口径唯一**：`scale/offset/precision/bitIndex` 属于**变量级**换算，由服务端在值入变量总线（hub）**之前**执行。全系统（组件显示、报警阈值、报警消息占位符 `{value}`）统一使用换算后的**工程值**。前端 `binder.ts` 只做表现层映射（颜色/显隐/值映射），**不做算术换算**。
2. **报警阈值口径**：`AlarmRule.threshold` 一律针对工程值配置，与用户在界面看到的数值一致。
3. **载荷格式**：MQTT / REST / WebSocket 三类数据源的载荷**仅支持 UTF-8 JSON**。CSV、十六进制、二进制帧不支持（值标记 `q='bad'`），此为 P0 明确边界（旧网关非 JSON 输出属企业版二期评估项）。
4. **jsonPath 子集**：仅支持点路径 + 数组下标（如 `data.temp`、`list.0.value`），不支持 JSONPath 完整语法与过滤表达式。后端自写点路径解析（约 30 行），不引入第三方 jsonpath 库。
5. **图片资产**：二进制不进 doc——组件图片由编辑器直传 `POST /api/v1/uploads` 落盘（命名卷持久化），doc 只存返回的相对 URL（`/api/v1/uploads/{name}`）；同时兼容外链 URL。读取匿名开放（分享页无登录态）。
6. **浏览器兼容基线**：Chrome / Edge ≥ 90（构建目标 `vite` target `es2020`；**不使用 `structuredClone`**，undo 快照等深拷贝由自写 util 实现）。不承诺 IE 与 Firefox 与旧内核国产浏览器；产线嵌入式一体机部署前须核验内核版本。
7. **MQTT 订阅语义**：P0 固定 `cleanSession=true`、默认 QoS 0，避免重连后 EMQX 回放离线堆积消息造成值跳变与告警误判；QoS 1 仅作为数据源可选项，且 `cleanSession` 恒为 true（配置项存在但导入时强制重置为 true）。
8. **规模上限（验收标尺）**：单机 2C4G、单 worker；≤50 浏览器连接、≤5000 变量、单页 ≤200 组件（软上限，仅提示）、单份 doc 序列化体积 ≤ 1MB 编辑器 UI 告警、> 2MB 服务端 422（`code=doc_too_large`，硬校验）。

---

## 2. 工程 JSON 完整数据结构

存储总原则：整个工程是一份 `ProjectDoc`，存 PostgreSQL `projects.doc JSONB`，保存即全量覆盖 + `revision` 乐观锁（PUT 请求携带 `baseRevision`，与库表 `projects.revision` 不符返回 409 `REVISION_CONFLICT`，成功响应返回新 revision；敏感字段的空值保留合并为唯一例外，见 4.3 规则⑤）。前端 `web/src/types/doc.ts` 与服务端 `app/schemas/` 保持同构定义；`schemaVersion` 迁移由前端 `migrations.ts` 的 `migrateDoc()` 负责（迁移归属的双端边界见 5.3）。

### 2.1 顶层结构与版本

```ts
/** doc 内部 id（页面/组件/变量/绑定/数据源/报警规则）：前端 nanoid 生成；各类 id 的唯一性范围见 2.13 校验契约。
 *  注意：project.id 不属于此类型——它是 UUID，由服务端生成，见 ProjectID。 */
export type ID = string;

/** 工程 id：UUID 格式，由服务端 gen_random_uuid() 生成；与库表 projects.id 一致（保存校验、导入重写，见 2.2、2.13 规则 4） */
export type ProjectID = string;

/** 当前 schema 版本。读取任何 doc 前先执行 migrateDoc 升级到该版本 */
export const CURRENT_SCHEMA_VERSION = 1;

export interface ProjectDoc {
  schemaVersion: number;      // 结构版本，当前固定为 1；导入/读取时先迁移到 CURRENT_SCHEMA_VERSION
  project: ProjectMeta;       // 工程元信息
  settings: ProjectSettings;  // 全局配置
  datasources: DataSource[];  // 数据源定义
  variables: VariableDef[];   // 变量字典
  pages: Page[];              // 页面（含全部组件树）
  alarmRules: AlarmRule[];    // 报警规则（存于 doc，随工程导出导入）
}
```

### 2.2 工程元信息

```ts
export interface ProjectMeta {
  id: ProjectID;       // UUID（服务端生成），与库表 projects.id 一致：保存时服务端校验格式与一致性，
                       // 导入时重写为新库 id（见 5.2 步骤 8 与 2.13 规则 4）
  name: string;        // 工程名（≤128 字符，见 2.13 规则 6）
  description?: string;
  author?: string;     // 创建人用户名（仅记录，不做权限）
  createdAt: string;   // ISO8601
  updatedAt: string;   // 记录更新时间（ISO8601）；不作为乐观锁依据——乐观锁为库表 projects.revision，
                       // PUT 请求携带 baseRevision，不符返回 409 REVISION_CONFLICT（见 4.1、4.2）
}
```

### 2.3 全局配置

```ts
export interface ProjectSettings {
  designSize: { width: number; height: number }; // 新建页面默认设计分辨率，如 1920x1080
  adaptive: AdaptiveMode;                        // 新建页面默认自适应模式
  theme: 'blue-dark' | 'blue-light';             // 蓝色系简洁主题（全局主题基调）
  primaryColor: string;                          // 主题主色，默认 '#2563eb'，组件默认取色来源
  alarm: AlarmSettings;                          // 报警声音/级别设置：存 doc.settings.alarm，随工程 doc 保存（不设独立报警设置端点）
}

/** 报警声音/级别设置（settings.alarm） */
export interface AlarmSettings {
  levelColors: {                                 // 报警三级标准色（报警条、组件报警态、报警列表统一取用）
    info: string;      // 默认 '#3b82f6'
    warn: string;      // 默认 '#f59e0b'
    critical: string;  // 默认 '#ef4444'
  };
  soundEnabled: boolean;                         // 全局报警声音总开关（规则级 sound 为二级开关）
  soundThrottleSec: number;                      // 同一规则提示音节流秒数，默认 60（前端报警条遵守，见 2.11 防风暴契约）
}

/** 五种屏幕自适应（运行态行为，整体容器 transform:scale 实现；与画布编辑缩放无关） */
export type AdaptiveMode =
  | 'fixed'       // 原始像素，不缩放，超出滚动
  | 'fit-width'   // 等比缩放至宽度铺满，纵向滚动
  | 'fit-height'  // 等比缩放至高度铺满，横向滚动
  | 'fit-contain' // 等比整体缩放居中留白（大屏推荐默认）
  | 'stretch';    // X/Y 独立拉伸铺满，允许变形（UI 须标注可能变形）
```

### 2.4 页面

```ts
export interface Page {
  id: ID;                                   // 页面唯一（导入时保留）；分享快照含整份 doc、不单独引用页面 id（长度校验见 2.13 规则 6）
  name: string;
  order: number;                            // 多页切换顺序，越小越前
  background: {
    color: string;                          // 背景色
    image?: string;                         // 背景图外链 URL（P0 不做资源上传）
  };
  screen: {
    designWidth: number;                    // 本页设计分辨率（可与 settings.designSize 不同）
    designHeight: number;
    mode: AdaptiveMode;                     // 本页自适应模式
  };
  components: ComponentNode[];              // 顶层组件节点（组也是节点，见 2.6）
}
```

### 2.5 组件通用结构

```ts
export interface ComponentNode {
  id: ID;                        // 全工程唯一（含组内子组件）
  type: WidgetType;              // 渲染器类型，web/src/widgets/registry.ts 按 type 分发
  name: string;                  // 图层显示名（图层面板可重命名）
  x: number;                     // 设计坐标 X（px，左上角；组内子组件为相对组原点的坐标）
  y: number;
  w: number;                     // 宽（px）
  h: number;
  rotate?: number;               // 旋转角度 deg，顺时针，默认 0（即任务文 rotation）
  z: number;                     // 图层序，大者在上；组整体占一个 z 位（即任务文 zIndex）
  visible?: boolean;             // 默认 true；运行态可被 visibility 绑定覆盖
  locked?: boolean;              // 锁定：画布上不可选中/拖动
  opacity?: number;              // 0~1，默认 1；可被绑定覆盖（路径 opacity）
  props: Record<string, unknown>;// 组件私有属性；schema 由 registry 声明，驱动右侧属性面板
  style?: ComponentStyle;        // 通用外观（可选）；哪些键生效由 registry 按组件声明
  animations?: ComponentAnimations; // 动画配置（可选）；生效范围同样由 registry 声明
  bindings: Binding[];           // 数据绑定；同一 prop 仅允许一条（校验契约见 2.13）
  children?: ComponentNode[];    // 仅 type==='group'；组内子组件，坐标相对组原点
}

/** 通用外观（可选字段；未设置的键回落到组件 props 内置默认值） */
export interface ComponentStyle {
  fill?: string;          // 填充/背景色（设备图元的本体色、图表底色、文本背景）
  stroke?: string;        // 描边色
  strokeWidth?: number;
  borderRadius?: number;
  color?: string;         // 前景/字体色（text 数值色、gauge 读数色等）
  fontSize?: number;
  fontWeight?: number;
  textAlign?: 'left' | 'center' | 'right';
}

/** 动画配置（可选；运行态生效，编辑态静止以便精确编辑） */
export interface ComponentAnimations {
  blink?: { enabled: boolean; intervalMs: number };  // 闪烁：整体 opacity 方波；报警态闪烁优先接管（见 2.12）
  flow?: { enabled: boolean; speed: number };        // 管道流动：stroke-dashoffset 速度 px/s，仅 pipe 生效
  rotate?: { enabled: boolean; clockwise: boolean; periodMs: number }; // 旋转一周时长 ms，仅 motor/pump 生效
}
```

`rotate` 动画的运行态启停规则（实现不得偏离）：组件存在指向 `props.state` 的 value 绑定时，仅当**有效 state 显式等于运行值 1** 时旋转（boolean `true` 按"true 等价 1"折算，见 2.7 pump）；state 为 `0`（停止）或 `2`（故障）**均停转**。**禁止真值判断**——`2` 在 JS 中为真值，按真值判定会让故障态设备持续旋转，违背三态语义。registry 为 motor/pump 声明旋转条件值 `rotateWhen: 1`，渲染器读取该声明而非硬编码。无绑定时按 `enabled` 常转。

```ts
export type WidgetType =
  // 基础类
  | 'text' | 'image' | 'table' | 'button' | 'carousel'
  // 图表类（除 flip-counter 外统一走 ECharts 适配器）
  | 'flip-counter' | 'line-chart' | 'bar-chart' | 'pie-chart'
  | 'gauge' | 'progress' | 'trend-chart'
  // 设备类（SVG：启停变色 / 管道流动 / 闪烁 / 旋转）
  | 'status-light' | 'motor' | 'pump' | 'valve' | 'pipe'
  // M7 增量（对齐业界主流组态，详见 §7）
  | 'var-display' | 'state-text' | 'switch' | 'multi-switch' | 'input-cmd'
  | 'tank' | 'flow-bar' | 'image-switch' | 'web-frame' | 'video'
  | 'weather' | 'clock' | 'history-chart'
  | 'breaker' | 'isolator' | 'ground' | 'ct' | 'pt' | 'transformer'
  // M9 批次1 增量（行业图元，详见 §8）
  | 'symbol'
  // 结构
  | 'group';
```

### 2.6 图层与成组的表达

- **图层**：`z` 字段全局即页面内排序，图层面板按 z 降序显示；置顶/上移/下移即交换 z 值。选中框、对齐参考线均为编辑态覆盖层，不进入 doc。
- **成组**：`type:'group'` 节点通过 `children` 递归持有子组件，普通图元与组**同构**（都满足 `ComponentNode`），渲染器递归渲染。
- 组内坐标为**相对组原点**（组 x/y 为 0 时的局部坐标）；组整体拖拽只改组节点 x/y。
- 组内 `z` 仅在组内比较；组整体在页面中占一个 z 位。
- 解组算法（编辑器行为，不进 doc）：子组件坐标还原为 `组x + 子x`、`组y + 子y`，z 值按原相对顺序在页面 z 序中重新分配连续值。
- 嵌套组 P0 支持（递归结构天然支持），编辑器 UI 对嵌套层级不做限制，undo 快照按页面整页 JSON，天然覆盖嵌套。

### 2.7 三类组件示例（带专属 props）

基础类 `text`：

```ts
const textDemo: ComponentNode = {
  id: 'cmp_title_01',
  type: 'text',
  name: '车间标题',
  x: 40, y: 32, w: 420, h: 56, rotate: 0, z: 1,
  visible: true, locked: false, opacity: 1,
  props: {
    text: '一号产线实时监控',   // 显示文本；可被 value 绑定覆盖
    ellipsis: true,            // 超宽省略
    letterSpacing: 2
  },
  // 背景语义由 fill 承载（见 2.5 ComponentStyle），不存在 background 键
  style: { color: '#e2e8f0', fontSize: 28, fontWeight: 600, textAlign: 'left', fill: 'transparent' },
  animations: {},
  bindings: []
};
```

图表类 `gauge`：

```ts
const gaugeDemo: ComponentNode = {
  id: 'cmp_gauge_01',
  type: 'gauge',
  name: '反应釜温度仪表盘',
  x: 40, y: 120, w: 320, h: 320, z: 2,
  props: {
    value: 0,                  // 被绑定属性：编辑态显示静态演示值，运行态被求值结果覆盖
    min: 0, max: 150,          // 表盘量程；若未设置且绑定变量有 range，则取变量量程
    unit: '°C',                // 读数单位后缀
    splitNumber: 5,            // 刻度分段数
    decimals: 1,               // 读数显示小数位（仅显示层；不参与报警口径，报警用变量级 precision）
    levelBands: [              // 表盘分段色带（静态工艺分段，与绑定色/报警态相互独立）
      { from: 0, to: 80, color: '#22c55e' },
      { from: 80, to: 110, color: '#f59e0b' },
      { from: 110, to: 150, color: '#ef4444' }
    ],
    showValue: true
  },
  style: { color: '#38bdf8' },
  animations: {},
  bindings: [
    { id: 'bnd_g01', prop: 'props.value', variableId: 'var_temp_01', mode: 'value' }
  ]
};
```

设备类 `pump`：

```ts
const pumpDemo: ComponentNode = {
  id: 'cmp_pump_01',
  type: 'pump',
  name: '1号循环泵',
  x: 420, y: 160, w: 120, h: 120, z: 3,
  props: {
    state: 0,                  // 0 停止 / 1 运行 / 2 故障；接受 boolean（true 等价 1）——被绑定属性
    runColor: '#22c55e',       // 内置三态色（state 驱动，未经绑定时使用）
    stopColor: '#64748b',
    faultColor: '#ef4444'
  },
  style: {},
  // state===1（运行）时旋转；0 停止 / 2 故障均停转（见 2.5 启停规则，禁止真值判断）
  animations: { rotate: { enabled: true, clockwise: true, periodMs: 1000 } },
  bindings: [
    { id: 'bnd_p01', prop: 'props.state', variableId: 'var_pump_01', mode: 'value' }
  ]
};
```

三类共用的协议约定：被绑定属性在 `props` 中必有同名键（编辑态显示静态演示值）；registry 声明每个组件可绑定路径清单与类型、以及行为条件值（如 motor/pump 的 `rotateWhen`），属性面板据此渲染绑定表单。

### 2.8 绑定（数值 / 颜色 / 显隐）

```ts
export interface Binding {
  id: ID;
  prop: string;            // 目标路径，语法固定为以下四类之一：
                           //   'props.<key>'   组件私有属性（如 props.value、props.text、props.state）
                           //   'style.<key>'   通用外观键（如 style.fill、style.color）
                           //   'visible'       显隐
                           //   'opacity'       透明度
  variableId: ID;          // 引用 variables[].id
  mode: 'value' | 'color' | 'visibility';  // 绑定类别，决定求值语义与校验规则
  mapping?: ValueMapping;  // 映射规则：color 必填（缺省 → 校验 422）；value/visibility 可选
                           //   （value 缺省=直接赋工程值；visibility 缺省=按真值回退，见下方求值表）
}

/**
 * 映射规则。查表键为变量工程值的字符串化形式：
 *   number  → 十进制字符串（如 '63.8'）；enum 查表常配合变量级 precision 取整后使用
 *   boolean → 'true' / 'false'
 *   string  → 原文
 */
export type ValueMapping =
  | { kind: 'enum';  map: Record<string, string | boolean> }   // 离散值映射，如 {'1':'#22c55e','0':'#64748b'}
  | { kind: 'range'; bands: { min?: number; max?: number; value: string | boolean }[] }; // 数值区间映射，先命中先生效
```

三类绑定求值语义（前端 `binder.ts` 实现，仅映射、无算术换算）：

| mode | 求值结果 | 目标类型校验 | 无映射时 | 无命中时 |
|---|---|---|---|---|
| `value` | 工程值（或 enum 映射后的文本） | 与目标 prop 声明类型一致 | 直接赋工程值 | 直接赋工程值 |
| `color` | 颜色字符串 | 目标必须是颜色类路径（`style.fill/stroke/color`） | 禁止（校验 422，`mapping` 必填） | 保持 style 原值 |
| `visibility` | boolean | 仅允许目标 `visible` | 按真值判断（非 0/true/非空 → 显示） | 保持节点 visible 原值 |

范围校验约定：`range.bands` 按 `min/max` 升序书写，闭开区间 `[min, max)`，最后一档允许缺省 `max` 表示正无穷；求值取第一条命中。

### 2.9 变量字典

```ts
export interface VariableDef {
  id: ID;                  // 绑定与报警规则引用它；全工程唯一（见 2.13 规则 1）
  key: string;             // 工程内唯一、创建后不可改（如 reactor1_temp）；用于日志、报警消息与记录冗余
                           // （触发时快照冗余落 alarm_records.variable_key，长度校验见 2.13 规则 6）
  label: string;           // 显示名（如 "1号反应釜温度"），属性面板/报警消息展示用
  type: 'number' | 'boolean' | 'string';
  unit?: string;           // 工程单位（°C、kPa…），仅显示
  range?: { min: number; max: number };   // 量程：仪表盘/进度条缺省刻度来源，不做数据校验
  defaultValue?: number | boolean | string; // 初始值：连接建立前与断线时组件显示该值；
                            // 随 doc 存储于 projects.doc，但不写入任何运行值/历史值存储（P0 无运行值落库）
  datasourceId: ID;        // 所属数据源，必须指向 datasources[].id
  address: string;         // 取数地址：mqtt=topic；websocket=帧内定位约定键；rest=响应内定位键；mock 忽略；modbus=惯用区位十进制；opcua=nodeId 字符串（如 ns=2;s=demo.temp）
  jsonPath?: string;       // 载荷点路径（子集语法见第 1 章第 4 条），如 "data.temp"
  scale?: number;          // 工程值 = 原始值 × scale + offset；默认 1。服务端入 hub 前执行
  offset?: number;         // 默认 0
  precision?: number;      // 小数取位（四舍五入到 N 位）；缺省不取整。enum 查表使用取位后的值
  bitIndex?: number;       // 位提取：将原始值按整数取第 N 位（0 起）得 1/0；提取后仍按 type 规范化
                           // （boolean 变量将 1/0 归一为 true/false，见下方换算流水）。仅允许配合
                           // boolean / number 类型，且与 scale/offset/precision 互斥（校验见 2.13 规则 5）。
                           // 典型用途：从状态字中取位驱动 boolean 变量
  mock?: MockSpec;         // 所属数据源 type==='mock' 时的波形参数；其余数据源忽略
  description?: string;
}
```

**服务端换算流水（唯一口径，报警评估基于此结果）**：

1. `raw` = 按 `address` 定位帧，再按 `jsonPath` 提取；缺帧/解析失败 → 值标记 `q='bad'`，保留上一有效值。
2. **位提取**（可选步骤）：若 `bitIndex` 非空 → `raw = (ToInt(raw) >> bitIndex) & 1`（非整数输入先截断，转换失败 → `q='bad'`）。位提取后**继续执行步骤 3，不跳过类型规范化**。
3. **按 `type` 规范化**（所有变量必经，无论是否配置 bitIndex）：
   - `number` → `raw × scale + offset`（`scale` 默认 1、`offset` 默认 0；配置了 `bitIndex` 时二者必须保持缺省，互斥校验见 2.13 规则 5）；
   - `boolean` → `true / 1 / '1'` → `true`，其余（`0 / '0' / false / ''` 等）→ `false`（bitIndex 取出的 1/0 由此归一为 true/false）；
   - `string` → 原样（bitIndex 与 string 互斥，校验拦截）。
4. `number` 且 `precision` 非空 → 四舍五入到 N 位。**服务端实现必须使用 `decimal.Decimal` 的 `ROUND_HALF_UP` 量化**（如 `Decimal(str(v)).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)`），**禁止裸用内置 `round()`**——Python 内置 round 为银行家舍入（round-half-even），与前端 `Math.round` 在 x.5 边界结果不一致，会造成服务端报警判定与前端显示口径的分叉。
5. 结果类型与 `type` 不符 → `q='bad'`，值保持上一有效值。

```ts
export type MockSpec =
  | { kind: 'sine';   min: number; max: number; periodMs: number }  // 正弦波：min~max，周期 periodMs
  | { kind: 'ramp';   min: number; max: number; periodMs: number }  // 锯齿：min 线性升至 max 耗时 periodMs 后回落循环
  | { kind: 'random'; min: number; max: number; intervalMs: number }// 区间均匀随机，间隔 intervalMs
  | { kind: 'square'; onValue: number; offValue: number; periodMs: number; duty?: number }; // 方波，占空比默认 0.5
```

### 2.10 数据源（四类）

```ts
export type DataSource =
  | {
        id: ID; name: string; type: 'mqtt';
        enabled?: boolean;          // 启用开关，默认 true；停用即停止采集任务
        config: {
          brokerUrl: string;          // 如 mqtt://emqx:1883、mqtts://host:8883
          username?: string;
          password?: string;          // 敏感字段：GET 读取/导出/分享快照中一律为空字符串（库内 Fernet 加密存储）；
                                      // PUT 提交空字符串=保留库内旧值、null=显式清除（见 4.3 规则④⑤）
          topics: string[];           // 订阅主题列表，支持 MQTT 通配符 + / #；只订阅、绝不发布
          qos?: 0 | 1;                // 默认 0
          cleanSession?: boolean;     // 默认 true；导入时强制重置为 true（边界声明第 7 条）
          reconnectMinMs?: number;    // 断线重连初始延迟，默认 1000（指数退避）
          reconnectMaxMs?: number;    // 重连延迟上限，默认 30000
          staleTimeoutMs?: number;    // 无新值判 stale 阈值；缺省 = 3 × 变量采集周期
          tsPath?: string;            // 载荷时间戳点路径（点路径子集语法见第 1 章第 4 条）；缺省=用服务端接收时间
        };
      }
  | {
        id: ID; name: string; type: 'websocket';
        enabled?: boolean;          // 启用开关，默认 true
        config: {
          url: string;                // 上游 ws:// 或 wss:// 地址（服务端作为客户端长连接）
          headers?: Record<string, string>; // 连接请求头（如鉴权）；敏感键脱敏与空值保留合并语义见 4.3 规则④⑤
          subscribeFrame?: string;    // 连接成功后发送一次的订阅指令 JSON 文本；缺省不发
          heartbeatSec?: number;      // 心跳间隔秒；缺省不发心跳
          reconnectMinMs?: number;    // 默认 1000
          reconnectMaxMs?: number;    // 默认 30000
          staleTimeoutMs?: number;
          tsPath?: string;            // 载荷时间戳点路径；缺省=用服务端接收时间
        };
      }
  | {
        id: ID; name: string; type: 'rest';
        enabled?: boolean;          // 启用开关，默认 true
        config: {
          url: string;                // 完整 HTTP(S) 地址；服务端轮询，天然规避浏览器 CORS
          method: 'GET' | 'POST';
          intervalMs: number;         // 轮询间隔，下限 500（校验拦截更小值）
          headers?: Record<string, string>; // 键名匹配 authorization/token/password/secret/key（不区分大小写）
                                            // 的键为敏感项（脱敏与空值保留合并语义见 4.3 规则④⑤；websocket.headers 同口径）
          body?: string;              // POST 请求体（JSON 文本）
          timeoutMs?: number;         // 单次请求超时，默认 5000
          failureBackoffMs?: number;  // 失败后退避间隔，默认 intervalMs × 5
          staleTimeoutMs?: number;
          tsPath?: string;            // 载荷时间戳点路径；缺省=用服务端接收时间
        };
      }
  | {
        id: ID; name: string; type: 'mock';
        enabled?: boolean;          // 启用开关，默认 true；mock 数据生成的启停即由本字段控制（不设 projects.mock_enabled 列、不设独立 mock REST）
        config: { defaultIntervalMs?: number }; // 变量未配 MockSpec 间隔时的缺省生成间隔，默认 1000
      }
  | {
        id: ID; name: string; type: 'modbus';   // M8 阶段 1 后半：服务端 collector 采集（浏览器无 TCP 能力，运行态经 WS 取值）
        enabled?: boolean;
        config: {
          host: string;            // PLC/网关 IP
          port?: number;           // 默认 502
          unitId?: number;         // 从站号，默认 1
          intervalMs?: number;     // 轮询间隔，默认 1000（下限 100）
          timeoutMs?: number;      // 默认 3000
          staleTimeoutMs?: number | null;
        };
        // 变量 address 用 Modbus 惯用 5 位区位十进制：4xxxx 保持寄存器 / 3xxxx 输入寄存器
        // / 0xxxx 线圈（可写）/ 1xxxx 离散输入；scale/offset/precision 复用统一换算流水；
        // 协议自身无账号体系（UnitId 即从站标识），无敏感字段（脱敏/加密链路 no-op）
      }
  | {
        id: ID; name: string; type: 'opcua';   // 工厂可用阶段二：服务端 asyncua 订阅推送（浏览器 no-op，运行态经 WS 取值）
        enabled?: boolean;
        config: {
          endpointUrl: string;     // 仅 opc.tcp://（首版无 opc.https）
          securityMode?: 'none';   // 首版仅明文 None 安全模式（枚举占位后续扩展证书/加密）
          username?: string | null;   // 不脱敏（G6 沿 mqtt username）
          password?: string | null;   // 敏感：出口脱敏 / 库内 Fernet 加密（沿 mqtt 口径）
          publishIntervalMs?: number; // 订阅发布周期，默认 1000（下限 200）
          reconnectMinMs?: number; reconnectMaxMs?: number;  // 断线指数退避（沿 mqtt 缺省 1000/30000）
          staleTimeoutMs?: number | null;
        };
        // 变量 address = nodeId 字符串（如 ns=2;s=demo.temp）；writeAddress 缺省回落 address，
        // 写入 = node.set_value；断线重连成功后重建全部订阅（订阅不跨连接存活）
      };
```

工程保存时采集器按 datasource/variable 差量热重建任务；删除数据源/变量的编辑态级联规则见 2.13。

### 2.11 报警规则

```ts
export interface AlarmRule {
  id: ID;                  // 报警记录冗余引用它（触发时快照落 alarm_records.rule_id，长度校验见 2.13 规则 6）；随 doc 导出导入
  name: string;
  variableId: ID;          // 作用变量。类型约束：number 可用全部 op；boolean 仅 '=='/'!='
                           //（threshold 用 1/0 表示 true/false）；string 变量拒绝配置（校验 422）
  op: '>' | '>=' | '<' | '<=' | '==' | '!=';
  threshold: number;       // 阈值，口径=工程值（换算后），与界面显示一致
  level: 'info' | 'warn' | 'critical';   // 颜色取 settings.alarm.levelColors
  message: string;         // 报警文本，支持占位符 {key} {label} {value} {threshold}；value 为工程值
  enabled: boolean;
  hysteresis?: number;     // 回差带，默认 0：防临界抖动反复触发/恢复
  durationMs?: number;     // 持续满足该时长才触发；0 或缺省=立即
  sound?: boolean;         // 触发时前端播放提示音（且 settings.alarm.soundEnabled 为 true 才生效）
  // 恢复策略：P0 固定为"自动恢复"——触发条件不再满足且值越过回差带即恢复，无人工确认（ack 属 P1 预留）
}
```

恢复判定细则（按 op 分档，确定性规则）：

| op | 触发 | 恢复条件（hysteresis = H） |
|---|---|---|
| `>` | v > threshold | v ≤ threshold − H |
| `>=` | v ≥ threshold | v < threshold − H |
| `<` | v < threshold | v ≥ threshold + H |
| `<=` | v ≤ threshold | v > threshold + H |
| `==` / `!=` | 等值判定 | 反向判定即恢复（H 不适用，配置非 0 时校验警告） |

防风暴契约（与实时协议专项共同遵守）：同一规则的前端提示音按 `settings.alarm.soundThrottleSec`（默认 60s）节流；单工程活动报警 WS 帧条数上限 200 条，超出按 `critical > warn > info` 优先保留并携带 `truncated` 标记，未进入帧的仅落库、前端报警条显示"另有 N 条"；服务端重启时内存态丢失，启动时遗留 `active` 记录统一收口为 `recovered`（`recovered_at = now()`）。

### 2.12 报警态与绑定变色的优先级契约

同一组件上颜色类效果分三条通道，**职责分离、优先级固定**：

| 通道 | 来源 | 职责 |
|---|---|---|
| S0 静态样式 | `style` / `props` 内置默认值 | 基线外观 |
| S1 绑定求值 | `color` 绑定（enum/range） | 表达**工艺分段**（按值变色，如温度色带） |
| S2 报警态 | 该组件任一 `binding.variableId` 存在 active 报警 | 表达**运行状态强调** |

规则（实现不得偏离）：

1. 优先级 S2 > S1 > S0：报警态**覆盖组件填充色**为 `settings.alarm.levelColors[level]` 对应色，并在其上**叠加闪烁动画**（接管 `animations.blink` 通道）；报警恢复后自动回落至 S1/S0 呈现。
2. 多条报警同时命中同一组件时，取最高 level。
3. `visibility` 绑定优先于报警：绑定求值为隐藏即隐藏，报警态不突破显隐绑定。
4. 同一 `prop` 重复绑定被校验禁止（见 2.13），不存在同通道内竞争。

本契约的唯一实现点为 `web/src/widgets/WidgetHost.vue`。

### 2.13 引用完整性与编辑态级联规则（校验契约）

服务端在**保存（PUT `/api/v1/projects/{id}`）与导入（`POST /api/v1/projects/import`）**时执行全量校验，失败返回 422，错误体为 `{ code, message, errors: [{ path, message }] }`（errors[].path 为 doc 内字段路径，如 `pages[0].components[2].bindings[0].variableId`）：

1. **唯一性**：`variables[].id`、`variables[].key`、页面 id、组件 id（全工程含组内）、datasource id、alarmRule id、binding id。（`variables[].id` 与 `key` 分别唯一：两个变量同 id 不同 key 会使 `bindings[].variableId`、`alarmRules[].variableId` 的引用歧义，且报警记录冗余的 `variable_key` 无法区分。）
2. **引用存在性**：`bindings[].variableId`、`alarmRules[].variableId`、`variables[].datasourceId` 必须存在。
3. **同 prop 唯一**：同一组件同一 `prop` 仅一条绑定。
4. **`project.id`**：必须为 UUID 格式（正则校验）；保存（PUT）时必须与库内 `projects.id` 一致，不一致 422；导入时由服务端按 5.2 步骤 8 重写为新库 id（重写后自然满足）。此项拦截示例文件中 nanoid 风格 id 之类的非法值。
5. **类型与路径合法性**：`mode='color'` 的目标必须是颜色类路径且映射值合法（合法颜色串）；`mode='visibility'` 的目标必须为 `visible`；`alarmRules` 变量类型约束（见 2.11）；`bitIndex` 仅允许配合 `type ∈ {'boolean','number'}`，且与 `scale/offset/precision` 互斥（同时配置 → 422）。registry 级校验的职责边界见下方专述。
6. **字段长度上限**（超长直接 422，不允许落到库层以数据库报错暴露）：doc 内各级 `id` ≤ 64 字符（含页面 id、组件 id、规则 id 等，仅存 JSONB，统一 64）；`variables[].key` ≤ 128 字符；`variables[].label` ≤ 128；`project.name` ≤ 128。库表对应列均为 TEXT（见 4.1），上述上限为应用层统一校验。`users.username`、`share_links.token` 由服务端生成与管理，不属于 doc 校验范围。
7. **规模校验**：doc 序列化体积 ≤ 1MB 时编辑器 UI 告警、> 2MB 服务端 422（`code=doc_too_large`）；单页组件 > 200 时附 `warnings` 不阻断。

**registry 校验职责边界（P0 显式决策）**：组件"可绑定路径 + 目标类型"清单的事实来源在前端 `web/src/widgets/registry.ts`。P0 服务端**不**加载 registry 做逐组件校验——服务端仅校验通用路径语法（`props.*` / `style.*` / `visible` / `opacity` 四类）与 `style.*` 目标键必须属于 `ComponentStyle` 键集（规则 5）；registry 级校验（该组件是否真的拥有该 props 键、目标类型是否匹配）由前端属性面板在**创建绑定时**强制承担，服务端层面标注为**已知弱化**。运行态容错：binder 求值遇到组件上不存在的目标路径时，静默忽略该绑定并记 `console.warn`，不中断渲染。P1 预留扩展点：组件库构建期输出 `bindable-paths.json` 工件（可绑定路径 + 目标类型清单）随包分发，服务端 Pydantic 启动时加载后补齐 registry 级校验。

编辑器内删除操作的前端级联行为（服务端校验做最终兜底）：

| 删除对象 | 行为 |
|---|---|
| 变量 | 存在引用（bindings / alarmRules）时**阻断**并列出全部引用位置；用户确认"级联清除"后一并删除这些绑定与规则 |
| 数据源 | 先对其下全部变量执行上条流程，全部清除后删除数据源 |
| 页面 | 级联删除页内组件及其 bindings；既有分享快照为冻结副本，本次删除不影响（快照方案见 4.2），刷新/重建分享链接时按最新 doc 重新冻结 |

---

## 3. 最小示例工程 JSON

1 个页面、2 个组件（gauge + pump）、2 个变量、1 个 MQTT 数据源、1 条报警规则；覆盖数值 / 颜色 / 显隐三类绑定。此即导出文件格式（凭证字段在导出与分享快照中会被置空，见 4.3）。

```json
{
  "schemaVersion": 1,
  "project": {
    "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "name": "一号产线演示",
    "description": "最小示例：反应釜温度监控 + 循环泵状态",
    "author": "admin",
    "createdAt": "2026-01-15T08:00:00.000Z",
    "updatedAt": "2026-01-15T09:30:00.000Z"
  },
  "settings": {
    "designSize": { "width": 1920, "height": 1080 },
    "adaptive": "fit-contain",
    "theme": "blue-dark",
    "primaryColor": "#2563eb",
    "alarm": {
      "levelColors": { "info": "#3b82f6", "warn": "#f59e0b", "critical": "#ef4444" },
      "soundEnabled": true
    }
  },
  "datasources": [
    {
      "id": "ds_mqtt_01",
      "name": "车间 EMQX",
      "type": "mqtt",
      "config": {
        "brokerUrl": "mqtt://emqx:1883",
        "username": "factory",
        "password": "F@ct0ry2026",
        "topics": ["factory/line1/#"],
        "qos": 0,
        "cleanSession": true,
        "reconnectMinMs": 1000,
        "reconnectMaxMs": 30000
      }
    }
  ],
  "variables": [
    {
      "id": "var_temp_01",
      "key": "reactor1_temp",
      "label": "1号反应釜温度",
      "type": "number",
      "unit": "°C",
      "range": { "min": 0, "max": 150 },
      "defaultValue": 0,
      "datasourceId": "ds_mqtt_01",
      "address": "factory/line1/reactor1",
      "jsonPath": "data.temp",
      "scale": 0.1,
      "offset": 0,
      "precision": 1
    },
    {
      "id": "var_pump_01",
      "key": "pump1_running",
      "label": "1号循环泵运行",
      "type": "boolean",
      "defaultValue": false,
      "datasourceId": "ds_mqtt_01",
      "address": "factory/line1/pump1",
      "jsonPath": "data.running",
      "bitIndex": 0
    }
  ],
  "pages": [
    {
      "id": "page_overview",
      "name": "产线总览",
      "order": 0,
      "background": { "color": "#0b1220" },
      "screen": { "designWidth": 1920, "designHeight": 1080, "mode": "fit-contain" },
      "components": [
        {
          "id": "cmp_gauge_01",
          "type": "gauge",
          "name": "反应釜温度仪表盘",
          "x": 120, "y": 200, "w": 320, "h": 320, "rotate": 0, "z": 1,
          "visible": true, "locked": false, "opacity": 1,
          "props": {
            "value": 0,
            "min": 0, "max": 150,
            "unit": "°C",
            "splitNumber": 5,
            "decimals": 1,
            "levelBands": [
              { "from": 0, "to": 80, "color": "#22c55e" },
              { "from": 80, "to": 110, "color": "#f59e0b" },
              { "from": 110, "to": 150, "color": "#ef4444" }
            ],
            "showValue": true
          },
          "style": { "color": "#38bdf8" },
          "animations": {},
          "bindings": [
            { "id": "bnd_g01", "prop": "props.value", "variableId": "var_temp_01", "mode": "value" },
            {
              "id": "bnd_g02", "prop": "style.color", "variableId": "var_temp_01", "mode": "color",
              "mapping": {
                "kind": "range",
                "bands": [
                  { "max": 80, "value": "#22c55e" },
                  { "min": 80, "max": 110, "value": "#f59e0b" },
                  { "min": 110, "value": "#ef4444" }
                ]
              }
            }
          ]
        },
        {
          "id": "cmp_pump_01",
          "type": "pump",
          "name": "1号循环泵",
          "x": 560, "y": 240, "w": 120, "h": 120, "rotate": 0, "z": 2,
          "visible": true, "locked": false, "opacity": 1,
          "props": {
            "state": 0,
            "runColor": "#22c55e",
            "stopColor": "#64748b",
            "faultColor": "#ef4444"
          },
          "style": {},
          "animations": { "rotate": { "enabled": true, "clockwise": true, "periodMs": 1000 } },
          "bindings": [
            { "id": "bnd_p01", "prop": "props.state", "variableId": "var_pump_01", "mode": "value" },
            {
              "id": "bnd_p02", "prop": "visible", "variableId": "var_pump_01", "mode": "visibility",
              "mapping": { "kind": "enum", "map": { "true": true, "false": false } }
            }
          ]
        }
      ]
    }
  ],
  "alarmRules": [
    {
      "id": "alm_temp_01",
      "name": "反应釜温度超高",
      "variableId": "var_temp_01",
      "op": ">",
      "threshold": 110,
      "level": "warn",
      "message": "{label} 超高: {value} °C（阈值 {threshold}）",
      "enabled": true,
      "hysteresis": 2,
      "durationMs": 5000,
      "sound": true
    }
  ]
}
```

要点：温度原始值若上报 725，经 `scale=0.1` 得工程值 72.5，仪表盘显示 72.5、阈值 110 按同一口径判定；泵状态字（如上报 `5`）经 `bitIndex=0` 取位得 `1`，**取位后继续按 type 规范化**，boolean 归一为 `true`（见 2.9 换算流水），`props.state` 生效为运行态并驱动旋转与三态色；`bnd_p02` 仅演示显隐绑定语法（停止即隐藏），生产中建议改绑"设备在线"类变量。

---

## 4. PostgreSQL 存储设计

### 4.1 表结构（DDL 级，alembic 管理；PostgreSQL 16，`gen_random_uuid()` 内置）

```sql
-- 用户（单团队：无注册接口，管理员由初始化脚本按 .env 创建）
CREATE TABLE users (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username      TEXT        NOT NULL UNIQUE,
    password_hash TEXT        NOT NULL,               -- bcrypt（固定 60 字符）
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 工程（doc 为唯一事实来源，整体 JSONB）
CREATE TABLE projects (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT        NOT NULL,
    description TEXT,
    doc         JSONB       NOT NULL,                -- ProjectDoc 全量；schemaVersion 迁移入口
    revision    INTEGER     NOT NULL DEFAULT 1,      -- 乐观锁自增；PUT 携带 baseRevision，不符 409 REVISION_CONFLICT，成功响应返回新 revision
    owner_id    UUID        NOT NULL REFERENCES users(id),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()   -- 仅记录更新时间；乐观锁使用 revision 列
);
CREATE INDEX idx_projects_owner ON projects(owner_id);

-- 分享链接（快照方案：多链接、可过期、可撤销；无发布状态机、无 published_doc 列）
CREATE TABLE share_links (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id     UUID        NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    token          TEXT        NOT NULL UNIQUE,        -- 服务端生成（nanoid），即公开访问凭证
    doc_snapshot   JSONB       NOT NULL,               -- 创建/refresh 时冻结的脱敏后工程快照
    expires_at     TIMESTAMPTZ,                        -- NULL=永不过期
    revoked_at     TIMESTAMPTZ,                        -- 非 NULL=已撤销（"撤销发布"语义）
    last_access_at TIMESTAMPTZ,                        -- 最近访问时间（运营观测）
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_share_token ON share_links(token);

-- 报警记录（运行数据，不入 doc；高频写入）
CREATE TABLE alarm_records (
    id           BIGSERIAL PRIMARY KEY,
    project_id   UUID              NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    rule_id      TEXT              NOT NULL,        -- doc.alarmRules[].id 触发时快照；有意不做外键（规则随 doc 生灭）
    variable_key TEXT              NOT NULL,        -- 触发时快照：变量被删后历史记录仍可读
    level        TEXT              NOT NULL CHECK (level IN ('info', 'warn', 'critical')),
    message      TEXT              NOT NULL,
    value        TEXT,                              -- 触发时刻工程值的字符串快照
    status       TEXT              NOT NULL CHECK (status IN ('active', 'recovered')),
    triggered_at TIMESTAMPTZ       NOT NULL,
    recovered_at TIMESTAMPTZ                        -- active 时为 NULL
);
CREATE INDEX idx_alarm_proj_triggered ON alarm_records(project_id, triggered_at DESC);
```


### 4.1.1 M8 修订：服务端闭环 DDL 增量（alembic 0002 权威）

> 「服务端监控闭环」落地增补（契约：docs/implementation/server-closed-loop-plan.md §3）。权威实现：`server/alembic/versions/0002_server_closed_loop.py`（可 downgrade）。

```sql
-- 用户增角色列（存量迁移置 admin；之后经 users API 收敛）
ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'admin'
    CHECK (role IN ('admin','operator','viewer'));   -- admin/operator/viewer

-- 报警记录改单行状态机：triggered → (acked) → cleared（修复「恢复另插新行」缺陷）
ALTER TABLE alarm_records
    ADD COLUMN acked_at   TIMESTAMPTZ,
    ADD COLUMN acked_by   UUID REFERENCES users(id) ON DELETE SET NULL,
    ADD COLUMN acked_note TEXT,
    ADD COLUMN cleared_at TIMESTAMPTZ;
-- status 约束改为 CHECK (status IN ('triggered','acked','cleared'))
-- 数据迁移：active→triggered；recovered→cleared（cleared_at=recovered_at）；recovered_at 列删除

-- 审计日志（只追加，RBAC 配套）
CREATE TABLE audit_logs (
    id BIGSERIAL PRIMARY KEY,
    user_id   UUID REFERENCES users(id) ON DELETE SET NULL,
    username  TEXT,                  -- 触发时快照，用户删除后仍可读
    action    TEXT NOT NULL,         -- login/write_var/alarm_ack/project_save/share_create/share_revoke/user_mgmt
    target_type TEXT, target_id TEXT,
    detail    JSONB,
    ip        TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_audit_created ON audit_logs(created_at DESC);
CREATE INDEX idx_audit_user    ON audit_logs(user_id);
CREATE INDEX idx_audit_action  ON audit_logs(action);

-- 历史值（服务端 historian 定窗采样入库；按 ts 分区可后置）
CREATE TABLE history_values (
    id BIGSERIAL PRIMARY KEY,
    project_id   UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    variable_key TEXT NOT NULL,      -- 触发时快照口径（变量删除后区间查询仍可读）
    ts           TIMESTAMPTZ NOT NULL,
    value        DOUBLE PRECISION NOT NULL   -- 工程值（服务端换算流水执行后）
);
CREATE INDEX idx_history_proj_var_ts ON history_values(project_id, variable_key, ts DESC);
```

### 4.2 工程 JSON 与数据库的存储映射

| doc / 数据部分 | 存储位置 | 拆分决策与理由 |
|---|---|---|
| `schemaVersion + project + settings + datasources + variables + pages（含组件/bindings）+ alarmRules` | `projects.doc JSONB` 整体 | 单行事务保证一致性；导入导出零转换；schemaVersion 迁移只需一条流水线。P0 无按组件/按页查询需求，规范化拆表只增加复杂度 |
| `project.id` | `projects.id`（双写） | 库内 id 为主，URL 与外键主体；导入时重写 doc 内 id 使二者一致 |
| 乐观锁 | `projects.revision`（INT 自增，doc 内不冗余） | PUT 请求携带 `baseRevision`，不符 409 `REVISION_CONFLICT`；成功响应返回新 revision（废弃 baseUpdatedAt/时间戳方案） |
| 分享语义 | `share_links` 拆表 | 多 token、过期/撤销可管理；`doc_snapshot` 快照方案——创建/refresh 时冻结**脱敏后** doc，编辑保存不影响已分享大屏，"发布"语义 = 创建或刷新分享链接。公开端 `GET /api/v1/share/{token}`（无鉴权读快照）与管理端 `POST /api/v1/projects/{id}/shares`（列表/创建）、`DELETE /api/v1/shares/{token}`（撤销，置 `revoked_at`，记录保留）、`POST /api/v1/shares/{token}/refresh`（刷新快照）并存；单复数差异为有意设计（公开面与管理面分离） |
| 报警**规则** | `doc.alarmRules`（doc 内） | 规则属于工程配置，随导出导入迁移 |
| 报警**记录** | `alarm_records` 拆表 | 高频写入的运行数据与配置生命周期不同；不入 doc 避免保存覆盖冲突与文档膨胀；`rule_id` 不做外键（规则删除不影响历史记录）；`variable_key`/`value` 为触发时快照，保证可读性 |
| 用户与凭证 | `users` 独立表 | 鉴权数据绝不进入工程文档（导出/分享不携带） |
| 数据源凭证（mqtt password、rest/websocket 敏感 headers） | `projects.doc` 内 Fernet 加密存储 | 库内加密（cryptography，密钥 `.env` 的 `DATASOURCE_SECRET`）；所有出口（读取/导出/分享快照）一律脱敏，见 4.3 |
| 变量实时值 | 进程内 hub（不落库） | 实时值仅内存流转，经 ws_manager 100ms 合帧下发（03 §3.4） |
| 历史趋势 | history_values 拆表（**M8 修订**） | 服务端 historian 按 `HISTORY_SAMPLE_INTERVAL_MS` 定窗采样工程值入库；清理任务消费 `HISTORY_RETENTION_DAYS`；前端经 `GET /api/v1/projects/{id}/history` 查询（03 §2.10）。浏览器本地分钟桶缓冲降级为演示/离线用途 |

### 4.3 敏感凭证处理（安全契约）

- 脱敏范围：`mqtt.config.password`；`rest` / `websocket` 的 `config.headers` 中键名匹配 `authorization|token|password|secret|key`（不区分大小写）的键值。`mqtt.config.username` 不脱敏。
- 规则：
  - ① **导出 JSON** 与 **`doc_snapshot`（分享快照）** 中敏感字段一律置空字符串；
  - ② 公开端点（`GET /api/v1/share/{token}`）返回快照，天然不含凭证；
  - ③ **导入**时若文件携带凭证，一律视为空并置空（安全默认），用户导入后重新填写；
  - ④ **库内加密存储 + 读取脱敏**：凭证在 `projects.doc` 内以 Fernet 加密存储（`cryptography`，密钥来自 `.env` 的 `DATASOURCE_SECRET`），服务端内部（采集器任务、连通性测试）按需解密使用；读取（`GET /api/v1/projects/{id}`）对已登录用户返回**脱敏 doc**：敏感字段一律为空字符串。
  - ⑤ **保存（PUT）空值保留合并**——本条与规则④配对，防止"编辑器载入脱敏 doc（密码框为空）→ 用户做任意无关修改 → PUT 全量覆盖 → 空字符串抹掉库内明文凭证 → 采集器差量热重建后 MQTT 鉴权失败"的断数缺陷。服务端写库前将提交 doc 中的敏感字段与库内旧 doc **逐字段合并**：
    - 提交值为**非空字符串** → 覆盖为新值；
    - 提交值为**空字符串或字段缺省** → 保留库内旧值（语义：未修改）；
    - 提交值为 **`null`** → 显式清除（从 doc 中删除该字段；username 与 password 同时置 null = 无凭据状态，对应 broker/服务端允许匿名的场景）。
    前端属性面板密码框以空串回显"已配置、未修改"状态（placeholder 提示"留空表示不修改"），提供"清除"按钮提交 `null`。合并只作用于脱敏范围内的字段，其余字段仍为全量覆盖。
- `pytest` 必过项：
  1. 导出 → 导入 → 再导出的 round-trip 测试中，敏感字段两次导出均为空；
  2. GET → 不触碰凭证、修改其他任意字段 → PUT → 内部读取确认库内凭证仍在（采集器重建后可连通）；PUT 携带 `null` 后确认字段被删除；
  3. 清除凭证后导出 → 导入 → 再导出的 round-trip：确认"凭证已清除"状态随文件迁移，两次导出敏感字段均为空、库内无残留。

### 4.4 报警记录保留策略（7x24 运行必须）

- 配置（`.env`）：`ALARM_RETENTION_DAYS`（默认 30）、`ALARM_MAX_ROWS_PER_PROJECT`（单工程行数上限，默认 200000）。
- 清理任务：server 进程内每 24h 执行（启动时先跑一次）：① 删除 `status='recovered'` 且 `recovered_at < now() - RETENTION` 的记录；② 单工程 recovered 总量超过 `ALARM_MAX_ROWS_PER_PROJECT` 时按 `recovered_at` 最旧截断；**active 记录一律不清理**（启动时遗留 `active` 先统一收口为 `recovered`，见 2.11 防风暴契约）。
- 部署文档须注明该策略与两个环境变量。

---

## 5. 导入导出文件格式与版本兼容策略

### 5.1 导出文件格式

- 内容 = `ProjectDoc` 全量，与 `projects.doc` 结构完全一致（唯一差异：敏感字段置空）。独立导出端点：`GET /api/v1/projects/{id}/export`（响应为 JSON body，由前端 Blob 触发下载并命名文件；响应头不使用非 ASCII 文件名）。导出 doc 已按 4.3 规则①脱敏，导出文件天然不含凭证。
- 文件名约定（不强制校验）：`{project.name}_schema{schemaVersion}_{yyyyMMddHHmmss}.json`。
- 导入 = `POST /api/v1/projects/import`（multipart 文件或 JSON body）；`POST /api/v1/projects` 仅创建工程元信息、不得携带完整 doc。重复导入同一文件产生新工程（不做内容级去重，P0 明确）。导入入口 P0 仅前端编辑器一处。

### 5.2 导入流水线（服务端，顺序固定）

1. `JSON.parse` 失败 → 422 `invalid_json`。
2. `schemaVersion` 缺失或非正整数 → 422。
3. `schemaVersion > CURRENT_SCHEMA_VERSION` → 422 `version_unsupported`（提示升级前端）。
4. `schemaVersion < CURRENT_SCHEMA_VERSION` → 422 `version_unsupported`（错误信息提示：请使用前端编辑器的导入入口——前端会先执行 `migrateDoc()` 将文件升级到当前版后再提交。P0 导入唯一入口为前端 UI，正常操作不会触发该错误；见 5.3 双端边界）。
5. Pydantic v2 全量结构校验 → 422 列出字段路径。
6. 引用完整性校验（2.13 全部规则）→ 422。
7. 敏感字段强制置空（4.3 规则③）。
8. 重写 `doc.project.id` 为新库 id、重置 `createdAt/updatedAt` → 入库（内部组件/变量 id 不重新生成，保持可读与 diff 友好）。

### 5.3 schemaVersion 迁移策略（双端归属闭环）

- **迁移的唯一执行点在前端**：`MIGRATIONS: Record<number, (doc: object) => object>`（键 = 起始版本）注册表集中于 `web/src/types/migrations.ts`，编辑器载入与导入提交前经 `migrateDoc()` 升级到 `CURRENT_SCHEMA_VERSION`。**服务端（Python）不实现迁移**，仅接受并校验 `CURRENT_SCHEMA_VERSION`（5.2 步骤 4/5），避免 TS/Python 双实现漂移。注册表框架在 M0 建好（P0 仅 v1，无迁移函数，但框架与测试位就绪）。
- **边界声明（P0 已知限制）**：非前端客户端直接向 API 提交旧版 doc 会得到 422 `version_unsupported`。若 P1 出现非前端导入入口（开放 API / CLI），届时迁移改为服务端注册表（Python 实现）并以 5.4 round-trip 契约测试做 TS/Python 双端同构回归（预留扩展点，触发条件明确）。
- 旧版前端读到新版文件：版本高于自身 `CURRENT` 时明确报错提示升级，禁止"尽量读"的静默降级。

### 5.4 round-trip 契约测试（pytest 必过项）

内置示例工程 → 导出 → 导入 → 再导出，两次导出做结构化 diff：除 `project.id/createdAt/updatedAt` 外**字段级一致**，敏感字段均为空。清除凭证场景的 round-trip 覆盖见 4.3 pytest 必过项第 3 条。该测试是导出/导入/迁移三方契约的回归保障。

---

## 6. 移交其他专项的事项清单

以下为评审指出、但归属其他专项文档的缺口，本文仅登记交界面契约，防遗漏：

| 事项 | 归属专项 | 交界面约定 |
|---|---|---|
| `GET /api/v1/health` 存活检查（compose healthcheck 依赖） | 接口清单专项 | 无数据结构影响 |
| `PUT /api/v1/auth/password` 改密接口（body `{oldPassword, newPassword}`） | 接口清单专项 | 无表结构变更（仅更新 `password_hash`） |
| `POST /api/v1/datasources/test` 连通性测试（全局端点，入参即 `DataSource.config`，超时 5s，出参 `{ok, type, latencyMs, message}`，不落库） | 接口清单专项 | 入参复用 2.10 结构；测试入参同样适用 4.3 规则⑤空值保留语义（空串回填库内值后再测） |
| WS 访问日志对 token 脱敏；share token / JWT 运行态 WS 并发上限（`SHARE_MAX_WS_PER_TOKEN` / `JWT_WS_MAX_PER_USER_PROJECT`） | 部署 / 实时专项 | token 即凭证，日志必须脱敏 |
| 运行态级联热清理（删工程 / 撤销分享 / 分享过期时推送 error 帧并断开 WS、停采集任务、清内存变量池） | 实时专项 | 触发源即本文 4.1 的删陧行为；error/close 语义以实时协议专项为准 |
| 多页工程全项目订阅的告警广播流量上界、报警声音 60s 节流、值无变化不下发 | 实时专项 | 帧协议内约定 |
| 时间戳信任策略（epoch ms；载荷时间戳点路径由数据源 `config.tsPath` 声明（见 2.10），未配置或缺帧回退服务端接收时间；载荷时间戳与服务器时间偏差 > ±5min（双向，含未来时间）视为不可信，回退服务器时间并记 warn） | 实时专项 | 值携带 `t/q` 语义 |
| 服务端重启遗留 active 报警标记 recovered | 实时专项 | 落库语义见 2.11 防风暴契约 |
---

## 7. M7 增量契约（反控 / 虚拟变量 / 事件与行为 / 弹框 / 动效扩展）

> M7 对齐业界主流组态功能集引入。**全部字段可选或带默认值，向后兼容，schemaVersion 不变**。
> 双端实现：`web/src/types/doc.ts` ↔ `server/app/schemas/doc.py`（本节为权威描述，改动须双侧同步）。

### 7.1 反控（写通道）

- 架构（**M8 修订**）：反控统一走服务端 WS 通道——C→S `write` 帧 → 服务端校验（JWT 用户、operator/admin 角色、变量 writable）后按数据源类型分发（mqtt publish / rest POST / ws send），回 S→C `writeAck` 帧（见 03-接口清单 §3.4 帧目录）；并落审计 `write_var`。浏览器直连模式仅保留为编辑器「数据源连接测试」专用，不再承担运行态写。分享页恒只读。
- 权限：`RuntimeEngine.write()` 为唯一入口。**编辑器预览可写（writable=true）；分享页恒只读（writable=false）**。
- `VariableDef` 增量：`writable: bool = false`（默认只读）；`writeAddress: str | null`（mqtt 写 topic，缺省回落 `address`）。
- 数据源写配置（`config` 增量）：
  - `RestConfig.writeUrl / writeMethod(POST|PUT) / writeBodyTemplate`（占位 `{key}` `{value}`，缺省 `{"key":value}`；无 writeUrl 即不可写）
  - `WebsocketConfig.writeFrameTemplate`（占位同上）
  - `MqttConfig.writeQos`（0|1；订阅 topics 不变，写 topic 在变量 writeAddress）
  - `mock`：本地回环（写入直接走 onRaw → toEngineering 全链路，绑定/报警/历史一致生效）
- `MockSpec` 新增 `{kind:'hold'}`（保持型）：不周期推送，仅启动时推一次 `defaultValue`，此后只随写入回环变化。反控演示与受控开关量（泵启停/阀门/设定值）用它，否则周期波形会立刻覆盖用户写入。
- 校验：`writeVar` 事件动作的目标变量必须 `writable=true`（doc_service 引用校验，422）。

### 7.2 虚拟变量

- `VariableDef.expr: str | null` 非空即为虚拟变量，此时 `datasourceId` 必须为哨兵 `'virtual'`（不入 datasources 数组，doc_service 校验特判）。
- 表达式引用其它变量 **key**，前端引擎（`utils/expr.ts` 白名单文法，非 eval）求值：`+ - * / %`、比较、`&& || !`、三元、内置 `abs/min/max/floor/ceil/round/pow/sqrt`。
- 依赖图前向传播：任一变量变化 → 传递闭包内的虚拟变量按拓扑序重算；循环引用按出现序求值并 warn（不死循环）。
- 虚拟变量不可写（write 拒绝）；换算流水（scale/offset）对其不生效（表达式产出即工程值）。

### 7.3 事件与行为（ComponentNode.events）

```ts
interface NodeEventDef { id; trigger: 'click'|'dblclick'|'contextmenu'; actions: EventActionDef[] }
interface EventActionDef {
  type: 'writeVar'|'showPopup'|'hidePopup'|'switchPage'|'openUrl'|'toggleVisible'
  variableId?; value?; targetId?; pageId?; url?
}
```

- 运行态生效（编辑态不响应）；`writeVar` 的 `value` 支持表达式（求值失败按原字符串写入）。
- 引用校验：writeVar→变量存在且 writable；showPopup/hidePopup/toggleVisible→目标组件存在；switchPage→页面存在；openUrl→url 非空。

### 7.4 悬停信息与弹框

- `ComponentNode.tooltip: { enabled, template }`：模板占位 `{变量key}` 运行态实时替换（el-tooltip）。
- `ComponentNode.popup: { style: 'dialog'|'menu', title?, triggerExpr? }`：**仅 group**（非 group 配 popup → 422）。
  - 运行态默认隐藏；事件动作（showPopup/hidePopup/toggleVisible）经覆盖层控制显隐。
  - `triggerExpr` 条件弹框：表达式真值时自动显示（与事件动作独立生效，同为覆盖层通道）。
  - 显示时带全页遮罩（dialog 半透明 / menu 透明仅拦截外点关闭），弹框组 z 抬升至 9000 段。

### 7.5 动效扩展

- `ComponentAnimations.move: { enabled, path(SVG path，相对组件原点), periodMs, mode:'loop'|'pingpong' }`：CSS Motion Path 轨迹运动。
- 绑定目标路径新增动效通道（§2.8 四类扩为五类）：
  `anim.rotateOn | anim.rotatePeriod | anim.flowOn | anim.blinkOn | anim.moveOn`（仅 mode='value'；优先级高于静态 animations，符合 K12）。
- `ScreenCfg.lockPan: bool = false`：运行态锁定画面（禁滚动/拖拽，BY「不让实时画面移动」）。

### 7.6 M7 新组件（props 由 registry schema 驱动）

| type | 说明 | 关键 props |
|---|---|---|
| var-display | 变量值显示（前缀/精度/单位） | prefix/precision/unit，绑 props.value |
| state-text | 多状态文本（枚举→文本+色） | states(JSON)/defaultText，绑 props.value |
| switch | 开关（读写一体反控） | variableId/onValue/offValue/confirm/label |
| multi-switch | 多档开关（反控） | variableId/levels(JSON) |
| input-cmd | 输入框指令（反控） | variableId/placeholder/unit/buttonText/clearAfter |
| tank | 水池（液位动画） | percent(绑)/wave |
| flow-bar | 流动条（变量控流速/方向） | speed(绑，0=停)/showArrow/vertical |
| image-switch | 变量驱动图片切换 | images(JSON)/alt，绑 props.value |
| web-frame | 网页 iframe 嵌入 | url/sandbox |
| video | HTML5 视频（RTSP 需流媒体网关转封装） | url/autoPlay/muted/loop/controls |
| weather | 天气（open-meteo，无 key） | city/lat/lon |
| clock | 日期时钟 | showDate/showSeconds/layout |
| history-chart | 历史图表（分钟桶 localStorage 持久化，1h/6h/24h/3d） | variableId/title/unit/rangeMs/compact（隐坐标轴）/live（引擎内存近 60 点实时滚动，启动即有曲线） |
| breaker/isolator/ground/ct/pt/transformer | 二次接线单线图符号 | 颜色走 style.color（--dev-color） |

### 7.7 历史数据（浏览器本地）

（**M8 修订**：历史权威来源已迁移服务端——`history_values` 表 + `GET /api/v1/projects/{id}/history`，见 §4.1.1 与 03-接口清单 §2.10；历史图表组件接服务端 API。本节浏览器本地分钟桶缓冲降级为演示案例/离线预览用途，不再是权威数据源。）

`runtime/history.ts`：分钟桶 `[tsMin, sum, n]` 均值环形缓冲；单变量 3 天 / 全局 12 万桶上限；`webscada:hist:v1` 持久化（10s 节流落盘，beforeunload 兜底）。

### 7.8 画面嵌入

- 分享页 `/s/:token?embed=1`：隐藏标题栏纯画面嵌入（iframe 场景）；恒只读。
- `RuntimeStage` props：`writable`（写通道开关，分享页恒 false）、`embed`（隐藏标题栏）。

### 7.9 演示案例集（对齐业界主流组态 演示站）

工程管理页「演示案例」按钮可一键生成 6 个开箱即用案例（单一 mock 数据源，可直接预览/分享）：
生成器在 `web/src/utils/demos/`，`index.ts` 的 `DEMO_CASES` 为清单。

| 案例 | 覆盖能力 |
|---|---|
| 案例一 · 污水处理系统（1920×1080） | 水池液位、泵旋转启停、管道流动、状态文本、仪表、趋势/历史图、报警、悬停信息、右键菜单弹框、条件弹框（pH>9.5 自动弹出）、输入框指令、开关反控、画面锁定 |
| 案例二 · 电力系统（单线图） | 二次接线图元全套（PT/断路器/CT/隔离/接地/变压器）、母线、分闸闪烁（anim.blinkOn 区间绑定）、遥测仪表、右键分合闸菜单、遥控写前确认 |
| 案例三 · 轨迹运动 | 小车匀速循环、小球抛物线往返（move pingpong）、风机变量控转速（anim.rotatePeriod）、传送带流动、hold 反控开关 |
| 案例四 · 移动端（375×812 / 812×375 双页） | 自定义分辨率、时钟/天气、水箱、开关/多档/输入框、紧凑 live 迷你趋势、画面锁定 |
| 案例五 · MQTT 通讯测试 | 订阅回读、发布写入、链路状态、报文曲线、writeVar/openUrl 事件（mock 回环演示同一条链路） |
| 案例六 · 反控指令集（双页） | 多档开关、confirm 开关、输入框指令、档位控转速、switchPage、showPopup/hidePopup/toggleVisible、右键菜单、条件弹框、悬停信息 |

案例遵守与产品一致的口径：文案不提及具体商业产品；引用第三方数据（天气 open-meteo）实时获取。

### 7.10 关键实现约束（M7 踩坑留档）

- `RuntimeStage` 的 `writable` 必须用 `withDefaults(..., { writable: true })`：Vue 对 Boolean 类型 prop 未传时转换为 `false`，否则编辑器预览会被误判为只读。
- 运行态必须挂载**全部**节点（不可在 `v-for` 里按 `visible` 过滤）：静态 `visible:false` 的组件需要能被子图事件 `toggleVisible` 重新显示。
- 弹框遮罩 `z-index:-1`（父节点已建栈上下文）：正值会盖住弹框内容导致按钮不可点。
- ECharts 数据数组必须传**副本**（`historyOf` 返回 `[...]`）：引擎内部数组原地 push，传引用时调用方 ref 赋值得不到响应式更新，图表会停在首次快照。
- 编辑态画布与运行态 Overlay 的 DOM 同时存在，自动化测试/选择器需限定 `.runtime-stage` 作用域。

## 8. M9 增量契约（行业图元库）

> M9 批次1 对标业界主流组态「图元图库」引入。**WidgetType 新增可选值 + 组件 props 可选字段，旧 doc 不含即不受影响，schemaVersion 不变（仍为 1）**。
> 双端实现：`web/src/types/doc.ts` ↔ `server/app/schemas/doc.py`；资产层仅前端（服务端不加载 SVG）。

### 8.1 symbol 组件（通用图元载体）

- `type: 'symbol'`，props：`symbolId: str`（资产 id，格式 `<分类>/<名称>`，如 `valve/globe`；缺失时组件灰显「图元缺失」占位）。
- 颜色走 `style.color` → `--dev-color`（与设备类 SVG 同一取色通道），color 绑定/报警态驱动变色，无需状态帧字段。
- 资产层（前端唯一实现点）：`web/src/assets/symbols/`
  - 目录即分类（9 大类）：valve / pump / tank / hvac / pipe-fitting / wtp / power / instrument / misc，首批 68 个**全自绘** SVG（版权红线：禁止第三方素材）。
  - `import.meta.glob('./*/*.svg', eager)` 收集，新增 SVG 文件零代码注册；中文名登记于 index.ts 的 `NAME_MAP`。
  - defaultSize 按 viewBox 宽高比推导（最长边 120px 等比）。
- 拖放协议增量：dataTransfer `application/x-widget` 载荷支持复合值 `'symbol|<symbolId>'`（普通组件仍为纯 type）；`editor.addComponent(type, x, y, extraProps?)` 第四参覆盖默认 props（symbol 场景同时覆盖节点名/尺寸）。

### 8.2 我的图元（批次2，ProjectDoc.assets）

- `ProjectDoc.assets?: { mySymbols: MySymbolDef[] }`——**可选字段，旧 doc 缺省视为空库，schemaVersion 不变（1）**。
  按既有惯例（§7 全量可选字段先例），不为纯增量字段制造 N-1 迁移窗口。
- `MySymbolDef: { id, label, nodes: ComponentNode[], createdAt }`：保存时选中集**展平**（group 经 flattenGroup
  还原绝对坐标）并归一化到包围盒原点；插入画布时整体经 `_cloneWithNewIds` 重映射 id（事件 targetId 引用语义同粘贴）。
- 资产库非画布内容：不入页面撤销栈，仅标脏保存。跨工程共享为后手（需用户级资产表，本期不做）。

### 8.3 画面装饰与模板（批次3）

- `WidgetType` +`'title-bar'`（props: text/align；category 'decor'，registry 第四分组）。
- decor 装饰件走 symbol 资产 `decor/` 分类（边框/容器框/分隔线/底纹等，7 个），无需新类型。
- 画面模板（`web/src/utils/pageTemplates/`，前端唯一实现点）：面板「模板」Tab 一键新建整页，
  `editor.applyPageTemplate(name, page)`；模板为静态占位布局（无绑定），4 个：大屏总览 / 单线图框架 /
  双栏控制面板 / 移动端竖屏。

### 8.4 表达式函数库扩容 + 内置 _tick（批次4）

- BUILTINS 新增（前端 expr.ts ↔ 服务端 expr_eval.py 同构，JS 语义对齐点见 expr_eval 注释）：
  `sin/cos/tan/asin/acos/atan/atan2/exp/log/clamp(x,lo=0,hi=1)/sign`。
- 内置秒节拍变量 **`_tick`**（key 以下划线开头，与用户命名空间隔离）：
  - 服务端：hub.set_doc 注册哨兵 VariableDef（stale 永不触发，timeout=0）；runtime_boot `_tick_loop` 每秒
    `hub.tick_all()` 推进（值=unix 秒，变化广播 + 依赖级联重算）。
  - 前端：引擎 start 注册同名变量；本地（编辑器直连）模式引擎定时器推进，server 模式收 WS 帧应用。
  - 用途：虚拟变量 expr / 条件弹框表达式引用 `_tick` 即获得每秒重算（定时脚本等价物，无脚本引擎风险）。
  - 不入变量绑定下拉（不在 doc.variables），仅表达式可引用。

### 8.5 画面方向强制（批次5）

- `ScreenCfg.orientation: 'auto' | 'landscape' | 'portrait'`（默认 auto，双端 schema 同步）。
- 运行态 RuntimeStage：视口方向与设定不符时页面 `rotate(90deg)`，外层 wrap 按旋转后占位（宽高=设计尺寸
  互换 × 缩放），自适应规则按旋转后视口计算；编辑态不旋转。分享页/全屏同样生效。

### 8.6 拖放协议增量（批次1/2 合并口径）

- dataTransfer `application/x-widget`（+ text/plain 兜底）载荷三形态：
  纯 type（注册组件）/ `symbol|<symbolId>`（图元库）/ `mysym|<资产id>`（我的图元）。
- `editor.addComponent(type, x, y, extraProps?)` 第四参覆盖默认 props（symbol 场景同时覆盖节点名/尺寸）。
