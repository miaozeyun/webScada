# 服务器部署操作手册（产品 + 官网）

> 面向第一次上服务器的操作者：从登录、拉代码到产品与官网都能访问。
> 脚本说明见 [deploy/deploy.sh](../../deploy/deploy.sh)、官网配置见 [website/README.md](../../website/README.md)。
> 下文用 `www.example.com` 作示例域名，替换成你的真实域名。

## 0. 准备清单

| 项目 | 要求 |
|---|---|
| 服务器 | Ubuntu 22.04/24.04 或 Debian 12，2 核 4G 起，磁盘 ≥40G |
| Docker | Engine ≥25 + Compose v2（本手册不安装 Docker） |
| 域名 | 已备案，能修改 DNS 解析 |
| 网络 | 云安全组 / 本机防火墙放行 22、80、443 |
| 端口 | 80/443 未被其他程序占用（`ss -ltnp | grep -E ':80|:443'`） |

## 1. 登录与检查

```bash
ssh root@<服务器公网IP>

cat /etc/os-release            # 确认发行版
docker compose version         # 需 v2.x
docker info >/dev/null && echo "docker 可用"
df -h /                        # 根分区 ≥5G 可用
free -m                        # ≥2G
```

Docker 未安装（仅提示，装法见官方文档）：

```bash
curl -fsSL https://get.docker.com | sh
systemctl enable --now docker
```

非 root 用户需加入 docker 组并重新登录：`usermod -aG docker <用户名>`。

## 2. 拉代码

约定部署目录 `/opt/webScada`（备份脚本与 crontab 示例均按此路径）。

```bash
mkdir -p /opt && cd /opt
git clone https://gitee.com/miao_zeyun/web-scada.git webScada
cd /opt/webScada
```

私有仓库需要凭证；服务器拉取困难时可在本机打包上传（此后无法用 `--pull` 更新）：

```bash
# 本机
tar czf webscada-src.tar.gz --exclude=.git --exclude=node_modules --exclude=.venv .
scp webscada-src.tar.gz root@<IP>:/opt/

# 服务器
mkdir -p /opt/webScada && tar xzf /opt/webscada-src.tar.gz -C /opt/webScada
```

## 3. 首次部署产品

```bash
cd /opt/webScada
bash deploy/deploy.sh
```

国内网络构建慢或失败时加镜像前缀：

```bash
bash deploy/deploy.sh --reg-prefix m.daocloud.io/docker.io/
```

脚本会生成 `.env` 随机密钥、构建镜像、启动并等待健康检查。**管理员初始密码只在输出中显示一次，立刻记录下来**。
默认访问 `http://<服务器IP>/`（80 端口）。

自检：

```bash
docker compose ps                          # 四个服务 healthy
curl -fsS http://127.0.0.1/api/v1/health   # 返回 ok
```

## 4. 域名解析与防火墙

在 DNS 控制台添加记录：

| 主机记录 | 类型 | 值 |
|---|---|---|
| `www` | A | 服务器公网 IP |
| `@`（可选，裸域名） | A | 服务器公网 IP |

验证解析已生效（可能要等几分钟到几小时）：

```bash
getent hosts www.example.com
```

放行端口（已启用 ufw 时）：

```bash
ufw allow 22/tcp && ufw allow 80/tcp && ufw allow 443/tcp
ufw status
```

云服务器还要在控制台安全组放行 80/443。

## 5. 申请 HTTPS 证书（Let's Encrypt，可自动续期）

用 webroot 方式，续期时不需要停 nginx。

### 5.1 先让官网域名块生效（此时用自签证书，浏览器会告警）

```bash
cd /opt/webScada

# 幂等写 .env：已有该键则替换，没有则追加
set_env() { grep -q "^$1=" .env && sed -i "s|^$1=.*|$1=$2|" .env || echo "$1=$2" >> .env; }

set_env SITE_DOMAIN www.example.com
docker compose up -d nginx          # 改了 environment，必须 up -d 重建容器
```

> `SITE_CERT`/`SITE_KEY` 暂不填，回落到自签证书，仅用于让 80 端口的 ACME 校验路径可用。
> Docker 行为差异：改 `.env`（环境变量）要 `up -d` 重建；只改模板文件或证书文件要
> `docker compose restart nginx`——配置没变时 `up -d` 不会动容器，模板不会重新渲染。

### 5.2 申请证书

```bash
apt update && apt install -y certbot
mkdir -p /opt/webScada/deploy/acme

certbot certonly --webroot -w /opt/webScada/deploy/acme \
  -d www.example.com -d example.com \
  --agree-tos -m you@example.com --no-eff-email
```

成功后有 `/etc/letsencrypt/live/www.example.com/{fullchain,privkey}.pem`。

### 5.3 放入部署目录并启用

```bash
cd /opt/webScada
cp /etc/letsencrypt/live/www.example.com/fullchain.pem deploy/certs/site.crt
cp /etc/letsencrypt/live/www.example.com/privkey.pem   deploy/certs/site.key
chmod 600 deploy/certs/site.key

set_env() { grep -q "^$1=" .env && sed -i "s|^$1=.*|$1=$2|" .env || echo "$1=$2" >> .env; }
set_env SITE_CERT site.crt
set_env SITE_KEY site.key
docker compose up -d nginx          # 环境变量变化 → 重建容器并加载新证书
```

### 5.4 自动续期 + 自动生效

Let's Encrypt 证书 90 天到期，certbot 的 systemd timer 会自动续期，但需要把新证书同步到 `deploy/certs/` 并重启 nginx：

```bash
mkdir -p /etc/letsencrypt/renewal-hooks/deploy
cat > /etc/letsencrypt/renewal-hooks/deploy/webscada.sh <<'EOF'
#!/bin/sh
set -e
SRC=/etc/letsencrypt/live/www.example.com
DST=/opt/webScada/deploy/certs
cp "$SRC/fullchain.pem" "$DST/site.crt"
cp "$SRC/privkey.pem" "$DST/site.key"
chmod 600 "$DST/site.key"
# 只换了证书文件、环境变量没变：up -d 不会动容器，必须 restart 才会重读证书
cd /opt/webScada && docker compose restart nginx
EOF
chmod +x /etc/letsencrypt/renewal-hooks/deploy/webscada.sh
systemctl list-timers | grep certbot          # 确认定时器已启用
certbot renew --dry-run                        # 演练续期
```

> 用云厂商免费证书也可以：控制台申请 → 下载 Nginx 格式 → 把 `.pem`/`.key` 传成
> `deploy/certs/site.crt`、`site.key`，跳过 5.2–5.4。到期手动换文件并 `docker compose up -d nginx`。

## 6. 官网域名与 ICP 替换

全站有 40 处 `webscada.example.com` 与 4 处 ICP 占位，替换后才符合收录与备案要求。

**推荐在本地仓库替换后推送，服务器只拉代码**（避免服务器工作区变脏，影响后续 `deploy.sh --pull`）：

```bash
# 本地开发机
./scripts/set-site-domain.sh www.example.com "京ICP备12345678号-1"
git add website && git commit -m "site: 替换正式域名与备案号" && git push

# 服务器
cd /opt/webScada && git pull --ff-only
```

只有服务器一份代码时，直接在服务器执行替换并提交：

```bash
cd /opt/webScada
./scripts/set-site-domain.sh www.example.com "京ICP备12345678号-1"
git add website && git commit -m "site: 替换正式域名与备案号"
```

> 之后升级若报「存在未提交的本地改动」，先 `git status` 确认，再 `git stash` 或提交。

## 7. 验收

```bash
curl -sI https://www.example.com/ | head -5                  # 200 + 证书（-k 可跳过校验）
curl -sI http://www.example.com/about.html | head -1         # 301 → https
curl -s https://www.example.com/llms.txt | head -3           # GEO 事实摘要
curl -sI https://www.example.com/assets/css/style.css        # max-age=3600
curl -s -o /dev/null -w '%{http_code}\n' https://www.example.com/not-exist   # 404
docker compose ps
docker compose logs nginx --tail 20
```

浏览器检查：首页、features/about/editions、404 页面、证书链正常（无告警）。

产品站仍走默认 server，用 `http://<服务器IP>/` 访问；官网走 `https://www.example.com/`。
两者互不影响。

## 8. 日常操作

```bash
cd /opt/webScada

# 升级产品（自动备份 → 构建 → 健康校验，失败自动回滚）
bash deploy/deploy.sh --pull

# 只更新官网内容（静态文件直读挂载目录，不需要重启）
git pull --ff-only

# 改 .env 的 SITE_* 后（环境变量变化，需重建容器）
docker compose up -d nginx

# 改官网模板 / 换证书文件后（配置没变，up -d 不会动容器，必须 restart）
docker compose restart nginx

# 手动备份
./scripts/backup.sh
```

每日自动备份（`crontab -e`）：

```cron
30 2 * * * cd /opt/webScada && ./scripts/backup.sh >> backups/backup.log 2>&1
```

## 9. 排错

| 现象 | 排查 |
|---|---|
| nginx 起不来 | `docker compose logs nginx`；多为 `SITE_CERT`/`SITE_KEY` 指向的文件不在 `deploy/certs/` |
| 访问域名仍是产品页 | `SITE_DOMAIN` 没生效（未 `up -d nginx`）或与产品域名相同 |
| 502 Bad Gateway | `docker compose logs server`，server 未 healthy 或数据库迁移失败 |
| 证书申请失败 | 域名未解析到本机、80 端口未放行、其他程序占用 80（`ss -ltnp`） |
| 续期没生效 | `certbot certificates` 看到期时间；hook 是否可执行；`docker compose up -d nginx` 是否成功 |
| 部署脚本报端口被占用 | `ss -ltnp | grep -E ':80|:443'`，停掉占用进程或用 `-p/-s` 换端口 |
| 构建失败 | 国内网络加 `--reg-prefix m.daocloud.io/docker.io/`；`docker compose build --no-cache` 排除缓存 |

更多数据恢复见 [backup-restore.md](backup-restore.md)。

## 10. 目录与文件速查

| 路径 | 内容 |
|---|---|
| `/opt/webScada/.env` | 全部密钥与端口（**离线备份，勿入库**） |
| `/opt/webScada/deploy/certs/` | TLS 证书与私钥 |
| `/opt/webScada/deploy/acme/` | Let's Encrypt HTTP-01 校验文件（自动生成） |
| `/opt/webScada/website/` | 官网静态文件（挂载进 nginx） |
| `/opt/webScada/backups/` | 数据库/附件备份 |
| 数据卷 | `docker volume ls | grep webscada`（pgdata / emqx_data / emqx_log / uploads_data） |
