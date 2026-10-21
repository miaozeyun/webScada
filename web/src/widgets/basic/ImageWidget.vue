<script setup lang="ts">
/** 图片组件：属性面板可本地上传（落盘 /api/v1/uploads）或直接填 URL。 */
import { computed } from 'vue'
import { useRuntimeStore } from '@/runtime/store'

const props = defineProps<{ nodeProps: Record<string, unknown> }>()
const runtime = useRuntimeStore()

const src = computed(() => String(props.nodeProps.src ?? ''))
const fit = computed(() => String(props.nodeProps.fit ?? 'contain') as 'contain' | 'cover' | 'fill')
</script>

<template>
  <div class="image-widget">
    <img v-if="src" :src="src" :style="{ objectFit: fit }" alt="" draggable="false" />
    <div v-else class="ws-canvas-empty">{{ runtime.running ? '图片未配置' : '在右侧属性上传图片或填 URL' }}</div>
  </div>
</template>

<style scoped>
.image-widget {
  width: 100%;
  height: 100%;
  overflow: hidden;
}

.image-widget img {
  width: 100%;
  height: 100%;
  display: block;
}
</style>
