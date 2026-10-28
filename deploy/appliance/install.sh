#!/usr/bin/env bash
# 一体机首次安装（离线）：载入镜像 → 生成 .env → 启动 → 健康校验
#
# 前置：目标机已装 Docker Engine ≥25 + compose v2；本目录含 images.tar
# 用法：./install.sh [HTTP端口，默认 80]
set -euo pipefail
cd "$(dirname "$0")"

PORT="${1:-80}"
[ -f images.tar ] || { echo "[install] 缺少 images.tar（请先运行 build-offline.sh）" >&2; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "[install] 需要 docker compose v2" >&2; exit 1; }

echo "[install] 1/4 载入镜像…"
docker load -i images.tar

if [ ! -f .env ]; then
  echo "[install] 2/4 未找到 .env，生成随机密钥…"
  JWT_SECRET="$(openssl rand -hex 32)"
  DATASOURCE_SECRET="$(openssl rand -base64 32 | tr '+/' '-_' | tr -d '\n')"
  ADMIN_PASSWORD="$(openssl rand -base64 12 | tr -d '\n')"
  POSTGRES_PASSWORD="$(openssl rand -hex 16)"
  cat > .env <<EOF
# 由 install.sh 生成（日期 $(date +%F)）。JWT_SECRET / DATASOURCE_SECRET 丢失后果见 README。
HTTP_PORT=$PORT
HTTPS_PORT=443
POSTGRES_USER=webscada
POSTGRES_PASSWORD=$POSTGRES_PASSWORD
POSTGRES_DB=webscada
JWT_SECRET=$JWT_SECRET
DATASOURCE_SECRET=$DATASOURCE_SECRET
ADMIN_USER=admin
ADMIN_PASSWORD=$ADMIN_PASSWORD
EMQX_DASHBOARD_USER=admin
EMQX_DASHBOARD_PASSWORD=$(openssl rand -hex 12)
EMQX_DEFAULT_USERNAME=webscada_mqtt
EMQX_DEFAULT_PASSWORD=$(openssl rand -hex 12)
EOF
  chmod 600 .env
  echo "[install] 管理员初始密码：$ADMIN_PASSWORD（请登录后立即修改；本行只显示这一次）"
else
  echo "[install] 2/4 使用已有 .env（HTTP_PORT=$(grep -E '^HTTP_PORT=' .env | cut -d= -f2 || echo 80)）"
fi

# 镜像前缀必须与 images.tar 内镜像名一致（离线机无法回源重拉）
if [ -f package.env ]; then
  PKG_PREFIX="$(grep -E '^REG_PREFIX=' package.env | cut -d= -f2- || true)"
  if [ -n "$PKG_PREFIX" ]; then
    if grep -qE '^REG_PREFIX=' .env; then
      sed -i "s|^REG_PREFIX=.*|REG_PREFIX=${PKG_PREFIX}|" .env
    else
      echo "REG_PREFIX=${PKG_PREFIX}" >> .env
    fi
  fi
fi

# 证书目录由 tls-init 首次启动自动生成；若目录为空则确保可写
mkdir -p deploy/certs

echo "[install] 3/4 启动服务…"
docker compose --no-build up -d

echo "[install] 4/4 健康校验（最长 3 分钟）…"
PORT_ACTUAL="$(docker compose port nginx 80 2>/dev/null | head -1 | sed 's/.*://')"
PORT_ACTUAL="${PORT_ACTUAL:-$PORT}"
for _ in $(seq 1 36); do
  if curl -fsS "http://localhost:${PORT_ACTUAL}/api/v1/health" >/dev/null 2>&1; then
    echo "[install] 完成：http://localhost:${PORT_ACTUAL}（浏览器打开后用 admin 登录）"
    echo "[install] 开机自启：将 webscada.service 复制到 /etc/systemd/system/ 后 systemctl enable --now webscada"
    exit 0
  fi
  sleep 5
done
echo "[install] 健康检查未通过：docker compose logs server --tail 100" >&2
exit 1
