/**
 * buildRealtimeRows 行构造纯函数（工厂可用阶段二 Task 6）：
 * 覆盖 正常行 / quality 非 good 灰显 / alarm 标记 / 未知 key 空行 / precision 格式化 五类场景。
 * buildHistoryRows（Task 7）：桶聚合取桶内最后一点 / 空 series / bucketCount 大于点数 / 时间标签自适应跨度。
 */
import { describe, expect, it } from 'vitest'
import { buildHistoryRows, buildRealtimeRows } from '@/utils/tableRows'

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

/** 本地时区构造（跨时区确定性）：Date(y,m,d,hh,mm) 各环境一致 */
const t = (y: number, mo: number, d: number, h: number, mi: number): number => new Date(y, mo, d, h, mi).getTime()

describe('buildHistoryRows', () => {
  it('桶聚合：6 点 → 3 桶，每桶取最后一点；短跨度时间标签 HH:mm；值 toFixed(2)', () => {
    // 10:00~10:05 每分钟一点，值 1..6；跨度 5min / 3 桶 → 桶宽 ~1min
    // 桶划分（floor((ts-first)/width)，末点封顶 bucket-1）：{00,01} {02,03} {04,05}
    const series: [number, number][] = [
      [t(2026, 9, 23, 10, 0), 1],
      [t(2026, 9, 23, 10, 1), 2],
      [t(2026, 9, 23, 10, 2), 3],
      [t(2026, 9, 23, 10, 3), 4],
      [t(2026, 9, 23, 10, 4), 5],
      [t(2026, 9, 23, 10, 5), 6],
    ]
    const rows = buildHistoryRows(series, 3)
    expect(rows).toHaveLength(3)
    // 断言取点（每桶最后一点）与时间标签（≤24h 仅时刻）
    expect(rows[0]).toMatchObject({ time: '10:01', text: '2.00', value: 2 })
    expect(rows[1]).toMatchObject({ time: '10:03', text: '4.00', value: 4 })
    expect(rows[2]).toMatchObject({ time: '10:05', text: '6.00', value: 6 })
    // ts 保留代表点原始时间戳（供行 key / 调试）
    expect(rows[2].ts).toBe(series[5][0])
  })

  it('时间标签自适应跨度：序列跨度 > 24h 用 MM-DD HH:mm；单点序列（跨度 0）不除零出 1 行', () => {
    const rows = buildHistoryRows(
      [
        [t(2026, 9, 22, 10, 0), 61.5],
        [t(2026, 9, 23, 11, 30), 62.7],
      ],
      2,
    )
    expect(rows.map((r) => r.time)).toEqual(['10-22 10:00', '10-23 11:30'])
    expect(rows.map((r) => r.text)).toEqual(['61.50', '62.70'])

    const single = buildHistoryRows([[t(2026, 9, 23, 8, 0), 3.456]], 24)
    expect(single).toHaveLength(1)
    expect(single[0]).toMatchObject({ time: '08:00', text: '3.46', value: 3.456 })
  })

  it('空 series：undefined / [] 返回空行数组；bucketCount 非法（<1）同样空数组兜底', () => {
    const series: [number, number][] = [[t(2026, 9, 23, 10, 0), 1]]
    expect(buildHistoryRows(undefined, 24)).toEqual([])
    expect(buildHistoryRows([], 24)).toEqual([])
    expect(buildHistoryRows(series, 0)).toEqual([])
  })

  it('bucketCount 大于点数：不虚增行——每点独占一桶，行数=点数且保持时间顺序', () => {
    const series: [number, number][] = Array.from({ length: 6 }, (_, i) => [t(2026, 9, 23, 10, i), i + 1])
    const rows = buildHistoryRows(series, 10)
    expect(rows).toHaveLength(6)
    expect(rows.map((r) => r.value)).toEqual([1, 2, 3, 4, 5, 6])
    expect(rows.map((r) => r.time)).toEqual(['10:00', '10:01', '10:02', '10:03', '10:04', '10:05'])
  })
})
