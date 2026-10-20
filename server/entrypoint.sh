#!/usr/bin/env bash
# 容器入口：等待数据库就绪 → 执行迁移 → 幂等初始化管理员 → 启动服务
# compose 已有 depends_on(healthy)，此处重试是双保险（M0 风险对策）
set -e
# app 包以源码方式存在于 /app（venv 仅装依赖），显式加入模块搜索路径
export PYTHONPATH=/app

DB_HOST=$(python -c "import urllib.parse as u;print(u.urlparse(__import__('app.core.config',fromlist=['settings']).settings.DATABASE_URL).hostname or 'postgres')")
DB_PORT=$(python -c "import urllib.parse as u;print(u.urlparse(__import__('app.core.config',fromlist=['settings']).settings.DATABASE_URL).port or 5432)")

for i in $(seq 1 30); do
  if python -c "import socket,sys;s=socket.socket();s.settimeout(2);sys.exit(0 if s.connect_ex(('$DB_HOST',$DB_PORT))==0 else 1)"; then
    echo "[entrypoint] 数据库已就绪"
    break
  fi
  echo "[entrypoint] 等待 $DB_HOST:$DB_PORT 就绪... ($i/30)"
  sleep 2
done

alembic upgrade head
python scripts/create_admin.py
# --proxy-headers + 信任网段：让 uvicorn 采纳 nginx 的 X-Forwarded-For（M4+ 建连限流依赖真实 client IP）
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips="*"
