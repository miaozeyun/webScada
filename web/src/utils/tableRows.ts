/**
 * 表格组件行构造纯函数（工厂可用阶段二 Task 6 实时表格 / Task 7 历史表格共用落点）。
 * 纯函数无 Vue/Pinia 依赖：组件侧以 getVar 闭包注入运行态变量池（useRuntimeStore，K12 同源通道），
 * 值均为服务端/引擎换算后的工程值（K9 口径），此处只做展示格式化与状态标记。
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
