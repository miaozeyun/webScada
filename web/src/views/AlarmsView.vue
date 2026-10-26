<script setup lang="ts">
/**
 * 报警中心（2026-10-26）：单工程报警历史/确认，交接班查遗留报警用。
 * 复用 AlarmPanel（过滤/分页/ack/角色控制），本页只提供路由与工程上下文。
 */
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft } from '@element-plus/icons-vue'
import { getProject } from '@/api/projects'
import AlarmPanel from '@/components/alarm/AlarmPanel.vue'

const route = useRoute()
const router = useRouter()
const projectId = String(route.params.id ?? '')
const projectName = ref('')
const loadError = ref('')

onMounted(async () => {
  try {
    const p = await getProject(projectId)
    projectName.value = p.name
    document.title = `报警 · ${p.name}`
  } catch {
    loadError.value = '工程不存在或无权访问'
  }
})
</script>

<template>
  <div class="alarms-page">
    <header class="app-bar">
      <button class="back" type="button" @click="router.push('/projects')">
        <el-icon><ArrowLeft /></el-icon>工程台账
      </button>
      <span class="title">报警中心</span>
      <span class="name">{{ projectName }}</span>
      <span class="spacer" />
      <el-button size="small" @click="router.push(`/editor/${projectId}`)">返回编辑器</el-button>
    </header>

    <main class="body">
      <el-alert
        v-if="loadError"
        :title="loadError"
        type="error"
        :closable="false"
        show-icon
        class="err"
      />
      <AlarmPanel v-else :project-id="projectId" />
    </main>
  </div>
</template>

<style scoped>
.alarms-page {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--ws-canvas);
}

.app-bar {
  height: 52px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 0 20px;
  background: var(--ws-ink);
  color: var(--ws-text-inverse);
}

.back {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
  border: 1px solid rgba(148, 163, 184, 0.3);
  border-radius: 6px;
  background: transparent;
  color: var(--ws-inv-88);
  font-size: 13px;
  cursor: pointer;
}

.back:hover {
  color: #fff;
  border-color: var(--ws-signal-bright);
}

.title {
  font-size: 14px;
  font-weight: 600;
}

.name {
  color: var(--ws-inv-60);
  font-size: 13px;
}

.spacer {
  flex: 1;
}

.body {
  flex: 1;
  min-height: 0;
  padding: 16px 20px 20px;
  display: flex;
  flex-direction: column;
}

.err {
  margin-bottom: 12px;
}
</style>
