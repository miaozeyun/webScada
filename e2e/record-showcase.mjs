// 官网旗舰案例轮播素材：从分享页录制真实运行态视频（webm），并预置 6h 分钟桶历史，
// 让「近 1 小时」趋势图有数据（分享页历史走本地分钟桶兜底），最后抽首帧海报。
// 用法：node record-showcase.mjs（需 5199 vite dev + 8088 compose 在跑）
import { chromium } from 'playwright'
import { mkdirSync, copyFileSync, writeFileSync } from 'node:fs'

const BASE = 'http://localhost:5199'
const API = 'http://localhost:8088/api/v1'
const OUT = 'F:/mycode/webScada/website/assets/media'
mkdirSync(OUT, { recursive: true })

const CASES = [
  { key: 'line', token: 'WK1Soo8dCS5Yg9T1PHJdpeKJ0LX-Xklb' },
  { key: 'wind', token: '59K9YaJBRix_pf-wPkgn4CY7J0R4JpPk' },
  { key: 'datacenter', token: '8nfJQOkM-l9_PvdycAK1kvKD1Dd6iOVl' },
]

/** 与 web/src/utils/demos/index.ts mockValueAt 同口径 */
function mockValueAt(spec, t, seed) {
  switch (spec.kind) {
    case 'hold':
      return null
    case 'sine':
      return spec.min + (spec.max - spec.min) * (0.5 + 0.5 * Math.sin((2 * Math.PI * t) / spec.periodMs))
    case 'ramp': {
      const p = (t % spec.periodMs) / spec.periodMs
      return p < 0.5 ? spec.min + (spec.max - spec.min) * p * 2 : spec.max - (spec.max - spec.min) * (p - 0.5) * 2
    }
    case 'square': {
      const p = (t % spec.periodMs) / spec.periodMs
      return p < (spec.duty ?? 0.5) ? spec.onValue : spec.offValue
    }
    case 'random': {
      const x = Math.sin(seed * 9301 + Math.floor(t / 60000) * 49297) * 233280
      const r = x - Math.floor(x)
      return spec.min + r * (spec.max - spec.min)
    }
    default:
      return null
  }
}

/** 生成 6h 分钟桶：{ varId: [[tsMin, sum, n], ...] } */
function seedBuckets(doc, hours = 6) {
  const BUCKET = 60_000
  const now = Date.now()
  const out = {}
  let seed = 1
  for (const v of doc.variables ?? []) {
    if (!v.mock) continue
    seed++
    const arr = []
    for (let m = hours * 60; m >= 0; m--) {
      const t = now - m * BUCKET
      const val = mockValueAt(v.mock, t, seed)
      if (val === null || !Number.isFinite(val)) continue
      const tsMin = Math.floor(t / BUCKET) * BUCKET
      arr.push([tsMin, val, 1])
    }
    if (arr.length) out[v.id] = arr
  }
  return out
}

const browser = await chromium.launch()

for (const c of CASES) {
  const share = await (await fetch(`${API}/shares/${c.token}`)).json()
  const buckets = seedBuckets(share.doc)
  const payload = JSON.stringify(buckets)
  writeFileSync(`${OUT}/${c.key}-seed.json`, payload)

  const ctx = await browser.newContext({
    viewport: { width: 1920, height: 1080 },
    deviceScaleFactor: 1,
    locale: 'zh-CN',
    recordVideo: { dir: `${OUT}/raw`, size: { width: 1920, height: 1080 } },
  })
  await ctx.addInitScript((data) => {
    try {
      localStorage.setItem('webscada:hist:v1', data)
    } catch {
      /* 忽略 */
    }
  }, payload)
  const page = await ctx.newPage()
  await page.goto(`${BASE}/s/${c.token}?embed=1`, { waitUntil: 'networkidle' })
  // 营销素材：隐藏右上角可能遮挡画面的报警通知卡，保留画面本身的跳动
  await page.addStyleTag({ content: '.el-notification,.el-message,.el-message-box{display:none!important}' })
  await page.waitForTimeout(5000)
  await page.screenshot({ path: `${OUT}/${c.key}-poster.jpg`, type: 'jpeg', quality: 88 })
  await page.waitForTimeout(13000)
  await ctx.close()
  const video = await page.video().path()
  copyFileSync(video, `${OUT}/${c.key}.webm`)
  console.log('saved', c.key)
}

await browser.close()
console.log('done')
