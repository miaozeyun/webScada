/**
 * 组件注册表（协议核心）：type → 元信息 / 默认 props / 属性面板 schema / 渲染器。
 * 协议在 M2a 冻结：新增组件只增注册项，不改协议形状（P1 能耗温湿度组件零成本挂载）。
 * 服务端不加载本注册表（registry 级校验由前端创建绑定时承担，02 §2.13 职责边界）。
 */
import type { Component } from 'vue'
import type { WidgetType } from '@/types/doc'
import ImageWidget from './basic/ImageWidget.vue'
import TextWidget from './basic/TextWidget.vue'

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
  /** iconfont 图标类名（编辑器面板/图层列表共用，参照 visual-drag-demo） */
  icon: string
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

export { registry }

/** 组件面板分组列表（按 category） */
export function paletteByCategory(category: WidgetMeta['category']): WidgetMeta[] {
  return [...registry.values()].filter((m) => m.category === category)
}
