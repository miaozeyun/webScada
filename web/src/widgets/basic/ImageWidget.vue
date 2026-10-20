<script setup lang="ts">
/** 图片组件：仅外链 URL（P0 不做上传，设计边界 D7）。 */
import { computed } from 'vue'

const props = defineProps<{ nodeProps: Record<string, unknown> }>()

const src = computed(() => String(props.nodeProps.src ?? ''))
const fit = computed(() => String(props.nodeProps.fit ?? 'contain') as 'contain' | 'cover' | 'fill')
</script>

<template>
  <div class="image-widget">
    <img v-if="src" :src="src" :style="{ objectFit: fit }" alt="" draggable="false" />
    <div v-else class="image-placeholder">图片（在右侧填入 URL）</div>
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

.image-placeholder {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px dashed #475569;
  color: #64748b;
  font-size: 13px;
  background: rgba(30, 58, 138, 0.08);
}
</style>
