<script setup lang="ts">
/** 趋势图（双序列面积，SCADA 温度/压力典型形态）。 */
import { computed } from 'vue'
import EchartsBase from '../EchartsBase.vue'

const props = defineProps<{ nodeProps: Record<string, unknown> }>()

const AXIS = { axisLabel: { color: '#909399' }, axisLine: { lineStyle: { color: '#c0c4cc' } }, splitLine: { lineStyle: { color: 'rgba(148,163,184,0.2)' } } }

const option = computed(() => {
  const bound = Array.isArray(props.nodeProps.data) ? (props.nodeProps.data as number[]) : null
  const d1 = bound ?? [62, 71, 86, 79, 68, 74]
  const labels = d1.map((_, i) => `T-${d1.length - i}`)
  return {
    title: { text: String(props.nodeProps.title ?? ''), left: 'center', textStyle: { color: '#909399', fontSize: 14 } },
    tooltip: { trigger: 'axis' },
    legend: bound ? undefined : { top: 6, right: 8, textStyle: { color: '#909399' } },
    grid: { left: 40, right: 16, top: 44, bottom: 28 },
    xAxis: { type: 'category', boundaryGap: false, data: labels, ...AXIS },
    yAxis: { type: 'value', name: String(props.nodeProps.unit ?? ''), nameTextStyle: { color: '#909399' }, ...AXIS },
    series: bound
      ? [
          { name: '序列1', type: 'line', smooth: true, symbol: 'none', data: d1, lineStyle: { color: '#1ba7b8', width: 2 }, itemStyle: { color: '#1ba7b8' }, areaStyle: { color: 'rgba(27,167,184,0.2)' } },
        ]
      : [
          { name: '序列1', type: 'line', smooth: true, symbol: 'none', data: [62, 71, 86, 79, 68, 74], lineStyle: { color: '#1ba7b8', width: 2 }, itemStyle: { color: '#1ba7b8' }, areaStyle: { color: 'rgba(27,167,184,0.2)' } },
          { name: '序列2', type: 'line', smooth: true, symbol: 'none', data: [40, 48, 55, 52, 46, 50], lineStyle: { color: '#67c23a', width: 2 }, itemStyle: { color: '#67c23a' }, areaStyle: { color: 'rgba(103,194,58,0.15)' } },
        ],
  }
})
</script>

<template>
  <EchartsBase :option="option" />
</template>
