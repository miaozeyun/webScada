/**
 * 四类数据源适配器（M3）：mock / websocket / rest / mqtt（MQTT over WebSocket）。
 * 浏览器直连（02 §2.13 前端承担数据接入），统一 onRaw(variable, raw) 回调；
 * 原始值到工程值的换算（scale/offset/precision/bitIndex，G3）由 engine 执行。
 */
import mqtt from 'mqtt'
import type { DataSource, VariableDef } from '@/types/doc'

export interface SourceHandle {
  stop(): void
  /** 反控写入（M7）：mqtt/rest/websocket 返回；mock 由引擎本地回环（不经此通道） */
  write?(variable: VariableDef, value: number | boolean | string): Promise<void>
}

export type RawCallback = (variable: VariableDef, raw: unknown) => void

/** 点路径取值：a.b.c / a[0].b；空路径返回原值 */
export function getByPath(data: unknown, path?: string | null): unknown {
  if (!path) return data
  return path
    .replace(/\[(\d+)\]/g, '.$1')
    .split('.')
    .filter(Boolean)
    .reduce<unknown>((acc, key) => (acc == null ? undefined : (acc as Record<string, unknown>)[key]), data)
}

/** 消息 → 值：address 定位（对象字段或消息本体）→ jsonPath 深取 */
function pick(message: unknown, variable: VariableDef): unknown {
  let base: unknown = message
  if (variable.address && typeof message === 'object' && message !== null) {
    base = (message as Record<string, unknown>)[variable.address]
  }
  return getByPath(base, variable.jsonPath)
}

export function startSource(ds: DataSource, variables: VariableDef[], onRaw: RawCallback): SourceHandle {
  if (ds.enabled === false) return { stop: () => {} }
  const vars = variables.filter((v) => v.datasourceId === ds.id)
  if (vars.length === 0) return { stop: () => {} }

  switch (ds.type) {
    case 'mock':
      return startMock(ds, vars, onRaw)
    case 'websocket':
      return startWebsocket(ds, vars, onRaw)
    case 'rest':
      return startRest(ds, vars, onRaw)
    case 'mqtt':
      return startMqtt(ds, vars, onRaw)
  }
}

// ---- mock：变量各自按 spec 振荡（sine/ramp/random/square/hold） ----

function startMock(ds: Extract<DataSource, { type: 'mock' }>, vars: VariableDef[], onRaw: RawCallback): SourceHandle {
  const timers = new Set<ReturnType<typeof setInterval>>()
  const t0 = Date.now()
  for (const v of vars) {
    const spec = v.mock
    if (!spec) continue
    if (spec.kind === 'hold') {
      // 保持型：仅推初始默认值，此后只随反控写入回环变化
      if (v.defaultValue !== null && v.defaultValue !== undefined) onRaw(v, v.defaultValue)
      continue
    }
    const interval = spec.kind === 'random' ? spec.intervalMs : Math.max(100, spec.periodMs / 24)
    timers.add(
      setInterval(() => {
        const t = Date.now() - t0
        let raw: number
        switch (spec.kind) {
          case 'sine':
            raw = spec.min + ((spec.max - spec.min) * (0.5 + 0.5 * Math.sin((2 * Math.PI * t) / spec.periodMs)))
            break
          case 'ramp': {
            const p = (t % spec.periodMs) / spec.periodMs
            raw = p < 0.5 ? spec.min + (spec.max - spec.min) * p * 2 : spec.max - (spec.max - spec.min) * (p - 0.5) * 2
            break
          }
          case 'random':
            raw = spec.min + Math.random() * (spec.max - spec.min)
            break
          case 'square': {
            const p = (t % spec.periodMs) / spec.periodMs
            raw = p < (spec.duty ?? 0.5) ? spec.onValue : spec.offValue
            break
          }
        }
        onRaw(v, raw)
      }, Math.max(100, interval)),
    )
  }
  return {
    stop: () => {
      timers.forEach(clearInterval)
      timers.clear()
    },
  }
}

// ---- websocket：长连接推送 ----

function startWebsocket(ds: Extract<DataSource, { type: 'websocket' }>, vars: VariableDef[], onRaw: RawCallback): SourceHandle {
  let closed = false
  let ws: WebSocket | null = null
  let heartbeat: ReturnType<typeof setInterval> | null = null
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  const min = ds.config.reconnectMinMs ?? 1000
  const max = ds.config.reconnectMaxMs ?? 15000
  let delay = min

  const connect = (): void => {
    ws = new WebSocket(ds.config.url)
    ws.onopen = () => {
      delay = min
      if (ds.config.subscribeFrame) ws?.send(ds.config.subscribeFrame)
      if (ds.config.heartbeatSec) {
        heartbeat = setInterval(() => ws?.readyState === WebSocket.OPEN && ws.send('{}'), ds.config.heartbeatSec * 1000)
      }
    }
    ws.onmessage = (ev) => {
      if (closed) return
      let data: unknown
      try {
        data = JSON.parse(String(ev.data))
      } catch {
        data = ev.data
      }
      for (const v of vars) {
        const raw = pick(data, v)
        if (raw !== undefined) onRaw(v, raw)
      }
    }
    ws.onclose = () => {
      if (closed) return
      if (heartbeat) clearInterval(heartbeat)
      reconnectTimer = setTimeout(connect, delay)
      delay = Math.min(delay * 2, max)
    }
  }
  connect()

  return {
    stop: () => {
      closed = true
      if (heartbeat) clearInterval(heartbeat)
      if (reconnectTimer) clearTimeout(reconnectTimer)
      ws?.close()
    },
    write: (variable, value) =>
      new Promise<void>((resolve, reject) => {
        if (!ws || ws.readyState !== WebSocket.OPEN) {
          reject(new Error('WebSocket 未连接，写入失败'))
          return
        }
        const tpl = ds.config.writeFrameTemplate
        const frame = tpl
          ? tpl.replace(/\{key\}/g, variable.key).replace(/\{value\}/g, JSON.stringify(value))
          : JSON.stringify({ [variable.key]: value })
        ws.send(frame)
        resolve()
      }),
  }
}

// ---- rest：轮询 ----

function startRest(ds: Extract<DataSource, { type: 'rest' }>, vars: VariableDef[], onRaw: RawCallback): SourceHandle {
  let stopped = false
  let timer: ReturnType<typeof setTimeout> | null = null

  const poll = async (): Promise<void> => {
    if (stopped) return
    try {
      const resp = await fetch(ds.config.url, {
        method: ds.config.method ?? 'GET',
        headers: ds.config.headers ?? undefined,
        body: ds.config.method === 'POST' ? (ds.config.body ?? undefined) : undefined,
        signal: AbortSignal.timeout(ds.config.timeoutMs ?? 5000),
      })
      if (resp.ok) {
        const data: unknown = await resp.json()
        for (const v of vars) {
          const raw = pick(data, v)
          if (raw !== undefined) onRaw(v, raw)
        }
      }
    } catch {
      /* 网络失败静默，等下一轮 */
    }
    if (!stopped) timer = setTimeout(poll, Math.max(500, ds.config.intervalMs))
  }
  poll()

  return {
    stop: () => {
      stopped = true
      if (timer) clearTimeout(timer)
    },
    write: async (variable, value) => {
      const url = ds.config.writeUrl
      if (!url) throw new Error('该 REST 数据源未配置写端点（writeUrl）')
      const body = (ds.config.writeBodyTemplate
        ? ds.config.writeBodyTemplate.replace(/\{key\}/g, variable.key).replace(/\{value\}/g, JSON.stringify(value))
        : JSON.stringify({ [variable.key]: value }))
      const resp = await fetch(url, {
        method: ds.config.writeMethod ?? 'POST',
        headers: { 'Content-Type': 'application/json', ...(ds.config.headers ?? {}) },
        body,
        signal: AbortSignal.timeout(ds.config.timeoutMs ?? 5000),
      })
      if (!resp.ok) throw new Error(`写入失败：HTTP ${resp.status}`)
    },
  }
}

// ---- mqtt：MQTT over WebSocket（mqtt.js，brokerUrl 形如 ws://host:8083/mqtt） ----

function startMqtt(ds: Extract<DataSource, { type: 'mqtt' }>, vars: VariableDef[], onRaw: RawCallback): SourceHandle {
  const client = mqtt.connect(ds.config.brokerUrl, {
    username: ds.config.username || undefined,
    password: ds.config.password || undefined,
    reconnectPeriod: ds.config.reconnectMinMs ?? 1000,
    clean: ds.config.cleanSession ?? true,
    protocolVersion: 4,
  })
  const topics = ds.config.topics ?? []
  if (topics.length) client.subscribe(topics, { qos: ds.config.qos ?? 0 })

  client.on('message', (_topic, payload) => {
    let data: unknown
    try {
      data = JSON.parse(payload.toString())
    } catch {
      data = payload.toString()
    }
    for (const v of vars) {
      // 变量 address 即订阅 topic；同 topic 多变量各自经 jsonPath 取值
      if (v.address && v.address !== _topic) continue
      const raw = getByPath(data, v.jsonPath)
      if (raw !== undefined) onRaw(v, raw)
    }
  })

  return {
    stop: () => {
      client.end(true)
    },
    write: async (variable, value) => {
      const topic = variable.writeAddress || variable.address
      if (!topic) throw new Error(`变量 ${variable.key} 未配置写地址（writeAddress/address）`)
      await new Promise<void>((resolve, reject) => {
        client.publish(
          topic,
          typeof value === 'string' ? value : String(value),
          { qos: ds.config.writeQos ?? 0, retain: false },
          (err) => (err ? reject(err) : resolve()),
        )
      })
    },
  }
}

// ---- 连接测试（M7「MQTT 通讯测试」泛化到四源） ----

export interface TestResult {
  ok: boolean
  message: string
}

/** 数据源连通性测试：mock 恒通；mqtt 尝试连接后立即断开；ws/rest 各发一次请求 */
export function testConnection(ds: DataSource): Promise<TestResult> {
  switch (ds.type) {
    case 'mock':
      return Promise.resolve({ ok: true, message: 'mock 数据源在浏览器本地生成，无需连接' })
    case 'mqtt':
      return new Promise((resolve) => {
        const client = mqtt.connect(ds.config.brokerUrl, {
          username: ds.config.username || undefined,
          password: ds.config.password || undefined,
          reconnectPeriod: 0,
          connectTimeout: 5000,
          protocolVersion: 4,
        })
        const done = (ok: boolean, message: string): void => {
          resolve({ ok, message })
          setTimeout(() => client.end(true), 200)
        }
        client.on('connect', () => done(true, `已连接 ${ds.config.brokerUrl}`))
        client.on('error', (err: Error) => done(false, `连接失败：${err.message}`))
      })
    case 'websocket':
      return new Promise((resolve) => {
        try {
          const ws = new WebSocket(ds.config.url)
          const timer = setTimeout(() => {
            resolve({ ok: false, message: '连接超时（5s）' })
            ws.close()
          }, 5000)
          ws.onopen = () => {
            clearTimeout(timer)
            resolve({ ok: true, message: `已连接 ${ds.config.url}` })
            ws.close()
          }
          ws.onerror = () => {
            clearTimeout(timer)
            resolve({ ok: false, message: '连接失败（onerror）' })
          }
        } catch (err) {
          resolve({ ok: false, message: `连接失败：${(err as Error).message}` })
        }
      })
    case 'rest':
      return fetch(ds.config.url, {
        method: ds.config.method ?? 'GET',
        headers: ds.config.headers ?? undefined,
        body: ds.config.method === 'POST' ? (ds.config.body ?? undefined) : undefined,
        signal: AbortSignal.timeout(5000),
      })
        .then((resp) => ({
          ok: resp.ok,
          message: resp.ok ? `HTTP ${resp.status}（${ds.config.url}）` : `HTTP ${resp.status}（${ds.config.url}）`,
        }))
        .catch((err: Error) => ({ ok: false, message: `请求失败：${err.message}` }))
  }
}
