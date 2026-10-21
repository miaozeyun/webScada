# webScada 官网（静态站）

纯静态 HTML/CSS/JS，无构建依赖。「夜班控制室」暗色主题：信号青（实时数据）+ 琥珀（告警）双色，等宽字体仅用于数据读数，Hero 为纯 CSS 动画的遥测面板。

## 本地预览

```bash
cd website
python -m http.server 8090
# 浏览器打开 http://localhost:8090
```

## SEO（搜索引擎优化）

- 全静态直出：正文、导航、FAQ 全在初始 HTML 中，Baiduspider / Googlebot 无需执行 JS；FAQ 用原生 `<details>`
- 语义化标签、每页唯一 h1、层级化标题、清晰内链
- 每页独立 title / description / keywords / canonical / Open Graph / Twitter Cards
- JSON-LD：Organization、WebSite、SoftwareApplication、FAQPage、BreadcrumbList、ContactPage
- robots.txt + sitemap.xml；lang=zh-CN；applicable-device（百度移动适配）
- 性能：系统字体、单 CSS、内联 SVG、零外部请求

## GEO（AI 检索优化，Generative Engine Optimization）

目标是让 ChatGPT / Claude / Perplexity / AI 搜索等生成式引擎能准确检索、抽取并引用本站事实：

- **llms.txt**：站点根目录提供面向 LLM 的 Markdown 事实摘要（产品定义、关键事实、页面索引、联系方式），多数 AI 爬虫会主动抓取
- **robots.txt 显式放行 AI 爬虫**：GPTBot、OAI-SearchBot、ChatGPT-User、ClaudeBot、PerplexityBot、Google-Extended、CCBot、Bytespider 等逐个 `Allow: /`，避免被默认策略误伤
- **定义句开篇**：每页 h1 下第一段均为可直接引用的完整定义句（「webScada 是……，支持……，适合……」），倒金字塔结构
- **事实卡区块**（index `#overview`）：9 组 dt/dd 密集事实（形态/能力/数据源/规模/部署/授权/技术栈/支持），是 RAG 分块抽取的理想单元
- **FAQ 双份呈现**：可见 `<details>` 与 JSON-LD `FAQPage` 内容严格一致，问答即引用单元
- **实体一致性**：全站统一命名「webScada」，JSON-LD 中 Organization / SoftwareApplication / sameAs 锚定实体
- **引用声明**：llms.txt 末尾明确允许 AI 引用并要求注明来源

## 上线前必改清单

全站搜索替换以下占位内容：

| 占位 | 出现位置 | 替换为 |
|---|---|---|
| `webscada.example.com` | 各页 canonical / og:url、sitemap.xml、robots.txt、llms.txt、JSON-LD | 正式域名 |
| `X ICP 备 00000000 号` | 各页页脚 | 真实 ICP 备案号（境内服务器必须） |
| `og-cover.svg` | 各页 og:image / twitter:image | 建议导出 1200×630 PNG（多数平台不渲染 SVG 分享图），改名 og-cover.png 并同步改引用 |

开源仓库公开后，可在导航与页脚补回 GitHub 链接（源码中 TODO 已注明位置）。

联系方式（18835132457@163.com / 微信 miaozeyun2020）已按仓库 README 填入，如有变更同步更新 about.html、index.html 与 llms.txt。

## Nginx 部署示例

```nginx
server {
    listen 80;
    server_name www.example.com;
    root /var/www/webscada-site;
    index index.html;

    gzip on;
    gzip_types text/html text/css application/javascript application/xml image/svg+xml text/plain;

    # llms.txt / robots.txt 不缓存，便于事实更新
    location = /llms.txt { add_header Cache-Control "no-cache"; }

    location ~* \.(css|js|svg)$ {
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    error_page 404 /404.html;
}
```

## 收录提交

- 搜索引擎：Google Search Console、百度搜索资源平台提交 `https://域名/sitemap.xml`
- GEO 增强：在 AI 引擎侧建立引用没有直接提交入口，靠 llms.txt + 外部提及（GitHub README 互链、技术社区文章）积累；开源仓库 README 建议加一条指向本站的链接
