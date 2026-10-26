/**
 * 点位 CSV 批量导入解析（工厂可用阶段一 Task 6）——纯函数，无 DOM / 无第三方库。
 *
 * 表头固定英文列名（首行，列序不限、可为子集，必填 key/label/type；address 允许为空，
 * 以支持 mock 变量的导出→导入往返）：
 *   key,label,type,address,unit,jsonPath,scale,offset,precision,bitIndex,writable,
 *   writeAddress,modbusDataType,modbusByteOrder,unitId,min,max
 *
 * 约定：
 * - 容忍 UTF-8 BOM 与 CRLF/LF（引号内换行按 RFC 4180 视为字段内容）；引号字段支持
 *   内嵌逗号与 "" 转义；未加引号的字段剔除两侧空格，引号内内容原样保留。
 * - **不设凭证列**（K11）：数据源凭证只在数据源表单配置，导入一律视为空。
 * - 行级校验对齐服务端 doc.py（key 字符集与长度、type/枚举、precision 0~6、
 *   bitIndex 0~63 且与 scale/offset/precision 互斥、unitId 0~255），保证导入产物
 *   不会被 3s 自动保存的整体 PUT 以 422 打回。
 * - 未在列名清单内的表头列报错（fail-fast：列名拼错导致数据静默丢弃比报错更危险）。
 * - 错误 message 为纯中文描述，物理行号放 `line` 字段（表头行 = 第 1 行）。
 */
import type { VariableDef } from '@/types/doc'

/** CSV 一行解析结果（仅含 CSV 中给出的列；可选字段缺省为 undefined） */
export interface PointCsvRow {
  key: string
  label: string
  type: 'number' | 'boolean' | 'string'
  address: string
  unit?: string
  jsonPath?: string
  scale?: number
  offset?: number
  precision?: number
  bitIndex?: number
  writable?: boolean
  writeAddress?: string
  modbusDataType?: VariableDef['modbusDataType']
  modbusByteOrder?: VariableDef['modbusByteOrder']
  unitId?: number
  /** min/max 同时给出才生成；只给其一为行错 */
  range?: { min: number; max: number } | null
}

/** 行级/表头级错误：line 为物理行号（表头 = 1） */
export interface PointCsvError {
  line: number
  message: string
}

export type PointCsvResult = { rows: PointCsvRow[]; errors: PointCsvError[] }

/** 全部合法列名（顺序即文档约定顺序，解析不依赖顺序） */
export const POINT_CSV_COLUMNS: readonly string[] = [
  'key', 'label', 'type', 'address', 'unit', 'jsonPath', 'scale', 'offset',
  'precision', 'bitIndex', 'writable', 'writeAddress', 'modbusDataType',
  'modbusByteOrder', 'unitId', 'min', 'max',
] as const

export const POINT_CSV_REQUIRED: readonly string[] = ['key', 'label', 'type'] as const

const VAR_KEY_RE = /^[A-Za-z0-9_.\-]+$/
const VAR_TYPES = new Set(['number', 'boolean', 'string'])
const MODBUS_DATA_TYPES = new Set(['int16', 'uint16', 'int32', 'uint32', 'float32'])
const MODBUS_BYTE_ORDERS = new Set(['ABCD', 'CDAB', 'BADC', 'DCBA'])
/** 列名 → 最大长度（对齐 doc.py Field 约束，超限必然 422，导入前拦截） */
const LENGTH_LIMITS: Readonly<Record<string, number>> = {
  key: 128, label: 128, unit: 32, address: 512, jsonPath: 256, writeAddress: 512,
}

/**
 * 变量表 → 点位 CSV（与 parsePointCsv 同格式，可往返）。
 *
 * 虚拟变量（expr）不导出：CSV 是「点表」口径，表达式没有列位；
 * 导出后再导入不会静默改坏虚拟变量（导入侧对 key 冲突的虚拟变量直接跳过并提示）。
 */
export function buildPointCsv(variables: VariableDef[]): string {
  const esc = (v: unknown): string => {
    const s = v === null || v === undefined ? '' : String(v)
    return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
  }
  const lines = [POINT_CSV_COLUMNS.join(',')]
  for (const v of variables) {
    if (v.expr) continue
    lines.push([
      v.key, v.label, v.type, v.address ?? '', v.unit ?? '', v.jsonPath ?? '',
      v.scale ?? '', v.offset ?? '', v.precision ?? '', v.bitIndex ?? '',
      v.writable ? 'true' : 'false', v.writeAddress ?? '',
      v.modbusDataType ?? '', v.modbusByteOrder ?? '', v.unitId ?? '',
      v.range?.min ?? '', v.range?.max ?? '',
    ].map(esc).join(','))
  }
  return `${lines.join('\n')}\n`
}

// ============ CSV 状态机（RFC 4180 子集） ============

interface RawRecord {
  /** 原始字段（未 trim；引号内内容已含转义还原） */
  fields: string[]
  /** 各字段是否曾用引号包裹（true = 不 trim，内容原样） */
  quoted: boolean[]
  /** 记录首字符所在物理行号（从 1 计） */
  line: number
}

/**
 * 逐字符状态机：引号内 `,` `\r` `\n` 属字段内容；`""` 还原为单个 `"`；
 * `\r\n` / `\n` / 孤立 `\r` 均为记录分隔；引号必须出现在字段首才开启引号模式
 * （引号外的引号按字面量容忍）。
 */
function lexCsvRecords(text: string): RawRecord[] {
  const records: RawRecord[] = []
  let fields: string[] = []
  let quotedFlags: boolean[] = []
  let field = ''
  let fieldQuoted = false
  let inQuotes = false
  let line = 1
  let recLine = 1

  const finishField = (): void => {
    fields.push(field)
    quotedFlags.push(fieldQuoted)
    field = ''
    fieldQuoted = false
  }
  const finishRecord = (): void => {
    if (fields.length > 0 || field !== '' || fieldQuoted) finishField()
    records.push({ fields, quoted: quotedFlags, line: recLine })
    fields = []
    quotedFlags = []
  }

  for (let i = 0; i < text.length; i++) {
    const ch = text[i]
    if (inQuotes) {
      if (ch === '"') {
        if (text[i + 1] === '"') {
          field += '"'
          i++ // 跳过转义的第二个引号
        } else {
          inQuotes = false
        }
      } else if (ch === '\r' || ch === '\n') {
        line++
        if (ch === '\r' && text[i + 1] === '\n') i++
        field += '\n' // 引号内换行归一为 \n
      } else {
        field += ch
      }
    } else if (ch === '"' && field === '' && !fieldQuoted) {
      inQuotes = true
      fieldQuoted = true
    } else if (ch === ',') {
      finishField()
    } else if (ch === '\r' || ch === '\n') {
      if (ch === '\r' && text[i + 1] === '\n') i++
      line++
      finishRecord()
      recLine = line
    } else {
      field += ch
    }
  }
  // 末行无换行符也要收尾（全空白文本则无记录）
  if (fields.length > 0 || field !== '' || fieldQuoted) finishRecord()
  return records
}

/** 记录 → 字符串单元格（引号字段原样，未引号字段 trim）；空记录返回 [] */
function cellsOf(rec: RawRecord): string[] {
  return rec.fields.map((f, i) => (rec.quoted[i] ? f : f.trim()))
}

function isBlank(cells: string[]): boolean {
  return cells.length <= 1 && (cells[0] ?? '') === ''
}

// ============ 解析入口 ============

export function parsePointCsv(text: string): PointCsvResult {
  const src = text.charCodeAt(0) === 0xfeff ? text.slice(1) : text // 容忍 UTF-8 BOM
  const records = lexCsvRecords(src).map((rec) => ({ rec, cells: cellsOf(rec) }))
  const nonBlank = records.filter((r) => !isBlank(r.cells))
  const errors: PointCsvError[] = []
  const rows: PointCsvRow[] = []

  // ---- 表头 ----
  const header = nonBlank[0]
  if (!header) {
    return { rows, errors: [{ line: 1, message: 'CSV 为空：缺少表头行' }] }
  }
  const known = new Set(POINT_CSV_COLUMNS)
  const seenCols = new Set<string>()
  for (const name of header.cells) {
    if (!known.has(name)) {
      errors.push({ line: 1, message: `表头含未知列：${name}（仅支持 ${POINT_CSV_COLUMNS.join('/')} 的子集）` })
    } else if (seenCols.has(name)) {
      errors.push({ line: 1, message: `表头列重复：${name}` })
    }
    seenCols.add(name)
  }
  const missing = POINT_CSV_REQUIRED.filter((c) => !seenCols.has(c))
  if (missing.length) {
    errors.push({ line: 1, message: `表头缺少必填列：${missing.join('/')}` })
  }
  if (errors.length) return { rows, errors } // 表头不可信时不解析数据行

  const colIdx = new Map<string, number>()
  header.cells.forEach((name, i) => colIdx.set(name, i))
  const colCount = header.cells.length

  // ---- 数据行 ----
  const seenKeys = new Set<string>()
  for (const { rec, cells } of nonBlank.slice(1)) {
    const rowErrs: string[] = []

    /** 取列值（不存在或留空均返回 ''） */
    const cell = (name: string): string => {
      const i = colIdx.get(name)
      return i === undefined ? '' : (cells[i] ?? '')
    }
    /** 数值列解析：留空返回 undefined；非法记行错并返回 undefined */
    const num = (name: string): number | undefined => {
      const s = cell(name)
      if (s === '') return undefined
      const v = Number(s)
      if (!Number.isFinite(v)) {
        rowErrs.push(`${name} 不是合法数值：${s}`)
        return undefined
      }
      return v
    }
    /** 整数域列解析（如 precision 0~6） */
    const int = (name: string, lo: number, hi: number): number | undefined => {
      const v = num(name)
      if (v === undefined) return undefined
      if (!Number.isInteger(v) || v < lo || v > hi) {
        rowErrs.push(`${name} 须为 ${lo}~${hi} 的整数：${cell(name)}`)
        return undefined
      }
      return v
    }

    if (cells.length !== colCount) {
      rowErrs.push(`字段数 ${cells.length} 与表头 ${colCount} 列不一致`)
    } else {
      // 必填与字符集
      const key = cell('key')
      const type = cell('type')
      if (key === '') rowErrs.push('key 不能为空')
      else if (!VAR_KEY_RE.test(key)) rowErrs.push(`key 含非法字符（仅允许字母/数字与 . _ -）：${key}`)
      for (const name of ['label', 'type'] as const) {
        if (cell(name) === '') rowErrs.push(`${name} 不能为空`)
      }
      if (type !== '' && !VAR_TYPES.has(type)) {
        rowErrs.push(`type 非法（仅 number/boolean/string）：${type}`)
      }
      // 长度上限（对齐服务端 Field 约束）
      for (const [name, limit] of Object.entries(LENGTH_LIMITS)) {
        const v = cell(name)
        if (v !== '' && v.length > limit) rowErrs.push(`${name} 长度超过上限 ${limit}`)
      }
      // key 重复（仅合法 key 计入查重，避免非法行级联误报）
      if (key !== '' && VAR_KEY_RE.test(key)) {
        if (seenKeys.has(key)) rowErrs.push(`key 重复：${key}`)
        else seenKeys.add(key)
      }
    }

    // 下列列级校验仅在列对齐时执行（错位行的取值不可信）
    if (cells.length === colCount) {
      const scale = num('scale')
      const offset = num('offset')
      const precision = int('precision', 0, 6)
      const bitIndex = int('bitIndex', 0, 63)
      const unitId = int('unitId', 0, 255)
      const minV = num('min')
      const maxV = num('max')

      let writable: boolean | undefined
      const ws = cell('writable')
      if (ws !== '') {
        const t = ws.toLowerCase()
        if (t === 'true' || t === '1') writable = true
        else if (t === 'false' || t === '0') writable = false
        else rowErrs.push(`writable 仅接受 true/false：${ws}`)
      }

      const mdt = cell('modbusDataType')
      if (mdt !== '' && !MODBUS_DATA_TYPES.has(mdt)) {
        rowErrs.push(`modbusDataType 非法（仅 int16/uint16/int32/uint32/float32）：${mdt}`)
      }
      const mbo = cell('modbusByteOrder')
      if (mbo !== '' && !MODBUS_BYTE_ORDERS.has(mbo)) {
        rowErrs.push(`modbusByteOrder 非法（仅 ABCD/CDAB/BADC/DCBA）：${mbo}`)
      }

      let range: { min: number; max: number } | null = null
      if (minV !== undefined || maxV !== undefined) {
        if (minV === undefined || maxV === undefined) {
          rowErrs.push('min/max 须同时填写')
        } else {
          range = { min: minV, max: maxV }
        }
      }

      // 互斥对齐服务端 _check_transform_rules（先在导入侧拦截，防整体 422）
      if (bitIndex !== undefined && rowErrs.length === 0) {
        if (cell('type') === 'string') {
          rowErrs.push('bitIndex 不允许配合 string 类型')
        } else if (scale !== undefined || offset !== undefined || precision !== undefined) {
          rowErrs.push('bitIndex 与 scale/offset/precision 互斥，不可同时配置')
        }
      }

      if (rowErrs.length === 0) {
        rows.push({
          key: cell('key'),
          label: cell('label'),
          type: cell('type') as PointCsvRow['type'],
          address: cell('address'),
          unit: cell('unit') || undefined,
          jsonPath: cell('jsonPath') || undefined,
          scale,
          offset,
          precision,
          bitIndex,
          writable,
          writeAddress: cell('writeAddress') || undefined,
          modbusDataType: (mdt || undefined) as PointCsvRow['modbusDataType'],
          modbusByteOrder: (mbo || undefined) as PointCsvRow['modbusByteOrder'],
          unitId,
          range: range ?? undefined,
        })
      }
    }

    for (const m of rowErrs) errors.push({ line: rec.line, message: m })
  }

  return { rows, errors }
}
