<script setup lang="ts">
/** 视频（M7，对齐 业界主流组态「视频」）：HTML5 原生 video（mp4/webm/hls 视浏览器而定）。
 * RTSP/GB28181 需流媒体网关转 WebRTC/HTTP-FLV（企业版），此处给占位提示。
 * 编辑态禁用指针事件（同 WebFrameWidget）。 */
import { computed } from 'vue'
import { useRuntimeStore } from '@/runtime/store'

const props = defineProps<{ nodeProps: Record<string, unknown> }>()
const runtime = useRuntimeStore()

const url = computed(() => String(props.nodeProps.url ?? ''))
const isRtsp = computed(() => /^rtsp:\/\//i.test(url.value))
</script>

<template>
  <div class="video-widget">
    <video
      v-if="url && !isRtsp"
      :src="url"
      :autoplay="nodeProps.autoPlay !== false"
      :muted="nodeProps.muted !== false"
      :loop="nodeProps.loop !== false"
      :controls="nodeProps.controls !== false"
      :style="{ pointerEvents: runtime.running ? 'auto' : 'none' }"
      playsinline
    />
    <div v-else-if="isRtsp" class="ws-canvas-empty">
      RTSP 流需流媒体网关转码（WebRTC/HTTP-FLV）后以 http(s) 地址接入
    </div>
    <div v-else class="ws-canvas-empty">{{ runtime.running ? '视频未配置' : '在右侧属性填入视频 URL' }}</div>
  </div>
</template>

<style scoped>
.video-widget {
  width: 100%;
  height: 100%;
  overflow: hidden;
  background: #000;
}

video {
  width: 100%;
  height: 100%;
  object-fit: contain;
  display: block;
}
</style>
