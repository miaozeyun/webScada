/**
 * UUID v4 生成（RFC 4122）。
 *
 * 不用 `crypto.randomUUID`：它只在**安全上下文**（HTTPS 或 localhost）可用，
 * 局域网 `http://<服务器IP>` 入口下为 undefined，调用即抛 TypeError。
 * `crypto.getRandomValues` 无此限制，全场景可用。
 *
 * 用途：仅前端构造 doc 时的 project.id（服务端 import 会重写为库内 uuid4，
 * 但重写前要先过 UUID_RE 校验，故格式必须是合法 UUID）。
 */
export function uuidV4(): string {
  const b = new Uint8Array(16)
  if (typeof crypto !== 'undefined' && typeof crypto.getRandomValues === 'function') {
    crypto.getRandomValues(b)
  } else {
    // 极老浏览器兜底：Math.random 非密码学安全，此处仅作本地 doc id，不涉密钥
    for (let i = 0; i < 16; i++) b[i] = Math.floor(Math.random() * 256)
  }
  b[6] = (b[6] & 0x0f) | 0x40 // version 4
  b[8] = (b[8] & 0x3f) | 0x80 // variant 10xx
  const h: string[] = []
  for (let i = 0; i < 16; i++) h.push((b[i] + 0x100).toString(16).slice(1))
  return `${h.slice(0, 4).join('')}-${h.slice(4, 6).join('')}-${h.slice(6, 8).join('')}-${h.slice(8, 10).join('')}-${h.slice(10, 16).join('')}`
}
