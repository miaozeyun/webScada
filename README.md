# webScada

Web 原生、轻量、低代码拖拽组态的实时监控大屏（只读监控）。开源核心 + 企业版。设计文档见 [docs/design/](docs/design/00-总览.md)。

## 架构一览

Vue3 + TS 前端（编辑器/运行态双模式）· FastAPI + PostgreSQL 后端（单进程全异步）· EMQX（MQTT 接入）· Nginx（静态托管 + 反代）。`docker compose` 四容器一键部署，面向中小工厂单机场景。

## 快速部署（Docker）

要求：Docker Desktop ≥ 4.30（Windows）或 Docker Engine ≥ 25 + Compose v2（Linux）。

```bash
# 1. 准备环境变量
cp .env.example .env
#    必填三项：JWT_SECRET / DATASOURCE_SECRET / ADMIN_PASSWORD
python -c "import secrets;print('JWT_SECRET='+secrets.token_hex(32))"
python -c "from cryptography.fernet import Fernet;print('DATASOURCE_SECRET='+Fernet.generate_key().decode())"

# 2. 构建并启动（首次会拉取/构建镜像，视网络数分钟）
docker compose up -d --build

# 3. 验证四容器 healthy
docker compose ps
curl http://localhost/api/v1/health        # {"status":"ok",...}

# 4. 浏览器访问
# http://localhost  → 用 .env 中 ADMIN_USER/ADMIN_PASSWORD 登录
```

停服：`docker compose down`（保留数据）；清空数据：`docker compose down -v`。

## 本地开发

```bash
# 后端（调试模式，需本地可达的 PostgreSQL，或直接复用容器内 postgres）
cd server
python -m venv .venv && .venv/Scripts/pip install -e ".[dev]"    # Windows
.venv/Scripts/pytest                                              # 测试（默认 SQLite 内存库，无需 PG）

# 前端（vite dev server，/api 代理到 localhost:8000）
cd web
npm install
npm run dev      # http://localhost:5173
```

## 环境变量说明

| 变量 | 默认 | 说明 |
|---|---|---|
| `POSTGRES_USER/PASSWORD/DB` | webscada / webscada123 / webscada | PostgreSQL 初始凭据（仅首次建库生效） |
| `JWT_SECRET` | **必填** | JWT HS256 签名密钥 |
| `JWT_EXPIRE_HOURS` | 2 | JWT 有效期；7x24 大屏走分享链接不受此限 |
| `DATASOURCE_SECRET` | **必填** | 数据源凭证 Fernet 加密密钥；**丢失后已存凭证不可解，需在各数据源面板重填** |
| `ADMIN_USER / ADMIN_PASSWORD` | admin / **必填** | 初始化管理员（仅用户不存在时创建，不覆盖后续改密） |
| `HTTP_PORT` | 80 | Nginx 对外端口 |
| `ALARM_RETENTION_DAYS` | 30 | 报警记录保留天数（清理任务 M5 生效） |
| `ALARM_MAX_ROWS_PER_PROJECT` | 200000 | 单工程报警记录行数上限（M5 生效） |
| `SHARE_MAX_WS_PER_TOKEN` | 20 | 同一分享 token 并发运行态 WS 上限（M4/M6 生效） |
| `JWT_WS_MAX_PER_USER_PROJECT` | 10 | 同用户同工程 JWT 运行态 WS 上限（M4/M6 生效） |
| `RATE_LIMIT_CONNECT_PER_MIN` | 30 | 建连频率上限 次/分（M4/M6 生效） |
| `WS_MAX_CONNECTIONS` | 50 | 全实例 WS 连接上限（M4/M6 生效） |

**TLS 说明**：本编排仅发布 HTTP。生产环境请在外层企业级反代/网关终止 TLS 后转发至 `${HTTP_PORT}`（或在 deploy/nginx 增加 443 配置挂载证书）；WebSocket 的 token 走查询串，其安全性依赖 HTTPS（内网豁免场景请自行评估）。

## 里程碑

- **M0（当前）**：部署底座 + 登录鉴权 + 工程 CRUD / 导入导出（凭证脱敏）+ doc 契约校验
- M1 画布编辑器核心 → M2 组件库 → M3 变量与数据接入 → M4 绑定与运行态 → M5 告警 → M6 发布分享

阶段定义与验收标准见 [docs/design/04-分阶段任务拆解.md](docs/design/04-分阶段任务拆解.md)。

## 运行口径（重要）

- 只读监控：系统不存在任何向设备的写通道
- 数据源载荷仅支持 UTF-8 JSON；CSV/二进制不支持
- MQTT 默认 QoS0 + clean session，断线期间数据不补传
- 变量删除/改名后，已分享大屏对应组件显示停滞，刷新分享快照（重新发布）即恢复
- 浏览器基线 Chrome/Edge ≥ 90
