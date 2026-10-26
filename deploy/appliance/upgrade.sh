#!/usr/bin/env bash
# 一体机升级：保留上一版镜像 → 载入新版 → 更新编排 → 启动 → 健康校验（失败自动回滚）
#
# 用法：./upgrade.sh ../appliance-20261025
# 前置：建议先执行 ./scripts/backup.sh（数据库/附件/EMQX 数据）
set -euo pipefail
cd "$(dirname "$0")"

NEW="${1:?用法: ./upgrade.sh <新版本包目录>}"
[ -f "$NEW/images.tar" ] || { echo "[upgrade] 新包缺少 images.tar" >&2; exit 1; }
[ -f .env ] || { echo "[upgrade] 当前目录无 .env，先完成首次安装" >&2; exit 1; }

echo "[upgrade] 1/5 备份当前镜像标签…"
docker tag webscada-server:latest webscada-server:prev 2>/dev/null || true
docker tag webscada-nginx:latest webscada-nginx:prev 2>/dev/null || true

echo "[upgrade] 2/5 载入新镜像…"
docker load -i "$NEW/images.tar"

echo "[upgrade] 3/5 更新编排与 nginx 配置（不动 .env / 证书 / 数据卷）…"
cp docker-compose.yml docker-compose.yml.prev
cp deploy/nginx/nginx.conf deploy/nginx/nginx.conf.prev
cp "$NEW/docker-compose.yml" docker-compose.yml
if [ -f "$NEW/deploy/nginx/nginx.conf" ]; then
  cp "$NEW/deploy/nginx/nginx.conf" deploy/nginx/nginx.conf
fi
# 新包的镜像前缀可能与旧包不同：同步到 .env，否则 compose 解析出的镜像名对不上
if [ -f "$NEW/package.env" ]; then
  PKG_PREFIX="$(grep -E '^REG_PREFIX=' "$NEW/package.env" | cut -d= -f2- || true)"
  if [ -n "$PKG_PREFIX" ]; then
    if grep -qE '^REG_PREFIX=' .env; then
      sed -i "s|^REG_PREFIX=.*|REG_PREFIX=${PKG_PREFIX}|" .env
    else
      echo "REG_PREFIX=${PKG_PREFIX}" >> .env
    fi
  fi
fi

echo "[upgrade] 4/5 启动…"
if ! docker compose --no-build up -d; then
  echo "[upgrade] 启动失败（新编排/镜像不兼容？），自动回滚…" >&2
  exec ./rollback.sh
fi

echo "[upgrade] 5/5 健康校验…"
PORT="$(docker compose port nginx 80 2>/dev/null | head -1 | sed 's/.*://')"
PORT="${PORT:-80}"
for _ in $(seq 1 24); do
  if curl -fsS "http://localhost:${PORT}/api/v1/health" >/dev/null 2>&1; then
    echo "[upgrade] 完成：$(curl -fsS "http://localhost:${PORT}/api/v1/health")"
    exit 0
  fi
  sleep 5
done

echo "[upgrade] 新版本健康检查失败，自动回滚…" >&2
exec ./rollback.sh
