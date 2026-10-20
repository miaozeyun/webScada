/**
 * 演示案例五：MQTT 通讯测试（mock 回环演示）。
 * 覆盖：订阅回读显示 / 发布写入（开关+输入框）/ 链路状态 / 历史与趋势 / writeVar 事件 / openUrl 事件。
 * 真实场景：工具栏「数据」建 MQTT 数据源（ws://host:8083/mqtt），topic 填变量取数地址，
 * 写地址填变量 writeAddress 即可发布——本案例以 mock 数据源演示同一条链路。
 */
import { bd, demoDoc, enumMap, mvar, nd, pg, txt } from './shared'

export function buildMqttTestDoc(): ReturnType<typeof demoDoc> {
  const V = {
    link: 'v_link', rxTemp: 'v_rx_temp', rxCnt: 'v_rx_cnt',
    txTemp: 'v_tx_temp', txSw: 'v_tx_sw',
  }

  const vars = [
    mvar(V.link, 'mq.link', 'Broker 链路', { kind: 'square', min: 0, max: 1, periodMs: 40000, duty: 0.95 }),
    mvar(V.rxTemp, 'mq.rx_temp', '订阅·设备温度', { kind: 'sine', min: 15, max: 35, periodMs: 15000, unit: '℃' }),
    mvar(V.rxCnt, 'mq.rx_cnt', '订阅·上报计数', { kind: 'sine', min: 0, max: 1000, periodMs: 60000 }),
    mvar(V.txTemp, 'mq.tx_temp', '发布·温度设定', { kind: 'hold', def: 25, writable: true, unit: '℃' }),
    mvar(V.txSw, 'mq.tx_sw', '发布·设备开关', { kind: 'hold', def: 1, writable: true }),
  ]

  const comps = [
    txt('t_title', 40, 16, 760, 48, 'MQTT 通讯测试（mock 回环演示）', 26, '#e2e8f0'),
    nd('c_link', 'state-text', 40, 76, 200, 40, {
      name: '链路状态',
      props: { defaultText: '--', states: '[{"value":0,"text":"● Broker 断开","color":"#ef4444","background":"#2a1215"},{"value":1,"text":"● Broker 已连接","color":"#22c55e","background":"#12261a"}]' },
      bindings: [bd(V.link, 'props.value')],
    }),
    txt('t_note', 40, 126, 1180, 56,
      '真实场景：工具栏「数据」新建 MQTT 数据源（broker 如 ws://localhost:8083/mqtt），变量取数地址=订阅 topic；反控需变量开启「可写」并填写地址（发布 topic）。本工程用 mock 数据源演示同一条 订阅→显示→写入→回读 链路。',
      13, '#64748b'),

    // ---- 订阅侧（回读显示） ----
    txt('t_rx', 40, 200, 300, 28, '订阅（Sub · 回读显示）', 16, '#94a3b8'),
    nd('c_rx_t', 'var-display', 40, 232, 300, 60, { name: '设备温度', props: { prefix: 'device/temp', unit: '℃', precision: 2 }, bindings: [bd(V.rxTemp, 'props.value')], style: { color: '#e2e8f0' } }),
    nd('c_rx_c', 'var-display', 360, 232, 300, 60, { name: '上报计数', props: { prefix: 'device/count', unit: '', precision: 0 }, bindings: [bd(V.rxCnt, 'props.value')], style: { color: '#e2e8f0' } }),
    nd('c_light', 'status-light', 690, 240, 40, 40, { name: '在线灯', bindings: [bd(V.txSw, 'style.color', 'color', enumMap({ '1': '#22c55e', '0': '#64748b' }))] }),

    // ---- 发布侧（写入） ----
    txt('t_tx', 40, 320, 300, 28, '发布（Pub · 反控写入）', 16, '#94a3b8'),
    nd('c_tx_in', 'input-cmd', 40, 352, 340, 46, { name: '温度设定下发', props: { variableId: V.txTemp, placeholder: '下发温度设定', unit: '℃', buttonText: '发布', clearAfter: true } }),
    nd('c_tx_sw', 'switch', 400, 352, 230, 46, { name: '设备开关', props: { variableId: V.txSw, onValue: 1, offValue: 0, confirm: true, label: '设备通电' } }),
    nd('c_tx_vd', 'var-display', 650, 352, 240, 46, { name: '设定回读', props: { prefix: 'set/readback', unit: '℃', precision: 1 }, bindings: [bd(V.txTemp, 'props.value')], style: { color: '#e2e8f0' } }),

    // ---- 曲线 ----
    txt('t_chart', 40, 420, 300, 28, '报文曲线', 16, '#94a3b8'),
    nd('c_hist', 'history-chart', 40, 452, 580, 260, { name: '温度历史', props: { variableId: V.rxTemp, title: '订阅温度历史', unit: '℃', rangeMs: 3600000 } }),
    nd('c_trend', 'trend-chart', 640, 452, 580, 260, { name: '计数趋势', props: { title: '上报计数趋势', unit: '' }, bindings: [bd(V.rxCnt, 'props.data')] }),

    // ---- 事件演示 ----
    txt('t_evt', 40, 736, 300, 28, '事件动作', 16, '#94a3b8'),
    nd('c_btn_off', 'button', 40, 768, 190, 42, { name: '一键断电', props: { text: '断电（writeVar）' }, events: [{ trigger: 'click', actions: [{ type: 'writeVar', variableId: V.txSw, value: '0' }] }] }),
    nd('c_btn_on', 'button', 250, 768, 190, 42, { name: '一键上电', props: { text: '上电（writeVar）' }, events: [{ trigger: 'click', actions: [{ type: 'writeVar', variableId: V.txSw, value: '1' }] }] }),
    nd('c_btn_doc', 'button', 460, 768, 230, 42, { name: '打开 EMQX', props: { text: 'EMQX 文档（openUrl）' }, events: [{ trigger: 'click', actions: [{ type: 'openUrl', url: 'https://www.emqx.io/zh' }] }] }),
    nd('c_vd_sw', 'var-display', 710, 768, 200, 42, { name: '开关回读', props: { prefix: '设备', unit: '', precision: 0 }, bindings: [bd(V.txSw, 'props.value')], style: { color: '#e2e8f0' } }),
  ]

  return demoDoc(
    '案例五 · MQTT 通讯测试',
    '订阅回读/发布写入/链路状态/报文曲线/writeVar 与 openUrl 事件（mock 回环；真实场景在「数据」面板配置 MQTT 数据源）',
    vars,
    [pg('pg_mq', '通讯测试', 1280, 860, comps)],
  )
}
