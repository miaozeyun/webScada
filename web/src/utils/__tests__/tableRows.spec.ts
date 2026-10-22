/**
 * buildRealtimeRows 行构造纯函数（工厂可用阶段二 Task 6）：
 * 覆盖 正常行 / quality 非 good 灰显 / alarm 标记 / 未知 key 空行 / precision 格式化 五类场景。
 */
import { describe, expect, it } from 'vitest'
import { buildRealtimeRows } from '@/utils/tableRows'

const col = (key: string, label = key): { key: string; label: string } => ({ key, label })

describe('buildRealtimeRows', () => {
  it('正常行：good 质量不灰显；number 按缺省 2 位小数、boolean 原样字符串化', () => {
    const rows = buildRealtimeRows(
      [col('temp1', '一号温度'), col('run', '运行状态')],
      (key) =>
        key === 'temp1'
          ? { value: 86.5, quality: 'good', alarm: false }
          : { value: true, quality: 'good', alarm: false },
    )
    expect(rows).toHaveLength(2)
    expect(rows[0]).toMatchObject({ key: 'temp1', label: '一号温度', text: '86.50', dim: false, alarm: false })
    expect(rows[1]).toMatchObject({ key: 'run', label: '运行状态', text: 'true', dim: false, alarm: false })
  })

  it('precision 格式化：按指定小数位（0/3）；string 值原样；未指定回落 2 位', () => {
    const rows = buildRealtimeRows(
      [col('a'), col('b'), col('c'), col('d')],
      (key) => {
        if (key === 'a') return { value: 3.14159, quality: 'good', alarm: false, precision: 3 }
        if (key === 'b') return { value: 7, quality: 'good', alarm: false, precision: 0 }
        if (key === 'c') return { value: '运行', quality: 'good', alarm: false }
        return { value: 1.5, quality: 'good', alarm: false, precision: null }
      },
    )
    expect(rows[0].text).toBe('3.142')
    expect(rows[1].text).toBe('7')
    expect(rows[2].text).toBe('运行')
    expect(rows[3].text).toBe('1.50') // precision=null → 缺省 2
  })

  it('quality 非 good：dim 置位灰显（stale 保留末值；bad 无值时占位 --）', () => {
    const rows = buildRealtimeRows(
      [col('stale'), col('bad')],
      (key) =>
        key === 'stale'
          ? { value: 42.1, quality: 'stale', alarm: false }
          : { value: null, quality: 'bad', alarm: false },
    )
    expect(rows[0]).toMatchObject({ text: '42.10', value: 42.1, quality: 'stale', dim: true })
    expect(rows[1]).toMatchObject({ text: '--', value: null, quality: 'bad', dim: true })
  })

  it('alarm 标记：报警行置位（与质量位互不影响）', () => {
    const rows = buildRealtimeRows(
      [col('press'), col('temp')],
      (key) =>
        key === 'press'
          ? { value: 0.98, quality: 'good', alarm: true }
          : { value: 86.5, quality: 'good', alarm: false },
    )
    expect(rows[0].alarm).toBe(true)
    expect(rows[0].dim).toBe(false)
    expect(rows[1].alarm).toBe(false)
  })

  it('未知 key：空行占位（--），不灰显不报警', () => {
    const rows = buildRealtimeRows([col('ghost', '已删变量')], () => undefined)
    expect(rows).toHaveLength(1)
    expect(rows[0]).toMatchObject({
      key: 'ghost',
      label: '已删变量',
      text: '--',
      value: null,
      dim: false,
      alarm: false,
    })
  })

  it('边界：空列清单返回空数组；已知变量尚无值（good + null）显示 -- 不灰显', () => {
    expect(buildRealtimeRows([], () => ({ value: 1, quality: 'good', alarm: false }))).toEqual([])
    const rows = buildRealtimeRows([col('t')], () => ({ value: null, quality: 'good', alarm: false }))
    expect(rows[0].text).toBe('--')
    expect(rows[0].dim).toBe(false)
  })
})
