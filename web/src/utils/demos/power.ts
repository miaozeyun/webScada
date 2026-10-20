/**
 * 演示案例二：110kV 变电站单线图（电力系统）。
 * 覆盖：二次接线图元全家桶（PT/断路器/CT/隔离/接地/变压器）/ 母线 / 状态变色 /
 * 分闸告警闪烁 / 仪表盘 / 右键分合闸菜单 / 远程操作开关（confirm）/ 报警。
 */
import { alm, bd, demoDoc, enumMap, mvar, nd, pg, txt } from './shared'

export function buildPowerDoc(): ReturnType<typeof demoDoc> {
  const V = {
    vbus: 'v_vbus', ia: 'v_ia', ib: 'v_ib', ic: 'v_ic', tt: 'v_tt',
    cb1: 'v_cb1', cb2: 'v_cb2', cb3: 'v_cb3', iso: 'v_iso', load: 'v_load',
  }

  const vars = [
    mvar(V.vbus, 'pwr.vbus', '母线电压', { kind: 'sine', min: 10.1, max: 10.6, periodMs: 30000, unit: 'kV' }),
    mvar(V.ia, 'pwr.ia', 'A 相电流', { kind: 'random', min: 80, max: 260, intervalMs: 2000, unit: 'A' }),
    mvar(V.ib, 'pwr.ib', 'B 相电流', { kind: 'random', min: 80, max: 260, intervalMs: 2200, unit: 'A' }),
    mvar(V.ic, 'pwr.ic', 'C 相电流', { kind: 'random', min: 80, max: 260, intervalMs: 2400, unit: 'A' }),
    mvar(V.tt, 'pwr.tt', '主变温度', { kind: 'sine', min: 55, max: 95, periodMs: 45000, unit: '℃' }),
    mvar(V.cb1, 'pwr.cb1', '进线断路器 1', { kind: 'hold', def: 1, writable: true }),
    mvar(V.cb2, 'pwr.cb2', '出线断路器 2', { kind: 'square', min: 0, max: 1, periodMs: 16000, duty: 0.85 }),
    mvar(V.cb3, 'pwr.cb3', '出线断路器 3', { kind: 'hold', def: 0, writable: true }),
    mvar(V.iso, 'pwr.iso', '隔离开关', { kind: 'hold', def: 1, writable: true }),
    mvar(V.load, 'pwr.load', '1号负荷', { kind: 'square', min: 0, max: 1, periodMs: 7000 }),
  ]

  // 连接线（竖线段）
  const vline = (id: string, x: number, y: number, len: number): ReturnType<typeof nd> =>
    nd(id, 'line', x, y, 2, len, { name: '连线', style: { stroke: '#94a3b8', strokeWidth: 2 } })

  const comps = [
    txt('t_title', 60, 22, 900, 54, '110kV 变电站 · 单线图监控', 30, '#e2e8f0'),
    nd('c_clock', 'clock', 1560, 22, 300, 58, { props: {}, style: { color: '#e2e8f0' } }),
    txt('t_sec1', 60, 100, 200, 28, '单线图', 16, '#94a3b8'),

    // ---- 进线：PT → CB1 → CT → 母线 ----
    txt('t_in', 105, 150, 100, 24, '110kV 进线', 13, '#cbd5e1'),
    nd('c_pt', 'pt', 120, 180, 70, 100, { name: '电压互感器', style: { color: '#94a3b8' }, tooltip: '进线 PT（电压互感器）' }),
    vline('l0', 154, 130, 50),
    vline('l1', 154, 280, 40),
    nd('c_cb1', 'breaker', 250, 230, 60, 80, {
      name: '进线断路器 1',
      bindings: [bd(V.cb1, 'style.color', 'color', enumMap({ '1': '#ef4444', '0': '#64748b' }))],
      tooltip: '进线断路器 QF1（右键操作）\n状态：{pwr.cb1}',
      events: [{ trigger: 'contextmenu', actions: [{ type: 'showPopup', targetId: 'grp_cb_menu' }] }],
    }),
    vline('l2', 279, 180, 50),
    vline('l3', 279, 310, 40),
    nd('c_ct', 'ct', 370, 225, 70, 90, { name: '电流互感器', style: { color: '#94a3b8' }, tooltip: '进线 CT（电流互感器）' }),
    vline('l4', 404, 180, 45),
    vline('l5', 404, 315, 40),
    // 母线
    nd('c_bus', 'rect', 470, 258, 640, 12, { name: '10kV 母线', style: { fill: '#f59e0b', borderRadius: 2 } }),
    txt('t_bus', 470, 232, 200, 24, '10kV 母线', 13, '#fbbf24'),

    // ---- 出线 1：CB → 电机负荷 ----
    vline('l6', 549, 270, 50),
    nd('c_cbL1', 'breaker', 520, 320, 60, 80, {
      name: '出线断路器（负荷）',
      bindings: [bd(V.load, 'style.color', 'color', enumMap({ '1': '#ef4444', '0': '#64748b' }))],
      tooltip: '1号负荷出线\n状态：{pwr.load}',
    }),
    vline('l7', 549, 400, 40),
    nd('c_motor', 'motor', 505, 440, 90, 90, {
      name: '1号负荷（电机）',
      anim: { rotate: { enabled: true, clockwise: true, periodMs: 2200 } },
      bindings: [bd(V.load, 'anim.rotateOn'), bd(V.load, 'style.color', 'color', enumMap({ '1': '#22c55e', '0': '#64748b' }))],
    }),
    nd('c_stL1', 'state-text', 480, 545, 140, 32, {
      name: '负荷状态', props: { defaultText: '停止', states: '[{"value":0,"text":"停机","color":"#94a3b8"},{"value":1,"text":"运行 1480rpm","color":"#67c23a"}]' },
      bindings: [bd(V.load, 'props.value')],
    }),

    // ---- 出线 2：CB（分闸告警闪烁）→ 隔离 → 接地 ----
    vline('l8', 729, 270, 50),
    nd('c_cb2', 'breaker', 700, 320, 60, 80, {
      name: '出线断路器 2',
      anim: { blink: { enabled: false, intervalMs: 500 } },
      bindings: [
        bd(V.cb2, 'style.color', 'color', enumMap({ '1': '#ef4444', '0': '#64748b' })),
        bd(V.cb2, 'anim.blinkOn', 'value', enumMap({ '0': true, '1': false })),
      ],
      tooltip: '出线断路器 QF2（分闸时闪烁告警）\n状态：{pwr.cb2}',
    }),
    vline('l9', 729, 400, 40),
    nd('c_iso', 'isolator', 700, 440, 60, 80, {
      name: '隔离开关 QS',
      bindings: [bd(V.iso, 'style.color', 'color', enumMap({ '1': '#f59e0b', '0': '#64748b' }))],
      tooltip: '隔离开关（可远程操作）\n状态：{pwr.iso}',
    }),
    vline('l10', 729, 520, 40),
    nd('c_gnd', 'ground', 704, 560, 50, 70, { name: '接地', style: { color: '#94a3b8' } }),

    // ---- 出线 3：CB → 变压器 → 负载 ----
    vline('l11', 909, 270, 50),
    nd('c_cb3', 'breaker', 880, 320, 60, 80, {
      name: '出线断路器 3',
      bindings: [bd(V.cb3, 'style.color', 'color', enumMap({ '1': '#ef4444', '0': '#64748b' }))],
      tooltip: '出线断路器 QF3（可远程操作）\n状态：{pwr.cb3}',
    }),
    vline('l12', 909, 400, 40),
    nd('c_tr', 'transformer', 875, 440, 70, 110, {
      name: '主变压器',
      bindings: [bd(V.tt, 'style.color', 'color', { kind: 'range', bands: [{ max: 85, value: '#94a3b8' }, { min: 85, value: '#ef4444' }] })],
      tooltip: '主变压器 T1\n绕组温度：{pwr.tt} ℃（>85 告警）',
    }),
    txt('t_tr_load', 855, 560, 120, 26, '→ 0.4kV 侧', 13, '#cbd5e1'),

    // ---- 断路器状态汇总 ----
    txt('t_sec2', 60, 620, 300, 28, '断路器状态', 16, '#94a3b8'),
    nd('c_st1', 'state-text', 60, 654, 170, 34, { name: 'QF1', props: { defaultText: '--', states: '[{"value":0,"text":"QF1 分闸","color":"#94a3b8"},{"value":1,"text":"QF1 合闸","color":"#ef4444"}]' }, bindings: [bd(V.cb1, 'props.value')] }),
    nd('c_st2', 'state-text', 250, 654, 170, 34, { name: 'QF2', props: { defaultText: '--', states: '[{"value":0,"text":"QF2 分闸⚠","color":"#e6a23c"},{"value":1,"text":"QF2 合闸","color":"#ef4444"}]' }, bindings: [bd(V.cb2, 'props.value')] }),
    nd('c_st3', 'state-text', 440, 654, 170, 34, { name: 'QF3', props: { defaultText: '--', states: '[{"value":0,"text":"QF3 分闸","color":"#94a3b8"},{"value":1,"text":"QF3 合闸","color":"#ef4444"}]' }, bindings: [bd(V.cb3, 'props.value')] }),
    nd('c_st4', 'state-text', 630, 654, 170, 34, { name: 'QS', props: { defaultText: '--', states: '[{"value":0,"text":"QS 分闸","color":"#94a3b8"},{"value":1,"text":"QS 合闸","color":"#f59e0b"}]' }, bindings: [bd(V.iso, 'props.value')] }),

    // ---- 右侧遥测区 ----
    txt('t_sec3', 1180, 100, 300, 28, '遥测', 16, '#94a3b8'),
    nd('c_g_v', 'gauge', 1180, 136, 220, 200, { name: '母线电压', props: { title: '母线电压', unit: 'kV', min: 9, max: 12, textColor: '#e2e8f0' }, bindings: [bd(V.vbus, 'props.value')] }),
    nd('c_g_a', 'gauge', 1410, 136, 220, 200, { name: 'A 相电流', props: { title: 'IA', unit: 'A', min: 0, max: 300, textColor: '#e2e8f0' }, bindings: [bd(V.ia, 'props.value')] }),
    nd('c_g_b', 'gauge', 1180, 350, 220, 200, { name: 'B 相电流', props: { title: 'IB', unit: 'A', min: 0, max: 300, textColor: '#e2e8f0' }, bindings: [bd(V.ib, 'props.value')] }),
    nd('c_g_c', 'gauge', 1410, 350, 220, 200, { name: 'C 相电流', props: { title: 'IC', unit: 'A', min: 0, max: 300, textColor: '#e2e8f0' }, bindings: [bd(V.ic, 'props.value')] }),
    nd('c_vd_tt', 'var-display', 1180, 566, 220, 56, {
      name: '主变温度',
      props: { prefix: '主变温度', unit: '℃', precision: 1 },
      style: { color: '#e2e8f0' },
      anim: { blink: { enabled: false, intervalMs: 700 } },
      bindings: [
        bd(V.tt, 'props.value'),
        bd(V.tt, 'anim.blinkOn', 'value', { kind: 'range', bands: [{ max: 85, value: false }, { min: 85, value: true }] }),
      ],
      tooltip: '主变压器绕组温度\n超过 85℃ 闪烁告警',
    }),
    nd('c_hist', 'history-chart', 1180, 636, 450, 220, { name: '母线电压历史', props: { variableId: V.vbus, title: '母线电压历史', unit: 'kV', rangeMs: 3600000 } }),

    // ---- 遥控区 ----
    txt('t_sec4', 60, 710, 300, 28, '遥控操作（写前确认）', 16, '#94a3b8'),
    nd('c_sw1', 'switch', 60, 744, 240, 44, { name: 'QF1 分合闸', props: { variableId: V.cb1, onValue: 1, offValue: 0, confirm: true, label: '进线 QF1' } }),
    nd('c_sw3', 'switch', 320, 744, 240, 44, { name: 'QF3 分合闸', props: { variableId: V.cb3, onValue: 1, offValue: 0, confirm: true, label: '出线 QF3' } }),
    nd('c_swi', 'switch', 580, 744, 240, 44, { name: 'QS 分合', props: { variableId: V.iso, onValue: 1, offValue: 0, confirm: true, label: '隔离 QS' } }),
    txt('t_hint', 60, 800, 520, 26, '提示：右键进线断路器 QF1 可弹出操作菜单；QF2 分闸时单线图闪烁告警', 13, '#64748b'),

    // ---- 右键操作菜单（menu 式弹框） ----
    nd('grp_cb_menu', 'group', 320, 210, 210, 190, {
      name: '断路器操作菜单',
      popup: { style: 'menu', title: '进线断路器 QF1', triggerExpr: null },
      style: { fill: '#1e293b', stroke: '#475569', borderRadius: 6 },
      children: [
        nd('m_on', 'button', 16, 16, 178, 40, { name: '合闸', props: { text: '⚡ 合闸' }, events: [{ trigger: 'click', actions: [{ type: 'writeVar', variableId: V.cb1, value: '1' }, { type: 'hidePopup', targetId: 'grp_cb_menu' }] }] }),
        nd('m_off', 'button', 16, 64, 178, 40, { name: '分闸', props: { text: '⏸ 分闸' }, events: [{ trigger: 'click', actions: [{ type: 'writeVar', variableId: V.cb1, value: '0' }, { type: 'hidePopup', targetId: 'grp_cb_menu' }] }] }),
        nd('m_lock', 'button', 16, 112, 178, 40, { name: '闭锁 QF3', props: { text: '🔒 远方闭锁 QF3' }, events: [{ trigger: 'click', actions: [{ type: 'writeVar', variableId: V.cb3, value: '0' }, { type: 'hidePopup', targetId: 'grp_cb_menu' }] }] }),
      ],
    }),
  ]

  return demoDoc(
    '案例二 · 电力系统',
    '变电站单线图：二次接线图元（PT/断路器/CT/隔离/接地/变压器）、母线、分闸闪烁告警、仪表遥测、右键分合闸菜单、远程遥控（写前确认）',
    vars,
    [pg('pg_power', '单线图', 1920, 1080, comps, { lockPan: true })],
    [
      alm('a_tt', '主变温度超高', V.tt, '>', 85, 'critical', '{label} = {value} ℃（阈值 {threshold}），检查冷却系统'),
      alm('a_ia', 'A 相过流', V.ia, '>', 245, 'warn', '{label} = {value} A（阈值 {threshold}）'),
      alm('a_vbus_lo', '母线欠压', V.vbus, '<', 10.2, 'warn', '{label} = {value} kV（阈值 {threshold}）'),
    ],
  )
}
