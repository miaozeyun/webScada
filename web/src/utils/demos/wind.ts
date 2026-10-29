/**
 * 演示案例十：海上风电集控（行业 demo · 深海青主题，2026-10-29）。
 *
 * 视觉主角：6 台风机叶轮按风速实时变速旋转，功率按风速立方律生成；
 * 左侧单机卡、中央数字孪生阵列、右侧并网/联锁三层信息逐级下钻。
 * 数据全部由 mock 源 + 虚拟变量表达式产生：风速驱动功率 → 容量系数 → 全场出力，
 * 叶轮转速、桨距角、机组负载率随动，非静态贴图。
 */
import type { ComponentNode } from '@/types/doc'
import { alm, bd, demoDoc, mvar, nd, pg, rangeMap, txt, vvar } from './shared'

const ACCENT = '#5eead4'
const ACCENT_2 = '#22d3ee'
const ACCENT_DIM = '#7dd3c7'
const CARD_FILL = 'linear-gradient(160deg, rgba(8,36,46,0.94) 0%, rgba(4,18,26,0.9) 100%)'
const PANEL_FILL = 'linear-gradient(165deg, rgba(6,26,34,0.9) 0%, rgba(3,14,20,0.86) 100%)'

export function buildWindDoc(): ReturnType<typeof demoDoc> {
  // ---- 变量：风速为唯一主驱动，全部有功/负载/转速由表达式级联 ----
  // 慢趋势（20min 周期，供近 1h 历史曲线）+ 阵风快扰动（合成值驱动实时功率/转速）
  const spd = mvar('w_spd', 'w_spd', '轮毂高度风速', { kind: 'sine', min: 8, max: 13, periodMs: 1200000, unit: 'm/s', precision: 1 })
  const gust = mvar('w_gust', 'w_gust', '阵风扰动', { kind: 'sine', min: -1.1, max: 1.1, periodMs: 7000, unit: 'm/s', precision: 1 })
  const dir = mvar('w_dir', 'w_dir', '风向', { kind: 'ramp', min: 0, max: 360, periodMs: 300000, unit: '°', precision: 0 })
  const grid = mvar('w_grid', 'w_grid', '并网频率', { kind: 'sine', min: 49.9, max: 50.1, periodMs: 14000, unit: 'Hz', precision: 3 })
  const volt = mvar('w_volt', 'w_volt', '35kV 母线电压', { kind: 'sine', min: 34.6, max: 35.4, periodMs: 60000, unit: 'kV', precision: 2 })
  const oil = mvar('w_oil', 'w_oil', '齿轮箱油温', { kind: 'sine', min: 54, max: 73.5, periodMs: 118000, unit: '℃', precision: 1 })
  const vib = mvar('w_vib', 'w_vib', '主轴振动', { kind: 'sine', min: 1.1, max: 5.1, periodMs: 41000, unit: 'mm/s', precision: 2 })

  const vars = [spd, gust, dir, grid, volt, oil, vib]

  // 单机功率：额定 6.5MW，风速 12m/s 以下按立方律，以上限功率（每台带相位噪声与效率因子）
  const factors = [0.97, 1.02, 0.99, 1.04, 0.96, 1.01]
  // _tick 为 Unix 秒（服务端每秒推进）：/7 对应约 44s 周期，噪声肉眼可见但不抖动
  const phases = [7, 8.5, 6.2, 9.4, 7.8, 8.1]
  const tPower: string[] = []
  const tLoad: string[] = []
  for (let i = 1; i <= 6; i++) {
    tPower.push(`v_t${i}`)
    tLoad.push(`v_l${i}`)
    vars.push(vvar(`v_t${i}`, `v_t${i}`, `WTG-0${i} 有功功率`,
      `round(min(6.5, 6.5 * min(1, pow(w_spd_eff / 12, 3)) * ${factors[i - 1]} + sin(_tick / ${phases[i - 1]} + ${i}) * 0.08), 2)`,
      { unit: 'MW', precision: 2 }))
    vars.push(vvar(`v_l${i}`, `v_l${i}`, `WTG-0${i} 负载率`,
      `round(max(0, min(100, v_t${i} / 6.5 * 100)), 0)`, { unit: '%', precision: 0 }))
  }

  vars.push(
    vvar('w_spd_eff', 'w_spd_eff', '合成轮毂风速', 'round(max(0, w_spd + w_gust), 1)', { unit: 'm/s', precision: 1 }),
    vvar('v_power', 'v_power', '全场有功功率', `round(${tPower.map((v) => `v_t${v.slice(3)}`).join(' + ')}, 2)`, { unit: 'MW', precision: 2 }),
    vvar('v_cap', 'v_cap', '出力负载率', 'round(v_power / 39 * 100, 1)', { unit: '%', precision: 1 }),
    // 今日发电量按当日秒数线性累计（0-25MWh/日），零点归零，避免 _tick 绝对值造成天文数字
    vvar('v_energy', 'v_energy', '今日发电量', 'round(486.3 + (_tick % 86400) / 3456, 1)', { unit: 'MWh', precision: 1 }),
    vvar('v_pitch', 'v_pitch', '桨距角', 'round(max(0, 6.5 - (w_spd_eff - 9) * 1.9), 1)', { unit: '°', precision: 1 }),
    vvar('v_rpm', 'v_rpm', '叶轮转速', 'round(w_spd_eff * 0.92, 1)', { unit: 'rpm', precision: 1 }),
    vvar('v_rp', 'v_rp', '叶轮旋转周期', 'round(2600 - w_spd_eff * 120, 0)', { unit: 'ms', precision: 0 }),
    vvar('v_flow', 'v_flow', '汇集流速', 'round(w_spd_eff * 8, 0)', { unit: 'px/s', precision: 0 }),
    vvar('v_pf', 'v_pf', '功率因数', 'round(0.982 + cos(_tick / 11) * 0.012, 3)', { precision: 3 }),
    vvar('v_q', 'v_q', '无功功率', 'round(v_power * 0.12, 2)', { unit: 'Mvar', precision: 2 }),
    vvar('v_avail', 'v_avail', '可利用率', 'round(98.4 + sin(_tick / 17) * 0.9, 1)', { unit: '%', precision: 1 }),
    // 展示用副本（2026-10-29）：报警态会整块覆盖组件底色，仪表/KPI 改绑副本值，
    // 告警仍由同名状态灯（绑原变量）呈现，避免大表盘被实色报警底糊住。
    vvar('v_spd_v', 'v_spd_v', '风速读数', 'round(w_spd_eff, 1)', { unit: 'm/s', precision: 1 }),
    vvar('v_oil_v', 'v_oil_v', '油温读数', 'round(w_oil, 1)', { unit: '℃', precision: 1 }),
    vvar('v_vib_v', 'v_vib_v', '振动读数', 'round(w_vib, 2)', { unit: 'mm/s', precision: 2 }),
    vvar('v_grid_v', 'v_grid_v', '频率读数', 'round(w_grid, 3)', { unit: 'Hz', precision: 3 }),
  )

  // ---- 顶部 KPI ----
  const kpi = (x: number, label: string, unit: string, varId: string, decimals: number) => [
    nd(`c_kpi${x}`, 'rect', x, 104, 430, 100, {
      name: `KPI·${label}`,
      style: { fill: CARD_FILL, stroke: 'rgba(94,234,212,0.18)', strokeWidth: 1, borderRadius: 10 },
    }),
    txt(`t_kpi${x}`, x + 18, 114, 260, 20, label, 12, ACCENT_DIM),
    nd(`c_fc${x}`, 'flip-counter', x + 16, 136, 398, 54, {
      name: label, props: { value: '0', unit, decimals, bg: 'transparent', border: 'transparent', color: ACCENT },
      bindings: [bd(varId, 'props.value')],
    }),
    nd(`c_kl${x}`, 'line', x + 18, 198, 120, 2, { name: `${label}强调线`, style: { fill: ACCENT } }),
  ]

  // ---- 左侧：6 台机组卡 ----
  const turbineColor = rangeMap(
    { max: 2, value: '#3f5b63' },
    { min: 2, max: 4, value: '#0e7490' },
    { min: 4, max: 5.5, value: ACCENT_2 },
    { min: 5.5, value: ACCENT },
  )
  const cards: ComponentNode[] = []
  for (let i = 0; i < 6; i++) {
    const n = i + 1
    const cx = 60 + (i % 2) * 300
    const cy = 272 + Math.floor(i / 2) * 254
    cards.push(
      nd(`c_tc${n}`, 'rect', cx, cy, 280, 236, {
        name: `WTG-0${n} 机组卡`,
        style: { fill: CARD_FILL, stroke: 'rgba(94,234,212,0.14)', strokeWidth: 1, borderRadius: 10 },
      }),
      txt(`t_tn${n}`, cx + 14, cy + 10, 150, 20, `WTG-0${n} · 直驱 6.5MW`, 12, '#d7f9f2'),
      nd(`c_ts${n}`, 'status-light', cx + 246, cy + 10, 20, 20, {
        name: `WTG-0${n} 通讯`, style: { color: '#34d399' }, tooltip: `WTG-0${n} 通讯正常·偏航自动`,
      }),
      nd(`c_tr${n}`, 'symbol', cx + 14, cy + 40, 76, 76, {
        name: `WTG-0${n} 叶轮`, props: { symbolId: 'energy/wind-rotor' },
        anim: { rotate: { enabled: true, clockwise: true, periodMs: 2200 } },
        style: { color: ACCENT_2 },
        bindings: [
          bd(`v_t${n}`, 'style.color', 'color', turbineColor),
          bd('v_rp', 'anim.rotatePeriod'),
        ],
        tooltip: `WTG-0${n}\n功率 {v_t${n}} MW · 油温 {w_oil} ℃\n叶轮转速 {v_rpm} rpm`,
      }),
      nd(`c_tp${n}`, 'var-display', cx + 100, cy + 40, 166, 38, {
        name: `WTG-0${n} 功率`, props: { prefix: '', unit: 'MW', precision: 2 },
        style: { color: '#e6fffb', fontSize: 22 },
        bindings: [bd(`v_t${n}`, 'props.value')],
      }),
      nd(`c_tw${n}`, 'var-display', cx + 100, cy + 84, 166, 26, {
        name: `WTG-0${n} 风速`, props: { prefix: '风速', unit: 'm/s', precision: 1 },
        style: { color: ACCENT_DIM, fontSize: 13 },
        bindings: [bd('v_spd_v', 'props.value')],
      }),
      nd(`c_tl${n}`, 'progress', cx + 14, cy + 128, 252, 20, {
        name: `WTG-0${n} 负载率`, props: { percent: 0, precision: 0, color: `linear-gradient(90deg, #0e7490, ${ACCENT})` },
        bindings: [bd(`v_l${n}`, 'props.percent')],
      }),
      txt(`t_tr${n}`, cx + 14, cy + 160, 252, 20, '额定 6.5 MW · 轮毂 110m · 叶轮 178m', 10, '#5f8b8a'),
      nd(`c_tv${n}`, 'var-display', cx + 14, cy + 190, 252, 26, {
        name: `WTG-0${n} 转速`, props: { prefix: '叶轮转速', unit: 'rpm', precision: 1 },
        style: { color: ACCENT_2, fontSize: 13 },
        bindings: [bd('v_rpm', 'props.value')],
      }),
    )
  }

  // ---- 中央：数字孪生阵列（叶轮 + 塔筒 + 汇流） ----
  const dt: ComponentNode[] = []
  const dtX = [760, 950, 1140]
  for (let i = 0; i < 6; i++) {
    const n = i + 1
    const cx = dtX[i % 3]
    const cy = 286 + Math.floor(i / 3) * 160
    dt.push(
      txt(`t_dtn${n}`, cx - 18, cy - 18, 110, 18, `WTG-0${n}`, 10, '#7dd3c7'),
      nd(`c_dtr${n}`, 'symbol', cx, cy, 64, 64, {
        name: `孪生叶轮${n}`, props: { symbolId: 'energy/wind-rotor' },
        anim: { rotate: { enabled: true, clockwise: true, periodMs: 2200 } },
        style: { color: ACCENT_2 },
        bindings: [bd(`v_t${n}`, 'style.color', 'color', turbineColor), bd('v_rp', 'anim.rotatePeriod')],
        tooltip: `WTG-0${n} 实时功率 {v_t${n}} MW`,
      }),
      nd(`c_dtt${n}`, 'line', cx + 30, cy + 64, 4, 48, { name: `塔筒${n}`, style: { fill: '#0e7490', borderRadius: 2 } }),
      nd(`c_dtp${n}`, 'var-display', cx - 30, cy + 116, 124, 24, {
        name: `孪生功率${n}`, props: { prefix: '', unit: 'MW', precision: 2 },
        style: { color: '#a5f3ec', fontSize: 12 },
        bindings: [bd(`v_t${n}`, 'props.value')],
      }),
    )
  }

  const comps: ComponentNode[] = [
    // ---- 顶带 ----
    nd('c_title', 'title-bar', 0, 0, 1920, 86, {
      name: '标题栏', props: { text: '海上风电集控中心 · 39 MW 海上风场', align: 'center' },
      style: { color: ACCENT },
    }),
    txt('t_sub', 40, 24, 420, 26, 'EAST CHINA SEA · OFFSHORE WIND FARM', 11, '#3f8b86'),
    nd('c_clock', 'clock', 1560, 16, 320, 52, {
      props: { showDate: true, showSeconds: true, layout: 'horizontal' }, style: { color: '#c7f9f2' },
    }),

    // ---- KPI ----
    ...kpi(40, '全场有功功率', 'MW', 'v_power', 2),
    ...kpi(510, '出力负载率', '%', 'v_cap', 1),
    ...kpi(980, '今日发电量', 'MWh', 'v_energy', 1),
    ...kpi(1450, '轮毂风速', 'm/s', 'v_spd_v', 1),

    // ---- 左列：机组阵列 ----
    nd('c_lpanel', 'rect', 40, 220, 640, 820, {
      name: '机组阵列面板', style: { fill: PANEL_FILL, stroke: 'rgba(94,234,212,0.12)', strokeWidth: 1, borderRadius: 12 },
    }),
    txt('t_lsec', 60, 236, 420, 24, '风机阵列 · 6 / 6 在线', 15, ACCENT_DIM),
    txt('t_lsub', 60, 258, 420, 18, '叶轮转速 / 功率 / 负载率随风速实时联动', 10, '#4f7f7d'),
    ...cards,

    // ---- 中央：数字孪生 ----
    nd('c_cpanel', 'rect', 700, 220, 540, 420, {
      name: '数字孪生面板', style: { fill: PANEL_FILL, stroke: 'rgba(94,234,212,0.12)', strokeWidth: 1, borderRadius: 12 },
    }),
    txt('t_csec', 720, 236, 420, 24, '风场数字孪生 · 实时功率汇集', 15, ACCENT_DIM),
    nd('c_seabed', 'rect', 716, 266, 508, 358, {
      name: '海面底层', style: { fill: 'linear-gradient(180deg, rgba(6,40,50,0.55) 0%, rgba(3,16,22,0.9) 100%)', stroke: 'rgba(34,211,238,0.10)', strokeWidth: 1, borderRadius: 8 },
    }),
    nd('c_arc', 'symbol', 868, 286, 204, 204, { name: '弧光', props: { symbolId: 'decor/arc-glow' }, style: { color: '#0e7490' } }),
    ...dt,
    nd('c_dtflow', 'flow-bar', 740, 598, 460, 14, {
      name: '汇集海缆', props: { speed: 60, showArrow: true }, style: { color: ACCENT_2 },
      bindings: [bd('v_flow', 'props.speed')], tooltip: '66kV 汇集海缆 · 流速随风速变化',
    }),

    // ---- 中央下：功率历史 ----
    nd('c_hpanel', 'rect', 700, 660, 540, 380, {
      name: '功率历史面板', style: { fill: PANEL_FILL, stroke: 'rgba(94,234,212,0.12)', strokeWidth: 1, borderRadius: 12 },
    }),
    txt('t_hsec', 720, 676, 420, 24, '轮毂风速 · 近 1 小时', 15, ACCENT_DIM),
    // 用带 mock 的原始变量取历史：生成案例时 seedCaseHistory 已预置 6h 曲线，打开即有走势
    nd('c_hist', 'history-chart', 716, 704, 508, 320, {
      name: '风速历史', props: {
        variableId: 'w_spd', title: '', unit: 'm/s', rangeMs: 3600000,
        color: ACCENT, areaColor: 'rgba(94,234,212,0.16)',
      },
    }),

    // ---- 右列：并网 ----
    nd('c_rpanelA', 'rect', 1256, 220, 624, 300, {
      name: '并网面板', style: { fill: PANEL_FILL, stroke: 'rgba(94,234,212,0.12)', strokeWidth: 1, borderRadius: 12 },
    }),
    txt('t_rsecA', 1276, 236, 420, 24, '并网点 · 35 kV 海上升压站', 15, ACCENT_DIM),
    nd('c_g_freq', 'gauge', 1272, 262, 250, 224, {
      name: '并网频率', props: { title: '并网频率', unit: 'Hz', min: 49.5, max: 50.5, precision: 3, textColor: '#d7f9f2', color: ACCENT },
      bindings: [bd('v_grid_v', 'props.value')],
    }),
    nd('c_v_v', 'var-display', 1540, 276, 320, 46, {
      name: '母线电压', props: { prefix: '母线电压', unit: 'kV', precision: 2 }, style: { color: '#d7f9f2', fontSize: 16 },
      bindings: [bd('w_volt', 'props.value')],
    }),
    nd('c_v_p', 'var-display', 1540, 328, 320, 46, {
      name: '有功功率', props: { prefix: '有功功率', unit: 'MW', precision: 2 }, style: { color: ACCENT, fontSize: 16 },
      bindings: [bd('v_power', 'props.value')],
    }),
    nd('c_v_pf', 'var-display', 1540, 380, 320, 46, {
      name: '功率因数', props: { prefix: '功率因数', unit: '', precision: 3 }, style: { color: '#d7f9f2', fontSize: 16 },
      bindings: [bd('v_pf', 'props.value')],
    }),
    nd('c_v_q', 'var-display', 1540, 432, 320, 46, {
      name: '无功功率', props: { prefix: '无功功率', unit: 'Mvar', precision: 2 }, style: { color: '#a5f3ec', fontSize: 16 },
      bindings: [bd('v_q', 'props.value')],
    }),
    txt('t_rnote', 1540, 484, 320, 22, '动态无功补偿 SVG 投运 · 电能质量 A 级', 10, '#4f7f7d'),

    // ---- 右列：单机功率明细 ----
    nd('c_rpanelB', 'rect', 1256, 528, 624, 248, {
      name: '单机明细面板', style: { fill: PANEL_FILL, stroke: 'rgba(94,234,212,0.12)', strokeWidth: 1, borderRadius: 12 },
    }),
    txt('t_rsecB', 1276, 544, 420, 22, '单机有功功率 · 实时明细', 15, ACCENT_DIM),
    ...Array.from({ length: 6 }, (_, i) => {
      const n = i + 1
      const y = 572 + i * 32
      return [
        txt(`t_row${n}`, 1276, y, 70, 22, `WTG-0${n}`, 11, '#9fd8d2'),
        nd(`c_rowp${n}`, 'var-display', 1350, y - 2, 104, 26, {
          name: `明细功率${n}`, props: { prefix: '', unit: 'MW', precision: 2 }, style: { color: '#e6fffb', fontSize: 12 },
          bindings: [bd(`v_t${n}`, 'props.value')],
        }),
        nd(`c_rowl${n}`, 'progress', 1464, y + 2, 300, 16, {
          name: `明细负载${n}`, props: { percent: 0, precision: 0, color: `linear-gradient(90deg, #0e7490, ${ACCENT_2})` },
          bindings: [bd(`v_l${n}`, 'props.percent')],
        }),
        nd(`c_rowsl${n}`, 'status-light', 1780, y + 1, 17, 17, { name: `明细状态${n}`, style: { color: '#34d399' } }),
      ]
    }).flat(),

    // ---- 右列：联锁监视 ----
    nd('c_rpanelC', 'rect', 1256, 792, 624, 248, {
      name: '联锁面板', style: { fill: PANEL_FILL, stroke: 'rgba(94,234,212,0.12)', strokeWidth: 1, borderRadius: 12 },
    }),
    txt('t_rsecC', 1276, 808, 420, 22, '齿轮箱 / 主轴 · 联锁监视', 15, ACCENT_DIM),
    nd('c_g_oil', 'gauge', 1272, 832, 288, 166, {
      name: '油温表', props: { title: '齿轮箱油温', unit: '℃', min: 40, max: 80, precision: 1, textColor: '#d7f9f2', color: '#fbbf24' },
      bindings: [bd('v_oil_v', 'props.value')],
    }),
    nd('c_g_vib', 'gauge', 1576, 832, 288, 166, {
      name: '振动表', props: { title: '主轴振动', unit: 'mm/s', min: 0, max: 6, precision: 2, textColor: '#d7f9f2', color: '#fb7185' },
      bindings: [bd('v_vib_v', 'props.value')],
    }),
    // 越限渐变 + 闪烁（联锁触点）
    nd('c_sl_oil', 'status-light', 1280, 1004, 18, 18, {
      name: '油温联锁', style: { color: '#34d399' },
      anim: { blink: { enabled: false, intervalMs: 600 } },
      bindings: [
        bd('w_oil', 'style.color', 'color', rangeMap({ max: 70, value: '#34d399' }, { min: 70, value: '#ef4444' })),
        bd('w_oil', 'anim.blinkOn', 'value', rangeMap({ max: 70, value: false }, { min: 70, value: true })),
      ],
      tooltip: '齿轮箱油温 {w_oil} ℃（>70 触发联锁）',
    }),
    txt('t_sl_oil', 1304, 1004, 130, 20, '油温联锁', 11, '#9fd8d2'),
    nd('c_sl_vib', 'status-light', 1460, 1004, 18, 18, {
      name: '振动联锁', style: { color: '#34d399' },
      anim: { blink: { enabled: false, intervalMs: 600 } },
      bindings: [
        bd('w_vib', 'style.color', 'color', rangeMap({ max: 4.6, value: '#34d399' }, { min: 4.6, value: '#ef4444' })),
        bd('w_vib', 'anim.blinkOn', 'value', rangeMap({ max: 4.6, value: false }, { min: 4.6, value: true })),
      ],
      tooltip: '主轴振动 {w_vib} mm/s（>4.6 触发联锁）',
    }),
    txt('t_sl_vib', 1484, 1004, 130, 20, '振动联锁', 11, '#9fd8d2'),
    nd('c_sl_yaw', 'status-light', 1640, 1004, 18, 18, { name: '偏航自动', style: { color: '#34d399' }, tooltip: '偏航系统自动对风' }),
    txt('t_sl_yaw', 1664, 1004, 100, 20, '偏航自动', 11, '#9fd8d2'),
    nd('c_avail', 'var-display', 1770, 1000, 96, 22, {
      name: '可利用率', props: { prefix: '', unit: '%', precision: 1 }, style: { color: '#7dd3c7', fontSize: 11 },
      bindings: [bd('v_avail', 'props.value')],
    }),
  ]

  return demoDoc(
    '海上风电集控',
    '深海青主题：风速立方律驱动 6 台机组功率与叶轮转速；数字孪生阵列、并网频率、油温/振动联锁三层下钻，全量 mock 实时数据。',
    vars,
    [pg('p_main', '海上风电集控', 1920, 1080, comps, { lockPan: true, bg: '#020a10', bgImage: '/bg/wind-farm.svg', bgOpacity: 0.95 })],
    [
      alm('a_oil', '齿轮箱油温高', 'w_oil', '>', 70, 'critical', '齿轮箱油温高：{value} ℃（阈值 70，联锁降载）'),
      alm('a_vib', '主轴振动超限', 'w_vib', '>', 4.6, 'critical', '主轴振动超限：{value} mm/s（阈值 4.6）'),
      alm('a_spd', '风速接近切出', 'w_spd_eff', '>', 13.5, 'warn', '风速接近切出：{value} m/s'),
      alm('a_freq', '并网频率偏低', 'w_grid', '<', 49.92, 'warn', '并网频率偏低：{value} Hz'),
    ],
  )
}
