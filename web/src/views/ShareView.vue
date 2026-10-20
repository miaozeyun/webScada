<script setup lang="ts">
/** 分享页（M6/M7）：/s/:token 匿名只读运行态，快照 doc + RuntimeEngine（匿名不上报报警记录）。
 * M7：恒为只读（writable=false，反控禁用）；?embed=1 纯画面嵌入（iframe 场景隐藏标题栏）。 */
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import type { ProjectDoc } from '@/types/doc'
import { getShareDoc } from '@/api/shares'
import RuntimeStage from '@/editor/RuntimeStage.vue'

const route = useRoute()
const doc = ref<ProjectDoc | null>(null)
const projectName = ref('')
const loadError = ref('')
const embed = computed(() => route.query.embed === '1')

onMounted(async () => {
  try {
    const share = await getShareDoc(String(route.params.token))
    doc.value = share.doc
    projectName.value = share.projectName
    document.title = `${share.projectName} · webScada 分享`
  } catch {
    loadError.value = '分享链接不存在、已撤销或已过期'
  }
})
</script>

<template>
  <div class="share-view">
    <RuntimeStage v-if="doc" :doc="doc" :title="`${projectName} · 分享`" :writable="false" :embed="embed" />
    <div v-else-if="loadError" class="share-error">
      <p>{{ loadError }}</p>
      <a href="/">返回首页</a>
    </div>
    <div v-else class="share-error">加载中…</div>
  </div>
</template>

<style scoped>
.share-view {
  height: 100vh;
}

.share-error {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  color: var(--ws-text-3);
  background: #0d1823;
  font-size: 14px;
}

.share-error a {
  color: var(--ws-signal-bright);
  text-decoration: none;
}
</style>
