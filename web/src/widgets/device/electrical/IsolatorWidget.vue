<script setup lang="ts">
/** 隔离开关（M7 二次接线）：无方框斜置触点。 */
</script>

<template>
  <svg class="dev-svg ele-svg" viewBox="0 0 100 100" preserveAspectRatio="xMidYMid meet">
    <line x1="50" y1="0" x2="50" y2="24" stroke="currentColor" stroke-width="5" />
    <line x1="50" y1="76" x2="50" y2="100" stroke="currentColor" stroke-width="5" />
    <!-- 触点圆点 + 斜杆 -->
    <circle cx="50" cy="76" r="4" fill="currentColor" />
    <line x1="50" y1="76" x2="76" y2="28" stroke="currentColor" stroke-width="5" />
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
