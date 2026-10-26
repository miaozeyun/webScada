<script setup lang="ts">
/**
 * 报警中心（2026-10-26）：单工程报警历史/确认，交接班查遗留报警用。
 * 复用 AlarmPanel（过滤/分页/ack/角色控制），本页只提供路由与工程上下文。
 */
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getProject } from '@/api/projects'
import { fetchMyRole } from '@/api/alarms'
import AlarmPanel from '@/components/alarm/AlarmPanel.vue'
import AppBar from '@/components/AppBar.vue'

const route = useRoute()
const router = useRouter()
const projectId = String(route.params.id ?? '')
const projectName = ref('')
const loadError = ref('')
/** viewer 只读账号进不了编辑器（路由守卫会弹回台账），不必显示「返回编辑器」 */
const canEdit = ref(false)

onMounted(async () => {
  const [project] = await Promise.all([
    getProject(projectId).catch(() => null),
    fetchMyRole()
      .then((role) => {
        canEdit.value = role === 'admin' || role === 'operator'
      })
      .catch(() => {}),
  ])
  if (!project) {
    loadError.value = '工程不存在或无权访问'
    return
  }
  projectName.value = project.name
  document.title = `报警 · ${project.name}`
})
</script>

<template>
  <div class="alarms-page">
    <AppBar scope="报警中心" :subtitle="projectName">
      <template #actions>
        <button class="ws-ghost-btn" type="button" @click="router.push('/projects')">返回台账</button>
        <button
          v-if="canEdit"
          class="ws-ghost-btn"
          type="button"
          @click="router.push(`/editor/${projectId}`)"
        >
          返回编辑器
        </button>
      </template>
    </AppBar>

    <main class="body">
      <el-alert
        v-if="loadError"
        :title="loadError"
        type="error"
        :closable="false"
        show-icon
        class="err"
      />
      <AlarmPanel v-else :project-id="projectId" :auto-refresh-sec="15" />
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
