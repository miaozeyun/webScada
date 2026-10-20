<script setup lang="ts">
/** 折线图（单序列平滑曲线）。 */
import { computed } from 'vue'
import EchartsBase from '../EchartsBase.vue'

const props = defineProps<{ nodeProps: Record<string, unknown> }>()

const AXIS = { axisLabel: { color: '#909399' }, axisLine: { lineStyle: { color: '#c0c4cc' } }, splitLine: { lineStyle: { color: 'rgba(148,163,184,0.2)' } } }

const option = computed(() => {
  const data = Array.isArray(props.nodeProps.data) ? (props.nodeProps.data as number[]) : [62, 71, 86, 79, 68, 74]
  return {
    title: { text: String(props.nodeProps.title ?? ''), left: 'center', textStyle: { color: '#909399', fontSize: 14 } },
    tooltip: { trigger: 'axis' },
    grid: { left: 40, right: 16, top: 40, bottom: 28 },
    xAxis: { type: 'category', boundaryGap: false, data: data.map((_, i) => `T-${data.length - i}`), ...AXIS },
    yAxis: { type: 'value', name: String(props.nodeProps.unit ?? ''), nameTextStyle: { color: '#909399' }, ...AXIS },
    series: [{ type: 'line', smooth: true, symbolSize: 5, data, lineStyle: { color: '#409eff', width: 2 }, itemStyle: { color: '#409eff' } }],
  }
})
</script>

<template>
  <EchartsBase :option="option" />
</template>
