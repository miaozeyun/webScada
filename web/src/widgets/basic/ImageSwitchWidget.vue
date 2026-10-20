<script setup lang="ts">
/** 图片切换（M7，对齐 BY「图片切换」）：变量值 → 图片枚举切换。
 * images JSON [{value, url}]；绑 props.value 匹配，无命中显示缺省图（首张）。 */
import { computed } from 'vue'

interface ImageItem {
  value: string | number | boolean
  url: string
}

const props = defineProps<{ nodeProps: Record<string, unknown> }>()

const images = computed<ImageItem[]>(() => {
  try {
    const arr = typeof props.nodeProps.images === 'string' ? JSON.parse(props.nodeProps.images) : props.nodeProps.images
    return Array.isArray(arr) ? arr.filter((i) => i && typeof i.url === 'string') : []
  } catch {
    return []
  }
})

const currentUrl = computed(() => {
  const v = props.nodeProps.value
  if (v !== undefined && v !== null && v !== '') {
    const hit = images.value.find((i) => String(i.value) === String(v))
    if (hit) return hit.url
  }
  return images.value[0]?.url ?? ''
})
</script>

<template>
  <div class="image-switch">
    <img v-if="currentUrl" :src="currentUrl" :alt="String(nodeProps.alt ?? '')" draggable="false" />
    <div v-else class="empty">配置图片列表<br />（images JSON）</div>
  </div>
</template>

<style scoped>
.image-switch {
  width: 100%;
  height: 100%;
  overflow: hidden;
}

img {
  width: 100%;
  height: 100%;
  object-fit: contain;
  display: block;
}

.empty {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #909399;
  font-size: 12px;
  text-align: center;
  background: repeating-linear-gradient(45deg, transparent 0 10px, rgba(148, 163, 184, 0.08) 10px 20px);
}
</style>
