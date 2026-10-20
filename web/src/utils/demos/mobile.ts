/**
 * 演示案例四：移动端（竖屏 + 横屏双页）。
 * 覆盖：自定义分辨率 375×812 / 812×375、手机竖屏布局（时钟/天气/液位/开关/多档/输入框/历史）、
 * lockPan 画面锁定、多页切换。
 */
import { bd, demoDoc, enumMap, mvar, nd, pg, txt } from './shared'

export function buildMobileDoc(): ReturnType<typeof demoDoc> {
  const V = {
    temp: 'v_temp', humi: 'v_humi', level: 'v_level',
    light: 'v_light', ac: 'v_ac', acSpeed: 'v_ac_speed', tempSet: 'v_temp_set',
  }

  const vars = [
    mvar(V.temp, 'home.temp', '室内温度', { kind: 'sine', min: 18, max: 28, periodMs: 30000, unit: '℃' }),
    mvar(V.humi, 'home.humi', '室内湿度', { kind: 'sine', min: 40, max: 80, periodMs: 40000, unit: '%' }),
    mvar(V.level, 'home.level', '水箱液位', { kind: 'sine', min: 25, max: 90, periodMs: 50000, unit: '%' }),
    mvar(V.light, 'home.light', '客厅照明', { kind: 'hold', def: 0, writable: true }),
    mvar(V.ac, 'home.ac', '中央空调', { kind: 'hold', def: 1, writable: true }),
    mvar(V.acSpeed, 'home.ac_speed', '空调风速', { kind: 'hold', def: 1, writable: true }),
    mvar(V.tempSet, 'home.temp_set', '温度设定', { kind: 'hold', def: 24, writable: true }),
  ]

  // ---- 页 1：手机竖屏 375×812 ----
  const p1 = [
    nd('m_clock', 'clock', 16, 14, 343, 54, { props: { showDate: false, showSeconds: false, layout: 'horizontal' }, style: { color: '#e2e8f0', fontSize: 30, textAlign: 'center' } }),
    nd('m_weather', 'weather', 16, 76, 343, 84, { props: { city: '上海', lat: 31.2, lon: 121.5 } }),
    txt('m_t1', 16, 176, 160, 24, '室内温度', 13, '#94a3b8'),
    nd('m_vd_t', 'var-display', 16, 200, 165, 56, { name: '温度', props: { unit: '℃', precision: 1 }, bindings: [bd(V.temp, 'props.value')], style: { color: '#e2e8f0' } }),
    txt('m_t2', 194, 176, 165, 24, '室内湿度', 13, '#94a3b8'),
    nd('m_vd_h', 'var-display', 194, 200, 165, 56, { name: '湿度', props: { unit: '%RH', precision: 0 }, bindings: [bd(V.humi, 'props.value')], style: { color: '#e2e8f0' } }),
    txt('m_t3', 16, 272, 200, 24, '生活水箱', 13, '#94a3b8'),
    nd('m_tank', 'tank', 16, 296, 120, 150, { name: '水箱', bindings: [bd(V.level, 'props.percent')], style: { color: '#38bdf8' }, tooltip: '水箱液位 {home.level} %' }),
    nd('m_prog', 'progress', 152, 340, 207, 18, { name: '湿度进度', bindings: [bd(V.humi, 'props.percent')] }),
    txt('m_t4', 152, 296, 200, 24, '湿度 0~100%', 12, '#64748b'),
    txt('m_t5', 16, 466, 300, 24, '设备控制', 13, '#94a3b8'),
    nd('m_sw_l', 'switch', 16, 492, 165, 46, { name: '照明', props: { variableId: V.light, onValue: 1, offValue: 0, confirm: false, label: '💡 照明' } }),
    nd('m_sw_a', 'switch', 194, 492, 165, 46, { name: '空调', props: { variableId: V.ac, onValue: 1, offValue: 0, confirm: false, label: '❄ 空调' } }),
    nd('m_st_l', 'state-text', 16, 542, 165, 30, { name: '照明状态', props: { defaultText: '--', states: '[{"value":0,"text":"已关闭","color":"#94a3b8"},{"value":1,"text":"已开启","color":"#fbbf24"}]' }, bindings: [bd(V.light, 'props.value')] }),
    nd('m_st_a', 'state-text', 194, 542, 165, 30, { name: '空调状态', props: { defaultText: '--', states: '[{"value":0,"text":"已关闭","color":"#94a3b8"},{"value":1,"text":"制冷中","color":"#38bdf8"}]' }, bindings: [bd(V.ac, 'props.value')] }),
    txt('m_t6', 16, 578, 200, 20, '风速调节', 13, '#94a3b8'),
    nd('m_ms', 'multi-switch', 16, 600, 343, 42, {
      name: '风速',
      props: { variableId: V.acSpeed, levels: '[{"value":0,"label":"停"},{"value":1,"label":"低"},{"value":2,"label":"中"},{"value":3,"label":"高"}]' },
    }),
    txt('m_t7', 16, 652, 200, 20, '温度设定', 13, '#94a3b8'),
    nd('m_in', 'input-cmd', 16, 674, 343, 42, { name: '温度设定', props: { variableId: V.tempSet, placeholder: '16 ~ 30 ℃', unit: '℃', buttonText: '设定', clearAfter: true } }),
    txt('m_t8', 16, 726, 200, 20, '温度历史', 13, '#94a3b8'),
    nd('m_hist', 'history-chart', 16, 748, 343, 58, { name: '温度历史', props: { variableId: V.temp, title: '', unit: '℃', rangeMs: 3600000, compact: true, live: true } }),
  ]

  // ---- 页 2：横屏 812×375 ----
  const p2 = [
    txt('h_title', 20, 12, 400, 34, '家居总览（横屏）', 20, '#e2e8f0'),
    nd('h_clock', 'clock', 560, 12, 232, 40, { props: { showDate: true, showSeconds: true, layout: 'horizontal' }, style: { color: '#e2e8f0', fontSize: 16 } }),
    nd('h_vd_t', 'var-display', 20, 60, 180, 52, { name: '温度', props: { prefix: '温度', unit: '℃', precision: 1 }, bindings: [bd(V.temp, 'props.value')], style: { color: '#e2e8f0' } }),
    nd('h_vd_h', 'var-display', 20, 120, 180, 52, { name: '湿度', props: { prefix: '湿度', unit: '%RH', precision: 0 }, bindings: [bd(V.humi, 'props.value')], style: { color: '#e2e8f0' } }),
    nd('h_vd_s', 'var-display', 20, 180, 180, 52, { name: '设定', props: { prefix: '设定', unit: '℃', precision: 0 }, bindings: [bd(V.tempSet, 'props.value')], style: { color: '#e2e8f0' } }),
    nd('h_sw_l', 'switch', 220, 66, 170, 44, { name: '照明', props: { variableId: V.light, onValue: 1, offValue: 0, confirm: false, label: '💡 照明' } }),
    nd('h_sw_a', 'switch', 220, 122, 170, 44, { name: '空调', props: { variableId: V.ac, onValue: 1, offValue: 0, confirm: false, label: '❄ 空调' } }),
    nd('h_ms', 'multi-switch', 220, 180, 260, 44, {
      name: '风速',
      props: { variableId: V.acSpeed, levels: '[{"value":0,"label":"停"},{"value":1,"label":"低"},{"value":2,"label":"中"},{"value":3,"label":"高"}]' },
    }),
    nd('h_tank', 'tank', 500, 60, 90, 120, { name: '水箱', bindings: [bd(V.level, 'props.percent')], style: { color: '#38bdf8' } }),
    nd('h_trend', 'trend-chart', 610, 60, 182, 170, { name: '温度趋势', props: { title: '', unit: '℃' }, bindings: [bd(V.temp, 'props.data')] }),
    nd('h_light', 'status-light', 500, 200, 30, 30, { name: '空调灯', bindings: [bd(V.ac, 'style.color', 'color', enumMap({ '1': '#22c55e', '0': '#64748b' }))] }),
    txt('h_hint', 500, 238, 300, 24, '横屏 812×375 · fit-contain 自适应', 12, '#64748b'),
  ]

  return demoDoc(
    '案例四 · 移动端（竖屏/横屏）',
    '自定义分辨率双页演示：竖屏 375×812（时钟/天气/水箱液位/开关/多档风速/输入框/历史）与横屏 812×375 总览，画面锁定防误拖',
    vars,
    [pg('pg_m_v', '手机竖屏', 375, 812, p1, { lockPan: true }), pg('pg_m_h', '横屏总览', 812, 375, p2, { lockPan: true, order: 1 })],
  )
}
