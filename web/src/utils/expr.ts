/**
 * 安全表达式求值器（M7）：虚拟变量 / 条件弹框 / writeVar 动作值共用。
 * 不走 eval / new Function：白名单文法（数字/字符串/布尔/标识符 + 四则/比较/逻辑/三元 + 内置数学函数），
 * 标识符从调用方给定的作用域（变量 key → 工程值）取值。
 * 语法/引用错误抛 SyntaxError / ReferenceError，调用方捕获后按缺省处理（引擎 console.warn 一次）。
 * 标识符须以字母或下划线开头（可含 . _ 数字）；数字开头或含 - 的变量 key 不支持在表达式中引用。
 */

type Scope = Record<string, unknown>

type EvalFn = (scope: Scope) => unknown

interface Token {
  type: 'num' | 'str' | 'ident' | 'op'
  value: string
}

const OPS = ['===', '!==', '==', '!=', '>=', '<=', '&&', '||', '+', '-', '*', '/', '%', '>', '<', '!', '?', ':', '(', ')', ',']

function tokenize(src: string): Token[] {
  const tokens: Token[] = []
  let i = 0
  while (i < src.length) {
    const ch = src[i]
    if (/\s/.test(ch)) { i++; continue }
    // 数字（十进制）
    if (/[0-9]/.test(ch) || (ch === '.' && /[0-9]/.test(src[i + 1] ?? ''))) {
      let j = i
      while (j < src.length && /[0-9.]/.test(src[j])) j++
      tokens.push({ type: 'num', value: src.slice(i, j) })
      i = j
      continue
    }
    // 字符串（单/双引号）
    if (ch === "'" || ch === '"') {
      let j = i + 1
      while (j < src.length && src[j] !== ch) j++
      if (j >= src.length) throw new SyntaxError(`表达式字符串未闭合：${src.slice(i)}`)
      tokens.push({ type: 'str', value: src.slice(i + 1, j) })
      i = j + 1
      continue
    }
    // 标识符（字母/下划线开头，可含 . _ 数字 —— 覆盖 a.b 形式的 key）
    if (/[A-Za-z_]/.test(ch)) {
      let j = i
      while (j < src.length && /[A-Za-z0-9_.]/.test(src[j])) j++
      tokens.push({ type: 'ident', value: src.slice(i, j) })
      i = j
      continue
    }
    // 运算符（长者优先）
    const op = OPS.find((o) => src.startsWith(o, i))
    if (!op) throw new SyntaxError(`表达式非法字符：${ch}（位置 ${i}）`)
    tokens.push({ type: 'op', value: op })
    i += op.length
  }
  return tokens
}

/** 内置函数（数学 + 三角 + 常用聚合；标识符命中函数名且后随 '(' 时按调用求值）
 *  M9 批次4 扩容：sin/cos/tan/asin/acos/atan/atan2/exp/log/clamp/sign（与服务端 expr_eval.py 同构）。 */
const BUILTINS: Record<string, (...args: number[]) => unknown> = {
  abs: Math.abs,
  min: Math.min,
  max: Math.max,
  floor: Math.floor,
  ceil: Math.ceil,
  round: (x: number, n = 0) => Number(Math.round(Number(`${x}e${n}`)) + `e-${n}`),
  pow: Math.pow,
  sqrt: Math.sqrt,
  sin: Math.sin,
  cos: Math.cos,
  tan: Math.tan,
  asin: Math.asin,
  acos: Math.acos,
  atan: Math.atan,
  atan2: Math.atan2,
  exp: Math.exp,
  log: Math.log,
  clamp: (x: number, lo = 0, hi = 1) => (x < lo ? lo : x > hi ? hi : x),
  sign: Math.sign,
}

function toNum(v: unknown): number {
  if (typeof v === 'number') return v
  if (typeof v === 'boolean') return v ? 1 : 0
  if (typeof v === 'string' && v !== '' && !Number.isNaN(Number(v))) return Number(v)
  return 0
}

/** 递归下降解析器：ternary > or > and > equality > relational > additive > multiplicative > unary > primary */
function parse(tokens: Token[]): EvalFn {
  let pos = 0

  const peek = (): Token | undefined => tokens[pos]
  const next = (): Token | undefined => tokens[pos++]
  const eat = (op: string): void => {
    const t = next()
    if (!t || t.type !== 'op' || t.value !== op) throw new SyntaxError(`期望 '${op}'，得到 '${t?.value ?? 'EOF'}'`)
  }
  const isOp = (op: string): boolean => peek()?.type === 'op' && peek()?.value === op

  function primary(): EvalFn {
    const t = next()
    if (!t) throw new SyntaxError('表达式意外结束')
    if (t.type === 'num') {
      const n = Number(t.value)
      return () => n
    }
    if (t.type === 'str') {
      const s = t.value
      return () => s
    }
    if (t.type === 'ident') {
      if (t.value === 'true') return () => true
      if (t.value === 'false') return () => false
      if (t.value === 'null') return () => null
      if (isOp('(')) {
        const fn = BUILTINS[t.value]
        if (!fn) throw new SyntaxError(`未知函数：${t.value}（可用：${Object.keys(BUILTINS).join('/')}）`)
        pos++ // 消耗 '('
        const args: EvalFn[] = []
        if (!isOp(')')) {
          args.push(ternary())
          while (isOp(',')) { pos++; args.push(ternary()) }
        }
        eat(')')
        return (scope) => fn(...args.map((a) => toNum(a(scope))))
      }
      const name = t.value
      return (scope) => {
        if (!(name in scope)) throw new ReferenceError(`表达式引用了未知变量：${name}`)
        return scope[name]
      }
    }
    if (t.type === 'op' && t.value === '(') {
      const inner = ternary()
      eat(')')
      return inner
    }
    throw new SyntaxError(`意外的记号：${t.value}`)
  }

  function unary(): EvalFn {
    if (isOp('!')) { pos++; const a = unary(); return (s) => !truthy(a(s)) }
    if (isOp('-')) { pos++; const a = unary(); return (s) => -toNum(a(s)) }
    if (isOp('+')) { pos++; const a = unary(); return (s) => toNum(a(s)) }
    return primary()
  }

  function binary(nextLevel: () => EvalFn, ops: string[], apply: (l: unknown, r: unknown, op: string) => unknown): EvalFn {
    let left = nextLevel()
    while (peek()?.type === 'op' && ops.includes(peek()!.value)) {
      const op = next()!.value
      const right = nextLevel()
      const l = left
      left = (s) => apply(l(s), right(s), op)
    }
    return left
  }

  const multiplicative = (): EvalFn =>
    binary(unary, ['*', '/', '%'], (l, r, op) => {
      const a = toNum(l), b = toNum(r)
      if (op === '*') return a * b
      if (op === '/') return b === 0 ? 0 : a / b
      return b === 0 ? 0 : a % b
    })

  const additive = (): EvalFn =>
    binary(multiplicative, ['+', '-'], (l, r, op) => {
      // 字符串拼接语义（+ 任一侧为字符串）
      if (op === '+' && (typeof l === 'string' || typeof r === 'string')) return `${str(l)}${str(r)}`
      const a = toNum(l), b = toNum(r)
      return op === '+' ? a + b : a - b
    })

  const relational = (): EvalFn =>
    binary(additive, ['>', '<', '>=', '<='], (l, r, op) => {
      const a = toNum(l), b = toNum(r)
      switch (op) { case '>': return a > b; case '<': return a < b; case '>=': return a >= b; default: return a <= b }
    })

  const equality = (): EvalFn =>
    binary(relational, ['==', '!=', '===', '!=='], (l, r, op) => {
      const eq = l === r || looseEq(l, r)
      return op.startsWith('!') ? !eq : eq
    })

  const andExpr = (): EvalFn =>
    binary(equality, ['&&'], (l, r) => (truthy(l) ? truthy(r) : false))

  const orExpr = (): EvalFn =>
    binary(andExpr, ['||'], (l, r) => (truthy(l) ? true : truthy(r)))

  function ternary(): EvalFn {
    const cond = orExpr()
    if (isOp('?')) {
      pos++
      const then = ternary()
      eat(':')
      const els = ternary()
      return (s) => (truthy(cond(s)) ? then(s) : els(s))
    }
    return cond
  }

  const result = ternary()
  if (pos < tokens.length) throw new SyntaxError(`表达式尾部存在多余内容：'${tokens[pos].value}'`)
  return result
}

function truthy(v: unknown): boolean {
  return v === true || (typeof v === 'number' && v !== 0) || (typeof v === 'string' && v !== '' && v !== 'false' && v !== '0')
}

function looseEq(l: unknown, r: unknown): boolean {
  if (l === null || r === null) return l === r
  const ln = typeof l === 'number' || typeof l === 'boolean'
  const rn = typeof r === 'number' || typeof r === 'boolean'
  if (ln && rn) return toNum(l) === toNum(r)
  return String(l) === String(r)
}

function str(v: unknown): string {
  if (v === null || v === undefined) return ''
  return typeof v === 'object' ? JSON.stringify(v) : String(v)
}

/** 编译缓存：同一表达式串只解析一次（虚拟变量每 tick 求值，解析开销必须摊销） */
const cache = new Map<string, EvalFn>()

/** 求值入口；出错抛异常（调用方决定缺省值与告警策略） */
export function evalExpr(src: string, scope: Scope): unknown {
  let fn = cache.get(src)
  if (!fn) {
    fn = parse(tokenize(src))
    cache.set(src, fn)
  }
  return fn(scope)
}

/** 提取表达式引用的标识符（排除内置/常量），供引擎构建依赖图 */
export function exprIdents(src: string): string[] {
  const idents: string[] = []
  for (const t of tokenize(src)) {
    if (t.type === 'ident' && !BUILTINS[t.value] && !['true', 'false', 'null'].includes(t.value) && !idents.includes(t.value)) {
      idents.push(t.value)
    }
  }
  return idents
}
