<script setup lang="ts">
/** 框选橡皮筋（设计坐标矩形，由 CanvasStage 定位在页面坐标系内）。 */
defineProps<{ rect: { x: number; y: number; w: number; h: number } }>()
</script>

<template>
  <div
    class="marquee"
    :style="{ left: `${rect.x}px`, top: `${rect.y}px`, width: `${rect.w}px`, height: `${rect.h}px` }"
  />
</template>

<style scoped>
.marquee {
  position: absolute;
  border: 1px solid var(--ws-select);
  background: rgba(27, 167, 184, 0.14);
  pointer-events: none;
}
</style>
