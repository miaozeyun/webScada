<script setup lang="ts">
/** 饼图（占比分布）。 */
import { computed } from 'vue'
import EchartsBase from '../EchartsBase.vue'

const props = defineProps<{ nodeProps: Record<string, unknown> }>()

const PALETTE = ['#1ba7b8', '#67c23a', '#e6a23c', '#f56c6c', '#909399']

const option = computed(() => ({
  title: { text: String(props.nodeProps.title ?? ''), left: 'center', textStyle: { color: '#909399', fontSize: 14 } },
  tooltip: { trigger: 'item' },
  legend: { bottom: 0, textStyle: { color: '#909399' } },
  color: PALETTE,
  series: [
    {
      type: 'pie',
      radius: ['38%', '62%'],
      center: ['50%', '46%'],
      label: { color: '#909399' },
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
