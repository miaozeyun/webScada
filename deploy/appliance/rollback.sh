#!/usr/bin/env bash
# 一体机回滚：把 upgrade.sh 保留的上一版镜像切回 latest 并重启
set -euo pipefail
cd "$(dirname "$0")"

docker image inspect webscada-server:prev >/dev/null 2>&1 || {
  echo "[rollback] 找不到 webscada-server:prev（未执行过升级或标签已被清理）" >&2
  exit 1
}
docker image inspect webscada-nginx:prev >/dev/null 2>&1 || {
  echo "[rollback] 找不到 webscada-nginx:prev" >&2
  exit 1
}

echo "[rollback] 切换上一版镜像…"
docker tag webscada-server:prev webscada-server:latest
docker tag webscada-nginx:prev webscada-nginx:latest

# 编排/nginx 配置同样回退（新版 compose 可能引用旧镜像没有的能力）
[ -f docker-compose.yml.prev ] && mv docker-compose.yml.prev docker-compose.yml
[ -f deploy/nginx/nginx.conf.prev ] && mv deploy/nginx/nginx.conf.prev deploy/nginx/nginx.conf

echo "[rollback] 重启…"
docker compose --no-build up -d

PORT="$(docker compose port nginx 80 2>/dev/null | head -1 | sed 's/.*://')"
PORT="${PORT:-80}"
for _ in $(seq 1 24); do
  if curl -fsS "http://localhost:${PORT}/api/v1/health" >/dev/null 2>&1; then
    echo "[rollback] 完成：已回到上一版本"
    exit 0
  fi
  sleep 5
done
echo "[rollback] 回滚后仍不健康，请人工介入：docker compose logs server --tail 200" >&2
exit 1
