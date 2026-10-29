#!/usr/bin/env bash
# webScada 官网一键部署（独立 nginx 容器，改宿主端口即可上线）
#
# 做什么：环境校验 → 端口占用检查 → nginx 配置校验 → 拉镜像 → 启动容器 → 健康检查
# 不做：安装 Docker、DNS 解析、证书签发（本方案是纯 HTTP 静态托管；
#       要 HTTPS 请走根目录主编排的方式一，或在前置反代上终止 TLS）
#
# 用法：
#   ./deploy/website/deploy.sh                 # 默认宿主机端口 39109
#   ./deploy/website/deploy.sh -p 8080         # 指定宿主机端口
#   ./deploy/website/deploy.sh --pull          # 先拉取最新 nginx 镜像再启动
#   ./deploy/website/deploy.sh --down          # 停止并移除容器
#   ./deploy/website/deploy.sh --logs          # 查看容器日志（Ctrl+C 退出）
#
# 幂等：重复执行即更新。站点文件是只读挂载，git pull 之后内容立刻生效，
#       不需要重建镜像、也不需要重启容器——只有改 nginx.conf 才需要重跑本脚本。
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd -- "$SCRIPT_DIR/../.." && pwd)"
SITE_DIR="$ROOT_DIR/website"
COMPOSE_FILE="$SCRIPT_DIR/docker-compose.yml"
ENV_FILE="$SCRIPT_DIR/.env"
CONTAINER="webscada-site"
DEFAULT_PORT=39109
DEFAULT_IMAGE="library/nginx:1.27-alpine"

# ---- 颜色（非终端自动关闭）----
if [ -t 1 ]; then
  BOLD=$'\033[1m'; RED=$'\033[31m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; RESET=$'\033[0m'
else
  BOLD=''; RED=''; GREEN=''; YELLOW=''; RESET=''
fi

log()  { printf '%s[site]%s %s\n' "$BOLD" "$RESET" "$*"; }
step() { printf '\n%s[site] %s%s\n' "$BOLD" "$*" "$RESET"; }
ok()   { printf '%s[site]%s %s\n' "$GREEN" "$RESET" "$*"; }
warn() { printf '%s[site] 警告%s %s\n' "$YELLOW" "$RESET" "$*" >&2; }
die()  { printf '%s[site] 错误%s %s\n' "$RED" "$RESET" "$*" >&2; exit 1; }

on_err() {
  local code=$?
  printf '%s[site] 错误%s 第 %s 行执行失败（退出码 %s）\n' "$RED" "$RESET" "$1" "$code" >&2
  exit "$code"
}
trap 'on_err "$LINENO"' ERR

usage() {
  cat <<'EOF'
webScada 官网一键部署（独立 nginx 容器，不安装 Docker）

用法: ./deploy/website/deploy.sh [选项]

选项:
  -p, --port PORT         宿主机对外端口（默认 39109）
      --reg-prefix PFX    镜像前缀，如 m.daocloud.io/docker.io/
                          （默认读根目录 .env 的 REG_PREFIX，都没有则用 docker.io/）
      --pull              启动前强制拉取最新 nginx 镜像
      --down              停止并移除官网容器
      --logs              查看容器日志（Ctrl+C 退出）
  -h, --help              显示本帮助

示例:
  ./deploy/website/deploy.sh                       # http://<服务器IP>:39109
  ./deploy/website/deploy.sh -p 8080 --pull        # 换端口 + 先拉新镜像
EOF
}

# ============================================================
# 工具函数
# ============================================================

need_val() { [ -n "${2:-}" ] || die "参数 $1 缺少取值（--help 查看用法）"; }

env_get() { # $1=文件 $2=key → 值（文件不存在或无该键输出空，退出码始终 0）
  [ -f "$1" ] || return 0
  # tr -d '\r'：文件若经 Windows 编辑器存成 CRLF，尾部的 \r 会把端口号污染成非法值
  sed -n "s/^$2=//p" "$1" | tail -n 1 | tr -d '\r'
}

validate_port() {
  [[ "$1" =~ ^[0-9]+$ ]] && [ "$1" -ge 1 ] && [ "$1" -le 65535 ]
}

port_in_use() { # $1=端口；能判定则返回 0/1，判定不了按未占用处理
  local port="$1"
  if command -v ss >/dev/null 2>&1; then
    ss -ltnH 2>/dev/null | awk '{print $4}' | grep -qE "[:.]${port}$"
  elif command -v netstat >/dev/null 2>&1; then
    netstat -ltn 2>/dev/null | awk '{print $4}' | grep -qE "[:.]${port}$"
  else
    return 1
  fi
}

port_owned_by_us() { # $1=端口；端口映射属于本容器则返回 0
  docker ps --filter "name=^/${CONTAINER}$" --format '{{.Ports}}' 2>/dev/null \
    | grep -q ":${1}->80/tcp"
}

http_probe() { # $1=端口；能判定则请求一次首页
  local url="http://127.0.0.1:${1}/"
  if command -v curl >/dev/null 2>&1; then
    curl -fsS -o /dev/null --max-time 5 "$url"
  elif command -v wget >/dev/null 2>&1; then
    wget -q -O /dev/null --timeout=5 "$url"
  else
    return 0   # 宿主机没有 curl/wget：跳过 HTTP 探活，容器健康检查仍然生效
  fi
}

# ============================================================
# 参数解析
# ============================================================

PORT=""
REG_PREFIX=""
ACTION="up"
DO_PULL=0

while [ "$#" -gt 0 ]; do
  case "$1" in
    -p|--port)     need_val "$1" "${2:-}"; PORT="$2"; shift 2 ;;
    --reg-prefix)  need_val "$1" "${2:-}"; REG_PREFIX="$2"; shift 2 ;;
    --pull)        DO_PULL=1; shift ;;
    --down)        ACTION="down"; shift ;;
    --logs)        ACTION="logs"; shift ;;
    -h|--help)     usage; exit 0 ;;
    *)             die "未知参数：$1（--help 查看用法）" ;;
  esac
done

[ -f "$COMPOSE_FILE" ] || die "找不到 $COMPOSE_FILE"
[ -f "$SCRIPT_DIR/nginx.conf" ] || die "找不到 $SCRIPT_DIR/nginx.conf"

# ============================================================
# 环境校验
# ============================================================

step "1/5 环境校验"

command -v docker >/dev/null 2>&1 || die "未安装 docker（本脚本不负责装 Docker）"
docker info >/dev/null 2>&1 || die "Docker 守护进程未运行或当前用户无权限（试试 sudo，或把用户加入 docker 组）"

if docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE=(docker-compose)
else
  die "未找到 docker compose（需要 Compose v2 或 docker-compose 1.29+）"
fi
log "Docker 与 ${COMPOSE[*]} 就绪"

[ -f "$SITE_DIR/index.html" ] || die "站点目录不完整：找不到 $SITE_DIR/index.html"

# 端口：命令行 > deploy/website/.env > 默认值
if [ -z "$PORT" ]; then
  PORT="$(env_get "$ENV_FILE" SITE_PORT)"
  [ -n "$PORT" ] || PORT="$DEFAULT_PORT"
fi
validate_port "$PORT" || die "端口不合法：$PORT（应为 1-65535 的整数）"

# 镜像前缀：命令行 > 根 .env（与产品编排共用镜像加速配置）> 本目录 .env > docker.io/
if [ -z "$REG_PREFIX" ]; then
  REG_PREFIX="$(env_get "$ROOT_DIR/.env" REG_PREFIX)"
fi
if [ -z "$REG_PREFIX" ]; then
  REG_PREFIX="$(env_get "$ENV_FILE" REG_PREFIX)"
fi
[ -n "$REG_PREFIX" ] || REG_PREFIX="docker.io/"
case "$REG_PREFIX" in */) ;; *) REG_PREFIX="${REG_PREFIX}/" ;; esac
IMAGE="${REG_PREFIX}${DEFAULT_IMAGE}"
log "镜像 ${IMAGE}，宿主机端口 ${PORT}"

# ============================================================
# 停止 / 日志：直接返回
# ============================================================

if [ "$ACTION" = "down" ]; then
  step "停止并移除官网容器"
  "${COMPOSE[@]}" -f "$COMPOSE_FILE" down
  ok "已停止（站点文件未改动）"
  exit 0
fi

if [ "$ACTION" = "logs" ]; then
  "${COMPOSE[@]}" -f "$COMPOSE_FILE" logs -f --tail=100 site
  exit 0
fi

# ============================================================
# 端口检查
# ============================================================

step "2/5 端口检查"

if port_in_use "$PORT" && ! port_owned_by_us "$PORT"; then
  # 端口被别的进程占着：提示常见元凶（产品编排的 nginx 默认吃 80/8088/443）
  die "端口 $PORT 已被其他进程占用。换端口：./deploy/website/deploy.sh -p 其他端口"
fi
log "端口 $PORT 可用"

# ============================================================
# 写入编排环境变量
# ============================================================

# compose 只读与本文件同目录的 .env；写进去才能保证「脚本校验的端口 = 容器实际端口」
cat > "$ENV_FILE" <<EOF
# 由 deploy/website/deploy.sh 自动生成，请勿手工添加密钥
SITE_PORT=${PORT}
REG_PREFIX=${REG_PREFIX}
EOF

# ============================================================
# 拉镜像 + 配置校验
# ============================================================

step "3/5 拉取镜像并校验 nginx 配置"

if [ "$DO_PULL" = 1 ] || ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  log "拉取 $IMAGE ..."
  docker pull "$IMAGE"
else
  log "镜像已存在，跳过拉取（需要更新加 --pull）"
fi

# 用一次性容器跑 nginx -t：配置写错在这里就拦住，不会把线上站点搞挂
log "校验 nginx.conf ..."
if ! "${COMPOSE[@]}" -f "$COMPOSE_FILE" run --rm -T --no-deps --entrypoint nginx site -t; then
  die "nginx 配置校验未通过（见上方输出），修正 deploy/website/nginx.conf 后重试"
fi
ok "配置校验通过"

# ============================================================
# 启动
# ============================================================

step "4/5 启动容器"

"${COMPOSE[@]}" -f "$COMPOSE_FILE" up -d --remove-orphans

# ============================================================
# 健康检查
# ============================================================

step "5/5 健康检查"

STATUS=""
for _ in $(seq 1 60); do
  STATUS="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$CONTAINER" 2>/dev/null || echo missing)"
  case "$STATUS" in
    healthy) break ;;
    unhealthy) break ;;
    missing|exited|dead) break ;;
  esac
  sleep 1
done

if [ "$STATUS" != "healthy" ]; then
  warn "容器状态：${STATUS:-unknown}，最近日志如下："
  "${COMPOSE[@]}" -f "$COMPOSE_FILE" logs --tail=40 site >&2 || true
  die "启动失败，排查后重试"
fi

http_probe "$PORT" || { warn "容器健康但 HTTP 探活失败"; }

ok "官网已启动"

# ---- 访问地址提示 ----
# 末尾 || true：Windows Git Bash 的 hostname 不支持 -I，配合 pipefail 会把脚本判成失败
HOST_IP="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
printf '\n'
log "本机访问： http://127.0.0.1:${PORT}/"
if [ -n "$HOST_IP" ]; then
  log "内网访问： http://${HOST_IP}:${PORT}/"
fi
log "公网访问： http://<服务器公网IP>:${PORT}/"
printf '\n'
log "云服务器记得在安全组 / 防火墙放行 ${PORT} 端口，例如："
log "  ufw allow ${PORT}/tcp        # Ubuntu / Debian"
log "  firewall-cmd --add-port=${PORT}/tcp --permanent && firewall-cmd --reload   # CentOS / RHEL"
printf '\n'
log "改内容：git pull 即生效（只读挂载，无需重启）；改 nginx.conf：重跑本脚本"
log "看日志：./deploy/website/deploy.sh --logs    停止：./deploy/website/deploy.sh --down"
