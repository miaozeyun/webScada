"""幂等初始化管理员：仅当 ADMIN_USER 不存在时创建，绝不覆盖已改密码（改密走 PUT /api/v1/auth/password）。"""
import asyncio

from sqlalchemy import select

from app.core.config import settings
from app.core.security import hash_password
from app.db.base import SessionLocal
from app.db.models import User


async def main() -> None:
    async with SessionLocal() as session:
        existing = await session.scalar(select(User).where(User.username == settings.ADMIN_USER))
        if existing is not None:
            print(f"[create_admin] 管理员 {settings.ADMIN_USER} 已存在，跳过（不覆盖密码）")
            return
        user = User(username=settings.ADMIN_USER, password_hash=hash_password(settings.ADMIN_PASSWORD))
        session.add(user)
        await session.commit()
        print(f"[create_admin] 已创建管理员 {settings.ADMIN_USER}")


if __name__ == "__main__":
    asyncio.run(main())
