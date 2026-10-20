<script setup lang="ts">
/** 文本组件：内容渲染（几何/定位由外层 NodeView 承担）。 */
import { computed } from 'vue'

const props = defineProps<{ nodeProps: Record<string, unknown> }>()

const text = computed(() => String(props.nodeProps.text ?? ''))
const ellipsis = computed(() => props.nodeProps.ellipsis !== false)
</script>

<template>
  <div class="text-widget" :class="{ 'text-ellipsis': ellipsis }">{{ text }}</div>
</template>

<style scoped>
.text-widget {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  padding: 0 6px;
  line-height: 1.35;
  white-space: pre-wrap;
}

.text-ellipsis {
  overflow: hidden;
  display: block;
  white-space: nowrap;
  text-overflow: ellipsis;
  padding-top: 0;
}
</style>
