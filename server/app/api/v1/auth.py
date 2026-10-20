"""认证接口（03-接口清单 §2.2）：
- login：统一错误文案防枚举；同用户名连续失败 5 次锁 60s（429）
- logout：当前 token 的 jti 进程内黑名单（重启清空，残留寿命 ≤2h，已声明）
- password：返回 204；旧 token 至自然过期仍有效（P0 不做全局作废）
"""
from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.errors import AppError
from app.core.security import (
    check_login_lockout,
    clear_login_failure,
    create_access_token,
    decode_access_token,
    dummy_verify,
    hash_password,
    record_login_failure,
    revoke_jti,
    verify_password,
)
from app.db.base import get_db
from app.db.models import User
from app.schemas.auth import ChangePasswordRequest, LoginRequest, LoginResponse, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)) -> LoginResponse:
    remain = check_login_lockout(body.username)
    if remain > 0:
        raise AppError("LOGIN_LOCKED", f"失败次数过多，请 {remain} 秒后重试", 429)

    user = await db.scalar(select(User).where(User.username == body.username))
    if user is None:
        dummy_verify(body.password)  # 时序对齐：与"密码错误"分支同耗时，防用户名枚举侧信道
        record_login_failure(body.username)
        raise AppError("LOGIN_FAILED", "用户名或密码错误", 401)
    if not verify_password(body.password, user.password_hash):
        record_login_failure(body.username)
        # 统一文案，防用户名枚举
        raise AppError("LOGIN_FAILED", "用户名或密码错误", 401)

    clear_login_failure(body.username)
    token, expires_in = create_access_token(str(user.id))
    return LoginResponse(access_token=token, expires_in=expires_in)


@router.post("/logout", status_code=204)
async def logout(request: Request, _user: User = Depends(get_current_user)) -> Response:
    auth = request.headers.get("authorization", "")
    token = auth.removeprefix("Bearer ").strip()
    payload = decode_access_token(token)
    revoke_jti(payload.get("jti", ""), payload.get("exp"))
    return Response(status_code=204)


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)) -> UserOut:
    # P0 无角色概念（users 表无 role 列；单团队全员管理员，P2 迁移扩展）
    return UserOut(id=str(user.id), username=user.username, createdAt=user.created_at)


@router.put("/password", status_code=204)
async def change_password(
    body: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    if not verify_password(body.oldPassword, user.password_hash):
        raise AppError("invalid_old_password", "旧密码错误", 422)
    user.password_hash = hash_password(body.newPassword)
    await db.commit()
    # 旧 token 有效至自然过期（≤2h），P0 不做全局作废——接口契约声明（03-接口清单 §2.2）
    return Response(status_code=204)
