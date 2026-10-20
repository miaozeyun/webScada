#!/usr/bin/env bash
# webScada 恢复脚本：将 backup.sh 产生的整库 dump 回滚进 postgres 并做健康校验
#
# 用法：./scripts/restore.sh backups/webscada-db-YYYYMMDD-HHMMSS.dump
# 注意：恢复会【清空当前库】；仅恢复工程 JSON（webscada-docs-*.json）见
#       docs/operations/backup-restore.md §仅恢复工程 JSON。
# 演练：建议每月按操作手册执行一次恢复演练（备份不可恢复 = 没有备份）。
set -euo pipefail

cd "$(dirname "$0")/.."

DUMP="${1:?用法: ./scripts/restore.sh <webscada-db-*.dump>}"
[ -f "$DUMP" ] || { echo "[restore] 备份文件不存在: $DUMP" >&2; exit 1; }

docker compose ps -q postgres 2>/dev/null | grep -q . \
  || { echo "[restore] postgres 容器未运行；先执行 docker compose up -d postgres" >&2; exit 1; }

echo "!! 恢复将停止 server/nginx 并【清空当前数据库】，整库回滚到：$DUMP"
read -r -p "确认请输入数据库名（.env 的 POSTGRES_DB，默认 webscada）： " CONFIRM
[ "$CONFIRM" = "webscada" ] || { echo "[restore] 已取消（输入与库名不一致）" >&2; exit 1; }

echo "[restore] 1/5 停止写入端（server / nginx）…"
docker compose stop server nginx

echo "[restore] 2/5 重建数据库…"
docker compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d postgres -c "DROP DATABASE IF EXISTS \"$POSTGRES_DB\"" -c "CREATE DATABASE \"$POSTGRES_DB\""'

echo "[restore] 3/5 pg_restore 导入（dump 先复制入容器：管道 /dev/stdin 不可 seek，pg_restore 自定义格式要求可寻址文件）…"
CID="$(docker compose ps -q postgres)"
docker cp "$DUMP" "$CID:/tmp/webscada-restore.dump"
docker compose exec -T postgres sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --exit-on-error /tmp/webscada-restore.dump && rm -f /tmp/webscada-restore.dump'

echo "[restore] 4/5 重启应用并等待健康检查…"
docker compose up -d server nginx
HEALTH_OK=0
for _ in $(seq 1 12); do
  if curl -fsS "http://localhost:${HTTP_PORT:-80}/api/v1/health" >/dev/null 2>&1; then HEALTH_OK=1; break; fi
  sleep 5
done
if [ "$HEALTH_OK" -ne 1 ]; then
  echo "[restore] 健康检查未通过，请排查：docker compose logs server --tail 100" >&2
  exit 1
fi

echo "[restore] 5/5 行数校验（对照备份前的业务量级）："
docker compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT '\''users='\''||count(*) FROM users UNION ALL SELECT '\''projects='\''||count(*) FROM projects UNION ALL SELECT '\''share_links='\''||count(*) FROM share_links UNION ALL SELECT '\''alarm_records='\''||count(*) FROM alarm_records"'

echo "[restore] 完成。请登录页面抽查：工程可打开、分享页正常、报警页有数据。"
echo "[restore] 演练归档要求见 docs/operations/backup-restore.md §恢复演练。"
