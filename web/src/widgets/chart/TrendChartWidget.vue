<script setup lang="ts">
/** 趋势图（双序列面积，SCADA 温度/压力典型形态）。 */
import { computed } from 'vue'
import EchartsBase from '../EchartsBase.vue'
import { AXIS, CHART, TITLE_STYLE } from './shared'

const props = defineProps<{ nodeProps: Record<string, unknown> }>()

const option = computed(() => {
  const bound = Array.isArray(props.nodeProps.data) ? (props.nodeProps.data as number[]) : null
  const d1 = bound ?? [62, 71, 86, 79, 68, 74]
  const labels = d1.map((_, i) => `T-${d1.length - i}`)
  return {
    title: { text: String(props.nodeProps.title ?? ''), left: 'center', textStyle: TITLE_STYLE },
    tooltip: { trigger: 'axis' },
    legend: bound ? undefined : { top: 6, right: 8, textStyle: { color: CHART.text } },
    grid: { left: 40, right: 16, top: 44, bottom: 28 },
    xAxis: { type: 'category', boundaryGap: false, data: labels, ...AXIS },
    yAxis: { type: 'value', name: String(props.nodeProps.unit ?? ''), nameTextStyle: { color: CHART.text }, ...AXIS },
    series: bound
      ? [
          { name: '序列1', type: 'line', smooth: true, symbol: 'none', data: d1, lineStyle: { color: CHART.signal, width: 2 }, itemStyle: { color: CHART.signal }, areaStyle: { color: CHART.signalArea } },
        ]
      : [
          { name: '序列1', type: 'line', smooth: true, symbol: 'none', data: [62, 71, 86, 79, 68, 74], lineStyle: { color: CHART.signal, width: 2 }, itemStyle: { color: CHART.signal }, areaStyle: { color: CHART.signalArea } },
          { name: '序列2', type: 'line', smooth: true, symbol: 'none', data: [40, 48, 55, 52, 46, 50], lineStyle: { color: CHART.ok, width: 2 }, itemStyle: { color: CHART.ok }, areaStyle: { color: CHART.okArea } },
        ],
  }
})
</script>

<template>
  <EchartsBase :option="option" />
</template>
