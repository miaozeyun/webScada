<script setup lang="ts">
/** 蝶阀：左右管段 + 中间蝶板（两三角相对）+ 顶部手轮，工业简笔风格。 */
defineProps<{ nodeProps: Record<string, unknown> }>()
</script>

<template>
  <svg class="dev-svg" viewBox="0 0 100 100" preserveAspectRatio="xMidYMid meet">
    <!-- 左右管段 -->
    <rect x="6" y="46" width="24" height="12" fill="none" stroke="currentColor" stroke-width="3" />
    <rect x="70" y="46" width="24" height="12" fill="none" stroke="currentColor" stroke-width="3" />
    <!-- 蝶板（两三角相对） -->
    <path d="M32 38 L48 50 L32 62 Z" fill="none" stroke="currentColor" stroke-width="3" />
    <path d="M68 38 L52 50 L68 62 Z" fill="none" stroke="currentColor" stroke-width="3" />
    <!-- 阀杆 + 手轮 -->
    <line x1="50" y1="38" x2="50" y2="20" stroke="currentColor" stroke-width="3" />
    <line x1="38" y1="20" x2="62" y2="20" stroke="currentColor" stroke-width="4" />
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
