#!/usr/bin/env bash
# 官网域名 / ICP 备案号批量替换（website/ 下的占位内容）
#
# 用法:
#   ./scripts/set-site-domain.sh www.example.com
#   ./scripts/set-site-domain.sh www.example.com "京ICP备12345678号-1"
#
# 替换范围：website/*.html、*.txt、*.xml 中的
#   webscada.example.com      → 正式域名（canonical / og:url / sitemap / robots / llms.txt / JSON-LD）
#
# ICP 备案号：只在给了第二个参数时才写入页脚。
#   页脚默认不预置任何占位文本——挂假备案号会被扫站工具判为「备案信息异常」，
#   比不挂更麻烦；备案通过后再执行本脚本补上即可（可重复执行，已写入的会跳过）。
#
# 上线后还有一件不能省的事：境内服务器须在 30 日内完成公安联网备案
#   （beian.mps.gov.cn），通过后同样把「公网安备 XXXX 号」补进页脚。
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

# --- 1. 域名替换 ---------------------------------------------------------
mapfile -t files < <(
  grep -rl -E 'webscada\.example\.com' website \
    --include='*.html' --include='*.txt' --include='*.xml' || true
)

if [ "${#files[@]}" -gt 0 ]; then
  # sed 替换文本中的 & / \ 需要转义
  esc_domain="$(printf '%s' "$DOMAIN" | sed 's/[&/\\]/\\&/g')"
  sed -i "s/webscada\.example\.com/${esc_domain}/g" "${files[@]}"
  echo "已替换 ${#files[@]} 个文件的域名为：$DOMAIN"
  printf '  %s\n' "${files[@]}"
else
  echo "未找到域名占位 webscada.example.com（可能已替换过）"
fi

# --- 2. ICP 备案号写入页脚 ------------------------------------------------
if [ -z "$ICP" ]; then
  echo "提示：未提供 ICP 备案号，页脚保持无备案号状态（境内上线前完成备案后，带第二个参数重跑本脚本）" >&2
else
  case "$ICP" in
    *'<'*|*'>'*|*'"'*) echo "备案号含非法字符：$ICP" >&2; exit 1 ;;
  esac

  # perl 替换串中 & { } 需转义
  esc_icp="$(printf '%s' "$ICP" | sed 's/[\\/&{}]/\\&/g')"
  mapfile -t pages < <(grep -rl 'class="site-footer"' website --include='*.html' || true)

  if [ "${#pages[@]}" -eq 0 ]; then
    echo "未找到含页脚的页面，跳过 ICP 写入" >&2
  else
    inserted=0
    skipped=0
    for f in "${pages[@]}"; do
      # 幂等：已写入过就不再插入
      if grep -q 'beian\.miit\.gov\.cn' "$f"; then
        skipped=$((skipped + 1))
        continue
      fi
      # 插在 .footer-bottom 的收尾 </div> 之前，即版权行之后
      perl -0pi -e "s{(\\n[ \\t]*</div>\\n[ \\t]*</div>\\n[ \\t]*</footer>)}{\\n        <span><a href=\"https://beian.miit.gov.cn/\" target=\"_blank\" rel=\"noopener\" style=\"color:inherit\">${esc_icp}</a></span>\$1}" "$f"
      inserted=$((inserted + 1))
    done
    echo "ICP 备案号已写入 ${inserted} 个页面页脚：$ICP"
    [ "$skipped" -eq 0 ] || echo "另有 ${skipped} 个页面已含备案链接，已跳过"
  fi

  echo "别忘了：公安联网备案通过后，把「公网安备 XXXX 号」也补进页脚"
fi

echo
echo "下一步："
echo "  1) 证书放 deploy/certs/（如 site.crt / site.key）"
echo "  2) .env 追加：SITE_DOMAIN=${DOMAIN} SITE_CERT=site.crt SITE_KEY=site.key"
echo "  3) docker compose up -d nginx"
