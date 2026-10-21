/**
 * 行业图元资产库（M9 批次1，对标业界主流组态「图元图库」）。
 * - SVG 全部自绘简笔工业风（stroke=currentColor，fill 以 none 为主），版权红线：禁止引入第三方素材
 * - 目录即分类：valve/ pump/ tank/ hvac/ pipe-fitting/ wtp/ power/ instrument/ misc/
 * - symbolId = '<目录>/<文件名>'（如 valve/globe）；新增 SVG 文件即自动入库（glob eager 收集，零代码注册）
 * - defaultSize 按 viewBox 宽高比推导（最长边 120px 等比）
 */
const raws = import.meta.glob('./*/*.svg', { query: '?raw', import: 'default', eager: true }) as Record<
  string,
  string
>

export interface SymbolAsset {
  id: string
  category: string
  label: string
  svg: string
  /** 建议默认尺寸（设计 px） */
  w: number
  h: number
}

export const CATEGORY_LABELS: Record<string, string> = {
  valve: '阀门',
  pump: '泵类',
  tank: '罐体',
  hvac: '暖通风',
  'pipe-fitting': '管件',
  wtp: '水处理',
  power: '电力',
  instrument: '仪表',
  misc: '其他',
  decor: '装饰',
}

/** id → 中文名（新素材务必同步登记，缺省回退显示 id） */
const NAME_MAP: Record<string, string> = {
  // 阀门
  'valve/gate': '闸阀',
  'valve/globe': '截止阀',
  'valve/ball': '球阀',
  'valve/check': '止回阀',
  'valve/plug': '旋塞阀',
  'valve/diaphragm': '隔膜阀',
  'valve/solenoid': '电磁阀',
  'valve/safety': '安全阀',
  'valve/three-way': '三通阀',
  'valve/angle': '角阀',
  'valve/motorized': '电动阀',
  // 泵类
  'pump/submersible': '潜水泵',
  'pump/metering': '计量泵',
  'pump/screw': '螺杆泵',
  'pump/vacuum': '真空泵',
  'pump/gear': '齿轮泵',
  'pump/vertical': '管道泵',
  // 罐体
  'tank/vertical': '立式罐',
  'tank/horizontal': '卧式罐',
  'tank/cone-bottom': '锥底罐',
  'tank/sphere': '球罐',
  'tank/air-receiver': '储气罐',
  'tank/open-basin': '敞口池',
  // 暖通风
  'hvac/fan': '离心风机',
  'hvac/axial-fan': '轴流风机',
  'hvac/ahu': '空调机组',
  'hvac/cooling-tower': '冷却塔',
  'hvac/heat-exchanger': '换热器',
  'hvac/heater': '电加热器',
  'hvac/chiller': '冷水机组',
  'hvac/damper': '风阀',
  // 管件
  'pipe-fitting/elbow': '弯头',
  'pipe-fitting/tee': '三通',
  'pipe-fitting/cross': '四通',
  'pipe-fitting/reducer': '异径管',
  'pipe-fitting/flange': '法兰',
  'pipe-fitting/blank': '盲板',
  'pipe-fitting/strainer': 'Y型过滤器',
  'pipe-fitting/flexible': '软连接',
  // 水处理
  'wtp/bar-screen': '格栅',
  'wtp/aerator': '曝气盘',
  'wtp/mixer': '搅拌机',
  'wtp/scraper': '刮泥机',
  'wtp/dosing-pump': '加药泵',
  'wtp/sand-filter': '砂滤罐',
  'wtp/mbr': 'MBR膜',
  'wtp/uv': '紫外消毒',
  'wtp/decanter': '滗水器',
  // 电力
  'power/generator': '发电机',
  'power/surge-arrester': '避雷器',
  'power/busbar': '母线',
  'power/capacitor': '电容器',
  'power/reactor': '电抗器',
  'power/fuse': '熔断器',
  'power/load-switch': '负荷开关',
  'power/cable-end': '电缆头',
  // 仪表
  'instrument/flow-meter': '流量计',
  'instrument/mag-flow': '电磁流量计',
  'instrument/level-gauge': '液位计',
  'instrument/pressure-gauge': '压力表',
  'instrument/thermometer': '温度计',
  'instrument/analyzer': '分析仪',
  // 其他
  'misc/fire-hydrant': '消防栓',
  'misc/extinguisher': '灭火器',
  'misc/camera': '摄像头',
  'misc/beacon': '警示灯',
  'misc/loudspeaker': '喇叭',
  'misc/gateway': '边缘网关',
  // 装饰（M9 批次3：大画幅边框/底纹，opacity 建议配合降低）
  'decor/frame-tech': '科技边框',
  'decor/frame-corner': '四角边框',
  'decor/panel-card': '容器框',
  'decor/hud-bar': '状态底栏',
  'decor/divider-wave': '分隔线',
  'decor/grid-dots': '点阵底纹',
  'decor/arc-glow': '弧光角饰',
}

/** 取 viewBox 宽高（缺省 100×100），按最长边 120px 等比给建议尺寸 */
function suggestSize(svg: string): { w: number; h: number } {
  const m = svg.match(/viewBox="([\d.\s-]+)"/)
  if (!m) return { w: 120, h: 120 }
  const n = m[1].trim().split(/\s+/).map(Number)
  const vw = n[2] || 100
  const vh = n[3] || 100
  return vw >= vh ? { w: 120, h: Math.max(24, Math.round((120 * vh) / vw)) } : { w: Math.max(24, Math.round((120 * vw) / vh)), h: 120 }
}

export const symbolAssets: SymbolAsset[] = Object.entries(raws)
  .map(([path, svg]) => {
    // './valve/globe.svg' → id 'valve/globe'
    const m = path.match(/^\.\/(.+)\/(.+)\.svg$/)
    if (!m) return null
    const [, category, name] = m
    const id = `${category}/${name}`
    return { id, category, label: NAME_MAP[id] ?? id, svg, ...suggestSize(svg) } satisfies SymbolAsset
  })
  .filter((s): s is SymbolAsset => s !== null)
  .sort((a, b) => a.category.localeCompare(b.category) || a.label.localeCompare(b.label, 'zh'))

const symbolMap = new Map(symbolAssets.map((s) => [s.id, s]))

export function getSymbol(id: string): SymbolAsset | undefined {
  return symbolMap.get(id)
}
