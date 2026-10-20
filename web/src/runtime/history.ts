/**
 * 历史数据服务（M7「历史图表」）：分钟桶均值环形缓冲，localStorage 持久化。
 * 数据采集在浏览器（02 §2.13 前端承担），历史也只存本地（同源分享页同样可读）。
 * 桶结构 [tsMin, sum, n]：tsMin=分钟起始时间戳；查询时折算均值点 [ts, avg]。
 * 容量：单变量 3 天（4320 桶），全局 12 万桶上限，超限按最旧桶整段丢弃（防 localStorage 撑爆）。
 */
const LS_KEY = 'webscada:hist:v1'
const BUCKET_MS = 60_000
const PER_VAR_MAX = 4320
const GLOBAL_MAX = 120_000
const FLUSH_INTERVAL_MS = 10_000

type Bucket = [ts: number, sum: number, n: number]

const data = new Map<string, Bucket[]>()
let loaded = false
let dirty = false
let flushTimer: ReturnType<typeof setInterval> | null = null

function load(): void {
  if (loaded) return
  loaded = true
  try {
    const raw = localStorage.getItem(LS_KEY)
    if (raw) {
      const parsed = JSON.parse(raw) as Record<string, Bucket[]>
      for (const [k, v] of Object.entries(parsed)) if (Array.isArray(v)) data.set(k, v)
    }
  } catch {
    /* 损坏则丢弃重来 */
  }
}

function totalBuckets(): number {
  let t = 0
  for (const arr of data.values()) t += arr.length
  return t
}

/** 全局超限时按最旧 10% 丢弃（跨变量均匀裁剪，避免单变量饿死） */
function trimGlobal(): void {
  if (totalBuckets() <= GLOBAL_MAX) return
  for (const arr of data.values()) {
    const drop = Math.ceil(arr.length * 0.1)
    if (drop > 0) arr.splice(0, drop)
  }
}

/** 采样一个数值点（引擎 onRaw 调用）；非数值忽略 */
export function sample(varId: string, value: unknown, at = Date.now()): void {
  let num: number
  if (typeof value === 'number') num = Number.isFinite(value) ? value : NaN
  else if (typeof value === 'boolean') num = value ? 1 : 0
  else return
  if (Number.isNaN(num)) return

  load()
  const tsMin = Math.floor(at / BUCKET_MS) * BUCKET_MS
  const arr = data.get(varId) ?? []
  const last = arr[arr.length - 1]
  if (last && last[0] === tsMin) {
    last[1] += num
    last[2] += 1
  } else {
    arr.push([tsMin, num, 1])
    if (arr.length > PER_VAR_MAX) arr.splice(0, arr.length - PER_VAR_MAX)
    trimGlobal()
  }
  data.set(varId, arr)
  dirty = true
}

/** 查询时间范围内的均值序列（分钟粒度）；from/to 为毫秒时间戳 */
export function query(varId: string, fromMs: number, toMs = Date.now()): [number, number][] {
  load()
  const arr = data.get(varId)
  if (!arr) return []
  const points: [number, number][] = []
  for (const [ts, sum, n] of arr) {
    if (ts < fromMs || ts > toMs) continue
    if (n <= 0) continue
    points.push([ts, Number((sum / n).toFixed(3))])
  }
  return points
}

/** 批量预置历史（演示案例生成用）：points 为 [时间戳 ms, 数值]；同分钟桶合并覆盖 */
export function seedSeries(varId: string, points: [number, number][]): void {
  load()
  const arr = data.get(varId) ?? []
  const byTs = new Map<number, Bucket>()
  for (const b of arr) byTs.set(b[0], b)
  for (const [t, v] of points) {
    if (!Number.isFinite(v)) continue
    byTs.set(Math.floor(t / BUCKET_MS) * BUCKET_MS, [Math.floor(t / BUCKET_MS) * BUCKET_MS, v, 1])
  }
  const merged = [...byTs.values()].sort((a, b) => a[0] - b[0]).slice(-PER_VAR_MAX)
  data.set(varId, merged)
  dirty = true
}

/** 立即落盘（seedSeries 批量写入后调用一次，避免逐条写 localStorage） */
export function flushNow(): void {
  trimGlobal()
  flush()
}

function flush(): void {
  if (!dirty) return
  dirty = false
  try {
    // Map → 普通对象再序列化；超限兜底再裁一次
    trimGlobal()
    const obj: Record<string, Bucket[]> = {}
    for (const [k, v] of data.entries()) obj[k] = v
    localStorage.setItem(LS_KEY, JSON.stringify(obj))
  } catch {
    /* 配额超限等异常静默（内存数据仍在，仅持久化失败） */
  }
}

/** 启动定期落盘（引擎 start 时调用；stop 时显式 flush） */
export function startPersist(): void {
  if (flushTimer) return
  flushTimer = setInterval(flush, FLUSH_INTERVAL_MS)
}

/** 停止并落盘（引擎 stop 调用；页面卸载前 beforeunload 兜底） */
export function stopPersist(): void {
  if (flushTimer) {
    clearInterval(flushTimer)
    flushTimer = null
  }
  flush()
}

if (typeof window !== 'undefined') {
  window.addEventListener('beforeunload', flush)
}
