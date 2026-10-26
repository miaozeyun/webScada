#!/usr/bin/env bash
# 官网域名 / ICP 备案号批量替换（website/ 下的占位内容）
#
# 用法:
#   ./scripts/set-site-domain.sh www.example.com
#   ./scripts/set-site-domain.sh www.example.com "京ICP备12345678号-1"
#
# 替换范围：website/*.html、*.txt、*.xml 中的
#   webscada.example.com      → 正式域名（canonical / og:url / sitemap / robots / llms.txt / JSON-LD）
#   X ICP 备 00000000 号      → 真实备案号（给了第二个参数才替换）
#
# 替换后还需：证书放 deploy/certs/ → .env 设 SITE_DOMAIN/SITE_CERT/SITE_KEY →
#             docker compose up -d nginx（详见 website/README.md）
set -Eeuo pipefail

DOMAIN="${1:-}"
ICP="${2:-}"

if [ -z "$DOMAIN" ]; then
  cat >&2 <<'EOF'
用法: ./scripts/set-site-domain.sh <域名> [ICP备案号]

例:
  ./scripts/set-site-domain.sh www.example.com
  ./scripts/set-site-domain.sh www.example.com "京ICP备12345678号-1"
EOF
  exit 1
fi

[[ "$DOMAIN" =~ ^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$ ]] \
  || { echo "域名非法：$DOMAIN" >&2; exit 1; }

cd -- "$(dirname -- "$0")/.."

mapfile -t files < <(
  grep -rl -E 'webscada\.example\.com|X ICP 备 00000000 号' website \
    --include='*.html' --include='*.txt' --include='*.xml' || true
)
[ "${#files[@]}" -gt 0 ] || { echo "未找到占位内容（可能已替换过）"; exit 0; }

# sed 替换文本中的 & / \ 需要转义
esc_domain="$(printf '%s' "$DOMAIN" | sed 's/[&/\\]/\\&/g')"
sed -i "s/webscada\.example\.com/${esc_domain}/g" "${files[@]}"

if [ -n "$ICP" ]; then
  esc_icp="$(printf '%s' "$ICP" | sed 's/[&/\\]/\\&/g')"
  sed -i "s/X ICP 备 00000000 号/${esc_icp}/g" "${files[@]}"
  echo "ICP 备案号已写入页脚：$ICP"
else
  echo "提示：未提供 ICP 备案号，页脚仍为占位文本（境内服务器上线前必须替换）" >&2
fi

echo "已替换 ${#files[@]} 个文件："
printf '  %s\n' "${files[@]}"

echo
echo "下一步："
echo "  1) 证书放 deploy/certs/（如 site.crt / site.key）"
echo "  2) .env 追加：SITE_DOMAIN=${DOMAIN} SITE_CERT=site.crt SITE_KEY=site.key"
echo "  3) docker compose up -d nginx"
