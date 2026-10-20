<script setup lang="ts">
/** 管道：水平管体 + 两端法兰，拉伸宽度即管长（高度建议保持小值）。 */
defineProps<{ nodeProps: Record<string, unknown> }>()
</script>

<template>
  <svg class="dev-svg" viewBox="0 0 100 100" preserveAspectRatio="none">
    <!-- 管体（preserveAspectRatio none：宽度即管长） -->
    <rect x="8" y="38" width="84" height="24" fill="currentColor" opacity="0.25" />
    <rect x="8" y="38" width="84" height="24" fill="none" stroke="currentColor" stroke-width="3" />
    <!-- 高光 -->
    <line x1="10" y1="44" x2="90" y2="44" stroke="currentColor" stroke-width="1.5" opacity="0.4" />
    <!-- 法兰 -->
    <rect x="4" y="34" width="7" height="32" fill="currentColor" opacity="0.85" />
    <rect x="89" y="34" width="7" height="32" fill="currentColor" opacity="0.85" />
  </svg>
</template>

<style scoped>
.dev-svg {
  width: 100%;
  height: 100%;
  display: block;
  color: var(--dev-color, #909399);
}
</style>
