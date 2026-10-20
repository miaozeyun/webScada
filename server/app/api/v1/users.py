"""用户管理接口（M8 RBAC，契约 §4.3）：全部端点 admin 专属。

- CRUD + 角色调整 + admin 重置密码（无需旧密码）
- 最后一个 admin 保护：降级/删除后 admin 计数为 0 → 409 last_admin
- 不能删自己 → 422 self_delete
- 全部写操作落审计 user_mgmt（audit_service 自建短会话，主事务回滚不留空档）
"""
import uuid

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.core.errors import AppError
from app.core.security import hash_password
from app.db.base import get_db
from app.db.models import User
from app.schemas.user import UserCreate, UserListOut, UserOut, UserPasswordReset, UserUpdate
from app.services import audit_service

router = APIRouter(prefix="/users", tags=["users"])

_ROLE_ADMIN = "admin"


def _to_out(u: User) -> UserOut:
    return UserOut(id=str(u.id), username=u.username, role=u.role, createdAt=u.created_at)


async def _admin_count(db: AsyncSession, exclude_user_id: uuid.UUID | None = None) -> int:
    """admin 计数；exclude_user_id 用于"除目标用户外"口径（最后一个 admin 保护）。"""
    stmt = select(func.count()).select_from(User).where(User.role == _ROLE_ADMIN)
    if exclude_user_id is not None:
        stmt = stmt.where(User.id != exclude_user_id)
    return int(await db.scalar(stmt) or 0)


async def _get_user_or_404(db: AsyncSession, user_id: str) -> User:
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise AppError("NOT_FOUND", "用户不存在", 404) from None
    user = await db.get(User, uid)
    if user is None:
        raise AppError("NOT_FOUND", "用户不存在", 404)
    return user


@router.get("", response_model=UserListOut)
async def list_users(
    keyword: str | None = None,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> UserListOut:
    base = select(User)
    if keyword:
        base = base.where(User.username.ilike(f"%{keyword}%"))
    total = await db.scalar(select(func.count()).select_from(base.subquery())) or 0
    # created_at 升序：初始 admin 稳定居首（存量用户由 0002 迁移全量置 admin）
    items = (
        await db.scalars(
            base.order_by(User.created_at.asc(), User.username.asc())
            .offset((page - 1) * size)
            .limit(size)
        )
    ).all()
    return UserListOut(
        total=int(total), page=page, size=size, items=[_to_out(u) for u in items]
    )


@router.post("", response_model=UserOut, status_code=201)
async def create_user(
    body: UserCreate,
    request: Request,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> UserOut:
    dup = await db.scalar(select(User.id).where(User.username == body.username))
    if dup is not None:
        raise AppError("USERNAME_EXISTS", "用户名已存在", 409)
    created = User(username=body.username, password_hash=hash_password(body.password), role=body.role)
    db.add(created)
    await db.commit()
    await db.refresh(created)
    await audit_service.audit(
        request, user, "user_mgmt", target_type="user", target_id=str(created.id),
        detail={"op": "create", "username": created.username, "role": created.role},
    )
    return _to_out(created)


@router.put("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: str,
    body: UserUpdate,
    request: Request,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> UserOut:
    target = await _get_user_or_404(db, user_id)
    # 最后一个 admin 保护：把唯一 admin 降级后系统中将无管理员 → 409
    if target.role == _ROLE_ADMIN and body.role != _ROLE_ADMIN:
        if await _admin_count(db, exclude_user_id=target.id) == 0:
            raise AppError("last_admin", "系统至少保留一个管理员，禁止降级最后一个 admin", 409)
    target.role = body.role
    await db.commit()
    await db.refresh(target)
    await audit_service.audit(
        request, user, "user_mgmt", target_type="user", target_id=str(target.id),
        detail={"op": "update_role", "username": target.username, "role": target.role},
    )
    return _to_out(target)


@router.put("/{user_id}/password", status_code=204)
async def reset_user_password(
    user_id: str,
    body: UserPasswordReset,
    request: Request,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Response:
    target = await _get_user_or_404(db, user_id)
    target.password_hash = hash_password(body.newPassword)
    await db.commit()
    await audit_service.audit(
        request, user, "user_mgmt", target_type="user", target_id=str(target.id),
        detail={"op": "reset_password", "username": target.username},
    )
    return Response(status_code=204)


@router.delete("/{user_id}", status_code=204)
async def delete_user(
    user_id: str,
    request: Request,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Response:
    target = await _get_user_or_404(db, user_id)
    if target.id == user.id:
        # 判定顺序：self_delete（422）先于最后一个 admin（409），契约 §4.3
        raise AppError("self_delete", "不能删除当前登录账号", 422)
    if target.role == _ROLE_ADMIN and await _admin_count(db, exclude_user_id=target.id) == 0:
        raise AppError("last_admin", "系统至少保留一个管理员，禁止删除最后一个 admin", 409)
    await db.delete(target)
    await db.commit()
    await audit_service.audit(
        request, user, "user_mgmt", target_type="user", target_id=str(target.id),
        detail={"op": "delete", "username": target.username},
    )
    return Response(status_code=204)
