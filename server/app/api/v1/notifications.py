"""通知投递记录（2026-10-26）：回答「这条报警到底发出去没有」。

- 成功即时发送、失败补发、死信统一落 notification_outbox（sent/pending/sending/dead）
- 本接口只读 operator/admin；渠道 URL 仅回显 host，不泄漏 path/token/密钥
"""
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_operator
from app.db.base import get_db
from app.db.models import NotificationOutbox, User
from app.services import project_service
from app.services.notify import _open_channel

router = APIRouter(tags=["notifications"])

_KIND_LABEL = {
    "webhook": "Webhook",
    "dingtalk": "钉钉",
    "wecom": "企业微信",
    "email": "邮件",
    "smtp": "邮件",
}


def _channel_label(channel: dict) -> str:
    kind = str(channel.get("kind") or "")
    label = _KIND_LABEL.get(kind, kind or "渠道")
    url = str(channel.get("url") or "")
    host = ""
    if url:
        try:
            host = urlparse(url).hostname or ""
        except ValueError:
            host = ""
    return f"{label} · {host}" if host else label


def _row_out(row: NotificationOutbox) -> dict:
    try:
        channel = _open_channel(row.channel_json)
    except Exception:  # noqa: BLE001 - 坏行/密钥丢失时只显示类型
        channel = {"kind": row.channel_kind}
    payload = row.payload_json if isinstance(row.payload_json, dict) else {}
    rec = payload.get("rec") if isinstance(payload.get("rec"), dict) else {}
    return {
        "id": row.id,
        "alarmId": row.alarm_id,
        "event": row.event,
        "channelKind": row.channel_kind,
        "channelLabel": _channel_label(channel),
        "status": row.status,
        "attempts": row.attempts,
        "lastError": row.last_error,
        "message": rec.get("message"),
        "level": rec.get("level"),
        "createdAt": row.created_at,
        "sentAt": row.sent_at,
    }


@router.get("/projects/{project_id}/notifications/deliveries")
async def list_deliveries(
    project_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    status: str | None = Query(default=None),
    _user: User = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """最近通知投递（operator/admin）：sent/pending/sending/dead 全量，时间倒序。"""
    project = await project_service.get_project(db, project_id)
    stmt = (
        select(NotificationOutbox)
        .where(NotificationOutbox.project_id == project.id)
        .order_by(NotificationOutbox.created_at.desc(), NotificationOutbox.id.desc())
        .limit(limit)
    )
    if status:
        stmt = stmt.where(NotificationOutbox.status == status)
    rows = (await db.execute(stmt)).scalars().all()
    return {"items": [_row_out(r) for r in rows]}
