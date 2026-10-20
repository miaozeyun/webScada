<script setup lang="ts">
/** 仪表盘（温度/压力等单值指示，min/max/unit 可调）。 */
import { computed } from 'vue'
import EchartsBase from '../EchartsBase.vue'

const props = defineProps<{ nodeProps: Record<string, unknown> }>()

const min = computed(() => Number(props.nodeProps.min ?? 0))
const max = computed(() => Number(props.nodeProps.max ?? 100))
const precision = computed(() => Number(props.nodeProps.precision ?? 1))
/** 文字色：深色大屏场景可配浅色（缺省沿用中性灰） */
const textColor = computed(() => String(props.nodeProps.textColor ?? '#606266') || '#606266')

const option = computed(() => ({
  series: [
    {
      type: 'gauge',
      min: min.value,
      max: max.value,
      startAngle: 210,
      endAngle: -30,
      progress: { show: true, width: 10, itemStyle: { color: '#1ba7b8' } },
      axisLine: { lineStyle: { width: 10, color: [[1, 'rgba(148,163,184,0.25)']] } },
      axisTick: { distance: -16, lineStyle: { color: '#c0c4cc' } },
      splitLine: { distance: -20, length: 6, lineStyle: { color: '#c0c4cc' } },
      axisLabel: { distance: 4, color: '#909399', fontSize: 10 },
      pointer: { itemStyle: { color: '#1ba7b8' }, width: 4 },
      anchor: { show: true, size: 10, itemStyle: { color: '#1ba7b8' } },
      detail: {
        valueAnimation: true,
        // 数值按 precision 取整（绑定注入的原始浮点不可直接展示）
        formatter: (v: number) => `${Number(v).toFixed(precision.value)} ${String(props.nodeProps.unit ?? '')}`,
        color: textColor.value,
        fontSize: 18,
        offsetCenter: [0, '62%'],
      },
      title: { color: '#909399', fontSize: 13, offsetCenter: [0, '88%'] },
      // 运行态绑定注入单值；无绑定回落静态演示值
      data: [{ value: Number(props.nodeProps.value ?? 65), name: String(props.nodeProps.title ?? '') }],
    },
  ],
}))
</script>

<template>
  <EchartsBase :option="option" />
</template>
