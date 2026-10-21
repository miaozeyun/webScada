/**
 * 画面模板（M9 批次3，对标 BY组态「画面模板」）：面板「模板」Tab 一键新建整页。
 * 模板为静态占位布局（不含变量绑定），插入后由用户接线数据；工厂复用 demos/shared。
 */
import type { ComponentNode, Page } from '@/types/doc'
import { nd, nid, pg, txt } from '@/utils/demos/shared'

export interface PageTemplate {
  id: string
  name: string
  desc: string
  /** 面板缩略提示尺寸 */
  size: { w: number; h: number }
  build(): Page
}

/** 颜色统一工业蓝口（静态占位色，用户可改） */
const C = { primary: '#3b82f6', sub: '#94a3b8', panel: '#111c2e' }

/** 装饰 symbol 快捷（nd 工厂无 opacity 选项，构造后补设） */
function decor(id: string, symbolId: string, x: number, y: number, w: number, h: number, opacity = 0.55): ComponentNode {
  const node = nd(id, 'symbol', x, y, w, h, { name: '装饰', props: { symbolId } })
  node.opacity = opacity
  return node
}

// ---- 模板一：大屏仪表总览（1920×1080） ----

function buildDashboard(): Page {
  const comps: ComponentNode[] = [
    decor('t_frame', 'decor/frame-tech', 20, 16, 1880, 1048, 0.4),
    nd('t_title', 'title-bar', 0, 0, 1920, 88, { name: '标题栏', props: { text: '生产运行总览', align: 'center' } }),
    nd('t_clock', 'clock', 1620, 1000, 260, 64, { name: '时间' }),
    decor('t_div1', 'decor/divider-wave', 240, 120, 400, 12, 0.5),
    decor('t_div2', 'decor/divider-wave', 1280, 120, 400, 12, 0.5),
  ]
  // 顶部四联仪表
  for (let i = 0; i < 4; i++) {
    comps.push(
      decor(`t_card${i}`, 'decor/panel-card', 60 + i * 465, 160, 430, 330, 0.5),
      nd(`t_gauge${i}`, 'gauge', 110 + i * 465, 210, 330, 270, {
        name: `仪表${i + 1}`,
        props: { title: `测点 ${i + 1}`, unit: '', min: 0, max: 100, precision: 1 },
      }),
    )
  }
  // 下部图表区
  comps.push(
    nd('t_line', 'line-chart', 60, 540, 900, 480, { name: '趋势图', props: { title: '实时趋势', unit: '' } }),
    nd('t_pie', 'pie-chart', 1010, 540, 420, 480, { name: '占比', props: { title: '工况占比' } }),
    nd('t_tank', 'tank', 1480, 560, 180, 440, { name: '水池', props: { percent: 50, wave: true } }),
    nd('t_state', 'state-text', 1700, 560, 180, 48, {
      name: '状态',
      props: { defaultText: '--', states: '[{"value":0,"text":"停止","color":"#909399"},{"value":1,"text":"运行","color":"#67c23a"}]' },
    }),
  )
  return pg(nid('tpl'), '大屏总览', 1920, 1080, comps)
}

// ---- 模板二：单线图框架（1920×1080） ----

function buildSlDraft(): Page {
  const comps: ComponentNode[] = [
    txt('t_sl_t', 60, 40, 400, 40, '10kV 进线', 24, C.primary),
    // 母线
    nd('t_bus', 'rect', 300, 200, 1320, 14, { name: '母线', style: { fill: C.primary } }),
    txt('t_bus_l', 300, 160, 200, 28, '10kV 母线', 14, C.sub),
  ]
  // 三条馈线
  for (let i = 0; i < 3; i++) {
    const x = 480 + i * 420
    const tag = `t_f${i}`
    comps.push(
      txt(`${tag}_l`, x - 60, 250, 280, 26, `馈线 ${i + 1}`, 13, C.sub),
      nd(`${tag}_qf`, 'breaker', x, 290, 56, 74, { name: `断路器${i + 1}` }),
      nd(`${tag}_qs`, 'isolator', x, 374, 56, 74, { name: `隔离${i + 1}` }),
      nd(`${tag}_ct`, 'ct', x - 8, 458, 72, 92, { name: `CT${i + 1}` }),
      nd(`${tag}_pt`, 'pt', x + 90, 458, 72, 100, { name: `PT${i + 1}` }),
      nd(`${tag}_gnd`, 'ground', x + 130, 570, 50, 70, { name: `接地${i + 1}` }),
      nd(`${tag}_tr`, 'transformer', x, 570, 70, 110, { name: `变压器${i + 1}` }),
      nd(`${tag}_m`, 'motor', x, 700, 90, 90, { name: `负荷${i + 1}` }),
      nd(`${tag}_v`, 'var-display', x + 120, 600, 220, 60, {
        name: `遥测${i + 1}`,
        props: { prefix: 'I', unit: 'A', precision: 1 },
      }),
    )
  }
  return pg(nid('tpl'), '单线图框架', 1920, 1080, comps)
}

// ---- 模板三：双栏控制面板（1280×800） ----

function buildTwoCol(): Page {
  const comps: ComponentNode[] = [
    nd('t2_title', 'title-bar', 0, 0, 1280, 64, { name: '标题栏', props: { text: '设备控制', align: 'left' } }),
    // 左栏：状态
    txt('t2_ls', 40, 96, 200, 30, '运行状态', 16, C.primary),
    decor('t2_card1', 'decor/panel-card', 24, 132, 360, 620, 0.5),
  ]
  for (let i = 0; i < 4; i++) {
    const y = 160 + i * 120
    comps.push(
      nd(`t2_st${i}`, 'status-light', 60, y, 52, 52, { name: `状态灯${i + 1}` }),
      nd(`t2_sx${i}`, 'state-text', 130, y + 8, 150, 40, {
        name: `状态${i + 1}`,
        props: { defaultText: '--', states: '[{"value":0,"text":"停止","color":"#909399"},{"value":1,"text":"运行","color":"#67c23a"}]' },
      }),
      nd(`t2_sw${i}`, 'switch', 290, y + 8, 76, 36, { name: `开关${i + 1}`, props: { variableId: '', onValue: 1, offValue: 0, confirm: false, label: '' } }),
    )
  }
  // 右栏：趋势与历史
  comps.push(
    txt('t2_rs', 420, 96, 200, 30, '过程趋势', 16, C.primary),
    nd('t2_trend', 'trend-chart', 420, 132, 830, 320, { name: '趋势图', props: { title: '', unit: '' } }),
    nd('t2_hist', 'history-chart', 420, 476, 830, 276, {
      name: '历史图',
      props: { variableId: '', title: '历史趋势', unit: '', rangeMs: 3600000 },
    }),
  )
  return pg(nid('tpl'), '双栏控制面板', 1280, 800, comps)
}

// ---- 模板四：移动端竖屏（375×812） ----

function buildMobile(): Page {
  const comps: ComponentNode[] = [
    nd('t3_title', 'title-bar', 0, 0, 375, 56, { name: '标题栏', props: { text: '移动监控', align: 'center' } }),
    nd('t3_clock', 'clock', 16, 68, 343, 40, { name: '时间', props: { showDate: false, showSeconds: true, layout: 'horizontal' } }),
    decor('t3_card', 'decor/panel-card', 12, 118, 351, 180, 0.5),
    nd('t3_v1', 'var-display', 28, 136, 150, 60, { name: '温度', props: { prefix: '温度', unit: '℃', precision: 1 } }),
    nd('t3_v2', 'var-display', 196, 136, 150, 60, { name: '压力', props: { prefix: '压力', unit: 'MPa', precision: 2 } }),
    nd('t3_prog', 'progress', 28, 214, 318, 40, { name: '液位', props: { percent: 50 } }),
    txt('t3_ctl', 16, 316, 200, 28, '远程控制', 15, C.primary),
    nd('t3_sw1', 'switch', 24, 352, 150, 44, { name: '开关1', props: { variableId: '', onValue: 1, offValue: 0, confirm: true, label: '1#泵' } }),
    nd('t3_sw2', 'switch', 200, 352, 150, 44, { name: '开关2', props: { variableId: '', onValue: 1, offValue: 0, confirm: true, label: '2#泵' } }),
    nd('t3_ms', 'multi-switch', 24, 412, 326, 44, {
      name: '多档',
      props: { variableId: '', levels: '[{"value":0,"label":"停止"},{"value":1,"label":"低速"},{"value":2,"label":"高速"}]' },
    }),
    txt('t3_tr', 16, 480, 200, 28, '实时趋势', 15, C.primary),
    nd('t3_trend', 'trend-chart', 12, 512, 351, 286, { name: '迷你趋势', props: { title: '', unit: '' } }),
  ]
  return pg(nid('tpl'), '移动端竖屏', 375, 812, comps)
}

export const PAGE_TEMPLATES: PageTemplate[] = [
  {
    id: 'dashboard',
    name: '大屏总览',
    desc: '1920×1080 · 标题栏 + 四联仪表 + 趋势/占比/水池',
    size: { w: 1920, h: 1080 },
    build: buildDashboard,
  },
  {
    id: 'sl-draft',
    name: '单线图框架',
    desc: '1920×1080 · 母线 + 三回馈线（断路器/隔离/CT/PT/变压器）',
    size: { w: 1920, h: 1080 },
    build: buildSlDraft,
  },
  {
    id: 'two-col',
    name: '双栏控制面板',
    desc: '1280×800 · 左状态控制 / 右趋势历史',
    size: { w: 1280, h: 800 },
    build: buildTwoCol,
  },
  {
    id: 'mobile-portrait',
    name: '移动端竖屏',
    desc: '375×812 · 状态卡 + 开关组 + 迷你趋势',
    size: { w: 375, h: 812 },
    build: buildMobile,
  },
]
