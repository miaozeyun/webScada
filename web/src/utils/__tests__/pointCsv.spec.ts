/**
 * 点位 CSV 批量导入解析测试（工厂可用阶段一 Task 6）。
 * 契约见 docs/superpowers/plans/2026-10-22-factory-usability-phase1.md Task 6：
 * - 表头固定英文列名（列序不限、可为 17 列子集），必填 key/label/type（address 可空）；
 * - 自写状态机支持引号字段（内嵌逗号 / "" 转义）；容忍 UTF-8 BOM 与 CRLF；
 * - 行级校验对齐服务端 doc.py（key 字符集、枚举、数值域、bitIndex 互斥），
 *   保证导入产物不会在 3s 自动保存时被整体 422 打回。
 * 运行：cd web && npx vitest run src/utils/__tests__/pointCsv.spec.ts
 */
import { describe, expect, it } from 'vitest'

import { POINT_CSV_COLUMNS, buildPointCsv, parsePointCsv } from '@/utils/pointCsv'
import type { VariableDef } from '@/types/doc'

const HEADER = POINT_CSV_COLUMNS.join(',')

/** 按表头列序拼一行数据（未给的列留空），便于用例聚焦被测列 */
function line(...fields: string[]): string {
  return POINT_CSV_COLUMNS.map((_, i) => fields[i] ?? '').join(',')
}

describe('parsePointCsv 正常解析', () => {
  it('正常 3 行：全字段精确断言（含 scale=0.1、range 1~100、modbusDataType=float32）', () => {
    const csv = [
      HEADER,
      line('m_temp', '1号炉温度', 'number', '40101', '℃', 'data.v', '0.1', '0', '1', '', '', '', 'float32', 'ABCD', '2', '1', '100'),
      line('line1_run', '1线运行', 'boolean', '00001', '', '', '', '', '', '0', 'true'),
      line('m_press', '总管压力', 'number', '30002', 'MPa', '', '1', '0.5', '2'),
    ].join('\n')

    const { rows, errors } = parsePointCsv(csv)

    expect(errors).toEqual([])
    expect(rows).toHaveLength(3)
    expect(rows[0]).toEqual({
      key: 'm_temp', label: '1号炉温度', type: 'number', address: '40101',
      unit: '℃', jsonPath: 'data.v', scale: 0.1, offset: 0, precision: 1,
      modbusDataType: 'float32', modbusByteOrder: 'ABCD', unitId: 2,
      range: { min: 1, max: 100 },
    })
    expect(rows[1]).toEqual({
      key: 'line1_run', label: '1线运行', type: 'boolean', address: '00001',
      bitIndex: 0, writable: true,
    })
    expect(rows[2]).toEqual({
      key: 'm_press', label: '总管压力', type: 'number', address: '30002',
      unit: 'MPa', scale: 1, offset: 0.5, precision: 2,
    })
  })

  it('容忍 UTF-8 BOM 与 CRLF；未加引号字段两侧空格剔除', () => {
    const csv = '\uFEFF key , label ,type,address\r\n p1 , 压力 ,number, 30001 \r\n'
    const { rows, errors } = parsePointCsv(csv)
    expect(errors).toEqual([])
    expect(rows).toEqual([{ key: 'p1', label: '压力', type: 'number', address: '30001' }])
  })

  it('带引号字段：内嵌逗号与 "" 转义双引号原样保留（含两端空格）', () => {
    const csv = HEADER + '\n' + line('p1', '"压力, 主管""B""侧"', 'number', '30001', '" ℃ "')
    const { rows, errors } = parsePointCsv(csv)
    expect(errors).toEqual([])
    expect(rows[0]).toEqual({
      key: 'p1', label: '压力, 主管"B"侧', type: 'number', address: '30001', unit: ' ℃ ',
    })
  })

  it('表头可为 17 列的子集（仅必填 4 列也能导入）', () => {
    const { rows, errors } = parsePointCsv('key,label,type,address\np1,压力,number,30001\n')
    expect(errors).toEqual([])
    expect(rows).toEqual([{ key: 'p1', label: '压力', type: 'number', address: '30001' }])
  })

  it('空行跳过不报错；行号按物理行计（含空行）', () => {
    const csv = [HEADER, '', line('p1', '压力', 'number', '30001'), '', line('p1', '温度', 'number', '30002')].join('\n')
    const { rows, errors } = parsePointCsv(csv)
    // 第 2 行 key 在第 5 行重复 → 仅报第 5 行
    expect(rows).toHaveLength(1)
    expect(errors).toHaveLength(1)
    expect(errors[0].line).toBe(5)
    expect(errors[0].message).toContain('重复')
  })
})

describe('parsePointCsv 表头校验', () => {
  it('缺 address 列 → 仍可解析（mock 变量地址可为空，保证导出可往返）', () => {
    const cols = POINT_CSV_COLUMNS.filter((c) => c !== 'address')
    const row = cols.map((c) => (c === 'key' ? 'p1' : c === 'label' ? '压力' : c === 'type' ? 'number' : '')).join(',')
    const { rows, errors } = parsePointCsv(`${cols.join(',')}\n${row}\n`)
    expect(errors).toEqual([])
    expect(rows).toHaveLength(1)
    expect(rows[0]).toMatchObject({ key: 'p1', label: '压力', type: 'number', address: '' })
  })

  it('表头含未知列 → 第 1 行报错（防列名拼错导致数据静默丢弃）', () => {
    const { rows, errors } = parsePointCsv(HEADER + ',remark\n' + line('p1', '压力', 'number', '30001', '', '', '', '', '', '', '', '', '', '', '', '', '', '备注'))
    expect(rows).toEqual([])
    expect(errors[0].line).toBe(1)
    expect(errors[0].message).toContain('remark')
  })

  it('空文件（无表头）→ 第 1 行报错', () => {
    const { rows, errors } = parsePointCsv('')
    expect(rows).toEqual([])
    expect(errors).toHaveLength(1)
    expect(errors[0].line).toBe(1)
    expect(errors[0].message).toContain('表头')
  })
})

describe('parsePointCsv 行级校验', () => {
  it('必填单元格为空（label）→ 行错', () => {
    const { rows, errors } = parsePointCsv(HEADER + '\n' + line('p1', '', 'number', '30001'))
    expect(rows).toEqual([])
    expect(errors[0].line).toBe(2)
    expect(errors[0].message).toContain('label')
  })

  it('type 非法 → 行错', () => {
    const { rows, errors } = parsePointCsv(HEADER + '\n' + line('p1', '压力', 'int', '30001'))
    expect(rows).toEqual([])
    expect(errors[0].line).toBe(2)
    expect(errors[0].message).toContain('type')
  })

  it('key 字符集非法（空格/中文）→ 行错', () => {
    const { rows, errors } = parsePointCsv(HEADER + '\n' + line('一号 炉', '温度', 'number', '30001'))
    expect(rows).toEqual([])
    expect(errors[0].line).toBe(2)
    expect(errors[0].message).toContain('key')
  })

  it('key 重复 → 后出现的一行报错', () => {
    const csv = HEADER + '\n' + line('p1', '压力', 'number', '30001') + '\n' + line('p1', '温度', 'number', '30002')
    const { rows, errors } = parsePointCsv(csv)
    expect(rows).toHaveLength(1)
    expect(errors).toHaveLength(1)
    expect(errors[0].line).toBe(3)
    expect(errors[0].message).toContain('重复')
  })

  it('字段数与表头列数不一致 → 行错', () => {
    const { rows, errors } = parsePointCsv(HEADER + '\np1,压力,number')
    expect(rows).toEqual([])
    expect(errors[0].line).toBe(2)
    expect(errors[0].message).toContain('字段数')
  })

  it('数值列非法（scale=abc）→ 行错', () => {
    const { rows, errors } = parsePointCsv(HEADER + '\n' + line('p1', '压力', 'number', '30001', '', '', 'abc'))
    expect(rows).toEqual([])
    expect(errors[0].line).toBe(2)
    expect(errors[0].message).toContain('scale')
  })

  it('precision 越界（7）→ 行错（对齐服务端 0~6）', () => {
    const { rows, errors } = parsePointCsv(HEADER + '\n' + line('p1', '压力', 'number', '30001', '', '', '', '', '7'))
    expect(rows).toEqual([])
    expect(errors[0].message).toContain('precision')
  })

  it('unitId 越界（256）→ 行错（对齐服务端 0~255）', () => {
    const { rows, errors } = parsePointCsv(HEADER + '\n' + line('p1', '压力', 'number', '30001', '', '', '', '', '', '', '', '', '', '', '256'))
    expect(rows).toEqual([])
    expect(errors[0].message).toContain('unitId')
  })

  it('writable 非法值 → 行错', () => {
    const { rows, errors } = parsePointCsv(HEADER + '\n' + line('p1', '压力', 'number', '30001', '', '', '', '', '', '', 'yes'))
    expect(rows).toEqual([])
    expect(errors[0].message).toContain('writable')
  })

  it('modbusDataType / modbusByteOrder 枚举外取值 → 行错', () => {
    const csv = HEADER + '\n'
      + line('p1', '压力', 'number', '30001', '', '', '', '', '', '', '', '', 'int64', 'ABCD')
      + '\n'
      + line('p2', '温度', 'number', '30002', '', '', '', '', '', '', '', '', 'int16', 'AB')
    const { rows, errors } = parsePointCsv(csv)
    expect(rows).toEqual([])
    expect(errors).toHaveLength(2)
    expect(errors[0].message).toContain('modbusDataType')
    expect(errors[1].message).toContain('modbusByteOrder')
  })

  it('min/max 只给其一 → 行错', () => {
    const { rows, errors } = parsePointCsv(HEADER + '\n' + line('p1', '压力', 'number', '30001', '', '', '', '', '', '', '', '', '', '', '', '10', ''))
    expect(rows).toEqual([])
    expect(errors[0].message).toContain('min/max')
  })

  it('bitIndex 与 scale 同给 → 行错（对齐服务端互斥校验）', () => {
    const { rows, errors } = parsePointCsv(HEADER + '\n' + line('p1', '压力', 'number', '30001', '', '', '2', '', '', '0'))
    expect(rows).toEqual([])
    expect(errors[0].message).toContain('互斥')
  })

  it('bitIndex 配 string 类型 → 行错（对齐服务端校验）', () => {
    const { rows, errors } = parsePointCsv(HEADER + '\n' + line('p1', '状态', 'string', 'topic', '', '', '', '', '', '0'))
    expect(rows).toEqual([])
    expect(errors[0].message).toContain('bitIndex')
  })

  it('类型非法 → 行错（address 可空，不再因此报错）', () => {
    const { rows, errors } = parsePointCsv(HEADER + '\n' + line('p1', '压力', 'int', ''))
    expect(rows).toEqual([])
    expect(errors).toHaveLength(1)
    expect(errors[0].message).toContain('type')
  })
})

describe('buildPointCsv 导出（与导入同格式，可往返）', () => {
  const vars = [
    {
      id: 'var1', key: 'm_temp', label: '1号炉温度', type: 'number', datasourceId: 'ds1',
      address: '40101', unit: '℃', scale: 0.1, precision: 1, writable: true,
      writeAddress: '40101', modbusDataType: 'float32', modbusByteOrder: 'CDAB', unitId: 2,
      range: { min: 0, max: 200 },
    },
    {
      id: 'var2', key: 'run', label: '运行', type: 'boolean', datasourceId: 'ds1',
      address: '00001', writable: false,
    },
  ] as VariableDef[]

  it('导出后重新解析，关键字段与绑定口径一致', () => {
    const csv = buildPointCsv(vars)
    expect(csv.split('\n')[0]).toBe(POINT_CSV_COLUMNS.join(','))
    const { rows, errors } = parsePointCsv(csv)
    expect(errors).toEqual([])
    expect(rows).toHaveLength(2)
    expect(rows[0]).toMatchObject({
      key: 'm_temp', label: '1号炉温度', type: 'number', address: '40101',
      unit: '℃', scale: 0.1, precision: 1, writable: true,
      modbusDataType: 'float32', modbusByteOrder: 'CDAB', unitId: 2,
      range: { min: 0, max: 200 },
    })
    expect(rows[1]).toMatchObject({ key: 'run', type: 'boolean', address: '00001', writable: false })
  })

  it('虚拟变量不导出（CSV 是点表口径）', () => {
    const csv = buildPointCsv([
      ...vars,
      { id: 'var3', key: 'avg', label: '平均', type: 'number', datasourceId: 'virtual', expr: 'm_temp / 2' } as VariableDef,
    ])
    expect(csv).not.toContain('avg')
  })

  it('含逗号/引号的名称被正确转义并可还原', () => {
    const csv = buildPointCsv([{ ...vars[0], label: '温度,"A"点' } as VariableDef])
    const { rows, errors } = parsePointCsv(csv)
    expect(errors).toEqual([])
    expect(rows[0].label).toBe('温度,"A"点')
  })
})
