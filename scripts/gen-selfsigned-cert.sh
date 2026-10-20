#!/usr/bin/env bash
# webScada 自签 TLS 证书生成 → deploy/certs/selfsigned.{crt,key}
#
# 用途：HTTPS(443) 本地/内网加密（nginx 443 server 块挂载 /etc/nginx/certs）。
# 说明：
# - docker compose 首次 up 时，tls-init 一次性服务会在证书缺失时自动生成同等证书；
#   本脚本用于手工生成或过期重签（先删旧文件再运行）。
# - 自签证书浏览器会提示「不受信任」，属预期；生产环境请替换为企业 CA / Let's Encrypt
#   证书（同名替换 selfsigned.crt / selfsigned.key 后重启 nginx）。
# - deploy/certs/ 含私钥，严禁提交 Git（建议在 .gitignore 增补 deploy/certs/）。
#
# 用法：./scripts/gen-selfsigned-cert.sh [有效天数，默认 825]
set -euo pipefail

# Windows（Git Bash/MSYS）：禁止把 -subj 的 /CN=... 当作路径转换成 D:/Program Files/...
export MSYS_NO_PATHCONV=1
export MSYS2_ARG_CONV_EXCL="*"

cd "$(dirname "$0")/.."

DIR=deploy/certs
CRT="$DIR/selfsigned.crt"
KEY="$DIR/selfsigned.key"
DAYS="${1:-825}"

if [ -f "$CRT" ] || [ -f "$KEY" ]; then
  echo "已存在 $CRT / $KEY。防误覆盖：请先手动删除旧证书后再重新生成。" >&2
  exit 1
fi

if ! command -v openssl >/dev/null 2>&1; then
  echo "本机未找到 openssl。可跳过本脚本直接 \`docker compose up -d --build\`：tls-init 服务会自动生成自签证书。" >&2
  exit 1
fi

mkdir -p "$DIR"
openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:P-256 -sha256 -nodes \
  -keyout "$KEY" -out "$CRT" -days "$DAYS" \
  -subj "/CN=webscada.local/O=webScada" \
  -addext "subjectAltName=DNS:localhost,DNS:webscada.local,IP:127.0.0.1"

chmod 600 "$KEY" 2>/dev/null || true   # Windows/NTFS 挂载可能不支持 chmod，忽略失败

echo "[gen-cert] 自签证书已生成（$DAYS 天；SAN: localhost / webscada.local / 127.0.0.1）"
echo "           $CRT"
echo "           $KEY"
echo "[gen-cert] 生效：docker compose restart nginx（或直接 docker compose up -d）"
