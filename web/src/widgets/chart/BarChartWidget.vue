<script setup lang="ts">
/** 柱状图：P0 静态模拟序列；M3 起由数据源绑定驱动（K12 装配点在 WidgetHost）。 */
import { computed } from 'vue'
import EchartsBase from '../EchartsBase.vue'
import { AXIS, CHART, TITLE_STYLE } from './shared'

const props = defineProps<{ nodeProps: Record<string, unknown> }>()

const option = computed(() => {
  // 运行态绑定注入历史序列（number[]）；无绑定回落静态模拟
  const data = Array.isArray(props.nodeProps.data) ? (props.nodeProps.data as number[]) : [62, 71, 86, 79, 68, 74]
  return {
    title: { text: String(props.nodeProps.title ?? ''), left: 'center', textStyle: TITLE_STYLE },
    tooltip: { trigger: 'axis' },
    grid: { left: 40, right: 16, top: 40, bottom: 28 },
    xAxis: { type: 'category', data: data.map((_, i) => `T-${data.length - i}`), ...AXIS },
    yAxis: { type: 'value', name: String(props.nodeProps.unit ?? ''), nameTextStyle: { color: CHART.text }, ...AXIS },
    series: [{ type: 'bar', data, itemStyle: { color: CHART.signal, borderRadius: [3, 3, 0, 0] }, barMaxWidth: 28 }],
  }
})
</script>

<template>
  <EchartsBase :option="option" />
</template>
