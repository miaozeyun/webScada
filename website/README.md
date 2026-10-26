# webScada 官网（静态站）

纯静态 HTML/CSS/JS，无构建依赖。「夜班控制室」暗色主题：信号青（实时数据）+ 琥珀（告警）双色，等宽字体仅用于数据读数，Hero 为纯 CSS 动画的遥测面板。

文案面向采购与业务负责人：先讲「解决什么问题」，技术口径收在 features.html 的「技术细节（给工程师看）」折叠区。

## 本地预览

```bash
cd website
python -m http.server 8090
# 浏览器打开 http://localhost:8090
```

## 产品截图

`assets/img/shots/` 下是产品真实运行界面截图（1600×900，JPEG）。重新生成需本地起 compose（8088）与 vite dev（5199），然后：

```bash
cd e2e
node shots.mjs   # 台账 / 编辑器 / 运行大屏 / 报警中心 / 仿真台
node shots2.mjs  # 卡片台账 / 分享管理
node shots4.mjs  # 分享管理（token 已脱敏）/ 数据源面板
```

新增截图时注意：不要把真实分享 token、账号信息截进图里；分享对话框截图前脚本会把 `.token` 文本替换为「演示链接」。

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
| `og-cover.svg` | 各页 og:image / twitter:image | 建议导出 1200×630 PNG（多数平台不渲染 SVG 分享图），改名 og-cover.png 并同步改引用 |

**页脚不预置 ICP 占位。** 挂一个假备案号会被扫站工具判为「备案信息异常」，比不挂更麻烦。
备案通过后执行 `./scripts/set-site-domain.sh <域名> "京ICP备12345678号-1"`，脚本把备案号写进各页页脚
（可重复执行，已写入的跳过）。未提供第二个参数时页脚保持无备案号状态。

境内服务器上线后 30 日内还需完成公安联网备案（beian.mps.gov.cn），通过后把「公网安备 XXXX 号」一并补进页脚。

开源仓库公开后，可在导航与页脚补回 GitHub 链接（源码中 TODO 已注明位置）。

联系方式（18835132457@163.com / 微信 miaozeyun2020）已按仓库 README 填入，如有变更同步更新 about.html、index.html 与 llms.txt。

## 域名与入口

| 站点 | 地址 | 说明 |
|---|---|---|
| 官网 | `https://www.zggkzy.cn` | 本目录，静态站 |
| 产品（试用） | `https://scada.zggkzy.cn` | 官网导航栏与首页 Hero 的「立即试用」按钮指向此处 |

两个域名指向同一台服务器的 nginx 容器，按 Host 精确分流：`www` 命中官网块，
`scada` 与 IP 访问命中产品默认块。DNS 需添加两条 A 记录。

「立即试用」按钮地址变更时全站替换：

```bash
grep -rl 'https://scada.zggkzy.cn/' website --include='*.html' \
  | xargs sed -i 's|https://scada.zggkzy.cn/|https://新地址/|g'
```

## 部署

### 方式一：与 webScada 同机（Docker compose，推荐）

官网已接入产品编排：`docker-compose.yml` 的 nginx 容器按域名精确分流，`website/`
只读挂载到容器 `/usr/share/nginx/site`，独立 server 块由
[deploy/nginx/templates/site.conf.template](../deploy/nginx/templates/site.conf.template) 渲染。

```bash
# 1) 一张证书同时覆盖官网与产品子域名（DNS 解析已生效、80 端口可达）
apt install -y certbot && mkdir -p deploy/acme
certbot certonly --webroot -w "$PWD/deploy/acme" \
  -d www.zggkzy.cn -d scada.zggkzy.cn \
  --agree-tos -m 你的邮箱@example.com --no-eff-email

# 2) 放入部署目录。产品 443 块写死 selfsigned.crt，复制同名即可共用同一张证书
cp /etc/letsencrypt/live/www.zggkzy.cn/fullchain.pem deploy/certs/site.crt
cp /etc/letsencrypt/live/www.zggkzy.cn/privkey.pem   deploy/certs/site.key
cp deploy/certs/site.crt deploy/certs/selfsigned.crt
cp deploy/certs/site.key deploy/certs/selfsigned.key
chmod 600 deploy/certs/*.key

# 3) 配置并重建 nginx（环境变量变化必须 up -d；restart 不会更新环境变量）
set_env() { grep -q "^$1=" .env && sed -i "s|^$1=.*|$1=$2|" .env || echo "$1=$2" >> .env; }
set_env SITE_DOMAIN www.zggkzy.cn
set_env SITE_CERT site.crt
set_env SITE_KEY site.key
docker compose up -d nginx
```

内容更新不需要重启：`git pull` 后 nginx 直接读取挂载目录的新文件。
`SITE_DOMAIN` 不能与产品域名相同；留空时官网块回落到 `.invalid` 占位域名，等同关闭。

证书续期（90 天）配置 deploy hook 自动同步并重启，见
[docs/operations/deploy-runbook.md](../docs/operations/deploy-runbook.md) 5.4 节。

### 方式二：独立 nginx（其他静态托管）

```nginx
server {
    listen 80;
    server_name www.example.com;
    root /var/www/webscada-site;
    index index.html;

    gzip on;
    # text/html 默认已包含，显式列出会触发 duplicate MIME type 告警
    gzip_types text/css application/javascript application/xml image/svg+xml text/plain;

    # GEO / 收录类文件不缓存
    location = /llms.txt    { add_header Cache-Control "no-cache"; }
    location = /robots.txt  { add_header Cache-Control "no-cache"; }
    location = /sitemap.xml { add_header Cache-Control "no-cache"; }

    # 资源文件名无内容哈希：用短缓存，改版后才能及时生效（不要设 immutable/30d）
    # expires 已同时输出 Expires 与 Cache-Control: max-age，勿再 add_header 重复声明
    location ~* \.(css|js|svg|png|jpe?g|webp|ico|woff2?)$ {
        expires 1h;
    }

    location / {
        add_header Cache-Control "no-cache";
        try_files $uri $uri/ =404;
    }

    error_page 404 /404.html;
}
```

同步上线：`rsync -avz --delete website/ user@server:/var/www/webscada-site/`。

## 收录提交

- 搜索引擎：Google Search Console、百度搜索资源平台提交 `https://域名/sitemap.xml`
- GEO 增强：在 AI 引擎侧建立引用没有直接提交入口，靠 llms.txt + 外部提及（GitHub README 互链、技术社区文章）积累；开源仓库 README 建议加一条指向本站的链接
