/**
 * 演示案例一：智慧污水处理系统（综合旗舰）。
 * 覆盖：水池液位动画 / 泵旋转启停 / 管道流动（变量控速）/ 状态文本 / 仪表盘 /
 * 趋势+历史图表 / 报警 / 悬停信息 / 右键菜单弹框 / 条件弹框 / 输入框指令 / 开关反控。
 */
import { alm, bd, demoDoc, enumMap, mvar, nd, onOff, pg, rangeMap, txt } from './shared'

export function buildWwtpDoc(): ReturnType<typeof demoDoc> {
  const V = {
    inflow: 'v_inflow', ph: 'v_ph', dox: 'v_dox', cod: 'v_cod',
    lg: 'v_lv_grid', lr: 'v_lv_reg', lb: 'v_lv_bio', lc: 'v_lv_clear',
    pump1: 'v_pump1', pump2: 'v_pump2', feeder: 'v_feeder', valve: 'v_valve',
    emerg: 'v_emerg', phSet: 'v_ph_set',
  }

  const vars = [
    mvar(V.inflow, 'wwtp.inflow', '进水流量', { kind: 'sine', min: 240, max: 780, periodMs: 40000, unit: 'm³/h' }),
    mvar(V.ph, 'wwtp.ph', '进水 pH', { kind: 'random', min: 6.5, max: 9.8, intervalMs: 2000 }),
    mvar(V.dox, 'wwtp.dox', '溶解氧 DO', { kind: 'random', min: 1.5, max: 4.5, intervalMs: 1500, unit: 'mg/L' }),
    mvar(V.cod, 'wwtp.cod', '出水 COD', { kind: 'random', min: 28, max: 55, intervalMs: 3000, unit: 'mg/L' }),
    mvar(V.lg, 'wwtp.lv_grid', '格栅池液位', { kind: 'sine', min: 30, max: 85, periodMs: 50000 }),
    mvar(V.lr, 'wwtp.lv_reg', '调节池液位', { kind: 'sine', min: 35, max: 80, periodMs: 60000 }),
    mvar(V.lb, 'wwtp.lv_bio', '生化池液位', { kind: 'sine', min: 40, max: 75, periodMs: 70000 }),
    mvar(V.lc, 'wwtp.lv_clear', '清水池液位', { kind: 'sine', min: 30, max: 90, periodMs: 55000 }),
    // 1 号泵为可控量（hold 回环），演示右键菜单/弹框内反控；2 号泵自动方波运行
    mvar(V.pump1, 'wwtp.pump1', '1号提升泵', { kind: 'hold', def: 1, writable: true }),
    mvar(V.pump2, 'wwtp.pump2', '2号提升泵', { kind: 'square', min: 0, max: 1, periodMs: 11000 }),
    mvar(V.feeder, 'wwtp.feeder', '加药泵', { kind: 'square', min: 0, max: 1, periodMs: 6000, duty: 0.7 }),
    mvar(V.valve, 'wwtp.valve_out', '出水阀', { kind: 'square', min: 0, max: 1, periodMs: 9000 }),
    mvar(V.emerg, 'wwtp.emerg', '应急排阀', { kind: 'hold', def: 0, writable: true }),
    mvar(V.phSet, 'wwtp.ph_set', 'pH 中和设定', { kind: 'hold', def: 7.2, writable: true }),
  ]

  const comps = [
    // ---- 标题区 ----
    txt('t_title', 60, 22, 820, 54, '智慧污水处理厂 · 工艺监控总览', 30, '#e2e8f0'),
    nd('c_clock', 'clock', 1500, 22, 360, 58, { props: { showDate: true, showSeconds: true, layout: 'horizontal' }, style: { color: '#e2e8f0' } }),
    txt('t_sec1', 60, 104, 240, 30, '工艺流程', 16, '#94a3b8'),

    // ---- 工艺流程（左→右：格栅→调节→生化→清水→出水） ----
    txt('t_grid', 95, 148, 120, 26, '格栅池', 14, '#cbd5e1'),
    nd('c_tank_grid', 'tank', 95, 178, 125, 150, {
      name: '格栅池', bindings: [bd(V.lg, 'props.percent')], style: { color: '#38bdf8' },
      tooltip: '格栅池液位 {wwtp.lv_grid} %',
    }),
    nd('c_fb1', 'flow-bar', 228, 240, 110, 24, { name: '提升管流', props: { speed: 80, showArrow: true }, bindings: [bd(V.pump1, 'props.speed', 'value', onOff('80', '0'))] }),
    nd('c_pump1', 'pump', 240, 290, 90, 90, {
      name: '1号提升泵', style: { color: '#38bdf8' },
      anim: { rotate: { enabled: true, clockwise: true, periodMs: 2500 } },
      bindings: [bd(V.pump1, 'anim.rotateOn'), bd(V.pump1, 'style.color', 'color', enumMap({ '1': '#22c55e', '0': '#64748b' }))],
      tooltip: '1号提升泵（右键操作）\n运行状态：{wwtp.pump1}',
      events: [{ trigger: 'contextmenu', actions: [{ type: 'showPopup', targetId: 'grp_pump_menu' }] }],
    }),
    nd('c_pump2', 'pump', 240, 400, 90, 90, {
      name: '2号提升泵', style: { color: '#38bdf8' },
      anim: { rotate: { enabled: true, clockwise: true, periodMs: 2500 } },
      bindings: [bd(V.pump2, 'anim.rotateOn'), bd(V.pump2, 'style.color', 'color', enumMap({ '1': '#22c55e', '0': '#64748b' }))],
      tooltip: '2号提升泵\n运行状态：{wwtp.pump2}',
    }),
    nd('c_st1', 'state-text', 345, 312, 110, 32, {
      name: '泵1状态', props: { defaultText: '停止', states: '[{"value":0,"text":"停止","color":"#94a3b8"},{"value":1,"text":"运行中","color":"#67c23a"}]' },
      bindings: [bd(V.pump1, 'props.value')],
    }),
    nd('c_st2', 'state-text', 345, 422, 110, 32, {
      name: '泵2状态', props: { defaultText: '停止', states: '[{"value":0,"text":"停止","color":"#94a3b8"},{"value":1,"text":"运行中","color":"#67c23a"}]' },
      bindings: [bd(V.pump2, 'props.value')],
    }),

    txt('t_reg', 385, 148, 140, 26, '调节池', 14, '#cbd5e1'),
    nd('c_tank_reg', 'tank', 385, 178, 145, 200, { name: '调节池', bindings: [bd(V.lr, 'props.percent')], style: { color: '#38bdf8' } }),
    nd('c_fb2', 'flow-bar', 536, 260, 110, 24, { name: '管流', props: { speed: 80 }, bindings: [bd(V.pump2, 'props.speed', 'value', onOff('80', '0'))] }),

    txt('t_bio', 675, 148, 190, 26, '生化池（A/O）', 14, '#cbd5e1'),
    nd('c_tank_bio', 'tank', 675, 178, 190, 240, { name: '生化池', bindings: [bd(V.lb, 'props.percent')], style: { color: '#34d399' } }),
    nd('c_vd_dox', 'var-display', 695, 380, 150, 40, { name: 'DO 显示', props: { prefix: 'DO', unit: 'mg/L', precision: 2 }, bindings: [bd(V.dox, 'props.value')] }),
    nd('c_feeder', 'pump', 555, 420, 70, 70, {
      name: '加药泵', style: { color: '#f59e0b' },
      anim: { rotate: { enabled: true, clockwise: true, periodMs: 2000 } },
      bindings: [bd(V.feeder, 'anim.rotateOn')],
      tooltip: 'PAC 加药泵\n运行状态：{wwtp.feeder}',
    }),
    nd('c_st_fd', 'state-text', 555, 496, 110, 30, {
      name: '加药状态', props: { defaultText: '停止', states: '[{"value":0,"text":"停止","color":"#94a3b8"},{"value":1,"text":"加药中","color":"#e6a23c"}]' },
      bindings: [bd(V.feeder, 'props.value')],
    }),
    nd('c_pump_re', 'pump', 900, 420, 70, 70, {
      name: '回流泵', style: { color: '#38bdf8' },
      anim: { rotate: { enabled: true, clockwise: true, periodMs: 2500 } },
      bindings: [bd(V.pump2, 'anim.rotateOn')],
    }),

    txt('t_clear', 945, 148, 140, 26, '清水池', 14, '#cbd5e1'),
    nd('c_tank_clear', 'tank', 945, 178, 145, 200, { name: '清水池', bindings: [bd(V.lc, 'props.percent')], style: { color: '#38bdf8' } }),
    nd('c_fb3', 'flow-bar', 1096, 260, 110, 24, { name: '出水管流', props: { speed: 80 }, bindings: [bd(V.valve, 'props.speed', 'value', onOff('80', '0'))] }),
    nd('c_valve', 'valve', 1225, 240, 80, 80, {
      name: '出水阀',
      bindings: [bd(V.valve, 'style.color', 'color', enumMap({ '1': '#22c55e', '0': '#64748b' }))],
      tooltip: '气动出水阀\n开度状态：{wwtp.valve_out}',
    }),

    // ---- 报警灯（连续量按阈值区间判定，超标才闪） ----
    nd('c_alm_ph', 'status-light', 330, 152, 34, 34, {
      name: 'pH 报警灯',
      anim: { blink: { enabled: false, intervalMs: 600 } },
      bindings: [
        bd(V.ph, 'style.color', 'color', rangeMap({ max: 9.2, value: '#22c55e' }, { min: 9.2, value: '#ef4444' })),
        bd(V.ph, 'anim.blinkOn', 'value', rangeMap({ max: 9.2, value: false }, { min: 9.2, value: true })),
      ],
      tooltip: 'pH 状态灯（>9.2 红灯闪烁）\n当前：{wwtp.ph}',
    }),

    // ---- 右侧指标区 ----
    txt('t_sec2', 1340, 104, 240, 30, '关键指标', 16, '#94a3b8'),
    nd('c_g_inflow', 'gauge', 1340, 140, 250, 210, { name: '进水流量', props: { title: '进水流量', unit: 'm³/h', min: 0, max: 1000, textColor: '#e2e8f0' }, bindings: [bd(V.inflow, 'props.value')] }),
    nd('c_g_dox', 'gauge', 1600, 140, 250, 210, { name: '溶解氧', props: { title: '溶解氧 DO', unit: 'mg/L', min: 0, max: 6, precision: 2, textColor: '#e2e8f0' }, bindings: [bd(V.dox, 'props.value')] }),
    nd('c_vd_ph', 'var-display', 1340, 366, 250, 56, { name: 'pH', props: { prefix: '进水 pH', unit: '', precision: 2 }, style: { color: '#e2e8f0' }, bindings: [bd(V.ph, 'props.value')] }),
    nd('c_vd_cod', 'var-display', 1600, 366, 250, 56, { name: 'COD', props: { prefix: '出水 COD', unit: 'mg/L', precision: 1 }, style: { color: '#e2e8f0' }, bindings: [bd(V.cod, 'props.value')] }),
    nd('c_trend', 'trend-chart', 1340, 440, 510, 230, { name: '进水流量趋势', props: { title: '进水流量趋势', unit: 'm³/h' }, bindings: [bd(V.inflow, 'props.data')] }),
    nd('c_hist', 'history-chart', 1340, 690, 510, 250, { name: 'COD 历史', props: { variableId: V.cod, title: '出水 COD 历史（1h/6h/24h/3d）', unit: 'mg/L', rangeMs: 3600000 } }),

    // ---- 左下控制区 ----
    txt('t_sec3', 60, 560, 240, 30, '加药与应急控制（反控演示）', 16, '#94a3b8'),
    nd('c_vd_set', 'var-display', 60, 596, 190, 48, { name: '当前设定', props: { prefix: '设定 pH', unit: '', precision: 1 }, bindings: [bd(V.phSet, 'props.value')] }),
    nd('c_in_ph', 'input-cmd', 60, 652, 290, 44, { name: 'pH 设定', props: { variableId: V.phSet, placeholder: '输入中和目标 pH', unit: 'pH', buttonText: '下发', clearAfter: true } }),
    nd('c_sw_em', 'switch', 60, 706, 230, 44, { name: '应急排阀', props: { variableId: V.emerg, onValue: 1, offValue: 0, confirm: true, label: '应急排阀' } }),
    txt('t_hint', 60, 762, 420, 60, '· 右键「1号提升泵」弹出操作菜单\n· 悬停泵/阀/水池查看实时信息\n· pH > 9.5 自动弹出处置弹框', 13, '#64748b'),

    // ---- 右键菜单弹框（menu 式） ----
    nd('grp_pump_menu', 'group', 360, 300, 200, 180, {
      name: '提升泵操作菜单',
      popup: { style: 'menu', title: '1号提升泵', triggerExpr: null },
      style: { fill: '#1e293b', stroke: '#475569', borderRadius: 6 },
      children: [
        nd('m_btn_on', 'button', 16, 16, 168, 40, { name: '启动', props: { text: '▶ 启动' }, events: [{ trigger: 'click', actions: [{ type: 'writeVar', variableId: V.pump1, value: '1' }, { type: 'hidePopup', targetId: 'grp_pump_menu' }] }] }),
        nd('m_btn_off', 'button', 16, 64, 168, 40, { name: '停止', props: { text: '■ 停止' }, events: [{ trigger: 'click', actions: [{ type: 'writeVar', variableId: V.pump1, value: '0' }, { type: 'hidePopup', targetId: 'grp_pump_menu' }] }] }),
        nd('m_btn_par', 'button', 16, 112, 168, 40, { name: '运行参数', props: { text: '⚙ 运行参数' }, events: [{ trigger: 'click', actions: [{ type: 'toggleVisible', targetId: 'grp_params' }, { type: 'hidePopup', targetId: 'grp_pump_menu' }] }] }),
      ],
    }),

    // ---- 运行参数面板（toggleVisible 目标，初始隐藏） ----
    nd('grp_params', 'group', 700, 560, 380, 200, {
      name: '运行参数面板', visible: false, style: { fill: '#111c33', stroke: '#3b82f6', borderRadius: 8 },
      children: [
        txt('p_t1', 16, 10, 340, 30, '提升泵运行参数', 16, '#e2e8f0'),
        nd('p_vd_in', 'var-display', 16, 48, 160, 44, { name: '瞬时流量', props: { prefix: '流量', unit: 'm³/h', precision: 0 }, bindings: [bd(V.inflow, 'props.value')] }),
        nd('p_vd_ph', 'var-display', 196, 48, 160, 44, { name: '介质 pH', props: { prefix: 'pH', unit: '', precision: 2 }, bindings: [bd(V.ph, 'props.value')] }),
        nd('p_vd_lv', 'var-display', 16, 100, 160, 44, { name: '调节池液位', props: { prefix: '液位', unit: '%', precision: 1 }, bindings: [bd(V.lr, 'props.value')] }),
        nd('p_vd_cod', 'var-display', 196, 100, 160, 44, { name: '出水 COD', props: { prefix: 'COD', unit: 'mg/L', precision: 1 }, bindings: [bd(V.cod, 'props.value')] }),
        nd('p_btn_close', 'button', 16, 152, 120, 36, { name: '关闭面板', props: { text: '关闭' }, events: [{ trigger: 'click', actions: [{ type: 'toggleVisible', targetId: 'grp_params' }] }] }),
      ],
    }),

    // ---- 条件弹框（pH 超标自动弹出） ----
    nd('grp_ph_alert', 'group', 560, 576, 560, 320, {
      name: 'pH 超标处置弹框',
      popup: { style: 'dialog', title: '⚠ 进水 pH 超标处置', triggerExpr: 'wwtp.ph > 9.5' },
      style: { fill: '#1a1207', stroke: '#f59e0b', borderRadius: 8 },
      children: [
        txt('a_t1', 20, 12, 520, 28, '进水 pH 已超过 9.5，请确认加药量或启用应急排放', 15, '#fbbf24'),
        nd('a_vd_ph', 'var-display', 20, 52, 200, 48, { name: '当前 pH', props: { prefix: '当前 pH', unit: '', precision: 2 }, style: { color: '#fbbf24' }, bindings: [bd(V.ph, 'props.value')] }),
        nd('a_in_set', 'input-cmd', 240, 52, 290, 48, { name: '下调设定', props: { variableId: V.phSet, placeholder: '输入新的中和目标 pH', unit: 'pH', buttonText: '下发', clearAfter: true } }),
        nd('a_sw_em', 'switch', 20, 112, 250, 44, { name: '应急排阀', props: { variableId: V.emerg, onValue: 1, offValue: 0, confirm: true, label: '启用应急排阀' } }),
        nd('a_st_fd', 'state-text', 290, 112, 240, 40, { name: '加药状态', props: { defaultText: '--', states: '[{"value":0,"text":"加药泵停止","color":"#94a3b8"},{"value":1,"text":"加药中","color":"#e6a23c"}]' }, bindings: [bd(V.feeder, 'props.value')] }),
        txt('a_t2', 20, 166, 520, 26, '处置完成后 pH 回落至 9.5 以下弹框自动关闭', 13, '#64748b'),
        nd('a_btn_close', 'button', 420, 200, 120, 40, { name: '手动关闭', props: { text: '关闭' }, events: [{ trigger: 'click', actions: [{ type: 'hidePopup', targetId: 'grp_ph_alert' }] }] }),
      ],
    }),
  ]

  return demoDoc(
    '案例一 · 污水处理系统',
    '综合旗舰案例：水池液位/泵旋转/管道流动/仪表/趋势与历史图表/报警/悬停信息/右键菜单/条件弹框/输入框指令/开关反控（mock 数据源，开箱即用）',
    vars,
    [pg('pg_wwtp', '工艺总览', 1920, 1080, comps, { lockPan: true })],
    [
      alm('a_ph', '进水 pH 超标', V.ph, '>', 9.2, 'warn', '{label} = {value}（阈值 {threshold}），请检查加药系统'),
      alm('a_cod', '出水 COD 超标', V.cod, '>', 50, 'critical', '{label} = {value} mg/L（阈值 {threshold}），出水不达标'),
      alm('a_dox', '溶解氧过低', V.dox, '<', 2, 'info', '{label} = {value} mg/L，曝气量不足'),
    ],
  )
}
