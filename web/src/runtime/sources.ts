/**
 * 数据源接入（M3 浏览器直连四源 + M8 服务端 WS 通道）。
 * M8 起：值流/报警/写通道权威在服务端（/api/v1/ws/runtime），startServerChannel 为运行态主通道；
 * 浏览器直连适配器（mock/websocket/rest/mqtt）仅保留为编辑器「数据源连接测试」专用（02 §7.1 修订）。
 */
import mqtt from 'mqtt'
import type {
  DataSource,
  VariableDef,
  WsActiveAlarm,
  WsErrorCode,
  WsValueEntry,
  WsWriteAckFrame,
} from '@/types/doc'

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
    case 'modbus':
      // Modbus 采集在服务端（collector），浏览器无 TCP 能力——no-op（运行态经 WS 取值）
      return { stop: () => {} }
    case 'opcua':
      // OPC UA 同理：服务端订阅推送，浏览器 no-op（运行态经 WS 取值）
      return { stop: () => {} }
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
    case 'modbus':
      return Promise.resolve({ ok: false, message: 'Modbus TCP 仅支持服务端采集，请用数据源面板「测试连接」' })
    case 'opcua':
      return Promise.resolve({ ok: false, message: 'OPC UA 仅支持服务端采集，请用数据源面板「测试连接」' })
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

// ==================== M8 服务端运行态 WS 通道（/api/v1/ws/runtime，权威通道） ====================

/** 致命 error code：停止重连（03 §3.6；INTERNAL_ERROR 按网络级失败退避重连） */
const FATAL_WS_CODES: ReadonlySet<string> = new Set([
  'TOKEN_EXPIRED',
  'PROJECT_REMOVED',
  'SHARE_REVOKED',
  'SHARE_EXPIRED',
  'RATE_LIMITED',
])

const SERVER_BACKOFF_MIN_MS = 1000
const SERVER_BACKOFF_MAX_MS = 30000
/** 客户端看门狗：30s 无任何入站帧 → 判定假死主动重连（03 §3.5） */
const SERVER_INBOUND_TIMEOUT_MS = 30000
/** write 等待 writeAck 超时 */
const WRITE_ACK_TIMEOUT_MS = 5000

export type ServerChannelStatus = 'connecting' | 'online' | 'offline' | 'error'

export interface ServerChannelCallbacks {
  /** snapshot/values 值条目（键=变量 key，值=服务端换算后工程值） */
  onEntry: (key: string, entry: WsValueEntry) => void
  onAlarm: (alarm: WsActiveAlarm) => void
  onAlarmClear: (alarmId: number, recoveredAt: number) => void
  onAlarmAck: (alarmId: number, ackedAt: number, ackedBy: string) => void
  /** snapshot 内嵌存量活动报警（首连/重连回填横幅、徽标、面板，03 §3.4）；
   *  truncated=true 表示服务端超 200 条截断，客户端应跳过差集清理防误清 */
  onSnapshotAlarms: (alarms: WsActiveAlarm[], truncated: boolean) => void
  onError: (code: WsErrorCode, message: string) => void
  /** 分享快照被刷新 → 宿主重新拉取 doc 并重建渲染（03 §3.4 reload） */
  onReload: () => void
  onStatus: (status: ServerChannelStatus) => void
}

export interface ServerChannelOptions extends ServerChannelCallbacks {
  projectId: string
  token: string
  page?: string
}

export interface ServerChannelHandle {
  /** 反控写：reqId 关联 writeAck；超时/失败 reject（engine 转用户提示） */
  write(variableKey: string, value: number | boolean | string): Promise<void>
  stop(): void
}

/** 服务端 WS 通道：连接序列/合帧值流/心跳/指数退避重连（1s→30s ±20% 抖动，03 §3.5/§3.6）。 */
export function startServerChannel(opts: ServerChannelOptions): ServerChannelHandle {
  let stopped = false
  let ws: WebSocket | null = null
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  let watchdogTimer: ReturnType<typeof setTimeout> | null = null
  let delay = SERVER_BACKOFF_MIN_MS
  const pendingWrites = new Map<string, { resolve: (v: void) => void; reject: (e: Error) => void }>()

  const clearWatchdog = (): void => {
    if (watchdogTimer) { clearTimeout(watchdogTimer); watchdogTimer = null }
  }
  const armWatchdog = (): void => {
    clearWatchdog()
    watchdogTimer = setTimeout(() => {
      // 30s 无入站帧：假死（TCP 半开/服务端宕机），主动断开走重连
      try { ws?.close() } catch { /* 已关 */ }
    }, SERVER_INBOUND_TIMEOUT_MS)
  }

  const wsUrl = (): string => {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    const params = new URLSearchParams({ project: opts.projectId, token: opts.token })
    if (opts.page) params.set('page', opts.page)
    return `${proto}://${location.host}/api/v1/ws/runtime?${params.toString()}`
  }

  const scheduleReconnect = (): void => {
    if (stopped) return
    opts.onStatus('offline')
    const jitter = delay * (0.8 + Math.random() * 0.4) // ±20% 抖动防雪崩
    reconnectTimer = setTimeout(connect, jitter)
    delay = Math.min(delay * 2, SERVER_BACKOFF_MAX_MS)
  }

  const onFrame = (frame: Record<string, unknown>): void => {
    armWatchdog() // 任何入站帧都刷新看门狗
    switch (frame.type) {
      case 'snapshot': {
        const data = (frame.data ?? {}) as Record<string, WsValueEntry>
        for (const [key, entry] of Object.entries(data)) opts.onEntry(key, entry)
        // 存量活动报警不可丢弃（03 §3.4 snapshot 语义）：刷新/重连后由引擎回填
        // 横幅/徽标/面板，并按 snapshot 报警 id 集合做差集清理已消失的报警
        const alarms = Array.isArray(frame.activeAlarms) ? (frame.activeAlarms as WsActiveAlarm[]) : []
        opts.onSnapshotAlarms(alarms, frame.truncated === true)
        break
      }
      case 'values': {
        const data = (frame.data ?? {}) as Record<string, WsValueEntry>
        for (const [key, entry] of Object.entries(data)) opts.onEntry(key, entry)
        break
      }
      case 'alarm':
        opts.onAlarm(frame.alarm as WsActiveAlarm)
        break
      case 'alarmClear':
        opts.onAlarmClear(Number(frame.alarmId), Number(frame.recoveredAt))
        break
      case 'alarmAck':
        opts.onAlarmAck(Number(frame.alarmId), Number(frame.ackedAt), String(frame.ackedBy ?? ''))
        break
      case 'ping':
        ws?.send(JSON.stringify({ type: 'pong' }))
        break
      case 'reload':
        opts.onReload()
        break
      case 'writeAck': {
        const ack = frame as unknown as WsWriteAckFrame
        const pending = ack.reqId ? pendingWrites.get(ack.reqId) : undefined
        if (pending) {
          pendingWrites.delete(ack.reqId)
          if (ack.ok) pending.resolve()
          else pending.reject(new Error(ack.message || ack.code || '写入被拒绝'))
        }
        break
      }
      case 'error': {
        const code = String(frame.code ?? 'INTERNAL_ERROR') as WsErrorCode
        opts.onError(code, String(frame.message ?? ''))
        if (FATAL_WS_CODES.has(code)) {
          // 致命：停止重连，提示人工介入（引擎侧经 onError 呈现）
          stopped = true
          opts.onStatus('error')
        }
        break
      }
      default:
        break // 未知帧类型忽略（03 §3.4 客户端容错口径）
    }
  }

  const connect = (): void => {
    if (stopped) return
    opts.onStatus('connecting')
    let socket: WebSocket
    try {
      socket = new WebSocket(wsUrl())
    } catch {
      scheduleReconnect()
      return
    }
    ws = socket
    socket.onopen = () => {
      delay = SERVER_BACKOFF_MIN_MS
      opts.onStatus('online')
      armWatchdog()
    }
    socket.onmessage = (ev) => {
      let frame: Record<string, unknown>
      try {
        frame = JSON.parse(String(ev.data)) as Record<string, unknown>
      } catch {
        return
      }
      onFrame(frame)
    }
    socket.onclose = (ev) => {
      clearWatchdog()
      // 未服务端指意的关闭（非致命 error 路径 stopped=true）→ 网络级失败，退避重连
      if (!stopped) scheduleReconnect()
      else if (ev.code === 4000) opts.onStatus('error')
    }
    socket.onerror = () => { /* onclose 跟进，统一走重连 */ }
  }

  connect()

  return {
    write: (variableKey, value) =>
      new Promise<void>((resolve, reject) => {
        if (!ws || ws.readyState !== WebSocket.OPEN) {
          reject(new Error('服务端连接未就绪，写入失败'))
          return
        }
        const reqId = `w_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`
        const timer = setTimeout(() => {
          pendingWrites.delete(reqId)
          reject(new Error('写入回执超时（writeAck）'))
        }, WRITE_ACK_TIMEOUT_MS)
        pendingWrites.set(reqId, {
          resolve: () => { clearTimeout(timer); resolve() },
          reject: (e) => { clearTimeout(timer); reject(e) },
        })
        ws.send(JSON.stringify({ type: 'write', reqId, variableKey, value }))
      }),
    stop: () => {
      stopped = true
      clearWatchdog()
      if (reconnectTimer) clearTimeout(reconnectTimer)
      for (const [, p] of pendingWrites) p.reject(new Error('连接已关闭'))
      pendingWrites.clear()
      try { ws?.close() } catch { /* 已关 */ }
      ws = null
    },
  }
}
