<script setup lang="ts">
/** 双绕组变压器（M7 二次接线）：两相切圆。 */
</script>

<template>
  <svg class="dev-svg ele-svg" viewBox="0 0 100 100" preserveAspectRatio="xMidYMid meet">
    <line x1="50" y1="0" x2="50" y2="12" stroke="currentColor" stroke-width="5" />
    <line x1="50" y1="88" x2="50" y2="100" stroke="currentColor" stroke-width="5" />
    <circle cx="50" cy="32" r="20" fill="none" stroke="currentColor" stroke-width="5" />
    <circle cx="50" cy="68" r="20" fill="none" stroke="currentColor" stroke-width="5" />
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
