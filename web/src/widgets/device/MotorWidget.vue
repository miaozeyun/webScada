<script setup lang="ts">
/** 电机：立式机身 + 散热筋 + 底座 + 转轴（顶视出轴），工业简笔风格。 */
defineProps<{ nodeProps: Record<string, unknown> }>()
</script>

<template>
  <svg class="dev-svg" viewBox="0 0 100 100" preserveAspectRatio="xMidYMid meet">
    <!-- 底座 -->
    <rect x="22" y="78" width="56" height="8" rx="2" fill="currentColor" opacity="0.8" />
    <!-- 机身（圆柱侧视） -->
    <rect x="30" y="30" width="40" height="50" rx="8" fill="none" stroke="currentColor" stroke-width="4" />
    <!-- 散热筋 -->
    <line x1="36" y1="42" x2="64" y2="42" stroke="currentColor" stroke-width="2" opacity="0.5" />
    <line x1="36" y1="52" x2="64" y2="52" stroke="currentColor" stroke-width="2" opacity="0.5" />
    <line x1="36" y1="62" x2="64" y2="62" stroke="currentColor" stroke-width="2" opacity="0.5" />
    <!-- 转轴 -->
    <rect x="44" y="16" width="12" height="14" fill="currentColor" opacity="0.9" />
    <line x1="50" y1="16" x2="50" y2="8" stroke="currentColor" stroke-width="4" />
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
