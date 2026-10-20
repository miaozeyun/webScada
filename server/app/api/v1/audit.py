"""审计日志查询接口（M8，契约 §4.4）：admin 专属，按 createdAt 倒序。"""
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.db.base import get_db
from app.db.models import AuditLog, User
from app.schemas.user import AuditLogListOut, AuditLogOut

router = APIRouter(prefix="/audit-logs", tags=["audit"])


@router.get("", response_model=AuditLogListOut)
async def list_audit_logs(
    userId: uuid.UUID | None = None,
    action: str | None = None,
    targetType: str | None = None,
    targetId: str | None = None,
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = None,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AuditLogListOut:
    base = select(AuditLog)
    if userId is not None:
        base = base.where(AuditLog.user_id == userId)
    if action:
        base = base.where(AuditLog.action == action)
    if targetType:
        base = base.where(AuditLog.target_type == targetType)
    if targetId:
        base = base.where(AuditLog.target_id == targetId)
    if from_ is not None:
        base = base.where(AuditLog.created_at >= from_)
    if to is not None:
        base = base.where(AuditLog.created_at <= to)

    total = await db.scalar(select(func.count()).select_from(base.subquery())) or 0
    items = (
        await db.scalars(
            # createdAt 倒序（§4.4）；id 倒序作稳定次序键（同秒多条不翻页抖动）
            base.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
    ).all()
    return AuditLogListOut(
        total=int(total),
        page=page,
        size=size,
        items=[
            AuditLogOut(
                id=r.id,
                userId=str(r.user_id) if r.user_id is not None else None,
                username=r.username,
                action=r.action,
                targetType=r.target_type,
                targetId=r.target_id,
                detail=r.detail,
                ip=r.ip,
                createdAt=r.created_at,
            )
            for r in items
        ],
    )
