/**
 * 演示案例六：反控指令集（双页）。
 * 页1 主控台：多档开关/写前确认开关/输入框指令/状态回显/仪表/趋势/历史。
 * 页2 交互演示：showPopup/hidePopup/toggleVisible/switchPage/openUrl/悬停信息/条件弹框/右键菜单。
 */
import { alm, bd, demoDoc, enumMap, mvar, nd, pg, txt } from './shared'

export function buildControlDoc(): ReturnType<typeof demoDoc> {
  const V = {
    fan: 'v_fan', light: 'v_light', heat: 'v_heat',
    tempSet: 'v_temp_set', timerMin: 'v_timer_min',
    temp: 'v_temp', press: 'v_press', level: 'v_level',
  }

  const vars = [
    mvar(V.fan, 'ctl.fan_speed', '风机档位', { kind: 'hold', def: 1, writable: true }),
    mvar(V.light, 'ctl.light', '车间照明', { kind: 'hold', def: 0, writable: true }),
    mvar(V.heat, 'ctl.heat', '电加热', { kind: 'hold', def: 0, writable: true }),
    mvar(V.tempSet, 'ctl.temp_set', '温度设定', { kind: 'hold', def: 25, writable: true, unit: '℃' }),
    mvar(V.timerMin, 'ctl.timer_min', '保温定时', { kind: 'hold', def: 30, writable: true, unit: 'min' }),
    mvar(V.temp, 'ctl.temp', '炉内温度', { kind: 'sine', min: 20, max: 95, periodMs: 60000, unit: '℃' }),
    mvar(V.press, 'ctl.press', '管道压力', { kind: 'sine', min: 0.2, max: 0.8, periodMs: 25000, unit: 'MPa' }),
    mvar(V.level, 'ctl.level', '料仓液位', { kind: 'sine', min: 30, max: 90, periodMs: 45000, unit: '%' }),
  ]

  // ---- 页 1：主控台 ----
  const p1 = [
    txt('t_title', 40, 18, 800, 50, '热处理车间 · 反控主控台', 26, '#e2e8f0'),
    nd('c_clock', 'clock', 1360, 18, 300, 54, { props: {}, style: { color: '#e2e8f0' } }),

    txt('t_fan', 40, 92, 400, 26, '风机档位（multi-switch 反控）', 14, '#94a3b8'),
    nd('c_ms', 'multi-switch', 40, 120, 380, 46, {
      name: '风机档位',
      props: { variableId: V.fan, levels: '[{"value":0,"label":"停止"},{"value":1,"label":"一档"},{"value":2,"label":"二档"},{"value":3,"label":"三档"}]' },
    }),
    nd('c_st_fan', 'state-text', 40, 174, 380, 36, {
      name: '风机状态',
      props: { defaultText: '--', states: '[{"value":0,"text":"风机停止","color":"#94a3b8"},{"value":1,"text":"一档 · 低速","color":"#67c23a"},{"value":2,"text":"二档 · 中速","color":"#409eff"},{"value":3,"text":"三档 · 高速","color":"#e6a23c"}]' },
      bindings: [bd(V.fan, 'props.value')],
    }),

    txt('t_sw', 40, 226, 400, 26, '写前确认开关（confirm）', 14, '#94a3b8'),
    nd('c_sw_l', 'switch', 40, 254, 185, 46, { name: '照明', props: { variableId: V.light, onValue: 1, offValue: 0, confirm: true, label: '车间照明' } }),
    nd('c_sw_h', 'switch', 235, 254, 185, 46, { name: '电加热', props: { variableId: V.heat, onValue: 1, offValue: 0, confirm: true, label: '电加热' } }),

    txt('t_in', 40, 312, 400, 26, '输入框指令（input-cmd）', 14, '#94a3b8'),
    nd('c_in_t', 'input-cmd', 40, 340, 300, 46, { name: '温度设定', props: { variableId: V.tempSet, placeholder: '设定炉温 20~95', unit: '℃', buttonText: '下发', clearAfter: true } }),
    nd('c_vd_set', 'var-display', 350, 340, 170, 46, { name: '设定回显', props: { prefix: '设定', unit: '℃', precision: 0 }, bindings: [bd(V.tempSet, 'props.value')], style: { color: '#e2e8f0' } }),
    nd('c_in_m', 'input-cmd', 40, 394, 300, 46, { name: '保温定时', props: { variableId: V.timerMin, placeholder: '保温时长（分钟）', unit: 'min', buttonText: '下发', clearAfter: true } }),
    nd('c_vd_m', 'var-display', 350, 394, 170, 46, { name: '定时时长', props: { prefix: '时长', unit: 'min', precision: 0 }, bindings: [bd(V.timerMin, 'props.value')], style: { color: '#e2e8f0' } }),

    txt('t_proc', 40, 456, 400, 26, '过程量（自动模拟）', 14, '#94a3b8'),
    nd('c_vd_t', 'var-display', 40, 484, 230, 56, {
      name: '炉内温度', props: { prefix: '炉温', unit: '℃', precision: 1 }, bindings: [bd(V.temp, 'props.value')], style: { color: '#e2e8f0' },
      anim: { blink: { enabled: false, intervalMs: 700 } },
    }),
    nd('c_blink_t', 'status-light', 280, 490, 34, 34, { name: '高温灯', bindings: [bd(V.temp, 'style.color', 'color', { kind: 'range', bands: [{ max: 80, value: '#64748b' }, { min: 80, value: '#ef4444' }] })] }),
    nd('c_tank', 'tank', 40, 552, 130, 160, { name: '料仓', bindings: [bd(V.level, 'props.percent')], style: { color: '#34d399' }, tooltip: '料仓液位 {ctl.level} %' }),
    nd('c_gauge', 'gauge', 190, 540, 240, 210, { name: '压力表', props: { title: '管道压力', unit: 'MPa', min: 0, max: 1, textColor: '#e2e8f0' }, bindings: [bd(V.press, 'props.value')] }),

    nd('c_trend', 'trend-chart', 470, 120, 500, 220, { name: '温度趋势', props: { title: '炉温趋势', unit: '℃' }, bindings: [bd(V.temp, 'props.data')] }),
    nd('c_hist', 'history-chart', 470, 356, 500, 260, { name: '液位历史', props: { variableId: V.level, title: '料仓液位历史', unit: '%', rangeMs: 21600000 } }),

    // 交互演示页入口
    nd('c_btn_p2', 'button', 1010, 120, 260, 46, { name: '进入交互演示', props: { text: '② 事件与行为演示 →' }, events: [{ trigger: 'click', actions: [{ type: 'switchPage', pageId: 'pg_ctl_2' }] }] }),
    txt('t_hint', 1010, 180, 620, 90, '① 本页全部控制件均走反控写通道（hold 型 mock 回环，写入即回读）\n② 页 2 演示事件与行为：单击/双击/右键/悬停/条件弹框\n③ 炉温 > 80℃ 时左下温度数值闪烁告警', 13, '#64748b'),
    nd('c_sw_p2', 'switch', 1010, 286, 240, 46, { name: '照明（跨页同变量）', props: { variableId: V.light, onValue: 1, offValue: 0, confirm: false, label: '车间照明' } }),
    nd('c_motor', 'motor', 1050, 380, 120, 120, {
      name: '主风机', style: { color: '#38bdf8' },
      anim: { rotate: { enabled: true, clockwise: true, periodMs: 2400 } },
      bindings: [bd(V.fan, 'anim.rotateOn'), bd(V.fan, 'anim.rotatePeriod', 'value', { kind: 'enum', map: { '1': '3600', '2': '1800', '3': '900' } })],
      tooltip: '主风机（档位控转速）\n当前档位：{ctl.fan_speed}',
    }),
    txt('t_fan_note', 1020, 510, 300, 26, '风机档位 1/2/3 → 3600/1800/900 ms 每圈', 12, '#64748b'),
  ]

  // ---- 页 2：事件与行为演示 ----
  const p2 = [
    txt('e_title', 40, 18, 800, 50, '事件与行为 · 交互演示', 26, '#e2e8f0'),
    nd('c_back', 'button', 40, 80, 220, 44, { name: '返回主控台', props: { text: '← 返回主控台（switchPage）' }, events: [{ trigger: 'click', actions: [{ type: 'switchPage', pageId: 'pg_ctl_1' }] }] }),

    txt('e_t1', 40, 150, 560, 26, '① showPopup：单击按钮弹出对话框', 14, '#94a3b8'),
    nd('e_btn_dlg', 'button', 40, 178, 220, 44, { name: '弹对话框', props: { text: '弹出对话框' }, events: [{ trigger: 'click', actions: [{ type: 'showPopup', targetId: 'grp_dialog' }] }] }),

    txt('e_t2', 40, 240, 560, 26, '② toggleVisible：双击文本显示/隐藏面板', 14, '#94a3b8'),
    nd('e_txt_toggle', 'text', 40, 268, 260, 44, { name: '双击我', props: { text: '双击我试试 👀' }, style: { fontSize: 18, color: '#409eff' }, events: [{ trigger: 'dblclick', actions: [{ type: 'toggleVisible', targetId: 'grp_panel' }] }] }),

    txt('e_t3', 40, 330, 560, 26, '③ 右键菜单：右键下方设备弹出操作菜单', 14, '#94a3b8'),
    nd('e_valve', 'valve', 40, 360, 90, 90, {
      name: '气动阀（右键）', style: { color: '#38bdf8' },
      events: [{ trigger: 'contextmenu', actions: [{ type: 'showPopup', targetId: 'grp_menu' }] }],
      tooltip: '气动调节阀\n右键打开操作菜单',
    }),

    txt('e_t4', 40, 470, 560, 26, '④ 悬停信息：鼠标悬停下方文本查看实时值', 14, '#94a3b8'),
    nd('e_txt_tip', 'text', 40, 498, 320, 44, {
      name: '悬停我',
      props: { text: '悬停我查看实时数据 ❓' },
      style: { fontSize: 18, color: '#67c23a' },
      tooltip: '炉温 {ctl.temp} ℃ ｜ 设定 {ctl.temp_set} ℃ ｜ 压力 {ctl.press} MPa',
    }),

    txt('e_t5', 40, 620, 560, 26, '⑤ 条件弹框：炉温 > 80℃ 自动弹出告警（等 sine 涨上去）', 14, '#94a3b8'),
    nd('e_vd_t', 'var-display', 40, 648, 220, 52, { name: '炉温', props: { prefix: '炉温', unit: '℃', precision: 1 }, bindings: [bd(V.temp, 'props.value')], style: { color: '#e2e8f0' } }),

    txt('e_t6', 660, 150, 560, 26, '⑥ openUrl：单击打开新窗口', 14, '#94a3b8'),
    nd('e_btn_url', 'button', 660, 178, 260, 44, { name: '打开官网', props: { text: '打开 webScada 首页（openUrl）' }, events: [{ trigger: 'click', actions: [{ type: 'openUrl', url: 'https://github.com' }] }] }),
    txt('e_t7', 660, 240, 560, 26, '⑦ 事件里也能写变量（writeVar）', 14, '#94a3b8'),
    nd('e_btn_w1', 'button', 660, 268, 170, 44, { name: '照明开', props: { text: '照明 → 开' }, events: [{ trigger: 'click', actions: [{ type: 'writeVar', variableId: V.light, value: '1' }] }] }),
    nd('e_btn_w0', 'button', 850, 268, 170, 44, { name: '照明关', props: { text: '照明 → 关' }, events: [{ trigger: 'click', actions: [{ type: 'writeVar', variableId: V.light, value: '0' }] }] }),

    // ---- 隐藏面板（toggleVisible 目标） ----
    nd('grp_panel', 'group', 660, 360, 420, 190, {
      name: '隐藏参数面板', visible: false, style: { fill: '#111c33', stroke: '#3b82f6', borderRadius: 8 },
      children: [
        txt('p_t', 16, 10, 380, 30, '双击触发的参数面板', 16, '#e2e8f0'),
        nd('p_vd1', 'var-display', 16, 48, 180, 46, { name: '炉温', props: { prefix: '炉温', unit: '℃', precision: 1 }, bindings: [bd(V.temp, 'props.value')] }),
        nd('p_vd2', 'var-display', 210, 48, 180, 46, { name: '压力', props: { prefix: '压力', unit: 'MPa', precision: 2 }, bindings: [bd(V.press, 'props.value')] }),
        nd('p_vd3', 'var-display', 16, 102, 180, 46, { name: '液位', props: { prefix: '液位', unit: '%', precision: 1 }, bindings: [bd(V.level, 'props.value')] }),
        nd('p_close', 'button', 210, 102, 120, 40, { name: '关闭', props: { text: '收起' }, events: [{ trigger: 'click', actions: [{ type: 'toggleVisible', targetId: 'grp_panel' }] }] }),
      ],
    }),

    // ---- 对话框弹框（showPopup 目标） ----
    nd('grp_dialog', 'group', 660, 580, 480, 240, {
      name: '手动对话框', popup: { style: 'dialog', title: '批次参数确认', triggerExpr: null },
      style: { fill: '#0f1e33', stroke: '#3b82f6', borderRadius: 8 },
      children: [
        txt('d_t', 20, 12, 440, 30, '批次 #B-20261020-07 待确认', 16, '#e2e8f0'),
        nd('d_in', 'input-cmd', 20, 52, 300, 46, { name: '炉温设定', props: { variableId: V.tempSet, placeholder: '批次炉温设定', unit: '℃', buttonText: '下发', clearAfter: true } }),
        nd('d_in2', 'input-cmd', 20, 106, 300, 46, { name: '保温时长', props: { variableId: V.timerMin, placeholder: '保温时长', unit: 'min', buttonText: '下发', clearAfter: true } }),
        nd('d_sw', 'switch', 20, 164, 220, 44, { name: '电加热', props: { variableId: V.heat, onValue: 1, offValue: 0, confirm: false, label: '下发后启动加热' } }),
        nd('d_close', 'button', 340, 164, 120, 42, { name: '关闭', props: { text: '关闭' }, events: [{ trigger: 'click', actions: [{ type: 'hidePopup', targetId: 'grp_dialog' }] }] }),
      ],
    }),

    // ---- 右键菜单（menu 式） ----
    nd('grp_menu', 'group', 150, 360, 200, 178, {
      name: '阀门操作菜单', popup: { style: 'menu', title: '气动调节阀', triggerExpr: null },
      style: { fill: '#1e293b', stroke: '#475569', borderRadius: 6 },
      children: [
        nd('m_1', 'button', 16, 14, 168, 40, { name: '全开', props: { text: '▶ 阀门全开' }, events: [{ trigger: 'click', actions: [{ type: 'writeVar', variableId: V.heat, value: '1' }, { type: 'hidePopup', targetId: 'grp_menu' }] }] }),
        nd('m_2', 'button', 16, 62, 168, 40, { name: '全关', props: { text: '■ 阀门全关' }, events: [{ trigger: 'click', actions: [{ type: 'writeVar', variableId: V.heat, value: '0' }, { type: 'hidePopup', targetId: 'grp_menu' }] }] }),
        nd('m_3', 'button', 16, 110, 168, 40, { name: '面板', props: { text: '⚙ 参数面板' }, events: [{ trigger: 'click', actions: [{ type: 'toggleVisible', targetId: 'grp_panel' }, { type: 'hidePopup', targetId: 'grp_menu' }] }] }),
      ],
    }),

    // ---- 条件弹框（炉温 > 80 自动弹出） ----
    nd('grp_hot', 'group', 260, 300, 520, 200, {
      name: '高温告警弹框', popup: { style: 'dialog', title: '⚠ 炉温高温告警', triggerExpr: 'ctl.temp > 80' },
      style: { fill: '#2a1215', stroke: '#ef4444', borderRadius: 8 },
      children: [
        txt('h_t', 20, 12, 480, 28, '炉温超过 80℃，建议下调设定或停加热', 15, '#f87171'),
        nd('h_vd', 'var-display', 20, 50, 220, 48, { name: '当前炉温', props: { prefix: '当前炉温', unit: '℃', precision: 1 }, bindings: [bd(V.temp, 'props.value')] }),
        nd('h_in', 'input-cmd', 260, 50, 240, 48, { name: '下调设定', props: { variableId: V.tempSet, placeholder: '输入新设定（如 60）', unit: '℃', buttonText: '下发', clearAfter: true } }),
        nd('h_sw', 'switch', 20, 108, 240, 44, { name: '停止加热', props: { variableId: V.heat, onValue: 1, offValue: 0, confirm: true, label: '停止电加热' } }),
        nd('h_close', 'button', 380, 108, 120, 42, { name: '关闭', props: { text: '关闭' }, events: [{ trigger: 'click', actions: [{ type: 'hidePopup', targetId: 'grp_hot' }] }] }),
      ],
    }),
  ]

  return demoDoc(
    '案例六 · 反控指令集',
    '双页演示：多档开关/confirm 开关/输入框指令/档位控转速/switchPage 跨页/showPopup/toggleVisible/右键菜单/条件弹框/悬停信息/openUrl/writeVar',
    vars,
    [pg('pg_ctl_1', '主控台', 1720, 780, p1, { lockPan: true }), pg('pg_ctl_2', '交互演示', 1220, 860, p2, { lockPan: true, order: 1 })],
    [alm('a_temp', '炉温超上限', V.temp, '>', 85, 'warn', '{label} = {value} ℃（阈值 {threshold}）')],
  )
}
