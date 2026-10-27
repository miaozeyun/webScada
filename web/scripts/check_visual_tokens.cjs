#!/usr/bin/env node
/**
 * 视觉令牌门禁：CLAUDE.md「全站 UI 色彩走 theme.css 令牌，勿在组件里硬编码色值」的可执行化。
 *
 * 规则：
 * - 扫描 web/src 下 .vue/.ts/.css 的硬编码色值（#hex 3-8 位 / rgb()/rgba()）。
 * - 内容口径文件/目录整表豁免（令牌定义本体、图表色板、演示与模板工程、仿真台、测试）。
 * - 行级豁免：该行或上一行含「token-exempt」标记（doc 内容口径缺省色等）。
 * - 存量 UI 违规登记在 visual_tokens_baseline.json（键 file::literal → 允许条数）：
 *   基线外新增 / 超出基线条数 → exit 1 并输出 file:line；低于基线只提示可缩减。
 *   清理存量时同步缩减基线，最终趋零。
 *
 * 用法：node scripts/check_visual_tokens.cjs [--update]（--update 用当前扫描结果重写基线）
 */
const fs = require('fs')
const path = require('path')

const SRC = path.resolve(__dirname, '..', 'src')
const BASELINE = path.join(__dirname, 'visual_tokens_baseline.json')

/** 内容口径豁免（永久，不进基线）：令牌/色板定义、写进 doc 的演示与模板内容、测试断言 */
const EXEMPT = [
  'styles/theme.css', // 令牌定义本体（单一来源）
  'utils/theme.ts', // 五主题令牌定义与派生计算
  'widgets/chart/shared.ts', // 图表固定色板（内容口径，与 UI 主题解耦）
  'utils/demos/', // 行业 demo 工程（doc 内容）
  'utils/pageTemplates/', // 画面模板（doc 内容）
  'utils/stressDoc.ts', // 压测 doc 生成器（内容）
  'views/SimulatorView.vue', // 仿真台示意画面（内容）
  '__tests__/', // 测试目录
]

const HEX_RE = /#[0-9a-fA-F]{3,8}\b/g
const RGB_RE = /\brgba?\(\s*\d/g

function walk(dir, out) {
  for (const name of fs.readdirSync(dir)) {
    const p = path.join(dir, name)
    const st = fs.statSync(p)
    if (st.isDirectory()) walk(p, out)
    else if (/\.(vue|ts|css)$/.test(name) && !/\.spec\.ts$/.test(name) && !/\.d\.ts$/.test(name)) out.push(p)
  }
}

function rel(p) {
  return path.relative(SRC, p).split(path.sep).join('/')
}

function isExempt(relPath) {
  return EXEMPT.some((e) => relPath === e || relPath.startsWith(e))
}

function scan() {
  const files = []
  walk(SRC, files)
  const found = [] // { relPath, line, literal }
  for (const f of files) {
    const r = rel(f)
    if (isExempt(r)) continue
    const lines = fs.readFileSync(f, 'utf8').split(/\r?\n/)
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i]
      const exemptMark = line.includes('token-exempt') || (i > 0 && lines[i - 1].includes('token-exempt'))
      if (exemptMark) continue
      for (const m of line.matchAll(HEX_RE)) found.push({ relPath: r, line: i + 1, literal: m[0] })
      if (RGB_RE.test(line)) found.push({ relPath: r, line: i + 1, literal: (line.match(/\brgba?\([^)]*\)/) || ['rgb?'])[0] })
    }
  }
  return found
}

function main() {
  const found = scan()
  const counts = new Map() // key -> { count, hits[] }
  for (const f of found) {
    const key = `${f.relPath}::${f.literal}`
    if (!counts.has(key)) counts.set(key, { count: 0, hits: [] })
    const e = counts.get(key)
    e.count++
    if (e.hits.length < 5) e.hits.push(`${f.relPath}:${f.line}`)
  }

  if (process.argv.includes('--update')) {
    const baseline = {}
    for (const [key, e] of counts) baseline[key] = e.count
    fs.writeFileSync(BASELINE, JSON.stringify({ __note: '存量 UI 硬编码色值基线：清理后用 --update 缩减，目标趋零', ...baseline }, null, 2) + '\n')
    console.log(`基线已更新：${counts.size} 个键，共 ${found.length} 处`)
    return
  }

  const baseline = fs.existsSync(BASELINE) ? JSON.parse(fs.readFileSync(BASELINE, 'utf8')) : {}
  const violations = []
  const shrinkable = []
  for (const [key, e] of counts) {
    const allowed = baseline[key] ?? 0
    if (e.count > allowed) violations.push({ key, hits: e.hits, delta: e.count - allowed })
  }
  for (const key of Object.keys(baseline)) {
    if (key.startsWith('__')) continue
    const cur = counts.get(key)
    if (!cur || cur.count < baseline[key]) shrinkable.push(key)
  }

  if (violations.length) {
    console.error('✗ 视觉令牌门禁未通过——以下硬编码色值超出基线（应改用 theme.css 令牌，或在内容口径处补 token-exempt 注释）：')
    for (const v of violations) {
      console.error(`  ${v.key}（新增 ${v.delta} 处）`)
      for (const h of v.hits) console.error(`    ${h}`)
    }
    console.error(`\n共 ${violations.length} 个键违规。存量清理请登记/缩减 scripts/visual_tokens_baseline.json。`)
    process.exit(1)
  }
  if (shrinkable.length) {
    console.log(`提示：${shrinkable.length} 个基线键已可缩减（清理存量后运行 node scripts/check_visual_tokens.cjs --update）`)
  }
  console.log(`✓ 视觉令牌门禁通过：当前 ${found.length} 处存量（${counts.size} 键），无新增违规`)
}

main()
