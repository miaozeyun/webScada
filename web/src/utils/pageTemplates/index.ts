/**
 * 画面模板（M9 批次3，对标业界主流组态「画面模板」）：面板「模板」Tab 一键新建整页。
 * 模板为静态占位布局（不含变量绑定），插入后由用户接线数据；工厂复用 demos/shared。
 *
 * 视觉口径（2026-10 重做）：
 * - 深色 HMI 底 + 卡片分组 + 信号青强调色，与行业 demo 同一套语言；
 * - 所有文字/数值/状态组件显式给 style.color——画布底色是深色，缺省继承色为黑会「看不见」；
 * - 不使用需绑定的组件（如历史曲线，无变量时只剩一行占位提示，破坏画面完整度）；
 * - z 序按数组书写顺序重排：循环构造的节点块先于字面量求值，nd 的自增 z 会与数组序脱节。
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

/** 模板统一配色（静态占位色，用户可改） */
const P = {
  bg: '#0b1220',
  card: '#111c2e',
  cardAlt: '#0e1727',
  line: 'rgba(148, 163, 184, 0.14)',
  text: '#e2e8f0',
  sub: '#94a3b8',
  muted: '#64748b',
  accent: '#38bdf8',
  ok: '#34d399',
  warn: '#f59e0b',
}

/** 卡片底：矩形 + 描边 + 圆角 */
function card(id: string, x: number, y: number, w: number, h: number, fill = P.card, radius = 10): ComponentNode {
  return nd(id, 'rect', x, y, w, h, {
    name: '面板',
    style: { fill, stroke: P.line, strokeWidth: 1, borderRadius: radius },
  })
}

/** 区块小标题：信号色竖条 + 文本 */
function section(id: string, x: number, y: number, text: string, w = 360): ComponentNode[] {
  return [
    nd(`${id}_bar`, 'rect', x, y + 4, 3, 16, { name: '标题条', style: { fill: P.accent, borderRadius: 2 } }),
    txt(`${id}_t`, x + 11, y, w, 24, text, 15, P.sub),
  ]
}

/** 竖向/横向连线（单线图用） */
function wire(id: string, x: number, y: number, len: number, horizontal = false): ComponentNode {
  return horizontal
    ? nd(id, 'rect', x, y, len, 2, { name: '连线', style: { fill: P.line } })
    : nd(id, 'rect', x, y, 2, len, { name: '连线', style: { fill: P.line } })
}

/** 多行文本：text 组件默认 ellipsis=true（nowrap），换行文案须显式关掉 */
function lines(id: string, x: number, y: number, w: number, h: number, text: string, size: number, color: string): ComponentNode {
  return nd(id, 'text', x, y, w, h, {
    name: text.split('\n')[0].slice(0, 12),
    props: { text, ellipsis: false },
    style: { fontSize: size, color },
  })
}

/** 状态行：指示灯 + 文本（设备工况/机组列表复用） */
function statusRow(id: string, x: number, y: number, text: string, color: string): ComponentNode[] {
  return [
    nd(`${id}_led`, 'status-light', x, y + 2, 18, 18, { name: '状态灯', style: { color } }),
    txt(`${id}_t`, x + 28, y, 320, 24, text, 13, color),
  ]
}

/** 统一收尾：重排 z（数组序即层级序）并落页 */
function finish(components: ComponentNode[], name: string, w: number, h: number): Page {
  components.forEach((c, i) => {
    c.z = i + 1
  })
  return pg(nid('tpl'), name, w, h, components, { bg: P.bg })
}

// ---- 模板一：大屏仪表总览（1920×1080） ----

function buildDashboard(): Page {
  const comps: ComponentNode[] = [
    nd('d_title', 'title-bar', 0, 0, 1920, 88, {
      name: '标题栏',
      props: { text: '生产运行总览', align: 'center' },
      style: { color: P.accent },
    }),
    nd('d_clock', 'clock', 1580, 20, 300, 50, {
      name: '时间',
      props: { showDate: true, showSeconds: true, layout: 'horizontal' },
      style: { color: P.sub },
    }),
  ]

  // 顶部 KPI 条：四联卡片（标签含单位，数值单独一行大字，避免单位对不齐）
  const kpis: [string, string][] = [
    ['实时产量 t/h', '1,286.4'],
    ['运行设备 台', '42 / 48'],
    ['综合能耗 kWh/t', '0.82'],
    ['连续运行 h', '18.4'],
  ]
  kpis.forEach(([label, value], i) => {
    const x = 60 + i * 455
    comps.push(
      card(`d_kpi${i}`, x, 108, 435, 112),
      txt(`d_kpi${i}_l`, x + 22, 126, 300, 22, label, 13, P.sub),
      txt(`d_kpi${i}_v`, x + 22, 152, 380, 52, value, 34, P.text),
    )
  })

  // 中部：主趋势
  comps.push(
    card('d_main', 60, 248, 1210, 500),
    ...section('d_main', 84, 268, '主工艺实时趋势'),
    nd('d_trend', 'trend-chart', 84, 306, 1162, 424, {
      name: '主趋势',
      props: { title: '', unit: '℃' },
    }),
  )

  // 左下：机组负荷率
  comps.push(card('d_load', 60, 768, 590, 252), ...section('d_load', 84, 788, '机组负荷率'))
  const loads: [string, number][] = [
    ['1# 循环泵', 82],
    ['2# 循环泵', 64],
    ['3# 循环泵', 47],
  ]
  loads.forEach(([label, pct], i) => {
    const y = 836 + i * 56
    comps.push(
      txt(`d_load${i}_l`, 84, y, 130, 24, label, 13, P.sub),
      nd(`d_load${i}_p`, 'progress', 214, y, 412, 24, {
        name: `${label}负荷`,
        props: { percent: pct, precision: 0 },
      }),
    )
  })

  // 中下：能耗构成
  comps.push(
    card('d_pie', 670, 768, 600, 252),
    ...section('d_pie', 694, 788, '能耗构成'),
    nd('d_pie_c', 'pie-chart', 694, 820, 552, 186, { name: '能耗构成', props: { title: '' } }),
  )

  // 右列：设备工况
  comps.push(card('d_dev', 1296, 248, 564, 772), ...section('d_dev', 1320, 268, '设备工况'))
  const gauges: [string, string, number, number, number][] = [
    ['出口温度', '℃', 0, 200, 1],
    ['系统压力', 'MPa', 0, 1.6, 2],
    ['瞬时流量', 'm³/h', 0, 500, 0],
    ['储罐液位', '%', 0, 100, 0],
  ]
  gauges.forEach(([title, unit, min, max, precision], i) => {
    comps.push(
      nd(`d_g${i}`, 'gauge', 1320 + (i % 2) * 280, 310 + Math.floor(i / 2) * 238, 250, 220, {
        name: title,
        props: { title, unit, min, max, precision, textColor: '#cbd5e1' },
      }),
    )
  })
  const states: [string, string][] = [
    ['1# 循环泵 · 运行', P.ok],
    ['2# 循环泵 · 待机', P.sub],
    ['3# 循环泵 · 停止', P.muted],
  ]
  states.forEach(([text, color], i) => {
    comps.push(...statusRow(`d_st${i}`, 1320, 800 + i * 56, text, color))
  })

  return finish(comps, '大屏总览', 1920, 1080)
}

// ---- 模板二：单线图框架（1920×1080） ----

function buildSlDraft(): Page {
  const comps: ComponentNode[] = [
    nd('s_title', 'title-bar', 0, 0, 1920, 80, {
      name: '标题栏',
      props: { text: '10kV 配电系统 · 单线图', align: 'center' },
      style: { color: P.accent },
    }),
    card('s_panel', 60, 104, 1800, 940),
    ...section('s_sec', 84, 124, '一次系统接线（示意）'),
  ]

  // 进线回路（对准母线起点 300）
  comps.push(
    txt('s_in_l', 240, 190, 220, 24, '10kV 进线', 14, P.sub),
    nd('s_in_qf', 'breaker', 272, 224, 56, 74, { name: '进线断路器', style: { color: P.sub } }),
    wire('s_in_w1', 299, 298, 20),
    nd('s_in_qs', 'isolator', 272, 318, 56, 74, { name: '进线隔离', style: { color: P.sub } }),
    wire('s_in_w2', 299, 392, 32),
    nd('s_bus', 'rect', 300, 420, 1080, 8, { name: '10kV 母线', style: { fill: P.accent, borderRadius: 4 } }),
    txt('s_bus_l', 300, 388, 260, 24, '10kV 母线 · Ⅰ 段', 13, P.sub),
  )

  // 三回馈线：断路器 → 隔离 → CT/PT → 变压器（接地） → 负荷 → 遥测
  const tags = ['1# 变压器回路', '2# 变压器回路', '3# 变压器回路']
  for (let i = 0; i < 3; i++) {
    const x = 440 + i * 340
    const t = `s_f${i}`
    const n = i + 1
    comps.push(
      txt(`${t}_l`, x - 30, 452, 300, 24, `馈线 ${n} · ${tags[i]}`, 13, P.sub),
      wire(`${t}_r0`, x + 27, 428, 44),
      nd(`${t}_qf`, 'breaker', x, 472, 56, 74, { name: `断路器${n}`, style: { color: P.sub } }),
      txt(`${t}_qf_l`, x + 66, 490, 80, 22, `QF${n}`, 12, P.muted),
      wire(`${t}_w1`, x + 27, 546, 14),
      nd(`${t}_qs`, 'isolator', x, 560, 56, 74, { name: `隔离${n}`, style: { color: P.sub } }),
      txt(`${t}_qs_l`, x + 66, 578, 80, 22, `QS${n}`, 12, P.muted),
      wire(`${t}_w2`, x + 27, 634, 16),
      nd(`${t}_ct`, 'ct', x - 10, 650, 72, 92, { name: `CT${n}`, style: { color: P.sub } }),
      txt(`${t}_ct_l`, x - 6, 744, 70, 20, `CT${n}`, 12, P.muted),
      nd(`${t}_pt`, 'pt', x + 70, 650, 72, 100, { name: `PT${n}`, style: { color: P.sub } }),
      txt(`${t}_pt_l`, x + 76, 752, 70, 20, `PT${n}`, 12, P.muted),
      wire(`${t}_w3`, x + 27, 750, 12),
      nd(`${t}_tr`, 'transformer', x, 762, 70, 110, { name: `变压器${n}`, style: { color: P.sub } }),
      txt(`${t}_tr_l`, x + 78, 800, 70, 22, `T${n}`, 12, P.muted),
      nd(`${t}_gnd`, 'ground', x + 118, 766, 44, 62, { name: `接地${n}`, style: { color: P.muted } }),
      wire(`${t}_w4`, x + 33, 872, 18),
      nd(`${t}_m`, 'motor', x - 14, 890, 90, 90, { name: `负荷${n}`, style: { color: P.sub } }),
      txt(`${t}_m_l`, x + 82, 922, 70, 22, `M${n}`, 12, P.muted),
      nd(`${t}_v`, 'var-display', x - 60, 992, 240, 40, {
        name: `遥测${n}`,
        props: { prefix: 'I', unit: 'A', precision: 1, value: 300 + n * 42 },
        style: { color: P.text },
      }),
    )
  }

  // 右侧：全站遥测 + 图例（填充右侧留白，也是实际接线时最先绑定的量）
  comps.push(
    card('s_meas', 1400, 180, 420, 780),
    ...section('s_meas', 1424, 200, '全站遥测', 240),
  )
  const readings: [string, string, string, number][] = [
    ['母线电压', 'kV', '10.24', 2],
    ['全站电流', 'A', '428.6', 1],
    ['有功功率', 'MW', '4.26', 2],
  ]
  readings.forEach(([prefix, unit, value, precision], i) => {
    comps.push(
      nd(`s_m${i}`, 'var-display', 1424, 246 + i * 88, 372, 72, {
        name: prefix,
        props: { prefix, unit, precision, value },
        style: { color: P.text },
      }),
    )
  })
  comps.push(
    txt('s_leg_t', 1424, 540, 240, 22, '图例', 13, P.sub),
    lines(
      's_leg',
      1424,
      574,
      372,
      160,
      'QF  断路器（合/分）\nQS  隔离开关\nCT  电流互感器\nPT  电压互感器\nT    配电变压器\nM    电动机负荷',
      12,
      P.muted,
    ),
    lines('s_note', 96, 992, 320, 44, '拖入变量后绑定\n开关状态与遥测', 12, P.muted),
  )

  return finish(comps, '单线图框架', 1920, 1080)
}

// ---- 模板三：双栏控制面板（1280×800） ----

function buildTwoCol(): Page {
  const comps: ComponentNode[] = [
    nd('c_title', 'title-bar', 0, 0, 1280, 64, {
      name: '标题栏',
      props: { text: '设备控制 · 循环水站', align: 'left' },
      style: { color: P.accent },
    }),
    nd('c_clock', 'clock', 940, 14, 320, 36, {
      name: '时间',
      props: { showDate: false, showSeconds: true, layout: 'horizontal' },
      style: { color: P.sub },
    }),
    card('c_left', 24, 84, 392, 692),
    ...section('c_left', 44, 102, '运行状态', 240),
  ]

  const devices: [string, string, string, string][] = [
    ['1# 循环泵', '变频 · 45 kW', '运行', P.ok],
    ['2# 循环泵', '变频 · 45 kW', '运行', P.ok],
    ['3# 循环泵', '工频 · 55 kW', '待机', P.warn],
    ['冷却塔风机', '变频 · 22 kW', '停止', P.muted],
  ]
  devices.forEach(([name, sub, state, color], i) => {
    const y = 150 + i * 120
    comps.push(
      card(`c_row${i}`, 44, y, 352, 104, P.cardAlt, 8),
      nd(`c_row${i}_led`, 'status-light', 64, y + 32, 40, 40, { name: `${name}状态`, style: { color } }),
      txt(`c_row${i}_n`, 120, y + 16, 180, 24, name, 15, P.text),
      txt(`c_row${i}_s`, 120, y + 44, 200, 22, sub, 12, P.muted),
      nd(`c_row${i}_st`, 'state-text', 120, y + 68, 110, 24, {
        name: `${name}状态文本`,
        props: {
          // 占位文案与状态表同口径：未绑定即显示「运行」，绑定后按 value 映射
          defaultText: state,
          states: `[{"value":0,"text":"停止","color":"${P.muted}","background":"rgba(100,116,139,0.16)"},{"value":1,"text":"运行","color":"${P.ok}","background":"rgba(52,211,153,0.14)"},{"value":2,"text":"待机","color":"${P.warn}","background":"rgba(245,158,11,0.14)"}]`,
        },
        style: { color, fill: `${color}22`, borderRadius: 4 },
      }),
      nd(`c_row${i}_sw`, 'switch', 268, y + 34, 108, 40, {
        name: `${name}开关`,
        props: { variableId: '', onValue: 1, offValue: 0, confirm: true, label: '' },
        style: { color: P.text },
      }),
    )
  })
  comps.push(lines('c_note', 44, 660, 352, 44, '开关为反控组件：绑定\n可写变量后运行态下发', 12, P.muted))

  // 右栏上：过程趋势
  comps.push(
    card('c_trend', 432, 84, 824, 332),
    ...section('c_trend', 452, 102, '过程趋势', 240),
    nd('c_trend_c', 'trend-chart', 452, 138, 784, 262, { name: '过程趋势', props: { title: '', unit: '℃' } }),
  )

  // 右栏下：回路参数
  comps.push(card('c_kpi', 432, 432, 824, 344), ...section('c_kpi', 452, 450, '回路参数', 240))
  const readings: [string, string, number, number][] = [
    ['出口温度', '℃', 1, 32.6],
    ['进口压力', 'MPa', 2, 0.42],
    ['瞬时流量', 'm³/h', 1, 386.4],
    ['储罐液位', '%', 0, 64],
  ]
  readings.forEach(([prefix, unit, precision, value], i) => {
    comps.push(
      nd(`c_v${i}`, 'var-display', 452 + (i % 2) * 404, 486 + Math.floor(i / 2) * 90, 380, 72, {
        name: prefix,
        props: { prefix, unit, precision, value },
        style: { color: P.text },
      }),
    )
  })
  const progs: [string, number][] = [
    ['1# 泵负荷', 78],
    ['2# 泵负荷', 46],
  ]
  progs.forEach(([label, pct], i) => {
    const x = 452 + i * 404
    comps.push(
      txt(`c_p${i}_l`, x, 660, 200, 22, label, 12, P.muted),
      nd(`c_p${i}`, 'progress', x, 684, 380, 26, { name: label, props: { percent: pct, precision: 0 } }),
    )
  })

  return finish(comps, '双栏控制面板', 1280, 800)
}

// ---- 模板四：移动端竖屏（375×812） ----

function buildMobile(): Page {
  const comps: ComponentNode[] = [
    card('m_head', 0, 0, 375, 72, P.cardAlt, 0),
    txt('m_title', 16, 12, 343, 28, '循环水站 · 移动监控', 20, P.text),
    nd('m_clock', 'clock', 16, 44, 343, 22, {
      name: '时间',
      props: { showDate: false, showSeconds: true, layout: 'horizontal' },
      style: { color: P.sub },
    }),
    card('m_kpi', 12, 88, 351, 150),
    nd('m_t', 'var-display', 28, 104, 150, 54, {
      name: '温度',
      props: { prefix: '温度', unit: '℃', precision: 1, value: 32.6 },
      style: { color: P.text },
    }),
    nd('m_p', 'var-display', 196, 104, 150, 54, {
      name: '压力',
      props: { prefix: '压力', unit: 'MPa', precision: 2, value: 0.42 },
      style: { color: P.text },
    }),
    txt('m_lv_l', 28, 172, 150, 20, '储罐液位', 12, P.muted),
    nd('m_lv', 'progress', 28, 196, 318, 24, { name: '储罐液位', props: { percent: 64, precision: 0 } }),
    ...section('m_ctl', 16, 254, '远程控制', 200),
    card('m_ctl_c', 12, 284, 351, 186),
    nd('m_sw1', 'switch', 28, 300, 155, 44, {
      name: '1# 泵开关',
      props: { variableId: '', onValue: 1, offValue: 0, confirm: true, label: '1# 泵' },
      style: { color: P.text },
    }),
    nd('m_sw2', 'switch', 192, 300, 155, 44, {
      name: '2# 泵开关',
      props: { variableId: '', onValue: 1, offValue: 0, confirm: true, label: '2# 泵' },
      style: { color: P.text },
    }),
    nd('m_ms', 'multi-switch', 28, 356, 319, 44, {
      name: '机组档位',
      props: {
        variableId: '',
        levels: '[{"value":0,"label":"停止"},{"value":1,"label":"低速"},{"value":2,"label":"高速"}]',
      },
      style: { color: P.text },
    }),
    nd('m_led', 'status-light', 28, 418, 20, 20, { name: '通讯状态', style: { color: P.ok } }),
    txt('m_led_t', 56, 416, 280, 24, '机组运行 · 通讯正常', 12, P.ok),
    ...section('m_trend_s', 16, 486, '实时趋势', 200),
    card('m_trend_c', 12, 516, 351, 272),
    nd('m_trend', 'trend-chart', 24, 528, 327, 248, { name: '实时趋势', props: { title: '', unit: '℃' } }),
  ]

  return finish(comps, '移动端竖屏', 375, 812)
}

export const PAGE_TEMPLATES: PageTemplate[] = [
  {
    id: 'dashboard',
    name: '大屏总览',
    desc: '1920×1080 · KPI 条 + 主趋势 + 负荷率/能耗 + 四联仪表与设备工况',
    size: { w: 1920, h: 1080 },
    build: buildDashboard,
  },
  {
    id: 'sl-draft',
    name: '单线图框架',
    desc: '1920×1080 · 10kV 进线 + 母线 + 三回馈线（断路器/隔离/CT/PT/变压器/负荷）',
    size: { w: 1920, h: 1080 },
    build: buildSlDraft,
  },
  {
    id: 'two-col',
    name: '双栏控制面板',
    desc: '1280×800 · 左设备状态与反控开关 / 右趋势与回路参数',
    size: { w: 1280, h: 800 },
    build: buildTwoCol,
  },
  {
    id: 'mobile-portrait',
    name: '移动端竖屏',
    desc: '375×812 · 双读数卡 + 反控开关组 + 迷你趋势',
    size: { w: 375, h: 812 },
    build: buildMobile,
  },
]
