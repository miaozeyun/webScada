<script setup lang="ts">
/** 网页嵌入（M7，对齐 BY「网页」组件）：iframe 沙箱嵌入外部页面/本地监控页。
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
    <div v-else class="empty">配置网页 URL（https://…）</div>
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

.empty {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #94a3b8;
  font-size: 12px;
  background: repeating-linear-gradient(45deg, transparent 0 10px, rgba(148, 163, 184, 0.08) 10px 20px);
}
</style>
