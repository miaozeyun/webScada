<script setup lang="ts">
/** 饼图（占比分布）。 */
import { computed } from 'vue'
import EchartsBase from '../EchartsBase.vue'
import { CHART, PALETTE, TITLE_STYLE } from './shared'

const props = defineProps<{ nodeProps: Record<string, unknown> }>()

const option = computed(() => ({
  title: { text: String(props.nodeProps.title ?? ''), left: 'center', textStyle: TITLE_STYLE },
  tooltip: { trigger: 'item' },
  legend: { bottom: 0, textStyle: { color: CHART.text } },
  color: PALETTE,
  series: [
    {
      type: 'pie',
      radius: ['38%', '62%'],
      center: ['50%', '46%'],
      label: { color: CHART.text },
      data: [
        { name: 'A 路', value: 35 },
        { name: 'B 路', value: 28 },
        { name: 'C 路', value: 22 },
        { name: '备用', value: 15 },
      ],
    },
  ],
}))
</script>

<template>
  <EchartsBase :option="option" />
</template>
