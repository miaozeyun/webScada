<script setup lang="ts">
/** 水泵：蜗壳圆体 + 顶部出口管 + 底脚，工业简笔风格。 */
defineProps<{ nodeProps: Record<string, unknown> }>()
</script>

<template>
  <svg class="dev-svg" viewBox="0 0 100 100" preserveAspectRatio="xMidYMid meet">
    <!-- 出口管 -->
    <rect x="42" y="10" width="16" height="22" fill="none" stroke="currentColor" stroke-width="4" />
    <!-- 蜗壳体 -->
    <circle cx="50" cy="60" r="26" fill="none" stroke="currentColor" stroke-width="4" />
    <!-- 叶轮 -->
    <g stroke="currentColor" stroke-width="3" opacity="0.75">
      <line x1="50" y1="44" x2="50" y2="76" />
      <line x1="36" y1="52" x2="64" y2="68" />
      <line x1="36" y1="68" x2="64" y2="52" />
    </g>
    <circle cx="50" cy="60" r="6" fill="currentColor" />
    <!-- 底脚 -->
    <rect x="30" y="84" width="40" height="6" rx="2" fill="currentColor" opacity="0.8" />
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
