<script setup lang="ts">
/** 流动条（M7，对齐 业界主流组态「流动条」）：管内流体条纹滚动，速度/启停由 props.speed（px/s）驱动
 * （绑变量：0=停止，正值右流，负值左流）。方向箭头可选。 */
import { computed } from 'vue'

const props = defineProps<{ nodeProps: Record<string, unknown> }>()

const speed = computed(() => {
  const v = Number(props.nodeProps.speed)
  return Number.isFinite(v) ? v : 60
})

const running = computed(() => speed.value !== 0)
const duration = computed(() => {
  // 16px 条纹周期 → 时长；限幅防过快
  const s = Math.abs(speed.value)
  if (s < 1) return 0
  return Math.max(0.08, 16 / s)
})
const direction = computed(() => (speed.value < 0 ? 'reverse' : 'normal'))
</script>

<template>
  <div class="flow-bar" :class="{ running, horizontal: nodeProps.vertical !== true }">
    <div class="pipe">
      <div class="fluid" :style="{ animationDuration: `${duration}s`, animationDirection: direction }" />
    </div>
    <svg v-if="nodeProps.showArrow !== false" class="arrow" viewBox="0 0 100 40" preserveAspectRatio="none">
      <path d="M 15 20 L 60 20 M 48 10 L 62 20 L 48 30" fill="none" stroke="currentColor" stroke-width="6"
        :transform="speed < 0 ? 'translate(100,0) scale(-1,1)' : undefined" />
    </svg>
  </div>
</template>

<style scoped>
.flow-bar {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  gap: 4%;
  color: var(--dev-color, #1ba7b8);
}

.flow-bar.horizontal {
  flex-direction: row;
}

.pipe {
  flex: 1;
  height: 58%;
  border: 2px solid currentColor;
  border-radius: 4px;
  overflow: hidden;
  background: rgba(148, 163, 184, 0.12);
  position: relative;
}

.fluid {
  width: 100%;
  height: 100%;
  background: repeating-linear-gradient(
    115deg,
    currentColor 0 8px,
    transparent 8px 16px
  );
  opacity: 0.55;
}

.running .fluid {
  animation: ws-flowbar-slide linear infinite;
}

@keyframes ws-flowbar-slide {
  from { transform: translateX(0); }
  to { transform: translateX(-16px); }
}

.arrow {
  width: 18%;
  height: 70%;
  color: currentColor;
}
</style>
