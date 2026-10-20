"""通用依赖：当前登录用户（JWT Bearer）与 RBAC 角色依赖（M8，契约 §6.3 签名冻结）。"""
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


# ---------------- M8 RBAC（三级角色矩阵：401=未登录/凭证无效，403=角色不足） ----------------

# 工程写口径（团队协作）：operator/admin 可编辑任意工程；owner 限制仅 DELETE 收紧（契约 §4.7）
_EDIT_ROLES = ("admin", "operator")


def require_role(*roles: str):
    """角色白名单依赖工厂：JWT 用户角色不在白名单 → 403 FORBIDDEN（未登录仍 401）。"""

    async def _dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise AppError("FORBIDDEN", "当前角色无权限执行该操作", 403)
        return user

    return _dependency


require_admin = require_role("admin")
require_operator = require_role(*_EDIT_ROLES)


def require_project_edit(user: User, project_id: str) -> None:
    """工程写权限闸门（端点体内调用）：operator/admin 可编辑任意工程（§4.7 团队协作口径）。

    仅做角色校验，工程存在性由端点经 project_service.get_project 兜底（404）；
    project_id 预留行级权限扩展位（当前不做按工程授权）。
    """
    if user.role not in _EDIT_ROLES:
        raise AppError("FORBIDDEN", "当前角色无权限编辑工程", 403)


def require_project_view(user: User, project_id: str) -> None:
    """工程读权限闸门：任意 JWT 角色可读（viewer 只读口径）。project_id 预留行级权限扩展位。"""
    return None
