/**
 * 表格组件行构造纯函数（工厂可用阶段二 Task 6 实时表格 / Task 7 历史表格共用落点）。
 * 纯函数无 Vue/Pinia 依赖：实时表格以 getVar 闭包注入运行态变量池（useRuntimeStore，K12 同源通道），
 * 历史表格消费 queryHistory 返回的 [ts, value][] 序列；值均为服务端/引擎换算后的工程值（K9 口径），
 * 此处只做降采样、展示格式化与状态标记。
 */
import type { ValueQuality } from '@/types/doc'

/** 变量单元格：getVar(key) 的返回形态（value=工程值；quality 质量位；alarm 报警中） */
export interface RealtimeVarCell {
  value: number | boolean | string | null
  quality: ValueQuality
  alarm: boolean
  /** number 值的小数位；null/缺省回落 2（与 var-display 缺省一致） */
  precision?: number | null
}

/** 实时表格数据列定义（columns JSON 的解析形态）：key=变量 key，label=行首显示名 */
export interface RealtimeColumnDef {
  key: string
  label: string
  /** 覆盖变量 precision（分享页无变量定义可回落时，在列内显式指定） */
  precision?: number | null
  /** 覆盖变量单位（showUnit 时拼在值后） */
  unit?: string | null
}

/** 行构造结果：text 为格式化显示值；dim/alarm 驱动行样式（组件侧报警色优先于灰显） */
export interface RealtimeRow {
  key: string
  label: string
  /** number 按 precision 格式化；boolean/string 原样字符串化；无值占位 '--' */
  text: string
  value: number | boolean | string | null
  quality: ValueQuality
  /** quality !== 'good'：值超时/不可信，灰显标记 */
  dim: boolean
  /** 报警中：行警示色标记 */
  alarm: boolean
}

/** 值 → 显示文本：number 按小数位（非有限数原样 String）；boolean/string 原样；空值占位 '--' */
function formatValue(v: number | boolean | string | null, precision: number): string {
  if (v === null || v === undefined) return '--'
  if (typeof v === 'number') return Number.isFinite(v) ? v.toFixed(precision) : String(v)
  return String(v)
}

/**
 * 实时表格行构造：每个数据列（变量 key）一行。
 * - 未知 key（变量不存在/已删除）→ 空行占位 '--'，不灰显不报警（占位本身已表达无数据）
 * - quality !== 'good' → dim=true（stale 保留末值灰显 / bad 值不可信灰显，03 §2.10 口径）
 * - alarm=true 独立于质量位（服务端 q != 'good' 不判定报警，两者不互斥也不联动）
 */
export function buildRealtimeRows(
  columns: Array<{ key: string; label: string }>,
  getVar: (key: string) => RealtimeVarCell | undefined,
): RealtimeRow[] {
  return columns.map((col) => {
    const cell = getVar(col.key)
    if (!cell) {
      return { key: col.key, label: col.label, text: '--', value: null, quality: 'good', dim: false, alarm: false }
    }
    const precision = typeof cell.precision === 'number' && Number.isFinite(cell.precision) ? cell.precision : 2
    return {
      key: col.key,
      label: col.label,
      text: formatValue(cell.value, precision),
      value: cell.value,
      quality: cell.quality,
      dim: cell.quality !== 'good',
      alarm: cell.alarm === true,
    }
  })
}

// ============ 历史表格（工厂可用阶段二 Task 7：区间桶快照） ============

/** 历史表格行：每行 = 一个时间桶，代表点为桶内最后一点（last 口径，与服务端 agg=last 同构） */
export interface HistoryRow {
  /** 桶代表点时间戳（epoch ms，桶内最后一点） */
  ts: number
  /** 时间标签：序列跨度 ≤ 24h 用 HH:mm，> 24h 用 MM-DD HH:mm（本地时区，两位补零） */
  time: string
  /** 值显示文本（toFixed(2)，与历史表格列口径一致） */
  text: string
  /** 桶内最后一点的工程值（服务端已换算，K9 口径） */
  value: number
}

/** 两位补零 */
const two = (n: number): string => String(n).padStart(2, '0')

/** 毫秒 → 时间标签：withDate 时带 MM-DD 前缀（跨天跨度须区分日期） */
function formatHistoryTime(ts: number, withDate: boolean): string {
  const d = new Date(ts)
  const hm = `${two(d.getHours())}:${two(d.getMinutes())}`
  return withDate ? `${two(d.getMonth() + 1)}-${two(d.getDate())} ${hm}` : hm
}

/** 序列跨度超过 24h 的时间标签带日期阈值（毫秒） */
const DAY_MS = 24 * 3600_000

/**
 * 历史表格行构造：把（升序）时间序列降采样为至多 bucketCount 行。
 * - 等距分桶：桶宽 = (last.ts - first.ts) / bucketCount，点归桶 floor((ts-first)/桶宽)，末桶封顶防溢出；
 *   桶内后到覆盖先到 → 每桶保留最后一点（last 口径，与 queryHistory agg='last' 一致，二次分桶仅兜稀疏/原始序列）
 * - 空桶不出行（不虚增 '--' 行）；空/未定义 series、bucketCount < 1 → 空行数组
 * - 时间标签随跨度自适应：≤ 24h 仅 HH:mm，> 24h 带 MM-DD；值统一 toFixed(2)
 */
export function buildHistoryRows(
  series: ReadonlyArray<[number, number]> | undefined,
  bucketCount: number,
): HistoryRow[] {
  if (!series || series.length === 0 || !(bucketCount >= 1)) return []
  const firstTs = series[0][0]
  const lastTs = series[series.length - 1][0]
  // 单点/全同刻序列：跨度 0 无分桶意义，末点独占一行（避免 0 除）
  if (lastTs <= firstTs) {
    const [ts, v] = series[series.length - 1]
    return [{ ts, time: formatHistoryTime(ts, false), text: v.toFixed(2), value: v }]
  }
  const width = (lastTs - firstTs) / bucketCount
  const buckets: Array<[number, number]> = []
  for (const [ts, v] of series) {
    const idx = Math.min(Math.floor((ts - firstTs) / width), bucketCount - 1)
    buckets[idx] = [ts, v]
  }
  const withDate = lastTs - firstTs > DAY_MS
  return buckets
    .filter((b): b is [number, number] => !!b)
    .map(([ts, v]) => ({ ts, time: formatHistoryTime(ts, withDate), text: v.toFixed(2), value: v }))
}
