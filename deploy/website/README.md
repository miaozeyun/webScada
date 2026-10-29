# 官网一键部署（独立 nginx 容器）

把 `website/` 静态站用**一个 nginx 容器**跑起来，宿主机端口默认 **39109**。
与产品编排（根目录 `docker-compose.yml`）完全独立，不影响 80/443 上的组态系统。

## 一键启动

```bash
./deploy/website/deploy.sh            # http://<服务器IP>:39109/
```

脚本会依次做：环境校验 → 端口占用检查 → `nginx -t` 配置校验 → 拉镜像 → 启动容器 → 健康检查，
任一步失败都会明确报错并停下（配置写错不会把线上站点搞挂）。

## 常用命令

```bash
./deploy/website/deploy.sh -p 8080        # 换宿主机端口
./deploy/website/deploy.sh --pull         # 拉取最新 nginx 镜像
./deploy/website/deploy.sh --logs         # 看日志（Ctrl+C 退出）
./deploy/website/deploy.sh --down         # 停止并移除容器
./deploy/website/deploy.sh --help         # 全部选项
```

## 目录说明

| 文件 | 作用 |
|---|---|
| `deploy.sh` | 一键部署脚本（幂等，重复执行即更新） |
| `docker-compose.yml` | 单容器编排，站点目录只读挂载 `../../website` |
| `nginx.conf` | 站点配置：gzip、缓存策略、安全头、隐藏目录拒绝 |
| `.env` | 脚本生成，只存 `SITE_PORT` / `REG_PREFIX`，不要手工加密钥 |

## 运维要点

- **改页面内容不用重启**：`website/` 是只读挂载，`git pull` 后刷新浏览器即生效。
- **视频素材必须以 `application/octet-stream` 发出**：`nginx.conf` 里 `~* \.(webm|mp4|m4v)$` 单独一条
  location 做了这件事，且必须排在 `.css|.js|...` 资源正则**之前**。原因：部分链路（客户端安全软件 /
  运营商 / 机房前置）会把 `Content-Type: video/*` 的响应整段卡死——表现为 `HEAD` 正常但 `GET`
  一个字节都不返回，首屏录屏永远停在 poster 上，看起来就是「画面里的数据不动」。浏览器对 `<video>`
  按内容嗅探解码，改 MIME 不影响播放。改这条规则前先确认链路是否仍拦截 video MIME。
- **只有改 `nginx.conf` 才需要重跑脚本**（或 `docker compose -f deploy/website/docker-compose.yml restart site`）。
- **端口要放行**：云服务器安全组 + 主机防火墙，否则外网访问不到。
- **本方案是纯 HTTP**。要 HTTPS：走主编排的 `SITE_DOMAIN` 方案（见 `website/README.md` 方式一），
  或在这台机器前面挂一层 Caddy / 云负载均衡做 TLS 终止。
- **镜像加速**：默认复用根目录 `.env` 里的 `REG_PREFIX`（如 `m.daocloud.io/docker.io/`），
  也可 `--reg-prefix` 临时指定。
