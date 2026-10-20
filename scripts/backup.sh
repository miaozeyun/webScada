#!/usr/bin/env bash
# webScada 数据库定时备份（商用 P0：备份恢复，评审 blocker：部署运维无备份）
#
# 备份内容：
#   1. 整库逻辑备份（pg_dump custom 格式）：users / projects(doc JSONB+revision) /
#      share_links / alarm_records / alembic_version，审计表等新表上线后自动包含
#   2. 工程 JSON 可读导出（projects.doc 逐行 JSONL）：灾难场景即使没有 dump，
#      也可在干净环境重建库后通过编辑器「导入」逐工程恢复
#
# 定时（crontab 示例，每日 02:30，注意保留本脚本可执行位）：
#   30 2 * * * cd /opt/webScada && ./scripts/backup.sh >> backups/backup.log 2>&1
#
# 操作手册 / 恢复步骤 / 演练要求：docs/operations/backup-restore.md
# 恢复命令：./scripts/restore.sh <dump 文件>
set -euo pipefail

cd "$(dirname "$0")/.."

KEEP_DAYS="${BACKUP_KEEP_DAYS:-14}"
TS="$(date +%Y%m%d-%H%M%S)"
OUT=backups
mkdir -p "$OUT"

docker compose ps -q postgres 2>/dev/null | grep -q . \
  || { echo "[backup] postgres 容器未运行；先执行 docker compose up -d postgres" >&2; exit 1; }

# 1) 整库备份（凭据取自容器内环境，无需在本机持有数据库口令）
docker compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' \
  > "$OUT/webscada-db-$TS.dump"

# 2) 工程 JSON 导出（JSONL：一行一个 ProjectDoc；doc 为 JSONB 原文）
docker compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT doc::text FROM projects ORDER BY id"' \
  > "$OUT/webscada-docs-$TS.json"

# 3) 过期清理（默认保留 14 天，可用环境变量 BACKUP_KEEP_DAYS 覆盖）
find "$OUT" -name 'webscada-db-*.dump' -mtime "+$KEEP_DAYS" -delete
find "$OUT" -name 'webscada-docs-*.json' -mtime "+$KEEP_DAYS" -delete

echo "[backup] 完成（保留 $KEEP_DAYS 天）："
ls -lh "$OUT/webscada-db-$TS.dump" "$OUT/webscada-docs-$TS.json"
echo "[backup] 建议：将 $OUT 同步至异机/对象存储（rclone / scp 均可），本机备份不构成灾备"
