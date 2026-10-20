"""分享链接接口（M6，快照方案 G5）：创建即冻结脱敏 doc；token 公开只读访问。

03-接口清单 §2.6：
- POST /projects/{id}/shares     创建（鉴权）
- GET  /shares/{token}           公开访问（无鉴权，校验撤销/过期）
- DELETE /shares/{token}         撤销（鉴权）
"""
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.errors import AppError
from app.db.base import get_db
from app.db.models import Project, ShareLink, User
from app.schemas.share import ShareCreate, ShareDoc, ShareOut
from app.services import project_service

router = APIRouter(tags=["shares"])


@router.post("/projects/{project_id}/shares", response_model=ShareOut, status_code=201)
async def create_share(
    project_id: str,
    body: ShareCreate,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ShareOut:
    project = await project_service.get_project(db, project_id)
    now = datetime.now(timezone.utc)
    link = ShareLink(
        project_id=project.id,
        token=secrets.token_urlsafe(24),
        # 快照冻结当前脱敏 doc（G6：凭证恒为空）
        doc_snapshot=project_service.doc_for_api(project),
        expires_at=now + timedelta(hours=body.expiresHours) if body.expiresHours else None,
    )
    db.add(link)
    await db.commit()
    await db.refresh(link)
    return ShareOut(token=link.token, expiresAt=link.expires_at, createdAt=link.created_at)


@router.get("/shares/{token}", response_model=ShareDoc)
async def get_share(token: str, db: AsyncSession = Depends(get_db)) -> ShareDoc:
    link = (await db.execute(select(ShareLink).where(ShareLink.token == token))).scalar_one_or_none()
    if link is None or link.revoked_at is not None:
        raise AppError("not_found", "分享链接不存在或已撤销", 404)
    if link.expires_at is not None and link.expires_at <= datetime.now(timezone.utc):
        raise AppError("not_found", "分享链接已过期", 404)

    await db.execute(update(ShareLink).where(ShareLink.id == link.id).values(last_access_at=datetime.now(timezone.utc)))
    await db.commit()

    project = await db.get(Project, link.project_id)
    if project is None:
        raise AppError("not_found", "工程已删除", 404)
    return ShareDoc(projectName=project.name, doc=link.doc_snapshot)


@router.delete("/shares/{token}", status_code=204)
async def revoke_share(
    token: str,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    link = (await db.execute(select(ShareLink).where(ShareLink.token == token))).scalar_one_or_none()
    if link is None:
        raise AppError("not_found", "分享链接不存在", 404)
    await db.execute(update(ShareLink).where(ShareLink.id == link.id).values(revoked_at=datetime.now(timezone.utc)))
    await db.commit()
