"""通用依赖：当前登录用户（JWT Bearer）。"""
import uuid

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.security import decode_access_token
from app.db.base import get_db
from app.db.models import User

_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    if creds is None:
        raise AppError("UNAUTHORIZED", "未登录或缺少凭证", 401)
    payload = decode_access_token(creds.credentials)
    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError):
        raise AppError("UNAUTHORIZED", "无效的登录凭证", 401) from None
    user = await db.get(User, user_id)
    if user is None:
        raise AppError("UNAUTHORIZED", "用户不存在", 401)
    return user
