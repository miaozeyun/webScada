"""分享链接接口（M6 快照方案 G5；M8 角色收敛与审计见契约 §4.7/§5；出参对齐 03 §2.6）。

- POST /projects/{id}/shares         创建（operator/admin，§4.7）
- GET  /projects/{id}/shares         列表（operator/admin；lastAccessAt 供泄露排查，03 §2.6）
- POST /shares/{token}/refresh       刷新快照为当前工程 doc，并广播 reload（M8 新增）
- GET  /shares/{token}               公开访问（无鉴权，校验撤销/过期）
- DELETE /shares/{token}             撤销（operator/admin，§4.7）

M8 终审 #3：撤销/过期即时生效——revoke 与过期路径向该 token 全部在线 share 连接
推 error(SHARE_REVOKED/SHARE_EXPIRED) + close(4000)（经惰性 import ws_manager，降级不阻断）。
"""
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request
from loguru import logger
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_operator
from app.core.config import settings
from app.core.errors import AppError
from app.db.base import get_db
from app.db.models import Project, ShareLink, User
from app.schemas.share import ShareCreate, ShareDoc, ShareItem, ShareOut, ShareRefreshOut
from app.services import audit_service, project_service
from app.utils import sanitize as sz

router = APIRouter(tags=["shares"])


def _share_url(request: Request, token: str) -> str:
    """契约 §2.6 url 出参：前端分享路由 /s/{token}。

    优先 PUBLIC_BASE_URL（反代/非 80 端口部署的唯一可靠来源）；未配置时按请求推导。
    注意 nginx 的 Host 头若只传 $host 会丢端口，compose 已改为 $http_host。
    """
    base = settings.PUBLIC_BASE_URL.strip() or str(request.base_url)
    return f"{base.rstrip('/')}/s/{token}"


def _share_snapshot(project: Project) -> dict:
    """分享快照：在凭证脱敏之上剔除数据源连接配置/通知渠道/寄存器地址（匿名可见）。"""
    return sz.sanitize_doc_for_share(project.doc)


def _is_expired(link: ShareLink) -> bool:
    """过期判定：expires_at 为 None 永不过期；SQLite 读回 naive datetime 时按 UTC 口径。"""
    if link.expires_at is None:
        return False
    exp = link.expires_at if link.expires_at.tzinfo else link.expires_at.replace(tzinfo=timezone.utc)
    return exp <= datetime.now(timezone.utc)


async def _kick_share_ws(token: str, code: str, message: str) -> None:
    """该 token 全部在线 share 连接推 error 帧 + close(4000)（03 §2.6：撤权/过期即时生效）。

    惰性 import ws_manager（契约 §6.4 跨包规约）：A 未合入/无运行态时降级，不阻断主流程。
    """
    try:
        from app.services import ws_manager

        await ws_manager.close_share_token(token, code, message)
    except Exception as exc:  # noqa: BLE001 - 未合入/无在线连接：降级为下次握手拒绝
        logger.warning("分享连接断开广播失败（降级）token={} code={} : {}", token, code, exc)


def _resolve_expires_at(body: ShareCreate, now: datetime) -> datetime | None:
    """expiresAt 优先；未传时兼容旧 expiresHours（now+hours）；均缺省 = 永不过期。"""
    if body.expiresAt is not None:
        return body.expiresAt
    if body.expiresHours:
        return now + timedelta(hours=body.expiresHours)
    return None


@router.post("/projects/{project_id}/shares", response_model=ShareOut, status_code=201)
async def create_share(
    project_id: str,
    body: ShareCreate,
    request: Request,
    user: User = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> ShareOut:
    project = await project_service.get_project(db, project_id)
    now = datetime.now(timezone.utc)
    link = ShareLink(
        project_id=project.id,
        token=secrets.token_urlsafe(24),
        # 快照冻结当前脱敏 doc（G6：凭证恒为空）
        doc_snapshot=_share_snapshot(project),
        expires_at=_resolve_expires_at(body, now),
        refreshed_at=now,
    )
    db.add(link)
    await db.commit()
    await db.refresh(link)
    await audit_service.audit(
        request, user, "share_create", target_type="share", target_id=link.token,
        detail={"projectId": str(project.id), "projectName": project.name,
                "expiresAt": link.expires_at.isoformat() if link.expires_at else None},
    )
    return ShareOut(
        token=link.token, url=_share_url(request, link.token),
        expiresAt=link.expires_at, revokedAt=link.revoked_at, createdAt=link.created_at,
        refreshedAt=link.refreshed_at,
    )


@router.get("/projects/{project_id}/shares")
async def list_shares(
    project_id: str,
    request: Request,
    _user: User = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """分享链接列表（03 §2.6）：含已撤销记录（revokedAt 供排查），createdAt 倒序。"""
    project = await project_service.get_project(db, project_id)
    rows = (
        await db.execute(
            select(ShareLink)
            .where(ShareLink.project_id == project.id)
            .order_by(ShareLink.created_at.desc())
        )
    ).scalars().all()
    return {
        "items": [
            ShareItem(
                token=link.token, url=_share_url(request, link.token),
                expiresAt=link.expires_at, revokedAt=link.revoked_at,
                createdAt=link.created_at, lastAccessAt=link.last_access_at,
                refreshedAt=link.refreshed_at,
            )
            for link in rows
        ]
    }


@router.post("/shares/{token}/refresh", response_model=ShareRefreshOut)
async def refresh_share(
    token: str,
    request: Request,
    user: User = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> ShareRefreshOut:
    """刷新快照为当前工程 doc（操作后在线分享页收到 reload 帧重取）。

    广播经惰性 import ws_manager（A 包；未合入/未启动时 try/except 降级为
    "下次连接取新快照"，不阻断刷新本身）——契约 §6.4 跨包调用规约。
    """
    link = (await db.execute(select(ShareLink).where(ShareLink.token == token))).scalar_one_or_none()
    if link is None or link.revoked_at is not None:
        raise AppError("not_found", "分享链接不存在或已撤销", 404)
    if _is_expired(link):
        # 过期路径：在线连接一并踢下线（终审 #3：撤权/过期即时生效）
        await _kick_share_ws(token, "SHARE_EXPIRED", "分享链接已过期，连接即将关闭")
        raise AppError("not_found", "分享链接已过期", 404)
    project = await db.get(Project, link.project_id)
    if project is None:
        raise AppError("not_found", "工程已删除", 404)

    link.doc_snapshot = _share_snapshot(project)
    link.refreshed_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(link)

    try:
        from app.services import ws_manager  # 惰性 import：A 包交付前模块可能缺席

        await ws_manager.broadcast_reload(token)
    except Exception as exc:  # A 未合入 / 无运行态：降级不阻断
        logger.warning("分享 refresh 广播 reload 失败（降级为下次连接生效）token={} : {}", token, exc)

    # refresh 不落审计：action 枚举（§6.3）无对应项，快照刷新非安全敏感操作
    return ShareRefreshOut(token=link.token, refreshedAt=datetime.now(timezone.utc))


@router.get("/shares/{token}", response_model=ShareDoc)
async def get_share(token: str, db: AsyncSession = Depends(get_db)) -> ShareDoc:
    link = (await db.execute(select(ShareLink).where(ShareLink.token == token))).scalar_one_or_none()
    if link is None or link.revoked_at is not None:
        raise AppError("not_found", "分享链接不存在或已撤销", 404)
    if _is_expired(link):
        # 过期路径：在线连接一并踢下线（终审 #3）
        await _kick_share_ws(token, "SHARE_EXPIRED", "分享链接已过期，连接即将关闭")
        raise AppError("not_found", "分享链接已过期", 404)

    await db.execute(update(ShareLink).where(ShareLink.id == link.id).values(last_access_at=datetime.now(timezone.utc)))
    await db.commit()

    project = await db.get(Project, link.project_id)
    if project is None:
        raise AppError("not_found", "工程已删除", 404)
    # 公开出参收窄到契约字段（03 §2.6）：projectId/createdAt/doc；不含工程名等管理面信息
    return ShareDoc(projectId=str(link.project_id), createdAt=link.created_at, doc=link.doc_snapshot)


@router.delete("/shares/{token}", status_code=204)
async def revoke_share(
    token: str,
    request: Request,
    user: User = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> None:
    link = (await db.execute(select(ShareLink).where(ShareLink.token == token))).scalar_one_or_none()
    if link is None:
        raise AppError("not_found", "分享链接不存在", 404)
    await db.execute(update(ShareLink).where(ShareLink.id == link.id).values(revoked_at=datetime.now(timezone.utc)))
    await db.commit()
    await audit_service.audit(
        request, user, "share_revoke", target_type="share", target_id=token,
        detail={"projectId": str(link.project_id)},
    )
    # 撤销即时生效：该 token 全部在线分享连接踢下线（03 §2.6：error(SHARE_REVOKED) 后关闭）
    await _kick_share_ws(token, "SHARE_REVOKED", "分享链接已撤销，连接即将关闭")
