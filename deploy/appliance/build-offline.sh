#!/usr/bin/env bash
# 构建离线交付包（一体机/气隙工厂）：镜像 + compose + 运行期挂载文件 + 校验和
#
# 用法：./deploy/appliance/build-offline.sh [输出目录]
#   默认输出 dist/appliance-<版本>-<日期>/
# 产物：
#   images.tar              全部运行镜像（docker save）
#   docker-compose.yml      与本次构建一致的编排
#   deploy/ scripts/        运行期绑定挂载所需（nginx 配置/证书生成/sim 可选/备份脚本）
#   install.sh upgrade.sh rollback.sh webscada.service
#   SHA256SUMS              逐文件校验和
set -euo pipefail

cd "$(dirname "$0")/../.."

VERSION="${APP_VERSION:-$(date +%Y%m%d)}"
OUT="${1:-dist/appliance-$VERSION}"
mkdir -p "$OUT"

# 构建期只需要 compose 能解析：为 :? 必填变量提供一次性占位（不会进镜像，也不会进交付包，
# 包内 compose 用 --no-interpolate 保留 ${VAR} 占位，目标机用自己的 .env 展开）
export JWT_SECRET="${JWT_SECRET:-build-only-not-shipped}"
export DATASOURCE_SECRET="${DATASOURCE_SECRET:-build-only-not-shipped}"
export ADMIN_PASSWORD="${ADMIN_PASSWORD:-build-only-not-shipped}"

echo "[offline] 1/5 构建镜像（国内源由 .env 的 REG_PREFIX / PIP_INDEX_URL 控制）…"
docker compose build

echo "[offline] 2/5 导出镜像…"
# 只导出运行所需四类镜像；sim-* 是演示服务，不随交付包分发
IMAGES="$(
  docker compose config --images \
    | grep -v 'sim' \
    | sort -u
)"
# shellcheck disable=SC2086
docker save $IMAGES -o "$OUT/images.tar"

# 记录构建时的镜像前缀：images.tar 内的镜像名带此前缀，目标机 .env 必须解析出同一组名字，
# 否则 compose 会去找 docker.io/... 而本地只有镜像站前缀的名字（离线机直接 image not found）。
BUILD_REG_PREFIX="${REG_PREFIX:-$(grep -E '^REG_PREFIX=' .env 2>/dev/null | tail -1 | cut -d= -f2- || true)}"
BUILD_REG_PREFIX="${BUILD_REG_PREFIX:-docker.io/}"
printf 'REG_PREFIX=%s\n' "$BUILD_REG_PREFIX" > "$OUT/package.env"

echo "[offline] 3/5 复制编排与运行期文件…"
# --no-interpolate：保留 ${VAR} 占位，避免把构建机的密钥/端口固化进交付包；
# --no-path-resolution：保留 ./deploy/... 相对路径，否则会写成构建机绝对路径，目标机挂载源不存在。
# 目标机启动时由它自己的 .env 展开、按包根目录解析相对路径。
docker compose config --no-interpolate --no-path-resolution > "$OUT/docker-compose.yml"
cp -r deploy "$OUT/deploy"
# 证书私钥绝不进交付包：目标机首次启动由 tls-init 自签，生产自行替换
rm -rf "$OUT/deploy/certs"
mkdir -p "$OUT/deploy/certs"
cp -r scripts "$OUT/scripts"
cp .env.example "$OUT/.env.example"
cp deploy/appliance/install.sh deploy/appliance/upgrade.sh deploy/appliance/rollback.sh "$OUT/"
cp deploy/appliance/webscada.service "$OUT/"
chmod +x "$OUT"/*.sh "$OUT"/scripts/*.sh

echo "[offline] 4/5 生成校验和…"
(
  cd "$OUT"
  find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS
)

echo "[offline] 5/5 打包…"
tar czf "$OUT.tar.gz" -C "$(dirname "$OUT")" "$(basename "$OUT")"
sha256sum "$OUT.tar.gz" > "$OUT.tar.gz.sha256"

du -h "$OUT.tar.gz"
echo "[offline] 完成：$OUT.tar.gz（拷贝到 U 盘，气隙机上解压后执行 ./install.sh）"
