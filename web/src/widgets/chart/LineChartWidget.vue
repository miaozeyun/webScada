<script setup lang="ts">
/** 折线图（单序列平滑曲线）。 */
import { computed } from 'vue'
import EchartsBase from '../EchartsBase.vue'
import { AXIS, CHART, TITLE_STYLE } from './shared'

const props = defineProps<{ nodeProps: Record<string, unknown> }>()

const option = computed(() => {
  const data = Array.isArray(props.nodeProps.data) ? (props.nodeProps.data as number[]) : [62, 71, 86, 79, 68, 74]
  return {
    title: { text: String(props.nodeProps.title ?? ''), left: 'center', textStyle: TITLE_STYLE },
    tooltip: { trigger: 'axis' },
    grid: { left: 40, right: 16, top: 40, bottom: 28 },
    xAxis: { type: 'category', boundaryGap: false, data: data.map((_, i) => `T-${data.length - i}`), ...AXIS },
    yAxis: { type: 'value', name: String(props.nodeProps.unit ?? ''), nameTextStyle: { color: CHART.text }, ...AXIS },
    series: [{ type: 'line', smooth: true, symbolSize: 5, data, lineStyle: { color: CHART.signal, width: 2 }, itemStyle: { color: CHART.signal } }],
  }
})
</script>

<template>
  <EchartsBase :option="option" />
</template>
