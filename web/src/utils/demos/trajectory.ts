/**
 * 演示案例三：轨迹运动 · 动效演示。
 * 覆盖：轨迹运动（loop/pingpong + anim.moveOn 变量启停）/ 管道流动 /
 * 旋转启停与变量控转速（anim.rotatePeriod）/ 开关反控（hold 回环保持）。
 */
import { bd, demoDoc, enumMap, mvar, nd, pg, txt } from './shared'

export function buildTrajectoryDoc(): ReturnType<typeof demoDoc> {
  const V = {
    run: 'v_run', ball: 'v_ball', conveyor: 'v_conveyor',
    fanRun: 'v_fan_run', fanPeriod: 'v_fan_period',
  }

  const vars = [
    mvar(V.run, 'traj.run', '产线运行', { kind: 'hold', def: 1, writable: true }),
    mvar(V.ball, 'traj.ball', '小球运动', { kind: 'hold', def: 1, writable: true }),
    mvar(V.conveyor, 'traj.conveyor', '传送带速度', { kind: 'square', min: 0, max: 90, periodMs: 9000 }),
    mvar(V.fanRun, 'traj.fan_run', '风机运行', { kind: 'square', min: 0, max: 1, periodMs: 6000 }),
    mvar(V.fanPeriod, 'traj.fan_period', '风机转速周期', { kind: 'sine', min: 1200, max: 6000, periodMs: 20000 }),
  ]

  const comps = [
    txt('t_title', 40, 16, 700, 48, '轨迹运动 · 动效演示', 26, '#e2e8f0'),
    txt('t_hint', 40, 62, 900, 26, '小车匀速循环 · 小球抛物线往返 · 风机转速随变量实时变化（拖动开关体验）', 13, '#64748b'),

    // ---- 传送带 + 小车 ----
    nd('c_pipe', 'pipe', 60, 380, 920, 30, { name: '传送带', style: { color: '#64748b' } }),
    nd('c_flow', 'flow-bar', 60, 415, 920, 26, { name: '传送带流', props: { speed: 90, showArrow: true }, bindings: [bd(V.conveyor, 'props.speed')] }),
    nd('c_truck', 'text', 60, 300, 100, 76, {
      name: '巡检小车',
      props: { text: '🚚', ellipsis: false },
      style: { fontSize: 52 },
      anim: { move: { enabled: false, path: 'M 0 0 L 820 0', periodMs: 12000, mode: 'loop' } },
      bindings: [bd(V.run, 'anim.moveOn')],
      tooltip: '轨道巡检小车\n产线运行：{traj.run}',
    }),

    // ---- 小球（抛物线往返 + 自转） ----
    nd('c_ball', 'circle', 60, 140, 56, 56, {
      name: '抛送小球',
      style: { fill: '#38bdf8' },
      anim: {
        move: { enabled: false, path: 'M 0 180 Q 460 -220 920 180', periodMs: 7000, mode: 'pingpong' },
        rotate: { enabled: false, clockwise: true, periodMs: 1400 },
      },
      bindings: [bd(V.ball, 'anim.moveOn'), bd(V.ball, 'anim.rotateOn')],
      tooltip: '气力抛送小球（往返）\n运动开关：{traj.ball}',
    }),

    // ---- 风机（变量控转速） ----
    nd('c_fan', 'motor', 1040, 160, 130, 130, {
      name: '变频风机',
      style: { color: '#38bdf8' },
      anim: { rotate: { enabled: true, clockwise: true, periodMs: 3000 } },
      bindings: [bd(V.fanRun, 'anim.rotateOn'), bd(V.fanPeriod, 'anim.rotatePeriod'), bd(V.fanRun, 'style.color', 'color', enumMap({ '1': '#22c55e', '0': '#64748b' }))],
      tooltip: '变频风机（转速随变量变化）\n旋转周期：{traj.fan_period} ms/圈',
    }),
    nd('c_vd_fan', 'var-display', 1020, 300, 170, 48, { name: '风机周期', props: { prefix: '周期', unit: 'ms/圈', precision: 0 }, bindings: [bd(V.fanPeriod, 'props.value')] }),

    // ---- 水泵 ----
    nd('c_pump', 'pump', 1040, 420, 110, 110, {
      name: '工艺水泵', style: { color: '#38bdf8' },
      anim: { rotate: { enabled: true, clockwise: true, periodMs: 2200 } },
      bindings: [bd(V.run, 'anim.rotateOn')],
    }),
    nd('c_pipe2', 'pipe', 60, 500, 380, 24, { name: '出水管', style: { color: '#64748b' } }),
    nd('c_flow2', 'flow-bar', 60, 528, 380, 22, { name: '出水流', props: { speed: 60 }, bindings: [bd(V.conveyor, 'props.speed')] }),

    // ---- 控制区 ----
    txt('t_ctrl', 60, 580, 300, 28, '运行控制（hold 反控回环）', 16, '#94a3b8'),
    nd('c_sw_run', 'switch', 60, 614, 220, 44, { name: '产线开关', props: { variableId: V.run, onValue: 1, offValue: 0, confirm: false, label: '小车/水泵' } }),
    nd('c_sw_ball', 'switch', 300, 614, 200, 44, { name: '小球开关', props: { variableId: V.ball, onValue: 1, offValue: 0, confirm: false, label: '小球' } }),
    nd('c_light1', 'status-light', 520, 616, 36, 36, { name: '运行灯', bindings: [bd(V.run, 'style.color', 'color', enumMap({ '1': '#22c55e', '0': '#64748b' }))] }),
    nd('c_light2', 'status-light', 566, 616, 36, 36, { name: '风机灯', bindings: [bd(V.fanRun, 'style.color', 'color', enumMap({ '1': '#f59e0b', '0': '#64748b' }))] }),
    txt('t_hint2', 60, 668, 900, 26, '说明：anim.moveOn / anim.rotateOn / anim.rotatePeriod 均为运行态绑定通道，静态动画配置被绑定覆盖（K12）', 13, '#64748b'),
  ]

  return demoDoc(
    '案例三 · 轨迹运动',
    '轨迹运动演示：小车匀速循环、小球抛物线往返、风机变量控转速、传送带流动；开关为 hold 型 mock 反控回环',
    vars,
    [pg('pg_traj', '轨迹演示', 1280, 760, comps, { lockPan: true })],
  )
}
