<script setup lang="ts">
/**
 * 大屏标题栏（M9 批次3 画面装饰）：横幅 + 主标题 + 强调线。
 * 文字色/强调色走 --dev-color（style.color），底纹固定半透明（随任意底色可用）。
 */
import { computed } from 'vue'

const props = defineProps<{ nodeProps: Record<string, unknown> }>()

const align = computed(() => {
  const a = String(props.nodeProps.align ?? 'center')
  return a === 'left' ? 'flex-start' : a === 'right' ? 'flex-end' : 'center'
})
const text = computed(() => String(props.nodeProps.text ?? '标题'))
</script>

<template>
  <div class="title-bar" :style="{ justifyContent: align }">
    <span class="bar-text">{{ text }}</span>
  </div>
</template>

<style scoped>
.title-bar {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  padding: 0 28px;
  position: relative;
  /* 固定中性半透明底，不用 color-mix：① Chrome 90 基线不支持 ② html2canvas 解析
     color-mix/color() 会抛错，直接导致台账缩略图整页截图失败（见 docs/经验教训.md） */
  background: linear-gradient(180deg, rgba(148, 163, 184, 0.12), transparent 85%);
  color: var(--dev-color, #909399);
  border-bottom: 2px solid currentColor;
  box-sizing: border-box;
}

.bar-text {
  font-size: 28px;
  font-weight: 700;
  letter-spacing: 0.18em;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
