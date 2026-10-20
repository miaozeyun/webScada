<script setup lang="ts">
/** 直线（参照 visual-drag-demo LineShape）：水平细条，组件自身高度即线宽（默认 2px，拉高变粗）。 */
defineProps<{ nodeProps: Record<string, unknown> }>()
</script>

<template>
  <div class="line-widget" />
</template>

<style scoped>
.line-widget {
  width: 100%;
  height: 100%;
  /* fill（背景色）即线色，未设置时兜底灰 */
  background: #909399;
}
</style>
