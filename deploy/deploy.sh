#!/usr/bin/env bash
# webScada 应用层一键部署 / 原地升级（在线环境，Ubuntu / Debian）
#
# 做什么：环境校验 →（可选）拉取代码 → 生成/校验 .env → 升级前备份 + 镜像快照
#         → 构建镜像 → 启动 → 健康校验（失败自动回滚到部署前镜像）
# 不做：安装 Docker、配置防火墙、签发证书、配置 crontab（见 README.Docker.md §1/§6）
#
# 用法：
#   ./deploy/deploy.sh                  # 首次部署或原地升级（默认 80/443）
#   ./deploy/deploy.sh -p 8088          # 指定对外 HTTP 端口
#   ./deploy/deploy.sh --pull           # 先 git pull --ff-only 再部署
#   sudo ./deploy/deploy.sh --no-cache  # 强制全量重建
#
# 完整选项见 --help。脚本幂等：重复执行即升级。
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
cd -- "$ROOT_DIR"

ENV_FILE="$ROOT_DIR/.env"
COMPOSE_FILE="$ROOT_DIR/docker-compose.yml"
LOCK_FILE="${TMPDIR:-/tmp}/webscada-deploy.lock"

# ---- 颜色（非终端自动关闭）----
if [ -t 1 ]; then
  BOLD=$'\033[1m'; RED=$'\033[31m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; RESET=$'\033[0m'
else
  BOLD=''; RED=''; GREEN=''; YELLOW=''; RESET=''
fi

log()  { printf '%s[deploy]%s %s\n' "$BOLD" "$RESET" "$*"; }
step() { printf '\n%s[deploy] %s%s\n' "$BOLD" "$*" "$RESET"; }
ok()   { printf '%s[deploy]%s %s\n' "$GREEN" "$RESET" "$*"; }
warn() { printf '%s[deploy] 警告%s %s\n' "$YELLOW" "$RESET" "$*" >&2; }
die()  { printf '%s[deploy] 错误%s %s\n' "$RED" "$RESET" "$*" >&2; exit 1; }

on_err() {
  local code=$?
  printf '%s[deploy] 错误%s 第 %s 行执行失败（退出码 %s）\n' "$RED" "$RESET" "$1" "$code" >&2
  exit "$code"
}

# ============================================================
# 工具函数
# ============================================================

env_get() { # $1=key → 值（未配置输出空，退出码始终 0）
  [ -f "$ENV_FILE" ] || { printf ''; return 0; }
  # tr -d '\r'：.env 若经 Windows 编辑器保存为 CRLF，值尾部的 \r 会让密钥校验/登录失败
  sed -n "s/^${1}=//p" "$ENV_FILE" | tail -n 1 | tr -d '\r'
}

env_set() { # $1=key $2=value；存在则整行替换，不存在则追加（值含 = 也安全）
  local key="$1" val="$2" tmp
  [ -f "$ENV_FILE" ] || : > "$ENV_FILE"
  tmp="$(mktemp "${ENV_FILE}.XXXXXX")"
  awk -v k="$key" -v v="$val" '
    BEGIN { found = 0 }
    index($0, k "=") == 1 { print k "=" v; found = 1; next }
    { print }
    END { if (!found) print k "=" v }
  ' "$ENV_FILE" > "$tmp"
  mv -f "$tmp" "$ENV_FILE"
}

gen_hex()    { openssl rand -hex "$1"; }
gen_fernet() { openssl rand -base64 32 | tr '+/' '-_' | tr -d '\r\n'; }
gen_pass()   { openssl rand -base64 48 | tr -dc 'A-Za-z0-9' | cut -c1-"${1:-16}"; }

validate_port() {
  [[ "$1" =~ ^[0-9]+$ ]] && [ "$1" -ge 1 ] && [ "$1" -le 65535 ]
}

need_val() {
  [ "$#" -ge 2 ] && [ -n "$2" ] || die "参数 $1 缺少取值"
}

usage() {
  cat <<'EOF'
webScada 一键部署 / 升级（应用层，不安装 Docker）

用法: ./deploy/deploy.sh [选项]

选项:
  -p, --port PORT         对外 HTTP 端口（默认取 .env 的 HTTP_PORT，首次 80）
  -s, --https-port PORT   对外 HTTPS 端口（默认取 .env 的 HTTPS_PORT，首次 443）
  -u, --public-url URL    对外访问地址，写入 PUBLIC_BASE_URL（分享链接用）
                         例: https://scada.example.com:8088
      --reg-prefix PFX    基础镜像前缀，如 m.daocloud.io/docker.io/
                         国内网络构建慢/失败时使用
      --admin-password P  首次部署时指定管理员密码（不传则随机生成，
                         仅允许字母数字与 _ . @ + -，8~64 位）
      --pull              部署前执行 git pull --ff-only（要求工作区干净）
      --no-cache          禁用构建缓存，全量重建
      --no-backup         升级前跳过数据库备份（不推荐）
      --with-sim          同时启动仿真验证台（sim profile）
  -h, --help              显示本帮助

前置条件:
  - Ubuntu / Debian（其他发行版通常也可用，脚本不安装 Docker）
  - Docker Engine >= 25 + Compose v2，当前用户有 Docker 权限
  - 在 webScada 仓库根目录执行（含 docker-compose.yml）

说明:
  - 首次部署自动生成 .env（随机 JWT / 数据源密钥 / 数据库与 EMQX 口令），
    管理员密码只在输出中显示一次。
  - 升级前默认调用 scripts/backup.sh 备份；健康检查失败自动回滚旧镜像，
    但数据库迁移不回滚——跨版本升级前请阅读 CHANGELOG。
EOF
}

# 部署前镜像快照：构建覆盖同名 tag 后旧镜像以 dangling 形式保留，可 retag 回滚
snapshot_image() { # $1=service → "<image id>|<image ref>"，无容器时输出空
  local cid
  cid="$(docker compose ps -aq "$1" 2>/dev/null | head -n 1)" || true
  [ -n "$cid" ] || return 0
  docker inspect --format '{{.Image}}|{{.Config.Image}}' "$cid" 2>/dev/null || true
}

wait_service_ready() { # $1=service $2=超时秒数
  # 注意：local 是命令，其参数在赋值前统一展开，依赖前面变量的声明必须拆行
  local svc="$1"
  local timeout="${2:-180}"
  local deadline=$((SECONDS + timeout))
  local cid state=""
  while [ "$SECONDS" -lt "$deadline" ]; do
    cid="$(docker compose ps -q "$svc" 2>/dev/null | head -n 1)" || true
    if [ -n "$cid" ]; then
      state="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$cid" 2>/dev/null || echo unknown)"
      case "$state" in
        healthy|running) return 0 ;;
        exited|dead)     warn "$svc 容器状态异常：$state"; return 1 ;;
      esac
    fi
    sleep 3
  done
  warn "$svc 未在 ${timeout}s 内就绪（最后状态：${state:-未创建}）"
  return 1
}

# 仅加载函数（测试 / 其他脚本 source 用）：直接执行时 return 失败 → exit 0
if [ "${WEBSCADA_DEPLOY_LIB:-0}" = "1" ]; then
  return 0 2>/dev/null || exit 0
fi

trap 'on_err "$LINENO"' ERR

# ============================================================
# 参数
# ============================================================
ARG_PORT=""
ARG_HTTPS_PORT=""
ARG_PUBLIC_URL=""
ARG_REG_PREFIX=""
ARG_ADMIN_PASSWORD=""
DO_PULL=0
NO_CACHE=0
NO_BACKUP=0
WITH_SIM=0
FIRST_RUN=0
UPGRADE=0
PREV_SERVER_ID=""
PREV_SERVER_REF=""
PREV_NGINX_ID=""
PREV_NGINX_REF=""

while [ "$#" -gt 0 ]; do
  case "$1" in
    -p|--port)          need_val "$@"; ARG_PORT="$2"; shift 2 ;;
    -s|--https-port)    need_val "$@"; ARG_HTTPS_PORT="$2"; shift 2 ;;
    -u|--public-url)    need_val "$@"; ARG_PUBLIC_URL="$2"; shift 2 ;;
    --reg-prefix)       need_val "$@"; ARG_REG_PREFIX="$2"; shift 2 ;;
    --admin-password)   need_val "$@"; ARG_ADMIN_PASSWORD="$2"; shift 2 ;;
    --pull)             DO_PULL=1; shift ;;
    --no-cache)         NO_CACHE=1; shift ;;
    --no-backup)        NO_BACKUP=1; shift ;;
    --with-sim)         WITH_SIM=1; shift ;;
    -h|--help)          usage; exit 0 ;;
    *)                  die "未知参数：$1（--help 查看用法）" ;;
  esac
done

# ============================================================
# 0. 前置校验
# ============================================================
step "0/7 环境校验"

[ -f "$COMPOSE_FILE" ] || die "未找到 docker-compose.yml：请在 webScada 仓库根目录执行"

missing=()
for cmd in docker curl openssl awk sed grep; do
  command -v "$cmd" >/dev/null 2>&1 || missing+=("$cmd")
done
[ "${#missing[@]}" -eq 0 ] || die "缺少必需命令：${missing[*]}"

if [ -r /etc/os-release ]; then
  # shellcheck disable=SC1091
  . /etc/os-release
  log "系统：${PRETTY_NAME:-未知}"
  case "${ID:-}" in
    ubuntu|debian|raspbian|linuxmint) ;;
    *)
      case " ${ID_LIKE:-} " in
        *debian*|*ubuntu*) ;;
        *) warn "非 Ubuntu / Debian 系（ID=${ID:-未知}），按通用 Linux 继续；遇问题见 README.Docker.md" ;;
      esac
      ;;
  esac
fi

docker compose version >/dev/null 2>&1 \
  || die "需要 Docker Compose v2（docker compose 子命令）。安装见 README.Docker.md §1"
docker info >/dev/null 2>&1 \
  || die "无法访问 Docker 守护进程：请用 sudo 运行，或将当前用户加入 docker 组后重新登录"

# 并发部署互斥（flock 不可用时跳过）
if command -v flock >/dev/null 2>&1; then
  exec 9>"$LOCK_FILE"
  flock -n 9 || die "另一个部署进程正在运行（锁文件：$LOCK_FILE）"
fi

avail_kb="$(df -Pk "$ROOT_DIR" 2>/dev/null | awk 'NR==2 {print $4}' || true)"
avail_kb="${avail_kb:-0}"
if [ "$avail_kb" -lt 5242880 ]; then
  warn "根分区可用 $(awk -v k="$avail_kb" 'BEGIN{printf "%.1f", k/1048576}')GB，建议 ≥5GB（镜像 + 构建缓存 + 备份）"
fi

if [ -r /proc/meminfo ]; then
  mem_kb="$(awk '/^MemTotal:/ {print $2}' /proc/meminfo 2>/dev/null || true)"
  if [ -n "$mem_kb" ]; then
    mem_mb=$((mem_kb / 1024))
    [ "$mem_mb" -ge 1900 ] || warn "内存 ${mem_mb}MB，低于推荐 2GB；前端构建阶段峰值更高"
  fi
fi

# ============================================================
# 1. 代码同步（可选）
# ============================================================
step "1/7 代码同步"

if [ "$DO_PULL" -eq 1 ]; then
  git rev-parse --is-inside-work-tree >/dev/null 2>&1 || die "--pull 要求当前目录是 git 仓库"
  if ! git diff --quiet || ! git diff --cached --quiet; then
    die "存在未提交的本地改动，拒绝自动 git pull（请先提交或 stash）"
  fi
  log "git pull --ff-only …"
  git pull --ff-only || die "git pull 失败（本地分支与远端分叉，请手动处理）"
  ok "代码已更新到 $(git rev-parse --short HEAD)"
else
  log "跳过代码更新（需要时加 --pull）"
fi

# ============================================================
# 2. 配置 .env
# ============================================================
step "2/7 配置 .env"

[ -z "$ARG_PORT" ] || validate_port "$ARG_PORT" || die "--port 取值非法：$ARG_PORT"
[ -z "$ARG_HTTPS_PORT" ] || validate_port "$ARG_HTTPS_PORT" || die "--https-port 取值非法：$ARG_HTTPS_PORT"
if [ -n "$ARG_ADMIN_PASSWORD" ]; then
  [[ "$ARG_ADMIN_PASSWORD" =~ ^[A-Za-z0-9_.@+-]{8,64}$ ]] \
    || die "--admin-password 只允许字母数字与 _ . @ + -，长度 8~64"
fi

if [ ! -f "$ENV_FILE" ]; then
  FIRST_RUN=1
  log "未找到 .env，生成随机密钥…"
  cat > "$ENV_FILE" <<'EOF'
# 由 deploy/deploy.sh 生成。本文件含密钥：chmod 600，离线备份，勿提交 Git。
# DATASOURCE_SECRET 丢失 = 已存数据源凭证不可解密；JWT_SECRET 变更 = 所有登录会话失效。
# 完整参数说明见 .env.example。
EOF
  env_set POSTGRES_USER webscada
  env_set POSTGRES_PASSWORD "$(gen_hex 16)"
  env_set POSTGRES_DB webscada
  env_set JWT_SECRET "$(gen_hex 32)"
  env_set JWT_EXPIRE_HOURS 2
  env_set DATASOURCE_SECRET "$(gen_fernet)"
  env_set ADMIN_USER admin
  env_set ADMIN_PASSWORD "${ARG_ADMIN_PASSWORD:-$(gen_pass 16)}"
  env_set HTTP_PORT "${ARG_PORT:-80}"
  env_set HTTPS_PORT "${ARG_HTTPS_PORT:-443}"
  env_set PUBLIC_BASE_URL "${ARG_PUBLIC_URL:-}"
  env_set REG_PREFIX "${ARG_REG_PREFIX:-}"
  env_set EMQX_DASHBOARD_USER admin
  env_set EMQX_DASHBOARD_PASSWORD "$(gen_hex 12)"
  env_set EMQX_DEFAULT_USERNAME webscada_mqtt
  env_set EMQX_DEFAULT_PASSWORD "$(gen_hex 12)"
  chmod 600 "$ENV_FILE"
  ok ".env 已生成（chmod 600）"
else
  log "使用已有 .env"
  [ -z "$ARG_PORT" ]        || env_set HTTP_PORT "$ARG_PORT"
  [ -z "$ARG_HTTPS_PORT" ]  || env_set HTTPS_PORT "$ARG_HTTPS_PORT"
  [ -z "$ARG_PUBLIC_URL" ]  || env_set PUBLIC_BASE_URL "$ARG_PUBLIC_URL"
  [ -z "$ARG_REG_PREFIX" ]  || env_set REG_PREFIX "$ARG_REG_PREFIX"
fi

# 必填项校验（compose 用 ${VAR:?} 硬性要求，空值要到 up 阶段才暴露，这里提前拦）
missing_env=()
for key in POSTGRES_PASSWORD JWT_SECRET DATASOURCE_SECRET ADMIN_PASSWORD; do
  val="$(env_get "$key")"
  [ -n "${val//[[:space:]]/}" ] || missing_env+=("$key")
done
[ "${#missing_env[@]}" -eq 0 ] \
  || die ".env 缺少必填项：${missing_env[*]}（模板见 .env.example，补齐后重试）"

jwt_secret="$(env_get JWT_SECRET)"
[ "${#jwt_secret}" -ge 32 ] || die "JWT_SECRET 长度不足 32 字符（应用会拒绝启动）"

ds_secret="$(env_get DATASOURCE_SECRET)"
[[ "$ds_secret" =~ ^[A-Za-z0-9_-]{43}=$ ]] \
  || die "DATASOURCE_SECRET 不是合法 Fernet 密钥（应为 44 字符 urlsafe base64）。生成：openssl rand -base64 32 | tr '+/' '-_'"

PORT="$(env_get HTTP_PORT)"
PORT="${PORT:-80}"
HTTPS_PORT="$(env_get HTTPS_PORT)"
HTTPS_PORT="${HTTPS_PORT:-443}"
validate_port "$PORT" || die ".env 中 HTTP_PORT 非法：$PORT"
validate_port "$HTTPS_PORT" || die ".env 中 HTTPS_PORT 非法：$HTTPS_PORT"

# 端口占用检查：仅在本项目容器不存在时做（重复部署时端口本就归本项目所有）
if ! docker compose ps -q nginx 2>/dev/null | grep -q .; then
  if command -v ss >/dev/null 2>&1; then
    for p in "$PORT" "$HTTPS_PORT"; do
      if ss -ltn 2>/dev/null | awk '{print $4}' | grep -qE "[:.]${p}$"; then
        die "端口 ${p} 已被其他进程占用，请用 -p/-s 指定空闲端口，或先停止占用进程"
      fi
    done
  fi
fi

# ============================================================
# 3. 识别升级 + 部署前备份
# ============================================================
step "3/7 部署前备份"

if [ -n "$(docker volume ls -q --filter label=com.docker.compose.project=webscada 2>/dev/null || true)" ]; then
  UPGRADE=1
  log "检测到已有部署（数据卷存在），按升级流程处理"
else
  log "未检测到已有数据卷，按首次部署处理（跳过备份）"
fi

if [ "$UPGRADE" -eq 1 ] && [ "$NO_BACKUP" -eq 0 ]; then
  log "调用 scripts/backup.sh 备份数据库 / 上传文件 / EMQX 数据…"
  if ./scripts/backup.sh; then
    ok "部署前备份完成（backups/）"
  else
    die "备份失败，已中止部署。确认无需备份可加 --no-backup 跳过"
  fi
fi

if [ "$UPGRADE" -eq 1 ]; then
  snap="$(snapshot_image server)"
  PREV_SERVER_ID="${snap%%|*}"
  PREV_SERVER_REF="${snap#*|}"
  [ "$PREV_SERVER_REF" = "$snap" ] && PREV_SERVER_REF=""
  snap="$(snapshot_image nginx)"
  PREV_NGINX_ID="${snap%%|*}"
  PREV_NGINX_REF="${snap#*|}"
  [ "$PREV_NGINX_REF" = "$snap" ] && PREV_NGINX_REF=""
  if [ -n "$PREV_SERVER_ID" ]; then
    log "已记录部署前镜像：server=${PREV_SERVER_ID:0:19}… nginx=${PREV_NGINX_ID:0:19}…"
  else
    warn "未找到运行中的 server 容器，本次不提供自动回滚"
  fi
fi

# ============================================================
# 4. 构建镜像
# ============================================================
step "4/7 构建镜像（server / nginx / tls-init）"

build_args=()
[ "$NO_CACHE" -eq 1 ] && build_args+=(--no-cache)

log "开始构建，首次约 3-5 分钟…"
if ! docker compose build ${build_args[@]+"${build_args[@]}"} server nginx tls-init; then
  die "镜像构建失败：旧版本容器保持运行，未做任何变更。
    国内网络可尝试：--reg-prefix m.daocloud.io/docker.io/"
fi
ok "镜像构建完成"

# ============================================================
# 5. 启动
# ============================================================
step "5/7 启动服务"

if [ "$WITH_SIM" -eq 1 ]; then
  log "启动基线 + 仿真验证台（sim profile）…"
  docker compose --profile sim up -d --remove-orphans
else
  log "启动基线四容器（nginx / server / postgres / emqx）…"
  docker compose up -d --remove-orphans
fi
ok "容器已创建"

# ============================================================
# 6. 健康校验
# ============================================================
step "6/7 健康校验"

stack_ok=1
for svc in postgres emqx server nginx; do
  if wait_service_ready "$svc" 180; then
    ok "$svc 就绪"
  else
    stack_ok=0
    break
  fi
done

PORT_ACTUAL="$(docker compose port nginx 80 2>/dev/null | head -n 1 | sed 's/.*://' || true)"
PORT_ACTUAL="${PORT_ACTUAL:-$PORT}"
HEALTH_URL="http://127.0.0.1:${PORT_ACTUAL}/api/v1/health"

if [ "$stack_ok" -eq 1 ]; then
  http_ok=0
  for _ in $(seq 1 30); do
    if curl -fsS -m 3 "$HEALTH_URL" >/dev/null 2>&1; then
      http_ok=1
      break
    fi
    sleep 2
  done
  [ "$http_ok" -eq 1 ] || stack_ok=0
fi

if [ "$stack_ok" -ne 1 ]; then
  warn "健康检查未通过，最近日志如下："
  docker compose logs --tail 80 server nginx 2>/dev/null || true
  if [ -n "$PREV_SERVER_ID" ] && [ -n "$PREV_SERVER_REF" ]; then
    log "自动回滚到部署前镜像…"
    docker tag "$PREV_SERVER_ID" "$PREV_SERVER_REF" || warn "server 镜像回滚失败"
    if [ -n "$PREV_NGINX_ID" ] && [ -n "$PREV_NGINX_REF" ]; then
      docker tag "$PREV_NGINX_ID" "$PREV_NGINX_REF" || warn "nginx 镜像回滚失败"
    fi
    docker compose up -d --no-build --force-recreate server nginx || warn "回滚启动失败"
    warn "已回滚到部署前镜像。注意：数据库迁移不会回滚，跨版本请按 docs/operations/backup-restore.md 恢复备份"
  else
    warn "首次部署无旧镜像可回滚，请根据上方日志排查"
  fi
  exit 1
fi

ok "HTTP 健康检查通过：$HEALTH_URL"

# ============================================================
# 7. 完成
# ============================================================
step "7/7 部署完成"

HOST_IP="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
HOST_IP="${HOST_IP:-127.0.0.1}"
if [ "$PORT" = "80" ]; then
  ACCESS_URL="http://${HOST_IP}"
else
  ACCESS_URL="http://${HOST_IP}:${PORT}"
fi

printf '\n'
ok "访问地址：${ACCESS_URL}/"
ok "HTTPS：  https://${HOST_IP}:${HTTPS_PORT}/（自签证书，浏览器会提示不受信）"
if [ "$FIRST_RUN" -eq 1 ]; then
  ok "管理员： $(env_get ADMIN_USER) / $(env_get ADMIN_PASSWORD)"
  warn "以上初始密码只显示这一次，登录后请立即修改"
else
  log "管理员账号沿用 .env 中的 ADMIN_USER / ADMIN_PASSWORD"
fi

printf '\n常用命令：\n'
printf '  docker compose ps                    # 查看容器状态\n'
printf '  docker compose logs -f server        # 跟踪后端日志\n'
printf '  ./scripts/backup.sh                  # 手动备份（建议 crontab 每日执行）\n'
printf '\n'
warn "请离线备份 .env：JWT_SECRET 丢失 = 全员重新登录；DATASOURCE_SECRET 丢失 = 已存数据源凭证不可解密"
[ -n "$(env_get PUBLIC_BASE_URL)" ] || printf '  %s提示%s 若通过域名或反向代理访问，请设置 PUBLIC_BASE_URL（--public-url）以生成正确的分享链接\n' "$YELLOW" "$RESET"
