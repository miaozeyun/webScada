<script setup lang="ts">
/** 状态指示灯：圆形灯体，颜色跟 style.color（currentColor）；M3 起由变量绑定/报警态驱动。 */
defineProps<{ nodeProps: Record<string, unknown> }>()
</script>

<template>
  <svg class="dev-svg" viewBox="0 0 100 100" preserveAspectRatio="xMidYMid meet">
    <circle cx="50" cy="50" r="34" fill="currentColor" opacity="0.25" />
    <circle cx="50" cy="50" r="22" fill="currentColor" />
    <circle cx="43" cy="43" r="6" fill="#fff" opacity="0.55" />
  </svg>
</template>

<style scoped>
.dev-svg {
  width: 100%;
  height: 100%;
  display: block;
  color: var(--dev-color, #67c23a); /* 兜底默认绿 */
}
</style>
