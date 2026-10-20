/** doc 内部对象 id 生成（G9：前端 nanoid；建议前缀 page_/cmp_/var_/ds_/bnd_/alm_，G33） */
import { customAlphabet } from 'nanoid'

// 去掉易混淆字符的小写字母数字表，21 位
const gen = customAlphabet('0123456789abcdefghijklmnopqrstuvwxyz', 21)

export function newId(prefix: string): string {
  return `${prefix}_${gen()}`
}

export function newPageId(): string {
  return newId('page')
}

export function newComponentId(): string {
  return newId('cmp')
}
