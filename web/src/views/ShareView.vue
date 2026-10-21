<script setup lang="ts">
/** 分享页（M6/M7，M8 扩展）：/s/:token 匿名只读运行态。
 * M8：快照 doc 仅决定渲染；值流/报警经服务端 WS（shareToken 通道，只读）。
 * reload 帧（分享快照被刷新）→ 重取快照 doc 并整体重启引擎（03 §3.4 换版语义）。
 * 顶栏：分享页默认无顶栏（chromeless，画面铺满视口，右上角悬浮全屏）；?embed=1 连悬浮按钮一并隐藏。 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import type { ProjectDoc } from '@/types/doc'
import { getShareDoc } from '@/api/shares'
import { setHistoryProjectId, setHistoryShareToken } from '@/api/history'
import RuntimeStage from '@/editor/RuntimeStage.vue'

const route = useRoute()
const token = computed(() => String(route.params.token))
const doc = ref<ProjectDoc | null>(null)
const projectName = ref('')
const loadError = ref('')
const embed = computed(() => route.query.embed === '1')

async function load(): Promise<void> {
  loadError.value = ''
  try {
    // 分享页历史图接服务端 /history（api/history 分享通道）：注入 Bearer shareToken，
    // doc 就绪后注入工程 id（历史图组件无法从快照 doc 反查 projectId）
    setHistoryShareToken(token.value)
    const share = await getShareDoc(token.value)
    doc.value = share.doc
    setHistoryProjectId(share.doc.project.id)
    // 公开出参收窄为 {projectId, createdAt, doc}（03 §2.6）：工程名取快照 doc 内的 project.name
    const name = share.doc.project?.name ?? ''
    projectName.value = name
    document.title = `${name} · webScada 分享`
  } catch {
    if (!doc.value) loadError.value = '分享链接不存在、已撤销或已过期'
  }
}

/** 失败重试：清错误回到加载态后重取快照 */
function retry(): void {
  loadError.value = ''
  void load()
}

// M8：reload 帧 → 快照换版（doc 引用替换驱动 RuntimeStage 重启引擎；值流不断线）
function onServerReload(): void {
  load()
}

onMounted(load)

// 离开分享页：恢复 JWT 历史通道并清注入，防分享 token 泄漏到编辑器预览等后续页面
onBeforeUnmount(() => {
  setHistoryShareToken(null)
  setHistoryProjectId('')
})
</script>

<template>
  <div class="share-view">
    <RuntimeStage
      v-if="doc"
      :doc="doc"
      :title="`${projectName} · 分享`"
      :writable="false"
      :server-token="token"
      :embed="embed"
      :chromeless="true"
      @server-reload="onServerReload"
    />
    <div v-else-if="loadError" class="share-fallback">
      <svg class="fallback-mark" viewBox="0 0 48 48" aria-hidden="true">
        <rect x="5.5" y="9.5" width="37" height="29" />
        <path d="M5.5 17.5 H42.5 M11.5 13.5 H13 M15.5 13.5 H17" />
        <path d="M18 32 L23 26 L27 30 L32 20" />
        <path d="M32 20 L32 26 M32 20 L26 20" />
      </svg>
      <p class="fallback-text">{{ loadError }}</p>
      <div class="fallback-actions">
        <el-button size="small" type="primary" plain @click="retry">重试</el-button>
        <a class="fallback-link" href="/">返回首页</a>
      </div>
    </div>
    <div v-else class="share-fallback">
      <span class="ws-spinner" role="status" aria-label="加载中" />
      <p class="fallback-text">正在载入画面…</p>
    </div>
  </div>
</template>

<style scoped>
.share-view {
  height: 100vh;
}

/* 加载/错误态与全站浅色工业主题一致（此前为旧深色残留） */
.share-fallback {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 14px;
  background: var(--ws-canvas);
  color: var(--ws-text-2);
  font-size: 14px;
}

.fallback-mark {
  width: 48px;
  height: 48px;
  fill: none;
  stroke: var(--ws-steel-3);
  stroke-width: 1.4;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.fallback-text {
  margin: 0;
}

.fallback-actions {
  display: flex;
  align-items: center;
  gap: 16px;
}

.fallback-link {
  color: var(--ws-signal);
  text-decoration: none;
}

.fallback-link:hover {
  text-decoration: underline;
}
</style>
