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

onMounted(() => {
  chart = echarts.init(el.value!)
  chart.setOption(props.option)
  // 编辑器里拖拽缩放组件时跟随 resize
  ro = new ResizeObserver(() => chart?.resize())
  ro.observe(el.value!)
})

// option 由各图表 computed 整体新建，引用变化即需重设；deep 遍历大数组（历史序列）纯属浪费
watch(
  () => props.option,
  (o) => chart?.setOption(o, true),
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
