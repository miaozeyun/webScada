<script setup lang="ts">
/** 断路器（M7 二次接线）：方框内斜置触点（标准单线图符号）。
 * 通电态可绑 style.color 变色（如合闸绿/分闸灰）。 */
</script>

<template>
  <svg class="dev-svg ele-svg" viewBox="0 0 100 100" preserveAspectRatio="xMidYMid meet">
    <!-- 引线 -->
    <line x1="50" y1="0" x2="50" y2="14" stroke="currentColor" stroke-width="5" />
    <line x1="50" y1="86" x2="50" y2="100" stroke="currentColor" stroke-width="5" />
    <!-- 触点（斜置） -->
    <line x1="28" y1="82" x2="72" y2="22" stroke="currentColor" stroke-width="5" />
    <!-- 方框 -->
    <rect x="20" y="16" width="60" height="68" fill="none" stroke="currentColor" stroke-width="4" />
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
