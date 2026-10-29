/**
 * 组件注册表（协议核心）：type → 元信息 / 默认 props / 属性面板 schema / 渲染器。
 * 协议在 M2a 冻结：新增组件只增注册项，不改协议形状（P1 能耗温湿度组件零成本挂载）。
 * 服务端不加载本注册表（registry 级校验由前端创建绑定时承担，02 §2.13 职责边界）。
 */
import { markRaw, type Component } from 'vue'
import {
  Calendar,
  Clock,
  Cloudy,
  Collection,
  CollectionTag,
  Compass,
  DataAnalysis,
  Document,
  DataLine,
  EditPen,
  Files,
  Grid,
  Histogram,
  Monitor,
  Odometer,
  Operation,
  Picture,
  PictureFilled,
  PieChart,
  Postcard,
  Switch,
  Tickets,
  Timer,
  TrendCharts,
  VideoCamera,
} from '@element-plus/icons-vue'
import type { WidgetType } from '@/types/doc'
import ButtonWidget from './basic/ButtonWidget.vue'
import CarouselWidget from './basic/CarouselWidget.vue'
import CircleWidget from './basic/CircleWidget.vue'
import ClockWidget from './basic/ClockWidget.vue'
import FlipCounterWidget from './basic/FlipCounterWidget.vue'
import ImageSwitchWidget from './basic/ImageSwitchWidget.vue'
import ImageWidget from './basic/ImageWidget.vue'
import InputCmdWidget from './basic/InputCmdWidget.vue'
import LineWidget from './basic/LineWidget.vue'
import MultiSwitchWidget from './basic/MultiSwitchWidget.vue'
import ProgressWidget from './basic/ProgressWidget.vue'
import RectWidget from './basic/RectWidget.vue'
import StateTextWidget from './basic/StateTextWidget.vue'
import SymbolWidget from './basic/SymbolWidget.vue'
import SwitchWidget from './basic/SwitchWidget.vue'
import TitleBarWidget from './basic/TitleBarWidget.vue'
import TableWidget from './basic/TableWidget.vue'
import TextWidget from './basic/TextWidget.vue'
import VarDisplayWidget from './basic/VarDisplayWidget.vue'
import VideoWidget from './basic/VideoWidget.vue'
import WeatherWidget from './basic/WeatherWidget.vue'
import WebFrameWidget from './basic/WebFrameWidget.vue'
import RealtimeTableWidget from './realtime/RealtimeTableWidget.vue'
import HistoryTableWidget from './realtime/HistoryTableWidget.vue'
import BarChartWidget from './chart/BarChartWidget.vue'
import GaugeWidget from './chart/GaugeWidget.vue'
import HistoryChartWidget from './chart/HistoryChartWidget.vue'
import LineChartWidget from './chart/LineChartWidget.vue'
import PieChartWidget from './chart/PieChartWidget.vue'
import TrendChartWidget from './chart/TrendChartWidget.vue'
import BreakerWidget from './device/electrical/BreakerWidget.vue'
import CtWidget from './device/electrical/CtWidget.vue'
import GroundWidget from './device/electrical/GroundWidget.vue'
import IsolatorWidget from './device/electrical/IsolatorWidget.vue'
import PtWidget from './device/electrical/PtWidget.vue'
import TransformerWidget from './device/electrical/TransformerWidget.vue'
import FlowBarWidget from './device/FlowBarWidget.vue'
import MotorWidget from './device/MotorWidget.vue'
import PipeWidget from './device/PipeWidget.vue'
import PumpWidget from './device/PumpWidget.vue'
import StatusLightWidget from './device/StatusLightWidget.vue'
import TankWidget from './device/TankWidget.vue'
import ValveWidget from './device/ValveWidget.vue'

/** 属性面板表单项类型（PropPanel 据此渲染）；variable=动态变量下拉（editor.doc.variables），
 *  image/imagelist=图片直传（单图 / 换行分隔的多图列表） */
export type PropFieldType =
  | 'text'
  | 'textarea'
  | 'number'
  | 'color'
  | 'select'
  | 'switch'
  | 'variable'
  | 'image'
  | 'imagelist'

export interface PropSchemaItem {
  key: string
  label: string
  type: PropFieldType
  /** select 选项 */
  options?: { label: string; value: string | number }[]
  /** number 的约束 */
  min?: number
  max?: number
  step?: number
  defaultValue: unknown
}

export interface WidgetMeta {
  type: WidgetType
  /** 组件面板显示名 */
  name: string
  /** Element Plus 图标组件（注册时 markRaw）；缺省时面板/图层渲染组件本体缩略图 */
  epIcon?: Component
  category: 'basic' | 'chart' | 'device' | 'decor'
  /** 新建默认尺寸（设计 px） */
  defaultSize: { w: number; h: number }
  /** 默认 props（函数返回，避免共享引用） */
  defaultProps: () => Record<string, unknown>
  /** 属性面板 schema（右侧 PropPanel 渲染） */
  propsSchema: PropSchemaItem[]
  renderer: Component
}

const registry = new Map<WidgetType, WidgetMeta>()

function register(meta: WidgetMeta): void {
  registry.set(meta.type, meta)
}

// ---- M1 验证用基础组件（其余 M2a/M2b/M2c 按同一协议注册） ----

register({
  type: 'text',
  name: '文本',
  epIcon: markRaw(Document),
  category: 'basic',
  defaultSize: { w: 240, h: 48 },
  defaultProps: () => ({ text: '文本内容', ellipsis: true }),
  propsSchema: [
    { key: 'text', label: '文本内容', type: 'textarea', defaultValue: '文本内容' },
    { key: 'ellipsis', label: '超宽省略', type: 'switch', defaultValue: true },
  ],
  renderer: TextWidget,
})

register({
  type: 'rect',
  name: '矩形',
  category: 'basic',
  defaultSize: { w: 200, h: 120 },
  defaultProps: () => ({}),
  propsSchema: [],
  renderer: RectWidget,
})

register({
  type: 'circle',
  name: '圆形',
  category: 'basic',
  defaultSize: { w: 120, h: 120 },
  defaultProps: () => ({}),
  propsSchema: [],
  renderer: CircleWidget,
})

register({
  type: 'line',
  name: '直线',
  category: 'basic',
  defaultSize: { w: 200, h: 2 },
  defaultProps: () => ({}),
  propsSchema: [],
  renderer: LineWidget,
})

register({
  type: 'button',
  name: '按钮',
  category: 'basic',
  defaultSize: { w: 120, h: 40 },
  defaultProps: () => ({ text: '按钮' }),
  propsSchema: [{ key: 'text', label: '按钮文字', type: 'text', defaultValue: '按钮' }],
  renderer: ButtonWidget,
})

register({
  type: 'image',
  name: '图片',
  epIcon: markRaw(Picture),
  category: 'basic',
  defaultSize: { w: 320, h: 200 },
  defaultProps: () => ({ src: '', fit: 'contain' }),
  propsSchema: [
    { key: 'src', label: '图片', type: 'image', defaultValue: '' },
    {
      key: 'fit',
      label: '填充方式',
      type: 'select',
      options: [
        { label: 'contain 留白', value: 'contain' },
        { label: 'cover 裁剪', value: 'cover' },
        { label: 'fill 拉伸', value: 'fill' },
      ],
      defaultValue: 'contain',
    },
  ],
  renderer: ImageWidget,
})

register({
  type: 'table',
  name: '表格',
  epIcon: markRaw(Grid),
  category: 'basic',
  defaultSize: { w: 480, h: 260 },
  defaultProps: () => ({ data: '[["参数", "当前值", "单位"], ["出口温度", "86.5", "℃"], ["进口压力", "0.42", "MPa"]]' }),
  propsSchema: [
    { key: 'data', label: '表格数据（JSON 二维数组，首行为表头）', type: 'textarea', defaultValue: '[]' },
  ],
  renderer: TableWidget,
})

register({
  type: 'carousel',
  name: '轮播',
  epIcon: markRaw(Files),
  category: 'basic',
  defaultSize: { w: 360, h: 240 },
  defaultProps: () => ({ urls: '', intervalSec: 5 }),
  propsSchema: [
    { key: 'urls', label: '图片', type: 'imagelist', defaultValue: '' },
    { key: 'intervalSec', label: '切换间隔（秒）', type: 'number', min: 1, max: 120, step: 1, defaultValue: 5 },
  ],
  renderer: CarouselWidget,
})

// ---- M7 新增（对齐业界主流组态） ----

register({
  type: 'var-display',
  name: '变量',
  epIcon: markRaw(Postcard),
  category: 'basic',
  defaultSize: { w: 220, h: 64 },
  defaultProps: () => ({ prefix: '', unit: '', precision: 2 }),
  propsSchema: [
    { key: 'prefix', label: '前缀', type: 'text', defaultValue: '' },
    { key: 'unit', label: '单位', type: 'text', defaultValue: '' },
    { key: 'precision', label: '小数位', type: 'number', min: 0, max: 6, step: 1, defaultValue: 2 },
  ],
  renderer: VarDisplayWidget,
})

register({
  type: 'state-text',
  name: '状态',
  epIcon: markRaw(CollectionTag),
  category: 'basic',
  defaultSize: { w: 160, h: 48 },
  defaultProps: () => ({
    defaultText: '--',
    states: '[{"value":0,"text":"停止","color":"#909399"},{"value":1,"text":"运行","color":"#67c23a"},{"value":2,"text":"故障","color":"#f56c6c"}]',
  }),
  propsSchema: [
    { key: 'states', label: '状态映射（JSON：value/text/color/background）', type: 'textarea', defaultValue: '[]' },
    { key: 'defaultText', label: '无匹配文案', type: 'text', defaultValue: '--' },
  ],
  renderer: StateTextWidget,
})

register({
  type: 'switch',
  name: '开关（反控）',
  epIcon: markRaw(Switch),
  category: 'basic',
  defaultSize: { w: 120, h: 44 },
  defaultProps: () => ({ variableId: '', onValue: 1, offValue: 0, confirm: false, label: '' }),
  propsSchema: [
    { key: 'variableId', label: '控制变量（须开启可写）', type: 'variable', defaultValue: '' },
    { key: 'onValue', label: '开值', type: 'text', defaultValue: '1' },
    { key: 'offValue', label: '关值', type: 'text', defaultValue: '0' },
    { key: 'confirm', label: '写前确认', type: 'switch', defaultValue: false },
    { key: 'label', label: '标签文字', type: 'text', defaultValue: '' },
  ],
  renderer: SwitchWidget,
})

register({
  type: 'multi-switch',
  name: '多档开关（反控）',
  epIcon: markRaw(Operation),
  category: 'basic',
  defaultSize: { w: 240, h: 44 },
  defaultProps: () => ({
    variableId: '',
    levels: '[{"value":0,"label":"停止"},{"value":1,"label":"低速"},{"value":2,"label":"高速"}]',
  }),
  propsSchema: [
    { key: 'variableId', label: '控制变量（须开启可写）', type: 'variable', defaultValue: '' },
    { key: 'levels', label: '档位（JSON：value/label）', type: 'textarea', defaultValue: '[]' },
  ],
  renderer: MultiSwitchWidget,
})

register({
  type: 'input-cmd',
  name: '输入框指令（反控）',
  epIcon: markRaw(EditPen),
  category: 'basic',
  defaultSize: { w: 280, h: 44 },
  defaultProps: () => ({ variableId: '', placeholder: '输入设定值', unit: '', buttonText: '提交', clearAfter: true }),
  propsSchema: [
    { key: 'variableId', label: '控制变量（须开启可写）', type: 'variable', defaultValue: '' },
    { key: 'placeholder', label: '占位提示', type: 'text', defaultValue: '输入设定值' },
    { key: 'unit', label: '单位后缀', type: 'text', defaultValue: '' },
    { key: 'buttonText', label: '按钮文字', type: 'text', defaultValue: '提交' },
    { key: 'clearAfter', label: '提交后清空', type: 'switch', defaultValue: true },
  ],
  renderer: InputCmdWidget,
})

register({
  type: 'image-switch',
  name: '图片切换',
  epIcon: markRaw(PictureFilled),
  category: 'basic',
  defaultSize: { w: 200, h: 140 },
  defaultProps: () => ({ images: '[{"value":0,"url":""},{"value":1,"url":""}]', alt: '' }),
  propsSchema: [
    { key: 'images', label: '图片映射（JSON：value/url）', type: 'textarea', defaultValue: '[]' },
    { key: 'alt', label: '替代文本', type: 'text', defaultValue: '' },
  ],
  renderer: ImageSwitchWidget,
})

register({
  type: 'web-frame',
  name: '网页',
  epIcon: markRaw(Monitor),
  category: 'basic',
  defaultSize: { w: 480, h: 320 },
  defaultProps: () => ({ url: '', sandbox: 'allow-scripts allow-same-origin allow-forms allow-popups' }),
  propsSchema: [
    { key: 'url', label: '网页 URL', type: 'text', defaultValue: '' },
    { key: 'sandbox', label: 'iframe sandbox', type: 'text', defaultValue: 'allow-scripts allow-same-origin allow-forms allow-popups' },
  ],
  renderer: WebFrameWidget,
})

register({
  type: 'video',
  name: '视频',
  epIcon: markRaw(VideoCamera),
  category: 'basic',
  defaultSize: { w: 400, h: 240 },
  defaultProps: () => ({ url: '', autoPlay: true, muted: true, loop: true, controls: true }),
  propsSchema: [
    { key: 'url', label: '视频 URL（mp4/webm/hls）', type: 'text', defaultValue: '' },
    { key: 'autoPlay', label: '自动播放', type: 'switch', defaultValue: true },
    { key: 'muted', label: '静音', type: 'switch', defaultValue: true },
    { key: 'loop', label: '循环', type: 'switch', defaultValue: true },
    { key: 'controls', label: '控制条', type: 'switch', defaultValue: true },
  ],
  renderer: VideoWidget,
})

register({
  type: 'weather',
  name: '天气',
  epIcon: markRaw(Cloudy),
  category: 'basic',
  defaultSize: { w: 220, h: 90 },
  defaultProps: () => ({ city: '北京', lat: 39.9, lon: 116.4 }),
  propsSchema: [
    { key: 'city', label: '城市名（仅显示）', type: 'text', defaultValue: '北京' },
    { key: 'lat', label: '纬度', type: 'number', step: 0.1, defaultValue: 39.9 },
    { key: 'lon', label: '经度', type: 'number', step: 0.1, defaultValue: 116.4 },
  ],
  renderer: WeatherWidget,
})

register({
  type: 'clock',
  name: '时间',
  epIcon: markRaw(Clock),
  category: 'basic',
  defaultSize: { w: 260, h: 64 },
  defaultProps: () => ({ showDate: true, showSeconds: true, layout: 'horizontal' }),
  propsSchema: [
    { key: 'showDate', label: '显示日期', type: 'switch', defaultValue: true },
    { key: 'showSeconds', label: '显示秒', type: 'switch', defaultValue: true },
    {
      key: 'layout',
      label: '布局',
      type: 'select',
      options: [
        { label: '横排', value: 'horizontal' },
        { label: '上下', value: 'vertical' },
      ],
      defaultValue: 'horizontal',
    },
  ],
  renderer: ClockWidget,
})

register({
  type: 'history-chart',
  name: '历史图表',
  epIcon: markRaw(Timer),
  category: 'chart',
  defaultSize: { w: 420, h: 240 },
  defaultProps: () => ({ variableId: '', title: '历史趋势', unit: '', rangeMs: 3600000, agg: 'mean' }),
  propsSchema: [
    { key: 'variableId', label: '变量', type: 'variable', defaultValue: '' },
    { key: 'title', label: '标题', type: 'text', defaultValue: '' },
    { key: 'unit', label: '单位', type: 'text', defaultValue: '' },
    {
      key: 'rangeMs',
      label: '默认范围',
      type: 'select',
      options: [
        { label: '1 小时', value: 3600000 },
        { label: '6 小时', value: 21600000 },
        { label: '24 小时', value: 86400000 },
        { label: '3 天', value: 259200000 },
      ],
      defaultValue: 3600000,
    },
    {
      key: 'agg',
      label: '窗口聚合',
      type: 'select',
      options: [
        { label: '均值', value: 'mean' },
        { label: '最小值', value: 'min' },
        { label: '最大值', value: 'max' },
        { label: '末值', value: 'last' },
        { label: '求和', value: 'sum' },
      ],
      defaultValue: 'mean',
    },
    { key: 'compact', label: '紧凑模式（隐坐标轴）', type: 'switch', defaultValue: false },
    { key: 'live', label: '实时滚动（近 60 点，不等历史落库）', type: 'switch', defaultValue: false },
    { key: 'color', label: '曲线色（空=信号青）', type: 'color', defaultValue: '' },
    { key: 'areaColor', label: '面积填充色（空=默认）', type: 'color', defaultValue: '' },
  ],
  renderer: HistoryChartWidget,
})

register({
  type: 'tank',
  name: '水池',
  category: 'device',
  defaultSize: { w: 140, h: 160 },
  defaultProps: () => ({ percent: 50, wave: true }),
  propsSchema: [
    { key: 'percent', label: '液位 %（可绑定）', type: 'number', min: 0, max: 100, step: 1, defaultValue: 50 },
    { key: 'wave', label: '液面波动', type: 'switch', defaultValue: true },
  ],
  renderer: TankWidget,
})

register({
  type: 'flow-bar',
  name: '流动条',
  category: 'device',
  defaultSize: { w: 200, h: 28 },
  defaultProps: () => ({ speed: 60, showArrow: true, vertical: false }),
  propsSchema: [
    { key: 'speed', label: '流速 px/s（可绑定，0=停）', type: 'number', step: 10, defaultValue: 60 },
    { key: 'showArrow', label: '方向箭头', type: 'switch', defaultValue: true },
    { key: 'vertical', label: '竖向布置', type: 'switch', defaultValue: false },
  ],
  renderer: FlowBarWidget,
})

// ---- 二次接线图元（M7，单线图符号；颜色走 style.color） ----

register({
  type: 'breaker',
  name: '断路器',
  category: 'device',
  defaultSize: { w: 60, h: 80 },
  defaultProps: () => ({}),
  propsSchema: [],
  renderer: BreakerWidget,
})

register({
  type: 'isolator',
  name: '隔离开关',
  category: 'device',
  defaultSize: { w: 60, h: 80 },
  defaultProps: () => ({}),
  propsSchema: [],
  renderer: IsolatorWidget,
})

register({
  type: 'ground',
  name: '接地',
  category: 'device',
  defaultSize: { w: 50, h: 70 },
  defaultProps: () => ({}),
  propsSchema: [],
  renderer: GroundWidget,
})

register({
  type: 'ct',
  name: '电流互感器',
  category: 'device',
  defaultSize: { w: 70, h: 90 },
  defaultProps: () => ({}),
  propsSchema: [],
  renderer: CtWidget,
})

register({
  type: 'pt',
  name: '电压互感器',
  category: 'device',
  defaultSize: { w: 70, h: 100 },
  defaultProps: () => ({}),
  propsSchema: [],
  renderer: PtWidget,
})

register({
  type: 'transformer',
  name: '变压器',
  category: 'device',
  defaultSize: { w: 70, h: 110 },
  defaultProps: () => ({}),
  propsSchema: [],
  renderer: TransformerWidget,
})

// ---- 行业图元（M9 批次1，对标业界主流组态「图元图库」）：一个通用组件承载资产库全部 SVG ----

register({
  type: 'symbol',
  name: '行业图元',
  epIcon: markRaw(Collection),
  category: 'device',
  defaultSize: { w: 120, h: 120 },
  defaultProps: () => ({ symbolId: 'valve/globe' }),
  propsSchema: [
    { key: 'symbolId', label: '图元 ID（从左侧「图元库」拖入自动填充）', type: 'text', defaultValue: 'valve/globe' },
  ],
  renderer: SymbolWidget,
})

// ---- 画面装饰（M9 批次3，对标业界主流组态「画面装饰」）：纯装饰组件不绑数据 ----

register({
  type: 'title-bar',
  name: '标题栏',
  category: 'decor',
  defaultSize: { w: 800, h: 72 },
  defaultProps: () => ({ text: '监控大屏', align: 'center' }),
  propsSchema: [
    { key: 'text', label: '标题文字', type: 'text', defaultValue: '监控大屏' },
    {
      key: 'align',
      label: '对齐',
      type: 'select',
      options: [
        { label: '居中', value: 'center' },
        { label: '居左', value: 'left' },
        { label: '居右', value: 'right' },
      ],
      defaultValue: 'center',
    },
  ],
  renderer: TitleBarWidget,
})

// ---- 工厂可用阶段二新增（数据表格族：Task 6 实时表格 / Task 7 历史表格） ----

register({
  type: 'realtime-table',
  name: '实时表格',
  epIcon: markRaw(Tickets),
  category: 'basic',
  defaultSize: { w: 360, h: 260 },
  defaultProps: () => ({ columns: '[]', showQuality: false, showUnit: true }),
  propsSchema: [
    {
      key: 'columns',
      label: '数据列（JSON 数组：{key,label,precision?,unit?}，key=变量 key）',
      type: 'textarea',
      defaultValue: '[]',
    },
    { key: 'showQuality', label: '显示质量列（非 good 灰显）', type: 'switch', defaultValue: false },
    { key: 'showUnit', label: '值后拼接单位', type: 'switch', defaultValue: true },
  ],
  renderer: RealtimeTableWidget,
})

register({
  type: 'history-table',
  name: '历史表格',
  epIcon: markRaw(Calendar),
  category: 'basic',
  defaultSize: { w: 360, h: 480 },
  defaultProps: () => ({ variableKey: '', rangeMs: 86400000, bucketCount: 24 }),
  propsSchema: [
    { key: 'variableKey', label: '变量', type: 'variable', defaultValue: '' },
    {
      key: 'rangeMs',
      label: '时间范围',
      type: 'select',
      options: [
        { label: '1 小时', value: 3600000 },
        { label: '6 小时', value: 21600000 },
        { label: '24 小时', value: 86400000 },
      ],
      defaultValue: 86400000,
    },
    {
      key: 'bucketCount',
      label: '时间桶数（行数，每桶取末值）',
      type: 'number',
      min: 1,
      max: 120,
      step: 1,
      defaultValue: 24,
    },
  ],
  renderer: HistoryTableWidget,
})

// ---- 图表类（M2b：echarts 按需渲染，P0 静态模拟序列，M3 起绑定驱动） ----

register({
  type: 'bar-chart',
  name: '柱状图',
  epIcon: markRaw(Histogram),
  category: 'chart',
  defaultSize: { w: 360, h: 220 },
  defaultProps: () => ({ title: '柱状图', unit: '' }),
  propsSchema: [
    { key: 'title', label: '标题', type: 'text', defaultValue: '' },
    { key: 'unit', label: '单位', type: 'text', defaultValue: '' },
  ],
  renderer: BarChartWidget,
})

register({
  type: 'line-chart',
  name: '折线图',
  epIcon: markRaw(TrendCharts),
  category: 'chart',
  defaultSize: { w: 360, h: 220 },
  defaultProps: () => ({ title: '折线图', unit: '' }),
  propsSchema: [
    { key: 'title', label: '标题', type: 'text', defaultValue: '' },
    { key: 'unit', label: '单位', type: 'text', defaultValue: '' },
  ],
  renderer: LineChartWidget,
})

register({
  type: 'trend-chart',
  name: '趋势图',
  epIcon: markRaw(DataAnalysis),
  category: 'chart',
  defaultSize: { w: 380, h: 240 },
  defaultProps: () => ({ title: '趋势图', unit: '' }),
  propsSchema: [
    { key: 'title', label: '标题', type: 'text', defaultValue: '' },
    { key: 'unit', label: '单位', type: 'text', defaultValue: '' },
  ],
  renderer: TrendChartWidget,
})

register({
  type: 'pie-chart',
  name: '饼图',
  epIcon: markRaw(PieChart),
  category: 'chart',
  defaultSize: { w: 300, h: 260 },
  defaultProps: () => ({ title: '占比' }),
  propsSchema: [{ key: 'title', label: '标题', type: 'text', defaultValue: '' }],
  renderer: PieChartWidget,
})

register({
  type: 'gauge',
  name: '仪表盘',
  epIcon: markRaw(Compass),
  category: 'chart',
  defaultSize: { w: 240, h: 220 },
  defaultProps: () => ({ title: '温度', unit: '℃', min: 0, max: 100 }),
  propsSchema: [
    { key: 'title', label: '名称', type: 'text', defaultValue: '' },
    { key: 'unit', label: '单位', type: 'text', defaultValue: '' },
    { key: 'min', label: '量程下限', type: 'number', defaultValue: 0 },
    { key: 'max', label: '量程上限', type: 'number', defaultValue: 100 },
    { key: 'precision', label: '数值小数位', type: 'number', min: 0, max: 6, step: 1, defaultValue: 1 },
    { key: 'textColor', label: '数值颜色（深色大屏用浅色）', type: 'color', defaultValue: '#606266' },
    { key: 'color', label: '指针/进度色（空=信号青）', type: 'color', defaultValue: '' },
  ],
  renderer: GaugeWidget,
})

register({
  type: 'progress',
  name: '进度条',
  epIcon: markRaw(DataLine),
  category: 'chart',
  defaultSize: { w: 280, h: 44 },
  defaultProps: () => ({ percent: 72 }),
  propsSchema: [
    { key: 'percent', label: '百分比', type: 'number', min: 0, max: 100, step: 1, defaultValue: 72 },
    { key: 'precision', label: '数值小数位', type: 'number', min: 0, max: 3, step: 1, defaultValue: 0 },
    { key: 'color', label: '填充色（空=信号青）', type: 'color', defaultValue: '' },
  ],
  renderer: ProgressWidget,
})

register({
  type: 'flip-counter',
  name: '翻牌数字',
  epIcon: markRaw(Odometer),
  category: 'chart',
  defaultSize: { w: 280, h: 90 },
  defaultProps: () => ({ value: '86.5', unit: '℃' }),
  propsSchema: [
    { key: 'value', label: '数值', type: 'text', defaultValue: '0' },
    { key: 'unit', label: '单位', type: 'text', defaultValue: '' },
    { key: 'decimals', label: '小数位（空=原样，数字=定位数+千分位）', type: 'number', min: 0, max: 6, step: 1, defaultValue: 2 },
    { key: 'color', label: '数字颜色（空=主题信号色）', type: 'color', defaultValue: '' },
    { key: 'bg', label: '卡片底色（支持渐变）', type: 'text', defaultValue: '' },
    { key: 'border', label: '描边颜色', type: 'color', defaultValue: '' },
  ],
  renderer: FlipCounterWidget,
})

// ---- 设备类（M2c：SVG 简笔，颜色走"文字色"（--dev-color），M3 起绑定/报警驱动） ----

register({
  type: 'status-light',
  name: '状态灯',
  category: 'device',
  defaultSize: { w: 80, h: 80 },
  defaultProps: () => ({}),
  propsSchema: [],
  renderer: StatusLightWidget,
})

register({
  type: 'motor',
  name: '电机',
  category: 'device',
  defaultSize: { w: 100, h: 100 },
  defaultProps: () => ({}),
  propsSchema: [],
  renderer: MotorWidget,
})

register({
  type: 'pump',
  name: '水泵',
  category: 'device',
  defaultSize: { w: 100, h: 100 },
  defaultProps: () => ({}),
  propsSchema: [],
  renderer: PumpWidget,
})

register({
  type: 'valve',
  name: '阀门',
  category: 'device',
  defaultSize: { w: 100, h: 100 },
  defaultProps: () => ({}),
  propsSchema: [],
  renderer: ValveWidget,
})

register({
  type: 'pipe',
  name: '管道',
  category: 'device',
  defaultSize: { w: 200, h: 36 },
  defaultProps: () => ({}),
  propsSchema: [],
  renderer: PipeWidget,
})

export { registry }

/** 组件面板分组列表（按 category） */
export function paletteByCategory(category: WidgetMeta['category']): WidgetMeta[] {
  return [...registry.values()].filter((m) => m.category === category)
}
