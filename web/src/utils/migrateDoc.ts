/**
 * 工程文档 schemaVersion 迁移通道（M8 契约 §7.1，G8 迁移唯一实现点）。
 *
 * 挂接点：api/projects.ts importProject 提交前（编辑器导入入口同样经此通道）。
 * 语义：
 * - 非对象 / 缺版本 / 版本非法 → invalid；
 * - v > CURRENT_SCHEMA_VERSION → too_new（提示升级前端，禁止静默降级）；
 * - v < CURRENT → while 逐版应用 types/migrations.ts 的 MIGRATIONS[v]，任一步抛错或缺实现 → invalid；
 * - 通过路径统一深拷贝返回（调用方修改结果不影响入参对象）。
 */
import type { ProjectDoc } from '@/types/doc'
import { CURRENT_SCHEMA_VERSION, MIGRATIONS } from '@/types/migrations'

export type MigrateFailReason = 'too_new' | 'invalid'

export type MigrateResult =
  | { ok: true; doc: ProjectDoc }
  | { ok: false; reason: MigrateFailReason; message: string }

/**
 * 把任意来源（文件选择/拖入解析结果、历史导出等）的原始对象迁移到当前契约版本。
 * 不做结构校验（那是服务端 422 流程与编辑器打开时的事），只负责版本推进。
 */
export function migrateDoc(raw: unknown): MigrateResult {
  // 1) 非普通对象（null / 数组 / 原始值）→ invalid
  if (typeof raw !== 'object' || raw === null || Array.isArray(raw)) {
    return { ok: false, reason: 'invalid', message: '工程文件内容不是合法的 JSON 对象' }
  }
  // 2) 缺版本 / 版本非法（字符串、浮点等）→ invalid
  const v = (raw as Record<string, unknown>).schemaVersion
  if (typeof v !== 'number' || !Number.isInteger(v)) {
    return {
      ok: false,
      reason: 'invalid',
      message: '工程文件缺少 schemaVersion 或版本号非法（应为整数）',
    }
  }
  // 3) 高于前端支持 → too_new：提示升级前端，绝不静默降级（降级会丢新字段）
  if (v > CURRENT_SCHEMA_VERSION) {
    return {
      ok: false,
      reason: 'too_new',
      message: `工程文件 schemaVersion=${v} 高于当前前端支持的 ${CURRENT_SCHEMA_VERSION}，请升级前端版本后再导入`,
    }
  }
  // 4) 逐版升级：MIGRATIONS 键 = 起始版本，框架统一把 schemaVersion 改写为 N+1
  let doc = raw as Record<string, unknown>
  let ver = v
  while (ver < CURRENT_SCHEMA_VERSION) {
    const step = MIGRATIONS[ver]
    if (!step) {
      return {
        ok: false,
        reason: 'invalid',
        message: `缺少 schemaVersion ${ver} → ${ver + 1} 的迁移实现，无法升级该工程文件`,
      }
    }
    try {
      doc = step(doc)
      doc.schemaVersion = ver + 1
    } catch (e) {
      return {
        ok: false,
        reason: 'invalid',
        message: `schemaVersion ${ver} → ${ver + 1} 迁移执行失败：${e instanceof Error ? e.message : String(e)}`,
      }
    }
    ver += 1
  }
  // 5) 深拷贝返回。structuredClone 需 Chrome 98+，超出 es2020 基线（G22：Chrome/Edge ≥ 90）禁用；
  //    工程文档本就是纯 JSON（无 undefined/函数/循环引用），JSON 往返深拷贝安全且顺带净化非法值。
  return { ok: true, doc: JSON.parse(JSON.stringify(doc)) as ProjectDoc }
}
