# webScada 官网（静态站）

纯静态 HTML/CSS/JS，无构建依赖。「夜班控制室」暗色主题：信号青（实时数据）+ 琥珀（告警）双色，等宽字体仅用于数据读数。首屏是「置顶案例实况轮播」：三段分享页真实运行画面的录屏铺满整个首屏（`object-fit:cover`，超宽/超高部分裁切），10s 自动轮换（无 JS / 视频不可用时退化为同画面海报 + 缓推近）。页头不带实心条：默认是一层自上而下渐隐的暗色渐变，画面透过页头可见；页面滚动后才转为半透明玻璃底。案例切换条同样是透明浮层，位于首屏底部 96px。首屏光晕与页头色调跟随当前案例画面的主色（风电青 / 数据中心紫 / 产线琥珀），且光晕形态按案例区分：`data-glow="sea"` 上下地平线辉光 + 柔边、`dc` 对角双角冷光、`line` 底部炉火 + 两侧余晖，呼吸周期也各不相同。主色由 `showcase.js` 采样海报得出，取色失败时用 `.sc-slide[data-accent]` 兜底。主文案带排在首屏之后（滚动一屏可见）。

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

## 首屏置顶案例实况轮播（视频素材）

`assets/media/` 下是三个置顶案例（海上风电 / 数据中心 / 智能制造产线）的实况录屏：

- `{key}.webm`：1920×1080 VP9，约 18s 循环，20fps，单段 1–2.2MB；页面只加载当前段 + 下一段
- `{key}-poster.jpg`：同画面首帧，`<video>` 就绪前 / 不支持 VP9 / 减少动态偏好时展示

录制与压缩（需 vite dev 5199 + compose 8088 在跑，脚本会先用分享页的公开接口取 doc，
把 6 小时分钟桶历史写进录制上下文的 localStorage，否则「近 1 小时」趋势图是空的）：

```bash
cd e2e
node record-showcase.mjs   # 产出未压缩 webm 到 website/assets/media/
# 再用 Playwright 自带 ffmpeg 压到 1080p VP9（系统无 ffmpeg 时可用它）：
# ffmpeg -i x.webm -an -r 20 -c:v libvpx-vp9 -b:v 0 -crf 36 -row-mt 1 x.webm
```

切换/自动轮播逻辑在 `assets/js/showcase.js`：`.sc-strip` 是 `#showcase` 内部的绝对定位浮层，
脚本按全文档取 `.sc-case` / `.sc-arrow`；首段一开始播就预载其余段（窄屏只预载下一段），
且视频要等「播放推进 + 已缓冲 + 抽帧不是白底」才淡入（Chrome 首帧解码前会把 video 画成白底，
实测可达 2s，直接淡入就是肉眼可见的切换白屏）。探测仅用于「提前」显示：已缓冲且播放超过 2.2s 仍未确认可画就直接显示，
避免个别解码路径抽帧恒白时永远停在海报（观感就是「画面里的数据不动」）；海报始终垫在下方。
每次切换会把当前海报的主色写进 `--sc-accent`（同色相浅色版写进 `--sc-accent-soft`，供切换条序号/标签/箭头等小字用），
并把 `.sc-slide[data-glow]` 同步到 `#showcase[data-glow]`，光晕、页头染色、切换条（边框/序号/标签/进度条/箭头）随之改变
（取色规则：跳过暗底与灰白读数，按艳度²×亮度加权平均后统一拉高饱和/明度，否则深色大屏取出来接近黑色）。IntersectionObserver 离开视口或切后台即停播省电，
`prefers-reduced-motion` 下只显示海报；点击案例卡、左右箭头、触摸滑动均可切换。

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
| 产品（试用） | `http://103.236.97.137:39109`（临时演示地址） | 官网导航栏与首页首屏的「立即试用」按钮指向此处；正式域名上线后全站替换 |

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

### 方式三：独立 nginx 容器（一键，不碰产品编排）

仓库自带一键脚本，把一个 nginx 容器跑起来托管本目录，宿主机端口默认 **39109**，
与根目录 `docker-compose.yml` 的产品栈完全隔离（不占 80/443）：

```bash
./deploy/website/deploy.sh          # http://<服务器IP>:39109/
./deploy/website/deploy.sh -p 8080  # 换端口
./deploy/website/deploy.sh --help   # 全部选项
```

站点目录以只读方式挂载，`git pull` 后内容立刻生效；只有改 nginx.conf 才需要重跑脚本。
脚本会先跑 `nginx -t` 校验配置再启动，写错不会把线上站点搞挂。
纯 HTTP 方案，要 HTTPS 请走方式一或在前置反代上终止 TLS。详见
[deploy/website/README.md](../deploy/website/README.md)。

## 收录提交

- 搜索引擎：Google Search Console、百度搜索资源平台提交 `https://域名/sitemap.xml`
- GEO 增强：在 AI 引擎侧建立引用没有直接提交入口，靠 llms.txt + 外部提及（GitHub README 互链、技术社区文章）积累；开源仓库 README 建议加一条指向本站的链接
