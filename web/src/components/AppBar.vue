<script setup lang="ts">
/**
 * 控制台顶栏（工程台账 / 报警中心 / 仿真台 / 系统管理共用）。
 *
 * 此前四个视图各自复制一份同样的顶栏样式，已经出现「报警中心 52px、其余 48px」的漂移；
 * 收敛到本组件后，品牌区、配色选择、用户名与退出登录只有一处实现。
 * 视图差异走插槽：`nav`（管理页页签等）与 `actions`（返回台账等业务按钮）。
 */
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import ThemePicker from '@/components/ThemePicker.vue'

withDefaults(
  defineProps<{
    /** 当前页面名（品牌名后的分隔文字） */
    scope: string
    /** 附加上下文（如报警中心的工程名），窄屏自动隐藏 */
    subtitle?: string
    showTheme?: boolean
    showUser?: boolean
    showLogout?: boolean
  }>(),
  { subtitle: '', showTheme: true, showUser: true, showLogout: true },
)

const router = useRouter()
const auth = useAuthStore()

async function onLogout(): Promise<void> {
  await auth.logout()
  router.push('/login')
}
</script>

<template>
  <header class="app-bar">
    <div class="bar-brand">
      <svg class="bar-mark" viewBox="0 0 32 32" aria-hidden="true">
        <rect x="0.75" y="0.75" width="30.5" height="30.5" />
        <path d="M5 21 H11 L14 12 L18 24 L21 16 H27" />
      </svg>
      <span class="bar-name">webScada</span>
      <span class="bar-divider" aria-hidden="true" />
      <span class="bar-scope">{{ scope }}</span>
      <span v-if="subtitle" class="bar-sub" :title="subtitle">{{ subtitle }}</span>
    </div>
    <div class="bar-user">
      <slot name="nav" />
      <slot name="actions" />
      <ThemePicker v-if="showTheme" />
      <span v-if="showUser" class="user-name">{{ auth.username }}</span>
      <button v-if="showLogout" class="ws-ghost-btn" type="button" @click="onLogout">退出登录</button>
    </div>
  </header>
</template>

<style scoped>
.app-bar {
  height: 48px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 0 24px;
  background: var(--ws-ink);
  color: var(--ws-text-inverse);
}

.bar-brand {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}

.bar-mark {
  flex-shrink: 0;
  width: 22px;
  height: 22px;
  fill: none;
  stroke: var(--ws-signal-bright);
  stroke-width: 1.6;
  stroke-linejoin: round;
  stroke-linecap: round;
}

.bar-name {
  font-family: var(--ws-font-tech);
  font-size: 14px;
  font-weight: 600;
  letter-spacing: 0.1em;
}

.bar-divider {
  flex-shrink: 0;
  width: 1px;
  height: 16px;
  background: var(--ws-inv-line);
}

.bar-scope {
  white-space: nowrap;
  font-size: 13px;
  color: var(--ws-inv-75);
}

.bar-sub {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
  color: var(--ws-inv-60);
}

.bar-user {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 16px;
}

.user-name {
  max-width: 160px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: var(--ws-font-tech);
  font-size: 12px;
  letter-spacing: 0.03em;
  color: var(--ws-inv-75);
}

/* 窄屏：保留品牌与操作按钮，隐去可省的上下文文字 */
@media (max-width: 480px) {
  .app-bar {
    padding: 0 12px;
    gap: 8px;
  }

  .bar-brand {
    gap: 8px;
  }

  .bar-scope,
  .bar-sub,
  .user-name {
    display: none;
  }

  .bar-user {
    gap: 8px;
  }
}
</style>
