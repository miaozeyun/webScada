<script setup lang="ts">
/** 分享页（M6）：/s/:token 匿名只读运行态，快照 doc + RuntimeEngine（匿名不上报报警记录）。 */
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import type { ProjectDoc } from '@/types/doc'
import { getShareDoc } from '@/api/shares'
import RuntimeStage from '@/editor/RuntimeStage.vue'

const route = useRoute()
const doc = ref<ProjectDoc | null>(null)
const projectName = ref('')
const loadError = ref('')

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
    <RuntimeStage v-if="doc" :doc="doc" :title="`${projectName} · 分享`" />
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
  color: #909399;
  background: #f5f7fa;
  font-size: 14px;
}

.share-error a {
  color: #409eff;
  text-decoration: none;
}
</style>
