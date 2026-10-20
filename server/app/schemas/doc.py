"""工程 JSON 契约（Pydantic v2）——与前端 web/src/types/doc.ts 同构镜像。

契约权威版：docs/design/02-工程JSON数据结构.md；改动必须双侧同步并跑 round-trip 测试。
约定：
- extra='ignore'：容忍未知字段（M0 风险对策：避免前向兼容的合法导入被过严拒绝）
- 跨对象引用完整性（引用存在性/唯一性/变量类型约束）不在本文件，见 doc_service.validate_references
  （需要跨对象上下文，无法用单模型校验表达）
"""
import re
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# doc 内部对象 id 长度上限（02 §2.13 规则 6：统一 64 字符）
_ID = Field(min_length=1, max_length=64)
# 显示名长度上限（02 §2.13 规则 6）
_NAME128 = Field(min_length=1, max_length=128)


class DocModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


# ================= 全局配置 =================

AdaptiveMode = Literal["fixed", "fit-width", "fit-height", "fit-contain", "stretch"]


class DesignSize(DocModel):
    width: int = Field(ge=200, le=7680)
    height: int = Field(ge=200, le=4320)


class LevelColors(DocModel):
    info: str = "#3b82f6"
    warn: str = "#f59e0b"
    critical: str = "#ef4444"


class AlarmSettings(DocModel):
    """报警声音/级别设置（G14：存 doc.settings.alarm，随工程 doc 保存，无独立端点）。"""

    levelColors: LevelColors = Field(default_factory=LevelColors)
    soundEnabled: bool = True
    # 同一规则提示音节流秒数（默认 60，前端报警条遵守）
    soundThrottleSec: int = Field(default=60, ge=1, le=3600)


class ProjectSettings(DocModel):
    designSize: DesignSize = Field(default_factory=lambda: DesignSize(width=1920, height=1080))
    adaptive: AdaptiveMode = "fit-contain"
    theme: Literal["blue-dark", "blue-light"] = "blue-dark"
    primaryColor: str = "#2563eb"
    alarm: AlarmSettings = Field(default_factory=AlarmSettings)


class ProjectMeta(DocModel):
    """工程元信息。id 为 UUID（服务端生成；格式与一致性校验在 doc_service，规则 4）。"""

    id: str
    name: str = _NAME128
    description: str | None = None
    author: str | None = None
    createdAt: str  # ISO8601
    updatedAt: str  # ISO8601；不作为乐观锁依据（乐观锁 = projects.revision，G2）
    # 台账卡片缩略图（编辑器保存前截图写入，JPEG dataURL 展示缓存）：
    # 出口统一剔除（utils/sanitize），仅 /projects 列表项按需读出
    thumbnail: str | None = Field(default=None, max_length=300_000)


# ================= 数据源（四类，discriminated union） =================

class MqttConfig(DocModel):
    brokerUrl: str = Field(min_length=1, max_length=512)
    username: str | None = Field(default=None, max_length=128)   # 不脱敏（G6）
    password: str | None = None                                  # 敏感：出口脱敏 / 库内加密
    topics: list[str] = Field(min_length=1)                      # 订阅 topic
    qos: Literal[0, 1] = 0
    writeQos: Literal[0, 1] = 0                                  # 反控写入 QoS（M7；写 topic 取变量 writeAddress）
    # 导入时强制重置 true（02 §1 边界第 7 条：防离线消息回放风暴）
    cleanSession: bool = True
    reconnectMinMs: int = Field(default=1000, ge=100)
    reconnectMaxMs: int = Field(default=30000, ge=1000)
    staleTimeoutMs: int | None = Field(default=None, ge=1000)
    tsPath: str | None = None                                    # 载荷时间戳点路径（G26）


class WebsocketConfig(DocModel):
    url: str = Field(min_length=1, max_length=1024)
    headers: dict[str, str] | None = None                        # 敏感键脱敏（G6）
    subscribeFrame: str | None = None
    heartbeatSec: int | None = Field(default=None, ge=1)
    reconnectMinMs: int = Field(default=1000, ge=100)
    reconnectMaxMs: int = Field(default=30000, ge=1000)
    staleTimeoutMs: int | None = Field(default=None, ge=1000)
    tsPath: str | None = None
    writeFrameTemplate: str | None = Field(default=None, max_length=2048)  # 反控写入帧模板，占位 {key} {value}


class RestConfig(DocModel):
    url: str = Field(min_length=1, max_length=1024)
    method: Literal["GET", "POST"] = "GET"
    intervalMs: int = Field(ge=500)                              # 轮询下限 500ms（校验拦截更小值）
    headers: dict[str, str] | None = None                        # 敏感键脱敏（G6）
    body: str | None = None
    timeoutMs: int = Field(default=5000, ge=500, le=60000)
    failureBackoffMs: int | None = Field(default=None, ge=500)
    staleTimeoutMs: int | None = Field(default=None, ge=1000)
    tsPath: str | None = None
    writeUrl: str | None = Field(default=None, max_length=1024)      # 反控写入端点（M7；无则不可写）
    writeMethod: Literal["POST", "PUT"] | None = None
    writeBodyTemplate: str | None = Field(default=None, max_length=2048)  # 占位 {key} {value}


class MockConfig(DocModel):
    # mock 数据生成的启停即 enabled 字段（G13：不设独立开关端点/表列）
    defaultIntervalMs: int = Field(default=1000, ge=100)


class ModbusConfig(DocModel):
    """Modbus TCP（M8 阶段 1 后半）：变量 address 用 Modbus 惯用区位十进制字符串——
    4xxxx=保持寄存器 / 3xxxx=输入寄存器 / 0xxxx(含 5 位补零)=线圈 / 1xxxx=离散输入。
    Modbus TCP 协议自身无账号体系（UnitId 即从站标识），无敏感字段。"""

    host: str = Field(min_length=1, max_length=253)
    port: int = Field(default=502, ge=1, le=65535)
    unitId: int = Field(default=1, ge=0, le=255)
    intervalMs: int = Field(default=1000, ge=100)               # 轮询下限 100ms
    timeoutMs: int = Field(default=3000, ge=500, le=60000)
    staleTimeoutMs: int | None = Field(default=None, ge=1000)


class _DsBase(DocModel):
    id: str = _ID
    name: str = _NAME128
    enabled: bool = True


class MqttDataSource(_DsBase):
    type: Literal["mqtt"]
    config: MqttConfig


class WebsocketDataSource(_DsBase):
    type: Literal["websocket"]
    config: WebsocketConfig


class RestDataSource(_DsBase):
    type: Literal["rest"]
    config: RestConfig


class MockDataSource(_DsBase):
    type: Literal["mock"]
    config: MockConfig = Field(default_factory=MockConfig)


class ModbusDataSource(_DsBase):
    type: Literal["modbus"]
    config: ModbusConfig


DataSource = Annotated[
    Union[MqttDataSource, WebsocketDataSource, RestDataSource, MockDataSource, ModbusDataSource],
    Field(discriminator="type"),
]


# ================= 变量字典 =================

class VarRange(DocModel):
    """量程：仪表盘/进度条缺省刻度来源，不做数据校验（02 §2.9）。"""

    min: float
    max: float


class MockSine(DocModel):
    kind: Literal["sine"]
    min: float
    max: float
    periodMs: int = Field(ge=100)


class MockRamp(DocModel):
    kind: Literal["ramp"]
    min: float
    max: float
    periodMs: int = Field(ge=100)


class MockRandom(DocModel):
    kind: Literal["random"]
    min: float
    max: float
    intervalMs: int = Field(ge=100)


class MockSquare(DocModel):
    kind: Literal["square"]
    onValue: float
    offValue: float
    periodMs: int = Field(ge=100)
    duty: float = Field(default=0.5, ge=0.0, le=1.0)


class MockHold(DocModel):
    """保持型：不周期推送，仅初始 defaultValue；写入回环后保持（M7 反控演示/受控开关量）。"""

    kind: Literal["hold"]


MockSpec = Annotated[
    Union[MockSine, MockRamp, MockRandom, MockSquare, MockHold],
    Field(discriminator="kind"),
]

# 变量 key 字符集（工程内唯一、创建后不可改；如 reactor1_temp / line1.motor01.speed）
_VAR_KEY_RE = re.compile(r"^[A-Za-z0-9_.\-]+$")

# 虚拟变量哨兵 datasourceId（M7）：expr 非空时固定此值，不入 datasources 数组
VIRTUAL_DATASOURCE_ID = "virtual"


class VariableDef(DocModel):
    id: str = _ID
    key: str = Field(min_length=1, max_length=128, pattern=_VAR_KEY_RE)
    label: str = _NAME128
    type: Literal["number", "boolean", "string"]
    unit: str | None = Field(default=None, max_length=32)
    range: VarRange | None = None
    defaultValue: float | bool | str | None = None
    datasourceId: str = _ID
    # 取数地址：mqtt=topic；websocket=帧内定位键；rest=响应内定位键；mock 忽略；
    # modbus=Modbus 区位十进制字符串（4xxxx 保持寄存器/3xxxx 输入寄存器/0xxxx 线圈/1xxxx 离散输入）
    address: str = Field(default="", max_length=512)
    jsonPath: str | None = Field(default=None, max_length=256)
    # ---- 反控（M7）：写通道经浏览器直连数据源，writable 变量才可写 ----
    writable: bool = False
    writeAddress: str | None = Field(default=None, max_length=512)   # mqtt 写 topic；缺省回落 address
    # ---- 虚拟变量（M7）：表达式引用其它变量 key，前端引擎求值 ----
    expr: str | None = Field(default=None, max_length=2048)
    # ---- 变量级换算（G3：服务端入池前一次执行；与 bitIndex 互斥） ----
    scale: float | None = None
    offset: float | None = None
    precision: int | None = Field(default=None, ge=0, le=6)
    # 位提取：raw=(ToInt(raw)>>bitIndex)&1，提取后仍按 type 规范化（02 §2.9 换算流水）
    bitIndex: int | None = Field(default=None, ge=0, le=63)
    mock: MockSpec | None = None                                  # 仅所属数据源 type='mock' 时生效
    description: str | None = Field(default=None, max_length=512)

    @model_validator(mode="after")
    def _check_transform_rules(self) -> "VariableDef":
        # M7：虚拟变量 datasourceId 哨兵约束
        if self.expr is not None and self.datasourceId != VIRTUAL_DATASOURCE_ID:
            raise ValueError("配置 expr 的虚拟变量 datasourceId 必须为 'virtual'")
        # 02 §2.13 规则 5：bitIndex 仅允许 boolean/number，且与 scale/offset/precision 互斥
        if self.bitIndex is not None:
            if self.type == "string":
                raise ValueError("bitIndex 不允许配合 string 类型变量")
            if any(v is not None for v in (self.scale, self.offset, self.precision)):
                raise ValueError("bitIndex 与 scale/offset/precision 互斥，不可同时配置")
        return self


# ================= 页面与组件 =================

STYLE_KEYS = {"fill", "stroke", "strokeWidth", "borderRadius", "color", "fontSize", "fontWeight", "textAlign"}
# 绑定目标路径语法（02 §2.8 + M7 动效通道）：props.* / style.* / visible / opacity / anim.*
_ANIM_PATHS = {"anim.rotateOn", "anim.rotatePeriod", "anim.flowOn", "anim.blinkOn", "anim.moveOn"}
_PROP_PATH_RE = re.compile(r"^(props\.[A-Za-z0-9_]+|style\.[A-Za-z]+|visible|opacity|anim\.(rotateOn|rotatePeriod|flowOn|blinkOn|moveOn))$")

WidgetType = Literal[
    # 基础类
    "text", "image", "rect", "circle", "line", "table", "button", "carousel",
    # 图表类
    "flip-counter", "line-chart", "bar-chart", "pie-chart", "gauge", "progress", "trend-chart",
    # 设备类（SVG）
    "status-light", "motor", "pump", "valve", "pipe",
    # M7 新增（对齐 BY组态）
    "var-display", "state-text", "switch", "multi-switch", "input-cmd",
    "tank", "flow-bar", "image-switch", "web-frame", "video", "weather", "clock", "history-chart",
    "breaker", "isolator", "ground", "ct", "pt", "transformer",
    # 结构
    "group",
]


class PageBackground(DocModel):
    color: str = "#0b1220"
    image: str | None = None   # 外链 URL（P0 不做资源上传）


class ScreenCfg(DocModel):
    designWidth: int = Field(ge=200, le=7680)
    designHeight: int = Field(ge=200, le=4320)
    mode: AdaptiveMode
    lockPan: bool = False   # M7：运行态锁定画面（禁止滚动/拖拽）


class ComponentStyle(DocModel):
    """通用外观（可选键；未设置的键回落 props 内置默认值）。"""

    fill: str | None = None
    stroke: str | None = None
    strokeWidth: float | None = Field(default=None, ge=0)
    borderRadius: float | None = Field(default=None, ge=0)
    color: str | None = None
    fontSize: float | None = Field(default=None, gt=0)
    fontWeight: float | None = Field(default=None, ge=100, le=900)
    textAlign: Literal["left", "center", "right"] | None = None


class BlinkCfg(DocModel):
    enabled: bool
    intervalMs: int = Field(ge=50)


class FlowCfg(DocModel):
    """管道流动：仅 pipe 生效。"""

    enabled: bool
    speed: float = Field(ge=0)  # px/s


class RotateCfg(DocModel):
    """旋转：仅 motor/pump 生效；运行态启停规则见 02 §2.5（state===1 才转）。"""

    enabled: bool
    clockwise: bool = True
    periodMs: int = Field(ge=50)


class MoveCfg(DocModel):
    """轨迹运动（M7）：沿 SVG path 位移（CSS offset-path），坐标相对组件原点。"""

    enabled: bool
    path: str = Field(default="", max_length=2048)   # 如 "M 0 0 L 300 0 L 300 200"
    periodMs: int = Field(default=8000, ge=100)
    mode: Literal["loop", "pingpong"] = "loop"


class ComponentAnimations(DocModel):
    blink: BlinkCfg | None = None
    flow: FlowCfg | None = None
    rotate: RotateCfg | None = None
    move: MoveCfg | None = None


# ---- 映射（enum / range，02 §2.8）----

class EnumMapping(DocModel):
    kind: Literal["enum"]
    # 查表键为变量工程值的字符串化形式：{'1': '#22c55e', '0': '#64748b'}
    map: dict[str, Union[str, bool]] = Field(min_length=1)


class RangeBand(DocModel):
    min: float | None = None   # 缺省 = 负无穷
    max: float | None = None   # 缺省 = 正无穷（最后一档）
    value: Union[str, bool]


class RangeMapping(DocModel):
    kind: Literal["range"]
    # 闭开区间 [min, max)，升序书写，先命中先生效
    bands: list[RangeBand] = Field(min_length=1)


ValueMapping = Annotated[Union[EnumMapping, RangeMapping], Field(discriminator="kind")]


class Binding(DocModel):
    id: str = _ID
    prop: str = Field(min_length=1, max_length=128)
    variableId: str = _ID
    mode: Literal["value", "color", "visibility"]
    # color 必填（缺省 422）；value 缺省=直接赋工程值；visibility 缺省=按真值回退
    mapping: ValueMapping | None = None

    @field_validator("prop")
    @classmethod
    def _check_prop_path(cls, v: str) -> str:
        if not _PROP_PATH_RE.match(v):
            raise ValueError(f"绑定目标路径非法：{v}（语法为 props.*/style.*/visible/opacity/anim.* 五类）")
        # 02 §2.13 规则 5：style.* 目标键必须属于 ComponentStyle 键集
        if v.startswith("style.") and v.split(".", 1)[1] not in STYLE_KEYS:
            raise ValueError(f"style 目标键非法：{v}（允许：{'/'.join(sorted(STYLE_KEYS))}）")
        return v

    @model_validator(mode="after")
    def _check_mode_rules(self) -> "Binding":
        # 02 §2.13 规则 5：mode 与目标路径的匹配约束
        if self.prop in _ANIM_PATHS and self.mode != "value":
            raise ValueError(f"动效绑定 {self.prop} 仅允许 mode='value'")
        if self.mode == "color":
            # 颜色类目标固定为 style.fill/stroke/color 三键
            if not re.match(r"^style\.(fill|stroke|color)$", self.prop):
                raise ValueError(f"color 绑定的目标必须是颜色类路径（style.fill/stroke/color），当前：{self.prop}")
            if self.mapping is None:
                raise ValueError("color 绑定必须配置 mapping（enum/range）")
            # color 映射值必须是合法颜色串（复查 minor 修复：防任意字符串入库后前端着色失效）
            values: list[str] = (
                list(self.mapping.map.values())
                if self.mapping.kind == "enum"
                else [str(b.value) for b in self.mapping.bands]
            )
            for v in values:
                if not re.match(r"^#[0-9a-fA-F]{3,8}$", v):
                    raise ValueError(f"color 映射值必须是 #RGB/#RRGGBB 颜色串，当前：{v}")
        if self.mode == "visibility" and self.prop != "visible":
            raise ValueError("visibility 绑定的目标必须是 visible")
        return self


# ---- 事件与行为 / 悬停信息 / 弹框（M7，对齐 BY组态） ----

class EventActionDef(DocModel):
    type: Literal["writeVar", "showPopup", "hidePopup", "switchPage", "openUrl", "toggleVisible"]
    variableId: str | None = None      # writeVar：目标变量（引用校验在 doc_service）
    value: str | None = Field(default=None, max_length=2048)  # writeVar：写入值（支持表达式）
    targetId: str | None = None        # showPopup/hidePopup/toggleVisible：目标组件 id
    pageId: str | None = None          # switchPage：目标页面 id
    url: str | None = Field(default=None, max_length=2048)    # openUrl


class NodeEventDef(DocModel):
    id: str = _ID
    trigger: Literal["click", "dblclick", "contextmenu"]
    actions: list[EventActionDef] = Field(min_length=1)


class TooltipCfg(DocModel):
    """悬停信息：模板占位 {变量key}，运行态实时替换。"""

    enabled: bool = True
    template: str = Field(default="", max_length=2048)


class PopupCfg(DocModel):
    """弹框容器：仅 group；运行态默认隐藏，事件动作/triggerExpr 控制显隐。"""

    style: Literal["dialog", "menu"] = "dialog"
    title: str | None = Field(default=None, max_length=128)
    triggerExpr: str | None = Field(default=None, max_length=2048)  # 条件弹框表达式


class ComponentNode(DocModel):
    """组件节点（普通图元与 group 同构；组内坐标为相对组原点）。"""

    id: str = _ID
    name: str = _NAME128
    type: WidgetType
    x: float
    y: float
    w: float = Field(ge=1)
    h: float = Field(ge=1)
    rotate: float = Field(default=0, ge=0, lt=360)
    z: int  # 图层序，大者在上；组整体占一个 z 位
    visible: bool = True
    locked: bool = False
    opacity: float = Field(default=1, ge=0, le=1)
    props: dict[str, Any] = Field(default_factory=dict)   # 组件私有属性（registry schema 驱动）
    style: ComponentStyle | None = None
    animations: ComponentAnimations | None = None
    bindings: list[Binding] = Field(default_factory=list)
    events: list[NodeEventDef] | None = None              # M7：事件与行为
    tooltip: TooltipCfg | None = None                     # M7：悬停信息
    popup: PopupCfg | None = None                         # M7：弹框容器（仅 group）
    children: list["ComponentNode"] | None = None          # 仅 type='group'

    @model_validator(mode="after")
    def _check_children(self) -> "ComponentNode":
        if self.children and self.type != "group":
            raise ValueError("仅 group 类型组件可以包含 children")
        if self.popup is not None and self.type != "group":
            raise ValueError("仅 group 类型组件可以配置 popup")
        return self


class Page(DocModel):
    id: str = _ID
    name: str = _NAME128
    order: int = 0   # 多页切换顺序，越小越前
    background: PageBackground = Field(default_factory=PageBackground)
    screen: ScreenCfg
    components: list[ComponentNode] = Field(default_factory=list)


# ================= 报警规则 =================

class AlarmRule(DocModel):
    id: str = _ID
    name: str = _NAME128
    variableId: str = _ID
    op: Literal[">", ">=", "<", "<=", "==", "!="]
    threshold: float  # 口径=工程值（换算后），与界面显示一致（G3）
    level: Literal["info", "warn", "critical"]
    # 支持占位符 {key} {label} {value} {threshold}；value 为工程值
    message: str = Field(min_length=1, max_length=512)
    enabled: bool = True
    hysteresis: float | None = Field(default=None, ge=0)   # 回差带，防临界抖动
    durationMs: int | None = Field(default=None, ge=0)     # 持续满足才触发；0/缺省=立即
    sound: bool | None = None                              # 且 settings.alarm.soundEnabled 为 true 才生效
    # 恢复策略：P0 固定自动恢复（越过回差带即恢复；ack 属 P1 预留）


# ================= 顶层 =================

class ProjectDoc(DocModel):
    """工程 JSON 顶层结构（契约中心）。schemaVersion 校验在 doc_service（G8：迁移唯一实现点在前端）。"""

    schemaVersion: int
    project: ProjectMeta
    settings: ProjectSettings = Field(default_factory=ProjectSettings)
    datasources: list[DataSource] = Field(default_factory=list)
    variables: list[VariableDef] = Field(default_factory=list)
    pages: list[Page] = Field(min_length=1)   # 至少一个页面
    alarmRules: list[AlarmRule] = Field(default_factory=list)
