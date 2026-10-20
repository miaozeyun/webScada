<script setup lang="ts">
/** 进度条：百分比可调，M3 起由变量绑定驱动。 */
import { computed } from 'vue'

const props = defineProps<{ nodeProps: Record<string, unknown> }>()

/** 绑定注入的原始浮点需按小数位取整展示（round 避免 70.015 → 70.0 的截断误差） */
const precision = computed(() => Number(props.nodeProps.precision ?? 0))

const percent = computed(() => Math.min(100, Math.max(0, Number(props.nodeProps.percent ?? 72))))

const display = computed(() => percent.value.toFixed(precision.value))
</script>

<template>
  <div class="progress-widget">
    <div class="bar">
      <div class="fill" :style="{ width: `${percent}%` }" />
    </div>
    <span class="pct">{{ display }}%</span>
  </div>
</template>

<style scoped>
.progress-widget {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 4px;
  box-sizing: border-box;
}

.bar {
  flex: 1;
  height: 14px;
  background: rgba(148, 163, 184, 0.25);
  border-radius: 7px;
  overflow: hidden;
}

.fill {
  height: 100%;
  border-radius: 7px;
  background: linear-gradient(90deg, #0b7285, #1ba7b8);
  transition: width 0.3s;
}

.pct {
  font-size: 14px;
  font-variant-numeric: tabular-nums;
  color: #909399;
  white-space: nowrap;
}
</style>
