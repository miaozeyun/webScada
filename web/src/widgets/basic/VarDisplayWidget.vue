<script setup lang="ts">
/** 变量显示（M7，对齐 业界主流组态「变量」组件）：前缀 + 数值（精度）+ 单位；绑 props.value。
 * 无值时显示占位 '--'（编辑态即此形态）。 */
import { computed } from 'vue'

const props = defineProps<{ nodeProps: Record<string, unknown> }>()

const display = computed(() => {
  const v = props.nodeProps.value
  if (v === undefined || v === null || v === '') return '--'
  const precision = Number(props.nodeProps.precision ?? 2)
  if (typeof v === 'number') return v.toFixed(precision)
  if (typeof v === 'string' && v !== '' && !Number.isNaN(Number(v))) return Number(v).toFixed(precision)
  return String(v)
})
</script>

<template>
  <div class="var-display">
    <span v-if="nodeProps.prefix" class="prefix">{{ nodeProps.prefix }}</span>
    <span class="value">{{ display }}</span>
    <span v-if="nodeProps.unit" class="unit">{{ nodeProps.unit }}</span>
  </div>
</template>

<style scoped>
.var-display {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: baseline;
  justify-content: center;
  gap: 6px;
  overflow: hidden;
}

.prefix {
  font-size: 0.5em;
  color: inherit;
  opacity: 0.75;
}

.value {
  font-size: 1.6em;
  font-weight: 700;
  font-family: 'DIN Alternate', Consolas, monospace;
  line-height: 1.1;
}

.unit {
  font-size: 0.45em;
  color: inherit;
  opacity: 0.7;
}
</style>
