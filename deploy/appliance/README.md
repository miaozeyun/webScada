# 一体机离线交付（阶段三）

面向工厂内网/气隙环境与设备厂随机交付：**不要求现场装 Python/Node/外网**，只需要目标机
有 Docker Engine ≥25 + compose v2。硬件基线：x86_64、2C4G、32GB 磁盘（历史数据按 30 天基线）。

## 交付包内容

`build-offline.sh` 产出的目录/压缩包：

| 文件 | 用途 |
|---|---|
| `images.tar` | 全部运行镜像（postgres / emqx / server / nginx），`docker save` 产物 |
| `package.env` | 构建时镜像前缀 `REG_PREFIX`（安装/升级时同步进 `.env`，否则离线机镜像名对不上） |
| `docker-compose.yml` | 保留 `${VAR}` 占位（`config --no-interpolate`），密钥不固化进包 |
| `deploy/` | nginx 配置、证书目录、本目录脚本 |
| `scripts/` | 备份/恢复、证书生成、仿真台（可选） |
| `.env.example` | 全新安装可参考；`install.sh` 会直接生成随机 `.env` |
| `install.sh` / `upgrade.sh` / `rollback.sh` | 首次安装 / 升级 / 回滚 |
| `webscada.service` | systemd 开机自启（WorkingDirectory 默认 `/opt/webscada`） |
| `SHA256SUMS` + 外层 `.tar.gz.sha256` | 传输完整性校验 |

## 制作（有外网的构建机）

```bash
cp .env.example .env      # 构建期只需要 REG_PREFIX / PIP_INDEX_URL 等镜像源配置
./deploy/appliance/build-offline.sh
# → dist/appliance-YYYYMMDD.tar.gz + .sha256
```

国内构建建议在 `.env` 设 `REG_PREFIX=m.daocloud.io/docker.io/`，pip/npm 已在 Dockerfile 用国内源。

## 现场安装（气隙机）

```bash
sha256sum -c appliance-YYYYMMDD.tar.gz.sha256
tar xzf appliance-YYYYMMDD.tar.gz && cd appliance-YYYYMMDD
sudo ./install.sh 8088          # 端口按现场；默认 80
```

`install.sh` 会：载入镜像 → 生成随机 `JWT_SECRET / DATASOURCE_SECRET / 数据库口令 / 管理员口令`
→ 启动 → 轮询 `/api/v1/health`。**管理员初始密码只在安装输出里显示一次**，登录后立即修改。

开机自启：

```bash
sudo cp webscada.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now webscada
```

## 升级与回滚

```bash
# 先备份（强烈建议）
./scripts/backup.sh
# 解压新包后执行
sudo ./upgrade.sh ../appliance-20261101
# 新版本健康检查失败会自动调用 rollback.sh；也可手动：
sudo ./rollback.sh
```

升级只替换镜像与编排/nginx 配置，**不动 `.env`、证书与数据卷**。

## 已知边界（诚实清单）

- 脚本假设镜像名是 compose 项目名派生的 `webscada-server` / `webscada-nginx`；改 `name:` 需同步改脚本。
- 只支持 x86_64；ARM/龙芯等需自行构建对应镜像。
- 断电自启依赖 Docker 的 `restart: unless-stopped` + systemd 单元；首次开机仍建议人工确认一次。
- 升级回滚不会回滚数据库迁移：跨大版本升级前必须先做 `backup.sh`，并阅读 CHANGELOG 的迁移说明。
- 脚本未在真实气隙硬件上做过 72h 长跑验收；首次交付请按 `docs/operations/backup-restore.md` 做一次恢复演练。
