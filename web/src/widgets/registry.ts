/**
 * 组件注册表（协议核心）：type → 元信息 / 默认 props / 属性面板 schema / 渲染器。
 * 协议在 M2a 冻结：新增组件只增注册项，不改协议形状（P1 能耗温湿度组件零成本挂载）。
 * 服务端不加载本注册表（registry 级校验由前端创建绑定时承担，02 §2.13 职责边界）。
 */
import { markRaw, type Component } from 'vue'
import {
  Compass,
  DataAnalysis,
  DataLine,
  Histogram,
  Odometer,
  Picture,
  PieChart,
  TrendCharts,
} from '@element-plus/icons-vue'
import type { WidgetType } from '@/types/doc'
import ButtonWidget from './basic/ButtonWidget.vue'
import CarouselWidget from './basic/CarouselWidget.vue'
import CircleWidget from './basic/CircleWidget.vue'
import FlipCounterWidget from './basic/FlipCounterWidget.vue'
import ImageWidget from './basic/ImageWidget.vue'
import LineWidget from './basic/LineWidget.vue'
import ProgressWidget from './basic/ProgressWidget.vue'
import RectWidget from './basic/RectWidget.vue'
import TableWidget from './basic/TableWidget.vue'
import TextWidget from './basic/TextWidget.vue'
import BarChartWidget from './chart/BarChartWidget.vue'
import GaugeWidget from './chart/GaugeWidget.vue'
import LineChartWidget from './chart/LineChartWidget.vue'
import PieChartWidget from './chart/PieChartWidget.vue'
import TrendChartWidget from './chart/TrendChartWidget.vue'
import MotorWidget from './device/MotorWidget.vue'
import PipeWidget from './device/PipeWidget.vue'
import PumpWidget from './device/PumpWidget.vue'
import StatusLightWidget from './device/StatusLightWidget.vue'
import ValveWidget from './device/ValveWidget.vue'

/** 属性面板表单项类型（PropPanel 据此渲染） */
export type PropFieldType = 'text' | 'textarea' | 'number' | 'color' | 'select' | 'switch'

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
  /** iconfont 图标类名（编辑器面板/图层列表共用，参照 visual-drag-demo）；图表类无对应图标时用 epIcon */
  icon?: string
  /** Element Plus 图标组件（iconfont 无对应时的兜底，注册时 markRaw） */
  epIcon?: Component
  category: 'basic' | 'chart' | 'device'
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
  icon: 'wenben',
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
  icon: 'juxing',
  category: 'basic',
  defaultSize: { w: 200, h: 120 },
  defaultProps: () => ({}),
  propsSchema: [],
  renderer: RectWidget,
})

register({
  type: 'circle',
  name: '圆形',
  icon: '24gl-circle',
  category: 'basic',
  defaultSize: { w: 120, h: 120 },
  defaultProps: () => ({}),
  propsSchema: [],
  renderer: CircleWidget,
})

register({
  type: 'line',
  name: '直线',
  icon: 'zhixian',
  category: 'basic',
  defaultSize: { w: 200, h: 2 },
  defaultProps: () => ({}),
  propsSchema: [],
  renderer: LineWidget,
})

register({
  type: 'button',
  name: '按钮',
  icon: 'button',
  category: 'basic',
  defaultSize: { w: 120, h: 40 },
  defaultProps: () => ({ text: '按钮' }),
  propsSchema: [{ key: 'text', label: '按钮文字', type: 'text', defaultValue: '按钮' }],
  renderer: ButtonWidget,
})

register({
  type: 'image',
  name: '图片',
  icon: 'tupian',
  category: 'basic',
  defaultSize: { w: 320, h: 200 },
  defaultProps: () => ({ src: '', fit: 'contain' }),
  propsSchema: [
    { key: 'src', label: '图片 URL（外链，P0 不做上传）', type: 'text', defaultValue: '' },
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
  icon: 'biaoge',
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
  epIcon: markRaw(Picture),
  category: 'basic',
  defaultSize: { w: 360, h: 240 },
  defaultProps: () => ({ urls: '', intervalSec: 5 }),
  propsSchema: [
    { key: 'urls', label: '图片 URL 列表（每行一个）', type: 'textarea', defaultValue: '' },
    { key: 'intervalSec', label: '切换间隔（秒）', type: 'number', min: 1, max: 120, step: 1, defaultValue: 5 },
  ],
  renderer: CarouselWidget,
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
