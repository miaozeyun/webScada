<script setup lang="ts">
/** 图片轮播：urls 每行一个外链，intervalSec 切换间隔。 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRuntimeStore } from '@/runtime/store'

const props = defineProps<{ nodeProps: Record<string, unknown> }>()
const runtime = useRuntimeStore()

const urls = computed(() =>
  String(props.nodeProps.urls ?? '')
    .split('\n')
    .map((s) => s.trim())
    .filter(Boolean),
)

const idx = ref(0)
let timer: ReturnType<typeof setInterval> | null = null

onMounted(() => {
  timer = setInterval(() => {
    if (urls.value.length > 1) idx.value = (idx.value + 1) % urls.value.length
  }, Math.max(1, Number(props.nodeProps.intervalSec ?? 5)) * 1000)
})

onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
})
</script>

<template>
  <div class="carousel-widget">
    <img v-if="urls.length" :src="urls[idx % urls.length]" alt="" draggable="false" />
    <div v-else class="ws-canvas-empty">{{ runtime.running ? '轮播图片未配置' : '在右侧属性填入图片 URL（每行一个）' }}</div>
    <span v-if="urls.length > 1" class="dots">
      <i v-for="n in urls.length" :key="n" :class="{ on: (idx % urls.length) === n - 1 }" />
    </span>
  </div>
</template>

<style scoped>
.carousel-widget {
  position: relative;
  width: 100%;
  height: 100%;
  overflow: hidden;
  box-sizing: border-box;
  background: #f5f7fa;
}

.carousel-widget img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.dots {
  position: absolute;
  bottom: 6px;
  left: 0;
  right: 0;
  display: flex;
  justify-content: center;
  gap: 4px;
}

.dots i {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.6);
}

.dots i.on {
  background: #0b7285;
}
</style>
