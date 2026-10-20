<script setup lang="ts">
/** 水池（M7，对齐 BY「水池」）：罐体 + 液位（绑 props.percent 0-100，自下而上）+ 液面波动。
 * 液体色走 --dev-color（style.color），缺省水蓝。 */
import { computed } from 'vue'

const props = defineProps<{ nodeProps: Record<string, unknown> }>()

const percent = computed(() => {
  const v = Number(props.nodeProps.percent)
  if (!Number.isFinite(v)) return 50
  return Math.min(100, Math.max(0, v))
})

// SVG viewBox 100x100：液位矩形 y = 88 - 76*p/100，高 = 76*p/100（罐内留边）
const levelY = computed(() => 88 - (76 * percent.value) / 100)
const levelH = computed(() => (76 * percent.value) / 100)
</script>

<template>
  <svg class="dev-svg tank-svg" viewBox="0 0 100 100" preserveAspectRatio="none">
    <defs>
      <clipPath id="tank-inner">
        <rect x="12" y="12" width="76" height="76" rx="3" />
      </clipPath>
      <linearGradient id="tank-liquid" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="currentColor" stop-opacity="0.85" />
        <stop offset="100%" stop-color="currentColor" stop-opacity="0.45" />
      </linearGradient>
    </defs>
    <!-- 罐体 -->
    <rect x="12" y="12" width="76" height="76" fill="none" stroke="currentColor" stroke-width="3" />
    <!-- 液体（clip 防溢出圆角） -->
    <g clip-path="url(#tank-inner)">
      <rect :y="levelY" width="100" height="76" fill="url(#tank-liquid)">
        <animate
          v-if="nodeProps.wave !== false && percent > 1"
          attributeName="y"
          :values="`${levelY};${levelY - 1.5};${levelY}`"
          dur="2.2s"
          repeatCount="indefinite"
        />
      </rect>
    </g>
    <!-- 刻度线 -->
    <line x1="12" y1="31" x2="19" y2="31" stroke="currentColor" stroke-width="1.5" opacity="0.6" />
    <line x1="12" y1="50" x2="19" y2="50" stroke="currentColor" stroke-width="1.5" opacity="0.6" />
    <line x1="12" y1="69" x2="19" y2="69" stroke="currentColor" stroke-width="1.5" opacity="0.6" />
    <!-- 百分比文字 -->
    <text x="50" :y="levelY > 42 ? levelY - 5 : 60" text-anchor="middle" class="pct" fill="#e2e8f0">
      {{ percent.toFixed(0) }}%
    </text>
  </svg>
</template>

<style scoped>
.dev-svg {
  width: 100%;
  height: 100%;
  display: block;
  color: var(--dev-color, #38bdf8);
}

.pct {
  font-size: 13px;
  font-weight: 600;
  font-family: Consolas, monospace;
}
</style>
