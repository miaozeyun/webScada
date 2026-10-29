/**
 * 演示案例十二：智能制造产线数字孪生（行业 demo · 琥珀产线主题，2026-10-29）。
 *
 * 视觉主角：6 工位沿输送线联动，线速驱动节拍/产量/单件能耗；
 * 工位三态（停机/运行/故障）与 OEE、良率、在制品、主轴温度/振动同屏下钻，
 * 支持线体模式、目标节拍、急停反控。全量 mock 实时数据。
 */
import type { ComponentNode } from '@/types/doc'
import { alm, bd, demoDoc, enumMap, mvar, nd, pg, rangeMap, txt, vvar } from './shared'

const ACCENT = '#fbbf24'
const ACCENT_2 = '#f59e0b'
const ACCENT_3 = '#fcd34d'
const OK = '#34d399'
const CARD_FILL = 'linear-gradient(160deg, rgba(42,28,8,0.94) 0%, rgba(18,12,4,0.9) 100%)'
const PANEL_FILL = 'linear-gradient(165deg, rgba(34,22,6,0.9) 0%, rgba(12,8,3,0.88) 100%)'

const STATIONS = [
  { name: '上料', symbol: 'pump/gear', factor: 1.0, base: 44, amp: 12 },
  { name: '激光焊接', symbol: 'hvac/axial-fan', factor: 1.05, base: 36, amp: 10 },
  { name: '精密加工', symbol: 'motor', factor: 1.12, base: 28, amp: 9 },
  { name: '视觉检测', symbol: 'misc/camera', factor: 0.98, base: 22, amp: 8 },
  { name: '总装', symbol: 'misc/gateway', factor: 1.08, base: 31, amp: 11 },
  { name: '包装码垛', symbol: 'tank/horizontal', factor: 1.15, base: 18, amp: 7 },
]

export function buildLineDoc(): ReturnType<typeof demoDoc> {
  // ---- 变量 ----
  // 慢趋势（20min 周期，供近 1h 历史曲线）+ 传动抖动（合成值驱动节拍/产量/能耗）
  const speed = mvar('m_spd', 'm_spd', '线速度', { kind: 'sine', min: 32, max: 45, periodMs: 1200000, unit: 'm/min', precision: 1 })
  const speedGust = mvar('m_g', 'm_g', '速度抖动', { kind: 'sine', min: -2.2, max: 2.2, periodMs: 6000, unit: 'm/min', precision: 1 })
  const ct = vvar('m_ct', 'm_ct', '节拍', 'round(60 / max(1, m_spd_eff * 1.35), 2)', { unit: 's', precision: 2 })
  const spindle = mvar('m_spd_t', 'm_spd_t', '主轴温度', { kind: 'sine', min: 48, max: 72, periodMs: 90000, unit: '℃', precision: 1 })
  const vib = mvar('m_vib', 'm_vib', '主轴振动', { kind: 'sine', min: 0.8, max: 3.6, periodMs: 45000, unit: 'mm/s', precision: 2 })
  const press = mvar('m_press', 'm_press', '气源压力', { kind: 'sine', min: 0.55, max: 0.72, periodMs: 52000, unit: 'MPa', precision: 2 })
  const mode = mvar('m_mode', 'm_mode', '线体模式', { kind: 'hold', def: 1, unit: '', precision: 0, writable: true })
  const takt = mvar('m_takt', 'm_takt', '目标节拍', { kind: 'hold', def: 1.4, unit: 's', precision: 2, writable: true })
  const estop = mvar('m_estop', 'm_estop', '急停', { kind: 'hold', def: 0, unit: '', precision: 0, writable: true })

  const vars: ReturnType<typeof mvar>[] = [speed, speedGust, ct, spindle, vib, press, mode, takt, estop]

  vars.push(
    vvar('m_spd_eff', 'm_spd_eff', '线速度(合成)', 'round(max(10, min(50, m_spd + m_g)), 1)', { unit: 'm/min', precision: 1 }),
    // _tick 为 Unix 秒：/23 约 145s 周期；累计产量按时段秒数增长，零点归零
    vvar('m_out', 'm_out', '累计产量', 'round(12480 + (_tick % 86400) / max(1.2, 3.8 - m_spd_eff * 0.048), 0)', { unit: '件', precision: 0 }),
    vvar('m_oee', 'm_oee', 'OEE', 'round(84.5 + sin(_tick / 23) * 4.2, 1)', { unit: '%', precision: 1 }),
    vvar('m_yield', 'm_yield', '良率', 'round(98.2 + sin(_tick / 29) * 0.9, 2)', { unit: '%', precision: 2 }),
    vvar('m_scrap', 'm_scrap', '不良率', 'round(100 - m_yield, 2)', { unit: '%', precision: 2 }),
    vvar('m_energy', 'm_energy', '单件能耗', 'round(0.42 + (46 - m_spd_eff) * 0.004, 3)', { unit: 'kWh/件', precision: 3 }),
    vvar('m_wip', 'm_wip', '在制品', 'round(28 + sin(_tick / 9) * 16, 0)', { unit: '件', precision: 0 }),
    vvar('m_flow', 'm_flow', '输送线速度', 'round(m_spd_eff * 3, 0)', { unit: 'px/s', precision: 0 }),
    vvar('m_fault', 'm_fault', '故障工位数', '(m_s1 == 2 ? 1 : 0) + (m_s2 == 2 ? 1 : 0) + (m_s3 == 2 ? 1 : 0) + (m_s4 == 2 ? 1 : 0) + (m_s5 == 2 ? 1 : 0) + (m_s6 == 2 ? 1 : 0)', { unit: '个', precision: 0 }),
    vvar('m_run', 'm_run', '运行工位数', '(m_s1 == 1 ? 1 : 0) + (m_s2 == 1 ? 1 : 0) + (m_s3 == 1 ? 1 : 0) + (m_s4 == 1 ? 1 : 0) + (m_s5 == 1 ? 1 : 0) + (m_s6 == 1 ? 1 : 0)', { unit: '个', precision: 0 }),
    vvar('m_uptime', 'm_uptime', '设备开动率', 'round(92.6 + sin(_tick / 19) * 2.4, 1)', { unit: '%', precision: 1 }),
    // 展示副本：避免报警实色底糊住 OEE 大表盘/KPI（状态灯/故障汇总仍用原变量）
    vvar('m_oee_v', 'm_oee_v', 'OEE 读数', 'round(m_oee, 1)', { unit: '%', precision: 1 }),
    vvar('m_spdt_v', 'm_spdt_v', '主轴温度读数', 'round(m_spd_t, 1)', { unit: '℃', precision: 1 }),
    vvar('m_vib_v', 'm_vib_v', '振动读数', 'round(m_vib, 2)', { unit: 'mm/s', precision: 2 }),
    vvar('m_fault_v', 'm_fault_v', '故障工位读数', 'm_fault', { unit: '个', precision: 0 }),
  )

  // 6 工位状态：方波（0 停机 / 1 运行 / 2 故障），相位与占空比错开
  const periods = [37000, 53000, 43000, 61000, 47000, 59000]
  const duties = [0.86, 0.78, 0.9, 0.92, 0.82, 0.88]
  for (let i = 1; i <= 6; i++) {
    vars.push(mvar(`m_s${i}`, `m_s${i}`, `${STATIONS[i - 1].name} 工位状态`, {
      kind: 'square', min: 0, max: 1, periodMs: periods[i - 1], duty: duties[i - 1],
    }))
    vars.push(vvar(`m_ct${i}`, `m_ct${i}`, `${STATIONS[i - 1].name} 节拍`,
      `round(m_ct * ${STATIONS[i - 1].factor}, 2)`, { unit: 's', precision: 2 }))
    vars.push(vvar(`m_buf${i}`, `m_buf${i}`, `${STATIONS[i - 1].name} 缓存`,
      `round(max(0, ${STATIONS[i - 1].base} + sin(_tick / ${6.2 + i * 0.7} + ${i}) * ${STATIONS[i - 1].amp}), 0)`,
      { unit: '件', precision: 0 }))
  }

  // 4 号工位偶发故障（视觉检测失败）：off 值 2，周期长、占空比高
  const s4 = vars.find((v) => v.id === 'm_s4')
  if (s4 && s4.mock && s4.mock.kind === 'square') s4.mock.offValue = 2

  // ---- 顶部 KPI ----
  const kpi = (x: number, label: string, unit: string, varId: string, decimals: number, color: string) => [
    nd(`c_kpi${x}`, 'rect', x, 104, 430, 100, {
      name: `KPI·${label}`,
      style: { fill: CARD_FILL, stroke: 'rgba(251,191,36,0.18)', strokeWidth: 1, borderRadius: 10 },
    }),
    txt(`t_kpi${x}`, x + 18, 114, 300, 20, label, 12, '#d6a94a'),
    nd(`c_fc${x}`, 'flip-counter', x + 16, 136, 398, 54, {
      name: label, props: { value: '0', unit, decimals, bg: 'transparent', border: 'transparent', color },
      bindings: [bd(varId, 'props.value')],
    }),
    nd(`c_kl${x}`, 'line', x + 18, 198, 120, 2, { name: `${label}强调线`, style: { fill: color } }),
  ]

  // ---- 工位卡 ----
  const stationColor = enumMap({ '0': '#5b6b80', '1': OK, '2': '#ef4444' })
  const stateJson = '[{"value":0,"text":"停机","color":"#94a3b8"},{"value":1,"text":"运行","color":"#34d399"},{"value":2,"text":"故障","color":"#ef4444"}]'
  const stations: ComponentNode[] = []
  for (let i = 0; i < 6; i++) {
    const n = i + 1
    const x = 84 + i * 190
    const st = STATIONS[i]
    stations.push(
      nd(`c_stc${n}`, 'rect', x, 280, 170, 190, {
        name: `${st.name}工位卡`,
        style: { fill: CARD_FILL, stroke: 'rgba(251,191,36,0.14)', strokeWidth: 1, borderRadius: 10 },
      }),
      txt(`t_stn${n}`, x + 12, 290, 110, 20, `S0${n} ${st.name}`, 11, '#f5e6c4'),
      nd(`c_stsl${n}`, 'status-light', x + 140, 290, 18, 18, {
        name: `${st.name}状态灯`, style: { color: OK },
        bindings: [bd(`m_s${n}`, 'style.color', 'color', stationColor)],
        tooltip: `${st.name}工位状态：{m_s${n}}（0 停机 / 1 运行 / 2 故障）`,
      }),
      st.symbol === 'motor'
        ? nd(`c_stsym${n}`, 'motor', x + 12, 318, 68, 68, {
            name: `${st.name}设备`, style: { color: ACCENT_2 },
            anim: { rotate: { enabled: true, clockwise: true, periodMs: 1600 } },
            bindings: [bd(`m_s${n}`, 'anim.rotateOn'), bd(`m_s${n}`, 'style.color', 'color', stationColor)],
          })
        : nd(`c_stsym${n}`, 'symbol', x + 12, 318, 68, 68, {
            name: `${st.name}设备`, props: { symbolId: st.symbol }, style: { color: ACCENT_2 },
            bindings: [bd(`m_s${n}`, 'style.color', 'color', stationColor)],
          }),
      nd(`c_stst${n}`, 'state-text', x + 90, 322, 70, 28, {
        name: `${st.name}状态`, props: { defaultText: '停机', states: stateJson },
        bindings: [bd(`m_s${n}`, 'props.value')],
      }),
      nd(`c_stct${n}`, 'var-display', x + 90, 356, 70, 24, {
        name: `${st.name}节拍`, props: { prefix: '', unit: 's', precision: 2 }, style: { color: ACCENT_3, fontSize: 11 },
        bindings: [bd(`m_ct${n}`, 'props.value')],
      }),
      nd(`c_stbuf${n}`, 'var-display', x + 12, 400, 146, 22, {
        name: `${st.name}缓存`, props: { prefix: '缓存', unit: '件', precision: 0 }, style: { color: '#b79a63', fontSize: 10 },
        bindings: [bd(`m_buf${n}`, 'props.value')],
      }),
      nd(`c_stbar${n}`, 'progress', x + 12, 432, 146, 14, {
        name: `${st.name}缓存水位`, props: { percent: 0, precision: 0, color: `linear-gradient(90deg, #92400e, ${ACCENT})` },
        bindings: [bd(`m_buf${n}`, 'props.percent')],
      }),
    )
  }

  const comps: ComponentNode[] = [
    // ---- 顶带 ----
    nd('c_title', 'title-bar', 0, 0, 1920, 86, {
      name: '标题栏', props: { text: '智造产线 · 数字孪生总廊', align: 'center' },
      style: { color: ACCENT },
    }),
    txt('t_sub', 40, 24, 460, 26, 'SMART FACTORY · LINE DIGITAL TWIN', 11, '#9c7a35'),
    nd('c_clock', 'clock', 1560, 16, 320, 52, {
      props: { showDate: true, showSeconds: true, layout: 'horizontal' }, style: { color: '#f5e6c4' },
    }),

    // ---- KPI ----
    ...kpi(40, 'OEE 综合效率', '%', 'm_oee_v', 1, ACCENT),
    ...kpi(510, '累计产量', '件', 'm_out', 0, ACCENT_3),
    ...kpi(980, '当前节拍', 's', 'm_ct', 2, '#fdba74'),
    ...kpi(1450, '良率', '%', 'm_yield', 2, OK),

    // ---- 产线总廊 ----
    nd('c_linepanel', 'rect', 40, 220, 1240, 470, {
      name: '产线面板', style: { fill: PANEL_FILL, stroke: 'rgba(251,191,36,0.12)', strokeWidth: 1, borderRadius: 12 },
    }),
    txt('t_linesec', 60, 236, 500, 24, '产线总廊 · 6 工位联动', 15, '#d6a94a'),
    txt('t_linesub', 60, 258, 700, 16, '工位三态（停机 / 运行 / 故障）驱动颜色与输送线启停；节拍随线速联动', 10, '#8a6a2c'),
    ...stations,

    // 输送线（线速驱动流动）
    nd('c_conveyor', 'flow-bar', 84, 492, 1120, 22, {
      name: '主输送线', props: { speed: 90, showArrow: true }, style: { color: ACCENT_2 },
      bindings: [bd('m_flow', 'props.speed')], tooltip: '主输送线 · 流速随线速变化',
    }),
    txt('t_flow_l', 84, 520, 200, 18, '上料 → 焊接 → 加工 → 检测 → 总装 → 码垛', 9, '#8a6a2c'),

    // 线尾汇总
    nd('c_wip', 'var-display', 84, 556, 300, 44, {
      name: '在制品', props: { prefix: '在制品 WIP', unit: '件', precision: 0 }, style: { color: ACCENT_3, fontSize: 16 },
      bindings: [bd('m_wip', 'props.value')],
    }),
    nd('c_speed', 'var-display', 410, 556, 300, 44, {
      name: '线速度', props: { prefix: '线速度', unit: 'm/min', precision: 1 }, style: { color: '#f5e6c4', fontSize: 16 },
      bindings: [bd('m_spd_eff', 'props.value')],
    }),
    nd('c_press', 'var-display', 736, 556, 300, 44, {
      name: '气源压力', props: { prefix: '气源压力', unit: 'MPa', precision: 2 }, style: { color: ACCENT, fontSize: 16 },
      bindings: [bd('m_press', 'props.value')],
    }),
    nd('c_run', 'var-display', 1062, 556, 178, 44, {
      name: '运行工位', props: { prefix: '运行', unit: '个', precision: 0 }, style: { color: OK, fontSize: 16 },
      bindings: [bd('m_run', 'props.value')],
    }),
    txt('t_linefoot', 84, 612, 1120, 64, '单件能耗由线速推导；4 号视觉检测工位偶发故障（红色闪烁），故障工位数实时汇总。点击右侧控制区可切换线体模式 / 下发目标节拍 / 急停。', 10, '#6f5628'),

    // ---- 左下：OEE 趋势 ----
    nd('c_oeePanel', 'rect', 40, 708, 610, 332, {
      name: 'OEE 面板', style: { fill: PANEL_FILL, stroke: 'rgba(251,191,36,0.12)', strokeWidth: 1, borderRadius: 12 },
    }),
    txt('t_oeesec', 60, 724, 420, 22, '线速度 · 近 1 小时', 15, '#d6a94a'),
    // 用带 mock 的原始变量取历史：生成案例时已预置 6h 曲线
    nd('c_oeehist', 'history-chart', 56, 752, 578, 276, {
      name: '线速度历史', props: {
        variableId: 'm_spd', title: '', unit: 'm/min', rangeMs: 3600000,
        color: ACCENT, areaColor: 'rgba(251,191,36,0.16)',
      },
    }),

    // ---- 中下：工位节拍明细 ----
    nd('c_detpanel', 'rect', 670, 708, 610, 332, {
      name: '节拍明细面板', style: { fill: PANEL_FILL, stroke: 'rgba(251,191,36,0.12)', strokeWidth: 1, borderRadius: 12 },
    }),
    txt('t_detsec', 690, 724, 420, 22, '工位节拍 · 实时明细', 15, '#d6a94a'),
    ...STATIONS.flatMap((st, i) => {
      const n = i + 1
      const y = 760 + i * 42
      return [
        txt(`t_dn${n}`, 690, y, 90, 22, `S0${n} ${st.name}`, 11, '#c9ad74'),
        nd(`c_dct${n}`, 'var-display', 786, y - 2, 96, 26, {
          name: `明细节拍${n}`, props: { prefix: '', unit: 's', precision: 2 }, style: { color: '#f5e6c4', fontSize: 12 },
          bindings: [bd(`m_ct${n}`, 'props.value')],
        }),
        nd(`c_db${n}`, 'var-display', 886, y - 2, 88, 26, {
          name: `明细缓存${n}`, props: { prefix: '', unit: '件', precision: 0 }, style: { color: '#b79a63', fontSize: 12 },
          bindings: [bd(`m_buf${n}`, 'props.value')],
        }),
        nd(`c_dp${n}`, 'progress', 980, y + 3, 274, 14, {
          name: `缓存水位${n}`, props: { percent: 0, precision: 0, color: `linear-gradient(90deg, #92400e, ${ACCENT_2})` },
          bindings: [bd(`m_buf${n}`, 'props.percent')],
        }),
      ]
    }),

    // ---- 右列：OEE 总览 ----
    nd('c_oeeCard', 'rect', 1300, 220, 580, 300, {
      name: 'OEE 总览面板', style: { fill: PANEL_FILL, stroke: 'rgba(251,191,36,0.12)', strokeWidth: 1, borderRadius: 12 },
    }),
    txt('t_oeecard', 1320, 236, 420, 22, 'OEE 总览 · 三率构成', 15, '#d6a94a'),
    nd('c_g_oee', 'gauge', 1316, 268, 252, 232, {
      name: 'OEE 仪表', props: { title: 'OEE', unit: '%', min: 60, max: 100, precision: 1, textColor: '#f5e6c4', color: ACCENT },
      bindings: [bd('m_oee_v', 'props.value')],
    }),
    nd('c_yieldv', 'var-display', 1590, 280, 270, 42, {
      name: '良率', props: { prefix: '良率', unit: '%', precision: 2 }, style: { color: OK, fontSize: 15 },
      bindings: [bd('m_yield', 'props.value')],
    }),
    nd('c_scrapv', 'var-display', 1590, 330, 270, 42, {
      name: '不良率', props: { prefix: '不良率', unit: '%', precision: 2 }, style: { color: '#fca5a5', fontSize: 15 },
      bindings: [bd('m_scrap', 'props.value')],
    }),
    nd('c_energyv', 'var-display', 1590, 380, 270, 42, {
      name: '单件能耗', props: { prefix: '单件能耗', unit: 'kWh/件', precision: 3 }, style: { color: ACCENT_3, fontSize: 15 },
      bindings: [bd('m_energy', 'props.value')],
    }),
    nd('c_uptimev', 'var-display', 1590, 430, 270, 42, {
      name: '开动率', props: { prefix: '开动率', unit: '%', precision: 1 }, style: { color: '#f5e6c4', fontSize: 15 },
      bindings: [bd('m_uptime', 'props.value')],
    }),

    // ---- 右列：主轴监视 ----
    nd('c_spdPanel', 'rect', 1300, 534, 580, 250, {
      name: '主轴面板', style: { fill: PANEL_FILL, stroke: 'rgba(251,191,36,0.12)', strokeWidth: 1, borderRadius: 12 },
    }),
    txt('t_spdsec', 1320, 550, 420, 22, '主轴温度 / 振动', 15, '#d6a94a'),
    nd('c_g_spdt', 'gauge', 1316, 574, 274, 190, {
      name: '主轴温度表', props: { title: '主轴温度', unit: '℃', min: 40, max: 80, precision: 1, textColor: '#f5e6c4', color: ACCENT_2 },
      bindings: [bd('m_spdt_v', 'props.value')],
    }),
    nd('c_g_vib', 'gauge', 1596, 574, 274, 190, {
      name: '振动表', props: { title: '主轴振动', unit: 'mm/s', min: 0, max: 5, precision: 2, textColor: '#f5e6c4', color: '#fb7185' },
      bindings: [bd('m_vib_v', 'props.value')],
    }),

    // ---- 右列：控制与安防 ----
    nd('c_ctrlPanel', 'rect', 1300, 798, 580, 242, {
      name: '控制面板', style: { fill: PANEL_FILL, stroke: 'rgba(251,191,36,0.12)', strokeWidth: 1, borderRadius: 12 },
    }),
    txt('t_ctrlsec', 1320, 814, 420, 22, '线体控制 · 安全联锁', 15, '#d6a94a'),
    txt('t_mode', 1320, 848, 100, 18, '线体模式', 10, '#8a6a2c'),
    nd('c_mode', 'multi-switch', 1424, 840, 250, 40, {
      name: '线体模式', props: {
        variableId: 'm_mode',
        levels: '[{"value":0,"label":"停止"},{"value":1,"label":"单机"},{"value":2,"label":"联动"}]',
      },
    }),
    txt('t_takt', 1690, 848, 90, 18, '目标节拍', 10, '#8a6a2c'),
    nd('c_takt', 'input-cmd', 1686, 868, 180, 38, {
      name: '目标节拍', props: { variableId: 'm_takt', placeholder: '如 1.4', unit: 's', buttonText: '下发', clearAfter: true },
    }),
    nd('c_estop', 'switch', 1320, 898, 220, 40, {
      name: '急停', props: { variableId: 'm_estop', onValue: 1, offValue: 0, confirm: true, label: '急停' },
    }),
    nd('c_sl_estop', 'status-light', 1560, 908, 18, 18, {
      name: '急停状态灯', style: { color: OK },
      bindings: [bd('m_estop', 'style.color', 'color', enumMap({ '0': OK, '1': '#ef4444' }))],
      tooltip: '急停 {m_estop}（1=已拍下）',
    }),
    txt('t_sl_estop', 1584, 908, 90, 18, '急停', 10, '#8a6a2c'),
    nd('c_sl_light', 'status-light', 1660, 908, 18, 18, { name: '安全光栅', style: { color: OK }, tooltip: '安全光栅无遮挡' }),
    txt('t_sl_light', 1684, 908, 90, 18, '光栅', 10, '#8a6a2c'),
    nd('c_sl_door', 'status-light', 1752, 908, 18, 18, { name: '安全门', style: { color: OK }, tooltip: '安全门关闭' }),
    txt('t_sl_door', 1776, 908, 80, 18, '安全门', 10, '#8a6a2c'),
    txt('t_ctrlhint', 1320, 950, 540, 44, '线体模式 / 目标节拍 / 急停均为可写变量，点击即下发并回环显示；急停与安全光栅联动停线。', 10, '#6f5628'),
    nd('c_faultv', 'var-display', 1320, 1000, 240, 26, {
      name: '故障工位', props: { prefix: '故障工位', unit: '个', precision: 0 }, style: { color: '#fca5a5', fontSize: 11 },
      bindings: [bd('m_fault_v', 'props.value')],
    }),
    nd('c_runv', 'var-display', 1580, 1000, 240, 26, {
      name: '运行工位', props: { prefix: '运行工位', unit: '个', precision: 0 }, style: { color: OK, fontSize: 11 },
      bindings: [bd('m_run', 'props.value')],
    }),
  ]

  return demoDoc(
    '智能制造产线',
    '琥珀产线主题：6 工位三态联动、线速驱动节拍/产量/单件能耗；OEE 与工位明细下钻，支持线体模式、目标节拍、急停反控。',
    vars,
    [pg('p_main', '智造产线总览', 1920, 1080, comps, { lockPan: true, bg: '#050301', bgImage: '/bg/line-amber.svg', bgOpacity: 0.95 })],
    [
      alm('a_spdt', '主轴温度高', 'm_spd_t', '>', 70, 'critical', '主轴温度高：{value} ℃（阈值 70）'),
      alm('a_vib', '主轴振动超限', 'm_vib', '>', 3.2, 'warn', '主轴振动超限：{value} mm/s（阈值 3.2）'),
      alm('a_oee', 'OEE 低于目标', 'm_oee', '<', 82, 'warn', 'OEE 低于目标：{value} %（目标 ≥82）'),
      alm('a_fault', '工位故障', 'm_fault', '>', 0, 'critical', '工位故障：{value} 个工位处于故障态'),
    ],
  )
}
