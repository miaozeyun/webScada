<script setup lang="ts">
import { onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { FormInstance, FormRules } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import ThemePicker from '@/components/ThemePicker.vue'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

const formRef = ref<FormInstance>()
const loading = ref(false)
// 不预填用户名：避免向访客暴露有效账号名（admin 为默认管理员）
const form = reactive({ username: '', password: '' })
// 记住我（缺省勾选）：签发 7 天 refresh token，access 过期自动续期免重复登录
const remember = ref(true)
/** 构建期注入的版本号（vite define __APP_VERSION__，取 package.json） */
const version = __APP_VERSION__

const rules: FormRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

// ---- 遥测读数带：登录页的"活仪表"（纯装饰模拟值；reduced-motion 下静止） ----

interface TelemetryItem {
  tag: string
  value: number
  unit: string
  min: number
  max: number
  step: number
  digits: number
}

const telemetry = reactive<TelemetryItem[]>([
  { tag: 'FLOW-101', value: 412.6, unit: 'm³/h', min: 380, max: 445, step: 3.2, digits: 1 },
  { tag: 'TEMP-201', value: 63.4, unit: '℃', min: 58, max: 68, step: 0.4, digits: 1 },
  { tag: 'PRESS-301', value: 0.38, unit: 'MPa', min: 0.32, max: 0.44, step: 0.008, digits: 2 },
  { tag: 'LEVEL-401', value: 72.5, unit: '%', min: 65, max: 80, step: 0.9, digits: 1 },
])

let telemetryTimer: number | undefined

onMounted(() => {
  if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    telemetryTimer = window.setInterval(() => {
      for (const t of telemetry) {
        const drift = (Math.random() - 0.5) * 2 * t.step
        t.value = Math.min(t.max, Math.max(t.min, t.value + drift))
      }
    }, 2200)
  }
})

onBeforeUnmount(() => window.clearInterval(telemetryTimer))

async function onSubmit(): Promise<void> {
  await formRef.value?.validate()
  loading.value = true
  try {
    await auth.login(form.username, form.password, remember.value)
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

    <!-- 背景工艺线稿（P&ID 语汇）：原料罐 → 泵 → 换热器 → 成品罐 + 趋势框，
         主管道带缓慢流动动画；整体只占右侧低区，为表单留出安静区 -->
    <svg class="process-sketch" viewBox="0 0 960 520" aria-hidden="true">
      <!-- 原料罐（左）：圆头容器 + 液位线 + 侧壁刻度 -->
      <g class="p-line major">
        <path d="M120 130 v210 a46 46 0 0 0 46 46 h96 a46 46 0 0 0 46 -46 v-210 a46 46 0 0 0 -46 -46 h-96 a46 46 0 0 0 -46 46 z" />
        <path d="M132 210 h164" class="p-fill-line" />
        <path d="M132 250 h164" class="p-fill-line faint" />
        <path d="M316 170 v8 M316 192 v8 M316 214 v8 M316 236 v8" class="p-tick" />
      </g>
      <!-- 成品罐（右，小一号） -->
      <g class="p-line">
        <path d="M700 190 v160 a38 38 0 0 0 38 38 h76 a38 38 0 0 0 38 -38 v-160 a38 38 0 0 0 -38 -38 h-76 a38 38 0 0 0 -38 38 z" />
        <path d="M710 258 h132" class="p-fill-line" />
      </g>
      <!-- 泵：圆 + 出口三角 -->
      <g class="p-line major">
        <circle cx="440" cy="400" r="26" />
        <path d="M440 374 v52 M414 400 h52" class="p-inner" />
      </g>
      <!-- 换热器：圆 + 内折管 -->
      <g class="p-line">
        <circle cx="580" cy="250" r="34" />
        <path d="M558 250 h8 l6 -14 8 28 8 -28 8 28 6 -14 h8" class="p-inner" />
      </g>
      <!-- 阀门（蝶阀符号）×2 -->
      <g class="p-line major">
        <path d="M366 400 l-14 -12 v24 z M394 400 l14 -12 v24 z" />
      </g>
      <g class="p-line">
        <path d="M636 250 l-12 -10 v20 z M660 250 l12 -10 v20 z" />
      </g>
      <!-- 管道：罐 → 阀 → 泵 → 换热器 → 成品罐（横平竖直，工艺图惯例） -->
      <path class="p-pipe flow" d="M308 386 h44 v14 h0 M352 400 h14 M394 400 h20 M466 400 h60 v-116" />
      <path class="p-pipe" d="M580 284 v56 h180 M672 250 h28 M546 250 h-88 v-90 h120" />
      <path class="p-pipe flow" d="M314 386 h-6 v-146 h120" />
      <!-- 趋势框（右上）：小折线图线稿 -->
      <g class="p-line">
        <rect x="700" y="70" width="150" height="64" rx="2" />
        <path d="M710 116 l18 -12 14 18 16 -26 14 14 18 -8 12 10 14 -16 16 20 18 -12" class="p-inner" />
      </g>
      <!-- 标注线（工程图纸感） -->
      <g class="p-dim">
        <path d="M120 430 h614" />
        <path d="M120 424 v12 M734 424 v12" />
      </g>
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
          <div class="remember-row">
            <el-checkbox v-model="remember">记住我 7 天</el-checkbox>
          </div>
          <el-button type="primary" class="login-btn" :loading="loading" @click="onSubmit">进入控制台</el-button>
        </el-form>

        <p class="access-foot">会话凭证保存在本地浏览器，退出登录即清除。</p>
      </section>
    </main>

    <!-- 遥测读数带：等宽字体的活读数，让登录页像一间开着的控制室 -->
    <div class="telemetry" aria-hidden="true">
      <span class="tl-dot"></span>
      <span v-for="t in telemetry" :key="t.tag" class="tl-item">
        <span class="tl-tag">{{ t.tag }}</span>
        <span class="tl-value ws-readout">{{ t.value.toFixed(t.digits) }}</span>
        <span class="tl-unit">{{ t.unit }}</span>
      </span>
    </div>

    <footer class="login-foot">
      <span>webScada 组态监控平台</span>
      <span class="foot-ver">v{{ version }}</span>
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

/* 背景工艺线稿：P&ID 语汇，双层透明度（major 主设备 / 次级管件） */
.process-sketch {
  position: absolute;
  right: -60px;
  bottom: 34px;
  width: min(1040px, 76vw);
  fill: none;
  stroke: var(--ws-signal-bright);
  stroke-width: 1.3;
  opacity: 0.34;
  pointer-events: none;
}

.process-sketch .p-line {
  opacity: 0.85;
}

.process-sketch .p-line:not(.major) {
  opacity: 0.55;
}

.process-sketch .p-inner {
  stroke-width: 1;
  opacity: 0.8;
}

.process-sketch .p-fill-line {
  stroke: var(--ws-signal-bright);
  stroke-dasharray: 3 4;
  opacity: 0.9;
}

.process-sketch .p-fill-line.faint {
  opacity: 0.5;
}

.process-sketch .p-tick {
  stroke-width: 1;
  opacity: 0.6;
}

.process-sketch .p-pipe {
  stroke: rgba(238, 244, 247, 0.5);
  stroke-width: 1.2;
}

.process-sketch .p-dim {
  stroke: rgba(238, 244, 247, 0.3);
  stroke-width: 1;
}

/* 主管道流动：虚线缓慢位移（reduced-motion 下静止） */
.process-sketch .flow {
  stroke-dasharray: 5 7;
  animation: sketchFlow 14s linear infinite;
}

@keyframes sketchFlow {
  to {
    stroke-dashoffset: -120;
  }
}

@media (prefers-reduced-motion: reduce) {
  .process-sketch .flow {
    animation: none;
  }
}

/* 遥测读数带：控制室顶棚的读数屏 */
.telemetry {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: center;
  gap: 26px;
  padding: 9px 22px;
  border: 1px solid var(--ws-inv-line);
  background: rgba(8, 16, 24, 0.3);
}

.tl-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--ws-ok-bright);
  box-shadow: 0 0 6px var(--ws-ok-bright);
  flex-shrink: 0;
}

.tl-item {
  display: inline-flex;
  align-items: baseline;
  gap: 7px;
  white-space: nowrap;
}

.tl-tag {
  font-family: var(--ws-font-tech);
  font-size: 11px;
  letter-spacing: 0.06em;
  color: var(--ws-inv-42);
}

.tl-value {
  font-size: 16px;
  font-weight: 600;
  color: var(--ws-signal-bright);
}

.tl-unit {
  font-size: 11px;
  color: var(--ws-inv-42);
}

/* 控制柜面板 */
.console {
  position: relative;
  z-index: 1;
  width: min(980px, calc(100vw - 48px));
  display: grid;
  grid-template-columns: 1.06fr 0.94fr;
  background: var(--ws-steel-0);
  border: 1px solid var(--ws-inv-line);
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
  font-size: 13px;
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

.remember-row {
  display: flex;
  align-items: center;
  margin: -4px 0 14px;
}

.remember-row :deep(.el-checkbox__label) {
  font-size: 12px;
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
  font-size: 11px;
  line-height: 1.7;
  color: var(--ws-text-3);
}

.login-foot {
  position: relative;
  z-index: 1;
  width: min(980px, calc(100vw - 48px));
  display: flex;
  align-items: center;
  gap: 24px;
  font-size: 11px;
  color: var(--ws-inv-42);
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

  .process-sketch {
    display: none;
  }
}

/* 窄屏遥测带：只保留两项读数，避免挤压 */
@media (max-width: 640px) {
  .telemetry {
    gap: 18px;
  }

  .tl-item:nth-child(n + 4) {
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
