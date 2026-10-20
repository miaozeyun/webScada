<script setup lang="ts">
/** 圆形（参照 visual-drag-demo CircleShape）：border-radius 50% 兜底，用户显式设置 borderRadius 时以 inline 为准。 */
defineProps<{ nodeProps: Record<string, unknown> }>()
</script>

<template>
  <div class="circle-widget" />
</template>

<style scoped>
.circle-widget {
  width: 100%;
  height: 100%;
  box-sizing: border-box;
  border: 1px solid #909399;
  border-radius: 50%;
  background: transparent;
}
</style>
