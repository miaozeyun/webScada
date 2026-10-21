/**
 * 演示案例八：无人值守换热站（行业 demo · 红蓝双温主题，行业通用语义管道色）。
 * 视觉主角：红=一次网/供水、蓝=回水的双向管网对冲流动；气候补偿设定曲线；
 * 供水温度超限触发条件弹框（含一键降阀位反控）。
 */
import { alm, bd, demoDoc, enumMap, mvar, nd, onOff, pg, rangeMap, txt, vvar } from './shared'
import type { ComponentNode } from '@/types/doc'

export function buildHeatingDoc(): ReturnType<typeof demoDoc> {
  // ---- 变量 ----
  const vars = [
    mvar('h_t1s', 'h_t1s', '一次网供水温度', { kind: 'sine', min: 88, max: 96, periodMs: 300000, unit: '℃' }),
    mvar('h_t2s', 'h_t2s', '二次网供水温度', { kind: 'sine', min: 46, max: 52, periodMs: 160000, unit: '℃', precision: 1 }),
    mvar('h_t2r', 'h_t2r', '二次网回水温度', { kind: 'sine', min: 38, max: 44, periodMs: 200000, unit: '℃', precision: 1 }),
    mvar('h_f1', 'h_f1', '一次网流量', { kind: 'sine', min: 10, max: 18, periodMs: 90000, unit: 't/h', precision: 1 }),
    vvar('h_ql', 'h_ql', '瞬时热负荷', 'round(h_f1 * (h_t1s - h_t2r) * 0.00489, 2)', { unit: 'GJ/h', precision: 2 }),
    mvar('h_dp', 'h_dp', '二网压差', { kind: 'sine', min: 0.18, max: 0.52, periodMs: 70000, unit: 'MPa' }),
    mvar('h_vpos', 'h_vpos', '电动阀阀位', { kind: 'hold', def: 65, unit: '%', writable: true }),
    mvar('h_p1', 'h_p1', '循环泵 1#', { kind: 'hold', def: 1, writable: true }),
    mvar('h_p2', 'h_p2', '循环泵 2#', { kind: 'square', min: 0, max: 1, periodMs: 300000 }),
    mvar('h_mw', 'h_mw', '补水量', { kind: 'random', min: 0.2, max: 1.8, intervalMs: 5000, unit: 'm³/h' }),
  ]
  // 楼栋供水温度 + 负荷率（周期错开制造波动层次）
  const bIds: string[] = []
  const blIds: string[] = []
  const bNames = ['1# 住宅楼', '2# 住宅楼', '商务楼 A', '商务楼 B', '幼儿园']
  const bRanges = [[44, 49], [43.5, 48.5], [44.5, 49.5], [43, 48], [45, 50]]
  for (let i = 0; i < 5; i++) {
    bIds.push(`h_b${i + 1}`)
    blIds.push(`h_bl${i + 1}`)
    vars.push(mvar(`h_b${i + 1}`, `h_b${i + 1}`, `${bNames[i]} 供水温度`, { kind: 'sine', min: bRanges[i][0], max: bRanges[i][1], periodMs: 16000 + i * 3000, unit: '℃', precision: 1 }))
    vars.push(mvar(`h_bl${i + 1}`, `h_bl${i + 1}`, `${bNames[i]} 负荷率`, { kind: 'sine', min: 55, max: 95, periodMs: 40000 + i * 7000, unit: '%' }))
  }

  // ---- 顶部 KPI 条 ----
  const kpi = (x: number, label: string, unit: string, varId: string, decimals: number) => [
    txt(`t_k_${label}`, x, 112, 435, 24, label, 13, '#8fa3c4'),
    nd(`c_fc_${label}`, 'flip-counter', x, 140, 435, 68, { name: label, props: { value: '0', unit, decimals }, bindings: [bd(varId, 'props.value')] }),
  ]

  // ---- 楼栋支路卡 ----
  const buildings: ComponentNode[] = []
  for (let i = 0; i < 5; i++) {
    const by = 296 + i * 136
    buildings.push(
      nd(`c_bc${i}`, 'rect', 760, by, 370, 120, { name: bNames[i], style: { fill: '#1f2937', stroke: 'rgba(255,255,255,0.04)', strokeWidth: 1, borderRadius: 8 } }),
      txt(`t_bc${i}`, 776, by + 12, 160, 24, bNames[i], 14, '#d7e0ee'),
      nd(`c_bsl${i}`, 'status-light', 1106, by + 14, 18, 18, { name: `${bNames[i]} 通讯`, style: { color: '#22c55e' } }),
      nd(`c_bvd${i}`, 'var-display', 776, by + 46, 170, 44, {
        name: `${bNames[i]} 供水`, props: { prefix: '供水', unit: '℃', precision: 1 }, style: { color: '#f0a58f' },
        bindings: [bd(bIds[i], 'props.value')], tooltip: `${bNames[i]} 供水温度 {h_b${i + 1}} ℃`,
      }),
      nd(`c_bpr${i}`, 'progress', 958, by + 54, 156, 22, { name: `${bNames[i]} 负荷率`, props: { percent: 0, precision: 0 }, bindings: [bd(blIds[i], 'props.percent')] }),
    )
  }

  const comps = [
    // ---- 顶带 ----
    nd('c_title', 'title-bar', 0, 0, 1920, 88, { name: '标题栏', props: { text: '无人值守换热站 · 2# 机组', align: 'center' }, style: { color: '#f0644c' } }),
    nd('c_clock', 'clock', 1548, 18, 292, 52, { props: { showDate: true, showSeconds: true, layout: 'horizontal' }, style: { color: '#c8d2e0' } }),

    // ---- KPI 条 ----
    ...kpi(60, '二次网供水温度', '℃', 'h_t2s', 1),
    ...kpi(515, '二次网回水温度', '℃', 'h_t2r', 1),
    ...kpi(970, '一次网流量', 't/h', 'h_f1', 1),
    ...kpi(1425, '瞬时热负荷', 'GJ/h', 'h_ql', 2),

    // ---- 主面板：板换工艺（左 62%） ----
    nd('c_panel', 'rect', 60, 232, 1130, 800, { name: '工艺面板', style: { fill: '#1a2333', stroke: 'rgba(240,100,76,0.10)', strokeWidth: 1, borderRadius: 12 } }),
    txt('t_sec1', 84, 252, 400, 30, '板式换热机组 · 二网循环', 15, '#8fa3c4'),

    // 供水温度报警灯
    nd('c_alm_t2s', 'status-light', 84, 296, 26, 26, {
      name: '供水温度报警灯',
      anim: { blink: { enabled: false, intervalMs: 600 } },
      bindings: [
        bd('h_t2s', 'style.color', 'color', rangeMap({ max: 51.8, value: '#22c55e' }, { min: 51.8, value: '#ef4444' })),
        bd('h_t2s', 'anim.blinkOn', 'value', rangeMap({ max: 51.8, value: false }, { min: 51.8, value: true })),
      ],
      tooltip: '二次供水温度 {h_t2s} ℃（>51.8 报警并自动弹框）',
    }),
    txt('t_alm', 118, 298, 160, 22, '供水温度监视', 12, '#64748b'),

    // 一次网：红进（横管→电动阀→延伸→竖管→板换）/ 蓝回（板换→竖管→横管回）
    txt('t_p1_in', 84, 322, 160, 22, '一次网 95℃ →', 11, '#c98a80'),
    nd('c_fb_p1', 'flow-bar', 84, 346, 166, 18, { name: '一次网供水管', props: { speed: 14, showArrow: true }, style: { color: '#f0644c' }, bindings: [bd('h_f1', 'props.speed')] }),
    nd('c_v_reg', 'symbol', 250, 315, 82, 82, {
      name: '电动调节阀', props: { symbolId: 'valve/motorized' }, style: { color: '#f0644c' },
      tooltip: '电动调节阀 阀位 {h_vpos}%（下发区可设定）',
    }),
    nd('c_fb_p1m', 'flow-bar', 332, 346, 268, 18, { name: '一次网供水管（阀后）', props: { speed: 14, showArrow: false }, style: { color: '#f0644c' }, bindings: [bd('h_f1', 'props.speed')] }),
    nd('c_vd_vpos', 'var-display', 346, 296, 200, 44, { name: '阀位', props: { prefix: '阀位', unit: '%', precision: 0 }, style: { color: '#f0a58f' }, bindings: [bd('h_vpos', 'props.value')] }),
    nd('c_fb_p1v', 'flow-bar', 600, 364, 18, 106, { name: '一次进板换', props: { speed: 14, vertical: true, showArrow: false }, style: { color: '#f0644c' }, bindings: [bd('h_f1', 'props.speed')] }),
    nd('c_hex', 'symbol', 530, 470, 150, 150, { name: '板式换热器', props: { symbolId: 'hvac/heat-exchanger' }, style: { color: '#c9a17e' }, tooltip: '板式换热器 BR0.5-60\n一次侧 95/48℃ · 二次侧 49/41℃' }),
    nd('c_fb_p1r', 'flow-bar', 660, 364, 18, 106, { name: '一次回水竖管', props: { speed: -12, vertical: true, showArrow: false }, style: { color: '#4d9de0' } }),
    nd('c_fb_p1rh', 'flow-bar', 400, 410, 278, 18, { name: '一次回水管', props: { speed: -12, showArrow: true }, style: { color: '#4d9de0' } }),
    txt('t_p1_out', 404, 386, 160, 22, '← 一次回水 48℃', 11, '#8fb0cd'),

    // 二次网：分水器(橙) → 泵×2 → 楼栋；楼栋 → 集水器(蓝)
    nd('c_man_sup', 'symbol', 84, 566, 150, 80, { name: '分水器', props: { symbolId: 'tank/horizontal' }, style: { color: '#f0855c' }, tooltip: '分水器 DN150' }),
    txt('t_p2_in', 246, 566, 140, 22, '二次供水 →', 11, '#f0a58f'),
    nd('c_fb_s1', 'flow-bar', 234, 590, 120, 18, { name: '二次供水管', props: { speed: 70, showArrow: false }, style: { color: '#f0855c' }, bindings: [bd('h_p1', 'props.speed', 'value', onOff('70', '0'))] }),
    nd('c_pump1', 'pump', 354, 568, 80, 80, {
      name: '循环泵 1#', style: { color: '#f0855c' },
      anim: { rotate: { enabled: true, clockwise: true, periodMs: 2200 } },
      bindings: [bd('h_p1', 'anim.rotateOn'), bd('h_p1', 'style.color', 'color', enumMap({ '1': '#f0855c', '0': '#5b6b80' }))],
      tooltip: '循环泵 1#（变频 42Hz）\n运行状态：{h_p1}',
    }),
    nd('c_pump2', 'pump', 444, 568, 80, 80, {
      name: '循环泵 2#', style: { color: '#f0855c' },
      anim: { rotate: { enabled: true, clockwise: true, periodMs: 2200 } },
      bindings: [bd('h_p2', 'anim.rotateOn'), bd('h_p2', 'style.color', 'color', enumMap({ '1': '#f0855c', '0': '#5b6b80' }))],
      tooltip: '循环泵 2#（备用，自动切换）\n运行状态：{h_p2}',
    }),
    nd('c_st_p1', 'state-text', 350, 656, 96, 26, {
      name: '泵1状态', props: { defaultText: '停止', states: '[{"value":0,"text":"停止","color":"#94a3b8"},{"value":1,"text":"运行","color":"#67c23a"}]' },
      bindings: [bd('h_p1', 'props.value')],
    }),
    nd('c_st_p2', 'state-text', 450, 656, 96, 26, {
      name: '泵2状态', props: { defaultText: '停止', states: '[{"value":0,"text":"停止","color":"#94a3b8"},{"value":1,"text":"运行","color":"#67c23a"}]' },
      bindings: [bd('h_p2', 'props.value')],
    }),
    nd('c_fb_s2', 'flow-bar', 524, 590, 236, 18, { name: '供水总管', props: { speed: 70, showArrow: true }, style: { color: '#f0644c' }, bindings: [bd('h_p1', 'props.speed', 'value', onOff('70', '0'))] }),
    nd('c_lk_hex', 'line', 604, 590, 4, 30, { name: '板换二次连接管', style: { stroke: '#f0855c', strokeWidth: 4 } }),
    nd('c_fb_r1', 'flow-bar', 234, 670, 526, 18, { name: '二次回水总管', props: { speed: -60, showArrow: true }, style: { color: '#4d9de0' }, bindings: [bd('h_p1', 'props.speed', 'value', onOff('-60', '0'))] }),
    txt('t_p2_out', 246, 632, 140, 22, '← 二次回水', 11, '#8fb0cd'),
    nd('c_man_ret', 'symbol', 84, 656, 150, 80, { name: '集水器', props: { symbolId: 'tank/horizontal' }, style: { color: '#4d9de0' }, tooltip: '集水器 DN150' }),

    ...buildings,

    // ---- 底部：定压补水 + 反控 ----
    txt('t_sec2', 84, 776, 200, 26, '定压补水', 13, '#8fa3c4'),
    nd('c_tank_soft', 'symbol', 84, 812, 90, 120, { name: '软水箱', props: { symbolId: 'tank/vertical' }, style: { color: '#4d9de0' }, tooltip: '软水箱 2 m³' }),
    nd('c_p_dose', 'symbol', 200, 846, 70, 70, { name: '补水泵', props: { symbolId: 'wtp/dosing-pump' }, style: { color: '#46d5c0' }, tooltip: '变频补水泵（定压 0.38MPa）' }),
    nd('c_vd_mw', 'var-display', 290, 856, 180, 44, { name: '补水量', props: { prefix: '补水量', unit: 'm³/h', precision: 2 }, style: { color: '#c8d2e0' }, bindings: [bd('h_mw', 'props.value')] }),
    nd('c_vd_dpx', 'var-display', 500, 812, 200, 48, { name: '二网压差（定压监视）', props: { prefix: '二网压差', unit: 'MPa', precision: 2 }, style: { color: '#c8d2e0' }, bindings: [bd('h_dp', 'props.value')] }),
    txt('t_dp_note', 500, 868, 200, 26, '定压点 0.38 MPa', 12, '#5b6b80'),
    nd('c_in_vpos', 'input-cmd', 84, 952, 300, 44, { name: '阀位设定', props: { variableId: 'h_vpos', placeholder: '目标阀位', unit: '%', buttonText: '下发', clearAfter: true } }),
    nd('c_sw_p1', 'switch', 400, 952, 210, 44, { name: '循环泵 1#', props: { variableId: 'h_p1', onValue: 1, offValue: 0, confirm: true, label: '循环泵 1#' } }),
    txt('t_hint', 630, 956, 500, 40, '悬停设备查看实时参数 · 供水 >51.8℃ 自动弹出处置弹框', 12, '#5b6b80'),

    // ---- 条件弹框：供水超限处置 ----
    nd('grp_alarm', 'group', 320, 560, 420, 260, {
      name: '供水温度超限处置',
      visible: false,
      popup: { style: 'dialog', title: '二次供水温度超限', triggerExpr: 'h_t2s > 51.8' },
      children: [
        txt('t_pop_body', 24, 56, 372, 88, '二次供水温度 {h_t2s} ℃ 超过 51.8℃ 阈值。\n建议将电动调节阀阀位降至 40%，\n并关注楼栋散热末端运行工况。', 13, '#d7e0ee'),
        nd('btn_pop_v', 'button', 24, 168, 180, 44, {
          name: '降阀位', props: { text: '阀位降至 40%' },
          events: [{ trigger: 'click', actions: [{ type: 'writeVar', variableId: 'h_vpos', value: '40' }, { type: 'hidePopup', targetId: 'grp_alarm' }] }],
        }),
        nd('btn_pop_close', 'button', 216, 168, 180, 44, {
          name: '关闭', props: { text: '知道了' },
          events: [{ trigger: 'click', actions: [{ type: 'hidePopup', targetId: 'grp_alarm' }] }],
        }),
      ],
    }),

    // ---- 右列 A：温度与热量 ----
    nd('c_panelA', 'rect', 1214, 232, 646, 300, { name: '温度面板', style: { fill: '#1a2333', stroke: 'rgba(255,255,255,0.05)', strokeWidth: 1, borderRadius: 12 } }),
    txt('t_secA', 1234, 252, 300, 30, '供回水温度 · 热量', 15, '#8fa3c4'),
    nd('c_vd_t2s', 'var-display', 1234, 292, 290, 76, { name: '二次供水', props: { prefix: '二次供水', unit: '℃', precision: 1 }, style: { color: '#f0644c', fontSize: 26, fontWeight: 700 }, bindings: [bd('h_t2s', 'props.value')] }),
    nd('c_vd_t2r', 'var-display', 1544, 292, 290, 76, { name: '二次回水', props: { prefix: '二次回水', unit: '℃', precision: 1 }, style: { color: '#4d9de0', fontSize: 26, fontWeight: 700 }, bindings: [bd('h_t2r', 'props.value')] }),
    nd('c_vd_dp', 'var-display', 1234, 384, 290, 56, { name: '二网压差', props: { prefix: '二网压差', unit: 'MPa', precision: 2 }, style: { color: '#c8d2e0' }, bindings: [bd('h_dp', 'props.value')] }),
    nd('c_vd_ql', 'var-display', 1544, 384, 290, 56, { name: '热负荷', props: { prefix: '瞬时热负荷', unit: 'GJ/h', precision: 2 }, style: { color: '#c8d2e0' }, bindings: [bd('h_ql', 'props.value')] }),
    txt('t_ql_note', 1234, 452, 600, 60, '热负荷 = 一次流量 × 一次温差 × 0.00489（虚拟变量表达式，随流量/温度实时联动）', 12, '#5b6b80'),

    // ---- 右列 B：气候补偿曲线（大图） ----
    nd('c_panelB', 'rect', 1214, 556, 646, 476, { name: '气候补偿面板', style: { fill: '#1a2333', stroke: 'rgba(255,255,255,0.05)', strokeWidth: 1, borderRadius: 12 } }),
    txt('t_secB', 1234, 576, 500, 30, '气候补偿 · 二次供水温度设定曲线', 15, '#8fa3c4'),
    nd('c_lc_cc', 'line-chart', 1230, 612, 614, 400, {
      name: '气候补偿曲线',
      props: { title: '', unit: '℃', data: [45, 45, 46, 47, 49, 51, 53, 55, 57, 58, 58, 57, 55, 53, 51, 50, 49, 48, 47, 47, 46, 46, 45, 45] },
    }),
  ]

  return demoDoc(
    '无人值守换热站',
    '红蓝双温主题：红=一次网/供水、蓝=回水的语义管网流动；气候补偿设定曲线；供水超限条件弹框一键降阀位。',
    vars,
    [pg('p_main', '换热站监控', 1920, 1080, comps, { lockPan: true, bg: '#141b26' })],
    [
      alm('a_t2s', '二次供水温度超限', 'h_t2s', '>', 51.8, 'critical', '二次供水温度超限：{value} ℃（阈值 51.8）'),
      alm('a_f1', '一次网流量偏低', 'h_f1', '<', 12.5, 'warn', '一次网流量偏低：{value} t/h'),
    ],
  )
}
