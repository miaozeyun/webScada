"""显式重置管理员密码（演示环境 / 运维应急）。

与 create_admin.py 的幂等初始化不同：本脚本**会覆盖**已存在管理员的密码，
用于「.env 改了 ADMIN_PASSWORD 但库里已有用户」的场景（create_admin 不覆盖）。

用法（容器内，缺省取容器环境里的 ADMIN_PASSWORD，不落 argv/进程列表）：
    docker compose exec -T server python scripts/reset_admin_password.py
    # 需要临时指定其他口令时（不进 .env）：
    docker compose exec -T -e NEW_ADMIN_PASSWORD='新密码' server \
      python scripts/reset_admin_password.py

宿主机裸跑：
    NEW_ADMIN_PASSWORD='新密码' python scripts/reset_admin_password.py
"""
import asyncio
import os
import sys
from pathlib import Path

# 容器内 `docker compose exec` 不经过 entrypoint，不会有 PYTHONPATH=/app；自行补齐（app 包在 /app）
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.core.config import settings
from app.core.security import hash_password
from app.db.base import SessionLocal
from app.db.models import User


async def main() -> None:
    # 优先级：NEW_ADMIN_PASSWORD（显式覆盖） > 容器环境 ADMIN_PASSWORD（来自 .env）
    new_password = (os.environ.get("NEW_ADMIN_PASSWORD") or settings.ADMIN_PASSWORD or "").strip()
    if not new_password:
        sys.exit("[reset_admin_password] 无名可用密码：设置 NEW_ADMIN_PASSWORD 或 .env 的 ADMIN_PASSWORD")

    async with SessionLocal() as session:
        user = await session.scalar(select(User).where(User.username == settings.ADMIN_USER))
        if user is None:
            # 首次部署尚未初始化时的兜底：直接建管理员（角色固定 admin）
            user = User(
                username=settings.ADMIN_USER,
                password_hash=hash_password(new_password),
                role="admin",
            )
            session.add(user)
            action = "已创建"
        else:
            user.password_hash = hash_password(new_password)
            action = "已重置"
        await session.commit()
        print(f"[reset_admin_password] {action}管理员 {settings.ADMIN_USER} 的密码")


if __name__ == "__main__":
    asyncio.run(main())
