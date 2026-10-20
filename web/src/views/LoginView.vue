<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { FormInstance, FormRules } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import ThemePicker from '@/components/ThemePicker.vue'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

const formRef = ref<FormInstance>()
const loading = ref(false)
const form = reactive({ username: 'admin', password: '' })

const rules: FormRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

async function onSubmit(): Promise<void> {
  await formRef.value?.validate()
  loading.value = true
  try {
    await auth.login(form.username, form.password)
    router.push((route.query.redirect as string) || '/projects')
  } catch {
    /* 拦截器已提示（统一文案防枚举） */
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <div class="blueprint" aria-hidden="true"></div>

    <!-- 工程单线图：母线 → 断路器 → 变压器 → 馈线，作为背景的结构语言 -->
    <svg class="single-line" viewBox="0 0 720 340" aria-hidden="true">
      <line class="bus" x1="0" y1="54" x2="720" y2="54" />
      <g class="feeder">
        <line x1="150" y1="54" x2="150" y2="112" />
        <rect x="138" y="112" width="24" height="24" />
        <line x1="150" y1="136" x2="150" y2="196" />
        <circle cx="150" cy="210" r="14" />
        <circle cx="150" cy="226" r="14" />
        <line x1="150" y1="240" x2="150" y2="308" />
        <line x1="132" y1="308" x2="168" y2="308" />
        <path d="M150 308 L150 330" />
      </g>
      <g class="feeder">
        <line x1="360" y1="54" x2="360" y2="96" />
        <rect x="348" y="96" width="24" height="24" />
        <line x1="360" y1="120" x2="360" y2="330" />
        <line x1="342" y1="286" x2="378" y2="286" />
      </g>
      <g class="feeder faint">
        <line x1="560" y1="54" x2="560" y2="140" />
        <rect x="548" y="140" width="24" height="24" />
        <line x1="560" y1="164" x2="560" y2="330" />
        <circle cx="560" cy="252" r="12" />
      </g>
      <line class="bus faint" x1="0" y1="330" x2="720" y2="330" />
    </svg>

    <main class="console">
      <section class="brand">
        <div class="brand-line">
          <svg class="brand-mark" viewBox="0 0 32 32" aria-hidden="true">
            <rect x="0.75" y="0.75" width="30.5" height="30.5" />
            <path d="M5 21 H11 L14 12 L18 24 L21 16 H27" />
          </svg>
          <span class="brand-name">webScada</span>
        </div>

        <h1>组态监控平台</h1>
        <p class="brand-desc">在浏览器里搭建工业监控画面，接入实时数据，把画面交给现场。</p>

        <dl class="specs">
          <div>
            <dt>数据通道</dt>
            <dd>MQTT · WebSocket · REST</dd>
          </div>
          <div>
            <dt>画面组织</dt>
            <dd>多页面 · 自适应缩放</dd>
          </div>
          <div>
            <dt>运行能力</dt>
            <dd>实时曲线 · 报警 · 反控</dd>
          </div>
        </dl>
      </section>

      <section class="access">
        <h2>操作员登录</h2>
        <p class="access-desc">使用平台账号继续管理工程。</p>

        <el-form ref="formRef" :model="form" :rules="rules" label-position="top" @keyup.enter="onSubmit">
          <el-form-item label="用户名" prop="username">
            <el-input v-model="form.username" placeholder="用户名" size="large" autocomplete="username" />
          </el-form-item>
          <el-form-item label="密码" prop="password">
            <el-input
              v-model="form.password"
              type="password"
              placeholder="密码"
              size="large"
              show-password
              autocomplete="current-password"
            />
          </el-form-item>
          <el-button type="primary" class="login-btn" :loading="loading" @click="onSubmit">进入控制台</el-button>
        </el-form>

        <p class="access-foot">会话凭证保存在本地浏览器，退出登录即清除。</p>
      </section>
    </main>

    <footer class="login-foot">
      <span>webScada 组态监控平台</span>
      <span class="foot-ver">v0.1</span>
      <ThemePicker />
    </footer>
  </div>
</template>

<style scoped>
.login-page {
  position: relative;
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 28px;
  overflow: hidden;
  padding: 36px 0 28px;
  background:
    radial-gradient(1100px 560px at 12% -10%, var(--ws-ink-3) 0%, transparent 62%),
    linear-gradient(158deg, var(--ws-ink-2) 0%, var(--ws-ink) 58%, var(--ws-ink) 100%);
  color: var(--ws-text-inverse);
}

/* 工程网格：只在中部透出，四周压暗 */
.blueprint {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(255, 255, 255, 0.05) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255, 255, 255, 0.05) 1px, transparent 1px);
  background-size: 48px 48px;
  -webkit-mask-image: radial-gradient(980px 680px at 50% 42%, #000 25%, transparent 82%);
  mask-image: radial-gradient(980px 680px at 50% 42%, #000 25%, transparent 82%);
  pointer-events: none;
}

.single-line {
  position: absolute;
  right: -30px;
  bottom: -12px;
  width: min(760px, 62vw);
  fill: none;
  stroke: var(--ws-signal-bright);
  stroke-width: 1.4;
  opacity: 0.5;
  pointer-events: none;
}

.single-line .bus {
  stroke: rgba(238, 244, 247, 0.5);
}

.single-line .faint {
  opacity: 0.55;
}

/* 控制柜面板 */
.console {
  position: relative;
  z-index: 1;
  width: min(980px, calc(100vw - 48px));
  display: grid;
  grid-template-columns: 1.06fr 0.94fr;
  background: var(--ws-steel-0);
  border: 1px solid rgba(238, 244, 247, 0.18);
  border-top: 3px solid var(--ws-signal-bright);
  box-shadow: 0 28px 80px rgba(0, 0, 0, 0.5);
  color: var(--ws-text);
}

/* 四角刻度：面板安装标记 */
.console::before,
.console::after {
  content: '';
  position: absolute;
  width: 10px;
  height: 10px;
  border-color: var(--ws-signal);
  border-style: solid;
  pointer-events: none;
}

.console::before {
  left: 7px;
  top: 7px;
  border-width: 1px 0 0 1px;
}

.console::after {
  right: 7px;
  bottom: 7px;
  border-width: 0 1px 1px 0;
}

.brand {
  padding: 46px 44px 40px;
}

.brand-line {
  display: flex;
  align-items: center;
  gap: 10px;
}

.brand-mark {
  width: 26px;
  height: 26px;
  fill: none;
  stroke: var(--ws-signal);
  stroke-width: 1.6;
  stroke-linejoin: round;
  stroke-linecap: round;
}

.brand-name {
  font-family: var(--ws-font-tech);
  font-size: 15px;
  font-weight: 600;
  letter-spacing: 0.1em;
  color: var(--ws-text);
}

.brand h1 {
  margin: 30px 0 14px;
  font-size: 38px;
  line-height: 1.22;
  font-weight: 600;
  letter-spacing: 0.01em;
  color: var(--ws-text);
}

.brand-desc {
  max-width: 34em;
  margin: 0;
  font-size: 14px;
  line-height: 1.8;
  color: var(--ws-text-2);
}

.specs {
  margin: 34px 0 0;
  padding-top: 18px;
  border-top: 1px solid var(--ws-steel-3);
  display: grid;
  gap: 9px;
}

.specs > div {
  display: flex;
  align-items: baseline;
  gap: 16px;
}

.specs dt {
  width: 72px;
  flex-shrink: 0;
  font-size: 12px;
  color: var(--ws-text-3);
}

.specs dd {
  margin: 0;
  font-family: var(--ws-font-tech);
  font-variant-numeric: tabular-nums;
  font-size: 12.5px;
  letter-spacing: 0.02em;
  color: var(--ws-text-2);
}

/* 登录区：嵌入面板的白色模块 */
.access {
  padding: 46px 40px 36px;
  background: var(--ws-panel);
  border-left: 1px solid var(--ws-steel-3);
}

.access h2 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--ws-text);
}

.access-desc {
  margin: 8px 0 26px;
  font-size: 13px;
  color: var(--ws-text-3);
}

.access :deep(.el-form-item) {
  margin-bottom: 18px;
}

.access :deep(.el-form-item__label) {
  padding-bottom: 5px;
  font-size: 12px;
  font-weight: 500;
  color: var(--ws-text-2);
}

.login-btn {
  width: 100%;
  height: 40px;
  margin-top: 4px;
  --el-button-bg-color: var(--ws-action);
  --el-button-border-color: var(--ws-action);
  --el-button-hover-bg-color: var(--ws-action-hover);
  --el-button-hover-border-color: var(--ws-action-hover);
  --el-button-active-bg-color: var(--ws-action-hover);
  --el-button-active-border-color: var(--ws-action-hover);
  font-size: 14px;
  letter-spacing: 0.04em;
}

.access-foot {
  margin: 22px 0 0;
  font-size: 11.5px;
  line-height: 1.7;
  color: var(--ws-text-3);
}

.login-foot {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: center;
  gap: 18px;
  font-size: 11.5px;
  color: rgba(238, 244, 247, 0.45);
}

.foot-ver {
  font-family: var(--ws-font-tech);
  letter-spacing: 0.06em;
}

/* 窄屏：面板单列，弱化背景图形 */
@media (max-width: 900px) {
  .login-page {
    justify-content: flex-start;
    padding-top: 24px;
  }

  .console {
    grid-template-columns: 1fr;
  }

  .brand {
    padding: 32px 28px 26px;
  }

  .brand h1 {
    margin-top: 20px;
    font-size: 30px;
  }

  .brand-desc {
    font-size: 13px;
  }

  .specs {
    margin-top: 24px;
  }

  .access {
    padding: 28px;
    border-left: none;
    border-top: 1px solid var(--ws-steel-3);
  }

  .single-line {
    display: none;
  }
}

@media (max-height: 700px) and (min-width: 901px) {
  .brand {
    padding-top: 34px;
    padding-bottom: 30px;
  }

  .brand h1 {
    margin: 20px 0 12px;
    font-size: 32px;
  }

  .specs {
    margin-top: 24px;
  }
}
</style>
