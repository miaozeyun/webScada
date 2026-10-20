/**
 * 演示案例集入口（对齐 BY组态 演示站「画面案例」）：
 * 六个开箱即用案例（mock 数据源），一键导入后可直接预览/分享。
 */
import type { MockSpec, ProjectDoc } from '@/types/doc'
import { flushNow, seedSeries } from '@/runtime/history'
import { buildWwtpDoc } from './wwtp'
import { buildPowerDoc } from './power'
import { buildTrajectoryDoc } from './trajectory'
import { buildMobileDoc } from './mobile'
import { buildMqttTestDoc } from './mqttTest'
import { buildControlDoc } from './control'

export interface DemoCase {
  key: string
  name: string
  description: string
  build: () => ProjectDoc
}

export const DEMO_CASES: DemoCase[] = [
  {
    key: 'wwtp',
    name: '污水处理系统',
    description: '综合旗舰：水池/泵/管道流动/仪表/图表/报警/右键菜单/条件弹框/输入框指令',
    build: buildWwtpDoc,
  },
  {
    key: 'power',
    name: '电力系统',
    description: '变电站单线图：二次接线图元/母线/分闸闪烁/遥测仪表/遥控分合闸',
    build: buildPowerDoc,
  },
  {
    key: 'trajectory',
    name: '轨迹运动',
    description: '小车循环/小球往返/风机变量控转速/传送带流动',
    build: buildTrajectoryDoc,
  },
  {
    key: 'mobile',
    name: '移动端（竖屏/横屏）',
    description: '自定义分辨率双页：375×812 竖屏控制页 + 812×375 横屏总览',
    build: buildMobileDoc,
  },
  {
    key: 'mqtt',
    name: 'MQTT 通讯测试',
    description: '订阅回读/发布写入/链路状态/报文曲线（mock 回环演示）',
    build: buildMqttTestDoc,
  },
  {
    key: 'control',
    name: '反控指令集',
    description: '双页：多档/确认开关/输入框指令/事件行为六件套/条件弹框/悬停信息',
    build: buildControlDoc,
  },
]

/** 按 mock 波形回填某时刻的近似值（与 runtime/sources.ts 公式同口径；random 用确定性伪随机） */
function mockValueAt(spec: MockSpec, t: number, seed: number): number | null {
  switch (spec.kind) {
    case 'hold':
      return null
    case 'sine':
      return spec.min + (spec.max - spec.min) * (0.5 + 0.5 * Math.sin((2 * Math.PI * t) / spec.periodMs))
    case 'ramp': {
      const p = (t % spec.periodMs) / spec.periodMs
      return p < 0.5 ? spec.min + (spec.max - spec.min) * p * 2 : spec.max - (spec.max - spec.min) * (p - 0.5) * 2
    }
    case 'square': {
      const p = (t % spec.periodMs) / spec.periodMs
      return p < (spec.duty ?? 0.5) ? spec.onValue : spec.offValue
    }
    case 'random': {
      const x = Math.sin(seed * 9301 + Math.floor(t / 60000) * 49297) * 233280
      const r = x - Math.floor(x)
      return spec.min + r * (spec.max - spec.min)
    }
  }
}

/** 生成案例后预置最近 6 小时历史（分钟桶），打开案例即可看到历史/趋势曲线 */
export function seedCaseHistory(doc: ProjectDoc, hours = 6): void {
  const now = Date.now()
  let seed = 1
  for (const v of doc.variables) {
    if (!v.mock) continue
    seed++
    const points: [number, number][] = []
    for (let m = hours * 60; m >= 0; m--) {
      const t = now - m * 60_000
      const val = mockValueAt(v.mock, t, seed)
      if (val !== null) points.push([t, val])
    }
    if (points.length) seedSeries(v.id, points)
  }
  flushNow()
}
