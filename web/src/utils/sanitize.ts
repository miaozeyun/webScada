/**
 * 导出凭证脱敏（前端二次保险，G6）。
 * 服务端导出端点已统一脱敏；此处再过一遍，保证落盘文件绝不包含凭证
 * （与 server/app/utils/sanitize.py 同一契约；缩略图一并剔除）。
 */
import type { ProjectDoc } from '@/types/doc'

const SENSITIVE_HEADER_RE = /(authorization|token|password|secret|key)/i

export function sanitizeDocForExport(doc: ProjectDoc): ProjectDoc {
  // doc 为纯 JSON 数据，JSON round-trip 克隆足够（G22：不使用 structuredClone）
  const cloned = JSON.parse(JSON.stringify(doc)) as ProjectDoc
  for (const ds of cloned.datasources ?? []) {
    if (!ds.config) continue
    // 仅清空已存在的键（与服务端 sanitize.py「缺失键保持缺失」一致，避免导出文件多出空键）
    if (ds.type === 'mqtt' && 'password' in ds.config) {
      ds.config.password = ''
    } else if (ds.type === 'rest' || ds.type === 'websocket') {
      if (ds.config.headers) {
        for (const key of Object.keys(ds.config.headers)) {
          if (SENSITIVE_HEADER_RE.test(key)) ds.config.headers[key] = ''
        }
      }
    }
  }
  // 钉钉通知渠道加签密钥（阶段二 Task 4，与服务端 sanitize.py 同口径）
  for (const ch of cloned.settings?.notify?.channels ?? []) {
    if (ch.kind === 'dingtalk' && 'secret' in ch) ch.secret = ''
  }
  // 台账缩略图为展示缓存（编辑器保存时自动重建），导出文件不携带
  if (cloned.project && 'thumbnail' in cloned.project) {
    const { thumbnail: _omit, ...rest } = cloned.project
    cloned.project = rest
  }
  return cloned
}
