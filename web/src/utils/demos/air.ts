/**
 * 演示案例九：空压站集控（行业 demo · 灰蓝能量橙主题）。
 * 视觉主角：三台螺杆机「待机灰 / 加载橙 / 卸载蓝」三态联动（多档开关反控），
 * 母管压力大表盘随加卸载往复呼吸，加载台数由表达式实时汇总。
 */
import { alm, bd, demoDoc, enumMap, mvar, nd, onOff, pg, txt, vvar } from './shared'
import type { ComponentNode } from '@/types/doc'

export function buildAirDoc(): ReturnType<typeof demoDoc> {
  const vars = [
    mvar('a_m1', 'a_m1', '1# 螺杆机模式', { kind: 'hold', def: 2, writable: true }),
    mvar('a_m2', 'a_m2', '2# 螺杆机模式', { kind: 'hold', def: 1, writable: true }),
    mvar('a_m3', 'a_m3', '3# 螺杆机模式', { kind: 'hold', def: 0, writable: true }),
    mvar('a_mpr', 'a_mpr', '母管压力', { kind: 'ramp', min: 0.58, max: 0.84, periodMs: 47000, unit: 'MPa', precision: 2 }),
    mvar('a_flow', 'a_flow', '总供气流量', { kind: 'sine', min: 8, max: 42, periodMs: 60000, unit: 'Nm³/min', precision: 1 }),
    vvar('a_nload', 'a_nload', '加载台数', '(a_m1 == 1 ? 1 : 0) + (a_m2 == 1 ? 1 : 0) + (a_m3 == 1 ? 1 : 0)', { unit: '台', precision: 0 }),
    vvar('a_kwh', 'a_kwh', '今日能耗', 'round(1594 + sin(_tick / 95000) * 12, 0)', { unit: 'kWh', precision: 0 }),
    mvar('a_dew', 'a_dew', '压力露点', { kind: 'sine', min: -62, max: -38, periodMs: 110000, unit: '℃' }),
    mvar('a_dp', 'a_dp', '滤后压差', { kind: 'sine', min: 20, max: 70, periodMs: 40000, unit: 'kPa' }),
  ]

  const kpi = (x: number, label: string, unit: string, varId: string, decimals: number) => [
    txt(`t_k_${label}`, x, 112, 435, 24, label, 13, '#8fa3c4'),
    nd(`c_fc_${label}`, 'flip-counter', x, 140, 435, 68, { name: label, props: { value: '0', unit, decimals }, bindings: [bd(varId, 'props.value')] }),
  ]

  // ---- 三机卡：模式 0 待机灰 / 1 加载橙 / 2 卸载蓝 ----
  const modeColor = enumMap({ '0': '#5b6b80', '1': '#ff9f43', '2': '#4d9de0' })
  const runHours = ['3,812', '2,756', '1,189']
  const specPower = ['6.1', '6.3', '5.9']
  const machines: ComponentNode[] = []
  for (let i = 0; i < 3; i++) {
    const my = 296 + i * 244
    const n = i + 1
    machines.push(
      nd(`c_mk${n}`, 'rect', 84, my, 752, 224, { name: `${n}# 机组卡`, style: { fill: '#161e2c', stroke: 'rgba(255,159,67,0.08)', strokeWidth: 1, borderRadius: 10 } }),
      nd(`c_m${n}`, 'symbol', 112, my + 48, 128, 128, {
        name: `${n}# 螺杆机`, props: { symbolId: 'pump/screw' },
        bindings: [bd(`a_m${n}`, 'style.color', 'color', modeColor)],
        tooltip: `${n}# 螺杆机 110kW 水冷\n模式：待机/加载/卸载（下方切换）`,
      }),
      nd(`c_st_m${n}`, 'state-text', 264, my + 52, 150, 34, {
        name: `${n}# 运行模式`, props: { defaultText: '待机', states: '[{"value":0,"text":"待机","color":"#94a3b8"},{"value":1,"text":"加载","color":"#e6a23c"},{"value":2,"text":"卸载","color":"#409eff"}]' },
        bindings: [bd(`a_m${n}`, 'props.value')],
      }),
      nd(`c_ms_m${n}`, 'multi-switch', 264, my + 108, 230, 44, {
        name: `${n}# 模式切换`, props: { variableId: `a_m${n}`, levels: '[{"value":0,"label":"待机"},{"value":1,"label":"加载"},{"value":2,"label":"卸载"}]' },
      }),
      txt(`t_rh${n}`, 508, my + 62, 200, 28, `累计 ${runHours[i]} h`, 13, '#c8d2e0'),
      nd(`c_sl_m${n}`, 'status-light', 688, my + 58, 24, 24, { name: `${n}# 故障灯`, style: { color: '#22c55e' }, tooltip: `${n}# 机组无故障` }),
      txt(`t_sp${n}`, 508, my + 108, 280, 28, `比功率 ${specPower[i]} kWh/Nm³`, 12, '#64748b'),
    )
  }

  const comps = [
    // ---- 顶带 ----
    nd('c_title', 'title-bar', 0, 0, 1920, 88, { name: '标题栏', props: { text: '空压站集控 · 三机一网', align: 'center' }, style: { color: '#ff9f43' } }),
    nd('c_clock', 'clock', 1548, 18, 292, 52, { props: { showDate: true, showSeconds: true, layout: 'horizontal' }, style: { color: '#c8d2e0' } }),

    // ---- KPI 条 ----
    ...kpi(60, '母管压力', 'MPa', 'a_mpr', 2),
    ...kpi(515, '总供气流量', 'Nm³/min', 'a_flow', 1),
    ...kpi(970, '加载台数', '台', 'a_nload', 0),
    ...kpi(1425, '今日能耗', 'kWh', 'a_kwh', 0),

    // ---- 中央：三机面板 ----
    nd('c_panel', 'rect', 60, 232, 800, 800, { name: '机组面板', style: { fill: '#131a26', stroke: 'rgba(255,159,67,0.10)', strokeWidth: 1, borderRadius: 12 } }),
    txt('t_sec1', 84, 252, 400, 30, '机组运行 · 加卸载联动', 15, '#8fa3c4'),
    ...machines,
    // 母管出气流动（任一机组加载即流动）
    nd('c_fb_main', 'flow-bar', 110, 966, 700, 20, {
      name: '母管出气', props: { speed: 40, showArrow: true }, style: { color: '#ff9f43' },
      bindings: [bd('a_nload', 'props.speed', 'value', onOff('40', '0'))],
      tooltip: '母管出气总管（任一机组加载即有流量）',
    }),
    txt('t_main_lbl', 110, 942, 300, 22, '母管出气 →', 11, '#b78a5a'),
    txt('t_note', 84, 996, 752, 26, '切换机组模式：机身色 / 加载台数 / 母管流动随之联动。', 12, '#5b6b80'),

    // ---- 左列 A：母管压力大表 ----
    nd('c_panelA', 'rect', 884, 232, 460, 300, { name: '压力面板', style: { fill: '#131a26', stroke: 'rgba(255,255,255,0.05)', strokeWidth: 1, borderRadius: 12 } }),
    txt('t_secA', 904, 252, 300, 30, '母管压力 MPa', 15, '#8fa3c4'),
    nd('c_g_mpr', 'gauge', 904, 286, 420, 236, { name: '母管压力表', props: { title: '', unit: 'MPa', min: 0.4, max: 1.0, precision: 2, textColor: '#c8d2e0' }, bindings: [bd('a_mpr', 'props.value')] }),

    // ---- 左列 B：气源处理 ----
    nd('c_panelB', 'rect', 884, 556, 460, 300, { name: '气源面板', style: { fill: '#131a26', stroke: 'rgba(255,255,255,0.05)', strokeWidth: 1, borderRadius: 12 } }),
    txt('t_secB', 904, 576, 300, 30, '气源处理链', 15, '#8fa3c4'),
    nd('c_tank_air', 'symbol', 904, 616, 110, 150, { name: '储气罐', props: { symbolId: 'tank/air-receiver' }, style: { color: '#8fa3c4' }, tooltip: '储气罐 2 m³ · 安全阀 1.0MPa' }),
    nd('c_dryer', 'symbol', 1030, 632, 110, 110, { name: '冷干机', props: { symbolId: 'hvac/heat-exchanger' }, style: { color: '#4d9de0' }, tooltip: '冷冻式干燥机 3.8 Nm³/min' }),
    nd('c_strainer', 'symbol', 1160, 640, 90, 90, { name: '过滤器', props: { symbolId: 'pipe-fitting/strainer' }, style: { color: '#8fa3c4' }, tooltip: 'Y 型过滤器 + C/T 级除油除尘' }),
    nd('c_vd_dew', 'var-display', 904, 784, 240, 48, { name: '压力露点', props: { prefix: '露点', unit: '℃', precision: 1 }, style: { color: '#46d5c0' }, bindings: [bd('a_dew', 'props.value')], tooltip: '压力露点 {a_dew} ℃（>-41 报警）' }),
    txt('t_dry_note', 1164, 792, 170, 40, '露点在线监测\n除油 C/T 双级', 12, '#5b6b80'),

    // ---- 左列 C：管网参数 ----
    nd('c_panelC', 'rect', 884, 880, 460, 152, { name: '管网面板', style: { fill: '#131a26', stroke: 'rgba(255,255,255,0.05)', strokeWidth: 1, borderRadius: 12 } }),
    txt('t_secC', 904, 896, 300, 26, '管网参数', 15, '#8fa3c4'),
    nd('c_vd_flow', 'var-display', 904, 928, 200, 48, { name: '流量', props: { prefix: '瞬时流量', unit: 'Nm³/min', precision: 1 }, style: { color: '#c8d2e0' }, bindings: [bd('a_flow', 'props.value')] }),
    nd('c_vd_dp', 'var-display', 1124, 928, 200, 48, { name: '滤后压差', props: { prefix: '滤后压差', unit: 'kPa', precision: 0 }, style: { color: '#c8d2e0' }, bindings: [bd('a_dp', 'props.value')] }),

    // ---- 右列 A：压力历史 ----
    nd('c_panelD', 'rect', 1368, 232, 492, 300, { name: '压力历史面板', style: { fill: '#131a26', stroke: 'rgba(255,255,255,0.05)', strokeWidth: 1, borderRadius: 12 } }),
    txt('t_secD', 1388, 252, 400, 30, '母管压力 · 历史', 15, '#8fa3c4'),
    nd('c_hc_mpr', 'history-chart', 1384, 290, 460, 230, { name: '压力历史', props: { variableId: 'a_mpr', title: '', unit: 'MPa', rangeMs: 3600000, live: true } }),

    // ---- 右列 B：瞬时流量柱状（大图） ----
    nd('c_panelE', 'rect', 1368, 556, 492, 476, { name: '流量面板', style: { fill: '#131a26', stroke: 'rgba(255,255,255,0.05)', strokeWidth: 1, borderRadius: 12 } }),
    txt('t_secE', 1388, 576, 400, 30, '瞬时流量 Nm³/min', 15, '#8fa3c4'),
    nd('c_bc_flow', 'bar-chart', 1384, 612, 460, 400, { name: '流量柱状', props: { title: '', unit: 'Nm³/min' }, bindings: [bd('a_flow', 'props.data')] }),
  ]

  return demoDoc(
    '空压站集控',
    '灰蓝能量橙主题：三机待机/加载/卸载三态联动（多档开关反控），母管压力大表呼吸往复，加载台数表达式汇总。',
    vars,
    [pg('p_main', '空压站监控', 1920, 1080, comps, { lockPan: true, bg: '#0f151f' })],
    [
      alm('a_mpr', '母管压力低', 'a_mpr', '<', 0.62, 'critical', '母管压力低：{value} MPa（阈值 0.62）'),
      alm('a_dew', '压力露点超标', 'a_dew', '>', -41, 'warn', '压力露点超标：{value} ℃（阈值 -41）'),
    ],
  )
}
