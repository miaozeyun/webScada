<script setup lang="ts">
/** 矩形（参照 visual-drag-demo RectShape）：外观走 ComponentStyle（fill/stroke/borderRadius），此处仅兜底默认描边。 */
defineProps<{ nodeProps: Record<string, unknown> }>()
</script>

<template>
  <div class="rect-widget" />
</template>

<style scoped>
.rect-widget {
  width: 100%;
  height: 100%;
  box-sizing: border-box;
  /* WidgetHost 的 inline style（fill/stroke）设置后覆盖对应项 */
  border: 1px solid #909399;
  background: transparent;
}
</style>
