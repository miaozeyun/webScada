<script setup lang="ts">
/** 翻牌数字（KPI 大数值展示）：值与单位可调，M3 起接变量绑定实时刷新。
 * decimals 设定时数值按定位数+千分位格式化（等宽读数，KPI 观感统一）。 */
import { computed } from 'vue'

const props = defineProps<{ nodeProps: Record<string, unknown> }>()

const value = computed(() => {
  const raw = props.nodeProps.value ?? '86.5'
  const d = props.nodeProps.decimals
  const num = Number(raw)
  if (d === undefined || d === null || d === '' || !Number.isFinite(num)) return String(raw)
  return num.toLocaleString('zh-CN', { minimumFractionDigits: Number(d), maximumFractionDigits: Number(d) })
})
const unit = computed(() => String(props.nodeProps.unit ?? ''))
</script>

<template>
  <div class="flip-counter">
    <span class="digits">{{ value }}</span>
    <span v-if="unit" class="unit">{{ unit }}</span>
  </div>
</template>

<style scoped>
.flip-counter {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: baseline;
  justify-content: center;
  gap: 6px;
  background: linear-gradient(180deg, #1f2d3d 0%, #16222f 100%);
  border: 1px solid rgba(112, 192, 255, 0.35);
  border-radius: 6px;
  overflow: hidden;
  box-sizing: border-box;
}

/* 字号随组件高度自适应，避免小尺寸溢出 */
.digits {
  font-size: min(3em, calc(100vh / 12));
  font-family: var(--ws-font-tech);
  font-variant-numeric: tabular-nums;
  font-weight: 600;
  color: var(--ws-signal-bright);
  line-height: 1.2;
  white-space: nowrap;
}

.unit {
  font-size: 1em;
  color: #909399;
  white-space: nowrap;
}
</style>
