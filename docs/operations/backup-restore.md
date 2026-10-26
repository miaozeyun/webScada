# 备份与恢复操作手册（webScada）

> 对应脚本：`scripts/backup.sh`（备份）、`scripts/restore.sh`（恢复）。
> 背景：商用就绪度评审（2026-10-20）将「无备份恢复」列为部署运维维度的关键短板，
> 本手册与其脚本是止血项；异地容灾、主备冗余属企业版规划，见 README 路线图。

## 1. 备份什么

| 数据 | 位置 | 覆盖情况 |
|---|---|---|
| 用户（users） | PostgreSQL `users` 表 | 整库 dump ✅ |
| 工程（含画面 JSON、数据源、变量、报警规则） | `projects.doc`（JSONB）+ `revision` | 整库 dump ✅ + JSONL 可读导出 ✅ |
| 分享快照 | `share_links.doc_snapshot` | 整库 dump ✅ |
| 报警记录 | `alarm_records` | 整库 dump ✅ |
| 操作审计 | 审计表（服务端闭环阶段 1 交付） | 上线后自动包含在整库 dump 中 |
| 图片/附件 | `uploads_data` 命名卷 | `webscada-uploads-*.tar.gz` ✅ |
| EMQX 内置账号/会话 | `emqx_data` 命名卷 | `webscada-emqx-*.tar.gz` ✅ |
| 浏览器本地历史桶（localStorage） | 各操作者浏览器 | ❌ 不在服务端备份范围（运行态引擎迁移服务端后此问题消亡） |
| `.env` / TLS 证书 | 宿主机文件 | 手工纳入你的机密备份流程（勿入库） |

## 2. 备份

### 2.1 手动执行

```bash
cd /opt/webScada          # 仓库根目录
./scripts/backup.sh
# 产物：
#   backups/webscada-db-YYYYMMDD-HHMMSS.dump      （pg_dump custom 格式，整库）
#   backups/webscada-docs-YYYYMMDD-HHMMSS.json    （工程 JSONL，一行一个 ProjectDoc）
#   backups/webscada-uploads-YYYYMMDD-HHMMSS.tar.gz（图片资产，失败仅告警）
#   backups/webscada-emqx-YYYYMMDD-HHMMSS.tar.gz   （EMQX 账号/会话，失败仅告警）
```

`restore.sh` 会按 dump 文件名推导同一时间戳的 uploads/emqx 归档并一并还原（旧备份没有这两项时跳过）。

保留策略：默认 14 天，环境变量 `BACKUP_KEEP_DAYS` 覆盖。

### 2.2 定时执行（crontab）

```cron
# 每日 02:30 备份并记录日志
30 2 * * * cd /opt/webScada && ./scripts/backup.sh >> backups/backup.log 2>&1
```

### 2.3 异机留存（必须）

本机备份不构成灾备。至少一地在 cron 之后追加同步，例如：

```cron
45 2 * * * rclone sync /opt/webScada/backups remote:webscada-backups
```

或 `scp` 到备用机。原则：**备份与生产不同机、不同电、不同城更佳**。

## 3. 恢复

### 3.1 整库恢复

```bash
./scripts/restore.sh backups/webscada-db-YYYYMMDD-HHMMSS.dump
```

脚本行为：停止 server/nginx → 重建数据库 → `pg_restore` → 重启 → 健康检查 + 四表行数校验。
执行前需交互输入库名确认（默认 `webscada`）。

### 3.2 仅恢复工程 JSON（无 dump 的兜底路径）

前提：一个可用的空库环境（`docker compose up -d postgres` 后由 server 容器自动迁移建表）。

1. `docker compose up -d --build`（server 完成迁移并创建 admin）；
2. 对 JSONL 文件逐行恢复——每行是一个 ProjectDoc，通过编辑器「导入工程」上传即可；
   或批量写入：

```bash
# 高级路径：直接写库（须保持 revision/project.id 一致；谨慎操作）
docker compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"' <<'SQL'
-- 单工程示例（<doc> 为 JSONL 中的一行，注意先在页面建同名工程对齐 project.id，或直接 INSERT）
SQL
```

推荐逐工程走「编辑器导入」：会完整触发契约校验，比裸 INSERT 更安全。
注意：数据源凭证在 doc 中是脱敏密文，导入后需在各数据源面板重新填写。

## 4. 恢复演练（每月一次，硬要求）

备份不可恢复等于没有备份。演练步骤：

1. **准备**：在测试机/同机空闲端口 clone 一份部署（或直接用当前环境，接受短暂停机）。
2. **执行**：取最近一份 dump 走 §3.1 完整恢复。
3. **校验清单**：
   - [ ] `curl http://localhost/api/v1/health` 返回 ok；
   - [ ] 脚本输出行数与备份前业务量级一致（users/projects/share_links/alarm_records）；
   - [ ] admin 可登录（`.env` 的 ADMIN_PASSWORD）；
   - [ ] 任选 1 个工程能打开编辑，绑定组件有数值；
   - [ ] 分享链接页面可访问（快照来自 share_links）；
   - [ ] 报警页有历史记录。
4. **归档**：记录演练日期、dump 文件名、结果到 `docs/operations/drill-log.md`（自建），
   未按期演练按运维事故处理。

## 5. 已知边界

- `alarm_records` 行数上限 `ALARM_MAX_ROWS_PER_PROJECT`（默认 20 万行）决定单库体积上限，
  dump 体积随之上限可控；如报警量大建议下调保留天数 `ALARM_RETENTION_DAYS`。
- historian（历史时序入库）尚未交付；浏览器 localStorage 历史不在备份范围（见 §1）。
- 恢复期间服务不可写（server 已停止），窗口通常 < 1 分钟（视库体积）。
