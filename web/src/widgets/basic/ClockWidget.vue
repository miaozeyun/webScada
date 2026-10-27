<script setup lang="ts">
/** 时间（M7，对齐 业界主流组态「天气和时间」）：本地日期 + 时钟，1s tick；布局（横排/上下）可选。 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

const props = defineProps<{ nodeProps: Record<string, unknown> }>()

const now = ref(new Date())
let timer: ReturnType<typeof setInterval> | null = null

onMounted(() => {
  timer = setInterval(() => (now.value = new Date()), 1000)
})
onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
})

const pad = (n: number): string => String(n).padStart(2, '0')
const WEEK = ['日', '一', '二', '三', '四', '五', '六']

const dateText = computed(() => {
  const d = now.value
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} 周${WEEK[d.getDay()]}`
})

const timeText = computed(() => {
  const d = now.value
  const sec = props.nodeProps.showSeconds !== false ? `:${pad(d.getSeconds())}` : ''
  return `${pad(d.getHours())}:${pad(d.getMinutes())}${sec}`
})
</script>

<template>
  <div class="clock-widget" :class="{ vertical: nodeProps.layout === 'vertical' }">
    <span class="time">{{ timeText }}</span>
    <span v-if="nodeProps.showDate !== false" class="date">{{ dateText }}</span>
  </div>
</template>

<style scoped>
.clock-widget {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  overflow: hidden;
}

.clock-widget.vertical {
  flex-direction: column;
  gap: 2px;
}

.time {
  font-size: 1.7em;
  font-weight: 700;
  font-family: var(--ws-font-tech);
  letter-spacing: 0.04em;
  white-space: nowrap;
}

.date {
  font-size: 0.6em;
  opacity: 0.75;
  white-space: nowrap;
}
</style>
