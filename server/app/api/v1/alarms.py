"""报警接口（M8 重写，契约 §4.1 / 03 §2.7）：列表过滤、单行状态机 ack、废弃别名兼容。

- GET  /projects/{id}/alarms                 列表（status 缺省=未恢复集合；variableKey 前缀匹配）
- POST /projects/{id}/alarms/{alarmId}/ack   operator/admin；幂等；广播 alarmAck；落审计 alarm_ack
- GET  /projects/{id}/alarm-records          废弃别名（委托同实现）
- POST /projects/{id}/alarm-records          旧前端上报兼容：active/recovered → trigger/clear
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request
from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_operator
from app.core.errors import AppError
from app.db.base import get_db
from app.db.models import AlarmRecord, Project, User
from app.schemas.alarm import AckBody, AckOut, AlarmOut, AlarmRecordIn
from app.services import alarm_service, project_service

router = APIRouter(tags=["alarms"])

_VALID_STATUS = ("triggered", "acked", "cleared")
_VALID_LEVEL = ("info", "warn", "critical")


def _aware(dt: datetime) -> datetime:
    """ISO 入参无时区时按 UTC（契约：时间 REST=ISO8601 UTC）。"""
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def _ack_usernames(db: AsyncSession, rows: list[AlarmRecord]) -> dict:
    """批量取确认人 username（AlarmOut.ackedBy 展示口径）。"""
    ids = {r.acked_by for r in rows if r.acked_by is not None}
    if not ids:
        return {}
    rows_u = (await db.execute(select(User).where(User.id.in_(ids)))).scalars().all()
    return {u.id: u.username for u in rows_u}


async def _list_impl(
    db: AsyncSession,
    project: Project,
    status: str,
    level: str | None,
    variableKey: str | None,
    from_: datetime | None,
    to: datetime | None,
    page: int,
    size: int,
) -> dict:
    statuses = [s.strip() for s in (status or "").split(",") if s.strip()]
    for s in statuses:
        if s not in _VALID_STATUS:
            raise AppError("validation_error", f"status 取值非法：{s}（可选 {_VALID_STATUS}）", 422)
    if level is not None and level not in _VALID_LEVEL:
        raise AppError("validation_error", f"level 取值非法（可选 {_VALID_LEVEL}）", 422)

    q = select(AlarmRecord).where(AlarmRecord.project_id == project.id)
    if statuses:
        q = q.where(AlarmRecord.status.in_(statuses))
    if level:
        q = q.where(AlarmRecord.level == level)
    if variableKey:
        # 03 §2.7：前缀匹配。LIKE 通配符先转义，防用户输入 %/_ 改变匹配语义
        escaped = variableKey.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
        q = q.where(AlarmRecord.variable_key.like(f"{escaped}%", escape="\\"))
    if from_ is not None:
        q = q.where(AlarmRecord.triggered_at >= _aware(from_))
    if to is not None:
        q = q.where(AlarmRecord.triggered_at <= _aware(to))

    total = await db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = (
        await db.execute(
            q.order_by(AlarmRecord.triggered_at.desc(), AlarmRecord.id.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
    ).scalars().all()
    names = await _ack_usernames(db, list(rows))
    items = [
        AlarmOut(
            id=r.id,
            ruleId=r.rule_id,
            variableKey=r.variable_key,
            level=r.level,
            message=r.message,
            value=r.value,
            status=r.status,
            triggeredAt=r.triggered_at,
            ackedAt=r.acked_at,
            ackedBy=names.get(r.acked_by),
            ackedNote=r.acked_note,
            clearedAt=r.cleared_at,
        )
        for r in rows
    ]
    return {"total": int(total), "page": page, "size": size, "items": items}


@router.get("/projects/{project_id}/alarms")
async def list_alarms(
    project_id: str,
    status: str = Query(default="triggered,acked"),
    level: str | None = Query(default=None),
    variableKey: str | None = Query(default=None),
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """报警列表（JWT 任意角色；分页信封契约 03 §1.4）。"""
    project = await project_service.get_project(db, project_id)
    return await _list_impl(db, project, status, level, variableKey, from_, to, page, size)


@router.post("/projects/{project_id}/alarms/{alarm_id}/ack", response_model=AckOut)
async def ack_alarm(
    project_id: str,
    alarm_id: int,
    body: AckBody,
    request: Request,
    user: User = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> AckOut:
    """报警确认（operator/admin；viewer 403）：状态机幂等，变更后广播 alarmAck 并落审计。"""
    project = await project_service.get_project(db, project_id)
    rec = await alarm_service.ack(db, project.id, alarm_id, user, body.note)
    # 审计（C 包 audit_service；未合入时打桩降级——惰性 import 跨包规约 §6.4）
    try:
        from app.services import audit_service

        await audit_service.audit(
            request,
            user,
            "alarm_ack",
            target_type="alarm",
            target_id=str(alarm_id),
            detail={"project_id": str(project.id), "rule_id": rec.rule_id, "status": rec.status},
        )
    except ImportError:
        logger.info("audit_service 未合入（C 包），alarm_ack 审计跳过（打桩降级）")
    return AckOut(
        id=rec.id,
        status=rec.status,
        ackedAt=rec.acked_at,
        ackedBy=str(user.id),  # 契约示例口径：ack 出参 ackedBy 为 user id 串
        ackedNote=rec.acked_note,
    )


@router.get("/projects/{project_id}/alarm-records")
async def list_alarm_records_alias(
    project_id: str,
    status: str = Query(default="triggered,acked"),
    level: str | None = Query(default=None),
    variableKey: str | None = Query(default=None),
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """废弃别名（03 §2.7）：与 GET /alarms 同实现，前端一律改用新路径。"""
    project = await project_service.get_project(db, project_id)
    return await _list_impl(db, project, status, level, variableKey, from_, to, page, size)


@router.post("/projects/{project_id}/alarm-records", status_code=201)
async def add_alarm_record_compat(
    project_id: str,
    body: AlarmRecordIn,
    _user: User = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> None:
    """旧前端上报兼容（M8 前端已停用）：active/recovered 上报映射状态机 trigger/clear。

    operator/admin 门槛（终审 #5：viewer 不得伪造报警记录；兼容端点同样过 RBAC）。
    """
    project = await project_service.get_project(db, project_id)
    now = datetime.now(timezone.utc)
    if body.status == "recovered":
        await alarm_service.clear(db, project.id, body.ruleId, now)
    else:
        snapshot = {
            "id": body.ruleId,
            "variableKey": body.variableKey,
            "level": body.level,
            "message": body.message,
        }
        await alarm_service.trigger(db, project.id, snapshot, body.value, now)
    return None
