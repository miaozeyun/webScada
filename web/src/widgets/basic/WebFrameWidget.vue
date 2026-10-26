<script setup lang="ts">
/** 网页嵌入（M7，对齐 业界主流组态「网页」组件）：iframe 沙箱嵌入外部页面/本地监控页。
 * 目标站若设置 X-Frame-Options/CSP frame-ancestors 会拒绝加载，显示占位提示。
 * 编辑态（runtime 未启动）iframe 禁用指针事件，避免吞掉画布选中/拖拽。 */
import { computed } from 'vue'
import { useRuntimeStore } from '@/runtime/store'

const props = defineProps<{ nodeProps: Record<string, unknown> }>()
const runtime = useRuntimeStore()

const url = computed(() => String(props.nodeProps.url ?? ''))
const sandbox = computed(() =>
  String(props.nodeProps.sandbox ?? 'allow-scripts allow-same-origin allow-forms allow-popups'),
)
</script>

<template>
  <div class="web-frame">
    <iframe
      v-if="url"
      :src="url"
      :sandbox="sandbox"
      :style="{ pointerEvents: runtime.running ? 'auto' : 'none' }"
      frameborder="0"
      allow="fullscreen"
      referrerpolicy="no-referrer"
    />
    <div v-else class="ws-canvas-empty">{{ runtime.running ? '网页未配置' : '在右侧属性填入网页 URL' }}</div>
  </div>
</template>

<style scoped>
.web-frame {
  width: 100%;
  height: 100%;
  background: #fff;
  overflow: hidden;
}

iframe {
  width: 100%;
  height: 100%;
  border: 0;
  display: block;
}
</style>
