# webScada Docker 部署手册

> 面向部署/运维人员。开发与架构说明见 [README.md](README.md)，架构设计契约见
> [docs/design/01-整体架构与目录结构.md](docs/design/01-整体架构与目录结构.md) §2.2 部署拓扑。

## 1. 环境要求

- Docker Engine ≥ 25（Windows 为 Docker Desktop ≥ 4.30）
- Docker Compose v2（`docker compose` 子命令形式；v1 `docker-compose` 不保证兼容）
- 2 GB 以上可用内存（EMQX + PostgreSQL + FastAPI + Nginx 全家桶）

## 2. 镜像加速（国内环境）

`.env` 中一条配置即可切换全部基础镜像（Dockerfile `FROM` 与 compose `image` 共用前缀）：

```dotenv
# 国内（二选一）
REG_PREFIX=m.daocloud.io/docker.io/
REG_PREFIX=dockerpull.com/

# 海外 / 已配 Docker 镜像代理的机器：留空或不写该行（回落官方 docker.io/）
```

依赖安装层已内置国内源，无需额外配置：

- pip：清华源（可用 `PIP_INDEX_URL` 覆盖，经 build-args 注入）
- npm：npmmirror（Dockerfile 内写死，如需官方源改 `web/Dockerfile`）

## 3. 快速启动

### 3.1 一键部署脚本（推荐）

适用 Ubuntu / Debian，Docker 已就绪、代码已在服务器的场景：

```bash
sudo ./deploy/deploy.sh                 # 首次部署：自动生成 .env 随机密钥并构建启动
sudo ./deploy/deploy.sh --pull          # 升级：先 git pull --ff-only 再构建启动
sudo ./deploy/deploy.sh -p 8088         # 指定对外 HTTP 端口
```

脚本流程：环境校验 →（可选）拉代码 → 生成/校验 `.env` → 升级前备份 + 镜像快照 →
构建 → 启动 → 健康校验；**健康检查不通过时自动回滚到部署前镜像**（数据库迁移不回滚）。
首次部署会在输出中显示一次管理员初始密码。`--help` 查看全部选项。

> 脚本在 Git 索引中已标记为可执行（`100755`），`git pull` 后直接 `./deploy/deploy.sh` 即可。
> 若因 Windows 检出、zip/手工拷贝导致 `Permission denied`，脚本会自行 `chmod +x scripts/*.sh`，
> 也可手动 `chmod +x deploy/deploy.sh scripts/*.sh`，或直接 `bash deploy/deploy.sh`。

脚本不负责：安装 Docker、配置防火墙、签发证书、配置 crontab——分别见 §1、§6 与
[scripts/backup.sh](scripts/backup.sh) 头部注释。气隙环境的离线交付包见
[deploy/appliance/README.md](deploy/appliance/README.md)。

### 3.2 手动步骤

```bash
cp .env.example .env          # 然后编辑：至少填 JWT_SECRET / DATASOURCE_SECRET / ADMIN_PASSWORD
docker compose up -d --build  # 首次构建约 3-5 分钟（含前端编译与 Python 依赖）
docker compose ps             # 期望 postgres/emqx/server/nginx 全部 healthy
```

访问入口：

| 入口 | 地址 | 说明 |
|------|------|------|
| Web 控制台 | `http://localhost/` 或 `https://localhost/`（自签证书） | 唯一对外入口（80/443） |
| 官网静态站 | `https://<SITE_DOMAIN>/` | 与产品共用 80/443，按域名精确分流；配置与上线步骤见 [website/README.md](website/README.md) |
| MQTT over WS | `127.0.0.1:8083` | 仅本机回环，浏览器 mqtt 数据源直连 |
| EMQX 管理台 | `127.0.0.1:18083` | 仅本机回环 |

内部服务（postgres 5432 / emqx 1883 / server 8000）不对宿主机发布端口，仅容器网络互通；
临时调试用 `docker compose exec <service> sh` 进入，不要往 compose 加 `ports`。

## 4. 常用命令

```bash
docker compose logs -f server        # 跟踪某服务日志（server/nginx/postgres/emqx）
docker compose restart nginx         # 重启单个服务（改 deploy/nginx/nginx.conf 后即用此生效）
docker compose up -d --build server  # 改后端代码后重建单个服务
docker compose exec server sh        # 进入容器排查
docker compose down                  # 停止全部容器（数据卷保留）
docker compose exec emqx emqx ctl status   # EMQX 状态
```

两个一次性 init 服务说明：

- `tls-init`：`deploy/certs/` 缺自签证书时自动生成，正常退出后不驻留（`docker compose ps` 不显示）
- `emqx-authn-init`：向 EMQX 内置鉴权库写入 MQTT 客户端账号，日志出现 `OK` 即成功

## 5. 数据管理

持久化数据全部在 named volume（`pgdata` / `emqx_data` / `emqx_log`）：

```bash
docker volume ls | grep webscada
docker volume inspect webscada_pgdata   # 查看宿主机实际路径
```

备份与恢复（已内置脚本，凭据从容器内环境取，无需本机持有数据库口令）：

```bash
./scripts/backup.sh                     # pg_dump 整库 + 工程 JSON 可读导出 → backups/
./scripts/restore.sh backups/webscada-db-<时间戳>.dump   # 恢复
```

定时备份 crontab 示例（每日 02:30，默认保留 14 天）：

```cron
30 2 * * * cd /opt/webScada && ./scripts/backup.sh >> backups/backup.log 2>&1
```

操作手册与恢复演练要求见 [docs/operations/backup-restore.md](docs/operations/backup-restore.md)。

`docker compose down -v` 会**删除全部数据卷**，仅在确认数据已备份或可丢弃时使用。

## 6. 安全注意事项

1. **改默认口令**：`.env` 中 `POSTGRES_PASSWORD` / `EMQX_DASHBOARD_PASSWORD` /
   `EMQX_DEFAULT_PASSWORD` / `ADMIN_PASSWORD` 必须在部署前全部覆盖默认值。
2. **密钥生成**：`JWT_SECRET`、`DATASOURCE_SECRET` 按各自注释的命令生成随机值。
   `DATASOURCE_SECRET` 丢失等于已存数据源凭证不可解密，请离线妥善保管。
3. **证书**：默认自签证书仅用于验证 TLS 链路；生产环境用企业 CA / Let's Encrypt 证书
   同名替换 `deploy/certs/` 后 `docker compose restart nginx`。该目录含私钥，严禁提交 Git。
4. **生产建议**：80 端口过渡期保留，证书受信后按 `deploy/nginx/nginx.conf` 80 块头注释
   收缩为 301 跳转；对外只发布 80/443，管理面端口（8083/18083）保持回环绑定。
5. 容器加固基线：全服务 `no-new-privileges`；server 以非 root（uid 1000）+ `cap_drop ALL`
   运行；postgres/emqx 保留官方镜像所需能力集。

## 7. 仿真验证台（sim profile，可选）

演示 / 联调用的虚拟数据源，不接触真实 PLC 与产线设备。两容器均复用 server 镜像
（`pymodbus`/`aiomqtt` 已在其依赖内，不新增镜像），挂载 `scripts/sim/` 只读运行：

| 服务 | 模拟对象 | 说明 |
|------|----------|------|
| `sim-modbus` | Modbus TCP 从站 `:502` | 寄存器表固化在 `scripts/sim/modbus_slave.py` docstring（正弦计数 / float32 双字节序 23.5、88.0 / int32 -123456 / 线圈），HR 40001~40010 每秒刷新 |
| `sim-mqtt-gateway` | 3 台产线设备 MQTT 网关 | `line1/line2/line3` 每秒发布 `factory/{dev}/temp`、`factory/{dev}/run` 与 `factory/line1/press`，payload `{"v":…,"ts":…}`；主题表见 `scripts/sim/mqtt_gateway.py` docstring |
| `sim-opcua` | OPC UA 服务 `:4840` | ns=2 下 `demo.temp`（周期正弦 20~90，每秒刷新）/ `demo.press`（恒 0.75）/ `demo.state`（可写，反控演示）；变量 address 即 nodeId（如 `ns=2;s=demo.temp`），节点表见 `scripts/sim/opcua_server.py` docstring |

启动 / 停止（`profiles: ["sim"]` 隔离，默认 `docker compose up -d` 不会启动它们）：

```bash
docker compose --profile sim up -d sim-modbus sim-mqtt-gateway sim-opcua   # 或 --profile sim up -d 连基线一起起
docker compose --profile sim stop sim-modbus sim-mqtt-gateway sim-opcua
docker compose logs sim-mqtt-gateway --tail 20                   # 可见 factory/line1/temp v=… 发布行
```

与 [scripts/seed_demo.py](scripts/seed_demo.py) 的配套关系：先起仿真台，再在宿主机执行
`python scripts/seed_demo.py`（幂等）创建「仿真演示工程」——其 modbus 数据源指向
`sim-modbus:502`、mqtt 数据源订阅 `factory/#`，变量地址与寄存器表 / 主题表一一对照，
登录后打开该工程运行态即可看到读数、报警与历史曲线，全程无需真实设备。

报警演示：网关 `line1` 温度为 20~85 ℃ 正弦（周期 60s），首轮 60 秒内必然扫过 80
（约 8~22s 区间），seed 工程预设 `line1_temp > 75`（warn）报警规则，启动后约 10 秒内
报警列表即出现记录，每个正弦周期重复触发/恢复一次。


