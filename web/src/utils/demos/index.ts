/**
 * 演示案例集入口（对齐业界主流组态 演示站「画面案例」）：
 * 六个开箱即用案例（mock 数据源），一键导入后可直接预览/分享。
 */
import type { MockSpec, ProjectDoc } from '@/types/doc'
import { flushNow, seedSeries } from '@/runtime/history'
import { buildPvDoc } from './pv'
import { buildHeatingDoc } from './heating'
import { buildAirDoc } from './air'
import { buildWwtpDoc } from './wwtp'
import { buildPowerDoc } from './power'
import { buildTrajectoryDoc } from './trajectory'
import { buildMobileDoc } from './mobile'
import { buildMqttTestDoc } from './mqttTest'
import { buildControlDoc } from './control'
import { buildWindDoc } from './wind'
import { buildDatacenterDoc } from './datacenter'
import { buildLineDoc } from './line'

export interface DemoCase {
  key: string
  name: string
  description: string
  build: () => ProjectDoc
  /** 演示只读（2026-10-29）：旗舰案例生成后只读——编辑器可体验，改动不落库；定制走复制工程 */
  readonly?: boolean
}

export const DEMO_CASES: DemoCase[] = [
  {
    key: 'wind',
    name: '海上风电集控（旗舰视觉）',
    description: '深海青主题：风速立方律驱动 6 台机组功率与叶轮变速，数字孪生阵列 + 并网/联锁三层下钻',
    build: buildWindDoc,
    readonly: true,
  },
  {
    key: 'datacenter',
    name: '数据中心基础设施（旗舰视觉）',
    description: '靛紫霓虹主题：12 列机柜热力矩阵实时变色，冷热通道双温、PUE/COP 联动，UPS 2N 与应急制冷反控',
    build: buildDatacenterDoc,
    readonly: true,
  },
  {
    key: 'line',
    name: '智能制造产线（旗舰视觉）',
    description: '琥珀产线主题：6 工位三态联动、线速驱动节拍/产量/能耗，OEE 下钻 + 线体模式/目标节拍/急停反控',
    build: buildLineDoc,
    readonly: true,
  },
  {
    key: 'pv',
    name: '光伏电站集控',
    description: '行业 demo·破晓琥珀：辐照驱动阵列辉度四档渐亮，出力/PR/组串电流表达式联动，并网点频率报警',
    build: buildPvDoc,
  },
  {
    key: 'heating',
    name: '无人值守换热站',
    description: '行业 demo·红蓝双温：一次/二次网语义色管网对冲流动，气候补偿曲线，供水超限条件弹框一键降阀位',
    build: buildHeatingDoc,
  },
  {
    key: 'air',
    name: '空压站集控',
    description: '行业 demo·灰蓝能量橙：三机待机/加载/卸载三态联动（多档反控），母管压力呼吸表盘，露点与压力报警',
    build: buildAirDoc,
  },
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
