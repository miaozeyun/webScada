<script setup lang="ts">
/**
 * echarts 通用基座：按需注册（core + 本项目用到的图型/组件），容器尺寸变化自动 resize。
 * 各图表组件只负责按 nodeProps 生成 option。
 */
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { BarChart, GaugeChart, LineChart, PieChart } from 'echarts/charts'
import {
  GridComponent,
  LegendComponent,
  TitleComponent,
  TooltipComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([BarChart, GaugeChart, LineChart, PieChart, GridComponent, LegendComponent, TitleComponent, TooltipComponent, CanvasRenderer])

const props = defineProps<{ option: echarts.EChartsCoreOption }>()

const el = ref<HTMLDivElement>()
let chart: echarts.ECharts | null = null
let ro: ResizeObserver | null = null
/** 上一次的结构签名（series 数量 + 顶层组件 + 轴/序列类型，详见 shapeOf） */
let prevShape = ''

/**
 * 结构签名：series 数量、顶层选项键、坐标轴/序列类型。
 * 只比「形状」不比数据——数据更新走合并（触发过渡动画），形状变化才全量重建。
 * 轴类型必须进签名：历史图在实时/历史模式间切 xAxis.time ↔ category，合并不换轴型。
 */
function shapeOf(o: echarts.EChartsCoreOption): string {
  const obj = o as Record<string, unknown>
  const series = obj.series
  const count = Array.isArray(series) ? series.length : 0
  const keys = Object.keys(obj)
    .filter((k) => obj[k] !== undefined)
    .sort()
    .join('|')
  const types: string[] = []
  for (const key of ['xAxis', 'yAxis', 'angleAxis', 'radiusAxis', 'series']) {
    const v = obj[key]
    if (Array.isArray(v)) {
      types.push(`${key}:${v.map((item) => (item as { type?: string } | null)?.type ?? '').join(',')}`)
    } else if (v && typeof v === 'object') {
      types.push(`${key}:${(v as { type?: string }).type ?? ''}`)
    }
  }
  return `${count}#${keys}#${types.join('|')}`
}

/**
 * 应用 option。
 *
 * 运行态图表每收到一帧值就会重算 option（服务端 10Hz），此前用 setOption(o, true)
 * 全量重建：整棵组件树销毁重建，仪表盘每帧重置指针动画（肉眼可见的跳变），
 * 历史序列越长开销越大。改为增量合并后数据更新走 ECharts 过渡动画，开销只与变化量相关。
 *
 * 结构变化（series 数量变化、某个顶层组件出现/消失，如绑定后隐藏图例）必须全量重建：
 * 合并会把已移除的序列/图例残留下来。该场景低频，重建一次可接受。
 */
function applyOption(o: echarts.EChartsCoreOption): void {
  if (!chart) return
  const shape = shapeOf(o)
  const rebuild = prevShape !== '' && shape !== prevShape
  prevShape = shape
  chart.setOption(o, { notMerge: rebuild })
}

onMounted(() => {
  chart = echarts.init(el.value!)
  prevShape = shapeOf(props.option)
  chart.setOption(props.option)
  // 编辑器里拖拽缩放组件时跟随 resize
  ro = new ResizeObserver(() => chart?.resize())
  ro.observe(el.value!)
})

// option 由各图表 computed 整体新建，引用变化即需重设；deep 遍历大数组（历史序列）纯属浪费
watch(
  () => props.option,
  (o) => applyOption(o),
)

onBeforeUnmount(() => {
  ro?.disconnect()
  chart?.dispose()
})
</script>

<template>
  <div ref="el" class="echarts-base" />
</template>

<style scoped>
.echarts-base {
  width: 100%;
  height: 100%;
}
</style>
