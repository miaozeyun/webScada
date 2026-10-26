// 官网本地自检：逐页截图 + 收集控制台错误 + 检查内链/锚点
import { chromium } from 'playwright'
import { mkdirSync } from 'node:fs'

const BASE = 'http://localhost:8090'
const OUT = 'F:/mycode/webScada/website/.preview'
mkdirSync(OUT, { recursive: true })

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 })
const errors = []
page.on('console', (m) => {
  if (m.type() === 'error') errors.push(`${page.url()} · ${m.text()}`)
})
page.on('pageerror', (e) => errors.push(`${page.url()} · ${e.message}`))
page.on('response', (r) => {
  if (r.status() >= 400) errors.push(`${page.url()} · HTTP ${r.status()} ${r.url()}`)
})

const pages = ['index.html', 'features.html', 'editions.html', 'about.html']
for (const p of pages) {
  await page.goto(`${BASE}/${p}`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(400)
  await page.screenshot({ path: `${OUT}/${p.replace('.html', '')}.png`, fullPage: true })
  const links = await page.$$eval('a[href]', (as) => as.map((a) => a.getAttribute('href')))
  for (const href of new Set(links)) {
    if (!href || href.startsWith('http') || href.startsWith('mailto:') || href.startsWith('#')) continue
    const [path, hash] = href.split('#')
    const targetPath = path || p
    const res = await page.request.get(`${BASE}/${targetPath}`)
    if (!res.ok()) {
      errors.push(`${p} · 死链 ${href} (${res.status()})`)
      continue
    }
    if (hash) {
      const html = await res.text()
      if (!html.includes(`id="${hash}"`)) errors.push(`${p} · 锚点未找到 ${targetPath}#${hash}`)
    }
  }
}

// 移动端首页
await page.setViewportSize({ width: 390, height: 844 })
await page.goto(`${BASE}/index.html`, { waitUntil: 'networkidle' })
await page.screenshot({ path: `${OUT}/mobile-index.png`, fullPage: true })

await browser.close()
console.log(errors.length ? errors.join('\n') : 'no errors')
