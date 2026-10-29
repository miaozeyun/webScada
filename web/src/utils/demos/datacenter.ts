/**
 * 演示案例十一：数据中心基础设施监控（行业 demo · 靛紫霓虹主题，2026-10-29）。
 *
 * 视觉主角：12 列机柜热力矩阵随 IT 负载实时变色，冷/热通道双温对冲，
 * PUE 由 IT 负载与制冷链路表达式推导；UPS 双路 + 电池后备 + 漏水/门禁联锁一屏总览。
 * 数据全部由 mock 源 + 虚拟变量表达式产生，不同时间常数叠加出真实波动层次。
 */
import type { ComponentNode } from '@/types/doc'
import { alm, bd, demoDoc, enumMap, mvar, nd, pg, rangeMap, txt, vvar } from './shared'

const ACCENT = '#c4b5fd'
const ACCENT_2 = '#22d3ee'
const ACCENT_3 = '#f0abfc'
const DIM = '#a78bfa'
const CARD_FILL = 'linear-gradient(160deg, rgba(24,16,48,0.94) 0%, rgba(9,6,22,0.9) 100%)'
const PANEL_FILL = 'linear-gradient(165deg, rgba(18,12,38,0.9) 0%, rgba(7,5,18,0.88) 100%)'

export function buildDatacenterDoc(): ReturnType<typeof demoDoc> {
  // ---- 变量：IT 负载为主驱动；PUE / 总功率 / 冷量由表达式推导 ----
  // 慢趋势（25min 周期，供近 1h 历史曲线）+ 业务抖动（合成值驱动 PUE/机柜热力）
  const it = mvar('d_it', 'd_it', 'IT 负载', { kind: 'sine', min: 660, max: 880, periodMs: 1500000, unit: 'kW', precision: 0 })
  const itGust = mvar('d_it_g', 'd_it_g', '负载抖动', { kind: 'sine', min: -16, max: 16, periodMs: 9000, unit: 'kW', precision: 0 })
  const cold = mvar('d_cold', 'd_cold', '冷通道温度', { kind: 'sine', min: 21.6, max: 24.6, periodMs: 70000, unit: '℃', precision: 1 })
  const hot = mvar('d_hot', 'd_hot', '热通道温度', { kind: 'sine', min: 30.2, max: 37.2, periodMs: 83000, unit: '℃', precision: 1 })
  const hum = mvar('d_hum', 'd_hum', '机房湿度', { kind: 'sine', min: 38, max: 62, periodMs: 150000, unit: '%RH', precision: 0 })
  const chw = mvar('d_chw', 'd_chw', '冷冻水供水温度', { kind: 'sine', min: 10.5, max: 13.5, periodMs: 101000, unit: '℃', precision: 1 })
  const ups1 = mvar('d_ups1', 'd_ups1', 'UPS-1 负载率', { kind: 'sine', min: 46, max: 72, periodMs: 95000, unit: '%', precision: 0 })
  const ups2 = mvar('d_ups2', 'd_ups2', 'UPS-2 负载率', { kind: 'sine', min: 42, max: 68, periodMs: 107000, unit: '%', precision: 0 })
  const water = mvar('d_water', 'd_water', '冷冻水流量', { kind: 'sine', min: 82, max: 124, periodMs: 76000, unit: 'm³/h', precision: 0 })
  const mode = mvar('d_mode', 'd_mode', '冷机运行模式', { kind: 'hold', def: 1, unit: '', precision: 0, writable: true })
  const emg = mvar('d_emg', 'd_emg', '应急制冷', { kind: 'hold', def: 0, unit: '', precision: 0, writable: true })

  const vars: ReturnType<typeof mvar>[] = [it, itGust, cold, hot, hum, chw, ups1, ups2, water, mode, emg]
  vars.push(
    vvar('d_it_eff', 'd_it_eff', 'IT 负载(合成)', 'round(max(500, min(1000, d_it + d_it_g)), 1)', { unit: 'kW', precision: 0 }),
    // _tick 为 Unix 秒：除以 9~25 得到几十秒级呼吸波动（不是小时级冻结）
    vvar('d_pue', 'd_pue', 'PUE', 'round(1.168 + (d_it_eff - 760) / 9000 + sin(_tick / 17) * 0.008, 3)', { precision: 3 }),
    vvar('d_total', 'd_total', '总功率', 'round(d_it_eff * d_pue, 1)', { unit: 'kW', precision: 1 }),
    vvar('d_cool', 'd_cool', '制冷功率', 'round(d_total - d_it_eff, 1)', { unit: 'kW', precision: 1 }),
    vvar('d_chwr', 'd_chwr', '冷冻水回水温度', 'round(d_chw + 6.8 + sin(_tick / 9) * 0.4, 2)', { unit: '℃', precision: 2 }),
    vvar('d_cop', 'd_cop', '冷机 COP', 'round(6.4 - (d_hot - 32) * 0.035 + sin(_tick / 13) * 0.12, 2)', { precision: 2 }),
    vvar('d_batt', 'd_batt', '电池 SOC', 'round(97.6 - sin(_tick / 25) * 1.2, 1)', { unit: '%', precision: 1 }),
    // 今日用电按当日秒数累计（0-1000kWh/日），零点归零
    vvar('d_energy', 'd_energy', '今日用电', 'round(8420 + (_tick % 86400) / 86.4, 0)', { unit: 'kWh', precision: 0 }),
    vvar('d_saving', 'd_saving', '今日 PUE 节电', 'round(486 + sin(_tick / 19) * 12, 0)', { unit: 'kWh', precision: 0 }),
    vvar('d_bak', 'd_bak', '电池后备时间', 'round(18.6 - (d_ups1 + d_ups2) / 12, 1)', { unit: 'min', precision: 1 }),
    vvar('d_itpct', 'd_itpct', 'IT 负载率', 'round(d_it_eff / 1000 * 100, 0)', { unit: '%', precision: 0 }),
    // 展示副本：报警态不糊住大表盘/KPI（状态灯仍绑原变量呈现告警）
    vvar('d_cold_v', 'd_cold_v', '冷通道读数', 'round(d_cold, 1)', { unit: '℃', precision: 1 }),
    vvar('d_pue_v', 'd_pue_v', 'PUE 读数', 'round(d_pue, 3)', { precision: 3 }),
    vvar('d_hum_v', 'd_hum_v', '湿度读数', 'round(d_hum, 0)', { unit: '%RH', precision: 0 }),
    vvar('d_ups1_v', 'd_ups1_v', 'UPS-1 读数', 'round(d_ups1, 0)', { unit: '%', precision: 0 }),
    vvar('d_ups2_v', 'd_ups2_v', 'UPS-2 读数', 'round(d_ups2, 0)', { unit: '%', precision: 0 }),
  )

  // 12 列机柜：负载 = IT 负载均摊 × 效率因子 + 相位噪声；温度由负载推出
  const rackFactors = [1.08, 0.94, 1.02, 0.88, 1.11, 0.97, 1.04, 0.91, 1.06, 0.86, 1.0, 0.95]
  for (let i = 1; i <= 12; i++) {
    const r = `d_r${i}`
    const t = `d_rt${i}`
    vars.push(vvar(r, `d_r${i}`, `R${String(i).padStart(2, '0')} 负载率`,
      `round(max(0, min(100, d_it_eff / 10.5 * ${rackFactors[i - 1]} + sin(_tick / ${7 + i * 0.6} + ${i * 0.7}) * 13)), 0)`,
      { unit: '%', precision: 0 }))
    vars.push(vvar(t, `d_rt${i}`, `R${String(i).padStart(2, '0')} 进风温度`,
      `round(19.8 + d_r${i} * 0.046 + sin(_tick / ${9 + i * 0.4} + ${i}) * 0.32, 1)`,
      { unit: '℃', precision: 1 }))
  }

  // ---- 顶部 KPI ----
  const kpi = (x: number, label: string, unit: string, varId: string, decimals: number, color: string) => [
    nd(`c_kpi${x}`, 'rect', x, 104, 430, 100, {
      name: `KPI·${label}`,
      style: { fill: CARD_FILL, stroke: 'rgba(196,181,253,0.18)', strokeWidth: 1, borderRadius: 10 },
    }),
    txt(`t_kpi${x}`, x + 18, 114, 300, 20, label, 12, DIM),
    nd(`c_fc${x}`, 'flip-counter', x + 16, 136, 398, 54, {
      name: label, props: { value: '0', unit, decimals, bg: 'transparent', border: 'transparent', color },
      bindings: [bd(varId, 'props.value')],
    }),
    nd(`c_kl${x}`, 'line', x + 18, 198, 120, 2, { name: `${label}强调线`, style: { fill: color } }),
  ]

  // ---- 机柜热力矩阵 ----
  const rackColor = rangeMap(
    { max: 45, value: '#22304f' },
    { min: 45, max: 60, value: '#4c1d95' },
    { min: 60, max: 75, value: '#7c3aed' },
    { min: 75, max: 88, value: '#a855f7' },
    { min: 88, value: ACCENT_2 },
  )
  const racks: ComponentNode[] = []
  for (let i = 1; i <= 12; i++) {
    const x = 64 + (i - 1) * 60
    racks.push(
      txt(`t_rk${i}`, x, 278, 46, 16, `R${String(i).padStart(2, '0')}`, 9, '#8b7bc4'),
      nd(`c_rk${i}`, 'rect', x, 298, 46, 286, {
        name: `机柜 R${String(i).padStart(2, '0')}`,
        style: { fill: '#4c1d95', borderRadius: 4 },
        bindings: [bd(`d_r${i}`, 'style.fill', 'color', rackColor)],
        tooltip: `R${String(i).padStart(2, '0')} 负载 {d_r${i}} %\n进风温度 {d_rt${i}} ℃`,
      }),
      nd(`c_rkv${i}`, 'var-display', x - 4, 590, 54, 22, {
        name: `R${String(i).padStart(2, '0')} 负载`, props: { prefix: '', unit: '%', precision: 0 },
        style: { color: '#d8ccff', fontSize: 10 },
        bindings: [bd(`d_r${i}`, 'props.value')],
      }),
    )
  }

  const comps: ComponentNode[] = [
    // ---- 顶带 ----
    nd('c_title', 'title-bar', 0, 0, 1920, 86, {
      name: '标题栏', props: { text: '云枢数据中心 · 基础设施监控总览', align: 'center' },
      style: { color: ACCENT },
    }),
    txt('t_sub', 40, 24, 460, 26, 'HYPERSCALE DC · INFRASTRUCTURE TWIN', 11, '#7c6bb0'),
    nd('c_clock', 'clock', 1560, 16, 320, 52, {
      props: { showDate: true, showSeconds: true, layout: 'horizontal' }, style: { color: '#e9e2ff' },
    }),

    // ---- KPI ----
    ...kpi(40, 'IT 负载', 'kW', 'd_it_eff', 0, ACCENT_2),
    ...kpi(510, 'PUE', '', 'd_pue_v', 3, ACCENT),
    ...kpi(980, '总功率', 'kW', 'd_total', 1, ACCENT_3),
    ...kpi(1450, '冷通道温度', '℃', 'd_cold_v', 1, '#7dd3fc'),

    // ---- 左列：机柜热力矩阵 ----
    nd('c_rackpanel', 'rect', 40, 220, 760, 430, {
      name: '机柜热力面板', style: { fill: PANEL_FILL, stroke: 'rgba(196,181,253,0.12)', strokeWidth: 1, borderRadius: 12 },
    }),
    txt('t_rksec', 60, 236, 420, 24, '机柜热力矩阵 · 12 列', 15, DIM),
    txt('t_rksub', 60, 258, 560, 16, '颜色 = 实时负载率：暗紫 <45% · 亮紫 60-75% · 青 88%+', 10, '#6d5fa0'),
    ...racks,
    txt('t_rkfoot', 64, 620, 620, 18, '单列 IT 负载约 55 ~ 90 kW · 进风温度 21 ~ 24 ℃', 10, '#6d5fa0'),

    // ---- 左列下：供配电链路 ----
    nd('c_pwrpanel', 'rect', 40, 666, 760, 374, {
      name: '供配电面板', style: { fill: PANEL_FILL, stroke: 'rgba(196,181,253,0.12)', strokeWidth: 1, borderRadius: 12 },
    }),
    txt('t_pwrsec', 60, 682, 420, 22, '供配电链路 · 2N 架构', 15, DIM),
    nd('c_sym_gen', 'symbol', 64, 716, 96, 96, { name: '市电', props: { symbolId: 'power/generator' }, style: { color: ACCENT_2 }, tooltip: '10kV 市电进线 · 双路互备' }),
    nd('c_sym_tr', 'transformer', 212, 712, 70, 104, { name: '变压器', style: { color: ACCENT }, tooltip: '干式变压器 2000kVA' }),
    nd('c_sym_ups', 'symbol', 336, 720, 92, 92, { name: 'UPS', props: { symbolId: 'power/capacitor' }, style: { color: ACCENT_3 }, tooltip: 'UPS 2N · 800kVA/台' }),
    nd('c_sym_bus', 'symbol', 520, 718, 110, 100, { name: '母线', props: { symbolId: 'power/busbar' }, style: { color: '#8b7bc4' }, tooltip: '低压母线槽 → 列头柜' }),
    nd('c_fb_gen', 'flow-bar', 164, 752, 44, 14, { name: '市电进线', props: { speed: 40, showArrow: true }, style: { color: ACCENT_2 } }),
    nd('c_fb_tr', 'flow-bar', 288, 752, 44, 14, { name: '变压器出线', props: { speed: 40, showArrow: true }, style: { color: ACCENT } }),
    nd('c_fb_ups', 'flow-bar', 434, 752, 82, 14, { name: 'UPS 出线', props: { speed: 50, showArrow: true }, style: { color: ACCENT_3 } }),
    nd('c_fb_bus', 'flow-bar', 634, 752, 130, 14, { name: '母线出线', props: { speed: 50, showArrow: true }, style: { color: '#8b7bc4' } }),
    txt('t_sym_gen', 64, 818, 100, 18, '10kV 市电', 10, '#7c6bb0'),
    txt('t_sym_tr', 208, 818, 100, 18, 'SCB13-2000', 10, '#7c6bb0'),
    txt('t_sym_ups', 340, 818, 100, 18, 'UPS 2N', 10, '#7c6bb0'),
    txt('t_sym_bus', 534, 818, 100, 18, '低压母线', 10, '#7c6bb0'),

    nd('c_ups1v', 'var-display', 64, 856, 160, 44, {
      name: 'UPS-1 负载', props: { prefix: 'UPS-1', unit: '%', precision: 0 }, style: { color: '#e9e2ff', fontSize: 15 },
      bindings: [bd('d_ups1_v', 'props.value')],
    }),
    nd('c_ups2v', 'var-display', 240, 856, 160, 44, {
      name: 'UPS-2 负载', props: { prefix: 'UPS-2', unit: '%', precision: 0 }, style: { color: '#e9e2ff', fontSize: 15 },
      bindings: [bd('d_ups2_v', 'props.value')],
    }),
    nd('c_battv', 'var-display', 416, 856, 160, 44, {
      name: '电池 SOC', props: { prefix: '电池', unit: '%', precision: 1 }, style: { color: '#86efac', fontSize: 15 },
      bindings: [bd('d_batt', 'props.value')],
    }),
    nd('c_bakv', 'var-display', 592, 856, 180, 44, {
      name: '后备时间', props: { prefix: '后备', unit: 'min', precision: 1 }, style: { color: ACCENT, fontSize: 15 },
      bindings: [bd('d_bak', 'props.value')],
    }),

    // 配电状态链
    nd('c_sl_grid', 'status-light', 64, 930, 18, 18, { name: '市电状态', style: { color: '#34d399' }, tooltip: '双路市电正常' }),
    txt('t_sl_grid', 88, 930, 110, 18, '市电正常', 10, '#8b7bc4'),
    nd('c_sl_gen', 'status-light', 214, 930, 18, 18, { name: '柴发状态', style: { color: '#fbbf24' }, tooltip: '柴油发电机热备' }),
    txt('t_sl_gen', 238, 930, 130, 18, '柴发热备', 10, '#8b7bc4'),
    nd('c_sl_leak', 'status-light', 384, 930, 18, 18, { name: '漏水检测', style: { color: '#34d399' }, tooltip: '冷通道漏水绳无告警' }),
    txt('t_sl_leak', 408, 930, 130, 18, '无漏水', 10, '#8b7bc4'),
    nd('c_sl_door', 'status-light', 534, 930, 18, 18, { name: '门禁状态', style: { color: '#34d399' }, tooltip: '机房双门互锁关闭' }),
    txt('t_sl_door', 558, 930, 130, 18, '门禁关闭', 10, '#8b7bc4'),
    nd('c_itpctv', 'var-display', 64, 970, 210, 34, {
      name: 'IT 负载率', props: { prefix: 'IT 负载率', unit: '%', precision: 0 }, style: { color: ACCENT_2, fontSize: 13 },
      bindings: [bd('d_itpct', 'props.value')],
    }),
    nd('c_energyv', 'var-display', 292, 970, 230, 34, {
      name: '今日用电', props: { prefix: '今日用电', unit: 'kWh', precision: 0 }, style: { color: ACCENT_3, fontSize: 13 },
      bindings: [bd('d_energy', 'props.value')],
    }),
    nd('c_savingv', 'var-display', 540, 970, 224, 34, {
      name: 'PUE 节电', props: { prefix: 'PUE 节电', unit: 'kWh', precision: 0 }, style: { color: '#86efac', fontSize: 13 },
      bindings: [bd('d_saving', 'props.value')],
    }),
    txt('t_pwrnote', 64, 1006, 700, 24, 'UPS 双路负载均衡由 STS 自动切换，任一市电失电零中断。', 10, '#5c4f87'),

    // ---- 中列：制冷链路 ----
    nd('c_coolpanel', 'rect', 820, 220, 520, 500, {
      name: '制冷链路面板', style: { fill: PANEL_FILL, stroke: 'rgba(196,181,253,0.12)', strokeWidth: 1, borderRadius: 12 },
    }),
    txt('t_coolsec', 840, 236, 420, 22, '制冷链路 · 冷机群控', 15, DIM),
    nd('c_sym_tower', 'symbol', 844, 270, 100, 100, { name: '冷却塔', props: { symbolId: 'hvac/cooling-tower' }, style: { color: ACCENT_2 }, tooltip: '横流式冷却塔 ×3（2 用 1 备）' }),
    nd('c_sym_chiller', 'symbol', 844, 416, 108, 108, { name: '冷水机组', props: { symbolId: 'hvac/chiller' }, style: { color: ACCENT }, tooltip: '离心式冷水机组 1200RT' }),
    nd('c_sym_pump', 'pump', 988, 438, 78, 78, {
      name: '冷冻水泵', style: { color: ACCENT_2 },
      anim: { rotate: { enabled: true, clockwise: true, periodMs: 1800 } },
      bindings: [bd('d_emg', 'style.color', 'color', enumMap({ '0': ACCENT_2, '1': '#fbbf24' }))],
      tooltip: '冷冻水泵（变频 42Hz）\n应急制冷状态：{d_emg}',
    }),
    nd('c_sym_ahu', 'symbol', 980, 270, 100, 100, { name: '空调末端', props: { symbolId: 'hvac/ahu' }, style: { color: ACCENT_3 }, tooltip: '列间空调 CRAH ×24' }),
    nd('c_fb_cw1', 'flow-bar', 888, 374, 14, 38, { name: '冷却水回水', props: { speed: 30, showArrow: false, vertical: true }, style: { color: ACCENT_2 }, bindings: [bd('d_water', 'props.speed', 'value', rangeMap({ max: 100, value: '30' }, { min: 100, value: '46' }))] }),
    nd('c_fb_chw1', 'flow-bar', 952, 466, 32, 16, { name: '冷冻水出机', props: { speed: 70, showArrow: true }, style: { color: ACCENT } }),
    nd('c_fb_chw2', 'flow-bar', 1020, 374, 14, 64, { name: '空调回水立管', props: { speed: 70, showArrow: false, vertical: true }, style: { color: ACCENT } }),
    nd('c_fb_chw3', 'flow-bar', 1084, 374, 14, 86, { name: '冷冻水立管', props: { speed: 70, showArrow: false, vertical: true }, style: { color: ACCENT_3 } }),

    nd('c_chwv', 'var-display', 1110, 300, 204, 34, {
      name: '冷冻水供水', props: { prefix: '冷冻水供', unit: '℃', precision: 1 }, style: { color: '#e9e2ff', fontSize: 13 },
      bindings: [bd('d_chw', 'props.value')],
    }),
    nd('c_chwrv', 'var-display', 1110, 338, 204, 34, {
      name: '冷冻水回水', props: { prefix: '冷冻水回', unit: '℃', precision: 1 }, style: { color: '#d8ccff', fontSize: 13 },
      bindings: [bd('d_chwr', 'props.value')],
    }),
    nd('c_hotv', 'var-display', 1110, 376, 204, 34, {
      name: '热通道', props: { prefix: '热通道', unit: '℃', precision: 1 }, style: { color: ACCENT_3, fontSize: 13 },
      bindings: [bd('d_hot', 'props.value')],
    }),
    nd('c_coolv', 'var-display', 1110, 414, 204, 34, {
      name: '制冷功率', props: { prefix: '制冷功率', unit: 'kW', precision: 1 }, style: { color: ACCENT_2, fontSize: 13 },
      bindings: [bd('d_cool', 'props.value')],
    }),
    nd('c_g_cop', 'gauge', 1080, 470, 232, 210, {
      name: 'COP 表', props: { title: '冷机 COP', unit: '', min: 4, max: 7.5, precision: 2, textColor: '#e9e2ff', color: ACCENT_2 },
      bindings: [bd('d_cop', 'props.value')],
    }),
    txt('t_coolfoot', 840, 642, 224, 64, '冷却水 32 / 37℃\n冷冻水 12 / 19℃\n冷却塔变频群控', 10, '#5c4f87'),

    // ---- 中列下：PUE 历史 ----
    nd('c_puepanel', 'rect', 820, 736, 520, 304, {
      name: 'PUE 面板', style: { fill: PANEL_FILL, stroke: 'rgba(196,181,253,0.12)', strokeWidth: 1, borderRadius: 12 },
    }),
    txt('t_puesec', 840, 752, 420, 22, 'IT 负载 · 近 1 小时', 15, DIM),
    // 用带 mock 的原始变量取历史：生成案例时已预置 6h 曲线
    nd('c_puehist', 'history-chart', 836, 780, 488, 248, {
      name: 'IT 负载历史', props: {
        variableId: 'd_it', title: '', unit: 'kW', rangeMs: 3600000,
        color: ACCENT, areaColor: 'rgba(196,181,253,0.16)',
      },
    }),

    // ---- 右列：环境与安防 ----
    nd('c_envpanel', 'rect', 1360, 220, 520, 420, {
      name: '环境面板', style: { fill: PANEL_FILL, stroke: 'rgba(196,181,253,0.12)', strokeWidth: 1, borderRadius: 12 },
    }),
    txt('t_envsec', 1380, 236, 420, 22, '环境与安防', 15, DIM),
    nd('c_g_cold', 'gauge', 1376, 262, 240, 190, {
      name: '冷通道表', props: { title: '冷通道', unit: '℃', min: 18, max: 28, precision: 1, textColor: '#e9e2ff', color: '#7dd3fc' },
      bindings: [bd('d_cold_v', 'props.value')],
    }),
    nd('c_g_hot', 'gauge', 1620, 262, 240, 190, {
      name: '热通道表', props: { title: '热通道', unit: '℃', min: 26, max: 42, precision: 1, textColor: '#e9e2ff', color: ACCENT_3 },
      bindings: [bd('d_hot', 'props.value')],
    }),
    nd('c_humv', 'var-display', 1376, 456, 232, 40, {
      name: '湿度', props: { prefix: '相对湿度', unit: '%RH', precision: 0 }, style: { color: '#e9e2ff', fontSize: 14 },
      bindings: [bd('d_hum_v', 'props.value')],
    }),
    nd('c_wspeed', 'var-display', 1624, 456, 236, 40, {
      name: '冷冻水流量', props: { prefix: '冷冻水流量', unit: 'm³/h', precision: 0 }, style: { color: '#d8ccff', fontSize: 14 },
      bindings: [bd('d_water', 'props.value')],
    }),
    nd('c_sl_cold', 'status-light', 1380, 516, 18, 18, {
      name: '冷通道告警灯', style: { color: '#34d399' },
      anim: { blink: { enabled: false, intervalMs: 600 } },
      bindings: [
        bd('d_cold', 'style.color', 'color', rangeMap({ max: 24, value: '#34d399' }, { min: 24, value: '#ef4444' })),
        bd('d_cold', 'anim.blinkOn', 'value', rangeMap({ max: 24, value: false }, { min: 24, value: true })),
      ],
      tooltip: '冷通道温度 {d_cold} ℃（>24 告警）',
    }),
    txt('t_sl_cold', 1404, 516, 120, 18, '冷通道 ≤24℃', 10, '#8b7bc4'),
    nd('c_sl_pue', 'status-light', 1540, 516, 18, 18, {
      name: 'PUE 告警灯', style: { color: '#34d399' },
      anim: { blink: { enabled: false, intervalMs: 600 } },
      bindings: [
        bd('d_pue', 'style.color', 'color', rangeMap({ max: 1.19, value: '#34d399' }, { min: 1.19, value: '#fbbf24' })),
        bd('d_pue', 'anim.blinkOn', 'value', rangeMap({ max: 1.19, value: false }, { min: 1.19, value: true })),
      ],
      tooltip: 'PUE {d_pue}（>1.19 预警）',
    }),
    txt('t_sl_pue', 1564, 516, 120, 18, 'PUE ≤1.19', 10, '#8b7bc4'),
    nd('c_sl_emg', 'status-light', 1700, 516, 18, 18, {
      name: '应急状态灯', style: { color: '#8b7bc4' },
      bindings: [bd('d_emg', 'style.color', 'color', enumMap({ '0': '#8b7bc4', '1': '#fbbf24' }))],
      tooltip: '应急制冷 {d_emg}（0=正常 1=投运）',
    }),
    txt('t_sl_emg', 1724, 516, 130, 18, '应急制冷', 10, '#8b7bc4'),
    txt('t_envnote', 1380, 560, 480, 64, 'Tier III+ 机房：冷通道封闭 + 行级空调；两路市电 + UPS 2N + 柴发后备，任一链路故障自动切换。', 10, '#5c4f87'),

    // ---- 右列下：UPS / 控制 ----
    nd('c_upspanel', 'rect', 1360, 656, 520, 384, {
      name: 'UPS 面板', style: { fill: PANEL_FILL, stroke: 'rgba(196,181,253,0.12)', strokeWidth: 1, borderRadius: 12 },
    }),
    txt('t_upssec', 1380, 672, 420, 22, 'UPS 双路 · 电池后备', 15, DIM),
    txt('t_u1', 1380, 704, 120, 18, 'UPS-1 负载', 10, '#8b7bc4'),
    nd('c_p1', 'progress', 1500, 704, 360, 20, { name: 'UPS-1 负载', props: { percent: 0, precision: 0, color: `linear-gradient(90deg, #7c3aed, ${ACCENT_2})` }, bindings: [bd('d_ups1_v', 'props.percent')] }),
    txt('t_u2', 1380, 744, 120, 18, 'UPS-2 负载', 10, '#8b7bc4'),
    nd('c_p2', 'progress', 1500, 744, 360, 20, { name: 'UPS-2 负载', props: { percent: 0, precision: 0, color: `linear-gradient(90deg, #7c3aed, ${ACCENT_2})` }, bindings: [bd('d_ups2_v', 'props.percent')] }),
    txt('t_bt', 1380, 784, 120, 18, '电池 SOC', 10, '#8b7bc4'),
    nd('c_pb', 'progress', 1500, 784, 360, 20, { name: '电池 SOC', props: { percent: 0, precision: 1, color: 'linear-gradient(90deg, #15803d, #86efac)' }, bindings: [bd('d_batt', 'props.percent')] }),
    nd('c_bak', 'var-display', 1380, 816, 220, 42, {
      name: '后备时间', props: { prefix: '后备时间', unit: 'min', precision: 1 }, style: { color: '#86efac', fontSize: 15 },
      bindings: [bd('d_bak', 'props.value')],
    }),
    nd('c_coolkw', 'var-display', 1620, 816, 240, 42, {
      name: '制冷功率', props: { prefix: '制冷功率', unit: 'kW', precision: 1 }, style: { color: ACCENT_2, fontSize: 15 },
      bindings: [bd('d_cool', 'props.value')],
    }),
    txt('t_mode', 1380, 884, 120, 18, '冷机模式', 10, '#8b7bc4'),
    nd('c_mode', 'multi-switch', 1500, 878, 360, 40, {
      name: '冷机模式', props: {
        variableId: 'd_mode',
        levels: '[{"value":0,"label":"手动"},{"value":1,"label":"自动"},{"value":2,"label":"群控"}]',
      },
    }),
    txt('t_emg', 1380, 940, 120, 18, '应急制冷', 10, '#8b7bc4'),
    nd('c_emg', 'switch', 1500, 932, 220, 40, {
      name: '应急制冷', props: { variableId: 'd_emg', onValue: 1, offValue: 0, confirm: true, label: '应急制冷' },
    }),
    txt('t_hint', 1380, 988, 480, 36, '冷机模式 / 应急制冷为可写变量，点击即下发并回环显示（演示反控链路）。', 10, '#5c4f87'),
  ]

  return demoDoc(
    '数据中心基础设施',
    '靛紫霓虹主题：12 列机柜热力矩阵实时变色，冷热通道双温、PUE/COP 表达式联动，UPS 2N + 电池后备 + 应急制冷反控。',
    vars,
    [pg('p_main', '数据中心总览', 1920, 1080, comps, { lockPan: true, bg: '#04030a', bgImage: '/bg/dc-core.svg', bgOpacity: 0.95 })],
    [
      alm('a_cold', '冷通道温度高', 'd_cold', '>', 24, 'warn', '冷通道温度高：{value} ℃（阈值 24）'),
      alm('a_pue', 'PUE 偏高', 'd_pue', '>', 1.19, 'warn', 'PUE 偏高：{value}（目标 ≤1.19）'),
      alm('a_ups1', 'UPS-1 负载高', 'd_ups1', '>', 70, 'info', 'UPS-1 负载高：{value} %'),
      alm('a_hum', '机房湿度高', 'd_hum', '>', 60, 'info', '机房湿度高：{value} %RH'),
    ],
  )
}
