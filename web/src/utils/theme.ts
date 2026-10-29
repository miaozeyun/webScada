/**
 * 界面配色主题：5 套工业配色，切换时写入 CSS 变量并派生 Element Plus 色阶。
 * 变量分三层：--ws-* 为产品自带令牌（含各主题手调的深底亮色），
 * 派生层（inv/signal-a/alert-a 等，见 applyTheme）由基础色计算，
 * --el-* 由主色/面板色计算得出。
 * 选择结果存 localStorage，登录页 / 工程台账 / 编辑器共享。
 */

export type ThemeId = 'electric' | 'prussian' | 'machine' | 'copper' | 'graphite'

export interface ThemeDef {
  id: ThemeId
  name: string
  desc: string
  /** 色卡：框架 / 工作区 / 信号 / 警示 */
  swatches: [string, string, string, string]
  vars: Record<string, string>
}

export const THEMES: ThemeDef[] = [
  {
    id: 'electric',
    name: '电气青',
    desc: '冷银灰工作台，电气青信号色',
    swatches: ['#14212e', '#e9edf1', '#0b7285', '#c2410c'],
    vars: {
      '--ws-ink': '#14212e',
      '--ws-ink-2': '#1d3040',
      '--ws-ink-3': '#2a4155',
      '--ws-steel-0': '#f8fafb',
      '--ws-steel-1': '#eef2f5',
      '--ws-steel-2': '#e2e8ee',
      '--ws-steel-3': '#cbd5df',
      '--ws-canvas': '#e9edf1',
      '--ws-panel': '#ffffff',
      '--ws-overlay': '#ffffff',
      '--ws-text': '#22313f',
      '--ws-text-2': '#56697a',
      '--ws-text-3': '#66788a',
      '--ws-text-inverse': '#eef4f7',
      '--ws-signal': '#0b7285',
      '--ws-signal-strong': '#095a69',
      '--ws-signal-bright': '#1ba7b8',
      '--ws-signal-soft': '#e4f2f4',
      '--ws-alert': '#c2410c',
      '--ws-alert-soft': '#f6e7e1',
      '--ws-warn': '#b87400',
      '--ws-ok': '#2f8a46',
      '--ws-ok-bright': '#7ddc93',
      '--ws-warn-bright': '#f5c25b',
      '--ws-alert-bright': '#ff9d6e',
      '--ws-select': '#1ba7b8',
      '--ws-action': '#14212e',
      '--ws-action-hover': '#2a4155',
    },
  },
  {
    id: 'prussian',
    name: '普鲁士蓝',
    desc: '配电网络的深钢蓝，冷峻克制',
    swatches: ['#101b2a', '#e7edf4', '#1d5b8f', '#b23a2e'],
    vars: {
      '--ws-ink': '#101b2a',
      '--ws-ink-2': '#172a3e',
      '--ws-ink-3': '#22415e',
      '--ws-steel-0': '#f7f9fc',
      '--ws-steel-1': '#ecf1f7',
      '--ws-steel-2': '#dfe7f0',
      '--ws-steel-3': '#c3d1df',
      '--ws-canvas': '#e7edf4',
      '--ws-panel': '#ffffff',
      '--ws-overlay': '#ffffff',
      '--ws-text': '#1a2a3b',
      '--ws-text-2': '#4d6378',
      '--ws-text-3': '#63768a',
      '--ws-text-inverse': '#eef3f8',
      '--ws-signal': '#1d5b8f',
      '--ws-signal-strong': '#164a75',
      '--ws-signal-bright': '#3a86c8',
      '--ws-signal-soft': '#e2edf7',
      '--ws-alert': '#b23a2e',
      '--ws-alert-soft': '#f6e5e2',
      '--ws-warn': '#a66a00',
      '--ws-ok': '#2f7a55',
      '--ws-ok-bright': '#7fd6a4',
      '--ws-warn-bright': '#f0bc63',
      '--ws-alert-bright': '#f2937f',
      '--ws-select': '#3a86c8',
      '--ws-action': '#101b2a',
      '--ws-action-hover': '#22415e',
    },
  },
  {
    id: 'machine',
    name: '机械绿',
    desc: '产线设备的机械绿，沉稳耐看',
    swatches: ['#182420', '#e8eeea', '#2f6b4f', '#b4451f'],
    vars: {
      '--ws-ink': '#182420',
      '--ws-ink-2': '#22332c',
      '--ws-ink-3': '#314b40',
      '--ws-steel-0': '#f5f8f6',
      '--ws-steel-1': '#eaf0ec',
      '--ws-steel-2': '#dde7e1',
      '--ws-steel-3': '#c3d2c9',
      '--ws-canvas': '#e8eeea',
      '--ws-panel': '#ffffff',
      '--ws-overlay': '#ffffff',
      '--ws-text': '#1f2e27',
      '--ws-text-2': '#51665b',
      '--ws-text-3': '#66796d',
      '--ws-text-inverse': '#eef5f0',
      '--ws-signal': '#2f6b4f',
      '--ws-signal-strong': '#245640',
      '--ws-signal-bright': '#4c9b77',
      '--ws-signal-soft': '#e2f0e9',
      '--ws-alert': '#b4451f',
      '--ws-alert-soft': '#f7e7e0',
      '--ws-warn': '#a87300',
      '--ws-ok': '#2f7a46',
      '--ws-ok-bright': '#7fd494',
      '--ws-warn-bright': '#efb659',
      '--ws-alert-bright': '#f19378',
      '--ws-select': '#4c9b77',
      '--ws-action': '#182420',
      '--ws-action-hover': '#314b40',
    },
  },
  {
    id: 'copper',
    name: '铜排',
    desc: '暖银灰与铜色母线，车间现场感',
    swatches: ['#261c14', '#efeae3', '#9a5b16', '#a3261c'],
    vars: {
      '--ws-ink': '#261c14',
      '--ws-ink-2': '#35281d',
      '--ws-ink-3': '#4a3828',
      '--ws-steel-0': '#faf8f5',
      '--ws-steel-1': '#f2eee8',
      '--ws-steel-2': '#e7e0d6',
      '--ws-steel-3': '#cfc3b3',
      '--ws-canvas': '#efeae3',
      '--ws-panel': '#ffffff',
      '--ws-overlay': '#ffffff',
      '--ws-text': '#2b2118',
      '--ws-text-2': '#615243',
      '--ws-text-3': '#7c6b57',
      '--ws-text-inverse': '#f6f0e9',
      '--ws-signal': '#9a5b16',
      '--ws-signal-strong': '#7e4a10',
      '--ws-signal-bright': '#c9822f',
      '--ws-signal-soft': '#f5ebdd',
      '--ws-alert': '#a3261c',
      '--ws-alert-soft': '#f6e5e2',
      '--ws-warn': '#8a6500',
      '--ws-ok': '#3d6b3a',
      '--ws-ok-bright': '#93cf8c',
      '--ws-warn-bright': '#e6b45c',
      '--ws-alert-bright': '#ef8f7a',
      '--ws-select': '#b87424',
      '--ws-action': '#261c14',
      '--ws-action-hover': '#4a3828',
    },
  },
  {
    id: 'graphite',
    name: '石墨深色',
    desc: '控制室深色底，荧光青读数',
    swatches: ['#0a1015', '#121a21', '#45c6d9', '#e06a3a'],
    vars: {
      '--ws-ink': '#0a1015',
      '--ws-ink-2': '#101a22',
      '--ws-ink-3': '#1b2a35',
      '--ws-steel-0': '#17222b',
      '--ws-steel-1': '#1c2934',
      '--ws-steel-2': '#263845',
      '--ws-steel-3': '#3a4e5f',
      '--ws-canvas': '#0c141a',
      '--ws-panel': '#121a21',
      '--ws-overlay': '#1a2733',
      '--ws-text': '#dce6ed',
      '--ws-text-2': '#a5b6c3',
      '--ws-text-3': '#748693',
      '--ws-text-inverse': '#ecf4f8',
      '--ws-signal': '#2a9db0',
      '--ws-signal-strong': '#1f7a8a',
      '--ws-signal-bright': '#45c6d9',
      '--ws-signal-soft': '#15333b',
      '--ws-alert': '#e06a3a',
      '--ws-alert-soft': '#33201a',
      '--ws-warn': '#d29a2e',
      '--ws-ok': '#4fae6e',
      '--ws-ok-bright': '#7fe0a0',
      '--ws-warn-bright': '#e8b45a',
      '--ws-alert-bright': '#f3966f',
      '--ws-select': '#45c6d9',
      '--ws-action': '#1f7a8a',
      '--ws-action-hover': '#2a9db0',
    },
  },
]

const STORAGE_KEY = 'webscada_theme'
const DEFAULT_THEME: ThemeId = 'electric'

function parseHex(hex: string): [number, number, number] {
  const raw = hex.replace('#', '')
  const full = raw.length === 3 ? raw.split('').map((c) => c + c).join('') : raw
  const n = Number.parseInt(full, 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

function toHex(rgb: [number, number, number]): string {
  return '#' + rgb.map((v) => Math.round(Math.max(0, Math.min(255, v))).toString(16).padStart(2, '0')).join('')
}

/** 线性混合：ratioB 为 b 的占比（0 = 全 a，1 = 全 b） */
function mix(a: string, b: string, ratioB: number): string {
  const [r1, g1, b1] = parseHex(a)
  const [r2, g2, b2] = parseHex(b)
  return toHex([r1 + (r2 - r1) * ratioB, g1 + (g2 - g1) * ratioB, b1 + (b2 - b1) * ratioB])
}

function alpha(hex: string, a: number): string {
  const [r, g, b] = parseHex(hex)
  return `rgba(${r}, ${g}, ${b}, ${a})`
}

export function getThemeId(): ThemeId {
  try {
    const saved = localStorage.getItem(STORAGE_KEY) as ThemeId | null
    if (saved && THEMES.some((t) => t.id === saved)) return saved
  } catch {
    /* 隐私模式：跳过存储，回落系统偏好 */
  }
  // 用户未做过选择时跟随系统深浅偏好（graphite 为深色主题；一旦手动选择即固定）
  return typeof matchMedia === 'function' && matchMedia('(prefers-color-scheme: dark)').matches
    ? 'graphite'
    : DEFAULT_THEME
}

export function applyTheme(id: ThemeId): void {
  const theme = THEMES.find((t) => t.id === id) ?? THEMES[0]
  const v = theme.vars
  const root = document.documentElement

  for (const [key, value] of Object.entries(v)) {
    root.style.setProperty(key, value)
  }

  // Element Plus 色阶：以面板色为混合底，深色主题下自动得到深色 hover/plain 底
  const panel = v['--ws-panel']
  const ink = v['--ws-ink']
  const families: Record<string, string> = {
    primary: v['--ws-signal'],
    success: v['--ws-ok'],
    warning: v['--ws-warn'],
    danger: v['--ws-alert'],
    error: v['--ws-alert'],
    info: v['--ws-text-3'],
  }
  // Element 语义：light-N 表示与面板色混合 N*10%，light-9 最接近面板色
  const steps: [string, number][] = [
    ['light-3', 0.3],
    ['light-5', 0.5],
    ['light-7', 0.7],
    ['light-8', 0.8],
    ['light-9', 0.9],
  ]
  for (const [name, base] of Object.entries(families)) {
    root.style.setProperty(`--el-color-${name}`, base)
    for (const [step, ratio] of steps) {
      root.style.setProperty(`--el-color-${name}-${step}`, mix(base, panel, ratio))
    }
    root.style.setProperty(`--el-color-${name}-dark-2`, mix(base, ink, 0.25))
  }

  const elVars: Record<string, string> = {
    '--el-text-color-primary': v['--ws-text'],
    '--el-text-color-regular': v['--ws-text-2'],
    '--el-text-color-secondary': v['--ws-text-3'],
    '--el-text-color-placeholder': mix(v['--ws-text-3'], panel, 0.35),
    '--el-text-color-disabled': mix(v['--ws-text-3'], panel, 0.55),
    '--el-border-color': v['--ws-steel-3'],
    '--el-border-color-light': v['--ws-steel-2'],
    '--el-border-color-lighter': v['--ws-steel-2'],
    '--el-border-color-extra-light': v['--ws-steel-1'],
    '--el-border-color-hover': v['--ws-text-3'],
    '--el-fill-color': v['--ws-steel-1'],
    '--el-fill-color-light': v['--ws-steel-0'],
    '--el-fill-color-lighter': v['--ws-steel-0'],
    '--el-fill-color-extra-light': v['--ws-panel'],
    '--el-fill-color-dark': v['--ws-steel-2'],
    '--el-fill-color-darker': v['--ws-steel-3'],
    '--el-fill-color-blank': v['--ws-panel'],
    '--el-bg-color': v['--ws-panel'],
    '--el-bg-color-page': v['--ws-canvas'],
    '--el-bg-color-overlay': v['--ws-overlay'],
    '--el-disabled-bg-color': v['--ws-steel-1'],
    '--el-disabled-text-color': v['--ws-text-3'],
    '--el-disabled-border-color': v['--ws-steel-2'],
    '--el-mask-color': alpha(ink, 0.55),
    '--el-mask-color-extra-light': alpha(ink, 0.3),
    '--el-overlay-color-lighter': alpha(ink, 0.5),
  }
  for (const [key, value] of Object.entries(elVars)) {
    root.style.setProperty(key, value)
  }

  // 派生令牌：深底（顶栏/工具条/状态栏）反白按透明度分档、信号与警示色的透明底、
  // 结构边线与按压态。收敛此前散落各组件的 rgba 字面量，保证五套主题一致跟随。
  const derived: Record<string, string> = {
    '--ws-inv-88': alpha(v['--ws-text-inverse'], 0.88),
    '--ws-inv-75': alpha(v['--ws-text-inverse'], 0.75),
    '--ws-inv-60': alpha(v['--ws-text-inverse'], 0.6),
    '--ws-inv-42': alpha(v['--ws-text-inverse'], 0.42),
    '--ws-inv-line': alpha(v['--ws-text-inverse'], 0.22),
    '--ws-inv-hover': alpha(v['--ws-text-inverse'], 0.08),
    '--ws-panel-a88': alpha(v['--ws-panel'], 0.88),
    '--ws-signal-a12': alpha(v['--ws-signal-bright'], 0.12),
    '--ws-signal-a18': alpha(v['--ws-signal-bright'], 0.18),
    '--ws-signal-a45': alpha(v['--ws-signal-bright'], 0.45),
    '--ws-alert-a16': alpha(v['--ws-alert'], 0.16),
    '--ws-alert-a40': alpha(v['--ws-alert'], 0.4),
    '--ws-alert-line': alpha(v['--ws-alert-bright'], 0.45),
    '--ws-warn-a14': alpha(v['--ws-warn'], 0.14),
    '--ws-warn-a28': alpha(v['--ws-warn'], 0.28),
    '--ws-warn-line': alpha(v['--ws-warn-bright'], 0.4),
    '--ws-ink-edge': mix(v['--ws-ink'], '#000000', 0.4),
    '--ws-inverse-press': mix(v['--ws-text-inverse'], v['--ws-ink'], 0.12),
    // 编辑器舞台：视口底比工作区深一档（画布像被照亮的 HMI 屏），点阵网格与暗角随主题同源
    '--ws-stage': mix(v['--ws-canvas'], v['--ws-ink'], 0.3),
    '--ws-stage-grid': alpha(v['--ws-text-3'], 0.4),
    '--ws-stage-grid-major': alpha(v['--ws-ink'], 0.4),
    '--ws-stage-vignette': alpha(v['--ws-ink'], 0.22),
  }
  for (const [key, value] of Object.entries(derived)) {
    root.style.setProperty(key, value)
  }

  root.dataset.wsTheme = theme.id

  // 移动端浏览器 UI 色（地址栏/状态栏）与框架色保持同步
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', v['--ws-ink'])

  try {
    localStorage.setItem(STORAGE_KEY, theme.id)
  } catch {
    /* 隐私模式下不持久化，仅当前会话生效 */
  }
}

export function initTheme(): void {
  applyTheme(getThemeId())
  // 多标签页同步：其它标签页切换主题时本页立即跟随
  window.addEventListener('storage', (e) => {
    if (e.key === STORAGE_KEY && e.newValue && THEMES.some((t) => t.id === e.newValue)) {
      applyTheme(e.newValue as ThemeId)
    }
  })
}
