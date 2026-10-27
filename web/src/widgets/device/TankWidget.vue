<script setup lang="ts">
/** 水池（M7，对齐 业界主流组态「水池」）：罐体 + 液位（绑 props.percent 0-100，自下而上）+ 液面波动。
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
  <div class="tank">
  <svg class="dev-svg tank-svg" viewBox="0 0 100 100" preserveAspectRatio="none">
    <!-- 罐体 -->
    <rect x="12" y="12" width="76" height="76" fill="none" stroke="currentColor" stroke-width="3" />
    <!-- 液体：CSS transform 波动（原 SMIL <animate> 每帧改 y 属性，会触发整页 layout，
         长时间停留的大屏上等于每秒 50+ 次重排；transform 走合成层，不触发布局）。
         不用渐变/clipPath id：多实例同 id 会互相串色，且 html2canvas 对 SVG 引用支持差。 -->
    <rect
      class="liquid"
      x="12"
      :y="levelY"
      width="76"
      :height="Math.max(0, 88 - levelY)"
      rx="3"
      fill="currentColor"
      opacity="0.6"
    />
    <!-- 刻度线 -->
    <line x1="12" y1="31" x2="19" y2="31" stroke="currentColor" stroke-width="1.5" opacity="0.6" />
    <line x1="12" y1="50" x2="19" y2="50" stroke="currentColor" stroke-width="1.5" opacity="0.6" />
    <line x1="12" y1="69" x2="19" y2="69" stroke="currentColor" stroke-width="1.5" opacity="0.6" />
    <!-- 百分比文字 -->
    <text x="50" :y="levelY > 42 ? levelY - 5 : 60" text-anchor="middle" class="pct" fill="#e2e8f0">
      {{ percent.toFixed(0) }}%
    </text>
  </svg>
  <!-- 液面波动：HTML 覆盖层做 transform 动画（合成层，不触发布局）；
       SVG 子元素的 transform 动画在 Chrome 里仍会每帧重排，曾占满屏 40+ 次/秒 -->
  <div
    v-if="nodeProps.wave !== false && percent > 1"
    class="surface"
    :style="{ top: `${levelY}%` }"
    aria-hidden="true"
  />
  </div>
</template>

<style scoped>
.tank {
  position: relative;
  width: 100%;
  height: 100%;
}

.dev-svg {
  width: 100%;
  height: 100%;
  display: block;
  color: var(--dev-color, #1ba7b8);
}

.pct {
  font-size: 13px;
  font-weight: 600;
  font-family: var(--ws-font-tech);
}

/* 液面高光条：同步液体颜色，随液位定位，只做合成友好的 transform 波动 */
.surface {
  position: absolute;
  left: 12%;
  right: 12%;
  height: 2px;
  margin-top: -1px;
  border-radius: 1px;
  background: currentColor;
  opacity: 0.45;
  pointer-events: none;
  will-change: transform;
  animation: tank-surface 2.2s ease-in-out infinite;
}

@keyframes tank-surface {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-1.5px); }
}
</style>
