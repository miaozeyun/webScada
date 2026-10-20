/**
 * schemaVersion 迁移注册表（M8 契约 docs/implementation/server-closed-loop-plan.md §7.1/§7.3）。
 * 注册表集中于本文件；utils/migrateDoc.ts 是唯一消费方（G8：迁移唯一实现点在前端）。
 *
 * CURRENT_SCHEMA_VERSION 冻结规约——提版（N→N+1）必须同时满足：
 * ① 本表注册 MIGRATIONS[N] 且有 round-trip 测试；
 * ② N+1 对 N 严格向后兼容（只增字段/枚举值，不改不删）；
 * ③ 服务端 SCHEMA_COMPAT_WINDOW 默认 1 生效（N-1 灰度缓冲）；
 * ④ 前后端 CURRENT_SCHEMA_VERSION 同 PR 同步（后端：server/app/core/config.py）；
 * ⑤ 测试矩阵覆盖「v=N 文件 → migrateDoc → 服务端保存 → 导出=v N+1」全链路。
 */

/** 当前前端契约版本（本期保持 1；提版时与服务端 settings.CURRENT_SCHEMA_VERSION 同 PR 同步） */
export const CURRENT_SCHEMA_VERSION = 1

/**
 * 单步迁移：把 v=N 的 doc 结构升级为 v=N+1（只做结构变换）。
 * 入参/出参用宽松 Record：迁移处理的是旧版 JSON，不能假设它满足新版 ProjectDoc 类型；
 * schemaVersion 字段由 migrateDoc 框架统一改写为 N+1，迁移函数无须（也不应）自行设置。
 */
export type MigrationFn = (doc: Record<string, unknown>) => Record<string, unknown>

/**
 * 迁移注册表：键 = 起始版本 N，值 = N → N+1 的迁移实现。
 * 本期 CURRENT_SCHEMA_VERSION=1，表为空——机制完整、测试位就绪（spec 内注入假想迁移验证逐步升级路径）。
 */
export const MIGRATIONS: Record<number, MigrationFn> = {}
