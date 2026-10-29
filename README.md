# webScada

一句话：**在浏览器里画一块监控大屏，接上现场的设备和数据，就能实时看。**

不用装客户端，不用学脚本，拖几个组件、连上数据源、点发布，就是一块能 7×24 挂着看的组态画面。
适合中小工厂、单设备/单产线的监控场景，介于「数据大屏」和「重型 SCADA」之间。

- 🌐 官网 / 在线演示：**<http://103.236.97.137:64304>**
- 🐞 问题反馈：[Gitee Issues](https://gitee.com/miao_zeyun/web-scada/issues)
- 📄 开源协议：[AGPL-3.0](LICENSE)（免费自用，商业版功能见 [NOTICE.md](NOTICE.md)）

> **当前状态：内部试点版（`internal-pilot`），暂时不对外售卖。**
> 可以拿来研究、试用、跑非关键产线，但请**有人盯着屏幕**用，别当安全联锁使。
> 正式的商用能力还在做，进度见文末「我们接下来做什么」。

---

## 它能干什么

| 你想做的事 | 现在能不能 |
|---|---|
| 拖拽画画面（对齐吸附、撤销、复制粘贴、旋转缩放） | ✅ 能 |
| 41 种现成组件 + 75 个工业图元（泵、阀、罐、管道…），也能存成自己的图元 | ✅ 能 |
| 建工程、存工程、导入导出（导出时自动抹掉密码） | ✅ 能 |
| 一个工程做多个画面，编辑和运行分开，一键生成只读分享链接 | ✅ 能 |
| 点按钮反控设备（开关、档位、输入数值） | ✅ 能（分享页永远只读） |
| 接数据：MQTT、HTTP 轮询、WebSocket、Modbus TCP、OPC UA、模拟数据 | ✅ 能 |
| 报警：超阈值/回升/持续多久才报，自动记下来，能发 Webhook 和邮件 | ✅ 能（服务端 7×24 判定） |
| 设备掉线自动报警，恢复自动清除 | ✅ 能 |
| 历史趋势图（服务端每 5 秒存一次，保留 30 天，可按时间段查询） | ✅ 能 |
| 用户和权限（管理员 / 操作员 / 只读），八类操作留痕审计 | ✅ 能 |
| 复制一整个工程当模板（一台设备一套画面，批量交给不同客户） | ✅ 能 |
| 点位（变量）表格导入导出 CSV | ✅ 能 |
| 离线一体机安装包（U 盘拷到没网的机器上装） | ⚠️ 脚本写好了，还没在真实离线硬件上长期跑过 |
| 视频接入、主备双机、白标换 logo、License 授权 | 🗺 在商业版计划里 |

---

## 它是怎么搭的

```
浏览器（编辑器 / 运行大屏）
        │  HTTP / WebSocket
        ▼
    nginx 容器  ────►  后端容器（FastAPI，一个进程扛全部）
                         │  采集设备数据、判断报警、存历史
                         ▼
                    PostgreSQL 数据库
                         ▲
                         │
    设备 / 网关 / 上游接口（MQTT、HTTP、Modbus TCP、OPC UA…）
```

技术栈：前端 Vue3 + TypeScript + Vite + Element Plus + ECharts；后端 FastAPI + PostgreSQL；消息用 EMQX；部署用 docker compose。

---

## 三步跑起来（Docker）

需要装好 Docker Desktop（Windows ≥ 4.30）或 Docker Engine 25+，完整部署手册见 [README.Docker.md](README.Docker.md)。

```bash
# 1. 复制配置，填三个必填密钥
cp .env.example .env
python -c "import secrets;print('JWT_SECRET='+secrets.token_hex(32))"
python -c "from cryptography.fernet import Fernet;print('DATASOURCE_SECRET='+Fernet.generate_key().decode())"
#    把上面两条命令的输出，连同 ADMIN_PASSWORD，一起填进 .env

# 2. 构建并启动（第一次会拉镜像、编译，需要几分钟）
docker compose up -d --build

# 3. 打开浏览器
#    https://localhost  →  用 .env 里的 ADMIN_USER / ADMIN_PASSWORD 登录
#    （自签证书会提示「不安全」，点继续即可，属正常）
```

启动完可以确认一下：`docker compose ps` 四个容器都是 healthy，
`curl -k https://localhost/api/v1/health` 返回 `{"status":"ok"}`。

### MQTT 怎么配

EMQX 默认**不允许匿名连接**，启动时会自动建一个账号：

- 账号密码：`webscada_mqtt` / `webscada_mqtt123`（**上线前务必在 `.env` 里改掉**）
- 在工程的数据源面板里填这个账号即可，后台会加密保存，任何地方都不会显示明文
- EMQX 管理台 `http://localhost:18083`（默认 `admin` / `public`，只能本机访问，**第一次登录必须改密码**）

### HTTPS 证书

已经自带 443 端口和自签证书，能用但浏览器会警告。
正式环境请换成自己的证书：替换 `deploy/certs/selfsigned.crt` 和 `.key`（文件名不变），然后 `docker compose restart nginx`。

---

## 默认账号

| 是什么 | 默认账号密码 | 注意 |
|---|---|---|
| webScada 管理员 | `admin` / 你在 `.env` 里设的 `ADMIN_PASSWORD`（必填） | 第一次登录请立刻改密码 |
| EMQX 管理台 | `admin` / `public` | 只能本机访问，第一次登录请改密码 |
| MQTT 客户端 | `webscada_mqtt` / `webscada_mqtt123` | 正式环境请改掉 |

⚠️ 两个密钥务必保管好：`JWT_SECRET` 泄露等于谁都能冒充登录；`DATASOURCE_SECRET` 丢了，
**存过的设备密码就再也解不开了**，只能逐个重填。`deploy/certs/` 和 `.env` 都不要提交到 Git。

---

## 常改的配置项

`ADMIN_PASSWORD`、`JWT_SECRET`、`DATASOURCE_SECRET` 三个必填，其余一般不用动。
全部配置项和默认值看 [.env.example](.env.example)，下面是最常改的几个：

| 变量 | 默认值 | 干什么的 |
|---|---|---|
| `HTTP_PORT` / `HTTPS_PORT` | 80 / 443 | 对外端口（被占用就改这里） |
| `JWT_EXPIRE_HOURS` | 2 | 登录多久失效（大屏用分享链接不受限） |
| `ALARM_RETENTION_DAYS` | 30 | 报警记录保留几天 |
| `BACKUP_KEEP_DAYS` | 14 | 备份保留几天 |
| `LOGIN_LOCKOUT_ATTEMPTS` | 5 | 登录失败几次锁账号 |

---

## 备份

```bash
./scripts/backup.sh                                # 备份数据库 + 导出工程，自动保留最近 14 天
./scripts/restore.sh backups/webscada-db-*.dump    # 恢复（会二次确认 + 恢复后自检）
```

**强烈建议每月做一次真实恢复演练**，不然备份到真要用的时候才发现是坏的。
详细做法见 [docs/operations/backup-restore.md](docs/operations/backup-restore.md)。

---

## 现在还不能做的事（先说清楚）

1. **西门子 S7、三菱 MC、欧姆龙 FINS 这类 PLC 原生协议还没做**。目前能接的是 MQTT、HTTP、WebSocket、Modbus TCP、OPC UA。
2. **只能单机部署**。登录状态、连接数统计都存在后端进程内存里，开多个 worker 或做集群会不准。另外**后端重启会让所有人掉线重登**。
3. **报警通知要自己配**。不配 Webhook / 邮件的话，报警只在页面里提示。配错了会进补发队列（最多重试 8 次、约 4 小时）。
4. **MQTT 数据源要用新账号**。老工程如果填的是以前没密码的连接，需要改成上面那个 MQTT 账号才能采集。
5. **历史数据表没做分区**，百万级以内没问题，再大建议加分区。
6. **反控只能写显式标了「可写」的变量**，分享页永远只读，不做联锁逻辑（这是产品边界，不是 bug）。
7. **数据格式只支持 UTF-8 JSON**；MQTT 用 QoS0，断网期间的包不补。
8. **性能基线**：2 核 4G 的单机，大约跑 50 个连接、5000 个变量、单页 200 个组件。
9. **浏览器要 Chrome / Edge 90 以上**。
10. **变量改名或删掉后**，已经发出去的分享大屏对应位置会停住不动，重新发布一次就恢复——这是正常行为。

---

## 我们接下来做什么

| 阶段 | 状态 | 做什么 |
|---|---|---|
| 打地基 | ✅ 已完成 | 开源协议、安全加固（TLS、MQTT 鉴权）、备份恢复、自动化测试 |
| 服务端闭环 | ✅ 已完成 | 后台 7×24 采集、报警判定、历史存储、实时推送、权限和审计 |
| 产品化打磨 | 🚧 进行中 | 报警展示优化、性能压测、组件细节打磨 |
| 正式商用 | ⬜ 未开始 | 授权激活、培训认证、多语言、白标定制 |

---

## 联系我们

- **社区交流 / 提 Bug**：[Gitee Issues](https://gitee.com/miao_zeyun/web-scada/issues)，免费，有时间就看
- **官网**：<http://103.236.97.137:64304>
- **商业授权 / 定制开发**：`18835132457@163.com`，微信 `miaozeyun2020`
- **发现安全漏洞**：请不要发公开 Issue，直接发邮件到 `18835132457@163.com`，标题加 `[security]`

**免责声明**：本软件按 AGPL-3.0「现状」提供，不是安全部件，**不得用于 SIL、安全联锁等安全关键场景**。
上线前请自行评估你所在环境的安全风险。

---

## 想一起写代码

- 开发环境怎么搭、代码约定是什么：看 [CONTRIBUTING.md](CONTRIBUTING.md)
- 第一次提 PR 需要先签 [CLA.md](CLA.md)
- 名字和 Logo 能不能用：看 [TRADEMARK.md](TRADEMARK.md)

本地开发（不想用 Docker 时）：

```bash
# 后端（测试用内存数据库，不依赖 PostgreSQL）
cd server
python -m venv .venv && .venv/Scripts/pip install -e ".[dev]"
.venv/Scripts/pytest

# 前端
cd web
npm install
npm run dev      # 打开 http://localhost:5199
```

---

## 开源协议

核心代码用 [AGPL-3.0](LICENSE)：自己用、改、二次开发都行；但如果把它放在网上给别人用，需要公开你改过的源码。

商业版功能（视频接入、主备冗余、白标、SLA 等）单独授权，边界见 [NOTICE.md](NOTICE.md)。
第三方组件清单见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

代码的授权不包含商标，Logo 和名字的使用规则见 [TRADEMARK.md](TRADEMARK.md)。
