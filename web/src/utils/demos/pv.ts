/**
 * 演示案例七：50MWp 光伏电站集控（行业 demo · 破晓琥珀主题）。
 * 视觉主角：辐照度驱动全屏「阵列苏醒」——6 子阵辉度色块随辐照四档渐亮，
 * 出力/等效小时/PR 由虚拟变量表达式联动（expr + _tick）。
 */
import { alm, bd, demoDoc, mvar, nd, pg, rangeMap, txt, vvar } from './shared'

export function buildPvDoc(): ReturnType<typeof demoDoc> {
  // ---- 变量：一个主驱动（辐照），全部派生量走 expr 联动 ----
  const irr = mvar('v_irr', 'pv_irr', '水平面辐照度', { kind: 'sine', min: 180, max: 920, periodMs: 150000, unit: 'W/m²' })
  const invT = mvar('v_inv_t', 'pv_inv_t', '逆变器温度', { kind: 'sine', min: 52, max: 73, periodMs: 80000, unit: '℃', precision: 1 })
  const freq = mvar('v_freq', 'pv_freq', '并网频率', { kind: 'sine', min: 49.85, max: 50.15, periodMs: 12000, unit: 'Hz' })

  const vars = [
    irr, invT, freq,
    vvar('v_out', 'pv_out', '电站出力', 'round(pv_irr * 0.052, 1)', { unit: 'MW', precision: 1 }),
    vvar('v_kwh', 'pv_kwh', '今日发电量', 'round(46.2 + sin(_tick / 90000) * 2.1, 1)', { unit: 'MWh', precision: 1 }),
    vvar('v_hours', 'pv_hours', '等效小时', 'round(3.4 + sin(_tick / 120000) * 0.25, 2)', { unit: 'h', precision: 2 }),
    vvar('v_pr', 'pv_pr', '系统效率 PR', 'round(80.6 + sin(_tick / 70000) * 1.8, 1)', { unit: '%', precision: 1 }),
    vvar('v_pf', 'pv_pf', '功率因数', 'round(0.96 + cos(_tick / 60000) * 0.02, 3)', { precision: 3 }),
  ]
  // 6 子阵：组串电流（辐照 + 每串相位微抖）与满发率（每串效率因子差异化）
  const strIds: string[] = []
  const srIds: string[] = []
  const factors = [0.97, 1.02, 0.99, 1.04, 0.96, 1.01]
  for (let i = 1; i <= 6; i++) {
    strIds.push(`v_str${i}`)
    srIds.push(`v_sr${i}`)
    vars.push(vvar(`v_str${i}`, `pv_str${i}`, `${i}# 子阵组串电流`, `round(pv_irr * 0.0105 * ${factors[i - 1]} + sin(_tick / 4000 + ${i}) * 0.2, 1)`, { unit: 'A', precision: 1 }))
    vars.push(vvar(`v_sr${i}`, `pv_sr${i}`, `${i}# 子阵满发率`, `round(pv_irr / 9.5 * ${factors[i - 1]}, 0)`, { unit: '%', precision: 0 }))
  }

  // ---- 顶部 KPI 条 ----
  const kpi = (x: number, label: string, unit: string, varId: string, decimals: number) => [
    txt(`t_k_${label}`, x, 112, 435, 24, label, 13, '#8fa3c4'),
    nd(`c_fc_${label}`, 'flip-counter', x, 140, 435, 68, { name: label, props: { value: '0', unit, decimals }, bindings: [bd(varId, 'props.value')] }),
  ]

  // ---- 6 子阵卡（3×2） ----
  const dayKwh = ['1,842', '1,796', '1,913', '1,855', '1,804', '1,877']
  const irrGlow = rangeMap(
    { max: 300, value: '#4a3d1e' },
    { min: 300, max: 550, value: '#7c5d1f' },
    { min: 550, max: 750, value: '#b98a29' },
    { min: 750, value: '#f5b342' },
  )
  const cards: ReturnType<typeof nd>[] = []
  for (let i = 0; i < 6; i++) {
    const cx = 84 + (i % 3) * 394
    const cy = 384 + Math.floor(i / 3) * 284
    const n = i + 1
    cards.push(
      nd(`c_blk${n}`, 'rect', cx, cy, 372, 268, { name: `${n}# 子阵卡`, props: {}, style: { fill: '#18233d', stroke: 'rgba(255,255,255,0.05)', strokeWidth: 1, borderRadius: 10 } }),
      txt(`t_blk${n}`, cx + 20, cy + 14, 160, 26, `${n}# 子阵`, 16, '#d7e0ee'),
      nd(`c_sl${n}`, 'status-light', cx + 330, cy + 16, 22, 22, { name: `通讯${n}`, style: { color: '#22c55e' }, tooltip: `${n}# 子阵通讯正常` }),
      nd(`c_vi${n}`, 'var-display', cx + 20, cy + 52, 190, 48, {
        name: `组串电流${n}`, props: { prefix: '组串电流', unit: 'A', precision: 1 }, style: { color: '#e8d5ac' },
        bindings: [bd(strIds[i], 'props.value')], tooltip: `${n}# 子阵组串电流 {pv_str${n}} A`,
      }),
      txt(`t_kwh${n}`, cx + 20, cy + 112, 190, 26, `当日 ${dayKwh[i]} kWh`, 12, '#64748b'),
      nd(`c_gl${n}`, 'rect', cx + 222, cy + 52, 130, 152, {
        name: `阵列辉度${n}`, style: { fill: '#7c5d1f', borderRadius: 8 },
        bindings: [bd('v_irr', 'style.fill', 'color', irrGlow)],
        tooltip: `${n}# 子阵阵列辉度（随辐照 4 档变化）`,
      }),
      nd(`c_sr${n}`, 'progress', cx + 20, cy + 152, 190, 26, { name: `满发率${n}`, props: { percent: 0, precision: 0 }, bindings: [bd(srIds[i], 'props.percent')] }),
      txt(`t_inv${n}`, cx + 20, cy + 226, 332, 26, '逆变器 SUN2000-100KTL · 组串 24 路', 11, '#5b6b80'),
    )
  }

  const comps = [
    // ---- 顶带：标题栏 + 时钟 ----
    nd('c_title', 'title-bar', 0, 0, 1920, 88, { name: '标题栏', props: { text: '50MWp 光伏电站 · 集控总览', align: 'center' }, style: { color: '#f5b342' } }),
    nd('c_clock', 'clock', 1548, 18, 292, 52, { props: { showDate: true, showSeconds: true, layout: 'horizontal' }, style: { color: '#c8d2e0' } }),

    // ---- KPI 条 ----
    ...kpi(60, '今日发电量', 'MWh', 'v_kwh', 1),
    ...kpi(515, '当前出力', 'MW', 'v_out', 1),
    ...kpi(970, '等效利用小时', 'h', 'v_hours', 2),
    ...kpi(1425, '系统效率 PR', '%', 'v_pr', 1),

    // ---- 中央：子阵运行面板 ----
    nd('c_panel', 'rect', 60, 232, 1210, 800, { name: '子阵面板', style: { fill: '#141d33', stroke: 'rgba(245,181,66,0.10)', strokeWidth: 1, borderRadius: 12 } }),
    txt('t_sec1', 84, 252, 400, 30, '子阵运行 · 辐照联动', 15, '#8fa3c4'),
    nd('c_vd_irr', 'var-display', 84, 296, 340, 64, { name: '辐照度', props: { prefix: '辐照度', unit: 'W/m²', precision: 0 }, style: { color: '#f5b342' }, bindings: [bd('v_irr', 'props.value')], tooltip: '水平面辐照度 {pv_irr} W/m²' }),
    nd('c_vd_out', 'var-display', 444, 296, 340, 64, { name: '出力', props: { prefix: '当前出力', unit: 'MW', precision: 1 }, style: { color: '#46d5c0' }, bindings: [bd('v_out', 'props.value')], tooltip: '出力 = 辐照 × 0.052（虚拟变量表达式联动）' }),
    nd('c_vd_pr', 'var-display', 804, 296, 340, 64, { name: 'PR', props: { prefix: '系统效率 PR', unit: '%', precision: 1 }, style: { color: '#c8d2e0' }, bindings: [bd('v_pr', 'props.value')] }),

    ...cards,

    txt('t_note', 84, 960, 1140, 56, '子阵辉度块随辐照四档渐亮（<300 / 550 / 750 W/m²）；出力、PR、组串电流均为虚拟变量表达式，修改辐照即可观察全屏联动。', 12, '#5b6b80'),

    // ---- 右列 A：并网点 ----
    nd('c_panelA', 'rect', 1296, 232, 564, 300, { name: '并网点面板', style: { fill: '#141d33', stroke: 'rgba(255,255,255,0.05)', strokeWidth: 1, borderRadius: 12 } }),
    txt('t_secA', 1316, 252, 240, 30, '并网点', 15, '#8fa3c4'),
    nd('c_g_freq', 'gauge', 1326, 296, 250, 220, { name: '并网频率', props: { title: '并网频率', unit: 'Hz', min: 49.5, max: 50.5, precision: 2, textColor: '#c8d2e0' }, bindings: [bd('v_freq', 'props.value')] }),
    nd('c_vd_pf', 'var-display', 1600, 306, 240, 56, { name: '功率因数', props: { prefix: '功率因数', unit: '', precision: 3 }, style: { color: '#c8d2e0' }, bindings: [bd('v_pf', 'props.value')] }),
    txt('t_pf_note', 1600, 380, 240, 100, '35kV 并网\n宽频阻抗监测投运\n电能质量 A 级', 12, '#64748b'),

    // ---- 右列 B：逆变器温度趋势（大图） ----
    nd('c_panelB', 'rect', 1296, 556, 564, 476, { name: '温度面板', style: { fill: '#141d33', stroke: 'rgba(255,255,255,0.05)', strokeWidth: 1, borderRadius: 12 } }),
    txt('t_secB', 1316, 576, 400, 30, '逆变器温度（>71.5℃ 报警）', 15, '#8fa3c4'),
    nd('c_trend_t', 'trend-chart', 1312, 612, 532, 400, { name: '逆变器温度趋势', props: { title: '', unit: '℃' }, bindings: [bd('v_inv_t', 'props.data')] }),
  ]

  return demoDoc(
    '50MWp 光伏电站集控',
    '破晓琥珀主题：辐照驱动阵列辉度四档渐亮；出力/PR/组串电流表达式联动；并网频率与逆变器温度报警。',
    vars,
    [pg('p_main', '集控总览', 1920, 1080, comps, { lockPan: true, bg: '#0d1526' })],
    [
      alm('a_t', '逆变器温度超限', 'v_inv_t', '>', 71.5, 'critical', '逆变器温度超限：{value} ℃（阈值 71.5）'),
      alm('a_f', '并网频率偏低', 'v_freq', '<', 49.88, 'warn', '并网频率偏低：{value} Hz'),
    ],
  )
}
