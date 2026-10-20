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


# ================= 数据源（四类，discriminated union） =================

class MqttConfig(DocModel):
    brokerUrl: str = Field(min_length=1, max_length=512)
    username: str | None = Field(default=None, max_length=128)   # 不脱敏（G6）
    password: str | None = None                                  # 敏感：出口脱敏 / 库内加密
    topics: list[str] = Field(min_length=1)                      # 只订阅、绝不发布
    qos: Literal[0, 1] = 0
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


class MockConfig(DocModel):
    # mock 数据生成的启停即 enabled 字段（G13：不设独立开关端点/表列）
    defaultIntervalMs: int = Field(default=1000, ge=100)


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


DataSource = Annotated[
    Union[MqttDataSource, WebsocketDataSource, RestDataSource, MockDataSource],
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


MockSpec = Annotated[
    Union[MockSine, MockRamp, MockRandom, MockSquare],
    Field(discriminator="kind"),
]

# 变量 key 字符集（工程内唯一、创建后不可改；如 reactor1_temp / line1.motor01.speed）
_VAR_KEY_RE = re.compile(r"^[A-Za-z0-9_.\-]+$")


class VariableDef(DocModel):
    id: str = _ID
    key: str = Field(min_length=1, max_length=128, pattern=_VAR_KEY_RE)
    label: str = _NAME128
    type: Literal["number", "boolean", "string"]
    unit: str | None = Field(default=None, max_length=32)
    range: VarRange | None = None
    defaultValue: float | bool | str | None = None
    datasourceId: str = _ID
    # 取数地址：mqtt=topic；websocket=帧内定位键；rest=响应内定位键；mock 忽略
    address: str = Field(default="", max_length=512)
    jsonPath: str | None = Field(default=None, max_length=256)
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
        # 02 §2.13 规则 5：bitIndex 仅允许 boolean/number，且与 scale/offset/precision 互斥
        if self.bitIndex is not None:
            if self.type == "string":
                raise ValueError("bitIndex 不允许配合 string 类型变量")
            if any(v is not None for v in (self.scale, self.offset, self.precision)):
                raise ValueError("bitIndex 与 scale/offset/precision 互斥，不可同时配置")
        return self


# ================= 页面与组件 =================

STYLE_KEYS = {"fill", "stroke", "strokeWidth", "borderRadius", "color", "fontSize", "fontWeight", "textAlign"}
# 绑定目标路径语法（02 §2.8）：props.* / style.* / visible / opacity 四类
_PROP_PATH_RE = re.compile(r"^(props\.[A-Za-z0-9_]+|style\.[A-Za-z]+|visible|opacity)$")

WidgetType = Literal[
    # 基础类
    "text", "image", "table", "button", "carousel",
    # 图表类
    "flip-counter", "line-chart", "bar-chart", "pie-chart", "gauge", "progress", "trend-chart",
    # 设备类（SVG）
    "status-light", "motor", "pump", "valve", "pipe",
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


class ComponentAnimations(DocModel):
    blink: BlinkCfg | None = None
    flow: FlowCfg | None = None
    rotate: RotateCfg | None = None


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
            raise ValueError(f"绑定目标路径非法：{v}（语法为 props.*/style.*/visible/opacity 四类）")
        # 02 §2.13 规则 5：style.* 目标键必须属于 ComponentStyle 键集
        if v.startswith("style.") and v.split(".", 1)[1] not in STYLE_KEYS:
            raise ValueError(f"style 目标键非法：{v}（允许：{'/'.join(sorted(STYLE_KEYS))}）")
        return v

    @model_validator(mode="after")
    def _check_mode_rules(self) -> "Binding":
        # 02 §2.13 规则 5：mode 与目标路径的匹配约束
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
    children: list["ComponentNode"] | None = None          # 仅 type='group'

    @model_validator(mode="after")
    def _check_children(self) -> "ComponentNode":
        if self.children and self.type != "group":
            raise ValueError("仅 group 类型组件可以包含 children")
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
