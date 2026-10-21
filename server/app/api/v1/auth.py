"""认证接口（03-接口清单 §2.2）：
- login：统一错误文案防枚举；同用户名连续失败 5 次锁 60s（429）；成功/失败落审计 login（M8）；
  rememberMe=True 额外签发 refresh token（阶段二 Task 3，7 天免重登）
- refresh：refresh token 一次性轮换（旧吊销 + 新对）；复用已吊销 token → 401 且该 user
  全部 refresh 吊销（防泄露重放）；access JWT 签发/负载不变
- logout：当前 token 的 jti 进程内黑名单（重启清空，残留寿命 ≤2h，已声明）；
  请求体带 refreshToken 则一并吊销
- password：返回 204；旧 access 至自然过期仍有效（P0 不做全局作废），但吊销该 user
  全部 refresh token（改密自救：防旧 refresh 经轮换链把泄露窗口延到 7 天）
- me：M8 起返回 role 字段（契约 §4.3，UserOut 迁移至 schemas/user.py）
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
    issue_refresh_token,
    record_login_failure,
    revoke_all_user_refresh_tokens,
    revoke_jti,
    revoke_refresh_token,
    rotate_refresh_token,
    verify_password,
)
from app.db.base import get_db
from app.db.models import User
from app.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    LoginResponse,
    LogoutRequest,
    RefreshRequest,
    RefreshResponse,
)
from app.schemas.user import UserOut
from app.services import audit_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)) -> LoginResponse:
    remain = check_login_lockout(body.username)
    if remain > 0:
        # 锁定期拦截不落审计：非凭据校验结果，避免锁定刷审计噪音
        raise AppError("LOGIN_LOCKED", f"失败次数过多，请 {remain} 秒后重试", 429)

    ip = audit_service.client_ip(request)
    user = await db.scalar(select(User).where(User.username == body.username))
    if user is None:
        dummy_verify(body.password)  # 时序对齐：与"密码错误"分支同耗时，防用户名枚举侧信道
        record_login_failure(body.username)
        await audit_service.audit(request, None, "login",
                                  detail={"success": False, "ip": ip, "username": body.username, "reason": "user_not_found"})
        raise AppError("LOGIN_FAILED", "用户名或密码错误", 401)
    if not verify_password(body.password, user.password_hash):
        record_login_failure(body.username)
        # 统一文案，防用户名枚举
        await audit_service.audit(request, user, "login",
                                  detail={"success": False, "ip": ip, "username": user.username, "reason": "bad_password"})
        raise AppError("LOGIN_FAILED", "用户名或密码错误", 401)

    clear_login_failure(body.username)
    token, expires_in = create_access_token(str(user.id))
    # 记住我终端：签发 refresh（sha256 落库、7 天），明文仅本次响应返回
    refresh_token = await issue_refresh_token(db, user.id) if body.rememberMe else None
    await audit_service.audit(request, user, "login", detail={"success": True, "ip": ip})
    return LoginResponse(access_token=token, expires_in=expires_in, refresh_token=refresh_token)


@router.post("/refresh", response_model=RefreshResponse)
async def refresh(body: RefreshRequest, db: AsyncSession = Depends(get_db)) -> RefreshResponse:
    """refresh token 轮换（操作员免重登）。

    失败一律 401（token 不存在 / 已过期 / 复用已吊销；复用同时已由安全层吊销该 user
    全部 refresh）。新 access 的签发走 create_access_token 唯一入口，语义与登录完全一致。
    """
    rotated = await rotate_refresh_token(db, body.refreshToken)
    if rotated is None:
        raise AppError("TOKEN_EXPIRED", "登录凭证已失效，请重新登录", 401)
    user_id, new_refresh = rotated
    user = await db.get(User, user_id)
    if user is None:
        # 签发后用户被删：refresh 随之外键级联清除，此分支仅防御竞态残值
        raise AppError("TOKEN_EXPIRED", "用户不存在", 401)
    token, expires_in = create_access_token(str(user.id))
    return RefreshResponse(access_token=token, expires_in=expires_in, refresh_token=new_refresh)


@router.post("/logout", status_code=204)
async def logout(
    request: Request,
    body: LogoutRequest | None = None,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    auth = request.headers.get("authorization", "")
    token = auth.removeprefix("Bearer ").strip()
    payload = decode_access_token(token)
    revoke_jti(payload.get("jti", ""), payload.get("exp"))
    # 记住我终端登出：携带 refreshToken 则一并吊销（不带则保持旧行为，仅 access 失效）
    if body is not None and body.refreshToken:
        await revoke_refresh_token(db, body.refreshToken)
    return Response(status_code=204)


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)) -> UserOut:
    # M8 RBAC：me 返回角色，前端按角色收敛菜单/按钮（E 包消费）
    return UserOut(id=str(user.id), username=user.username, role=user.role, createdAt=user.created_at)


@router.put("/password", status_code=204)
async def change_password(
    body: ChangePasswordRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    if not verify_password(body.oldPassword, user.password_hash):
        raise AppError("invalid_old_password", "旧密码错误", 422)
    user.password_hash = hash_password(body.newPassword)
    await db.commit()
    # 改密自救（审查修复）：吊销该 user 全部 refresh。「改密不做全局作废」的既有口径
    # 只覆盖旧 access（≤2h 自然失效）；refresh 轮换链会把泄露窗口延长到 7 天，须一并切断
    await revoke_all_user_refresh_tokens(db, user.id)
    # 自助改密亦属账号安全事件，落 user_mgmt（七类 action 内唯一贴合口径）
    await audit_service.audit(
        request, user, "user_mgmt", target_type="user", target_id=str(user.id),
        detail={"op": "change_password_self", "username": user.username},
    )
    # 旧 token 有效至自然过期（≤2h），P0 不做全局作废——接口契约声明（03-接口清单 §2.2）
    return Response(status_code=204)
